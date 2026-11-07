"""Exercise the real local validation entrypoint without host/cloud access."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / 'repo'
        shutil.copytree(ROOT, self.repo, ignore=shutil.ignore_patterns('.git', '__pycache__', '.terraform'))
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

    def test_job_environment_does_not_use_unavailable_runner_context(self):
        import yaml
        workflow = yaml.safe_load((self.repo / '.github/workflows/validate.yml').read_text())
        for name, job in workflow['jobs'].items():
            for key, value in job.get('env', {}).items():
                with self.subTest(job=name, key=key):
                    self.assertNotRegex(str(value), r'\$\{\{\s*runner\.',
                                        'runner context is unavailable in jobs.<job>.env')

    def test_missing_current_backup_file_is_rejected(self):
        (self.repo / 'scripts/hermes_server_backup.py').unlink()
        result = self.run_gate('--structure')
        self.assertNotEqual(result.returncode, 0)

    def test_current_static_checks_succeed(self):
        result = self.run_gate('--static')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_shellcheck_failure_is_not_swallowed(self):
        self.assertNotEqual(self.run_gate('--static', FAIL_TOOL='shellcheck').returncode, 0)

    def test_later_shell_syntax_error_fails_without_shellcheck(self):
        (self.bin / 'shellcheck').write_text('#!/bin/sh\nexit 127\n')
        for directory in ('scripts', 'tests'):
            with self.subTest(directory=directory):
                broken = self.repo / directory / 'zz-broken.sh'
                broken.write_text('#!/bin/bash\nif then\n')
                result = self.run_gate('--local')
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('PASS bash syntax', result.stdout)
                self.assertIn('zz-broken.sh', result.stderr)
                broken.unlink()

    def test_ci_wrapper_needs_yaml_but_not_ansible(self):
        ansible = self.bin / 'ansible-playbook'
        ansible.write_text('#!/bin/sh\nexit 127\n')
        ansible.chmod(0o755)
        wrapper = self.repo / 'tests/ci_toolchain_test.sh'
        result = subprocess.run(['bash', str(wrapper)], env=self.env,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('SKIP', result.stdout)
        self.assertIn('Ran 2 tests', result.stderr)
        python = self.bin / 'python3'
        python.write_text('#!/bin/sh\nexec "' + sys.executable + '" -S "$@"\n')
        python.chmod(0o755)
        result = subprocess.run(['bash', str(wrapper)], env=self.env,
                                capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('No module named', result.stderr)
        self.assertIn('yaml', result.stderr)

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

    def test_runtime_token_lookup_is_not_a_persisted_secret(self):
        (self.repo / 'lookup-example.sh').write_text(
            'GITHUB_TOKEN=$(printf runtime-only)\n'
            'GITHUB_TOKEN="${GITHUB_TOKEN:-}"\n')
        result = self.run_gate('--secrets')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_opaque_static_token_assignment_remains_rejected(self):
        value = 'synthetic-opaque-credential-value'
        (self.repo / 'leak.txt').write_text('GITHUB_TOKEN="' + value + '"\n')
        result = self.run_gate('--secrets')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(value, result.stdout + result.stderr)

    def test_nonempty_token_fallback_remains_rejected(self):
        (self.repo / 'leak.txt').write_text('GITHUB_TOKEN="${GITHUB_TOKEN:-synthetic-private-default}"\n')
        self.assertNotEqual(self.run_gate('--secrets').returncode, 0)

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
