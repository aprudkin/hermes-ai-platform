"""Quoted history is context, not another accounting source."""
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from test_cash_ledger_monitor import load_module

class QuotedReportTests(unittest.TestCase):
    def test_rendered_quotes_do_not_replace_new_report_or_its_date(self):
        m = load_module()
        old = 'Касса OldFixture\n01.09.2026\nClient Hr/229\nTotal: 229'
        fresh = '[Fixture|810000003]\nКасса NewFixture\n05.10.2026\nClient Hr/137\nTotal: 137'
        quotes = [f'[Replying to: "{old}"]',
                  f'[Replying to your previous message: "{old}"]',
                  '\n'.join('> ' + line for line in old.splitlines()),
                  f'<blockquote>\n{old}\n</blockquote>']
        for quote in quotes:
            with self.subTest(quote=quote), tempfile.TemporaryDirectory() as tmp:
                content = quote + '\n\n' + fresh
                parsed = m.parse_message(content)
                self.assertEqual(parsed.register_name, 'NewFixture')
                self.assertEqual(parsed.claimed_total_minor, 13700)
                ledger = m.Ledger(Path(tmp)/'ledger.db')
                ledger.process_message(source_row_id=1, timestamp=1791252477,
                                       platform_message_id='1', content=content)
                with ledger._connection() as db:
                    row = db.execute('SELECT accounting_date,raw_content FROM messages').fetchone()
                self.assertEqual(row['accounting_date'], '2026-10-05')
                self.assertEqual(row['raw_content'], content)

    def test_quote_only_and_control_text_never_become_reports(self):
        m = load_module()
        from cash_compact_formats import parse_compact
        old = '05\nFixture\n137 Cash\nИтого: 137'
        for body in ['', 'Добавь галочку в конец отчёта', 'Да, всё верно']:
            content = f'[Replying to your previous message: "{old}"]\n\n[Fixture|810000003]\n' + body
            self.assertIsNone(parse_compact(content, 1791252477))
            parsed = m.parse_message(content)
            self.assertIsNone(parsed.claimed_total_minor)
            self.assertEqual(parsed.entries, ())

    def test_quoted_finance_is_not_checked_by_direct_entrypoint(self):
        m = load_module()
        content = '[Replying to: "[Fixture Reporter|810000003]\nФинмониторинг\nМодель: Fixture\n100+37=137"]\n\n[Fixture|810000003]\nДобавь галочку'
        with tempfile.TemporaryDirectory() as tmp:
            ledger = m.Ledger(Path(tmp)/'ledger.db')
            self.assertIsNone(ledger.check_finance_message(source_row_id=1,timestamp=1791252477,content=content))

    def test_old_report_quote_does_not_create_another_clarification(self):
        m = load_module()
        report = '[Fixture Reporter|810000003]\nКасса FixtureQuote\n05.10\nClient Hr/137\nНеоднозначная запись 229\nTotal: 366'
        confirmation = '[Replying to: "' + report + '"]\n\n[Fixture User|810000002]\nДа, все верно.'
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with closing(sqlite3.connect(home / 'state.db')) as db:
                db.executescript('CREATE TABLE sessions(id INTEGER,chat_id TEXT); CREATE TABLE messages(id INTEGER,session_id INTEGER,role TEXT,active INTEGER,content TEXT,timestamp REAL,platform_message_id TEXT);')
                db.execute("INSERT INTO sessions VALUES(1,'fixture-chat')")
                db.executemany("INSERT INTO messages VALUES(?,1,'user',1,?,1791252477,?)", [(1, report, '1'), (2, confirmation, '2')])
                db.commit()
            questions = []
            ledger = m.Ledger(home/'ledger.db')
            m.run_monitor(source_db=home/'state.db', ledger=ledger,
                          state_path=home/'cursor.json', stats_path=home/'stats.json',
                          chat_id='fixture-chat', reply_sender=lambda *_: None,
                          review_sender=questions.append)
            self.assertEqual(len(questions), 1, 'quoted old report creates a duplicate clarification')
            with ledger._connection() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM messages').fetchone()[0], 1)
