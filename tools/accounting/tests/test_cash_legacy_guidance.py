import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from test_cash_ledger_monitor import load_module

class LegacyOperatorGuidanceTests(unittest.TestCase):
    def test_legacy_multiday_operator_report_gets_same_data_short_template(self):
        load_module()
        from cash_compact_formats import parse_compact,format_guidance
        timestamp=datetime(2026,10,17,20,tzinfo=ZoneInfo('America/Los_Angeles')).timestamp()
        source='[Sender|1]\nМодель 💎🍒SampleModel🍒💎\nОператор Ева\n15.10.2026 + 40💸\n16.10.2026 + 50💸\nИтого 90'
        parsed=parse_compact(source,timestamp)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.kind,'operator')
        self.assertFalse(parsed.standard)
        self.assertEqual(parsed.dates,('2026-10-15','2026-10-16'))
        self.assertEqual(parsed.daily,(('2026-10-15','40'),('2026-10-16','50')))
        guide=format_guidance(source,timestamp)
        self.assertIn('15–16\nЕва / SampleModel\n\n15 — 40\n16 — 50',guide)

if __name__=='__main__': unittest.main()
