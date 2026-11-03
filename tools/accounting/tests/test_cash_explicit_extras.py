import tempfile
import unittest
from pathlib import Path
from tests.test_cash_ledger_monitor import load_module

REPORT = '''Касса 🍒FixtureExtra🍒
Fixture City
11 .02
1️⃣ ✅Клиент 10:05 Hr/170 +35доп
Venmo (Fixture Holder)
2️⃣✅Клиент 11:05 Hr/170
Cash
3️⃣ ✅Клиент 12:05 Hr/170
Cash
4️⃣ ✅Клиент 13:05 Hr/170
Cash
5️⃣ ✅Клиент 14:05 Hr/170
Cash
6️⃣ ✅Клиент 15:05 Hr/170
Cash
Итого: 1020
Из них:
(205) Venmo (Fixture Holder)
(850) Cash
Модели: 650
Агентских: 405
Оператор Тестовая: 19'''


class ExplicitExtrasTests(unittest.TestCase):
    def test_scheduled_path_replies_once_with_verified_total_and_final_check(self):
        import sqlite3
        m = load_module()
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            with sqlite3.connect(home / 'state.db') as c:
                c.executescript('CREATE TABLE sessions(id INTEGER,chat_id TEXT); CREATE TABLE messages(id INTEGER,session_id INTEGER,role TEXT,active INTEGER,content TEXT,timestamp REAL,platform_message_id TEXT);')
                c.execute("INSERT INTO sessions VALUES(1,'-1008000000001')")
                c.execute("INSERT INTO messages VALUES(1,1,'user',1,?,1793289000,'265')", (REPORT,))
            calls = []
            args = dict(source_db=home/'state.db', ledger=m.Ledger(home/'ledger.db'),
                state_path=home/'cursor.json', stats_path=home/'stats.json',
                chat_id='-1008000000001', reply_sender=lambda mid,text: calls.append((mid,text)))
            self.assertEqual(m.run_monitor(**args), '')
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], '265')
            self.assertIn('**11.02 (ср):**', calls[0][1])
            self.assertIn('✅ Итого: 1,020$ — сходится ✅', calls[0][1])
            self.assertTrue(calls[0][1].endswith('✅'))
            self.assertEqual(m.run_monitor(**args), '')
            self.assertEqual(len(calls), 1)

    def test_spaced_source_date_wins_over_later_receipt_day(self):
        m = load_module()
        self.assertEqual(m._extract_accounting_date(REPORT, 1793289000), '2026-02-11')

    def test_synthetic_report_excludes_explicit_extra_from_base_revenue(self):
        m = load_module()
        parsed = m.parse_message(REPORT)
        self.assertEqual(sum(e.amount_minor for e in parsed.entries), 102000)
        self.assertEqual(parsed.review_lines, ())
        self.assertEqual(parsed.model_amount_minor, 65000)
        self.assertEqual(parsed.agency_amount_minor, 40500)
        self.assertEqual(parsed.operators[0].amount_minor, 1900)
        with tempfile.TemporaryDirectory() as t:
            ledger = m.Ledger(Path(t) / 'ledger.db')
            result = ledger.process_message(source_row_id=1, timestamp=1793289000,
                platform_message_id='265', content=REPORT)
            self.assertEqual(result.status, 'ok')
            self.assertIn('сходится ✅', ledger.cash_notice(1))


if __name__ == '__main__':
    unittest.main()
