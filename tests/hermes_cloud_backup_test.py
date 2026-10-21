#!/usr/bin/env python3
"""Bounded cloud routing/failure checks: real bundle verifier, fake rclone, no network."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest import mock

import hermes_backup_bundle_test as bundles

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/hermes_cloud_backup.py"
CONFIG = """[mailru-hermes]
type = webdav
url = https://webdav.cloud.mail.ru/
vendor = other
user = fixture-user
pass = fixture-obscured-secret

[hermes-backup]
type = crypt
remote = mailru-hermes:Hermes-Backups/crypt-v1
filename_encryption = standard
directory_name_encryption = true
password = fixture-obscured-secret
password2 = fixture-obscured-salt
"""


class CloudTest(unittest.TestCase):
    def setUp(self):
        self.fixture = bundles.BundleTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.base = self.fixture.base
        self.archive = self.fixture.bundle()
        self.archive.chmod(0o600)
        self.config = self.base / "upload.conf"
        self.recovery = self.base / "recovery.conf"
        for path in (self.config, self.recovery):
            path.write_text(CONFIG)
            path.chmod(0o600)
        self.log = self.base / "rclone.jsonl"
        self.remote = self.base / "cloud-object"
        self.stage = self.base / "temp"
        self.stage.mkdir(mode=0o700)
        fake = self.fixture.bin / "rclone"
        fake.write_text('''#!/usr/bin/env python3
import json, os, pathlib, shutil, sys
args = sys.argv[1:]
assert args[0] in ('copy', 'copyto')
assert '--immutable' in args and '--size-only' in args
assert '--config' in args
assert not any(k.upper().startswith('RCLONE_') for k in os.environ)
config = pathlib.Path(args[args.index('--config') + 1])
assert config.stat().st_mode & 0o077 == 0
assert config.parent.stat().st_mode & 0o077 == 0
src, dst = args[1:3]
upload = args[0] == 'copy'
if upload:
    assert dst == 'hermes-backup:full/'
    assert pathlib.Path(src).is_dir()
    assert [p.name for p in pathlib.Path(src).iterdir()] == ['bundle.tar.gz']
    src = str(pathlib.Path(src) / 'bundle.tar.gz')
else:
    assert src == 'hermes-backup:full/bundle.tar.gz'
assert config.name == ('upload.conf' if upload else 'recovery.conf')
with open(os.environ['CLOUD_LOG'], 'a') as log:
    log.write(json.dumps({'upload': upload, 'args': args}) + '\\n')
mode = os.environ.get('CLOUD_FAIL')
if mode == ('upload' if upload else 'download'):
    print('fixture-obscured-secret', file=sys.stderr)
    sys.exit(7)
remote = pathlib.Path(os.environ['CLOUD_OBJECT'])
if upload:
    if remote.exists():
        if remote.stat().st_size != pathlib.Path(src).stat().st_size: sys.exit(8)
    else:
        shutil.copyfile(src, remote)
else:
    shutil.copyfile(remote, dst)
    if mode == 'corrupt':
        p = pathlib.Path(dst)
        data = p.read_bytes()
        p.write_bytes(bytes([data[0] ^ 1]) + data[1:])
''')
        fake.chmod(0o755)
        self.env = dict(self.fixture.env, HERMES_BACKUP_FILE=str(self.archive),
                        HERMES_CONFIRM_CLOUD_UPLOAD="1", HERMES_CLOUD_CONFIG=str(self.config),
                        HERMES_CLOUD_RECOVERY_CONFIG=str(self.recovery),
                        CLOUD_LOG=str(self.log), CLOUD_OBJECT=str(self.remote), TMPDIR=str(self.stage),
                        RCLONE_CONFIG="/wrong", RCLONE_CRYPT_REMOTE="/plaintext",
                        RCLONE_PASSWORD_COMMAND="should-not-run", RCLONE_DUMP="bodies",
                        RCLONE_CONFIG_HERMES_BACKUP_TYPE="local")

    def run_cloud(self, **overrides):
        result = subprocess.run([sys.executable, str(SCRIPT)], env=dict(self.env, **overrides),
                                capture_output=True)
        self.assertNotIn(b"fixture-obscured-secret", result.stdout + result.stderr)
        self.assertEqual(list(self.stage.iterdir()), [], "private temporary files must be cleaned")
        return result

    def test_success_and_repeat_are_verified_without_overwriting(self):
        for _ in range(2):
            result = self.run_cloud()
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt["sha256"], hashlib.sha256(self.archive.read_bytes()).hexdigest())
            self.assertTrue(receipt["recovery_config_used"])
            self.assertTrue(receipt["bundle_integrity_verified"])
            self.assertFalse(receipt["state_restored"])
            self.assertFalse(receipt["restored_runtime_verified"])
        events = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual([e["upload"] for e in events], [True, False, True, False])
        self.assertEqual(self.config.read_text(), CONFIG)
        self.assertEqual(self.recovery.read_text(), CONFIG)
        self.assertEqual(self.archive.read_bytes(), self.remote.read_bytes())

    def test_confirmation_and_explicit_archive_required(self):
        for overrides in ({"HERMES_CONFIRM_CLOUD_UPLOAD": ""}, {"HERMES_BACKUP_FILE": ""},
                          {"HERMES_BACKUP_FILE": "relative.tar.gz"}):
            with self.subTest(overrides=overrides):
                self.assertNotEqual(self.run_cloud(**overrides).returncode, 0)
                self.assertFalse(self.log.exists())

    def test_wrong_config_is_rejected_before_external_command(self):
        bad_configs = [CONFIG.replace("type = crypt", "type = local"),
                       CONFIG.replace("https://", "http://"),
                       CONFIG.replace("webdav.cloud.mail.ru", "example.org"),
                       CONFIG.replace("filename_encryption = standard", "filename_encryption = off"),
                       CONFIG.replace("Hermes-Backups/crypt-v1", "elsewhere"),
                       CONFIG + "server_side_across_configs = true\n",
                       CONFIG + "[extra]\ntype = local\n",
                       "fixture-obscured-secret malformed config"]
        for contents in bad_configs:
            with self.subTest(contents=contents):
                self.config.write_text(contents)
                self.assertNotEqual(self.run_cloud().returncode, 0)
                self.assertFalse(self.log.exists())

    def test_missing_mismatched_or_non_independent_recovery_config(self):
        self.recovery.write_text(CONFIG.replace("fixture-obscured-salt", "different-salt"))
        self.assertNotEqual(self.run_cloud().returncode, 0)
        self.recovery.unlink()
        self.assertNotEqual(self.run_cloud().returncode, 0)
        self.assertNotEqual(self.run_cloud(HERMES_CLOUD_RECOVERY_CONFIG=str(self.config)).returncode, 0)
        self.assertFalse(self.log.exists())

    def test_private_regular_inputs_required(self):
        for path in (self.archive, self.config, self.recovery):
            with self.subTest(path=path.name):
                path.chmod(0o644)
                self.assertNotEqual(self.run_cloud().returncode, 0)
                path.chmod(0o600)
                self.assertFalse(self.log.exists())
        link = self.base / "link.tar.gz"
        link.symlink_to(self.archive)
        self.assertNotEqual(self.run_cloud(HERMES_BACKUP_FILE=str(link)).returncode, 0)
        directory = self.base / "directory.tar.gz"
        directory.mkdir()
        self.assertNotEqual(self.run_cloud(HERMES_BACKUP_FILE=str(directory)).returncode, 0)
        self.assertFalse(self.log.exists())

    def test_corrupt_or_personal_bundle_never_uploaded(self):
        self.archive.write_bytes(b"not a bundle")
        self.assertNotEqual(self.run_cloud().returncode, 0)
        self.archive = self.fixture.bundle(scope="personal")
        self.assertNotEqual(self.run_cloud().returncode, 0)
        self.assertFalse(self.log.exists())

    def test_failures_do_not_claim_verified_result(self):
        for failure in ("upload", "download", "corrupt"):
            with self.subTest(failure=failure):
                result = self.run_cloud(CLOUD_FAIL=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")
                events = [json.loads(line) for line in self.log.read_text().splitlines()]
                self.assertEqual(len(events), 1 if failure == "upload" else 2)
                self.log.unlink()
        self.assertTrue(self.remote.exists(), "do not delete the remote on verification failure")

    def test_existing_conflicting_object_is_preserved(self):
        for data in (b"previous copy", b"x" * self.archive.stat().st_size):
            self.remote.write_bytes(data)
            result = self.run_cloud()
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b"")
            self.assertEqual(self.remote.read_bytes(), data)

    def test_real_rclone_preserves_existing_objects(self):
        real_rclone = shutil.which("rclone")
        if not real_rclone:
            self.skipTest("rclone unavailable: native local crypt regression not exercised")
        env = {k: v for k, v in self.env.items() if not k.upper().startswith("RCLONE_")}
        env["PATH"] = os.environ["PATH"]  # Real rclone, never the bounded CLI double.
        key = subprocess.run([real_rclone, "obscure", "-"], input=b"harmless-local-test-key",
                             env=env, capture_output=True, check=True).stdout.decode().strip()
        encrypted = self.base / "encrypted"
        contents = ("[local-crypt]\ntype = crypt\nremote = " + str(encrypted)
                    + "\nfilename_encryption = standard\ndirectory_name_encryption = true\npassword = " + key + "\n")
        for path in (self.config, self.recovery):
            path.write_text(contents)
        spec = importlib.util.spec_from_file_location("cloud_helper", SCRIPT)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        original = self.archive.read_bytes()
        # Change only destination validation at this seam: the real orchestrator,
        # verifier and rclone run against an offline local crypt backend.
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(helper, "REMOTE", "local-crypt:full/"), \
                mock.patch.object(helper, "read_config", return_value=()), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            mask = os.umask(0o077)
            try:
                helper.execute()
                helper.execute()  # Same bytes remain verifiable on retry.
                # A second valid full bundle has the same basename but a different size.
                (self.fixture.root / "data/extra").write_text("another fixture" * 100)
                self.fixture.bundle()
                self.assertNotEqual(self.archive.stat().st_size, len(original))
                with self.assertRaises(helper.CloudError):
                    helper.execute()
            finally:
                os.umask(mask)
        recovered = self.base / "native-readback"
        result = subprocess.run([real_rclone, "copyto", "local-crypt:full/bundle.tar.gz",
                                 str(recovered), "--config", str(self.recovery)],
                                env=env, capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(recovered.read_bytes(), original, "existing encrypted object was overwritten")
        self.assertEqual(list(self.stage.iterdir()), [])

    def test_real_task_routes_to_cloud_helper(self):
        if not shutil.which("task"):
            self.skipTest("Go Task unavailable")
        result = subprocess.run(["task", "--taskfile", str(ROOT / "Taskfile.yml"),
                                 "backup:hermes:cloud"], env=self.env, cwd=ROOT, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertTrue(json.loads(result.stdout)["bundle_integrity_verified"])


if __name__ == "__main__":
    unittest.main()
