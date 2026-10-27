#!/usr/bin/env python3
"""Recovery staging: real cold bundle/copy/restore, synthetic Docker only."""
import contextlib
import importlib
import os
import signal
import subprocess
import time
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest import mock
from migration_host_test import HostOperationsTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from hermes_migration_controller import Refused


class RecoveryStageTest(unittest.TestCase):
    setUp = HostOperationsTest.setUp
    add_bytes = staticmethod(HostOperationsTest.add_bytes)
    save_fixture = HostOperationsTest.save_fixture
    setup_operations = HostOperationsTest.setup_operations

    def prepare(self):
        helper = Path(__file__).resolve().parents[1] / 'scripts/hermes_migration_recovery.py'
        self.assertTrue(helper.exists(), 'non-starting recovery adapter missing')
        self.recovery = importlib.import_module('hermes_migration_recovery')
        self.run_id = 'a' * 32
        operations = self.setup_operations()
        profile = self.root / 'data/profiles/manager'
        with contextlib.closing(sqlite3.connect(profile / 'state.db')) as db, db:
            db.execute('create table messages(id integer primary key, content text)')
            db.execute('insert into messages values(1, ?)', ('processed synthetic turn',))
        (profile / 'MEMORY.md').write_text('retained synthetic memory\n')
        (profile / 'config.yaml').write_text('synthetic_setting: retained\n')
        (profile / 'SOUL.md').write_text('Synthetic manager identity\n')
        (profile / 'jobs.json').write_text('{"cancelled-job":{"enabled":false}}\n')
        (profile / 'result.txt').write_bytes(b'completed synthetic result\n')
        (profile / 'effects.json').write_text('{"synthetic-effect":"uncertain","replay":false}\n')
        (profile / 'unprocessed.json').write_text('{"synthetic-input":"pending"}\n')
        with mock.patch.dict('os.environ', self.env):
            operations.fence(self.run_id)
            receipt = operations.capture(self.run_id)
        self.archive = self.opsdir / 'full.tar.gz'
        self.store = self.base / 'recovery-custody'
        self.store.mkdir(mode=0o700)
        self.request = dict(run_id=self.run_id, archive=self.archive,
                            archive_digest=receipt['archive_digest'],
                            container_id=receipt['container_id'], image_id=receipt['image_id'],
                            continuity_contract='processed-state-v1')
        self.stage = self.recovery.RecoveryStage(self.store)

    def test_contract_and_identity_are_validated_before_custody_writes(self):
        self.prepare()
        cases = [('continuity_contract', None), ('continuity_contract', 'zero-loss'),
                 ('continuity_contract', 'discard-processed'), ('run_id', '../run'),
                 ('archive_digest', 'A' * 64), ('container_id', ''), ('image_id', 'latest')]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                with self.assertRaises(Refused):
                    self.stage.stage(**dict(self.request, **{key: value}))
                self.assertFalse((self.store / 'intent.json').exists())
                self.assertFalse((self.store / 'full.tar.gz').exists())

    def test_interrupted_restore_retains_original_intent_and_partial_state(self):
        self.prepare()
        def interrupted(archive, destination):
            destination.mkdir(mode=0o700)
            (destination / 'partial').write_bytes(b'preserve-for-review')
            raise OSError('injected restore interruption')
        with mock.patch.object(self.recovery.bundle, 'restore_state', side_effect=interrupted):
            with self.assertRaises(OSError):
                self.stage.stage(**self.request)
        intent = (self.store / 'intent.json').read_bytes()
        for request in (dict(self.request, run_id='b' * 32), self.request):
            with self.assertRaises(Exception) as refusal:
                self.stage.stage(**request)
            self.assertEqual((self.store / 'intent.json').read_bytes(), intent)
            self.assertIsInstance(refusal.exception, Refused)
            self.assertEqual((self.store / 'restored/partial').read_bytes(), b'preserve-for-review')
        self.assertFalse((self.store / 'receipt.json').exists())

    def test_mismatched_digest_and_capture_identity_never_restore(self):
        self.prepare()
        for field, value in [('archive_digest', '0' * 64), ('container_id', '0' * 64),
                             ('image_id', 'sha256:' + '0' * 64)]:
            with self.subTest(field=field):
                directory = self.base / ('bad-' + field)
                directory.mkdir(mode=0o700)
                stage = self.recovery.RecoveryStage(directory)
                with self.assertRaises(Refused):
                    stage.stage(**dict(self.request, **{field: value}))
                self.assertFalse((directory / 'restored').exists())
                self.assertFalse((directory / 'receipt.json').exists())

    def test_completed_retry_detects_changed_bytes_without_repair(self):
        self.prepare()
        self.stage.stage(**self.request)
        result = self.store / 'restored/data/profiles/manager/result.txt'
        result.write_bytes(b'newer result must not be overwritten')
        with self.assertRaises(self.recovery.bundle.BundleError):
            self.stage.stage(**self.request)
        self.assertEqual(result.read_bytes(), b'newer result must not be overwritten')
        copied = self.store / 'full.tar.gz'
        copied.write_bytes(b'corrupt archive')
        with self.assertRaises(Refused):
            self.stage.stage(**self.request)
        self.assertEqual(copied.read_bytes(), b'corrupt archive')
        self.assertNotEqual(self.archive.read_bytes(), b'corrupt archive')

    def test_sigkill_before_and_after_restore_retains_unreceipted_custody(self):
        self.prepare()
        scripts = str(Path(self.recovery.__file__).parent)
        for boundary in ('before', 'after'):
            with self.subTest(boundary=boundary):
                directory = self.base / ('kill-' + boundary)
                directory.mkdir(mode=0o700)
                marker = directory / 'boundary'
                code = '''
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import hermes_migration_recovery as recovery
original = recovery.bundle.restore_state
def pause(archive, destination):
    if sys.argv[4] == 'after':
        original(archive, destination)
    marker = Path(sys.argv[2]) / 'boundary'
    with marker.open('xb') as stream:
        stream.write(b'ready'); stream.flush(); os.fsync(stream.fileno())
    while True:
        time.sleep(1)
recovery.bundle.restore_state = pause
recovery.RecoveryStage(sys.argv[2]).stage(**json.loads(sys.argv[3]))
'''
                request = dict(self.request, archive=str(self.archive))
                child = subprocess.Popen([sys.executable, '-c', code, scripts, str(directory),
                                          json.dumps(request), boundary],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    deadline = time.monotonic() + 10
                    while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertTrue(marker.exists(), 'child did not reach restore boundary')
                    intent = (directory / 'intent.json').read_bytes()
                    with self.assertRaisesRegex(Refused, 'busy'):
                        self.recovery.RecoveryStage(directory).stage(**self.request)
                    child.kill()
                    self.assertEqual(child.wait(timeout=5), -signal.SIGKILL)
                finally:
                    if child.poll() is None:
                        child.kill()
                    child.wait(timeout=5)
                self.assertEqual((directory / 'full.tar.gz').read_bytes(), self.archive.read_bytes())
                self.assertFalse((directory / 'receipt.json').exists())
                self.assertEqual((directory / 'restored').exists(), boundary == 'after')
                with self.assertRaises(Refused):
                    self.recovery.RecoveryStage(directory).stage(**self.request)
                self.assertEqual((directory / 'intent.json').read_bytes(), intent)

    def test_symlinked_custody_cannot_be_reused(self):
        self.prepare()
        self.stage.stage(**self.request)
        copied = self.store / 'full.tar.gz'
        saved = copied.read_bytes()
        copied.unlink()
        copied.symlink_to(self.archive)
        with self.assertRaises(Refused):
            self.stage.stage(**self.request)
        copied.unlink()
        copied.write_bytes(saved)
        copied.chmod(0o600)
        restored = self.store / 'restored'
        moved = self.base / 'moved-restore'
        restored.rename(moved)
        restored.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(Refused):
            self.stage.stage(**self.request)

    def test_receipt_and_intent_must_match_before_returning_success(self):
        self.prepare()
        receipt = self.stage.stage(**self.request)
        receipt_path = self.store / 'receipt.json'
        for key, value in [('ready', True), ('runtime_started', True),
                           ('independent_copy_verified', True), ('phase', 'STARTED'),
                           ('archive_verified', False), ('state_compared', False)]:
            with self.subTest(key=key):
                self.recovery.atomic_json(receipt_path, dict(receipt, **{key: value}))
                with self.assertRaises(Refused):
                    self.stage.stage(**self.request)
        self.recovery.atomic_json(receipt_path, receipt)
        intent_path = self.store / 'intent.json'
        intent = json.loads(intent_path.read_text())
        self.recovery.atomic_json(intent_path, dict(intent, run_id='b' * 32))
        with self.assertRaises(Refused):
            self.stage.stage(**self.request)

    def test_changed_restoration_cannot_publish_success(self):
        self.prepare()
        original_restore = self.recovery.bundle.restore_state
        def changed(archive, destination):
            original_restore(archive, destination)
            (destination / 'data/profiles/manager/result.txt').write_text('changed')
        with mock.patch.object(self.recovery.bundle, 'restore_state', side_effect=changed):
            with self.assertRaises(self.recovery.bundle.BundleError):
                self.stage.stage(**self.request)
        self.assertFalse((self.store / 'receipt.json').exists())
        self.assertTrue((self.store / 'intent.json').exists())

    def test_real_copy_and_restore_preserve_processed_state_without_start(self):
        self.prepare()
        original = self.archive.read_bytes()
        receipt = self.stage.stage(**self.request)
        self.assertEqual(receipt['phase'], 'STAGED')
        self.assertEqual(receipt['continuity_contract'], 'processed-state-v1')
        self.assertTrue(receipt['archive_verified'])
        self.assertTrue(receipt['state_compared'])
        self.assertFalse(receipt['independent_copy_verified'])
        self.assertFalse(receipt['runtime_started'])
        self.assertFalse(receipt['ready'])
        copied = self.store / 'full.tar.gz'
        self.assertEqual(copied.read_bytes(), original)
        self.assertNotEqual(copied.stat().st_ino, self.archive.stat().st_ino)
        restored = self.store / 'restored/data/profiles/manager'
        for name in ('MEMORY.md', 'jobs.json', 'result.txt', 'effects.json', 'unprocessed.json',
                     'config.yaml', 'SOUL.md'):
            self.assertEqual((restored / name).read_bytes(),
                             (self.root / 'data/profiles/manager' / name).read_bytes())
        with contextlib.closing(sqlite3.connect(restored / 'state.db')) as db:
            self.assertEqual(db.execute('pragma integrity_check').fetchone(), ('ok',))
            self.assertEqual(db.execute('select * from messages').fetchall(), [(1, 'processed synthetic turn')])
        self.assertEqual(self.stage.stage(**self.request), receipt)
        self.assertEqual(self.archive.read_bytes(), original)
        self.assertNotIn('docker start ', self.log.read_text())
        self.assertNotIn('docker unpause ', self.log.read_text())
        self.assertNotIn('docker load ', self.log.read_text())


if __name__ == '__main__':
    unittest.main(defaultTest='RecoveryStageTest')
