"""Checks against false closures and loss of newer unpaid accruals."""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_cash_ledger_monitor import load_module


class ClosureBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, BABLOMAT_ELENA_ID='810000002')
        self.env.start()
        self.addCleanup(self.env.stop)
        self.m = load_module()
        self.path = Path(self.tmp.name)/'ledger.db'
        self.ledger = self.m.Ledger(self.path)
        self.report(1, '03.10.2026')
        self.args = dict(confirmation_source_row_id=3, confirmation_message_id='59',
            report_source_row_id=1, report_message_id='51', confirmer_id='810000002',
            timestamp=1791252477, recipient_kind='model', recipient_key='Fixture',
            recipient_name='Fixture', period_start=None, period_end='2026-10-03')

    def report(self, row, day):
        return self.ledger.process_message(source_row_id=row, timestamp=1791252477,
            platform_message_id=str(50+row), content=f'Касса Fixture\n{day}\nClient Hr/137\nTotal: 137\nМодели: 83\nАгентских: 54\nОператор Анна: 11')

    def count(self):
        with self.ledger._connection() as db:
            return db.execute('SELECT COUNT(*) FROM period_closures').fetchone()[0]

    def test_newer_report_before_confirmation_remains_unpaid_after_restart(self):
        self.report(2, '04.10.2026')
        self.ledger.confirm_period_closure(**self.args)
        self.ledger = self.m.Ledger(self.path)
        payout = self.ledger.create_model_payout(model_name='Fixture', command_source_row_id=4,
            command_timestamp=1791252478, requester_id='810000001', requester_name='Fixture')
        self.assertEqual(payout.by_date, (('2026-10-04',8300),))
        with self.ledger._connection() as db:
            self.assertEqual(db.execute('SELECT total_minor FROM agency_payouts').fetchone()[0],5400)
        self.assertEqual(self.ledger.operator_statistics(), {'Анна':2200})
        self.assertEqual(self.ledger.register_statistics(), {'Fixture':27400})

    def test_unauthorized_wrong_recipient_wrong_reference_or_unverified_source_refused(self):
        for override,error in [({'confirmer_id':'810000009'},PermissionError),
                               ({'recipient_key':'Other'},ValueError),
                               ({'report_message_id':'999'},ValueError),
                               ({'recipient_kind':'agency'},ValueError),
                               ({'period_end':'2026-10-04'},ValueError)]:
            with self.subTest(override=override), self.assertRaises(error):
                self.ledger.confirm_period_closure(**dict(self.args, **override))
            self.assertEqual(self.count(),0)
        with self.ledger._connection() as db:
            db.execute("UPDATE messages SET check_status='unverified'")
        with self.assertRaises(ValueError):
            self.ledger.confirm_period_closure(**self.args)
        self.assertEqual(self.count(),0)

    def test_atomic_model_agency_failure_rolls_back_both(self):
        with self.ledger._connection() as db:
            db.execute("CREATE TRIGGER fail_agency BEFORE INSERT ON period_closures WHEN NEW.recipient_kind='agency' BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.ledger.confirm_period_closure(**self.args)
        self.assertEqual(self.count(),0)

    def test_operator_confirmation_leaves_model_and_agency_unpaid(self):
        self.ledger.confirm_period_closure(**dict(self.args, recipient_kind='operator',
            recipient_key='Анна',recipient_name='Анна'))
        self.report(4,'04.10.2026')
        notice = self.ledger.cash_notice(4)
        self.assertIn('🫦 Fixture: 166$',notice)
        self.assertIn('🎩 Агентство: 108$',notice)
        self.assertIn('🥷🏻 Анна: 11$',notice)
        payout = self.ledger.create_operator_payout(operator_name='Анна',command_source_row_id=5,
            command_timestamp=1791252478,requester_id='810000001',requester_name='Fixture')
        self.assertEqual(payout.total_minor,1100)

    def test_operator_closure_does_not_close_other_registers(self):
        self.ledger.process_message(source_row_id=2,timestamp=1791252477,platform_message_id='52',
            content='Касса OtherFixture\n03.10.2026\nClient Hr/137\nTotal: 137\nОператор Анна: 17')
        self.report(3,'04.10.2026')
        self.ledger.confirm_period_closure(**dict(self.args, confirmation_source_row_id=4,
            report_source_row_id=3,report_message_id='53',period_end='2026-10-04',
            recipient_kind='operator',recipient_key='Анна',recipient_name='Анна'))
        payout=self.ledger.create_operator_payout(operator_name='Анна',command_source_row_id=5,
            command_timestamp=1791252478,requester_id='810000001',requester_name='Fixture')
        self.assertEqual(payout.total_minor,1700)

    def test_later_accounting_day_posted_before_confirmed_report_stays_unpaid(self):
        self.report(2,'04.10.2026')
        self.report(3,'03.10.2026')
        self.ledger.confirm_period_closure(**dict(self.args,confirmation_source_row_id=4,
            report_source_row_id=3,report_message_id='53'))
        payout=self.ledger.create_model_payout(model_name='Fixture',command_source_row_id=5,
            command_timestamp=1791252478,requester_id='810000001',requester_name='Fixture')
        self.assertEqual(payout.by_date,(('2026-10-04',8300),))

    def test_late_historical_report_is_reviewed_without_reopening_closed_accruals(self):
        self.ledger.confirm_period_closure(**self.args)
        result=self.ledger.process_message(source_row_id=4,timestamp=1791252478,platform_message_id='54',
            content='Касса Fixture\n03.10.2026\nClient Hr/200\nTotal: 200\nМодели: 120\nАгентских: 80')
        self.assertEqual(result.status,'unverified')
        self.assertEqual(self.ledger.register_statistics(),{'Fixture':13700})
        with self.ledger._connection() as db:
            self.assertIsNotNone(db.execute('SELECT line FROM parse_reviews WHERE source_row_id=4').fetchone())

    def test_compact_operator_historical_day_respects_scoped_closure(self):
        self.ledger.confirm_period_closure(**dict(self.args,recipient_kind='operator',
            recipient_key='Анна',recipient_name='Анна'))
        result=self.ledger.process_message(source_row_id=4,timestamp=1791252478,platform_message_id='54',
            compact_enabled=True,content='Модель Fixture\nОпер Анна\n02.10.2026 + 17')
        self.assertEqual(result.status,'unverified')
        self.assertEqual(self.ledger.operator_statistics(),{'Анна':1100})

    def test_superseded_source_cannot_close_period(self):
        self.report(2,'03.10.2026')
        with self.assertRaises(ValueError):
            self.ledger.confirm_period_closure(**self.args)
        self.assertEqual(self.count(),0)

    def test_second_period_has_known_start_from_first_subsequent_accrual(self):
        self.ledger.confirm_period_closure(**self.args)
        self.report(4,'06.10.2026')
        args=dict(self.args, confirmation_source_row_id=5, confirmation_message_id='60',
                  report_source_row_id=4, report_message_id='54',period_end='2026-10-06')
        notice=self.ledger.confirm_period_closure(**args)
        self.assertIn('С: 06.10 (вт)',notice)
        self.assertEqual(self.ledger.confirm_period_closure(**args),notice)
        self.assertEqual(self.count(),4)
