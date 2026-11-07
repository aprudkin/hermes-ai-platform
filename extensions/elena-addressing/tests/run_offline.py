"""Run anonymized source regressions with synthetic routes and no network."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / 'tests'
paths = [TESTS / 'offline_guard', ROOT / 'scripts', TESTS, ROOT]
os.environ['PYTHONPATH'] = os.pathsep.join(map(str, paths))
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
sys.dont_write_bytecode = True
for path in reversed(paths):
    sys.path.insert(0, str(path))
import sitecustomize
os.environ.update({
    'ELENA_ADDRESSING_USER_ID': '810000002',
    'ELENA_ADDRESSING_OWNER_ID': '810000001',
    'ELENA_ADDRESSING_GROUP_ID': '-1008000000002',
    'ELENA_ADDRESSING_PROFILE': 'manager',
})
with tempfile.TemporaryDirectory(prefix='addressing-suite-') as home:
    os.environ['HERMES_HOME'] = home
    suite = unittest.defaultTestLoader.discover(str(TESTS), pattern='test_*.py')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
