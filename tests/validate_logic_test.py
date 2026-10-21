"""Exercise the real local validation entrypoint without host/cloud access."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / 'repo'
        shutil.copytree(ROOT, self.repo, ignore=shutil.ignore_patterns('.git', '__pycache__'))
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        for name in ('shellcheck', 'docker', 'task'):
            path = self.bin / name
            path.write_text('#!/usr/bin/env python3\nimport os,sys\n'
                            'if sys.argv[1:] == ["--version"] or sys.argv[1:] == ["compose", "version"]: sys.exit(0)\n'
                            'sys.exit(9 if os.environ.get("FAIL_TOOL") == os.path.basename(sys.argv[0]) else 0)\n')
            path.chmod(0o755)
        self.env = {**os.environ, 'PATH': str(self.bin) + os.pathsep + os.environ['PATH']}

    def run_gate(self, *args, **environment):
        return subprocess.run(['bash', str(self.repo / 'scripts/validate.sh'), *args],
                              cwd=self.repo, env={**self.env, **environment},
                              capture_output=True, text=True, timeout=30)

    def test_current_tree_is_valid_without_platform_directories(self):
        result = self.run_gate('--structure')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_current_backup_file_is_rejected(self):
        (self.repo / 'scripts/hermes_server_backup.py').unlink()
        result = self.run_gate('--structure')
        self.assertNotEqual(result.returncode, 0)

    def test_current_static_checks_succeed(self):
        result = self.run_gate('--static')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_shellcheck_failure_is_not_swallowed(self):
        self.assertNotEqual(self.run_gate('--static', FAIL_TOOL='shellcheck').returncode, 0)

    def test_compose_failure_is_not_swallowed(self):
        self.assertNotEqual(self.run_gate('--static', FAIL_TOOL='docker').returncode, 0)

    def test_python_syntax_failure_is_rejected_without_execution(self):
        (self.repo / 'scripts/broken.py').write_text('this is not valid python!')
        self.assertNotEqual(self.run_gate('--static').returncode, 0)

    def test_secret_is_rejected_without_echoing_value(self):
        value = 'sk-proj-' + 'x' * 40
        (self.repo / 'leak.txt').write_text('OPENAI_API_KEY=' + value + '\n')
        result = self.run_gate('--secrets')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(value, result.stdout + result.stderr)

    def test_ignored_secret_files_are_still_scanned(self):
        subprocess.run(['git', 'init', '--quiet', str(self.repo)], check=True)
        value = 'ghp_' + 'x' * 40
        (self.repo / 'ignored.key').write_text('GITHUB_TOKEN=' + value + '\n')
        result = self.run_gate('--secrets')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(value, result.stdout + result.stderr)

    def test_scanner_failure_is_not_treated_as_clean(self):
        scanner = self.bin / 'rg'
        scanner.write_text('#!/bin/sh\nexit 2\n')
        scanner.chmod(0o755)
        self.assertNotEqual(self.run_gate('--secrets').returncode, 0)

    def test_full_gate_propagates_behavioral_failure(self):
        (self.repo / 'tests/run.sh').write_text('#!/bin/sh\nexit 17\n')
        self.assertNotEqual(self.run_gate('--all').returncode, 0)

    def test_retired_remote_mode_and_extra_arguments_are_rejected(self):
        self.assertEqual(self.run_gate('--runtime').returncode, 2)
        self.assertEqual(self.run_gate('--structure', 'unexpected').returncode, 2)


if __name__ == '__main__':
    unittest.main()
