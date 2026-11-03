import tempfile
import unittest
from pathlib import Path
from tests.test_cash_ledger_monitor import load_module

class PeriodStartTests(unittest.TestCase):
    def test_new_period_excludes_old_accruals_without_erasing_history(self):
        m = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = m.Ledger(Path(tmp) / 'ledger.db')
            ledger.process_message(source_row_id=1, timestamp=1791249650, platform_message_id='1',
                content='Касса SampleModel\n04.10\nКлиент Hr/1700\nИтого: 1700\nМодели: 1020\nАгентских: 680\nОператор Анна: 60')
            self.assertTrue(ledger.record_period_start(source_row_id=2, timestamp=1791249652,
                platform_message_id='2', content='[Fixture Reporter|810000003]\nНОВЫЙ РАСЧЕТ!!'))
            ledger.process_message(source_row_id=3, timestamp=1791249654, platform_message_id='3',
                content='Касса SampleModel\n05.10\nКлиент Hr/500\nИтого: 500\nМодели: 300\nАгентских: 200\nОператор Анна: 30')
            notice = ledger.cash_notice(3)
            self.assertIn('🫦 SampleModel: 300$ — новый период с 05.10 (пн)', notice)
            self.assertIn('🥷🏻 Анна: 30$ — новый период с 05.10 (пн)', notice)
            self.assertIn('🎩 Агентство: 200$ — новый период с 05.10 (пн)', notice)
            self.assertNotIn('выплат ещё не было', notice)
            self.assertEqual(ledger.register_statistics(), {'SampleModel': 220000})
            self.assertIn('1,700$', ledger.cash_notice(1))
            model = ledger.create_model_payout(model_name='SampleModel', command_source_row_id=4,
                command_timestamp=1791249700, requester_id='810000001', requester_name='Owner')
            self.assertEqual(model.total_minor, 30000)
            op = ledger.create_operator_payout(operator_name='Анна', command_source_row_id=5,
                command_timestamp=1791249700, requester_id='810000001', requester_name='Owner')
            self.assertEqual(op.total_minor, 3000)
            with ledger._connection() as c:
                self.assertEqual(c.execute('SELECT total_minor FROM agency_payouts').fetchone()[0], 20000)
                self.assertEqual(c.execute('SELECT COUNT(*) FROM period_starts').fetchone()[0], 1)

    def test_monitor_handles_exact_marker_once_and_rejects_quotes(self):
        import sqlite3
        from contextlib import closing
        m = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with closing(sqlite3.connect(home / 'state.db')) as c:
                c.executescript('CREATE TABLE sessions(id TEXT,chat_id TEXT); CREATE TABLE messages(id INTEGER,session_id TEXT,role TEXT,active INTEGER,content TEXT,timestamp REAL,platform_message_id TEXT);')
                c.execute("INSERT INTO sessions VALUES ('s','chat')")
                c.executemany("INSERT INTO messages VALUES (?,'s','user',1,?,1791249654,?)", [
                    (1, '[Fixture Reporter|810000003]\nКасса SampleModel\n04.10\nКлиент Hr/1000\nИтого: 1000\nМодели: 600\nАгентских: 400\nОператор Анна: 60', '1'),
                    (2, '[Fixture Reporter|810000003]\nНОВЫЙ РАСЧЕТ!!', '2'),
                    (3, '[Fixture Reporter|810000003]\nКасса SampleModel\n05.10\nКлиент Hr/500\nИтого: 500\nМодели: 300\nАгентских: 200\nОператор Анна: 30', '3'),
                ])
                c.commit()
            ledger = m.Ledger(home / 'ledger.db')
            replies = []
            args = dict(source_db=home/'state.db',ledger=ledger,state_path=home/'cursor.json',stats_path=home/'stats.json',chat_id='chat',reply_sender=lambda i,t: replies.append((i,t)))
            m.run_monitor(**args)
            m.run_monitor(**args)
            self.assertEqual(len(replies), 2)
            self.assertIn('Анна: 30$ — новый период', replies[-1][1])
            for content in ['[Unknown|22]\nНОВЫЙ РАСЧЕТ!!', '[Owner|810000001]\nНовый расчет означает новый период!', '[Replying to: "НОВЫЙ РАСЧЕТ!!"]\n[Owner|810000001]\nДа']:
                self.assertFalse(ledger.record_period_start(source_row_id=4,timestamp=1791249654,platform_message_id='4',content=content))
            with ledger._connection() as c:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM period_starts').fetchone()[0], 1)

if __name__ == '__main__':
    unittest.main()
