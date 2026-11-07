"""Source/publication boundaries for the expanded reconstruction scope."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class RuntimeScopeTests(unittest.TestCase):
    def fixture(self, directory):
        target=Path(directory)/'repo'
        shutil.copytree(ROOT,target,ignore=shutil.ignore_patterns('.git','.generated','__pycache__','.pytest_cache','.venv'))
        return target

    def test_missing_calendar_entrypoint_fails_structure_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root=self.fixture(td)
            (root/'tools/event_calendar/__main__.py').unlink()
            result=subprocess.run(['bash',str(root/'scripts/validate.sh'),'--structure'],capture_output=True,text=True,timeout=15)
            self.assertNotEqual(result.returncode,0,'Expanded runtime sources must be required artifacts')

    def test_excluded_jira_code_fails_structure_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root=self.fixture(td)
            (root/'scripts/monitor_yandex_jira.py').write_text('# synthetic excluded component\n')
            result=subprocess.run(['bash',str(root/'scripts/validate.sh'),'--structure'],capture_output=True,text=True,timeout=15)
            self.assertNotEqual(result.returncode,0,'Owner-excluded Jira implementation must not return')

if __name__=='__main__':
    unittest.main()
