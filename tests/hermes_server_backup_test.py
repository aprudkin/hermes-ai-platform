#!/usr/bin/env python3
"""Offline server-workflow contracts; real capture/verifier, fake Docker and cloud CLI."""
import contextlib
import datetime as dt
import fcntl
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import hermes_backup_bundle_test as bundles
from hermes_cloud_backup_test import CONFIG

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import hermes_server_backup as server
import install_server_backup as installer


def run_id(seconds, char='a'):
    return dt.datetime.fromtimestamp(seconds, dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + char * 32


class ServerTest(unittest.TestCase):
    def setUp(self):
        mask = os.umask(0o077)
        self.addCleanup(os.umask, mask)
        self.fixture = bundles.BundleTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.base = self.fixture.base
        self.now = 1792569600
        self.current = run_id(self.now)
        self.state, self.logs, self.package, self.keys, self.cloud = [self.base / n for n in ('state', 'logs', 'package', 'keys', 'cloud')]
        for p in (self.state, self.logs, self.package, self.keys, self.cloud, self.state / 'runs', self.state / 'receipts'):
            p.mkdir(mode=0o700)
        for name in ('upload.conf', 'recovery.conf', 'daily-upload.conf', 'daily-recovery.conf'):
            config = CONFIG if not name.startswith('daily-') else CONFIG.replace('Hermes-Backups/crypt-v1', 'Backup/Hermes').replace('directory_name_encryption = true', 'directory_name_encryption = false')
            (self.keys / name).write_text(config)
        self.journal = server.Journal(self.logs, self.current, self.now)
        self.patches = mock.patch.multiple(server, STATE=self.state, LOGS=self.logs, PACKAGE=self.package,
                                          KEYS=self.keys, RUNTIME=self.fixture.root)
        self.patches.start()
        self.addCleanup(self.patches.stop)
        for name in ('hermes_backup_bundle.py',):
            shutil.copyfile(ROOT / 'scripts' / name, self.package / name)
        generated = subprocess.check_output([sys.executable, str(bundles.HELPER), 'program', str(self.fixture.guide)])
        (self.package / 'capture.py').write_bytes(generated)
        # Preserve the existing bounded Docker fixture and add the status format contract.
        docker = self.fixture.bin / 'docker'
        text = docker.read_text().replace("if args[:2] == ['image', 'inspect']:",
                                         "if args[:2] == ['inspect', '--format']:\n    print('true true' if paused.exists() else 'true false')\nelif args[:2] == ['image', 'inspect']:")
        docker.write_text(text)
        fake = self.package / 'rclone'
        fake.write_text('''#!/usr/bin/env python3
import json, os, pathlib, shutil, sys
args = sys.argv[1:]
action = args[0]
assert action in ('copy', 'lsjson', 'deletefile', 'rmdir')
assert '--config' in args
assert not any(k.upper().startswith('RCLONE_') for k in os.environ)
config = pathlib.Path(args[args.index('--config') + 1])
assert config.stat().st_mode & 0o077 == 0
assert config.name == ('daily-recovery.conf' if action == 'lsjson' else ('upload.conf' if 'scheduled-v1/' in args[1] else 'daily-upload.conf'))
with open(os.environ['CLOUD_EVENTS'], 'a') as stream:
    stream.write(json.dumps(args) + '\\n')
root = pathlib.Path(os.environ['CLOUD_ROOT'])
def cloud_path(remote):
    return root / remote.split(':', 1)[1]
if action == 'lsjson':
    source = cloud_path(args[1])
    if not source.exists(): sys.exit(4)
    if os.environ.get('CLOUD_FAIL') == 'lsjson': sys.exit(7)
    if source.is_dir():
        if '--stat' in args:
            # Pinned rclone lsjson --stat on a crypt directory reports its
            # filesystem root relative to that exact directory: empty Name/Path.
            print(json.dumps({'Name': '', 'Path': '', 'IsDir': True}))
            sys.exit(0)
        print(json.dumps([{'Name': p.name} for p in source.iterdir()]))
        sys.exit(0)
    size = source.stat().st_size + (1 if os.environ.get('CORRUPT') == '1' else 0)
    print(json.dumps({'Name': source.name, 'Size': size, 'IsDir': False}))
    sys.exit(0)
if os.environ.get('CLOUD_FAIL') == action:
    print('fixture-obscured-secret', file=sys.stderr)
    sys.exit(7)
if action == 'copy':
    assert args[2].startswith('hermes-backup:') and 'scheduled-v1' not in args[2]
    assert '--immutable' in args and '--size-only' in args
    source = pathlib.Path(args[1])
    files = list(source.iterdir())
    assert len(files) == 1 and files[0].name.endswith('.tar.gz')
    dest = cloud_path(args[2]) / files[0].name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if dest.stat().st_size != files[0].stat().st_size: sys.exit(8)
    else: shutil.copyfile(files[0], dest)
elif action == 'rmdir':
    cloud_path(args[1]).rmdir()
else:
    cloud_path(args[1]).unlink(missing_ok=True)
print(json.dumps({'stats': {'bytes': 123, 'speed': 45}, 'msg': 'fixture-obscured-secret'}), file=sys.stderr)
''')
        fake.chmod(0o700)
        self.events = self.base / 'cloud-events'
        env = {k: v for k, v in self.fixture.env.items() if not k.upper().startswith('RCLONE_')}
        env.update(CLOUD_ROOT=str(self.cloud), CLOUD_EVENTS=str(self.events))
        self.workflow = server.Workflow(self.journal, env)

    def test_external_removal_is_not_workflow_deletion_authority(self):
        _, old = self.old_copy(4 * 86400, 'b')
        old['cloud_removed_externally'] = True
        server.atomic_json(self.state / 'receipts' / (old['run'] + '.json'), old)
        _, current = self.old_copy(0, 'a')
        records = self.records()
        self.assertFalse(records[0]['cloud_deleted'])
        self.assertEqual(server.rotation_candidates(records, self.current), [])

    def test_existing_date_and_partial_suffix_are_skipped_and_receipted(self):
        base = server.date_directory(self.current)
        path = self.cloud / base / server.archive_name(self.current)
        path.parent.mkdir()
        path.write_bytes(b'unknown preexisting payload')
        (self.cloud / (base + '-2')).mkdir()  # Empty/failed folders also count.
        self.workflow.execute(self.current)
        self.assertEqual(path.read_bytes(), b'unknown preexisting payload')
        record = self.records()[0]
        self.assertEqual(record['cloud_directory'], base + '-3')
        self.assertEqual(server.record_remote(record), server.REMOTE + base + '-3/' + path.name)
        self.assertTrue((self.cloud / (base + '-3') / path.name).exists())
        self.assertEqual(list((self.cloud / (base + '-2')).iterdir()), [])

    def test_visible_moscow_date_and_no_reverse_download(self):
        run = '20261031T213000Z-' + 'f' * 32
        self.assertEqual(server.date_directory(run), '26-11-1')
        with mock.patch.object(self.workflow, 'verify', wraps=self.workflow.verify) as verifier:
            self.workflow.execute(self.current)
        self.assertEqual(verifier.call_count, 1)
        calls = [json.loads(line) for line in self.events.read_text().splitlines()]
        self.assertNotIn('copyto', [c[0] for c in calls])
        self.assertTrue(any(c[0] == 'lsjson' for c in calls))
        record = self.records()[0]
        self.assertEqual(record['cloud_layout'], 'dated-v2')
        self.assertTrue(record['cloud_metadata_checked'])
        self.assertNotIn('cloud_roundtrip_verified', self.journal.path.read_text())

    def test_repeated_backup_uses_next_suffix_and_keeps_both_cloud_copies(self):
        self.workflow.execute(self.current)
        second = run_id(self.now + 1, 'b')
        self.workflow.execute(second)
        records = self.records()
        base = server.date_directory(self.current)
        self.assertEqual([r['cloud_directory'] for r in records], [base, base + '-2'])
        self.assertTrue(all((self.cloud / r['cloud_directory'] / server.archive_name(r['run'])).is_file()
                            and not r['cloud_deleted'] for r in records))

    def test_empty_base_is_occupied_and_unconfirmed_metadata_fails_closed(self):
        base = server.date_directory(self.current)
        (self.cloud / base).mkdir()
        self.assertEqual(self.workflow.allocate_directory(self.current), base + '-2')
        self.workflow.env['CLOUD_FAIL'] = 'lsjson'
        with self.assertRaises(server.CloudError):
            self.workflow.allocate_directory(self.current)

    def test_receipt_directory_validation_and_legacy_dated_compatibility(self):
        _, record = self.old_copy(0, 'a')
        path = self.state / 'receipts' / (self.current + '.json')
        base = server.date_directory(self.current)
        record.update(cloud_layout='dated-v1', cloud_metadata_checked=True, cloud_roundtrip_verified=False)
        server.atomic_json(path, record)
        self.assertEqual(server.record_remote(self.records()[0]), server.REMOTE + base + '/' + server.archive_name(self.current))
        record['cloud_layout'] = 'dated-v2'
        for invalid in (None, '', base + '-1', base + '-0', base + '-02', base + '-2/../x',
                        '../' + base, base + '/', '26-1-1', 2):
            with self.subTest(directory=invalid):
                record['cloud_directory'] = invalid
                server.atomic_json(path, record)
                with self.assertRaises(server.CloudError):
                    self.records()
        for valid in (base, base + '-2', base + '-10'):
            record['cloud_directory'] = valid
            server.atomic_json(path, record)
            self.assertEqual(self.records()[0]['cloud_directory'], valid)
        del record['cloud_directory']
        server.atomic_json(path, record)
        with self.assertRaises(server.CloudError):
            self.records()

    def records(self):
        return server.load_receipts(self.state)

    def old_copy(self, age, char='b'):
        run = run_id(self.now - age, char)
        directory = self.state / 'runs' / run / 'upload'
        directory.mkdir(parents=True, mode=0o700)
        path = directory / server.archive_name(run)
        path.write_bytes(b'previous verified archive fixture')
        record = {'run': run, 'created': server.stamp(run), 'bytes': path.stat().st_size,
                  'sha256': server.digest(path), 'cloud_deleted': False,
                  'bundle_integrity_verified': True, 'state_restored': False,
                  'restored_runtime_verified': False}
        server.atomic_json(self.state / 'receipts' / (run + '.json'), record)
        (self.cloud / 'scheduled-v1').mkdir(exist_ok=True)
        (self.cloud / 'scheduled-v1' / path.name).write_bytes(path.read_bytes())
        return path, record

    def test_rotation_keeps_all_copies_from_three_moscow_calendar_dates(self):
        local = dt.datetime.fromtimestamp(self.now, server.ZoneInfo('Europe/Moscow'))
        cutoff = int((local.replace(hour=0, minute=0, second=0) - dt.timedelta(days=2)).timestamp())
        expired_path, expired = self.old_copy(self.now - cutoff + 1, 'b')
        boundary_path, boundary = self.old_copy(self.now - cutoff, 'c')
        recent_path, recent = self.old_copy(self.now - cutoff - 1, 'd')
        current_path, current = self.old_copy(0, 'a')
        unknown = self.cloud / 'manual.tar.gz'
        unknown.write_bytes(b'untouched')
        self.workflow.rotate(self.current)
        records = {r['run']: r for r in self.records()}
        self.assertTrue(records[expired['run']]['cloud_deleted'])
        self.assertFalse((self.cloud / 'scheduled-v1' / expired_path.name).exists())
        for path, record in ((boundary_path, boundary), (recent_path, recent),
                             (current_path, current)):
            self.assertFalse(records[record['run']]['cloud_deleted'])
            self.assertTrue((self.cloud / 'scheduled-v1' / path.name).exists())
        self.assertTrue(current_path.exists())
        self.assertEqual(unknown.read_bytes(), b'untouched')
        calls = [json.loads(line) for line in self.events.read_text().splitlines()]
        self.assertEqual([c[:2] for c in calls],
                         [['deletefile', server.LEGACY_REMOTE + expired_path.name]])

    def test_expired_dated_copy_and_empty_date_removed_without_purging_unknown_objects(self):
        old, expired = self.old_copy(5 * 86400, 'b')
        expired.update(cloud_layout='dated-v1', cloud_metadata_checked=True, cloud_roundtrip_verified=False)
        server.atomic_json(self.state / 'receipts' / (expired['run'] + '.json'), expired)
        day = self.cloud / server.date_directory(expired['run'])
        day.mkdir()
        (self.cloud / 'scheduled-v1' / old.name).rename(day / old.name)
        self.workflow.execute(self.current)
        self.assertFalse(day.exists())
        self.assertTrue({r['run']: r for r in self.records()}[expired['run']]['cloud_deleted'])
        self.assertTrue((self.cloud / server.date_directory(self.current)).is_dir())

    def test_nonempty_date_with_unknown_object_is_never_removed(self):
        day = self.cloud / server.date_directory(self.current)
        day.mkdir()
        unknown = day / 'owner-file.txt'
        unknown.write_bytes(b'untouched')
        self.workflow.remove_empty_date({'run': self.current, 'cloud_layout': 'dated-v1'})
        self.assertEqual(unknown.read_bytes(), b'untouched')
        calls = [json.loads(line) for line in self.events.read_text().splitlines()]
        self.assertEqual([c[0] for c in calls], ['lsjson'])

    def test_rotation_deletes_and_removes_only_receipted_suffix_not_base(self):
        old, expired = self.old_copy(5 * 86400, 'b')
        base = server.date_directory(expired['run'])
        day = self.cloud / (base + '-2')
        day.mkdir()
        (self.cloud / 'scheduled-v1' / old.name).rename(day / old.name)
        unknown = self.cloud / base
        unknown.mkdir()
        (unknown / 'owner-file').write_bytes(b'untouched')
        expired.update(cloud_layout='dated-v2', cloud_directory=day.name,
                       cloud_metadata_checked=True, cloud_roundtrip_verified=False)
        server.atomic_json(self.state / 'receipts' / (expired['run'] + '.json'), expired)
        self.old_copy(0, 'a')
        self.workflow.rotate(self.current)
        self.assertFalse(day.exists())
        self.assertEqual((unknown / 'owner-file').read_bytes(), b'untouched')
        calls = [json.loads(line) for line in self.events.read_text().splitlines()]
        self.assertEqual([c[:2] for c in calls], [
            ['deletefile', server.REMOTE + day.name + '/' + old.name],
            ['lsjson', server.REMOTE + day.name], ['rmdir', server.REMOTE + day.name]])

    def test_full_upload_metadata_rotation_and_local_cleanup(self):
        old, expired = self.old_copy(4 * 86400)
        boundary, retained = self.old_copy(2 * 86400, 'c')
        unknown = self.cloud / 'manual.tar.gz'
        unknown.write_bytes(b'untouched')
        self.workflow.execute(self.current)
        records = {r['run']: r for r in self.records()}
        self.assertTrue(records[expired['run']]['cloud_deleted'])
        self.assertFalse(records[retained['run']]['cloud_deleted'])
        self.assertFalse(old.exists())
        self.assertFalse(boundary.exists())
        self.assertTrue((self.cloud / 'scheduled-v1' / boundary.name).exists())
        self.assertTrue(unknown.exists())
        current = self.state / 'runs' / self.current
        self.assertFalse((current / 'readback.tar.gz').exists())
        self.assertTrue((current / 'upload' / server.archive_name(self.current)).exists())
        self.assertFalse(Path(self.fixture.env['PAUSED']).exists())
        lines = self.journal.path.read_text()
        self.assertIn('Source unpause confirmed', lines)
        self.assertIn('encrypted_upload_metadata_checked', lines)
        self.assertIn('success', lines)
        self.assertNotIn('secret', lines)
        calls = [json.loads(line) for line in self.events.read_text().splitlines()]
        self.assertEqual([c[0] for c in calls], ['lsjson', 'lsjson', 'copy', 'lsjson', 'deletefile'])

    def test_transfer_failures_never_rotate_or_delete_previous(self):
        for failure in ('copy', 'lsjson', 'corrupt'):
            with self.subTest(failure=failure):
                # Each subcase needs a new unique run; failed directories must not be reused.
                current = run_id(self.now, {'copy': 'd', 'lsjson': 'e', 'corrupt': 'f'}[failure])
                old, _ = self.old_copy(4 * 86400 + 50, {'copy': '1', 'lsjson': '2', 'corrupt': '3'}[failure])
                self.workflow.env['CLOUD_FAIL'] = failure
                self.workflow.env['CORRUPT'] = '1' if failure == 'corrupt' else '0'
                with self.assertRaises(server.CloudError):
                    self.workflow.execute(current)
                self.assertTrue(old.exists())
                self.assertTrue((self.cloud / 'scheduled-v1' / old.name).exists())
                self.assertFalse((self.state / 'receipts' / (current + '.json')).exists())
        self.assertNotIn('deletefile', self.events.read_text())
        self.assertNotIn('secret', self.journal.path.read_text())

    def test_capture_failure_releases_pause_and_never_uploads(self):
        self.workflow.env['FAIL'] = 'snapshot'
        with self.assertRaises(server.CloudError):
            self.workflow.execute(self.current)
        self.assertFalse(self.events.exists())
        self.assertFalse(Path(self.fixture.env['PAUSED']).exists())
        self.assertFalse(self.records())

    def test_verifier_failure_blocks_upload(self):
        with mock.patch.object(self.workflow, 'verify', side_effect=server.CloudError('fixture')):
            with self.assertRaises(server.CloudError):
                self.workflow.execute(self.current)
        self.assertFalse(self.events.exists())

    def test_low_space_fails_before_capture(self):
        with mock.patch.object(server.shutil, 'disk_usage', return_value=type('Disk', (), {'free': 0})()):
            with self.assertRaises(Exception):
                self.workflow.execute(self.current)
        self.assertFalse((self.state / 'runs' / self.current).exists())
        self.assertFalse(self.events.exists())

    def test_rotation_failure_keeps_new_and_previous_original(self):
        old, _ = self.old_copy(4 * 86400)
        self.workflow.env['CLOUD_FAIL'] = 'deletefile'
        with self.assertRaises(server.CloudError):
            self.workflow.execute(self.current)
        self.assertTrue(old.exists())
        self.assertEqual(len(self.records()), 2)
        self.assertTrue((self.cloud / server.date_directory(self.current) / server.archive_name(self.current)).exists())
        self.assertNotIn('"event": "success"', self.journal.path.read_text())

    def test_future_receipt_blocks_run(self):
        self.old_copy(-1)
        with self.assertRaises(server.CloudError):
            self.workflow.execute(self.current)
        self.assertFalse(self.events.exists())

    def test_bad_receipt_and_symlink_are_fail_closed(self):
        old, record = self.old_copy(4 * 86400)
        path = self.state / 'receipts' / (record['run'] + '.json')
        value = json.loads(path.read_text())
        value['run'] = '../manual'
        path.write_text(json.dumps(value))
        with self.assertRaises(server.CloudError): self.records()
        path.unlink()
        path.symlink_to(old)
        with self.assertRaises(server.CloudError): self.records()

    def test_unreceipted_leftovers_and_changed_original_are_not_deleted(self):
        old, record = self.old_copy(86400)
        old.write_bytes(b'changed')
        self.old_copy(0, 'a')  # current receipt is only a fixture here
        stray = self.state / 'runs' / 'unknown'
        stray.mkdir()
        (stray / 'archive.tar.gz').write_bytes(b'unknown')
        with self.assertRaises(server.CloudError):
            self.workflow.rotate(self.current)
        self.assertTrue(old.exists())
        self.assertTrue((stray / 'archive.tar.gz').exists())
        self.assertFalse(self.events.exists())

    def test_receipt_update_survives_previous_interrupted_write(self):
        _, record = self.old_copy(4 * 86400)
        path = self.state / 'receipts' / (record['run'] + '.json')
        leftover = path.with_name(path.name + '.new')
        leftover.write_text('{"cloud_deleted":')
        record['cloud_deleted'] = True
        server.atomic_json(path, record)
        self.assertEqual(json.loads(path.read_text()), record)
        self.assertEqual(leftover.read_text(), '{"cloud_deleted":')

    def test_next_backup_ignores_but_preserves_interrupted_receipt_files(self):
        old, record = self.old_copy(4 * 86400)
        receipts = self.state / 'receipts'
        leftovers = [receipts / (record['run'] + suffix)
                     for suffix in ('.json.new', '.json.' + 'f' * 32 + '.new')]
        for path in leftovers:
            path.write_text('{"cloud_deleted":')
        self.workflow.execute(self.current)
        self.assertEqual(len(self.records()), 2)
        self.assertTrue(all(path.read_text() == '{"cloud_deleted":' for path in leftovers))
        self.assertFalse(old.exists())
        self.assertIn('"event": "success"', self.journal.path.read_text())

    def test_pending_receipts_never_authorize_cloud_rotation(self):
        old, record = self.old_copy(4 * 86400)
        receipt = self.state / 'receipts' / (record['run'] + '.json')
        receipt.rename(receipt.with_name(receipt.name + '.new'))
        self.workflow.execute(self.current)
        self.assertEqual(len(self.records()), 1)
        self.assertTrue(old.exists())
        self.assertTrue((self.cloud / 'scheduled-v1' / old.name).exists())
        self.assertNotIn('deletefile', self.events.read_text())

    def test_pending_receipts_reject_symlinks_public_modes_and_unknown_entries(self):
        _, record = self.old_copy(4 * 86400)
        receipt = self.state / 'receipts' / (record['run'] + '.json')
        pending = receipt.with_name(receipt.name + '.new')
        pending.symlink_to(receipt)
        with self.assertRaises(server.CloudError):
            self.records()
        pending.unlink()
        pending.write_text('{}')
        pending.chmod(0o644)
        with self.assertRaises(server.CloudError):
            self.records()
        pending.unlink()
        unknown = pending.with_name('unknown.new')
        unknown.write_text('{}')
        with self.assertRaises(server.CloudError):
            self.records()

    def test_same_run_refuses_retry(self):
        (self.state / 'runs' / self.current).mkdir()
        with self.assertRaises(FileExistsError):
            self.workflow.execute(self.current)
        self.assertFalse(self.events.exists())

    def test_journal_retention_size_cap_and_unknown_files(self):
        old = self.logs / (run_id(self.now - server.LOG_AGE - 1, '1') + '.jsonl')
        old.write_text('old')
        unknown = self.logs / 'manual.log'
        unknown.write_text('keep')
        journal = server.Journal(self.logs, run_id(self.now, '2'), self.now)
        self.assertFalse(old.exists())
        self.assertTrue(unknown.exists())
        with mock.patch.multiple(server, LOG_FILE=1024, LOG_TOTAL=4096):
            for i in range(100): journal.emit('bounded', counter=i)
            self.assertLessEqual(journal.path.stat().st_size, 1024)
            self.assertEqual(json.loads(journal.path.read_text().splitlines()[-1])['counter'], 99)
            recent = self.logs / (run_id(self.now - 1, '3') + '.jsonl')
            recent.write_bytes(b'x' * 4096)
            server.Journal(self.logs, run_id(self.now, '4'), self.now)
            self.assertFalse(recent.exists())
        self.assertTrue(unknown.exists())

    def test_progress_rejects_private_text_and_nonfinite_stats(self):
        for line in ('secret', '[source elapsed 00:00:01 | previous stage 00:00:00] secret',
                     '{"stats":{"bytes":NaN,"speed":1},"msg":"secret"}',
                     '{"stats":{"bytes":true,"speed":1}}'):
            server.safe_progress(line, self.journal)
        self.assertEqual(self.journal.path.read_text(), '')
        server.safe_progress('{"stats":{"bytes":10,"speed":20},"msg":"secret"}', self.journal)
        self.assertNotIn('secret', self.journal.path.read_text())
        self.assertIn('transfer_progress', self.journal.path.read_text())

    def test_timeout_terminates_child_and_runs_cleanup(self):
        marker = self.base / 'cleanup'
        code = "import signal,time,pathlib,sys; signal.signal(signal.SIGTERM, lambda *a: (pathlib.Path(sys.argv[1]).write_text('done'), sys.exit(0))); time.sleep(30)"
        with self.assertRaises(server.CloudError):
            server.phase([sys.executable, '-c', code, str(marker)], self.workflow.env,
                         self.journal, 'timeout_test', timeout=0.5)
        self.assertEqual(marker.read_text(), 'done')

    def test_main_rejects_missing_authorization_without_work(self):
        with mock.patch.object(sys, 'argv', ['runner']), mock.patch.object(server, 'Workflow') as workflow, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(server.main(), 1)
            workflow.assert_not_called()

    def test_main_lock_and_environment_contract(self):
        # Isolate main's admission from privileged production paths, not flock itself.
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(sys, 'argv', ['runner', '--confirm-external-mutation']))
            stack.enter_context(mock.patch.object(server.os, 'getuid', return_value=0))
            stack.enter_context(mock.patch.object(server, 'trusted_tree'))
            stack.enter_context(mock.patch.object(server, 'private', return_value=type('Stat', (), {'st_size': 1})()))
            stack.enter_context(mock.patch.object(server, 'digest', return_value=server.RCLONE_SHA))
            stack.enter_context(mock.patch.object(server.time, 'time', return_value=self.now))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            workflow = stack.enter_context(mock.patch.object(server, 'Workflow'))
            stack.enter_context(mock.patch.dict(os.environ, {'RCLONE_CONFIG': 'forbidden', 'PYTHONPATH': 'forbidden'}))
            lock = (self.state / 'workflow.lock').open('wb')
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                self.assertEqual(server.main(), 1)
                workflow.assert_not_called()
            finally:
                lock.close()
            handlers = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
            try:
                self.assertEqual(server.main(), 0)
            finally:
                for sig, handler in handlers.items(): signal.signal(sig, handler)
            env = workflow.call_args.args[1]
            self.assertEqual(set(env), {'PATH', 'HOME', 'LANG'})

    def test_units_and_installer_never_start_or_enable(self):
        service = (ROOT / 'systemd/hermes-backup.service').read_text()
        timer = (ROOT / 'systemd/hermes-backup.timer').read_text()
        self.assertIn('08:00:00 Europe/Moscow', timer)
        self.assertIn('Persistent=true', timer)
        self.assertIn('KillMode=mixed', service)
        self.assertIn('TimeoutStopSec=240s', service)
        self.assertIn('Restart=no', service)
        self.assertIn('/usr/bin/python3 -I ', service)

    def test_installer_copies_secrets_outside_package_and_only_reloads(self):
        target = self.base / 'installed'
        target.mkdir()
        package, keys, state, logs, units = [target / name for name in ('package', 'keys', 'state', 'logs', 'units')]
        units.mkdir()
        binary = self.base / 'staged-rclone'
        binary.write_bytes(b'fixture binary')
        args = type('Args', (), {'upload_config': str(self.keys / 'upload.conf'),
                                'recovery_config': str(self.keys / 'recovery.conf'),
                                'rclone_binary': str(binary), 'confirm_external_mutation': True})()
        with mock.patch.multiple(installer, PACKAGE=package, KEYS=keys, STATE=state, LOGS=logs, UNITS=units), \
                mock.patch.object(installer, 'preflight') as admission, \
                mock.patch.object(installer, 'digest', return_value=server.RCLONE_SHA), \
                mock.patch.object(installer.subprocess, 'run') as commands, contextlib.redirect_stdout(io.StringIO()):
            installer.install(args)
            admission.assert_called_once_with(args)
            calls = [c.args[0] for c in commands.call_args_list]
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0][0:2], ['systemd-analyze', 'verify'])
            self.assertEqual(calls[1], ['systemctl', 'daemon-reload'])
            self.assertEqual(server.read_config(keys / 'daily-upload.conf', server.CRYPT_ROOT, 'false'),
                             server.read_config(keys / 'daily-recovery.conf', server.CRYPT_ROOT, 'false'))
            self.assertEqual((keys / 'upload.conf').read_text(), CONFIG)
            self.assertEqual((keys / 'recovery.conf').read_text(), CONFIG)
            self.assertEqual((keys / 'upload.conf').stat().st_mode & 0o777, 0o600)
            self.assertEqual(keys.stat().st_mode & 0o777, 0o700)
            self.assertFalse((package / 'upload.conf').exists())
            self.assertTrue((package / 'capture.py').exists())
            self.assertTrue((self.keys / 'upload.conf').exists())
            # No silent overwrite even if admission were mistakenly bypassed.
            with self.assertRaises(FileExistsError): installer.install(args)

    def test_installer_missing_confirmation_has_no_mutation(self):
        args = type('Args', (), {'confirm_external_mutation': False})()
        with mock.patch.object(installer.os, 'getuid', return_value=0), \
                mock.patch.object(installer.subprocess, 'run') as commands, \
                mock.patch.object(Path, 'mkdir') as mkdir:
            with self.assertRaises(server.CloudError): installer.install(args)
            commands.assert_not_called()
            mkdir.assert_not_called()


class CalendarTest(unittest.TestCase):
    def test_moscow_midnight_month_and_year_boundaries_keep_every_run(self):
        for text in ('2026-10-31T20:59:59+00:00', '2026-10-31T21:00:00+00:00',
                     '2026-12-31T23:59:59+00:00', '2027-01-01T00:00:00+00:00'):
            with self.subTest(current=text):
                now = dt.datetime.fromisoformat(text)
                local = now.astimezone(server.ZoneInfo('Europe/Moscow'))
                cutoff = local.replace(hour=0, minute=0, second=0) - dt.timedelta(days=2)
                times = [cutoff - dt.timedelta(seconds=1), cutoff,
                         cutoff + dt.timedelta(hours=1), cutoff + dt.timedelta(days=1),
                         now - dt.timedelta(seconds=1), now]
                records = [{'run': run_id(int(t.timestamp()), char), 'created': int(t.timestamp()),
                            'cloud_deleted': False} for t, char in zip(times, 'abcdef')]
                self.assertEqual(server.rotation_candidates(records, records[-1]['run']), [records[0]])


if __name__ == '__main__':
    unittest.main()
