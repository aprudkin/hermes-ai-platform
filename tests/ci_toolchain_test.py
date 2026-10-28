"""Ensure the CI runner installs the native tool required by task tests."""
from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class CIToolchainTests(unittest.TestCase):
    def test_ci_installs_only_current_validation_dependencies(self):
        text = (ROOT / '.github/workflows/validate.yml').read_text().lower()
        for retired in ('setup-terraform', 'ansible-core', 'ansible-lint', 'ansible-galaxy'):
            self.assertNotIn(retired, text)
        self.assertIn('shellcheck', text)
        self.assertIn('python3-yaml', text)

    def test_task_is_pinned_and_installed_before_real_validation(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/validate.yml').read_text())
        steps = workflow['jobs']['validate']['steps']
        gates = [i for i, step in enumerate(steps)
                 if './scripts/validate.sh --all' in step.get('run', '')]
        self.assertEqual(len(gates), 1)
        installs = [(i, step) for i, step in enumerate(steps)
                    if step.get('uses', '').startswith('go-task/setup-task@')]
        self.assertEqual(len(installs), 1,
                         'CI must install Go Task; task-backed backup/upgrade tests cannot run without it')
        index, installer = installs[0]
        self.assertLess(index, gates[0])
        self.assertRegex(installer.get('with', {}).get('version', ''),
                         r'^\d+\.\d+\.\d+$')


if __name__ == '__main__':
    unittest.main()
