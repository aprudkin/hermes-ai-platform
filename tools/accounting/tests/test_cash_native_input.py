"""Offline: stdlib tests always run; real seams require Hermes + PTB on PYTHONPATH.
Run with the existing Hermes/CI venv and PYTHONPATH=/opt/hermes; no install/config.
Missing optional runtime dependencies explicitly skip only the real-adapter tests.
"""
import importlib.util
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NativeInputTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / 'scripts/cash_native_input.py').exists(), 'native capture module missing')
        self.native = load('cash_native_input', ROOT / 'scripts/cash_native_input.py')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.db = self.home / 'cash-ledger/native-inputs.db'

    def event(self, text='new approval'):
        reply = NS(chat=NS(id=-100123), message_id=40, text='FULL old report', caption=None)
        msg = NS(chat=NS(id=-100123), message_id=41, from_user=NS(id=123, is_bot=False),
                 reply_to_message=reply, quote=NS(text='old'), text=text, caption=None,
                 date=datetime(2026, 1, 2, tzinfo=timezone.utc))
        return NS(raw_message=msg, text='UNTRUSTED decorated text', source=NS(user_id=None))

    def test_exact_native_record_and_read_only_missing(self):
        self.assertIsNone(self.native.read_native(self.db, '-100123', '41'))
        self.assertFalse(self.db.exists())
        event = self.event()
        self.native.capture(self.home, '-100999', event)
        self.assertFalse(self.db.exists())
        self.native.capture(self.home, '-100123', event)
        row = self.native.read_native(self.db, '-100123', '41')
        self.assertEqual(row, dict(chat_id='-100123', message_id='41', sender_id='123', sender_is_bot=False,
                                  reply_to_chat_id='-100123', reply_to_message_id='40', reply_to_text='FULL old report',
                                  quote_text='old', text='new approval', timestamp='2026-01-02T00:00:00+00:00'))
        self.assertIsNone(self.native.read_native(self.db, '-100999', '41'))

    def test_new_native_database_is_private(self):
        import os
        import stat
        if os.name != 'posix':
            self.skipTest('POSIX permission contract')
        self.native.capture(self.home,'-100123',self.event())
        self.assertEqual(stat.S_IMODE(self.db.stat().st_mode),0o600)

    def test_conflicting_reuse_preserves_variants_and_never_recovers_authority(self):
        self.native.capture(self.home, '-100123', self.event())
        self.native.capture(self.home, '-100123', self.event())
        self.assertIsNotNone(self.native.read_native(self.db, '-100123', '41'))
        self.native.capture(self.home, '-100123', self.event('changed approval'))
        self.assertIsNone(self.native.read_native(self.db, '-100123', '41'))
        self.native.capture(self.home, '-100123', self.event())
        self.assertIsNone(self.native.read_native(self.db, '-100123', '41'))
        with closing(sqlite3.connect(self.db)) as db:
            variants = db.execute('SELECT payload,conflicted FROM native_inputs').fetchall()
        self.assertEqual(len(variants), 2)
        self.assertTrue(all(row[1] for row in variants))
        self.assertTrue(any('changed approval' in row[0] for row in variants))
        self.assertTrue(any('new approval' in row[0] for row in variants))

    def test_invalid_or_mismatched_stored_payload_is_not_evidence(self):
        self.native.capture(self.home, '-100123', self.event())

        for payload in ('[]', '{"chat_id":"-100999","message_id":"41"}'):
            with closing(sqlite3.connect(self.db)) as db, db:
                db.execute('UPDATE native_inputs SET payload=?', (payload,))
            self.assertIsNone(self.native.read_native(self.db, '-100123', '41'))

    def test_native_bot_caption_cross_chat_reply_without_quote(self):
        event = self.event()
        msg = event.raw_message
        msg.from_user.is_bot = True
        msg.reply_to_message.chat.id = -100456
        msg.reply_to_message.text = None
        msg.reply_to_message.caption = 'FULL caption'
        msg.text = None
        msg.caption = 'new caption'
        msg.quote = None
        self.native.capture(self.home, '-100123', event)
        row = self.native.read_native(self.db, '-100123', '41')
        self.assertTrue(row['sender_is_bot'])
        self.assertEqual(row['reply_to_chat_id'], '-100456')
        self.assertEqual(row['reply_to_text'], 'FULL caption')
        self.assertEqual(row['text'], 'new caption')
        self.assertIsNone(row['quote_text'])


try:
    from plugins.platforms.telegram.adapter import TelegramAdapter
    from gateway.config import PlatformConfig
    from gateway.platforms.base import MessageType
    from telegram import Chat, Message, TextQuote, User
except ImportError as exc:
    TelegramAdapter = None
    RUNTIME_SKIP = f'Optional Hermes/PTB imports unavailable: {exc}; use installed Hermes/CI venv + PYTHONPATH'


