#!/usr/bin/env python3
"""Review regressions: isolated synthetic hosts, no SSH/Docker/network effects.
The original seven safety assertions failed on be6fb254 and 9cb6ade.
"""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('upstream_tests', ROOT / 'tests/migration_controller_test.py')
tests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tests)

class AdversarialSafety(unittest.TestCase):
    def setup_run(self, path, steps=4):
        helper = tests.ControllerTest()
        module = helper.module()
        c = module.Controller.create(path, 'owner-fixture', 'dm-fixture')
        site = tests.FixtureSite()
        for _ in range(steps):
            c.advance(site, now=1000)
        return helper, module, c, site

    def test_old_adapter_contract_cannot_admit_forward_effects(self):
        module = tests.ControllerTest().module()
        with tempfile.TemporaryDirectory() as tmp:
            c = module.Controller.create(Path(tmp) / 'run', 'owner-fixture', 'dm-fixture')
            site = tests.FixtureSite()
            site.call = lambda action, request: {'run_id': request['run_id'],
                                                 'ready': True, 'contract': 'migration-site-v1'}
            with self.assertRaises(module.Refused):
                c.advance(site, now=1000)
            self.assertEqual(c.status()['phase'], 'PREPARED')

    def test_target_start_does_not_run_after_preparation_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            helper, module, c, site = self.setup_run(Path(tmp) / 'run')
            helper.approve(c)
            c.advance(site, now=1000)
            original = site.call
            wall = [2799]
            def call(action, request):
                result = original(action, request)
                if action == 'source_probe':
                    wall[0] = 2801  # bounded RPC straddles prepare_deadline=2800
                if action == 'target_start':
                    result['started_at'] = wall[0]
                return result
            site.call = call
            with patch.object(module, 'clock_sample', side_effect=lambda _=None: {
                    'wall': wall[0], 'elapsed': wall[0], 'boot': 'injected-test-clock'}):
                c.advance(site)
            self.assertNotIn('target_start', site.calls,
                f"target started after expiry: phase={c.status()['phase']}, deadline={c.load()['prepare_deadline']}, start={c.load().get('started_at')}")

    def test_wall_clock_rollback_does_not_extend_elapsed_acceptance_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            helper, module, c, site = self.setup_run(Path(tmp) / 'run')
            helper.approve(c)
            for _ in range(2):
                c.advance(site, now=1000)
            original = site.call
            site.call = lambda action, req: ({'run_id': req['run_id'], 'evidence': None}
                if action == 'dialogue' else original(action, req))
            # 3800 real seconds since startup; NTP/manual clock moved backwards 3600.
            with patch.object(module, 'clock_sample', return_value={
                    'wall': 1200, 'elapsed': 4800, 'boot': 'injected-test-clock'}):
                c.advance(site)
            self.assertEqual(c.status()['phase'], 'FENCING_TARGET',
                             'wall-only deadline left target running beyond elapsed timeout')

    def test_autostarted_target_requires_delta_preservation_before_source_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, module, c, site = self.setup_run(Path(tmp) / 'run')
            self.assertFalse(c.load()['target_start_intent'])
            site.target_running = True  # unexpected reboot/autostart BEFORE controller start
            original = site.call
            def call(action, request):
                if action == 'target_fence':
                    site.target_running = False
                    return {'run_id': request['run_id']}
                if action == 'target_probe':
                    return {'run_id': request['run_id'], 'running': False,
                            'fenced': True, 'writers_stopped': True}
                return original(action, request)
            site.call = call
            c.rollback(now=1200)
            c.advance(site, now=1201)
            self.assertEqual(c.status()['phase'], 'PRESERVING_DELTA',
                             'target history discarded solely because local start intent was false')

    def test_unknown_phase_cannot_be_converted_to_prestart_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, module, c, _ = self.setup_run(Path(tmp) / 'run')
            state = c.load()
            state['phase'] = 'UNKNOWN_PHASE'
            module.atomic_json(c.path, state)
            with self.assertRaises(module.Refused):
                c.rollback(now=1200)

    def test_crash_after_admission_does_not_allow_late_first_freeze(self):
        with tempfile.TemporaryDirectory() as tmp:
            helper = tests.ControllerTest()
            module = helper.module()
            c = module.Controller.create(Path(tmp) / 'run', 'owner-fixture', 'dm-fixture')
            site = tests.FixtureSite()
            # Process dies after committing admission but before the first fence.
            with patch.object(c, 'watch', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    c.scheduled(site, 1000, 1060, clock=lambda: 1000)
            self.assertTrue(site.source_running)
            c = module.Controller(c.directory)
            def stop_after_first_transition(seconds):
                raise KeyboardInterrupt
            with self.assertRaises(KeyboardInterrupt):
                c.scheduled(site, 1000, 1060, clock=lambda: 1100, sleep=stop_after_first_transition)
            self.assertTrue(site.source_running, 'first freeze executed outside dated window after crash')

    def test_adapter_timeout_is_bounded_with_detached_pipe_holder(self):
        import hashlib
        import sys
        import time
        module = tests.ControllerTest().module()
        with tempfile.TemporaryDirectory() as tmp:
            adapter = Path(tmp) / 'adapter'
            adapter.write_text('#!' + sys.executable + '\n'
                'import subprocess,sys,time\n'
                'subprocess.Popen([sys.executable,"-c","import time; time.sleep(4)"], start_new_session=True)\n'
                'time.sleep(20)\n')
            adapter.chmod(0o700)
            site = module.CommandSite(adapter, hashlib.sha256(adapter.read_bytes()).hexdigest(), timeout=1)
            started = time.monotonic()
            with self.assertRaises(module.Refused):
                site.call('capture', {'run_id': 'fixture'})
            self.assertLess(time.monotonic() - started, 2.5,
                            'unbounded second communicate waits for escaped stdout holder')

    def test_clock_discontinuity_reboot_and_elapsed_expiry_fail_closed(self):
        samples = [
            {'wall': 1200, 'elapsed': 4800, 'boot': 'injected-test-clock'},
            {'wall': 2600, 'elapsed': 1200, 'boot': 'injected-test-clock'},
            {'wall': 1200, 'elapsed': 100, 'boot': 'different-boot'},
            {'wall': 2799, 'elapsed': 2801, 'boot': 'injected-test-clock'},
        ]
        for sample in samples:
            with self.subTest(sample=sample), tempfile.TemporaryDirectory() as tmp:
                helper, module, c, site = self.setup_run(Path(tmp) / 'run')
                helper.approve(c)
                c.advance(site, now=1000)
                c.advance(site, now=1000)
                c = module.Controller(c.directory)  # Durable anchor, not process memory.
                before = list(site.calls)
                with patch.object(module, 'clock_sample', return_value=sample):
                    c.advance(site)
                self.assertEqual(c.status()['phase'], 'FENCING_TARGET')
                self.assertEqual(site.calls, before)
                self.assertFalse(site.source_running)

    def test_clock_uncertainty_cannot_approve_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            helper, module, c, site = self.setup_run(Path(tmp) / 'run')
            with patch.object(module, 'clock_sample', return_value={
                    'wall': 1200, 'elapsed': 4800, 'boot': 'injected-test-clock'}):
                with self.assertRaises(module.Refused):
                    helper.approve(c, now=None)
            self.assertEqual(c.status()['phase'], 'AWAITING_CONFIRM')
            self.assertFalse(site.target_running)

    def test_target_start_rpc_expiry_never_enters_waiting(self):
        with tempfile.TemporaryDirectory() as tmp:
            helper, module, c, site = self.setup_run(Path(tmp) / 'run')
            helper.approve(c)
            c.advance(site, now=1000)
            original = site.call
            wall = [2799]
            def call(action, request):
                result = original(action, request)
                if action == 'target_start':
                    self.assertEqual(request['effect_expires_at'], 2800)
                    wall[0] = 2801
                    result['started_at'] = 2801  # Adapter violated expiry; preserve uncertainty.
                return result
            site.call = call
            with patch.object(module, 'clock_sample', side_effect=lambda _=None: {
                    'wall': wall[0], 'elapsed': wall[0], 'boot': 'injected-test-clock'}):
                c.advance(site)
            self.assertEqual(c.status()['phase'], 'FENCING_TARGET')
            self.assertTrue(c.load()['target_start_intent'])
            self.assertFalse(site.source_running)

    def test_dialogue_rpc_straddling_deadline_never_accepts(self):
        for unavailable in (False, True):
            with self.subTest(unavailable=unavailable), tempfile.TemporaryDirectory() as tmp:
                helper, module, c, site = self.setup_run(Path(tmp) / 'run')
                helper.approve(c)
                c.advance(site, now=1000)
                c.advance(site, now=1000)
                wall = [2799]
                def call(action, request):
                    self.assertEqual(action, 'dialogue')
                    wall[0] = 2801
                    if unavailable:
                        raise module.Refused('fixture unavailable')
                    return {'run_id': request['run_id'], 'evidence': helper.evidence(c)}
                site.call = call
                with patch.object(module, 'clock_sample', side_effect=lambda _=None: {
                        'wall': wall[0], 'elapsed': wall[0], 'boot': 'injected-test-clock'}):
                    c.advance(site)
                self.assertEqual(c.status()['phase'], 'FENCING_TARGET')

    def test_missing_or_malformed_delta_is_retryable_without_phase_change(self):
        variants = [{}, {'delta_digest': None}, {'delta_digest': ''},
                    {'delta_digest': 'g' * 64}, {'delta_digest': 'd' * 63},
                    {'delta_digest': ['d' * 64]}]
        for delta in variants:
            with self.subTest(delta=delta), tempfile.TemporaryDirectory() as tmp:
                helper, module, c, site = self.setup_run(Path(tmp) / 'run')
                c.rollback(now=1200)
                def call(action, request):
                    receipt = {'run_id': request['run_id']}
                    if action == 'target_probe':
                        receipt.update(running=False, fenced=True, writers_stopped=True)
                    elif action == 'preserve_delta':
                        receipt.update(verified=True, independent_copy_verified=True, **delta)
                    return receipt
                site.call = call
                c.advance(site, now=1201)
                before = c.path.read_bytes()
                with self.assertRaises(module.Refused):
                    c.advance(site, now=1202)
                self.assertEqual(c.path.read_bytes(), before)
                self.assertEqual(c.status()['phase'], 'PRESERVING_DELTA')

    def test_delta_receipt_requires_exact_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            helper, module, c, site = self.setup_run(Path(tmp) / 'run')
            helper.approve(c)
            for _ in range(2):
                c.advance(site, now=1000)
            c.rollback(now=1200)
            def call(action, request):
                receipt = {'run_id': request['run_id']}
                if action == 'target_fence':
                    site.target_running = False
                elif action == 'target_probe':
                    receipt.update(running=False, fenced=True, writers_stopped=True)
                elif action == 'preserve_delta':
                    receipt.update(verified=True, independent_copy_verified=True, delta_digest=None)
                else:
                    self.fail('unexpected action: ' + action)
                return receipt
            site.call = call
            c.advance(site, now=1201)
            with self.assertRaises(module.Refused):
                c.advance(site, now=1202)

if __name__ == '__main__':
    unittest.main(verbosity=2)
