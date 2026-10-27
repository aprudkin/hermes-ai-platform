#!/usr/bin/env python3
"""Real controller-process death; all side effects are private JSON fixtures."""
import importlib.util
import os
from pathlib import Path
import signal
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('upstream_tests', ROOT/'tests/migration_controller_test.py')
tests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tests)

class DeathTests(unittest.TestCase):
    def test_sigkill_admission_and_freeze_intent_never_refreeze_late(self):
        for when in ('admitted', 'before', 'after'):
            with self.subTest(when=when), tempfile.TemporaryDirectory() as tmp:
                module = tests.ControllerTest().module()
                c = module.Controller.create(Path(tmp) / 'run', 'owner-fixture', 'dm-fixture')
                site = tests.FixtureSite()
                ledger = Path(tmp) / 'frozen.json'
                original = site.call
                def effect(action, request):
                    if action == 'source_fence':
                        self.assertEqual(request['effect_expires_at'], 1060)
                        if when == 'before':
                            os.kill(os.getpid(), signal.SIGKILL)
                        module.atomic_json(ledger, {'operation_id': request['operation_id']})
                        if when == 'after':
                            os.kill(os.getpid(), signal.SIGKILL)
                    return original(action, request)
                def watch(*args, **kwargs):
                    if when == 'admitted':
                        os.kill(os.getpid(), signal.SIGKILL)
                    c.advance(site, now=1000)
                pid = os.fork()
                if pid == 0:
                    try:
                        site.call = effect
                        c.watch = watch
                        c.scheduled(site, 1000, 1060, clock=lambda: 1000)
                    finally:
                        os._exit(99)
                _, status = os.waitpid(pid, 0)
                self.assertTrue(os.WIFSIGNALED(status))
                self.assertEqual(os.WTERMSIG(status), signal.SIGKILL)
                c = module.Controller(c.directory)
                self.assertEqual(c.load()['freeze_latest'], 1060)
                self.assertEqual(c.load()['source_fence_intent'], when != 'admitted')
                self.assertEqual(ledger.exists(), when == 'after')
                c.advance(site, now=1100)
                self.assertEqual(site.calls, [])  # No late first/repeated effect.
                self.assertEqual(c.status()['phase'], 'BLOCKED' if when == 'admitted' else 'FENCING_TARGET')

    def test_sigkill_before_and_after_start_effect(self):
        for when in ('before', 'after'):
            with self.subTest(when=when), tempfile.TemporaryDirectory() as tmp:
                helper = tests.ControllerTest()
                module = helper.module()
                c = module.Controller.create(Path(tmp)/'run', 'owner-fixture', 'dm-fixture')
                site = tests.FixtureSite()
                for _ in range(4):
                    c.advance(site, now=1000)
                helper.approve(c)
                c.advance(site, now=1000)
                ledger = Path(tmp)/'effects.json'
                operation_log = Path(tmp)/'requests'
                original = site.call
                def durable_call(action, request):
                    if action == 'target_start':
                        with operation_log.open('a') as stream:
                            stream.write(request['operation_id']+'\n')
                            stream.flush()
                            os.fsync(stream.fileno())
                        if ledger.exists():
                            import json
                            site.target_running = True
                            return json.loads(ledger.read_text())
                        result = original(action, request)
                        module.atomic_json(ledger, result)
                        return result
                    return original(action, request)
                def killed_call(action, request):
                    if action == 'target_start' and when == 'before':
                        os.kill(os.getpid(), signal.SIGKILL)
                    result = durable_call(action, request)
                    if action == 'target_start' and when == 'after':
                        os.kill(os.getpid(), signal.SIGKILL)
                    return result
                pid = os.fork()
                if pid == 0:
                    try:
                        site.call = killed_call
                        c.advance(site, now=1000)
                    finally:
                        os._exit(99)
                _, status = os.waitpid(pid, 0)
                self.assertTrue(os.WIFSIGNALED(status))
                self.assertEqual(os.WTERMSIG(status), signal.SIGKILL)
                c = module.Controller(c.directory)
                self.assertEqual(c.status()['phase'], 'STARTING_TARGET')
                self.assertTrue(c.load()['target_start_intent'])
                self.assertEqual(ledger.exists(), when == 'after')
                site.call = durable_call
                c.advance(site, now=2000)
                self.assertEqual(c.status()['phase'], 'WAITING')
                self.assertEqual(c.load()['deadline'], 2800)
                ids = operation_log.read_text().splitlines()
                self.assertEqual(len(ids), 2 if when == 'after' else 1)
                self.assertEqual(len(set(ids)), 1)
                print(f'{when}: SIGKILL confirmed, durable intent and retry operation ID preserved, deadline=2800')

if __name__ == '__main__':
    unittest.main(verbosity=2)
