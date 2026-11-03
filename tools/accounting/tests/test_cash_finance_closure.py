"""Financial summaries authorize only their explicit recipient and known period."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_cash_ledger_monitor import load_module


class FinanceClosureTests(unittest.TestCase):
    def test_verified_finance_summary_closes_model_without_adding_revenue(self):
        m=load_module()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,BABLOMAT_ELENA_ID='810000002'):
            ledger=m.Ledger(Path(tmp)/'ledger.db')
            ledger.process_message(source_row_id=1,timestamp=1791252477,platform_message_id='50',
                content='Касса Fixture\n03.10.2026\nClient Hr/137\nTotal: 137\nМодели: 83\nАгентских: 54')
            ledger.check_finance_message(source_row_id=2,timestamp=1791252477,platform_message_id='51',
                content='Финмониторинг\nМодель: Fixture\nПериод: 01.10.2026 — 03.10.2026\n100+37=137')
            notice=ledger.confirm_period_closure(confirmation_source_row_id=3,confirmation_message_id='59',
                report_source_row_id=2,report_message_id='51',confirmer_id='810000002',timestamp=1791252478,
                recipient_kind='model',recipient_key='Fixture',recipient_name='Fixture',
                period_start='2026-10-01',period_end='2026-10-03')
            self.assertIn('С: 01.10 (чт)',notice)
            self.assertEqual(ledger.register_statistics(),{'Fixture':13700})
            payout=ledger.create_model_payout(model_name='Fixture',command_source_row_id=4,
                command_timestamp=1791252479,requester_id='810000001',requester_name='Fixture')
            self.assertEqual(payout.total_minor,0)
