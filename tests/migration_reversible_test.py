#!/usr/bin/env python3
"""Synthetic hosts only; production primitives, gzip, restore and local HTTP."""
import json
from pathlib import Path
import sys
import unittest
from unittest import mock
from migration_host_test import HostOperationsTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from hermes_migration_controller import Refused


class ReversibleTest(unittest.TestCase):
    setUp = HostOperationsTest.setUp
    add_bytes = staticmethod(HostOperationsTest.add_bytes)
    save_fixture = HostOperationsTest.save_fixture
    setup_operations = HostOperationsTest.setup_operations

    def prepare_host(self):
        self.ops = self.setup_operations()
        self.run_id = 'a' * 32
        docker = self.bin / 'docker'
        docker.write_text(docker.read_text().replace(
            "if args[0] in ('update', 'stop'):",
            "if args[0] in ('update', 'stop', 'start'):").replace(
            "data['container']['HostConfig']['RestartPolicy'] = {'Name': 'no', 'MaximumRetryCount': 0}",
            "policy = args[1].split('=', 1)[1].split(':')\n"
            "        data['container']['HostConfig']['RestartPolicy'] = {'Name': policy[0], 'MaximumRetryCount': int(policy[1]) if len(policy)>1 else 0}").replace(
            "    else:\n        data['container']['State'] = dict(Running=False",
            "    elif args[0] == 'start':\n"
            "        data['container']['State'] = dict(Running=True, Paused=False, Restarting=False, Dead=False, Pid=123, Status='running')\n"
            "    else:\n        data['container']['State'] = dict(Running=False"))
        self.proof = dict(run_id=self.run_id, target_fenced=True, persistent_fence=True,
                          outstanding_operations_revoked=True, no_target_activity_verified=True,
                          safe_to_resume=True, cancelled_jobs_preserved=True, replay_reviewed=True,
                          reconciliation_digest='b' * 64)
        self.guard_calls = []

    def guard(self):
        self.guard_calls.append(True)
        return dict(self.proof)

    def prepare_docker26_host(self):
        self.prepare_host()
        # Observed Docker 26.1.5 default: unlike the portable archive contract,
        # this does not mask /proc/interrupts. No security override was used.
        self.container['HostConfig']['MaskedPaths'] = [
            '/proc/asound', '/proc/acpi', '/proc/kcore', '/proc/keys',
            '/proc/latency_stats', '/proc/timer_list', '/proc/timer_stats',
            '/proc/sched_debug', '/proc/scsi', '/sys/firmware',
            '/sys/devices/virtual/powercap']
        self.container['HostConfig']['ReadonlyPaths'] = [
            '/proc/bus', '/proc/fs', '/proc/irq', '/proc/sys', '/proc/sysrq-trigger']
        self.container['HostConfig']['RestartPolicy'] = dict(Name='on-failure', MaximumRetryCount=3)
        self.save_fixture()

    def test_docker26_masks_allow_only_original_in_place_recovery(self):
        self.prepare_docker26_host()
        with mock.patch.dict('os.environ', self.env):
            with self.assertRaisesRegex(self.module.bundle.BundleError, 'custom masked paths'):
                self.module.bundle.validate_container(self.container, self.root, 'hermes')
            self.assertTrue(self.ops.fence(self.run_id)['docker_fenced'])
            original = (self.opsdir / 'original.json').read_bytes()
            self.assertEqual(json.loads(original), self.container)
            with self.assertRaisesRegex(Refused, 'cold capture failed'):
                self.ops.capture(self.run_id)
            self.assertFalse((self.opsdir / 'capture.json').exists())
            self.assertFalse((self.opsdir / 'full.tar.gz').exists())
            self.assertNotIn('docker image save', self.log.read_text())
            self.assertTrue(self.ops.recover(self.run_id, self.guard)['running'])
        self.assertEqual(json.loads(self.fixture.read_text())['container']['HostConfig'],
                         self.container['HostConfig'])
        self.assertEqual((self.opsdir / 'original.json').read_bytes(), original)
        self.assertEqual(self.log.read_text().count('docker start '), 1)

    def test_docker26_in_place_preserves_other_admission_gates(self):
        import copy
        self.prepare_docker26_host()
        changes = [('HostConfig', 'MaskedPaths', []),
                   ('HostConfig', 'MaskedPaths', ['/proc/keys']),
                   ('HostConfig', 'ReadonlyPaths', []),
                   ('HostConfig', 'Privileged', True),
                   ('HostConfig', 'NetworkMode', 'none'),
                   ('HostConfig', 'PidMode', 'host'),
                   ('HostConfig', 'Runtime', 'unknown'),
                   ('Config', 'OpenStdin', True),
                   ('Config', 'Cmd', ['other'])]
        with mock.patch.dict('os.environ', self.env):
            for section, key, value in changes:
                with self.subTest(section=section, key=key, value=value):
                    data = json.loads(self.fixture.read_text())
                    data['container'] = copy.deepcopy(self.container)
                    data['container'][section][key] = value
                    self.fixture.write_text(json.dumps(data))
                    with self.assertRaises(self.module.bundle.BundleError):
                        self.ops.fence(self.run_id)
                    self.assertFalse((self.opsdir / 'original.json').exists())
                    self.assertFalse(self.ops.anchor.exists())
            self.assertNotIn('docker update', self.log.read_text())
            self.assertNotIn('docker stop', self.log.read_text())

    def test_docker26_original_binding_rejects_mutations_without_start(self):
        import copy
        from hermes_migration_controller import atomic_json
        self.prepare_docker26_host()
        with mock.patch.dict('os.environ', self.env):
            self.ops.fence(self.run_id)
            frozen = json.loads(self.fixture.read_text())
            for section, key, value in [('HostConfig', 'MaskedPaths', []),
                                        ('HostConfig', 'ReadonlyPaths', []),
                                        ('HostConfig', 'Memory', 99),
                                        ('Config', 'User', '1234')]:
                with self.subTest(section=section, key=key):
                    changed = copy.deepcopy(frozen)
                    changed['container'][section][key] = value
                    self.fixture.write_text(json.dumps(changed))
                    with self.assertRaises(Refused):
                        self.ops.recover(self.run_id, self.guard)
            for key, value in [('Id', 'f' * 64), ('Image', 'sha256:' + 'f' * 64),
                               ('Mounts', [])]:
                with self.subTest(key=key):
                    changed = copy.deepcopy(frozen)
                    changed['container'][key] = value
                    self.fixture.write_text(json.dumps(changed))
                    with self.assertRaises(Refused):
                        self.ops.recover(self.run_id, self.guard)
            self.fixture.write_text(json.dumps(frozen))
            original = copy.deepcopy(self.container)
            original['HostConfig']['MaskedPaths'] = []
            atomic_json(self.opsdir / 'original.json', original)
            with self.assertRaisesRegex(Refused, 'original runtime receipt changed'):
                self.ops.recover(self.run_id, self.guard)
            self.assertNotIn('docker start ', self.log.read_text())

    def test_recovery_blocks_missing_or_changed_current_proofs(self):
        self.prepare_docker26_host()
        with mock.patch.dict('os.environ', self.env):
            self.ops.fence(self.run_id)
            for field in self.proof:
                if field == 'reconciliation_digest':
                    bad = 'wrong'
                elif field == 'run_id':
                    bad = 'c' * 32
                else:
                    bad = False
                with self.subTest(field=field), self.assertRaises(Refused):
                    self.ops.recover(self.run_id, lambda: dict(self.proof, **{field: bad}))
            self.assertNotIn('docker start ', self.log.read_text())
            original = (self.opsdir / 'original.json').read_bytes()
            calls = []
            def changed():
                calls.append(True)
                return dict(self.proof, cancelled_jobs_preserved=len(calls) == 1)
            with self.assertRaises(Refused):
                self.ops.recover(self.run_id, changed)
            self.assertNotIn('docker start ', self.log.read_text())
            self.assertEqual((self.opsdir / 'original.json').read_bytes(), original)

    def test_recovered_receipt_cannot_be_forged_or_outdate_reconciliation(self):
        self.prepare_docker26_host()
        from hermes_migration_controller import atomic_json
        with mock.patch.dict('os.environ', self.env):
            self.ops.fence(self.run_id)
            self.ops.recover(self.run_id, self.guard)
            path = self.opsdir / 'recovery.json'
            receipt = json.loads(path.read_text())
            atomic_json(path, dict(receipt, run_id='c' * 32))
            with self.assertRaises(Refused):
                self.ops.recover(self.run_id, self.guard)
            atomic_json(path, receipt)
            self.proof['reconciliation_digest'] = 'd' * 64
            result = self.ops.recover(self.run_id, self.guard)
            self.assertEqual(result['reconciliation_digest'], 'd' * 64)
            self.assertEqual(self.log.read_text().count('docker start '), 1)

    def prepare_integration(self):
        import importlib
        import time
        from migration_notice_test import NoticeTest
        from hermes_migration_controller import Controller
        self.prepare_host()
        notice = NoticeTest()
        notice.setUp()
        self.addCleanup(notice.doCleanups)
        helper = Path(__file__).resolve().parents[1] / 'scripts/hermes_migration_preparation.py'
        self.assertTrue(helper.exists(), 'composed preparation adapter missing')
        preparation = importlib.import_module('hermes_migration_preparation')
        from hermes_migration_recovery import RecoveryStage
        from migration_reversible_fixture import SyntheticAuthority
        self.authority = SyntheticAuthority(self)
        custody = self.base / 'custody'
        custody.mkdir(mode=0o700)
        self.site = preparation.PreparationSite(self.ops, RecoveryStage(custody), notice.sender(), self.authority)
        self.controller = Controller.create(self.base / 'controller', '42', '42', preparation_seconds=60)
        self.run_id = self.controller.load()['run_id']
        self.authority.bind(self.run_id)
        self.notice, self.custody = notice, custody
        return time.time()

    def test_integrated_missing_approval_recovers_original_without_target_start(self):
        now = self.prepare_integration()
        notice, custody = self.notice, self.custody
        with mock.patch.dict('os.environ', self.env):
            for phase in ('FENCING_SOURCE', 'CAPTURING', 'NOTIFYING_READY', 'AWAITING_CONFIRM'):
                self.assertEqual(self.controller.advance(self.site, now=now)['phase'], phase)
            state = self.controller.load()
            original = (self.opsdir / 'original.json').read_bytes()
            archive = (self.opsdir / 'full.tar.gz').read_bytes()
            self.assertEqual(len(notice.requests), 1)
            self.assertEqual(self.controller.advance(self.site, now=now + 61)['phase'], 'FENCING_TARGET')
            self.assertEqual(self.controller.advance(self.site, now=now + 61)['phase'], 'RECOVERING_SOURCE')
            self.assertEqual(self.controller.advance(self.site, now=now + 61)['phase'], 'ABORTED')
            self.assertEqual(self.controller.load()['prepare_deadline'], state['prepare_deadline'])
            self.assertEqual(self.controller.advance(self.site, now=now + 62)['phase'], 'ABORTED')
        self.assertEqual((self.opsdir / 'original.json').read_bytes(), original)
        self.assertEqual((self.opsdir / 'full.tar.gz').read_bytes(), archive)
        self.assertEqual((custody / 'full.tar.gz').read_bytes(), archive)
        stage = json.loads((custody / 'receipt.json').read_text())
        self.assertFalse(stage['ready'])
        self.assertFalse(stage['independent_copy_verified'])
        self.assertFalse(stage['runtime_started'])
        self.assertEqual(self.log.read_text().count('docker start '), 1)
        self.assertTrue(self.authority.current()['revoked'])
        self.assertFalse(self.authority.current()['target_running'])
        for name, original_bytes in self.authority.processed.items():
            self.assertEqual((self.authority.profile / name).read_bytes(), original_bytes)
            self.assertEqual((custody / 'restored/data/profiles/manager' / name).read_bytes(), original_bytes)

    def test_forward_expiry_rechecked_at_each_host_effect(self):
        now = self.prepare_integration()
        with mock.patch.dict('os.environ', self.env):
            self.controller.advance(self.site, now=now)
            original_run = self.module.bundle.run
            def crossing(command, **kwargs):
                result = original_run(command, **kwargs)
                if command[:2] == ['docker', 'update']:
                    self.authority.save(expired=True)
                return result
            with mock.patch.object(self.module.bundle, 'run', side_effect=crossing):
                with self.assertRaises(Refused):
                    self.controller.advance(self.site, now=now)
            self.assertNotIn('docker stop ', self.log.read_text())
            self.assertEqual(self.controller.load()['phase'], 'FENCING_SOURCE')
            # The controller's unchanged deadline still drives recovery, not retry.
            self.controller.advance(self.site, now=now + 61)
            self.controller.advance(self.site, now=now + 61)
            self.assertEqual(self.controller.advance(self.site, now=now + 61)['phase'], 'ABORTED')
        self.assertNotIn('docker start ', self.log.read_text())

    def test_notice_loss_does_not_resend_and_recovers_at_original_deadline(self):
        now = self.prepare_integration()
        self.notice.mode = 'lost'
        with mock.patch.dict('os.environ', self.env):
            for _ in range(3):
                self.controller.advance(self.site, now=now)
            deadline = self.controller.load()['prepare_deadline']
            for _ in range(2):
                with self.assertRaises(Refused):
                    self.controller.advance(self.site, now=now)
            self.assertEqual(len(self.notice.requests), 1)
            self.assertEqual(self.controller.load()['phase'], 'NOTIFYING_READY')
            for phase in ('FENCING_TARGET', 'RECOVERING_SOURCE', 'ABORTED'):
                self.assertEqual(self.controller.advance(self.site, now=now + 61)['phase'], phase)
            self.assertEqual(self.controller.load()['prepare_deadline'], deadline)
        self.assertEqual(self.log.read_text().count('docker start '), 1)
        self.assertEqual(len(self.notice.requests), 1)

    def test_unknown_target_or_new_cancellation_blocks_then_reconciles(self):
        now = self.prepare_integration()
        with mock.patch.dict('os.environ', self.env):
            for _ in range(4):
                self.controller.advance(self.site, now=now)
            self.controller.advance(self.site, now=now + 61)
            self.authority.save(unreachable=True)
            with self.assertRaises(Refused):
                self.controller.advance(self.site, now=now + 61)
            self.assertEqual(self.controller.load()['phase'], 'FENCING_TARGET')
            self.assertNotIn('docker start ', self.log.read_text())
            self.authority.save(unreachable=False)
            self.controller.advance(self.site, now=now + 61)
            jobs = self.authority.profile / 'jobs.json'
            jobs.write_text('{"cancelled-job":{"enabled":false},"new-cancellation":true}\n')
            with self.assertRaises(Refused):
                self.controller.advance(self.site, now=now + 61)
            self.assertNotIn('docker start ', self.log.read_text())
            policy = self.authority.current()['policy']
            policy['jobs.json'] = self.module.bundle.digest_file(jobs)['sha256']
            self.authority.save(policy=policy)
            self.assertEqual(self.controller.advance(self.site, now=now + 61)['phase'], 'ABORTED')
            self.assertIn('new-cancellation', jobs.read_text())
            self.assertIn('uncertain', (self.authority.profile / 'effects.json').read_text())
            self.assertEqual((self.authority.profile / 'result.txt').read_text(), 'completed synthetic result\n')

    def test_target_activity_never_uses_short_recovery_or_discards_delta(self):
        now = self.prepare_integration()
        with mock.patch.dict('os.environ', self.env):
            for _ in range(4):
                self.controller.advance(self.site, now=now)
            self.authority.save(target_activity=True)
            delta = self.authority.directory / 'target-delta'
            delta.write_bytes(b'new uncertain target work')
            self.controller.advance(self.site, now=now + 61)
            self.assertEqual(self.controller.advance(self.site, now=now + 61)['phase'], 'PRESERVING_DELTA')
            with self.assertRaises(Refused):
                self.controller.advance(self.site, now=now + 61)
            self.assertEqual(delta.read_bytes(), b'new uncertain target work')
            self.assertNotIn('docker start ', self.log.read_text())

    def test_absent_production_authority_refuses_admission_without_effects(self):
        from hermes_migration_preparation import PreparationSite
        from hermes_migration_controller import Controller
        self.prepare_host()
        controller = Controller.create(self.base / 'controller', '42', '42')
        with self.assertRaises(Refused):
            controller.advance(PreparationSite(self.ops, None, None))
        self.assertEqual(controller.load()['phase'], 'PREPARED')
        self.assertFalse(self.log.exists())

    def test_sigkill_recovery_start_intent_before_and_after_effect(self):
        import signal
        import subprocess
        import time
        from hermes_migration_host import read_private
        for boundary in ('before', 'after'):
            with self.subTest(boundary=boundary):
                case = ReversibleTest()
                case.setUp()
                self.addCleanup(case.doCleanups)
                now = case.prepare_integration()
                with mock.patch.dict('os.environ', case.env):
                    for _ in range(4):
                        case.controller.advance(case.site, now=now)
                    case.controller.advance(case.site, now=now + 61)
                    case.controller.advance(case.site, now=now + 61)
                before = case.controller.load()
                original = (case.opsdir / 'original.json').read_bytes()
                marker = case.base / 'start-boundary'
                code = '''
import os, sys, time
from pathlib import Path
sys.path[:0] = [sys.argv[1], sys.argv[2]]
from hermes_migration_controller import Controller
from hermes_migration_host import HostOperations
from hermes_migration_preparation import PreparationSite
from migration_reversible_fixture import SyntheticAuthority
import hermes_backup_bundle as bundle
base = Path(sys.argv[3])
authority = object.__new__(SyntheticAuthority)
authority.directory = base / 'synthetic-authority'
authority.path = authority.directory / 'state.json'
authority.profile = Path(sys.argv[4]) / 'data/profiles/manager'
original = bundle.run
def pause(command, **kwargs):
    if command[:2] != ['docker', 'start']:
        return original(command, **kwargs)
    if sys.argv[6] == 'after':
        original(command, **kwargs)
    with (base / 'start-boundary').open('xb') as stream:
        stream.write(b'ready'); stream.flush(); os.fsync(stream.fileno())
    while True:
        time.sleep(1)
bundle.run = pause
site = PreparationSite(HostOperations(sys.argv[4], base / 'operations'), None, None, authority)
Controller(base / 'controller').advance(site, now=float(sys.argv[5]))
'''
                repo = Path(__file__).resolve().parents[1]
                child = subprocess.Popen([sys.executable, '-c', code, str(repo / 'scripts'),
                                          str(repo / 'tests'), str(case.base), str(case.root),
                                          str(now + 61), boundary], env=case.env,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    limit = time.monotonic() + 10
                    while not marker.exists() and child.poll() is None and time.monotonic() < limit:
                        time.sleep(.02)
                    self.assertTrue(marker.exists(), 'recovery did not reach start boundary')
                    record = read_private(case.opsdir / 'operation.json')
                    self.assertTrue(record['revoked'])
                    self.assertEqual(record['recovery_step'], 'START_INTENT')
                    self.assertEqual(record['recovery_operation_id'], case.run_id + ':source_recover')
                    with mock.patch.dict('os.environ', case.env), self.assertRaisesRegex(Refused, 'busy'):
                        case.controller.advance(case.site, now=now + 61)
                    child.kill()
                    self.assertEqual(child.wait(timeout=5), -signal.SIGKILL)
                finally:
                    if child.poll() is None:
                        child.kill()
                    child.wait(timeout=5)
                self.assertEqual(case.controller.load(), before)
                self.assertEqual((case.opsdir / 'original.json').read_bytes(), original)
                with mock.patch.dict('os.environ', case.env):
                    if boundary == 'before':
                        with self.assertRaisesRegex(Refused, 'uncertain source start'):
                            case.controller.advance(case.site, now=now + 61)
                        self.assertNotIn('docker start ', case.log.read_text())
                    else:
                        self.assertEqual(case.controller.advance(case.site, now=now + 61)['phase'], 'ABORTED')
                        self.assertEqual(case.log.read_text().count('docker start '), 1)
                self.assertEqual(case.controller.load()['prepare_deadline'], before['prepare_deadline'])

    def test_failed_capture_and_partial_fence_can_recover_without_replaying_capture(self):
        now = self.prepare_integration()
        with mock.patch.dict('os.environ', self.env):
            self.controller.advance(self.site, now=now)
            self.controller.advance(self.site, now=now)
        with mock.patch.dict('os.environ', dict(self.env, FAIL='snapshot')):
            with self.assertRaises(Refused):
                self.controller.advance(self.site, now=now)
        pending = self.opsdir / 'full.tar.gz.pending'
        self.assertTrue(pending.exists())
        captured = pending.read_bytes()
        with mock.patch.dict('os.environ', self.env):
            for phase in ('FENCING_TARGET', 'RECOVERING_SOURCE', 'ABORTED'):
                self.assertEqual(self.controller.advance(self.site, now=now + 61)['phase'], phase)
        self.assertEqual(pending.read_bytes(), captured)
        self.assertFalse((self.opsdir / 'capture.json').exists())
        self.assertFalse(self.notice.requests)

    def test_partial_stop_error_stays_watchable_and_recovers_saved_settings(self):
        now = self.prepare_integration()
        with mock.patch.dict('os.environ', self.env):
            self.controller.advance(self.site, now=now)
        with mock.patch.dict('os.environ', dict(self.env, FAIL='stop')):
            with self.assertRaises(Exception) as failure:
                self.controller.advance(self.site, now=now)
            self.assertIsInstance(failure.exception, Refused, 'watch loop must retain and retry the phase')
        self.assertEqual(self.controller.load()['phase'], 'FENCING_SOURCE')
        with mock.patch.dict('os.environ', self.env):
            for phase in ('FENCING_TARGET', 'RECOVERING_SOURCE', 'ABORTED'):
                self.assertEqual(self.controller.advance(self.site, now=now + 61)['phase'], phase)
        self.assertEqual(json.loads(self.fixture.read_text())['container']['HostConfig'], self.container['HostConfig'])
        self.assertEqual(self.log.read_text().count('docker stop '), 1)

    def test_controller_original_settings_binding_checked_before_recovery(self):
        now = self.prepare_integration()
        with mock.patch.dict('os.environ', self.env):
            for _ in range(4):
                self.controller.advance(self.site, now=now)
            self.controller.advance(self.site, now=now + 61)
            self.controller.advance(self.site, now=now + 61)
            request = dict(self.controller.load(), operation_id=self.run_id + ':source_recover',
                           saved_states_digest='0' * 64)
            with self.assertRaises(Refused):
                self.site.call('source_recover', request)
            self.assertNotIn('docker start ', self.log.read_text())

    def test_original_settings_recovered_once_after_current_guard(self):
        self.prepare_host()
        self.assertTrue(hasattr(self.ops, 'recover'), 'guarded source recovery missing')
        with mock.patch.dict('os.environ', self.env):
            self.ops.fence(self.run_id)
            original = (self.opsdir / 'original.json').read_bytes()
            result = self.ops.recover(self.run_id, self.guard)
            self.assertTrue(result['running'])
            self.assertTrue(result['safe_to_resume'])
            self.assertTrue(result['cancelled_jobs_preserved'])
            self.assertTrue(result['replay_reviewed'])
            self.assertEqual(self.ops.recover(self.run_id, self.guard), result)
            with self.assertRaises(Refused):
                self.ops.capture(self.run_id)
        current = json.loads(self.fixture.read_text())['container']
        self.assertEqual(current['HostConfig'], self.container['HostConfig'])
        self.assertEqual((self.opsdir / 'original.json').read_bytes(), original)
        self.assertEqual(self.log.read_text().count('docker start '), 1)
        self.assertGreaterEqual(len(self.guard_calls), 3)


if __name__ == '__main__':
    unittest.main(defaultTest='ReversibleTest')
