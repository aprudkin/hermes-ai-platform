import tempfile
import unittest
from pathlib import Path
from tests.test_cash_ledger_monitor import load_module

class CoverageTests(unittest.TestCase):
    def test_unknown_number_cannot_silently_verify_a_partial_total(self):
        m=load_module()
        content='Касса Fixture\n05.10\nClient 13:00 Hr/500\nСтранная запись 300\nTotal: 500\nYours: 300\nОператор Анна: 20'
        p=m.parse_message(content)
        self.assertEqual(p.review_lines, ('Странная запись 300',))
        with tempfile.TemporaryDirectory() as t:
            ledger=m.Ledger(Path(t)/'ledger.db')
            r=ledger.process_message(source_row_id=1,timestamp=1791252477,platform_message_id='1',content=content)
            self.assertEqual(r.status,'unverified')
            self.assertIsNone(r.computed_total_minor)
            self.assertIsNone(r.difference_minor)
            self.assertEqual(ledger.cash_notice(1),'')
            with ledger._connection() as c:
                self.assertEqual(c.execute('SELECT line FROM parse_reviews').fetchone()[0],'Странная запись 300')

    def test_future_formats_are_flagged_instead_of_silently_skipped(self):
        m=load_module()
        for line in ['Client 13:00 15 мин/300', 'Client 13:00 2sessions/600', 'Client 13:00 cash $500', 'Client 13:00 50 USD', 'Доплата 300', 'Клиент 13:00 500 + чаевые 20', 'Client Hr/1,200', 'Client Hr/10 100', 'Client Hr/500  + 300']:
            with self.subTest(line=line):
                p=m.parse_message('Касса Fixture\n05.10\n'+line+'\nTotal: 500')
                self.assertTrue(p.review_lines)
        p=m.parse_message('Касса Fixture\n05.10.2026\nВремя 21:00\n120 min\nClient 1pm Hr/500\nTotal: 500\nYours: 300\nОператор Анна: 20')
        self.assertFalse(p.review_lines)
        self.assertEqual(p.model_amount_minor,30000)
        self.assertEqual(p.operators[0].amount_minor,2000)

    def test_unrecognized_small_operator_amount_requires_review(self):
        m=load_module()
        p=m.parse_message('Касса Fixture\nClient Hr/500\nTotal: 500\nОпер Анна = 20')
        self.assertEqual(p.review_lines,('Опер Анна = 20',))

    def test_monitor_routes_unknown_line_for_private_review_once(self):
        import sqlite3
        m=load_module()
        with tempfile.TemporaryDirectory() as t:
            home=Path(t)
            c=sqlite3.connect(home/'state.db')
            c.executescript("CREATE TABLE sessions(id TEXT,chat_id TEXT); CREATE TABLE messages(id INTEGER,session_id TEXT,role TEXT,active INTEGER,content TEXT,timestamp REAL,platform_message_id TEXT);")
            c.execute("INSERT INTO sessions VALUES ('s','chat')")
            c.execute("INSERT INTO messages VALUES (1,'s','user',1,?,1791252477,'77')",('Касса Fixture\n05.10\nClient Hr/500\nСтранная запись 300\nTotal: 800',))
            c.commit();c.close()
            private=[];group=[]
            args=dict(source_db=home/'state.db',ledger=m.Ledger(home/'ledger.db'),state_path=home/'state.json',stats_path=home/'stats.json',chat_id='chat',reply_sender=lambda i,t:group.append(t),review_sender=private.append)
            m.run_monitor(**args);m.run_monitor(**args)
            self.assertEqual(len(private),1)
            self.assertIn('Странная запись 300',private[0])
            self.assertIn('Fixture',private[0])
            self.assertEqual(len(group),1)
            self.assertNotIn('не сходится',group[0])
            self.assertIn('не завершена',group[0])

if __name__=='__main__': unittest.main()
