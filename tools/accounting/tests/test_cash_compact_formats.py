"""Optional compact formats: pure parsing and real temporary-ledger ingestion."""
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from test_cash_ledger_monitor import load_module


def stamp(value='2026-10-15T20:00:00'):
    return datetime.fromisoformat(value).replace(tzinfo=ZoneInfo('America/Los_Angeles')).timestamp()


CASH = '15\nFixture\n\n450 Cash\n450 Venmo\n\nИтого 900\nМодели 540\nАгентству 360\nАнна 40'


class CompactTests(unittest.TestCase):
    def test_opt_in_cash_ingestion_preserves_raw_and_separate_shares(self):
        m = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = m.Ledger(Path(tmp) / 'ledger.db')
            result = ledger.process_message(source_row_id=1, timestamp=stamp(),
                platform_message_id='10', content=CASH, compact_enabled=True)
            self.assertEqual(result.status, 'ok')
            self.assertEqual(result.computed_total_minor, 90000)
            self.assertEqual(ledger.register_statistics(), {'Fixture': 90000})
            self.assertEqual(ledger.model_statistics(), {'Fixture': 54000})
            self.assertEqual(ledger.agency_statistics(), {'Fixture': 36000})
            self.assertEqual(ledger.operator_statistics(), {'Анна': 4000})
            with ledger._connection() as c:
                row = c.execute('SELECT * FROM messages').fetchone()
                self.assertEqual(row['raw_content'], CASH)
                self.assertEqual(row['accounting_date'], '2026-10-15')
            ledger.process_message(source_row_id=1, timestamp=stamp(),
                platform_message_id='10', content=CASH, compact_enabled=True)
            self.assertEqual(ledger.operator_statistics(), {'Анна': 4000})
    def test_inline_client_split_is_counted_once_and_mismatch_is_reviewed(self):
        m = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = m.Ledger(Path(tmp) / 'ledger.db')
            for row_id, split, status in [(1, '350', 'ok'), (2, '340', 'unverified')]:
                text = f'15\nFixture\n450 = Zelle 100 + Cash {split}\nИтого 450\nМодели 270\nАгентству 180\nАнна 20'
                result = ledger.process_message(source_row_id=row_id, timestamp=stamp(),
                    platform_message_id=str(row_id), content=text, compact_enabled=True)
                self.assertEqual(result.status, status)
                if status == 'ok':
                    self.assertEqual(result.computed_total_minor, 45000)
                else:
                    self.assertIsNone(result.computed_total_minor)
                    with ledger._connection() as c:
                        self.assertIn('Zelle', c.execute('SELECT line FROM parse_reviews').fetchone()[0])

    def test_unknown_compact_amount_keeps_coverage_guard(self):
        m = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = m.Ledger(Path(tmp) / 'ledger.db')
            for row_id, line in enumerate(['30 Bitcoin', 'Модели ?', 'Опер Анна = 20'], 1):
                text = CASH + '\n' + line
                result = ledger.process_message(source_row_id=row_id, timestamp=stamp(),
                    platform_message_id=str(row_id), content=text, compact_enabled=True)
                self.assertEqual(result.status, 'unverified')
                with ledger._connection() as c:
                    self.assertIn(line, [r[0] for r in c.execute('SELECT line FROM parse_reviews WHERE source_row_id=?', (row_id,))])
    def test_day_resolution_uses_business_month_and_ambiguous_dates_stay_review_only(self):
        from cash_compact_formats import parse_compact
        before = parse_compact(CASH.replace('15\n', '30\n', 1), stamp('2026-11-01T05:59:00'))
        self.assertEqual(before.dates, ('2026-10-30',))
        m = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = m.Ledger(Path(tmp) / 'ledger.db')
            for row_id, heading in enumerate(['31', '16', '0', '15–17', '2020-10-15'], 1):
                text = CASH.replace('15\n', heading + '\n', 1)
                result = ledger.process_message(source_row_id=row_id, timestamp=stamp('2026-02-15T20:00:00'),
                    platform_message_id=str(row_id), content=text, compact_enabled=True)
                self.assertEqual(result.status, 'unverified', heading)
                with ledger._connection() as c:
                    self.assertIsNone(c.execute('SELECT * FROM messages WHERE source_row_id=?', (row_id,)).fetchone())
                    self.assertEqual(c.execute('SELECT raw_content FROM compact_sources WHERE source_row_id=?', (row_id,)).fetchone()[0], text)
            valid = CASH.replace('15\n', '03.10.2026\n', 1)
            result = ledger.process_message(source_row_id=20, timestamp=stamp(), platform_message_id='20',
                content=valid, compact_enabled=True)
            self.assertEqual(result.status, 'ok')
            with ledger._connection() as c:
                self.assertEqual(c.execute('SELECT accounting_date FROM messages WHERE source_row_id=20').fetchone()[0], '2026-10-03')
    def test_operator_only_accrual_is_not_revenue_or_model_cash_and_obeys_payout(self):
        m = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = m.Ledger(Path(tmp) / 'ledger.db')
            text = '15\nАнна / Fixture\n\n40'
            args = dict(source_row_id=1, timestamp=stamp(), platform_message_id='1',
                        content=text, compact_enabled=True)
            result = ledger.process_message(**args)
            self.assertEqual(result.status, 'operator_accrual')
            ledger.process_message(**args)
            self.assertEqual(ledger.register_statistics(), {})
            self.assertEqual(ledger.model_statistics(), {})
            self.assertEqual(ledger.agency_statistics(), {})
            self.assertEqual(ledger.operator_statistics(), {'Анна': 4000})
            payout = ledger.create_operator_payout(operator_name='Анна', command_source_row_id=2,
                command_timestamp=stamp(), requester_id='1', requester_name='Test')
            self.assertEqual(payout.total_minor, 4000)
            self.assertEqual(payout.by_date, (('2026-10-15', 4000),))
            ledger.process_message(source_row_id=3, timestamp=stamp('2026-10-16T20:00:00'),
                platform_message_id='3', content='16\nАнна / Fixture\n50', compact_enabled=True)
            payout = ledger.create_operator_payout(operator_name='Анна', command_source_row_id=4,
                command_timestamp=stamp('2026-10-16T20:00:00'), requester_id='1', requester_name='Test')
            self.assertEqual(payout.total_minor, 5000)
    def test_multiday_operator_summary_reuses_cash_and_daily_accruals_without_duplicates(self):
        m = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = m.Ledger(Path(tmp) / 'ledger.db')
            ledger.process_message(source_row_id=1, timestamp=stamp('2026-10-17T20:00:00'),
                platform_message_id='1', content=CASH, compact_enabled=True)
            ledger.process_message(source_row_id=2, timestamp=stamp('2026-10-17T20:00:00'),
                platform_message_id='2', content='16\nАнна / Fixture\n50', compact_enabled=True)
            text = '15–17\nАнна / Fixture\n15 — 40\n16 — 50\n17 — 40'
            for row_id in [3, 4]:
                result = ledger.process_message(source_row_id=row_id, timestamp=stamp('2026-10-17T20:00:00'),
                    platform_message_id=str(row_id), content=text, compact_enabled=True)
                self.assertEqual(result.status, 'operator_accrual')
            self.assertEqual(ledger.operator_statistics(), {'Анна': 13000})
            self.assertEqual(ledger.register_statistics(), {'Fixture': 90000})
            self.assertEqual(ledger.model_statistics(), {'Fixture': 54000})
            bad = text.replace('15 — 40', '15 — 41')
            result = ledger.process_message(source_row_id=5, timestamp=stamp('2026-10-17T20:00:00'),
                platform_message_id='5', content=bad, compact_enabled=True)
            self.assertEqual(result.status, 'unverified')
            self.assertEqual(ledger.operator_statistics(), {'Анна': 13000})
            with ledger._connection() as c:
                self.assertTrue(c.execute('SELECT line FROM parse_reviews WHERE source_row_id=5').fetchone())
            payout = ledger.create_operator_payout(operator_name='Анна', command_source_row_id=6,
                command_timestamp=stamp('2026-10-17T20:00:00'), requester_id='1', requester_name='Test')
            self.assertEqual(payout.total_minor, 13000)
    def test_compact_finance_uses_declared_previous_result_as_percentage_base(self):
        import json
        m = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = m.Ledger(Path(tmp) / 'ledger.db')
            text = '28–3\nFixture\n450+750+400+900+1350+900=4750\n14%=665\n−6%=625.10'
            for row_id, raw, expected in [(1, text, 'ok'), (2, text.replace('=665', '=666'), 'mismatch')]:
                notice = ledger.check_finance_message(source_row_id=row_id, timestamp=stamp(),
                    content=raw, compact_enabled=True)
                self.assertIn('Fixture', notice)
                self.assertIn('4750*14%', notice)
                with ledger._connection() as c:
                    row = c.execute('SELECT * FROM finance_checks WHERE source_row_id=?', (row_id,)).fetchone()
                    self.assertEqual(row['raw_content'], raw)
                    self.assertEqual(row['status'], expected)
                    checks = json.loads(row['checks_json'])
                    self.assertIn('665-6%' if row_id == 1 else '666-6%', checks[-1]['line'])
            self.assertEqual(ledger.register_statistics(), {})
            self.assertEqual(ledger.operator_statistics(), {})
            from cash_compact_formats import parse_compact
            self.assertEqual(parse_compact(text, stamp()).dates[0], '2026-09-28')
            self.assertEqual(parse_compact(text, stamp()).dates[-1], '2026-10-03')
            self.assertEqual(parse_compact(text.replace('28–3', '17–15'), stamp()).dates, ())
    def test_guidance_is_source_specific_preserves_declared_mismatch_and_unknowns(self):
        from cash_compact_formats import format_guidance
        raw = ('Касса Fixture\n15.10.2026\nClient Hr/450\nCash\nClient Hr/450 Venmo\n'
               'Итого: 901\nМодели: 540\nАгентских: 360\nОператор Анна: 40')
        advice = format_guidance(raw, stamp())
        self.assertIn('15\nFixture\n', advice)
        self.assertIn('450 Cash\n450 Venmo', advice)
        self.assertIn('Итого 901', advice)
        self.assertNotIn('Итого 900', advice)
        self.assertIn('Модели 540\nАгентству 360\nАнна 40', advice)
        advice = format_guidance('Касса SampleModel\n15.10\nClient Hr/450\nTotal: 450', stamp())
        self.assertIn('450 ?', advice)
        self.assertIn('Модели ?\nАгентству ?', advice)
        for text in [CASH, 'Привет! 40 минут', 'Выдача Анна', 'НОВЫЙ РАСЧЕТ!!']:
            self.assertIsNone(format_guidance(text, stamp()), text)
        self.assertIsNone(format_guidance(raw, stamp(), is_bot=True))
    def test_legacy_operator_and_finance_receive_their_own_same_data_templates(self):
        from cash_compact_formats import format_guidance
        operator = 'Модель 💎FixtureModel💎\nОпер Анна\n03.10.2026 + 40 💸'
        advice = format_guidance(operator, stamp())
        self.assertIsNotNone(advice)
        self.assertIn('3\nАнна / FixtureModel\n\n40', advice)
        m = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = m.Ledger(Path(tmp) / 'ledger.db')
            result = ledger.process_message(source_row_id=1, timestamp=stamp(),
                platform_message_id='1', content=operator, compact_enabled=True)
            self.assertEqual(result.status, 'operator_accrual')
            self.assertEqual(ledger.operator_statistics(), {'Анна': 4000})
        finance = 'Финмониторинг\nМодель: Fixture\nДаты: 28 сентября–3 октября\n450+450=901\n901*14%=126.14\n126.14-6%=118.57'
        advice = format_guidance(finance, stamp())
        self.assertIsNotNone(advice)
        self.assertIn('450+450=901', advice)
        self.assertIn('901*14%=126.14', advice)
        self.assertIn('Даты: 28 сентября–3 октября', advice)
        self.assertNotIn('450+450=900', advice)
    def test_cash_after_operator_accrual_does_not_duplicate_running_balance_or_payout(self):
        m = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = m.Ledger(Path(tmp) / 'ledger.db')
            ledger.process_message(source_row_id=1, timestamp=stamp(), platform_message_id='1',
                content='15\nАнна / Fixture\n40', compact_enabled=True)
            ledger.process_message(source_row_id=2, timestamp=stamp(), platform_message_id='2',
                content=CASH, compact_enabled=True)
            ledger.process_message(source_row_id=3, timestamp=stamp('2026-10-16T20:00:00'),
                platform_message_id='3', content='16\nАнна / Fixture\n50', compact_enabled=True)
            self.assertEqual(ledger.operator_statistics(), {'Анна': 9000})
            ledger.process_message(source_row_id=4, timestamp=stamp('2026-10-17T20:00:00'),
                platform_message_id='4', content=CASH.replace('15\n', '17\n', 1), compact_enabled=True)
            self.assertIn('🥷🏻 Анна: 130$', ledger.cash_notice(4))
            payout = ledger.create_operator_payout(operator_name='Анна', command_source_row_id=5,
                command_timestamp=stamp('2026-10-17T20:00:00'), requester_id='1', requester_name='Test')
            self.assertEqual(payout.total_minor, 13000)

    def test_unsafe_historical_operator_accrual_is_reviewed_after_period_boundary(self):
        m = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = m.Ledger(Path(tmp) / 'ledger.db')
            ledger.record_period_start(source_row_id=1, timestamp=stamp('2026-10-16T20:00:00'),
                platform_message_id='1', content='[Owner|810000002]\nНОВЫЙ РАСЧЕТ!!')
            result = ledger.process_message(source_row_id=2, timestamp=stamp('2026-10-17T20:00:00'),
                platform_message_id='2', content='15\nАнна / Fixture\n40', compact_enabled=True)
            self.assertEqual(result.status, 'unverified')
            self.assertEqual(ledger.operator_statistics(), {})
    def test_later_conflicting_cash_is_reviewed_instead_of_reinterpreting_operator_accrual(self):
        m = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = m.Ledger(Path(tmp) / 'ledger.db')
            ledger.process_message(source_row_id=1, timestamp=stamp(), platform_message_id='1',
                content='15\nАнна / Fixture\n40', compact_enabled=True)
            bad = CASH.replace('Анна 40', 'Анна 41')
            result = ledger.process_message(source_row_id=2, timestamp=stamp(), platform_message_id='2',
                content=bad, compact_enabled=True)
            self.assertEqual(result.status, 'unverified')
            self.assertEqual(ledger.operator_statistics(), {'Анна': 4000})
            with ledger._connection() as c:
                self.assertEqual(c.execute('SELECT raw_content FROM compact_sources WHERE source_row_id=2').fetchone()[0], bad)

    def test_compact_preserves_sender_and_never_reparses_already_persisted_source(self):
        m = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = m.Ledger(Path(tmp) / 'ledger.db')
            text = '[User|123]\n' + CASH
            ledger.process_message(source_row_id=1, timestamp=stamp(), platform_message_id='1',
                content=text, compact_enabled=True)
            ledger.process_message(source_row_id=1, timestamp=stamp(), platform_message_id='1',
                content=text.replace('Анна 40', 'Анна 99\nЕва 20'), compact_enabled=True)
            with ledger._connection() as c:
                row = c.execute('SELECT * FROM messages').fetchone()
                self.assertEqual(row['sender_id'], '123')
                self.assertEqual(row['sender_name'], 'User')
                self.assertEqual(row['raw_content'], text)
            self.assertEqual(ledger.operator_statistics(), {'Анна': 4000})
    def test_guidance_preserves_identical_clients_and_declared_payment_components(self):
        from cash_compact_formats import format_guidance
        repeated = 'Касса Fixture\n15.10\nClient Hr/450 Cash\nClient Hr/450 Cash\nTotal: 900'
        advice = format_guidance(repeated, stamp())
        self.assertEqual(advice.count('450 Cash'), 2)
        split = 'Касса Fixture\n15.10\nClient Hr/450\nZelle (100) + Cash (350)\nTotal: 450'
        advice = format_guidance(split, stamp())
        self.assertIn('450 = Zelle 100 + Cash 350', advice)
        historic = repeated.replace('15.10', '15.09.2026')
        self.assertIn('15.09.2026\nFixture', format_guidance(historic, stamp()))

    def test_incomplete_or_unsupported_compact_input_is_retained_for_review_and_guidance(self):
        from cash_compact_formats import format_guidance
        m = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = m.Ledger(Path(tmp) / 'ledger.db')
            for row_id, text in enumerate(['15\nFixture\n450 Cash', CASH + '\nИтого 901',
                CASH.replace('15\n', '31\n', 1), '15–17\nАнна / Fixture\n15 — 40\n17 — 40'], 1):
                result = ledger.process_message(source_row_id=row_id, timestamp=stamp(),
                    platform_message_id=str(row_id), content=text, compact_enabled=True)
                self.assertEqual(result.status, 'unverified', text)
                advice = format_guidance(text, stamp())
                self.assertIsNotNone(advice, text)
                self.assertIn('Fixture', advice)
                self.assertIn('450' if '450' in text else '40', advice)
    def test_operator_aliases_and_payment_breakdowns_cannot_create_fake_accruals(self):
        m = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = m.Ledger(Path(tmp) / 'ledger.db')
            for row_id, text in [(1, '15\nAnna / 💎fixture💎\n40'), (2, CASH)]:
                ledger.process_message(source_row_id=row_id, timestamp=stamp(), platform_message_id=str(row_id),
                    content=text, compact_enabled=True)
            self.assertEqual(ledger.operator_statistics(), {'Анна': 4000})
            result = ledger.process_message(source_row_id=3, timestamp=stamp(), platform_message_id='3',
                content=CASH.replace('15\n', '14\n', 1) + '\nCash 450', compact_enabled=True)
            self.assertEqual(result.status, 'unverified')
            self.assertNotIn('Cash', ledger.operator_statistics())
    def test_operator_source_retry_cannot_add_days_not_in_original_source(self):
        m = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = m.Ledger(Path(tmp) / 'ledger.db')
            ledger.process_message(source_row_id=1, timestamp=stamp('2026-10-16T20:00:00'),
                platform_message_id='1', content='15\nАнна / Fixture\n40', compact_enabled=True)
            ledger.process_message(source_row_id=1, timestamp=stamp('2026-10-16T20:00:00'),
                platform_message_id='1', content='16\nАнна / Fixture\n99', compact_enabled=True)
            self.assertEqual(ledger.operator_statistics(), {'Анна': 4000})
            with ledger._connection() as c:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM compact_operator_days').fetchone()[0], 1)
    def test_suggested_explicit_addition_round_trips_without_inventing_a_client_total(self):
        from cash_compact_formats import format_guidance
        text = 'Касса Fixture\n15.10\nClient Hr/100+400 Cash\nTotal: 500'
        advice = format_guidance(text, stamp())
        self.assertIn('100+400 Cash', advice)
        m = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = m.Ledger(Path(tmp) / 'ledger.db')
            result = ledger.process_message(source_row_id=1, timestamp=stamp(), platform_message_id='1',
                content='15\nFixture\n100+400 Cash\nИтого 500', compact_enabled=True)
            self.assertEqual(result.status, 'ok')
            self.assertEqual(result.computed_total_minor, 50000)
    def test_named_chatter_without_accounting_data_gets_no_format_advice(self):
        from cash_compact_formats import format_guidance
        for raw in ['Касса завтра\nПривет всем', 'Касса Fixture\n15.10\nКак дела?',
                    'Финмониторинг\nМодель: Fixture\nОбсудим позже']:
            self.assertIsNone(format_guidance(raw, stamp()), raw)
    def test_legacy_guidance_keeps_historical_operator_date_and_payment_annotations(self):
        from cash_compact_formats import format_guidance
        operator = 'Модель Fixture\nОпер Анна\n03.09.2026 + 40'
        self.assertIn('03.09.2026\nАнна / Fixture', format_guidance(operator, stamp()))
        source = 'Касса Fixture\n15.10\nClient Hr/500\nДепозит Zelle (holder) 400 +100 Cash\nTotal: 500'
        self.assertIn('Депозит Zelle (holder) 400 +100 Cash', format_guidance(source, stamp()))
    def test_unknown_or_ambiguous_names_cannot_be_fabricated_into_ledger_keys(self):
        m = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = m.Ledger(Path(tmp) / 'ledger.db')
            for row_id, text in enumerate([CASH.replace('Fixture', '?'), CASH.replace('Fixture', '123'),
                '15\nАнна / Fixture / Sample\n40'], 1):
                result = ledger.process_message(source_row_id=row_id, timestamp=stamp(), platform_message_id=str(row_id),
                    content=text, compact_enabled=True)
                self.assertEqual(result.status, 'unverified', text)
            self.assertEqual(ledger.register_statistics(), {})
            self.assertEqual(ledger.operator_statistics(), {})
    def test_running_operator_period_starts_at_earliest_separate_accrual(self):
        m = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = m.Ledger(Path(tmp) / 'ledger.db')
            ledger.process_message(source_row_id=1, timestamp=stamp(), platform_message_id='1',
                content='14\nАнна / Fixture\n40', compact_enabled=True)
            ledger.process_message(source_row_id=2, timestamp=stamp(), platform_message_id='2',
                content=CASH, compact_enabled=True)
            self.assertIn('🥷🏻 Анна: 80$ — с 14.10 (ср)', ledger.cash_notice(2))


if __name__ == '__main__':
    unittest.main()
