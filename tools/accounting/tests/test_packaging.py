"""Explicit routing must replace installation-specific defaults."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'

class PackagingTests(unittest.TestCase):
    def test_review_sender_without_routing_fails_before_state_creation(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith('BABLOMAT_')}
        code = "from cash_review_sender import PrivateReviewSender; import sys; PrivateReviewSender(sys.argv[1], post=lambda p: {})"
        with tempfile.TemporaryDirectory() as home:
            result = subprocess.run([sys.executable, '-c', code, home], env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0, 'missing route silently accepted')
            self.assertEqual(list(Path(home).iterdir()), [])

    def test_monitor_cli_requires_explicit_home_and_source_chat(self):
        env = {k: v for k, v in os.environ.items() if k != 'HERMES_HOME' and not k.startswith('BABLOMAT_')}
        script = SCRIPTS / 'cash_ledger_reply_monitor.py'
        result = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('--home', result.stderr)
        self.assertIn('--chat-id', result.stderr)

    def test_inherited_offline_guard_blocks_sockets_and_nonfixture_databases(self):
        code = "import socket; socket.create_connection(('127.0.0.1', 9))"
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Offline test attempted network access', result.stderr)
        code = "import sqlite3; sqlite3.connect('/offline-not-temp/state.db')"
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Offline test attempted non-temporary state/credential access', result.stderr)
