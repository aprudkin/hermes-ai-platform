"""Offline checks for archived helpers; no real account or browser access."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class RuntimeHelpersTests(unittest.TestCase):
    def test_agentmail_import_does_not_register_or_write_state(self):
        source=ROOT/'tools/agent_mail/agentmail_setup.py'
        self.assertTrue(source.is_file(),'AgentMail helper has not been versioned')
        with tempfile.TemporaryDirectory() as tmp:
            code='''import importlib.util,socket,sys
from pathlib import Path
from unittest.mock import patch
p=Path(sys.argv[1]);home=Path(sys.argv[2])
spec=importlib.util.spec_from_file_location('archived_agentmail',p)
module=importlib.util.module_from_spec(spec)
with patch('socket.socket.connect',side_effect=AssertionError('Network forbidden')):
 spec.loader.exec_module(module)
assert not list(home.iterdir()),'Import wrote private state'
'''
            result=subprocess.run([sys.executable,'-c',code,str(source),tmp],env={**os.environ,'HERMES_HOME':tmp},capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_agentmail_requires_explicit_execution(self):
        source=ROOT/'tools/agent_mail/agentmail_setup.py'
        self.assertTrue(source.is_file())
        with tempfile.TemporaryDirectory() as tmp:
            result=subprocess.run([sys.executable,str(source),'--home',tmp],capture_output=True,text=True,timeout=15)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('--execute',result.stderr)
            self.assertFalse(list(Path(tmp).iterdir()))

    def test_browser_helper_imports_are_inert(self):
        directory=ROOT/'tools/browser_bridge'
        self.assertTrue(directory.is_dir(),'Browser helpers have not been versioned')
        for filename in ('mac_browser_client.py','mac_browser_call.py','mac_browser_probe.py','chebi_browser.py'):
            with self.subTest(filename=filename),tempfile.TemporaryDirectory() as tmp:
                code='''import importlib.util,sys
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('archived_browser',Path(sys.argv[1]))
module=importlib.util.module_from_spec(spec)
with patch('socket.socket.connect',side_effect=AssertionError('Network forbidden')),patch('subprocess.Popen',side_effect=AssertionError('Process forbidden')):
 spec.loader.exec_module(module)
assert not list(Path(sys.argv[2]).iterdir()),'Import wrote state'
'''
                result=subprocess.run([sys.executable,'-c',code,str(directory/filename),tmp],env={**os.environ,'HERMES_HOME':tmp},capture_output=True,text=True,timeout=15)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)

if __name__=='__main__':
    unittest.main()
