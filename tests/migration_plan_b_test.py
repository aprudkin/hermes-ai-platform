#!/usr/bin/env python3
"""Exercise the portable client with fake SSH only; no hosts are changed."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts/hermes_migration_plan_b.py"


class PlanBTest(unittest.TestCase):
    def module(self):
        self.assertTrue(PATH.exists(), "standalone Plan B is missing")
        spec = importlib.util.spec_from_file_location("plan_b", PATH)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_default_only_reads_both_hosts_and_never_starts_container(self):
        module = self.module()
        calls = []
        def runner(args):
            calls.append(args)
            return ''
        result = module.run(["--source", "source-alias", "--target", "target-alias"], runner=runner)
        self.assertEqual(result["action"], "check")
        self.assertEqual(result["source"]["containers"], 0)
        self.assertEqual(len(calls), 2)
        for args in calls:
            self.assertIn("StrictHostKeyChecking=yes", args)
            self.assertIn("BatchMode=yes", args)
            self.assertIn("ControlPath=none", args)
            self.assertIn("ForwardAgent=no", args)
            self.assertIn("container ls", args[-1])
            self.assertNotIn("start", args[-1])

    def test_unreachable_target_is_not_a_fence(self):
        module = self.module()
        calls = []
        def runner(args):
            calls.append(args)
            if "target-alias" in args:
                raise module.Refused("SSH unavailable")
            return ''
        result = module.run(["--source", "source-alias", "--target", "target-alias"], runner=runner)
        self.assertFalse(result["target"]["reachable"])
        self.assertFalse(result["safe_to_start_source"])
        self.assertEqual(len(calls), 2)

    def test_rollback_requires_confirmation_and_targets_only_source_controller(self):
        module = self.module()
        calls = []
        def runner(args):
            calls.append(args)
            return '{"phase":"FENCING_TARGET","run_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
        base = ["--source", "source-alias", "--target", "target-alias", "--rollback", "--run-id", "a" * 32]
        with self.assertRaises(module.Refused):
            module.run(base, runner=runner)
        self.assertEqual(calls, [])
        module.run(base + ["--confirm-request"], runner=runner)
        self.assertEqual(len(calls), 2)  # intent and exact controller status readback
        self.assertTrue(all("source-alias" in args for args in calls))
        self.assertIn("request-rollback", calls[0][-1])
        self.assertIn("status", calls[1][-1])
        self.assertFalse(any("docker start" in args[-1] for args in calls))

    def test_rollback_refuses_missing_run_binding_before_ssh(self):
        module = self.module()
        calls = []
        with self.assertRaises(module.Refused):
            module.run(["--source", "source-alias", "--target", "target-alias", "--rollback",
                        "--confirm-request"], runner=lambda args: (calls.append(args) or
                        '{"phase":"FENCING_TARGET","run_id":"fixture"}'))
        self.assertEqual(calls, [])

    def test_controller_cli_refuses_mutation_without_execute(self):
        command = ROOT / "scripts/hermes_migration_controller.py"
        result = subprocess.run([sys.executable, str(command), "advance"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--execute", result.stderr)

    def test_rejects_ssh_option_injection(self):
        module = self.module()
        for alias in ("-oProxyCommand=bad", "source;bad", "user@host", "source host"):
            with self.subTest(alias=alias), self.assertRaises(module.Refused):
                module.run(["--source=" + alias, "--target", "target-alias"], runner=lambda args: '')


if __name__ == "__main__":
    unittest.main()