@unittest.skipIf(TelegramAdapter is None, globals().get('RUNTIME_SKIP', ''))
class RealTelegramTests(unittest.TestCase):
    def setUp(self):
        NativeInputTests.setUp(self)
        self.plugin = load('accounting_native_plugin', ROOT / 'plugin/__init__.py')
        self.env = patch.dict('os.environ', {'HERMES_HOME': str(self.home), 'BABLOMAT_CHAT_ID': ''})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.adapter = TelegramAdapter(PlatformConfig(extra={}))
        self.factories = []
        self.ctx = NS(config={'chat_id': '-100123'}, register_telegram_handler=self.factories.append)
        self.handlers = {}
        def add_handler(handler, group=0):
            self.handlers.setdefault(group, []).append(handler)
        self.app = NS(handlers=self.handlers, add_handler=add_handler)

    def message(self, number=41, chat_id=-100123):
        chat = Chat(chat_id, 'supergroup', title='Synthetic bookkeeping')
        reply = Message(40, datetime(2026, 1, 2, tzinfo=timezone.utc), chat,
                        from_user=User(900, 'Synthetic bot', True), text='FULL old report')
        return Message(number, reply.date, chat, from_user=User(123, 'Synthetic', False), text='new approval',
                       reply_to_message=reply, quote=TextQuote('old', 5))

    def wire(self):
        self.plugin.register(self.ctx)
        self.assertEqual(len(self.factories), 1)
        with patch.object(self.adapter, '_telegram_observe_allowed_chats', return_value={'-100123'}):
            self.factories[0](self.app, self.adapter)
        group = next(iter(self.handlers))
        self.assertLess(group, 0)
        return self.handlers[group][0]

    def deliver(self, handler, message):
        import asyncio
        from telegram import Update
        update = Update(77, message=message)
        check = handler.check_update(update)
        if check:
            asyncio.run(handler.handle_update(update, self.app, check, NS()))

    def test_native_handler_is_scoped_idempotent_and_does_not_patch_adapter(self):
        original = TelegramAdapter._build_message_event
        handler = self.wire()
        with patch.object(self.adapter, '_telegram_observe_allowed_chats', return_value={'-100123'}):
            self.factories[0](self.app, self.adapter)
        self.assertEqual(sum(map(len,self.handlers.values())),1)
        self.deliver(handler,self.message())
        self.deliver(handler,self.message(42,-100999))
        self.assertEqual(self.native.read_native(self.db,'-100123','41')['sender_id'],'123')
        self.assertIsNone(self.native.read_native(self.db,'-100999','42'))
        self.assertIs(TelegramAdapter._build_message_event,original)
        # Handler remains bound to its own profile even if process env changes.
        with patch.dict('os.environ',{'HERMES_HOME':str(self.home/'other')}):
            self.deliver(handler,self.message(43))
        self.assertFalse((self.home/'other/cash-ledger/native-inputs.db').exists())

    def test_missing_or_unauthorized_route_and_capture_failure(self):
        self.plugin.register(NS(config={},register_telegram_handler=self.factories.append))
        self.assertEqual(self.factories,[])
        self.plugin.register(self.ctx)
        with patch.object(self.adapter,'_telegram_observe_allowed_chats',return_value=set()):
            self.factories[0](self.app,self.adapter)
        self.assertEqual(self.handlers,{})
        handler=self.wire_after_registration()
        self.home.joinpath('cash-ledger').write_text('not a directory')
        with self.assertLogs(self.plugin.__name__,level='WARNING'):
            self.deliver(handler,self.message())

    def wire_after_registration(self):
        with patch.object(self.adapter,'_telegram_observe_allowed_chats',return_value={'-100123'}):
            self.factories[0](self.app,self.adapter)
        return self.handlers[next(iter(self.handlers))][0]

    def test_native_capture_before_observed_and_triggered_identity_is_removed(self):
        handler=self.wire()
        entries=[]
        self.adapter._session_store=NS(
            get_or_create_session=lambda source:(self.assertIsNone(source.user_id) or NS(session_id='synthetic')),
            append_to_transcript=lambda session_id,entry:entries.append(entry))
        self.deliver(handler,self.message())
        self.adapter._observe_unmentioned_group_message(self.message(),MessageType.TEXT)
        self.assertTrue(entries[0]['observed'])
        self.deliver(handler,self.message(42))
        event=self.adapter._build_message_event(self.message(42),MessageType.TEXT)
        with patch.object(self.adapter,'_telegram_observe_unmentioned_group_messages',return_value=True), \
             patch.object(self.adapter,'_telegram_observe_allowed_chats',return_value={'-100123'}):
            shared=self.adapter._apply_telegram_group_observe_attribution(event)
        self.assertIsNone(shared.source.user_id)
        for number in ('41','42'):
            row=self.native.read_native(self.db,'-100123',number)
            self.assertEqual(row['reply_to_message_id'],'40')
            self.assertEqual(row['reply_to_text'],'FULL old report')
            self.assertEqual(row['quote_text'],'old')
            self.assertEqual(row['sender_id'],'123')


if __name__ == '__main__':
    unittest.main()
