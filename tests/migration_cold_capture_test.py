#!/usr/bin/env python3
"""Real cold snapshot, gzip, verifier, SQLite and restore; only Docker is fake."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import unittest
from hermes_backup_bundle_test import BundleTest, HELPER


class ColdCaptureTest(unittest.TestCase):
    setUp = BundleTest.setUp
    add_bytes = staticmethod(BundleTest.add_bytes)
    save_fixture = BundleTest.save_fixture
    verify = BundleTest.verify
    rewrite_bundle = BundleTest.rewrite_bundle

    def stopped(self):
        self.container['State'] = dict(Running=False, Paused=False, Restarting=False,
                                      Dead=False, Pid=0, Status='exited', ExitCode=0,
                                      StartedAt='2026-01-01T00:00:00Z',
                                      FinishedAt='2026-01-01T01:00:00Z')
        self.container['HostConfig']['RestartPolicy'] = dict(Name='no', MaximumRetryCount=0)
        self.save_fixture()

    def cold(self, fail=''):
        program = subprocess.run([sys.executable, str(HELPER), 'program', str(self.guide)],
                                 check=True, capture_output=True)
        return subprocess.run([sys.executable, '-', 'capture-cold', str(self.root), 'hermes'],
                              input=program.stdout, capture_output=True,
                              env=dict(self.env, FAIL=fail))

    def test_real_frozen_full_capture_verify_and_sqlite_restore(self):
        self.stopped()
        database = self.root / 'data/profiles/manager/state.db'
        with sqlite3.connect(database) as db:
            db.execute('create table messages (id integer primary key, content text)')
            db.execute('insert into messages values (1, ?)', ('offline-fixture',))
        result = self.cold()
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        archive = self.base / 'full.tar.gz'
        archive.write_bytes(result.stdout)
        checked = self.verify(archive, scope='full')
        self.assertEqual(checked.returncode, 0, checked.stderr.decode())
        with tarfile.open(archive, 'r:gz') as bundle:
            manifest = json.load(bundle.extractfile('manifest.json'))
            observed = json.load(bundle.extractfile('container-inspect.json'))
            self.assertEqual(observed, self.container)
            self.assertEqual(manifest['capture']['mode'], 'cold-stopped-v1')
            self.assertEqual(manifest['image']['id'], self.real_image_id)
        target = self.base / 'restored'
        restore = subprocess.run([sys.executable, str(HELPER), 'restore-state', str(archive),
                                  str(target)], capture_output=True, env=self.env)
        self.assertEqual(restore.returncode, 0, restore.stderr.decode())
        with sqlite3.connect(target / 'data/profiles/manager/state.db') as db:
            self.assertEqual(db.execute('pragma integrity_check').fetchone(), ('ok',))
            self.assertEqual(db.execute('select * from messages').fetchall(), [(1, 'offline-fixture')])
        events = self.log.read_text()
        self.assertNotIn('docker pause ', events)
        self.assertNotIn('docker unpause ', events)
        self.assertNotIn('docker start ', events)
        self.assertFalse(Path(self.env['PAUSED']).exists())

    def test_cold_provenance_is_verified_not_an_unchecked_manifest_claim(self):
        self.stopped()
        result = self.cold()
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        bundle = self.base / 'full.tar.gz'
        bundle.write_bytes(result.stdout)
        with tarfile.open(bundle) as archive:
            original = json.load(archive.extractfile('manifest.json'))
        for change in ({'mode': 'fake'}, {'snapshot_started_at': 'tomorrow'},
                       {'snapshot_finished_at': '2000-01-01T00:00:00+00:00'}):
            with self.subTest(change=change):
                manifest = json.loads(json.dumps(original))
                manifest['capture'].update(change)
                mutated = self.rewrite_bundle(bundle, {'manifest.json': json.dumps(manifest).encode()})
                self.assertNotEqual(self.verify(mutated, scope='full').returncode, 0)

    def test_rejects_running_paused_restartable_and_unclean_without_docker_mutation(self):
        for alteration in ('running', 'paused', 'restart', 'exit', 'pid', 'mount', 'layer'):
            with self.subTest(alteration=alteration):
                self.stopped()
                if alteration == 'running': self.container['State']['Running'] = True
                if alteration == 'paused': Path(self.env['PAUSED']).touch()
                if alteration == 'restart': self.container['HostConfig']['RestartPolicy']['Name'] = 'always'
                if alteration == 'exit': self.container['State']['ExitCode'] = 137
                if alteration == 'pid': self.container['State']['Pid'] = 123
                if alteration == 'mount': self.container['Mounts'][0]['RW'] = False
                if alteration == 'layer': self.layer_changes = ['C /opt/program.py']
                self.save_fixture()
                result = self.cold()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b'')
                Path(self.env['PAUSED']).unlink(missing_ok=True)
                self.container['Mounts'][0]['RW'] = True
        self.assertNotIn('docker pause ', self.log.read_text())
        self.assertNotIn('docker unpause ', self.log.read_text())

    def test_ordinary_capture_still_rejects_stopped_source(self):
        self.stopped()
        result = BundleTest.capture(self)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'')

    def test_cold_failures_leave_source_stopped_and_no_stream(self):
        self.stopped()
        for failure in ('snapshot', 'image', 'diff'):
            with self.subTest(failure=failure):
                result = self.cold(failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b'')
                self.assertNotIn('docker unpause ', self.log.read_text())
                self.assertNotIn('docker start ', self.log.read_text())


if __name__ == '__main__':
    unittest.main(defaultTest='ColdCaptureTest')
