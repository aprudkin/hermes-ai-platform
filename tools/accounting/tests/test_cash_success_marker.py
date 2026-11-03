import tempfile
import unittest
from pathlib import Path
from tests.test_cash_ledger_monitor import load_module

class SuccessMarkerTests(unittest.TestCase):
    def test_verified_notice_marks_total_and_word_with_green_check(self):
        m=load_module()
        with tempfile.TemporaryDirectory() as t:
            ledger=m.Ledger(Path(t)/'ledger.db')
            ledger.process_message(source_row_id=1,timestamp=1791252477,platform_message_id='1',content='Касса Test\n05.10\nClient Hr/500\nИтого: 500')
            line=ledger.cash_notice(1).splitlines()[1]
            self.assertTrue(line.startswith('✅ Итого: '))
            self.assertTrue(line.endswith('сходится ✅'))
            ledger.process_message(source_row_id=2,timestamp=1791252477,platform_message_id='2',content='Касса Test\n05.10\nClient Hr/500\nИтого: 600')
            self.assertEqual(ledger.cash_notice(2),'')

if __name__=='__main__':unittest.main()
