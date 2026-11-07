import unittest
import elena_addressing as m

class CurrentAddressTests(unittest.TestCase):
    def test_every_selection_uses_only_current_address(self):
        self.assertEqual({m.name_for_slot(slot) for slot in range(m.TOTAL)}, {'Ле'})

    def test_unconfigured_addressing_is_inert(self):
        import os
        import subprocess
        import sys
        env = {k: v for k, v in os.environ.items() if not k.startswith('ELENA_ADDRESSING_')}
        code = "import elena_addressing as m; from types import SimpleNamespace; assert not m.configured(); assert m.rewrite_event(SimpleNamespace(), None) is None"
        result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
