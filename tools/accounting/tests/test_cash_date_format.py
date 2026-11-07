import unittest
from test_cash_ledger_monitor import load_module

class CashDateFormatTests(unittest.TestCase):
    def test_display_has_day_month_and_russian_weekday_without_year(self):
        m = load_module()
        self.assertEqual(m._display_date("2026-10-03"), "03.10 (сб)")
        self.assertEqual(m._display_date("2026-10-01"), "01.10 (чт)")
        payout = m._format_payout_report("Анна", "2026-10-01", "2026-10-03",
                                         (("2026-10-03", 5000),), 5000)
        self.assertIn("Период: 01.10 (чт) — 03.10 (сб)", payout)
        self.assertNotIn("2026", payout)
