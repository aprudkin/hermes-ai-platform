import unittest
import tempfile
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from test_cash_ledger_monitor import load_module

class CashBusinessDateTests(unittest.TestCase):
    def test_undated_cash_report_uses_ending_pacific_business_day(self):
        m=load_module()
        text='Касса Fixture\nHr/900\nTotal: 900'
        for hour, expected in [(23,'2026-10-03'),(1,'2026-10-03'),(6,'2026-10-04')]:
            day=3 if hour==23 else 4
            with self.subTest(hour=hour):
                timestamp=datetime(2026,10,day,hour,tzinfo=ZoneInfo('America/Los_Angeles')).timestamp()
                self.assertEqual(m._extract_accounting_date(text,timestamp),expected)
        timestamp=datetime(2026,10,4,1,tzinfo=ZoneInfo('America/Los_Angeles')).timestamp()
        self.assertEqual(m._extract_accounting_date('Касса Fixture\n02.10.2026\nTotal: 0',timestamp),'2026-10-02')

    def test_statistics_describe_the_pacific_date_policy(self):
        m=load_module()
        with tempfile.TemporaryDirectory() as tmp:
            statistics=m.Ledger(Path(tmp)/'ledger.db').statistics()
            self.assertEqual(statistics['timezone'],'America/Los_Angeles')
            self.assertEqual(statistics['business_day_cutoff_hour'],6)

if __name__=='__main__':
    unittest.main()
