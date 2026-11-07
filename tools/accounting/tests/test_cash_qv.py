import unittest
from test_cash_ledger_monitor import load_module

REPORT = '''PROFIT REGISTER Fixture
Fixture City
07.02.2026
1️⃣ ✅Client 10:13 am qv/170
Cash
2️⃣ ✅Client 5:05 pm Hr/310+90 (extra)
CashApp (Fixture Holder)
Total: 570
Of which:
(170) Cash
(400)CashApp (Fixture Holder)
Yours: 400
Agent fees: 170
Anna operator: 13'''

class QvTests(unittest.TestCase):
    def test_confirmed_qv_tariff_counts_once_and_keeps_shares_separate(self):
        m = load_module()
        p = m.parse_message(REPORT)
        self.assertEqual([e.amount_minor for e in p.entries], [17000,31000,9000])
        self.assertEqual(p.review_lines, ())
        self.assertEqual(p.claimed_total_minor, 57000)
        self.assertEqual(p.model_amount_minor, 40000)
        self.assertEqual(p.agency_amount_minor, 17000)
