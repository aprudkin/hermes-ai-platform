import tempfile
import unittest
from pathlib import Path
from tests.test_cash_ledger_monitor import load_module

CONTENT = '''[Fixture Reporter|810000003]
PROFIT REGISTER Fixture
Fixture City
09.02.2026
1️⃣ ✅Client 12:05pm Hr/210
Cash
2️⃣ ✅Client 2:05pm Hr/210
Cash
3️⃣ ✅Client 4:05pm 15min/130
CashApp
4️⃣ ✅Client 6:05pm Hr/210
Cash
Total: 760
Of which:
(630) Cash
(130)CashApp (Fixture Holder)
Yours: 450
Agent fees: 310
Anna operator: 17'''

class ShortDurationTests(unittest.TestCase):
    def test_15min_transaction_above_total_is_counted(self):
        m = load_module()
        p = m.parse_message(CONTENT)
        self.assertEqual([e.amount_minor for e in p.entries], [21000, 21000, 13000, 21000])
        with tempfile.TemporaryDirectory() as tmp:
            ledger = m.Ledger(Path(tmp)/'ledger.db')
            result = ledger.process_message(source_row_id=1, timestamp=1791252477,
                platform_message_id='77', content=CONTENT)
            self.assertEqual(result.status, 'ok')
            self.assertEqual(result.computed_total_minor, 76000)
            self.assertEqual(result.difference_minor, 0)
            self.assertEqual(ledger.register_statistics(), {'Fixture': 76000})

if __name__ == '__main__':
    unittest.main()
