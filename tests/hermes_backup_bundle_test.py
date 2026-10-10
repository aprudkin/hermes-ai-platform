#!/usr/bin/env python3
"""Offline recovery bundle contracts; Docker is bounded, tar/file I/O are real."""
import hashlib
import gzip
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
import fcntl
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/hermes_backup_bundle.py"
IMAGE_ID = "sha256:" + "a" * 64


class BundleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / "hermes"
        for name in ("app", "data", "data/profiles/manager"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        for name in ("app/docker-compose.yml", "app/gateway.env", "data/config.yaml",
                     "data/profiles/manager/SOUL.md"):
            (self.root / name).write_text("secret-fixture-content\n")
        (self.root / "data/profiles/manager/python3").symlink_to("/usr/bin/python3")
        self.guide = self.base / "guide.md"
        self.guide.write_bytes(b"# Exact offline restore guide\r\n")
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.log = self.base / "events"
        self.container = {
            "Id": "b" * 64, "Name": "/hermes", "Image": IMAGE_ID,
            "State": {"Running": True, "Paused": False},
            "Config": {"Image": "nousresearch/hermes-agent:v1", "Env": ["TOKEN=secret-value$LITERAL${KEEP}"],
                       "Cmd": ["hermes", "-p", "manager", "gateway", "run"],
                       "Entrypoint": ["/entrypoint.sh"], "User": "10000:10000",
                       "WorkingDir": "/opt", "Healthcheck": {"Test": ["CMD", "true"],
                       "Interval": 15000000000, "Timeout": 5000000000, "Retries": 12,
                       "StartPeriod": 60000000000}},
            "Mounts": [{"Type": "bind", "Source": str(self.root / "data"),
                        "Destination": "/opt/data", "RW": True, "Propagation": "rprivate"}],
            "HostConfig": {"NetworkMode": "host", "RestartPolicy": {"Name": "unless-stopped", "MaximumRetryCount": 0},
                           "LogConfig": {"Type": "json-file", "Config": {"max-size": "10m"}},
                           "Privileged": False, "ReadonlyRootfs": False, "Memory": 123456,
                           "NanoCpus": 1000000000},
        }
        layer = io.BytesIO()
        with tarfile.open(fileobj=layer, mode="w") as archive:
            self.add_bytes(archive, "opt/runtime.py", b"installed-runtime")
        self.layer = layer.getvalue()
        self.image_config = json.dumps({"architecture": "amd64", "os": "linux", "rootfs": {
            "type": "layers", "diff_ids": ["sha256:" + hashlib.sha256(self.layer).hexdigest()]}}).encode()
        self.real_image_id = "sha256:" + hashlib.sha256(self.image_config).hexdigest()
        self.container["Image"] = self.real_image_id
        self.image = {"Id": self.real_image_id, "RepoTags": ["nousresearch/hermes-agent:v1"],
                      "RepoDigests": ["nousresearch/hermes-agent@sha256:" + "c" * 64],
                      "Os": "linux", "Architecture": "amd64", "Size": len(self.layer)}
        self.fixture = self.base / "fixture.json"
        self.layer_changes = []
        self.save_fixture()
        self.image_tar = self.base / "saved-image.tar"
        with tarfile.open(self.image_tar, "w") as archive:
            self.add_bytes(archive, self.real_image_id[7:] + ".json", self.image_config)
            self.add_bytes(archive, "layer/layer.tar", self.layer)
            self.add_bytes(archive, "manifest.json", json.dumps([{
                "Config": self.real_image_id[7:] + ".json", "RepoTags": self.image["RepoTags"], "Layers": ["layer/layer.tar"]}]).encode())
        docker = self.bin / "docker"
        docker.write_text('''#!/usr/bin/env python3
import json, os, pathlib, shutil, sys, signal
args = sys.argv[1:]
log = pathlib.Path(os.environ['EVENTS'])
with log.open('a') as f: f.write('docker ' + ' '.join(args) + '\\n')
data = json.loads(pathlib.Path(os.environ['FIXTURE']).read_text())
paused = pathlib.Path(os.environ['PAUSED'])
mode = os.environ.get('FAIL', '')
if args[:2] == ['image', 'inspect']:
    print(json.dumps([data['image']]))
elif args[:2] == ['image', 'save']:
    if mode == 'image': sys.exit(1)
    shutil.copyfile(os.environ['IMAGE_TAR'], args[args.index('--output') + 1])
elif args[0] == 'inspect':
    data['container']['State']['Paused'] = paused.exists()
    if mode == 'replacement' and paused.exists(): data['container']['Id'] = 'd' * 64
    print(json.dumps([data['container']]))
elif args[0] == 'diff':
    if mode == 'diff': print('C /opt/program.py')
    elif mode != 'late-diff' or paused.exists():
        for change in data.get('layer_changes', []): print(change)
elif args[0] == 'pause':
    paused.touch()
    if mode == 'pause': sys.exit(1)
    if mode == 'signal': os.kill(os.getppid(), signal.SIGTERM)
elif args[0] == 'unpause':
    if mode == 'unpause': sys.exit(1)
    paused.unlink(missing_ok=True)
else: sys.exit(8)
''')
        docker.chmod(0o755)
        # macOS has BSD tar: this narrow shim removes GNU-only metadata flags;
        # snapshot contents/ordering stay real. Linux runs the same real tar path.
        tar = self.bin / "tar"
        tar.write_text('''#!/usr/bin/env python3
import os, pathlib, sys
with pathlib.Path(os.environ['EVENTS']).open('a') as f: f.write('tar snapshot\\n')
if os.environ.get('FAIL') == 'snapshot': sys.exit(1)
args = sys.argv[1:]
if os.environ.get('GNU_TAR') != '1':
    args = [a for a in args if a not in ('--acls', '--xattrs', '--numeric-owner')]
os.execv(os.environ['REAL_TAR'], [os.environ['REAL_TAR']] + args)
''')
        tar.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        EVENTS=str(self.log), FIXTURE=str(self.fixture), IMAGE_TAR=str(self.image_tar),
                        PAUSED=str(self.base / "paused"), REAL_TAR=shutil.which("tar"), COPYFILE_DISABLE="1",
                        GNU_TAR="1" if b"GNU tar" in subprocess.check_output(["tar", "--version"]) else "0")

    def save_fixture(self):
        self.fixture.write_text(json.dumps({"container": self.container, "image": self.image,
                                           "layer_changes": self.layer_changes}))

    @staticmethod
    def add_bytes(archive, name, data):
        info = tarfile.TarInfo(name)
        info.size = len(data)
        info.mode = 0o600
        archive.addfile(info, io.BytesIO(data))

    def capture(self, fail="", low_space=False):
        program = subprocess.run([sys.executable, str(HELPER), "program", str(self.guide)], capture_output=True)
        self.assertEqual(program.returncode, 0, program.stderr.decode())
        if low_space:
            # Substitute the real disk-usage boundary, not capture behavior.
            prefix, suffix = program.stdout.rsplit(b"    sys.exit(main())", 1)
            program.stdout = prefix + b"    shutil.disk_usage = lambda path: type('Disk', (), {'free': 0})()\n    sys.exit(main())" + suffix
        result = subprocess.run([sys.executable, "-", "capture", str(self.root), "hermes"],
                                input=program.stdout, capture_output=True, env=dict(self.env, FAIL=fail))
        self.assertNotIn(b"secret-value", result.stderr)
        self.assertNotIn(b"secret-fixture", result.stderr)
        return result

    def bundle(self):
        result = self.capture()
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        path = self.base / "bundle.tar.gz"
        path.write_bytes(result.stdout)
        return path

    def verify(self, path, helper=HELPER):
        result = subprocess.run([sys.executable, str(helper), "verify", str(path)], capture_output=True)
        self.assertNotIn(b"secret-value", result.stdout + result.stderr)
        return result

    def rewrite_bundle(self, bundle, changes=None, omit=None, duplicate=None):
        target = self.base / "mutated.tar.gz"
        with tarfile.open(bundle) as source, tarfile.open(target, "w:gz") as dest:
            for member in source:
                if member.name == omit:
                    continue
                contents = source.extractfile(member).read()
                contents = (changes or {}).get(member.name, contents)
                self.add_bytes(dest, member.name, contents)
                if member.name == duplicate:
                    self.add_bytes(dest, member.name, contents)
        return target

    def test_bundle_layout_effective_config_and_embedded_verifier(self):
        path = self.bundle()
        verified = self.verify(path)
        self.assertEqual(verified.returncode, 0, verified.stderr.decode())
        with tarfile.open(path) as archive:
            self.assertEqual(set(archive.getnames()), {"manifest.json", "state.tar", "image.tar", "compose.restore.json",
                "RESTORE.md", "container-inspect.json", "image-inspect.json", "verify.py"})
            manifest = json.load(archive.extractfile("manifest.json"))
            self.assertEqual(manifest["format"], "hermes-recovery-bundle")
            self.assertEqual(manifest["version"], 1)
            self.assertEqual(manifest["source"]["profile"], "manager")
            service = json.load(archive.extractfile("compose.restore.json"))["services"]["hermes"]
            self.assertEqual(service["image"], "hermes-recovery:" + self.real_image_id[7:])
            self.assertEqual(service["pull_policy"], "never")
            self.assertEqual(service["volumes"], [{"type": "bind", "source": str(self.root / "data"), "target": "/opt/data", "read_only": False}])
            self.assertEqual(service["environment"], ["TOKEN=secret-value$$LITERAL$${KEEP}"])
            self.assertEqual(service["command"], ["hermes", "-p", "manager", "gateway", "run"])
            self.assertEqual(service["entrypoint"], ["/entrypoint.sh"])
            self.assertEqual(service["healthcheck"]["interval"], "15000000000ns")
            self.assertEqual(service["mem_limit"], 123456)
            self.assertEqual(service["cpus"], 1.0)
            self.assertEqual(archive.extractfile("RESTORE.md").read(), self.guide.read_bytes())
            helper = self.base / "verify.py"
            helper.write_bytes(archive.extractfile("verify.py").read())
            state = self.base / "state.tar"
            state.write_bytes(archive.extractfile("state.tar").read())
        self.assertEqual(helper.read_bytes(), HELPER.read_bytes())
        self.assertEqual(self.verify(path, helper).returncode, 0)
        extracted = self.base / "recovery"
        extracted.mkdir()
        subprocess.run([self.env['REAL_TAR'], "-xf", str(state), "-C", str(extracted)], check=True)
        self.assertEqual((extracted / "app/gateway.env").read_text(), "secret-fixture-content\n")
        self.assertTrue((extracted / "data/profiles/manager/SOUL.md").is_file())
        events = self.log.read_text().splitlines()
        save = next(i for i, event in enumerate(events) if event.startswith("docker image save"))
        pause = next(i for i, event in enumerate(events) if event.startswith("docker pause"))
        snapshot = events.index("tar snapshot")
        unpause = next(i for i, event in enumerate(events) if event.startswith("docker unpause"))
        self.assertLess(save, pause)
        self.assertLess(pause, snapshot)
        self.assertLess(snapshot, unpause)
        self.assertFalse((self.base / "paused").exists())
        self.assertEqual(list(self.root.glob(".hermes-backup-*")), [])

    def test_unsupported_mount_and_layer_changes_fail_without_pausing(self):
        for mutation in ("mount", "diff"):
            with self.subTest(mutation=mutation):
                if mutation == "mount":
                    self.container["Mounts"].append({"Type": "volume", "Destination": "/other"})
                    self.save_fixture()
                result = self.capture("diff" if mutation == "diff" else "")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")
                self.assertNotIn("docker pause", self.log.read_text())
                self.container["Mounts"] = self.container["Mounts"][:1]
                self.save_fixture()

    def test_unbacked_writable_layer_changes_fail_before_or_during_pause(self):
        for change in ('A', 'C', 'D'):
            for path in ('/srv/custom-app/main.py', '/app/config.json', '/etc/custom.conf', '/var/lib/custom.db'):
                for phase in ('', 'late-diff'):
                    with self.subTest(change=change, path=path, phase=phase):
                        self.log.write_text('')
                        self.layer_changes = [change + ' ' + path]
                        self.save_fixture()
                        result = self.capture(phase)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertEqual(result.stdout, b'')
                        self.assertFalse((self.base / 'paused').exists())
                        if phase:
                            self.assertIn('docker unpause', self.log.read_text())
                        else:
                            self.assertNotIn('docker pause', self.log.read_text())
        self.layer_changes = ['C /run', 'A /run/s6/service', 'D /tmp/runtime-file',
                              'C /var', 'C /var/tmp', 'A /var/tmp/runtime-file']
        self.save_fixture()
        self.assertEqual(self.capture().returncode, 0)

    def test_restore_preserves_custom_hostname_and_accepts_equivalent_path_order(self):
        self.container['HostConfig']['MaskedPaths'] = [
            '/proc/acpi', '/proc/asound', '/proc/interrupts', '/proc/kcore', '/proc/keys',
            '/proc/latency_stats', '/proc/sched_debug', '/proc/scsi', '/proc/timer_list',
            '/proc/timer_stats', '/sys/devices/virtual/powercap', '/sys/firmware']
        for hostname in (self.container['Id'][:12], 'custom-hermes-host'):
            with self.subTest(hostname=hostname):
                self.container['Config']['Hostname'] = hostname
                self.save_fixture()
                with tarfile.open(self.bundle()) as archive:
                    service = json.load(archive.extractfile('compose.restore.json'))['services']['hermes']
                    if hostname == self.container['Id'][:12]:
                        self.assertNotIn('hostname', service)
                    else:
                        self.assertEqual(service['hostname'], hostname)
        self.container['HostConfig']['MaskedPaths'] = ['/proc/acpi']
        self.save_fixture()
        self.assertNotEqual(self.capture().returncode, 0)

    def test_failures_cleanup_owned_pause_and_publish_nothing(self):
        for failure in ("image", "pause", "snapshot", "replacement", "unpause", "signal"):
            with self.subTest(failure=failure):
                self.log.write_text("")
                (self.base / "paused").unlink(missing_ok=True)
                result = self.capture(failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")
                if failure != "image":
                    self.assertIn("docker unpause", self.log.read_text())
                if failure != "unpause":
                    self.assertFalse((self.base / "paused").exists())
                self.assertEqual(list(self.root.glob(".hermes-backup-*")), [])

    def test_verifier_rejects_corruption_missing_and_duplicate_payloads(self):
        bundle = self.bundle()
        for name in ("state.tar", "image.tar", "compose.restore.json"):
            with self.subTest(name=name):
                self.assertNotEqual(self.verify(self.rewrite_bundle(bundle, {name: b"corrupt"})).returncode, 0)
                self.assertNotEqual(self.verify(self.rewrite_bundle(bundle, omit=name)).returncode, 0)
        self.assertNotEqual(self.verify(self.rewrite_bundle(bundle, duplicate="state.tar")).returncode, 0)
        truncated = self.base / "truncated.tar.gz"
        truncated.write_bytes(bundle.read_bytes()[:-35])
        self.assertNotEqual(self.verify(truncated).returncode, 0)
        legacy = self.base / "legacy.tar.gz"
        with tarfile.open(legacy, "w:gz") as archive:
            self.add_bytes(archive, "data/config.yaml", b"secret")
        self.assertNotEqual(self.verify(legacy).returncode, 0)


    def test_slow_stream_budget_starts_after_unpause_without_extending_snapshot(self):
        spec = importlib.util.spec_from_file_location('bundle', HELPER)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        helper.BUNDLE_SOURCE = HELPER.read_text()
        helper.RESTORE_GUIDE = self.guide.read_text()
        for elapsed, succeeds in ((31 * 60, True), (91 * 60, False)):
            with self.subTest(elapsed=elapsed):
                armed = [0]
                deadlines = []

                def alarm(seconds):
                    self.assertFalse((self.base / 'paused').exists())
                    armed[0] = seconds
                    deadlines.append(seconds)
                    return 0

                class SlowStream(io.BytesIO):
                    def write(stream, data):
                        if armed[0] and elapsed >= armed[0]:
                            helper.interrupted(helper.signal.SIGALRM, None)
                        return super().write(data)

                output = SlowStream()
                with mock.patch.dict(os.environ, self.env), \
                     mock.patch.object(helper.signal, 'signal'), \
                     mock.patch.object(helper.signal, 'alarm', side_effect=alarm), \
                     mock.patch.object(helper.sys, 'stdout', mock.Mock(buffer=output)), \
                     mock.patch.object(helper, 'run', wraps=helper.run) as commands:
                    if succeeds:
                        helper.capture(str(self.root), 'hermes')
                    else:
                        with self.assertRaises(helper.BundleError):
                            helper.capture(str(self.root), 'hermes')
                self.assertEqual(deadlines, [5400, 0])
                snapshots = [call for call in commands.call_args_list if call.args[0][0] == 'tar']
                self.assertEqual(len(snapshots), 1)
                self.assertEqual(snapshots[0].kwargs['timeout'], 300)
                self.assertFalse((self.base / 'paused').exists())
                self.assertEqual(list(self.root.glob('.hermes-backup-*')), [])
                if succeeds:
                    bundle = self.base / 'slow-stream.tar.gz'
                    bundle.write_bytes(output.getvalue())
                    helper.verify(bundle)

    def test_stream_after_unpause_does_not_stage_another_compressed_bundle(self):
        # Incompressible data keeps the child blocked on its stdout pipe while
        # we observe staging; this is synchronization, not a timing sleep.
        (self.root / 'data/stream-fixture.bin').write_bytes(os.urandom(2 * 1024 * 1024))
        program = subprocess.check_output([sys.executable, str(HELPER), "program", str(self.guide)])
        with subprocess.Popen([sys.executable, "-", "capture", str(self.root), "hermes"],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=self.env) as child:
            child.stdin.write(program)
            child.stdin.close()
            child.stdin = None
            first = child.stdout.read(1)
            self.assertEqual(first, b"\x1f")
            self.assertFalse((self.base / "paused").exists())
            self.assertIn("docker unpause", self.log.read_text())
            staged = [p.name for stage in self.root.glob('.hermes-backup-*') for p in stage.iterdir()]
            # Drain before assertions so a failing test cannot strand a writer.
            _, err = child.communicate(timeout=30)
            self.assertIn('state.tar', staged)
            self.assertIn('image.tar', staged)
            self.assertNotIn('bundle.tar.gz', staged)
            self.assertFalse(any(name.startswith('hermes-verify-') for name in staged))
            self.assertEqual(child.returncode, 0, err.decode())

    def test_disconnected_stream_removes_staging_without_leaving_pause(self):
        (self.root / 'data/stream-fixture.bin').write_bytes(os.urandom(2 * 1024 * 1024))
        program = subprocess.check_output([sys.executable, str(HELPER), 'program', str(self.guide)])
        with subprocess.Popen([sys.executable, '-', 'capture', str(self.root), 'hermes'],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=self.env) as child:
            child.stdin.write(program)
            child.stdin.close()
            child.stdin = None
            self.assertEqual(child.stdout.read(1), b'\x1f')
            child.stdout.close()
            child.stdout = None
            child.communicate(timeout=30)
            self.assertNotEqual(child.returncode, 0)
        self.assertFalse((self.base / 'paused').exists())
        self.assertEqual(list(self.root.glob('.hermes-backup-*')), [])

    def test_overlapping_capture_keeps_lock_inode_and_never_pauses(self):
        lock_path = self.root / ".hermes-backup.lock"
        with lock_path.open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            inode = lock_path.stat().st_ino
            result = self.capture()
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b"")
            self.assertEqual(lock_path.stat().st_ino, inode)
            self.assertFalse(self.log.exists())

    def test_space_preflight_uses_current_state_and_image_not_old_backups(self):
        result = self.capture(low_space=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")
        self.assertNotIn("docker image save", self.log.read_text())
        self.assertNotIn("docker pause", self.log.read_text())
        spec = importlib.util.spec_from_file_location("bundle", HELPER)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        with mock.patch.object(helper.shutil, "disk_usage", return_value=shutil._ntuple_diskusage(100, 100, 0)):
            with self.assertRaises(helper.BundleError):
                helper.require_space(self.root, self.image)
        (self.root / "backups").mkdir()
        with (self.root / "backups/old-bundle").open("wb") as old:
            old.truncate(100 * 1024 * 1024 * 1024)
        with mock.patch.object(helper.shutil, "disk_usage", return_value=shutil._ntuple_diskusage(10**9, 0, 10**9)):
            helper.require_space(self.root, self.image)

    def test_space_budget_requires_only_one_snapshot_and_image(self):
        spec = importlib.util.spec_from_file_location('bundle', HELPER)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        with (self.root / 'data/space-fixture.bin').open('wb') as stream:
            stream.truncate(64 * 1024 * 1024)
        image = dict(self.image, Size=32 * 1024 * 1024)
        available = 192 * 1024 * 1024
        with mock.patch.object(helper.shutil, 'disk_usage',
                               return_value=shutil._ntuple_diskusage(available, 0, available)):
            budget = helper.require_space(self.root, image)
        self.assertGreater(budget, 96 * 1024 * 1024)
        self.assertLessEqual(budget, available)

    def rewrite_with_rehashed_payload(self, bundle, name, contents):
        with tarfile.open(bundle) as archive:
            manifest = json.load(archive.extractfile("manifest.json"))
        manifest["payloads"][name] = {"sha256": hashlib.sha256(contents).hexdigest(), "size": len(contents)}
        return self.rewrite_bundle(bundle, {name: contents, "manifest.json": json.dumps(manifest).encode()})

    def test_nested_traversal_duplicate_and_missing_app_rejected_even_with_valid_hashes(self):
        bundle = self.bundle()
        with tarfile.open(bundle) as outer:
            state = outer.extractfile("state.tar").read()
        for attack in ("traversal", "duplicate", "symlink-child", "missing-app", "truncated", "trailing"):
            with self.subTest(attack=attack):
                output = io.BytesIO()
                with tarfile.open(fileobj=io.BytesIO(state)) as source, tarfile.open(fileobj=output, mode="w") as dest:
                    for member in source:
                        if attack == "missing-app" and member.name.startswith("app"):
                            continue
                        dest.addfile(member, source.extractfile(member) if member.isfile() else None)
                    if attack == "traversal":
                        self.add_bytes(dest, "data/../../outside", b"unsafe")
                    elif attack == "duplicate":
                        self.add_bytes(dest, "data/config.yaml", b"duplicate")
                    elif attack == "symlink-child":
                        self.add_bytes(dest, "data/profiles/manager/python3/child", b"unsafe")
                contents = output.getvalue()
                if attack == "truncated":
                    contents = contents[:1024]
                elif attack == "trailing":
                    contents += b"nonzero-after-tar-end"
                self.assertNotEqual(self.verify(self.rewrite_with_rehashed_payload(bundle, "state.tar", contents)).returncode, 0)
        with tarfile.open(bundle) as archive:
            image = archive.extractfile("image.tar").read()
        output = io.BytesIO()
        with tarfile.open(fileobj=io.BytesIO(image)) as source, tarfile.open(fileobj=output, mode="w") as dest:
            for member in source:
                contents = source.extractfile(member).read()
                if member.name == "layer/layer.tar":
                    contents = b"wrong layer bytes"
                self.add_bytes(dest, member.name, contents)
        self.assertNotEqual(self.verify(self.rewrite_with_rehashed_payload(bundle, "image.tar", output.getvalue())).returncode, 0)

    def test_containerd_saved_gzip_blob_preserves_same_image_identity(self):
        compressed = gzip.compress(self.layer)
        blob = "blobs/sha256/" + hashlib.sha256(compressed).hexdigest()
        with tarfile.open(self.image_tar, "w") as archive:
            self.add_bytes(archive, self.real_image_id[7:] + ".json", self.image_config)
            self.add_bytes(archive, blob, compressed)
            self.add_bytes(archive, "manifest.json", json.dumps([{
                "Config": self.real_image_id[7:] + ".json", "RepoTags": self.image["RepoTags"], "Layers": [blob]}]).encode())
        bundle = self.bundle()
        self.assertEqual(self.verify(bundle).returncode, 0)

    def make_oci_image(self, attack="", root_kind="index", compression="gzip", variant="", two_layers=False):
        # Synthetic standard OCI layout, not a claim about a retained live export.
        blobs = {}
        def blob(data, media_type):
            digest = "sha256:" + hashlib.sha256(data).hexdigest()
            blobs["blobs/sha256/" + digest[7:]] = data
            return {"mediaType": media_type, "digest": digest, "size": len(data)}
        def document(value, media_type):
            return blob(json.dumps(value).encode(), media_type)
        index_type = "application/vnd.oci.image.index.v1+json"
        manifest_type = "application/vnd.oci.image.manifest.v1+json"
        config_type = "application/vnd.oci.image.config.v1+json"
        layer_type = "application/vnd.oci.image.layer.v1.tar"
        compressed = self.layer if compression == "raw" else gzip.compress(self.layer, mtime=0)
        if compression == "gzip":
            layer_type += "+gzip"
        elif compression == "zstd":
            from compression import zstd
            compressed = zstd.compress(self.layer)
            layer_type += "+zstd"
        config_bytes = self.image_config
        if variant or two_layers:
            config_value = json.loads(config_bytes)
            if variant:
                config_value["variant"] = variant
            if two_layers:
                config_value["rootfs"]["diff_ids"] *= 2
            config_bytes = json.dumps(config_value).encode()
        config = blob(config_bytes, config_type)
        layer = blob(compressed, layer_type)
        saved_config = "blobs/sha256/" + config["digest"][7:]
        saved_layer = "blobs/sha256/" + layer["digest"][7:]
        if attack == "unlinked-config":
            config = blob(config_bytes + b"\n", config_type)
        elif attack == "unlinked-layer":
            # Same uncompressed diff_id, but not the descriptor's saved bytes.
            layer = blob(gzip.compress(self.layer, mtime=1), layer_type)
        elif attack == "config-size":
            config["size"] += 1
        elif attack == "layer-size":
            layer["size"] += 1
        elif attack == "config-media-type":
            config["mediaType"] = layer_type
        elif attack == "layer-media-type":
            layer["mediaType"] = config_type
        layer_descriptors = [layer]
        saved_layers = [saved_layer]
        if two_layers:
            # Two representations with identical diff_ids isolate descriptor
            # order validation from the existing uncompressed-layer checks.
            second = blob(gzip.compress(self.layer, mtime=1), layer_type)
            layer_descriptors.append(second)
            saved_layers.append("blobs/sha256/" + second["digest"][7:])
            if attack == "reordered-layers":
                saved_layers.reverse()
        image_manifest = {"schemaVersion": 2, "mediaType": manifest_type,
                          "config": config, "layers": layer_descriptors}
        if attack == "manifest-schema":
            image_manifest["schemaVersion"] = 1
        elif attack == "missing-config-descriptor":
            del image_manifest["config"]
        elif attack == "missing-layer-descriptor":
            image_manifest["layers"] = []
        manifest = document(image_manifest, manifest_type)
        manifest["platform"] = {"os": "linux", "architecture": "amd64"}
        if variant:
            manifest["platform"]["variant"] = variant
        if attack == "wrong-platform":
            manifest["platform"]["architecture"] = "arm64"
        elif attack == "wrong-variant":
            manifest["platform"]["variant"] = "v3"
        elif attack == "missing-platform":
            del manifest["platform"]
        elif attack == "manifest-size":
            manifest["size"] += 1
        # Docker retains the original index even when other platforms' blobs
        # are absent. Put that unavailable platform first to test selection.
        manifests = [{"mediaType": manifest_type, "digest": "sha256:" + "d" * 64,
                      "size": 123, "platform": {"os": "linux", "architecture": "arm64"}}, manifest]
        if attack == "ambiguous-platform":
            manifests.append(dict(manifest))
        elif attack == "nested-index":
            manifest["mediaType"] = index_type
        if root_kind == "index":
            root = document({"schemaVersion": 1 if attack == "root-schema" else 2,
                             "mediaType": index_type, "manifests": manifests}, index_type)
        else:
            root = manifest
        index = {"schemaVersion": 2, "mediaType": index_type, "manifests": [dict(root)]}
        if attack == "unlinked-root":
            index["manifests"][0]["digest"] = manifest["digest"]
        elif attack == "root-size":
            index["manifests"][0]["size"] += 1
        elif attack == "root-media-type":
            index["manifests"][0]["mediaType"] = config_type
        if attack in ("missing-root", "forged-root"):
            name = "blobs/sha256/" + root["digest"][7:]
            if attack == "missing-root":
                del blobs[name]
            else:
                blobs[name] += b"\n"
        elif attack == "missing-manifest":
            del blobs["blobs/sha256/" + manifest["digest"][7:]]
        elif attack == "missing-config":
            del blobs[saved_config]
        elif attack == "missing-layer":
            del blobs[saved_layer]
        with tarfile.open(self.image_tar, "w") as archive:
            for name, data in blobs.items():
                self.add_bytes(archive, name, data)
            self.add_bytes(archive, "oci-layout", b'{"imageLayoutVersion":"1.0.0"}')
            if attack != "missing-index":
                self.add_bytes(archive, "index.json", json.dumps(index).encode())
            self.add_bytes(archive, "manifest.json", json.dumps([{
                "Config": saved_config, "RepoTags": [], "Layers": saved_layers}]).encode())
        self.real_image_id = root["digest"]
        self.container["Image"] = self.real_image_id
        self.image["Id"] = self.real_image_id
        self.image["Descriptor"] = root
        self.image["Variant"] = variant
        self.save_fixture()

    def test_oci_index_and_manifest_roots_authenticate_exact_saved_image(self):
        compressions = ["raw", "gzip"]
        try:
            from compression import zstd
        except ImportError:
            pass
        else:
            compressions.append("zstd")
        for root_kind in ("index", "manifest"):
            for compression in compressions:
                with self.subTest(root_kind=root_kind, compression=compression):
                    self.make_oci_image(root_kind=root_kind, compression=compression)
                    path = self.bundle()
                    result = self.verify(path)
                    self.assertEqual(result.returncode, 0, result.stderr.decode())
                    with tarfile.open(path) as archive:
                        helper = self.base / "oci-verify.py"
                        helper.write_bytes(archive.extractfile("verify.py").read())
                    self.assertEqual(self.verify(path, helper).returncode, 0)

    def test_oci_layers_must_match_descriptor_order_even_with_same_diff_ids(self):
        self.make_oci_image(two_layers=True)
        result = self.verify(self.bundle())
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.make_oci_image(two_layers=True, attack="reordered-layers")
        result = self.verify(self.bundle())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"saved OCI layer linkage mismatch", result.stderr)

    def test_oci_platform_selection_uses_inspected_variant(self):
        self.make_oci_image(variant="v2")
        result = self.verify(self.bundle())
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.make_oci_image(variant="v2", attack="wrong-variant")
        self.assertNotEqual(self.verify(self.bundle()).returncode, 0)

    def test_oci_identity_rejects_forged_missing_and_unlinked_content(self):
        for attack in ("forged-root", "missing-root", "missing-index", "unlinked-root",
                       "root-size", "root-media-type", "root-schema", "manifest-schema",
                       "manifest-size", "missing-manifest",
                       "wrong-platform", "wrong-variant", "missing-platform", "ambiguous-platform", "nested-index",
                       "unlinked-config", "config-size", "config-media-type", "missing-config",
                       "missing-config-descriptor", "unlinked-layer", "layer-size", "layer-media-type",
                       "missing-layer", "missing-layer-descriptor"):
            with self.subTest(attack=attack):
                self.make_oci_image(attack=attack)
                result = self.verify(self.bundle())
                self.assertNotEqual(result.returncode, 0)

    def test_zstd_layers_require_available_stdlib_decoder(self):
        spec = importlib.util.spec_from_file_location("bundle", HELPER)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        try:
            from compression import zstd
        except ImportError:
            compressed = b"\x28\xb5\x2f\xfd" + b"fixture-no-decoder"
            available = False
        else:
            compressed = zstd.compress(self.layer)
            available = True
        blob = "blobs/sha256/" + hashlib.sha256(compressed).hexdigest()
        with tarfile.open(self.image_tar, "w") as archive:
            self.add_bytes(archive, self.real_image_id[7:] + ".json", self.image_config)
            self.add_bytes(archive, blob, compressed)
            self.add_bytes(archive, "manifest.json", json.dumps([{
                "Config": self.real_image_id[7:] + ".json", "RepoTags": self.image["RepoTags"], "Layers": [blob]}]).encode())
        if available:
            self.assertEqual(self.verify(self.bundle()).returncode, 0)
        else:
            result = self.verify(self.bundle())
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"stdlib decoder unavailable", result.stderr)
        real_import = __import__
        def unavailable(name, *args, **kwargs):
            if name == "compression":
                raise ImportError("bounded unavailable decoder fixture")
            return real_import(name, *args, **kwargs)
        with mock.patch("builtins.__import__", side_effect=unavailable):
            with self.assertRaisesRegex(helper.BundleError, "stdlib decoder unavailable"):
                helper.validate_image(self.image_tar, {"id": self.real_image_id, "os": "linux", "architecture": "amd64"})

    def test_restore_compose_schema_and_dollar_values_with_native_compose(self):
        if shutil.which("docker") is None:
            self.skipTest("native Docker Compose CLI unavailable")
        probe = subprocess.run(["docker", "compose", "version"], capture_output=True)
        if probe.returncode != 0:
            self.skipTest("native Docker Compose CLI is not runnable")
        path = self.bundle()
        config = self.base / "compose.restore.json"
        with tarfile.open(path) as archive:
            config.write_bytes(archive.extractfile("compose.restore.json").read())
        result = subprocess.run(["docker", "compose", "-f", str(config), "config", "--format", "json"],
                                capture_output=True, env=dict(os.environ, LITERAL="must-not-substitute", KEEP="wrong"))
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        # Compose's config output keeps $$ for the later container creation;
        # --no-interpolate confirms schema without exposing fixture credentials.
        service = json.loads(result.stdout)["services"]["hermes"]
        self.assertEqual(service["environment"]["TOKEN"], "secret-value$$LITERAL$${KEEP}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--fixture-bundle":
        fixture = BundleTest(methodName="test_bundle_layout_effective_config_and_embedded_verifier")
        try:
            fixture.setUp()
            shutil.copyfile(fixture.bundle(), sys.argv[2])
        finally:
            fixture.doCleanups()
    else:
        unittest.main()
