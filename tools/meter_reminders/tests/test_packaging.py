import runpy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

class PackagingTests(unittest.TestCase):
    def test_cron_entry_does_not_force_execute(self):
        calls = []
        fake = SimpleNamespace(main=lambda argv=None: calls.append(argv) or 0)
        script = Path(__file__).resolve().parents[1] / 'scripts/meter_reminder_cron.py'
        with patch.dict(sys.modules, {'meter_reminder': fake}), patch.object(sys, 'argv', [str(script), '--dry-run']):
            with self.assertRaises(SystemExit) as stopped:
                runpy.run_path(str(script), run_name='__main__')
        self.assertEqual(stopped.exception.code, 0)
        self.assertNotEqual(calls, [['--execute']], 'entry point silently enables delivery')
        self.assertEqual(calls, [None])

    def test_real_cron_cli_default_and_explicit_dry_run_are_read_only(self):
        import json
        import subprocess
        import tempfile
        from test_meter_reminder import RunnerTests
        script = Path(__file__).resolve().parents[1] / 'scripts/meter_reminder_cron.py'
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            tasks, db = RunnerTests().fixture(home)
            (home / 'shared-tasks').mkdir()
            tasks = tasks.replace(home / 'shared-tasks/tasks.json')
            before = tasks.read_bytes()
            for flags in ([], ['--dry-run']):
                result = subprocess.run([sys.executable, str(script), '--home', str(home),
                    '--now', '2026-10-24T16:00:00+03:00', '--report', *flags],
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(result.stdout)
                self.assertTrue(report['dry_run'])
                self.assertTrue(report['due'])
                self.assertFalse(report['route_policy']['membership_checked'])
                self.assertEqual(tasks.read_bytes(), before)
                self.assertEqual(sorted(p.name for p in tasks.parent.iterdir()), ['tasks.json'])

    def test_missing_meter_routes_fail_before_opening_any_task_register(self):
        import os
        import subprocess
        env = {k: v for k, v in os.environ.items() if not k.startswith('METER_')}
        code = "import meter_reminder as m; m.tick('does-not-exist.json', 'does-not-exist.db', m.parse('2026-10-24T16:00:00+03:00'), execute=True)"
        result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Explicit meter bot, task, group and two recipient IDs are required', result.stderr)
        self.assertNotIn('FileNotFoundError', result.stderr)
