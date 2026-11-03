import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from test_cash_reply_delivery import load_sender

CHAT = '-1008000000001'
OLD = '⚠️ Неверный итог 3750$'
NEW = '**Исправление**\nВерный итог 3600$ ✅'


def seed(sender, source, sent, text):
    key = hashlib.sha256(f'{sender.chat_id}:{source}:{text}'.encode()).hexdigest()
    with closing(sqlite3.connect(sender.path)) as c:
        c.execute('INSERT INTO receipts VALUES(?,?,?,?,?)', (key, 'sent', source, sent, text))
        c.commit()


def enable(home, chat=CHAT):
    p = home/'cash-ledger'/'correction-cleanup.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({'enabled': True, 'chat_id': chat, 'mode': 'delete_superseded_bot_notice'}))


class AutoDeleteCorrectionTests(unittest.TestCase):
    def test_verified_correction_deletes_only_old_bot_notice_and_keeps_audit(self):
        m = load_sender()
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            enable(home)
            events = []
            def post(payload):
                events.append(('post', payload['reply_parameters']['message_id']))
                return {'chat': {'id': int(CHAT)}, 'message_id': 101,
                        'reply_to_message': {'message_id': 100},
                        'text': 'Исправление\nВерный итог 3600$ ✅'}
            def edit(payload):
                events.append(('edit', payload['message_id']))
                return {'chat': {'id': int(CHAT)}, 'message_id': 100, 'text': OLD,
                        'entities': [{'type': 'strikethrough', 'offset': 0,
                                      'length': len(OLD.encode('utf-16-le'))//2}]}
            sender = m.ReplySender(home, CHAT, post=post, edit=edit)
            sender.delete = lambda payload: (events.append(('delete', payload['message_id'])) or {'ok': True, 'result': True})
            sender.verify_absent = lambda mid,text: (events.append(('absent', mid)) or True)
            seed(sender, 99, 100, OLD)
            sender('100', NEW)
            self.assertEqual(events, [('post', 100), ('delete', 100), ('absent', 100)])
            with closing(sqlite3.connect(sender.path)) as c:
                self.assertEqual(c.execute('SELECT text FROM receipts WHERE sent_message_id=100').fetchone()[0], OLD)
                self.assertEqual(c.execute('SELECT text FROM receipts WHERE sent_message_id=101').fetchone()[0], NEW)
                self.assertEqual(c.execute('SELECT status FROM superseded_deletions').fetchone()[0], 'deleted')
            sender('100', NEW)
            self.assertEqual(events, [('post', 100), ('delete', 100), ('absent', 100)])

    def test_unverified_replacement_text_never_deletes_old_notice(self):
        m = load_sender()
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            enable(home)
            events = []
            sender = m.ReplySender(home, CHAT, post=lambda payload: {
                'chat': {'id': int(CHAT)}, 'message_id': 101,
                'reply_to_message': {'message_id': 100}, 'text': 'Wrong text'})
            sender.delete = lambda payload: events.append(payload)
            seed(sender, 99, 100, OLD)
            with self.assertRaisesRegex(RuntimeError, 'Replacement text not verified'):
                sender('100', NEW)
            self.assertEqual(events, [])
            with closing(sqlite3.connect(sender.path)) as c:
                self.assertEqual(c.execute('SELECT status FROM receipts WHERE sent_message_id=100').fetchone()[0], 'sent')

    def test_user_source_or_unlinked_replacement_cannot_be_deleted(self):
        m = load_sender()
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            enable(home)
            sender = m.ReplySender(home, CHAT)
            events = []
            sender.delete = lambda payload: events.append(payload)
            seed(sender, 99, 100, OLD)
            seed(sender, 777, 101, NEW)
            with self.assertRaises(ValueError):
                sender.delete_superseded_message(99, 101)
            with self.assertRaises(ValueError):
                sender.delete_superseded_message(100, 101)
            with self.assertRaises(ValueError):
                sender.delete_superseded_message(101, 101)
            self.assertEqual(events, [])

    def test_wrong_chat_policy_does_not_authorize_delete(self):
        m = load_sender()
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            enable(home, chat='other-chat')
            sender = m.ReplySender(home, CHAT)
            with self.assertRaises(PermissionError):
                sender.delete_superseded_message(100, 101)

    def test_uncertain_delete_is_not_blindly_retried(self):
        m = load_sender()
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            enable(home)
            calls = []
            sender = m.ReplySender(home, CHAT, post=lambda payload: {
                'chat': {'id': int(CHAT)}, 'message_id': 101,
                'reply_to_message': {'message_id': 100},
                'text': 'Исправление\nВерный итог 3600$ ✅'})
            def delete(payload):
                calls.append(payload['message_id'])
                raise TimeoutError('uncertain')
            sender.delete = delete
            seed(sender, 99, 100, OLD)
            with self.assertRaises(TimeoutError):
                sender('100', NEW)
            with self.assertRaisesRegex(RuntimeError, 'uncertain'):
                sender('100', NEW)
            self.assertEqual(calls, [100])
            with closing(sqlite3.connect(sender.path)) as c:
                self.assertEqual(c.execute('SELECT status FROM superseded_deletions').fetchone()[0], 'uncertain')
                self.assertEqual(c.execute('SELECT text FROM receipts WHERE sent_message_id=101').fetchone()[0], NEW)

    def test_acknowledged_delete_rechecks_absence_without_resending_or_redeleting(self):
        m = load_sender()
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            enable(home)
            events = []
            sender = m.ReplySender(home, CHAT, post=lambda payload: {
                'chat': {'id': int(CHAT)}, 'message_id': 101,
                'reply_to_message': {'message_id': 100},
                'text': 'Исправление\nВерный итог 3600$ ✅'})
            sender.delete = lambda payload: (events.append('delete') or {'ok': True, 'result': True})
            sender.verify_absent = lambda mid,text: False
            seed(sender, 99, 100, OLD)
            with self.assertRaisesRegex(RuntimeError, 'absence not verified'):
                sender('100', NEW)
            sender.verify_absent = lambda mid,text: True
            sender('100', NEW)
            self.assertEqual(events, ['delete'])
            with closing(sqlite3.connect(sender.path)) as c:
                self.assertEqual(c.execute('SELECT status FROM superseded_deletions').fetchone()[0], 'deleted')


if __name__ == '__main__':
    unittest.main()
