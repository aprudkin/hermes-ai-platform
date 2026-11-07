"""Offline escalation entrypoint tests, always temporary profiles."""
import importlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))


class EscalationEntrypointTests(unittest.TestCase):
    def test_cli_exposes_explicit_enable_and_empty_home_stays_silent(self):
        import subprocess
        script = Path(__file__).resolve().parents[1] / 'scripts' / 'cash_review_escalation_monitor.py'
        help_result = subprocess.run([sys.executable, str(script), '--help'], capture_output=True, text=True)
        self.assertEqual(help_result.returncode, 0)
        self.assertIn('--enabled', help_result.stdout)
        with tempfile.TemporaryDirectory() as t:
            result = subprocess.run([sys.executable, str(script), '--home', t, '--enabled'], capture_output=True, text=True)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
            self.assertEqual(list(Path(t).iterdir()), [])

    def test_disabled_or_absent_case_database_is_read_free_write_free_noop(self):
        self.assertIsNotNone(importlib.util.find_spec('cash_review_escalation_monitor'),
                             'independent escalation entrypoint required')
        module = importlib.import_module('cash_review_escalation_monitor')
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            def forbidden(payload):
                self.fail('no-op must not deliver anything')
            self.assertEqual(module.run_escalations(home, post=forbidden), 0)
            self.assertEqual(module.run_escalations(home, enabled=True, post=forbidden), 0)
            self.assertEqual(list(home.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
