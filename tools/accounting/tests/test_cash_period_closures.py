import unittest
import os
from unittest.mock import patch
import tempfile
from pathlib import Path
from test_cash_ledger_monitor import load_module

class PeriodClosureTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, BABLOMAT_ELENA_ID='810000002')
        env.start()
        self.addCleanup(env.stop)

    def test_confirmation_closes_model_and_agency_but_not_operator(self):
        m = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = m.Ledger(Path(tmp) / 'ledger.db')
            for row_id, day in [(1, '03.10'), (4, '06.10')]:
                if row_id == 4:
                    notice = ledger.confirm_period_closure(
                        confirmation_source_row_id=3, confirmation_message_id='59',
                        report_source_row_id=1, report_message_id='52',
                        confirmer_id='810000002', timestamp=1791244898.0,
                        recipient_kind='model', recipient_key='Fixture', recipient_name='Fixture Model',
                        period_start=None, period_end='2026-10-03')
                    self.assertIn('**Закрытие периода:**', notice)
                    self.assertIn('Начало периода: не установлено', notice)
                    self.assertIn('По: 03.10 (сб)', notice)
                ledger.process_message(source_row_id=row_id, timestamp=1791244898.0,
                    platform_message_id='52' if row_id == 1 else str(row_id),
                    content=f'Касса Fixture\n{day}\nКлиент Hr/100\nTotal: 100\nМодели: 60\nАгентских: 40\nОператор Анна: 10')
            notice = ledger.cash_notice(4)
            self.assertIn('🫦 Fixture: 60$', notice)
            self.assertIn('🎩 Агентство: 40$', notice)
            self.assertIn('🥷🏻 Анна: 20$', notice)
            args=dict(confirmation_source_row_id=3, confirmation_message_id='59',
                report_source_row_id=1,report_message_id='52',confirmer_id='810000002',
                timestamp=1791244898.0,recipient_kind='model',recipient_key='Fixture',
                recipient_name='Fixture Model',period_start=None,period_end='2026-10-03')
            ledger.confirm_period_closure(**args)
            with ledger._connection() as c:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM period_closures').fetchone()[0],2)
            payout=ledger.create_model_payout(model_name='Fixture',command_source_row_id=5,
                command_timestamp=1791245000.0,requester_id='1',requester_name='Test')
            self.assertEqual(payout.total_minor,6000)
