#!/usr/bin/env python3
"""Admission observations cannot authorize effects; no host/network operations."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from hermes_migration_controller import Controller, Refused
from hermes_migration_preparation import PreparationSite


class NoEffects:
    def __getattr__(self, name):
        raise AssertionError('diagnostic touched effect adapter: ' + name)


class AdmissionTest(unittest.TestCase):
    def test_inventory_cannot_promote_claimed_proofs_even_with_supplied_authority(self):
        # Explicit opt-in diagnostic mode must not acquire a lease or call effects.
        import inspect
        self.assertIn('inventory', inspect.signature(PreparationSite).parameters)
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller.create(Path(directory) / 'controller', '42', '42')
            before = controller.load()
            gates = [row['gate'] for row in PreparationSite(None, None, None).diagnose()['gates']]
            inventory = {gate: {'verified': True, 'ready': True} for gate in gates}
            inventory.update(ready=True, independent_copy_verified=True, runtime_started=True)
            site = PreparationSite(NoEffects(), NoEffects(), NoEffects(),
                                   authority=NoEffects(), inventory=inventory)
            report = site.diagnose()
            self.assertFalse(report['ready'])
            self.assertTrue(all(row['observation'] == 'present-unverified' for row in report['gates']))
            self.assertNotIn('independent_copy_verified', report)
            self.assertNotIn('runtime_started', report)
            with self.assertRaises(Refused):
                controller.advance(site)
            self.assertEqual(controller.load(), before)
            for action in ('source_fence', 'source_probe', 'capture', 'notify_ready', 'notify_blocked',
                           'target_fence', 'target_probe', 'source_recover', 'restore', 'target_start',
                           'preserve_delta', 'reconcile', 'source_resume'):
                with self.subTest(action=action), self.assertRaises(Refused):
                    site.call(action, dict(before, operation_id=before['run_id'] + ':' + action))

    def test_reboot_pending_and_changed_policy_are_reported_fresh_without_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller.create(Path(directory) / 'controller', '42', '42')
            before = controller.load()
            inventory = {
                'recreation': {'reboot_recreation_possible': True},
                'remote_operations': {'pending': ['synthetic-uncertain-operation']},
                'policy': {'current': {'cancellations': 'v2', 'withdrawals': 'v2', 'effects': 'v2'},
                           'reconciled': {'cancellations': 'v1', 'withdrawals': 'v2', 'effects': 'v2'}},
            }
            site = PreparationSite(NoEffects(), NoEffects(), NoEffects(), inventory=inventory)
            report = site.diagnose()
            self.assertEqual(report.get('hazards'), ['reboot-recreation-possible',
                             'pending-remote-effects', 'changed-cancellations'])
            # The same site must reread CURRENT revisions; no cached cancellation receipt.
            inventory['policy']['current']['effects'] = 'v3'
            inventory['policy']['current']['withdrawals'] = 'v3'
            report = site.diagnose()
            self.assertIn('changed-effects', report['hazards'])
            self.assertIn('changed-withdrawals', report['hazards'])
            with self.assertRaises(Refused):
                controller.advance(site)
            self.assertEqual(controller.load(), before)
            # Even optimistic revisions and no known pending work are not production proofs.
            inventory['policy']['reconciled'] = dict(inventory['policy']['current'])
            inventory['remote_operations']['pending'] = []
            inventory['recreation']['reboot_recreation_possible'] = False
            self.assertEqual(site.diagnose()['hazards'], [])
            with self.assertRaises(Refused):
                controller.advance(site)
            self.assertEqual(controller.load(), before)

    def test_cli_is_read_only_sanitized_and_never_exits_success_for_admission(self):
        import os
        import subprocess
        script = Path(__file__).resolve().parents[1] / 'scripts/hermes_migration_preparation.py'
        with tempfile.TemporaryDirectory() as directory:
            inventory = Path(directory) / 'inventory.json'
            inventory.write_text(json.dumps({'ready': True, 'identity': {'private': 'DO-NOT-ECHO'}}))
            original = inventory.read_bytes()
            result = subprocess.run([sys.executable, str(script), '--inventory', str(inventory)],
                                    cwd=directory, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'),
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout),
                             PreparationSite(None, None, None, inventory=json.loads(original)).diagnose())
            self.assertNotIn('DO-NOT-ECHO', result.stdout + result.stderr)
            self.assertEqual(inventory.read_bytes(), original)
            self.assertEqual([p.name for p in Path(directory).iterdir()], ['inventory.json'])
            for invalid in ('{', '[]', 'null'):
                inventory.write_text(invalid)
                result = subprocess.run([sys.executable, str(script), '--inventory', str(inventory)],
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 2)
                self.assertIn('inventory unreadable or invalid', result.stderr)
                self.assertEqual(result.stdout, '')

    def test_each_missing_observation_and_malformed_inventory_remains_prepared(self):
        gates = [row['gate'] for row in PreparationSite(None, None, None).diagnose()['gates']]
        complete = {gate: {'verified': True} for gate in gates}
        for missing in gates:
            inventory = dict(complete)
            del inventory[missing]
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
                controller = Controller.create(Path(directory) / 'controller', '42', '42')
                before = controller.load()
                site = PreparationSite(NoEffects(), NoEffects(), NoEffects(), inventory=inventory)
                row = next(row for row in site.diagnose()['gates'] if row['gate'] == missing)
                self.assertEqual(row['observation'], 'missing-or-invalid')
                self.assertEqual(row['status'], 'BLOCKED')
                with self.assertRaises(Refused):
                    controller.advance(site)
                self.assertEqual(controller.load(), before)
        for inventory in ([], True, 'ready', {'policy': True}, {'policy': {'current': []}}):
            with self.subTest(inventory=inventory):
                self.assertFalse(PreparationSite(None, None, None, inventory=inventory).diagnose()['ready'])

    def test_unknown_remote_work_and_missing_reconciliation_are_not_claimed_changed(self):
        inventory = {'remote_operations': {'pending': 'unknown'},
                     'policy': {'current': {'cancellations': 'observed-hash'}, 'reconciled': {}}}
        report = PreparationSite(None, None, None, inventory=inventory).diagnose()
        self.assertEqual(report['hazards'], ['remote-effects-unknown', 'unreconciled-cancellations',
                                            'unreconciled-withdrawals', 'unreconciled-effects'])
        self.assertFalse(report['ready'])

    def test_missing_authority_reports_each_gate_and_leaves_controller_prepared(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller.create(Path(directory) / 'controller', '42', '42')
            before = controller.load()
            site = PreparationSite(NoEffects(), NoEffects(), NoEffects())
            request = dict(before, operation_id=before['run_id'] + ':preflight')
            report = site.call('preflight', request)
            self.assertEqual(report.get('status'), 'BLOCKED')
            self.assertEqual(report['evidence_scope'], 'observations-only')
            self.assertFalse(report['ready'])
            self.assertEqual({row['gate'] for row in report['gates']}, {
                'identity', 'writers', 'recreation', 'remote_operations', 'policy',
                'custody', 'rescue', 'approval', 'watchdog', 'target_runtime'})
            self.assertTrue(all(row['status'] == 'BLOCKED' for row in report['gates']))
            with self.assertRaises(Refused):
                controller.advance(site)
            self.assertEqual(controller.load(), before)


if __name__ == '__main__':
    unittest.main()
