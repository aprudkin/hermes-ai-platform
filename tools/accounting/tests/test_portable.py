"""Synthetic accounting-only round trips; never read a real profile."""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bablomat_portable as portable

CHAT = '-1008000000001'
REVIEW = '-1008000000002'


class PortableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'snapshot'
        self.home.mkdir()
        cash = self.home / 'cash-ledger'
        cash.mkdir()
        with sqlite3.connect(self.home / 'state.db') as db:
            db.executescript('''
                CREATE TABLE schema_version(version INTEGER);
                INSERT INTO schema_version VALUES(1);
                CREATE TABLE sessions(id TEXT PRIMARY KEY, source TEXT NOT NULL,
                  chat_id TEXT, thread_id TEXT, started_at REAL NOT NULL, ended_at REAL,
                  session_key TEXT, system_prompt TEXT, origin_json TEXT, archived INTEGER DEFAULT 0);
                CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT NOT NULL REFERENCES sessions(id), role TEXT NOT NULL,
                  content TEXT, timestamp REAL NOT NULL, platform_message_id TEXT,
                  active INTEGER DEFAULT 1, observed INTEGER DEFAULT 0, tool_calls TEXT);
                CREATE TABLE private_settings(value TEXT);
                INSERT INTO private_settings VALUES('UNRELATED-SECRET');
                CREATE VIRTUAL TABLE messages_fts USING fts5(content,content='messages',content_rowid='id');
                CREATE TRIGGER index_message AFTER INSERT ON messages BEGIN
                  INSERT INTO messages_fts(rowid,content) VALUES(new.id,new.content); END;
            ''')
            db.executemany('INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?,?,?)', [
                ('cash', 'telegram', CHAT, None, 1, None, 'old-session', 'PRIVATE-PROMPT', 'PRIVATE-ORIGIN', 0),
                ('review', 'telegram', REVIEW, None, 1, None, None, None, None, 0),
                ('private', 'telegram', '810000001', None, 1, None, None, None, None, 0)])
            db.executemany('INSERT INTO messages(id,session_id,role,content,timestamp,platform_message_id,tool_calls) VALUES(?,?,?,?,?,?,?)', [
                (10, 'cash', 'user', 'Synthetic closed report: 100', 1, '101', 'PRIVATE-TOOLS'),
                (12, 'cash', 'user', 'Synthetic payment confirmation', 2, '102', None),
                (20, 'cash', 'user', 'Synthetic open report: 200', 3, '103', None),
                (21, 'cash', 'user', 'UNRELATED-CHATTER', 4, '104', None),
                (30, 'review', 'user', 'Synthetic linked clarification', 5, '201', None),
                (31, 'review', 'user', 'UNRELATED-REVIEW-CHATTER', 6, '202', None),
                (900, 'private', 'user', 'UNRELATED-CONVERSATION', 7, '301', None)])
        with sqlite3.connect(cash / 'ledger.db') as db:
            db.executescript('''
                CREATE TABLE messages(source_row_id INTEGER PRIMARY KEY, platform_message_id TEXT,
                  accounting_date TEXT, computed_total_minor INTEGER, raw_content TEXT);
                INSERT INTO messages VALUES(10,'101','2026-01-01',10000,'Synthetic closed report: 100');
                INSERT INTO messages VALUES(20,'103','2026-01-03',20000,'Synthetic open report: 200');
                CREATE TABLE period_closures(confirmation_source_row_id INTEGER,
                  report_source_row_id INTEGER, recipient_kind TEXT, period_end TEXT);
                INSERT INTO period_closures VALUES(12,10,'model','2026-01-01');
                CREATE TABLE model_payouts(command_source_row_id INTEGER, total_minor INTEGER);
                INSERT INTO model_payouts VALUES(12,10000);
                CREATE TABLE parse_reviews(source_row_id INTEGER, line TEXT);
                INSERT INTO parse_reviews VALUES(20,'Synthetic unresolved amount');
            ''')
        with sqlite3.connect(cash / 'review-cases.db') as db:
            db.executescript('''
                CREATE TABLE responses(source_row_id INTEGER, chat_id TEXT, message_id TEXT);
                CREATE TABLE cases(case_id TEXT, group_state TEXT, reply_status TEXT);
                INSERT INTO cases VALUES('case-a','uncertain','open');
            ''')
            db.execute('INSERT INTO responses VALUES(30,?,?)', (REVIEW, '201'))
        with sqlite3.connect(cash / 'reply-deliveries.db') as db:
            db.executescript('''CREATE TABLE receipts(key TEXT, status TEXT, source_message_id INTEGER,
                sent_message_id INTEGER,text TEXT);
                INSERT INTO receipts VALUES('synthetic','uncertain',103,NULL,'Synthetic reply');''')
        with sqlite3.connect(cash / 'native-inputs.db') as db:
            db.execute('CREATE TABLE native_inputs(chat_id TEXT,message_id TEXT,payload TEXT,conflicted INTEGER)')
            db.executemany('INSERT INTO native_inputs VALUES(?,?,?,0)', [
                (CHAT, '102', '{"text":"Synthetic payment confirmation"}'),
                (CHAT, '104', '{"text":"UNRELATED-NATIVE-CHATTER"}')])
        self.write_json(cash / 'monitor-state.json', {'chat_id': CHAT, 'last_seen_message_rowid': 21})
        self.write_json(cash / 'format-guidance.json', {'enabled': True, 'guidance_enabled': False, 'after_source_row_id': 9})
        self.write_json(self.home / 'config.yaml', {'platforms': {'telegram': {
            'allowed_chats': [CHAT, REVIEW, '-1008000000003', '-1008000000004', '-1008000000005'],
            'group_allowed_chats': [CHAT, REVIEW], 'free_response_chats': [REVIEW],
            'require_mention': True, 'channel_prompts': {CHAT: 'OLD-MIXED-INSTRUCTIONS'}}},
            'model': 'UNRELATED-MODEL', 'plugins': {'enabled': ['unrelated-social']}})
        (self.home / '.env').write_text('TELEGRAM_BOT_TOKEN=synthetic-placeholder\nTELEGRAM_ALLOWED_USERS=810000001,810000002\nUNRELATED_API_KEY=UNRELATED-KEY\n')
        for name in portable.RUNTIME_FILES:
            f = self.home / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text('# synthetic inert runtime\n')
        report = self.home / 'reports' / 'synthetic'
        report.mkdir(parents=True)
        (report / 'report.json').write_text('{"total_minor":30000}')
        self.selection = self.root / 'selection.json'
        self.write_json(self.selection, {'chat_id': CHAT, 'artifacts': ['reports/synthetic'], 'source_rows': []})
        self.bundle = self.root / 'bundle'

    def write_json(self, path, value):
        path.write_text(json.dumps(value))

    def export(self):
        return portable.export_bundle(self.home, self.bundle, self.selection)

    def test_round_trip_preserves_all_accounting_without_other_conversations(self):
        self.export()
        manifest = portable.verify_bundle(self.bundle)
        self.assertEqual(manifest['source_high_water'], 900)
        target = self.root / 'imported'
        portable.import_bundle(self.bundle, target)
        for name in portable.DATABASES:
            if name == 'native-inputs.db':
                continue
            self.assertEqual(portable.database_inventory(self.home / 'cash-ledger' / name),
                             portable.database_inventory(target / 'cash-ledger' / name))
        with sqlite3.connect(target / 'state.db') as db:
            self.assertEqual([r[0] for r in db.execute('SELECT id FROM messages ORDER BY id')], [10, 12, 20, 30])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM private_settings').fetchone()[0], 0)
            self.assertTrue(all(row == (None, None, None, 1) for row in db.execute(
                'SELECT system_prompt,origin_json,session_key,archived FROM sessions')))
            db.execute("INSERT INTO sessions(id,source,chat_id,started_at) VALUES('new','telegram',?,10)", (CHAT,))
            cursor = db.execute("INSERT INTO messages(session_id,role,content,timestamp,platform_message_id) VALUES('new','user','new report',10,'105')")
            self.assertIsNotNone(cursor.lastrowid)
            self.assertGreater(cursor.lastrowid or 0, 900)
        self.assertEqual(json.loads((target / 'cash-ledger/monitor-state.json').read_text())['last_seen_message_rowid'], 900)
        all_bytes = b''.join(f.read_bytes() for f in self.bundle.rglob('*') if f.is_file())
        for forbidden in (b'UNRELATED-', b'PRIVATE-PROMPT', b'PRIVATE-TOOLS', b'PRIVATE-ORIGIN', b'OLD-MIXED-INSTRUCTIONS'):
            self.assertNotIn(forbidden, all_bytes)
        routes = json.loads((target / 'telegram-settings.json').read_text())
        self.assertEqual(len(routes['allowed_chats']), 5)
        self.assertNotIn('channel_prompts', routes)
        inactive = json.loads((target / 'config.yaml').read_text())
        self.assertFalse(inactive['platforms']['telegram']['enabled'])
        self.assertEqual(inactive['plugins']['enabled'], [])
        self.assertIn('accounting-native-input', inactive['plugins']['disabled'])
        self.assertFalse((target / '.env').exists())
        self.assertFalse((target / 'cron').exists())
        self.assertTrue((target / 'skills/bablomat-accounting/SKILL.md').is_file())
        self.assertEqual((target / 'reports/synthetic/report.json').read_text(), '{"total_minor":30000}')
        with self.assertRaises(FileExistsError):
            portable.import_bundle(self.bundle, target)

    def test_export_requires_caught_up_source_and_leaves_no_completed_bundle(self):
        with sqlite3.connect(self.home / 'state.db') as db:
            db.execute("INSERT INTO messages(id,session_id,role,content,timestamp,platform_message_id) VALUES(901,'cash','user','pending report',10,'105')")
        with self.assertRaisesRegex(ValueError, 'unprocessed'):
            self.export()
        self.assertFalse(self.bundle.exists())

    def test_missing_evidence_fails_instead_of_claiming_complete_history(self):
        with sqlite3.connect(self.home / 'state.db') as db:
            db.execute('DELETE FROM messages WHERE id=12')
        with self.assertRaisesRegex(ValueError, 'source rows'):
            self.export()

    def test_explicit_artifact_cannot_overwrite_filtered_core_state(self):
        self.write_json(self.selection, {'chat_id': CHAT,
                        'artifacts': ['cash-ledger/native-inputs.db', 'cash-ledger/monitor-state.json'],
                        'source_rows': []})
        self.export()
        with sqlite3.connect(self.bundle / 'payload/cash-ledger/native-inputs.db') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM native_inputs').fetchone()[0], 1)
        state = json.loads((self.bundle / 'payload/cash-ledger/monitor-state.json').read_text())
        self.assertEqual(state['last_seen_message_rowid'], 900)

    def test_new_wal_during_export_is_detected(self):
        original = portable.filtered_state

        def changing(*args):
            result = original(*args)
            (self.home / 'state.db-wal').write_bytes(b'changed-after-snapshot')
            return result

        with patch.object(portable, 'filtered_state', side_effect=changing), self.assertRaisesRegex(ValueError, 'snapshot changed'):
            self.export()
        self.assertFalse(self.bundle.exists())

    def test_unknown_artifacts_are_not_silently_included(self):
        self.write_json(self.selection, {'chat_id': CHAT, 'artifacts': ['../private'], 'source_rows': []})
        with self.assertRaises(ValueError):
            self.export()

    def test_symlinks_and_changing_snapshot_are_rejected(self):
        f = self.home / 'reports/synthetic/link'
        f.symlink_to(self.home / '.env')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.export()
        f.unlink()
        original = portable.filtered_state

        def changing(*args):
            result = original(*args)
            (self.home / '.env').write_text('changed')
            return result

        with patch.object(portable, 'filtered_state', side_effect=changing), self.assertRaisesRegex(ValueError, 'snapshot changed'):
            self.export()

    def test_corruption_and_extra_files_block_import(self):
        self.export()
        (self.bundle / 'payload/cash-ledger/ledger.db').write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            portable.import_bundle(self.bundle, self.root / 'bad-target')
        self.assertFalse((self.root / 'bad-target').exists())

    def test_unlisted_file_and_manifest_path_escape_are_rejected(self):
        self.export()
        (self.bundle / 'payload/extra').write_text('unexpected')
        with self.assertRaises(ValueError):
            portable.verify_bundle(self.bundle)
        (self.bundle / 'payload/extra').unlink()
        manifest = json.loads((self.bundle / 'manifest.json').read_text())
        manifest['files']['../outside'] = 'not-a-hash'
        self.write_json(self.bundle / 'manifest.json', manifest)
        with self.assertRaises(ValueError):
            portable.verify_bundle(self.bundle)

    def test_real_ledger_continues_once_without_reopening_paid_periods(self):
        from cash_ledger_monitor import Ledger, run_monitor

        ledger_path = self.home / 'cash-ledger/ledger.db'
        ledger_path.unlink()
        ledger = Ledger(ledger_path)
        for row_id, day, total in ((10, '01.10', 1000), (20, '03.10', 500)):
            text = (f'Касса Fixture\n{day}\nКлиент Hr/{total}\nИтого: {total}\n'
                    f'Модели: {total * 6 // 10}\nАгентских: {total * 4 // 10}\nОператор Анна: 10')
            ledger.process_message(source_row_id=row_id, timestamp=1791000000,
                                   platform_message_id=str(row_id), content=text)
        ledger.create_model_payout(model_name='Fixture', command_source_row_id=12,
                                  command_timestamp=1791000000, requester_id='810000001', requester_name='Fixture')
        before = ledger.cash_notice(20)
        self.export()
        target = self.root / 'continued'
        portable.import_bundle(self.bundle, target)
        restored = Ledger(target / 'cash-ledger/ledger.db')
        self.assertEqual(restored.cash_notice(20), before)
        sent = []

        def run():
            return run_monitor(source_db=target / 'state.db', ledger=restored,
                               state_path=target / 'cash-ledger/monitor-state.json',
                               stats_path=target / 'cash-ledger/daily-stats.json', chat_id=CHAT,
                               reply_sender=lambda message, text: sent.append((message, text)))

        run()
        self.assertEqual(sent, [])
        with sqlite3.connect(target / 'state.db') as db:
            db.execute("INSERT INTO sessions(id,source,chat_id,started_at) VALUES('new','telegram',?,10)", (CHAT,))
            db.execute("INSERT INTO messages(session_id,role,content,timestamp,platform_message_id) VALUES('new','user',?,1791100000,'105')",
                       ('Касса Fixture\n04.10\nКлиент Hr/500\nИтого: 500\nМодели: 300\nАгентских: 200\nОператор Анна: 10',))
        run()
        run()
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], '105')
        with sqlite3.connect(target / 'cash-ledger/ledger.db') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM model_payouts').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM agency_payouts').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM messages').fetchone()[0], 3)

    def test_wal_commits_are_included_in_an_offline_snapshot(self):
        with sqlite3.connect(self.home / 'cash-ledger/ledger.db') as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('INSERT INTO parse_reviews VALUES(20,\'Synthetic WAL evidence\')')
            db.commit()
            self.export()
        with sqlite3.connect(self.bundle / 'payload/cash-ledger/ledger.db') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM parse_reviews').fetchone()[0], 2)

    def test_unknown_telegram_settings_fail_instead_of_disappearing(self):
        config = json.loads((self.home / 'config.yaml').read_text())
        config['platforms']['telegram']['new_authorization_gate'] = True
        self.write_json(self.home / 'config.yaml', config)
        with self.assertRaisesRegex(ValueError, 'Unrecognized Telegram'):
            self.export()

    def test_cli_is_inert_and_requires_offline_acknowledgment(self):
        import subprocess
        import sys

        script = Path(__file__).resolve().parents[1] / 'scripts/bablomat_portable.py'
        result = subprocess.run([sys.executable, str(script), 'export', '--home', str(self.home),
                                 '--selection', str(self.selection), '--destination', str(self.bundle)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.bundle.exists())
        self.assertNotIn('synthetic-placeholder', result.stdout + result.stderr)

    def test_real_hermes_schema_can_reopen_and_append_after_filtering(self):
        import subprocess
        import sys

        self.assertTrue(os.environ.get('HERMES_SRC'), 'Set HERMES_SRC to the pinned test checkout')
        script = '''
import os, sys, sqlite3
from pathlib import Path
sys.path.insert(0, os.environ['HERMES_SRC'])
from hermes_state import SessionDB
from bablomat_portable import filtered_state
home = Path(os.environ['HERMES_HOME'])
source, target = home/'source.db', home/'filtered.db'
with SessionDB(source) as db:
    db.create_session('cash', 'telegram', chat_id='-1008000000001', system_prompt='PRIVATE-PROMPT')
    first = db.append_message('cash', 'user', 'Synthetic accounting report', platform_message_id='101')
    db.create_session('private', 'telegram', chat_id='810000001')
    last = db.append_message('private', 'user', 'UNRELATED-CONVERSATION')
assert filtered_state(source, target, {first}, '-1008000000001', first) == last
with SessionDB(target) as db:
    db.create_session('new', 'telegram', chat_id='-1008000000001')
    assert db.append_message('new', 'user', 'Synthetic new report', platform_message_id='102') > last
with sqlite3.connect(target) as db:
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert db.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 2
assert b'UNRELATED-CONVERSATION' not in target.read_bytes()
assert b'PRIVATE-PROMPT' not in target.read_bytes()
'''
        home = self.root / 'hermes-contract'
        home.mkdir()
        result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True,
                                env={**os.environ, 'HERMES_HOME': str(home)}, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_bundle_and_files_are_private(self):
        self.export()
        self.assertEqual(self.bundle.stat().st_mode & 0o777, 0o700)
        for f in self.bundle.rglob('*'):
            self.assertEqual(f.stat().st_mode & 0o777, 0o700 if f.is_dir() else 0o600)


if __name__ == '__main__':
    unittest.main()
