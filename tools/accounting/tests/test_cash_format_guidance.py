"""Opt-in monitor/reply integration; all databases and transports are temporary."""
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from test_cash_ledger_monitor import load_module
from test_cash_compact_formats import CASH, stamp
from cash_reply_sender import ReplySender

CHAT = '-1008000000001'
LEGACY = 'Касса Fixture\n15.10\nClient Hr/450 Cash\nTotal: 450\nYours: 270\nAgent fees: 180\nОператор Анна: 20'


class GuidanceIntegrationTests(unittest.TestCase):
    def setup_monitor(self, home, sources):
        with closing(sqlite3.connect(home / 'source.db')) as c:
            c.executescript('CREATE TABLE sessions(id INTEGER,chat_id TEXT); CREATE TABLE messages(id INTEGER,session_id INTEGER,role TEXT,active INTEGER,content TEXT,timestamp REAL,platform_message_id TEXT);')
            c.execute('INSERT INTO sessions VALUES(1,?)', (CHAT,))
            for row_id, text, role in sources:
                c.execute('INSERT INTO messages VALUES(?,1,?,1,?,?,?)', (row_id, role, text, stamp(), str(row_id + 100)))
            c.commit()
        m = load_module()
        return m, dict(source_db=home / 'source.db', ledger=m.Ledger(home / 'ledger.db'),
            state_path=home / 'cursor.json', stats_path=home / 'stats.json', chat_id=CHAT)

    def test_guidance_can_be_disabled_without_disabling_ingestion(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            m, args = self.setup_monitor(home, [(1, LEGACY, 'user'), (2, CASH, 'user')])
            (home / 'format-guidance.json').write_text(json.dumps({
                'enabled': True, 'after_source_row_id': 0, 'guidance_enabled': False}))
            calls=[]
            args['reply_sender']=lambda mid,text:calls.append((mid,text))
            m.run_monitor(**args)
            self.assertEqual(len(calls),2)
            self.assertTrue(all('Необязательный короткий формат' not in text for mid,text in calls))
            self.assertEqual(args['ledger'].register_statistics(), {'Fixture': 90000})

    def test_baseline_gate_only_guides_new_sources_in_one_anchored_receipted_reply(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            m, args = self.setup_monitor(home, [(1, LEGACY, 'user'), (2, LEGACY, 'user'),
                (3, CASH, 'user'), (4, LEGACY, 'assistant'), (5, 'Привет', 'user')])
            (home / 'format-guidance.json').write_text(json.dumps({'enabled': True, 'after_source_row_id': 1}))
            calls = []
            def post(payload):
                calls.append(payload)
                return {'chat': {'id': int(CHAT)}, 'message_id': len(calls) + 1000,
                    'reply_to_message': {'message_id': payload['reply_parameters']['message_id']}}
            sender = ReplySender(home, CHAT, post=post)
            args['reply_sender'] = sender
            self.assertEqual(m.run_monitor(**args), '')
            self.assertEqual([p['reply_parameters']['message_id'] for p in calls], [101, 102, 103])
            self.assertNotIn('Необязательный', calls[0]['text'])
            self.assertIn('Необязательный', calls[1]['text'])
            self.assertIn('450 Cash', calls[1]['text'])
            self.assertNotIn('Необязательный', calls[2]['text'])
            self.assertEqual(args['ledger'].register_statistics(), {'Fixture': 90000})
            self.assertEqual(m.run_monitor(**args), '')
            self.assertEqual(len(calls), 3)
            # Simulated retry from existing checkpoint: ReplySender receipts suppress duplicates.
            (home / 'cursor.json').write_text(json.dumps({'last_seen_message_rowid': 0}))
            m.run_monitor(**args)
            self.assertEqual(len(calls), 3)
    def test_operator_finance_and_review_sources_each_get_one_specific_reply(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            operator = 'Модель 💎FixtureModel💎\nОпер Анна\n03.10.2026 + 40 💸'
            finance = 'Финмониторинг\nМодель: Fixture\n100+100=201\n201*14%=28.14'
            no_total = 'Касса SampleModel\n15.10\nClient Hr/450 Cash'
            bad = CASH.replace('15\n', '31\n', 1)
            m, args = self.setup_monitor(home, [(1, operator, 'user'), (2, finance, 'user'),
                (3, no_total, 'user'), (4, bad, 'user')])
            (home / 'format-guidance.json').write_text(json.dumps({'enabled': True, 'after_source_row_id': 0}))
            calls, reviews = [], []
            args.update(reply_sender=lambda mid, text: calls.append((mid, text)), review_sender=reviews.append)
            m.run_monitor(**args)
            self.assertEqual([r[0] for r in calls], ['101', '102', '103', '104'])
            self.assertIn('Анна / FixtureModel', calls[0][1])
            self.assertIn('100+100=201', calls[1][1])
            self.assertIn('450 Cash', calls[2][1])
            self.assertEqual(calls[2][1].count('Необязательный'), 1)
            self.assertIn('уточнения', calls[3][1])
            self.assertEqual(len(reviews), 1)
            self.assertIn('31', reviews[0])
            self.assertIn('/104', reviews[0])

    def test_missing_malformed_or_disabled_gate_keeps_legacy_path(self):
        for gate in [None, '{bad', '{}', '[]', '{"enabled":true}',
                     '{"enabled":true,"after_source_row_id":true}',
                     '{"enabled":true,"after_source_row_id":-1}',
                     '{"enabled":false,"after_source_row_id":0}']:
            with self.subTest(gate=gate), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                m, args = self.setup_monitor(home, [(1, CASH, 'user'), (2, LEGACY, 'user')])
                if gate is not None:
                    (home / 'format-guidance.json').write_text(gate)
                calls = []
                args['reply_sender'] = lambda mid, text: calls.append(text)
                m.run_monitor(**args)
                self.assertEqual(len(calls), 1)
                self.assertNotIn('Необязательный', calls[0])
                self.assertEqual(args['ledger'].register_statistics(), {'Fixture': 45000})
                with args['ledger']._connection() as c:
                    self.assertIsNone(c.execute("SELECT name FROM sqlite_master WHERE name='compact_sources'").fetchone())
    def test_guidance_receipts_are_once_per_source_even_if_rendered_text_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            calls = []
            def post(payload):
                calls.append(payload)
                return {'chat': {'id': int(CHAT)}, 'message_id': 1000,
                    'reply_to_message': {'message_id': 101}}
            sender = ReplySender(home, CHAT, post=post)
            first = 'Notice\nНеобязательный короткий формат с теми же исходными суммами:\n15\nFixture\n450 Cash'
            sender('101', first)
            sender('101', first + '\n? — неизвестно')
            self.assertEqual(len(calls), 1)
            with closing(sqlite3.connect(sender.path)) as c:
                self.assertEqual(c.execute('SELECT status,source_message_id FROM receipts').fetchall(), [('sent', 101)])

    def test_uncertain_guidance_never_retries_under_a_changed_text_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            def post(payload):
                calls.append(payload)
                raise RuntimeError('transport unknown')
            sender = ReplySender(Path(tmp), CHAT, post=post)
            text = 'Необязательный короткий формат:\n15\nFixture\n450 Cash'
            with self.assertRaises(RuntimeError):
                sender('101', text)
            with self.assertRaises(RuntimeError):
                sender('101', text + '\nchanged')
            self.assertEqual(len(calls), 1)
    def test_compact_finance_notice_uses_source_period_and_ambiguous_period_is_reviewed(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            finance = '28–3\nFixture\n100+100=200\n14%=28\n−6%=26.32'
            m, args = self.setup_monitor(home, [(1, finance, 'user'), (2, finance.replace('28–3', '17–15'), 'user')])
            (home / 'format-guidance.json').write_text(json.dumps({'enabled': True, 'after_source_row_id': 0}))
            calls, reviews = [], []
            args.update(reply_sender=lambda mid, text: calls.append((mid, text)), review_sender=reviews.append)
            m.run_monitor(**args)
            self.assertIn('28.09 (пн) — 03.10 (сб)', calls[0][1])
            self.assertIn('дата', calls[1][1].casefold())
            self.assertEqual(len(reviews), 1)
            self.assertIn('/102', reviews[0])
            self.assertEqual(args['ledger'].register_statistics(), {})

    def test_native_bot_flag_excludes_bot_authored_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            m, args = self.setup_monitor(home, [(1, LEGACY, 'user'), (2, LEGACY, 'user')])
            with closing(sqlite3.connect(home / 'source.db')) as c:
                c.execute('ALTER TABLE messages ADD COLUMN is_bot INTEGER DEFAULT 0')
                c.execute('UPDATE messages SET is_bot=1 WHERE id=1')
                c.commit()
            (home / 'format-guidance.json').write_text(json.dumps({'enabled': True, 'after_source_row_id': 0}))
            calls = []
            args['reply_sender'] = lambda mid, text: calls.append(mid)
            m.run_monitor(**args)
            self.assertEqual(calls, ['102'])


if __name__ == '__main__':
    unittest.main()
