#!/usr/bin/env python3
"""Host primitives exercised against subprocess Docker fixture, real capture/verifier."""
import importlib
import json
from pathlib import Path
import sys
import unittest
from unittest import mock
from migration_cold_capture_test import ColdCaptureTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))


class HostOperationsTest(unittest.TestCase):
    setUp = ColdCaptureTest.setUp
    add_bytes = staticmethod(ColdCaptureTest.add_bytes)
    save_fixture = ColdCaptureTest.save_fixture

    def setup_operations(self):
        self.opsdir = self.base / 'operations'
        self.opsdir.mkdir(mode=0o700)
        docker = self.bin / 'docker'
        script = docker.read_text().replace("if args[:2] == ['image', 'inspect']:", """if args[0] in ('update', 'stop'):
    original = pathlib.Path(os.environ['FIXTURE'])
    if args[0] == 'update':
        data['container']['HostConfig']['RestartPolicy'] = {'Name': 'no', 'MaximumRetryCount': 0}
    else:
        data['container']['State'] = dict(Running=False, Paused=False, Restarting=False,
          Dead=False, Pid=0, Status='exited', ExitCode=0, StartedAt='2026-01-01T00:00:00Z',
          FinishedAt='2026-01-01T01:00:00Z')
    original.write_text(json.dumps(data))
    if os.environ.get('FAIL') == args[0]: sys.exit(1)
elif args[:2] == ['image', 'inspect']:""")
        docker.write_text(script)
        self.module = importlib.import_module('hermes_migration_host')
        return self.module.HostOperations(self.root, self.opsdir)

    def test_fence_capture_and_revoke_are_real_durable_operations(self):
        self.assertTrue((Path(__file__).resolve().parents[1] / 'scripts/hermes_migration_host.py').exists(),
                        'executable host operations missing')
        operations = self.setup_operations()
        run = 'a' * 32
        with mock.patch.dict('os.environ', self.env):
            fenced = operations.fence(run)
            self.assertTrue(fenced['docker_fenced'])
            self.assertFalse(fenced['all_writers_fenced'])
            self.assertEqual(json.loads((self.opsdir / 'original.json').read_text()), self.container)
            receipt = operations.capture(run)
            self.assertTrue(receipt['verified'])
            self.assertFalse(receipt['independent_copy_verified'])
            self.assertEqual(receipt['archive_format'], 'tar.gz')
            self.assertTrue((self.opsdir / 'full.tar.gz').is_file())
            retry = operations.capture(run)
            self.assertEqual(retry, receipt)
            self.assertEqual(self.log.read_text().count('docker image save'), 1)
            operations.revoke(run)
            with self.assertRaises(self.module.Refused):
                operations.capture(run)
            self.assertNotIn('docker start ', self.log.read_text())
            self.assertNotIn('docker unpause ', self.log.read_text())

    def test_uncertain_update_and_stop_reconcile_without_replacing_original(self):
        operations = self.setup_operations()
        run = 'b' * 32
        with mock.patch.dict('os.environ', dict(self.env, FAIL='update')):
            with self.assertRaises(self.module.bundle.BundleError):
                operations.fence(run)
        original = (self.opsdir / 'original.json').read_bytes()
        with mock.patch.dict('os.environ', dict(self.env, FAIL='stop')):
            with self.assertRaises(self.module.bundle.BundleError):
                operations.fence(run)
        with mock.patch.dict('os.environ', self.env):
            self.assertTrue(operations.fence(run)['docker_fenced'])
        self.assertEqual((self.opsdir / 'original.json').read_bytes(), original)
        self.assertEqual(self.log.read_text().count('docker update'), 1)
        self.assertEqual(self.log.read_text().count('docker stop'), 1)

    def test_failed_capture_retains_pending_bytes_and_never_publishes(self):
        operations = self.setup_operations()
        run = 'c' * 32
        with mock.patch.dict('os.environ', self.env):
            operations.fence(run)
        with mock.patch.dict('os.environ', dict(self.env, FAIL='snapshot')):
            with self.assertRaises(self.module.Refused):
                operations.capture(run)
        self.assertTrue((self.opsdir / 'full.tar.gz.pending').exists())
        self.assertFalse((self.opsdir / 'full.tar.gz').exists())
        self.assertFalse((self.opsdir / 'capture.json').exists())
        with mock.patch.dict('os.environ', self.env):
            with self.assertRaises(FileExistsError):
                operations.capture(run)
            self.assertTrue(operations.revoke(run)['revoked'])

    def test_replaced_container_or_changed_archive_cannot_reuse_receipt(self):
        operations = self.setup_operations()
        run = 'd' * 32
        with mock.patch.dict('os.environ', self.env):
            operations.fence(run)
            operations.capture(run)
            with (self.opsdir / 'full.tar.gz').open('ab') as stream:
                stream.write(b'corruption')
            with self.assertRaises(self.module.Refused):
                operations.capture(run)
            data = json.loads(self.fixture.read_text())
            data['container']['Id'] = 'f' * 64
            self.fixture.write_text(json.dumps(data))
            with self.assertRaises(self.module.Refused):
                operations.fence(run)

    def test_other_run_or_store_is_not_a_second_host_owner(self):
        operations = self.setup_operations()
        with mock.patch.dict('os.environ', self.env):
            operations.fence('a' * 32)
            with self.assertRaises(self.module.Refused):
                operations.fence('b' * 32)
            other = self.base / 'other-operations'
            other.mkdir(mode=0o700)
            with self.assertRaises(self.module.Refused):
                self.module.HostOperations(self.root, other).fence('a' * 32)
        self.assertEqual(self.log.read_text().count('docker stop'), 1)

    def test_existing_capture_and_host_leases_block_fence(self):
        import fcntl
        operations = self.setup_operations()
        for path in (self.root / '.hermes-backup.lock', self.root / '.hermes-migration.lock'):
            with path.open('a') as stream:
                path.chmod(0o600)
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with mock.patch.dict('os.environ', self.env):
                    with self.assertRaises(self.module.Refused):
                        operations.fence('e' * 32)
        self.assertFalse(self.log.exists())

    def test_restart_after_capture_cannot_reuse_stale_snapshot(self):
        operations = self.setup_operations()
        run = 'a' * 32
        with mock.patch.dict('os.environ', self.env):
            operations.fence(run)
            operations.capture(run)
            data = json.loads(self.fixture.read_text())
            data['container']['State']['StartedAt'] = '2026-01-02T00:00:00Z'
            data['container']['State']['FinishedAt'] = '2026-01-02T01:00:00Z'
            self.fixture.write_text(json.dumps(data))
            with self.assertRaises(self.module.Refused):
                operations.capture(run)
            with self.assertRaises(self.module.Refused):
                operations.fence(run)

    def test_capture_manifest_must_match_original_fence_identity(self):
        operations = self.setup_operations()
        run = 'a' * 32
        with mock.patch.dict('os.environ', self.env):
            operations.fence(run)
            docker = self.bin / 'docker'
            docker.write_text(docker.read_text().replace(
                "elif args[0] == 'inspect':",
                "elif args[0] == 'inspect':\n"
                "    command = pathlib.Path('/proc/' + str(os.getppid()) + '/cmdline').read_bytes()\n"
                "    if b'capture-cold' in command: data['container']['Id'] = 'e' * 64"))
            with self.assertRaises(self.module.Refused):
                operations.capture(run)
        self.assertFalse((self.opsdir / 'capture.json').exists())
        self.assertFalse((self.opsdir / 'full.tar.gz').exists())

    def test_orphan_capture_holds_host_lease_until_real_child_exits(self):
        import os
        import signal
        import subprocess
        import time
        operations = self.setup_operations()
        run = 'f' * 32
        with mock.patch.dict('os.environ', self.env):
            operations.fence(run)
        marker = self.base / 'blocked-child'
        docker = self.bin / 'docker'
        docker.write_text(docker.read_text().replace(
            "elif args[:2] == ['image', 'save']:",
            "elif args[:2] == ['image', 'save']:\n"
            "    import time\n"
            "    pathlib.Path(os.environ['BLOCK_MARKER']).write_text(str(os.getppid()))\n"
            "    time.sleep(30)"))
        parent = subprocess.Popen([sys.executable, self.module.__file__, 'capture', '--execute',
                                   '--root', str(self.root), '--state-dir', str(self.opsdir),
                                   '--run-id', run], env=dict(self.env, BLOCK_MARKER=str(marker)),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        child = None
        try:
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(marker.exists(), 'capture subprocess never reached image export')
            child = int(marker.read_text())
            parent.kill()
            parent.wait(timeout=3)
            with self.assertRaisesRegex(self.module.Refused, 'busy'):
                operations.revoke(run)
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait(timeout=3)
            if child is not None:
                os.killpg(child, signal.SIGKILL)
        self.assertFalse((self.opsdir / 'capture.json').exists())
        self.assertTrue((self.opsdir / 'full.tar.gz.pending').exists())

    def test_cli_requires_explicit_execute_without_docker_calls(self):
        import subprocess
        operations = self.setup_operations()
        result = subprocess.run([sys.executable, self.module.__file__, 'fence',
                                 '--root', str(self.root), '--state-dir', str(self.opsdir),
                                 '--run-id', 'a' * 32], env=self.env, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())


if __name__ == '__main__':
    unittest.main(defaultTest='HostOperationsTest')
