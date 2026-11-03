"""Unfixed source defect: quoted reports are re-ingested as new clarification cases."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from test_cash_ledger_monitor import load_module

class QuotedReportTests(unittest.TestCase):
    @unittest.expectedFailure  # Preserved source bug; quoted reports must not be treated as fresh reports.
    def test_old_report_quote_does_not_create_another_clarification(self):
        m = load_module()
        report = '[Fixture Reporter|810000003]\nКасса FixtureQuote\n05.10\nClient Hr/137\nНеоднозначная запись 229\nTotal: 366'
        confirmation = '[Replying to: "' + report + '"]\n\n[Fixture User|810000002]\nДа, все верно.'
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with sqlite3.connect(home / 'state.db') as db:
                db.executescript('CREATE TABLE sessions(id INTEGER,chat_id TEXT); CREATE TABLE messages(id INTEGER,session_id INTEGER,role TEXT,active INTEGER,content TEXT,timestamp REAL,platform_message_id TEXT);')
                db.execute("INSERT INTO sessions VALUES(1,'fixture-chat')")
                db.executemany("INSERT INTO messages VALUES(?,1,'user',1,?,1791252477,?)", [(1, report, '1'), (2, confirmation, '2')])
            questions = []
            m.run_monitor(source_db=home/'state.db', ledger=m.Ledger(home/'ledger.db'),
                          state_path=home/'cursor.json', stats_path=home/'stats.json',
                          chat_id='fixture-chat', reply_sender=lambda *_: None,
                          review_sender=questions.append)
            self.assertEqual(len(questions), 1, 'quoted old report creates a duplicate clarification')
