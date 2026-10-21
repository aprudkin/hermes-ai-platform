#!/usr/bin/env python3
"""Offline checks for visible progress without contaminating archive bytes."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/hermes_backup_progress.py"


class ProgressTest(unittest.TestCase):
    def launch(self, mode, *args):
        # Shorten only the display interval; execute the production functions.
        program = ("import runpy,sys; m=runpy.run_path(sys.argv[1]); "
                   + ("m['receive'](interval=0.05)" if mode == "receive" else
                      "sys.exit(m['verify'](sys.argv[2], sys.argv[3], interval=0.05))"))
        return subprocess.Popen([sys.executable, "-c", program, str(SCRIPT), *args],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_wait_and_receive_progress_preserve_exact_binary_stream(self):
        with tempfile.TemporaryFile() as errors:
            program = "import runpy,sys; runpy.run_path(sys.argv[1])['receive'](interval=0.05)"
            child = subprocess.Popen([sys.executable, "-c", program, str(SCRIPT)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors)
            try:
                time.sleep(0.2)
                errors.seek(0)
                self.assertIn(b"Connecting to source", errors.read(), "connection must be visible before any bytes arrive")
                payload = bytes(range(256)) * 32
                child.stdin.write(payload)
                child.stdin.flush()
                time.sleep(0.2)
                errors.seek(0)
                progress = errors.read()
                self.assertIn(b"MiB", progress)
                self.assertIn(b"MiB/s", progress)
                output, _ = child.communicate(timeout=5)
                self.assertEqual(child.returncode, 0)
                self.assertEqual(output, payload)
                self.assertNotIn(b"Backup verified", progress)
            finally:
                if child.poll() is None:
                    child.kill()
                child.communicate()

    def test_empty_stream_is_not_announced_as_success(self):
        child = self.launch("receive")
        stdout, stderr = child.communicate(timeout=5)
        self.assertEqual(stdout, b"")
        self.assertNotIn(b"verified", stderr.lower())
        self.assertEqual(child.returncode, 0)  # Shell owns empty/archive/SSH failure checks.

    def test_elapsed_offset_is_visible_in_both_phases(self):
        for args in (("receive", "754"), ("verify", "/nonexistent-fixture", "full", "754")):
            with self.subTest(phase=args[0]):
                result = subprocess.run([sys.executable, str(SCRIPT), *args], input=b"",
                                        capture_output=True, timeout=5)
                self.assertIn(b"[elapsed 00:12:34]", result.stderr)

    def test_termination_reaps_verifier_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "child.pid"
            program = '''import importlib.util, pathlib, subprocess, sys
spec = importlib.util.spec_from_file_location('progress', sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
real = subprocess.Popen
pid_file = pathlib.Path(sys.argv[2])
def spawn(*a, **kw):
    child = real([sys.executable, '-c', 'import time; time.sleep(30)'], **kw)
    pid_file.write_text(str(child.pid))
    return child
m.subprocess.Popen = spawn
sys.argv = ['progress', 'verify', 'unused', 'full', '0']
sys.exit(m.main())
'''
            child = subprocess.Popen([sys.executable, "-c", program, str(SCRIPT), str(pid_file)],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 5
                while not pid_file.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(pid_file.exists())
                child.terminate()
                stdout, stderr = child.communicate(timeout=7)
                self.assertEqual(child.returncode, 130)
                self.assertIn(b"interrupted", stderr)
                self.assertNotIn(b"Backup verified", stdout)
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(pid_file.read_text()), 0)
            finally:
                if child.poll() is None:
                    child.kill()
                child.communicate()

    def test_verify_reports_phase_and_keeps_failure_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "invalid.tar.gz"
            archive.write_bytes(b"invalid")
            child = self.launch("verify", str(archive), "full")
            stdout, stderr = child.communicate(timeout=5)
            self.assertNotEqual(child.returncode, 0)
            self.assertIn(b"Verifying", stderr)
            self.assertIn(b"Decompressing archive and checking payload hashes", stderr)
            self.assertNotIn(b"Backup verified", stdout + stderr)

    def test_verifier_heartbeat_and_exit_status(self):
        # Substitute only the child process for a slow deterministic failure.
        program = '''import importlib.util, subprocess, sys
spec = importlib.util.spec_from_file_location('progress', sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
real = subprocess.Popen
m.subprocess.Popen = lambda *a, **kw: real([sys.executable, '-c', 'import time; time.sleep(0.2); raise SystemExit(7)'], **kw)
sys.exit(m.verify('unused', 'full', interval=0.05))
'''
        result = subprocess.run([sys.executable, "-c", program, str(SCRIPT)], capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 7)
        self.assertGreaterEqual(result.stderr.count(b"Verifying"), 2)
        self.assertEqual(result.stdout, b"")


if __name__ == "__main__":
    unittest.main()
