"""Offline tests for the recovered content-free System notifier; no Telegram I/O."""
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / 'tools/system_status/hermes_manager_status.py'


class StatusTest(unittest.TestCase):
    def load(self, configured=True):
        self.assertTrue(SOURCE.is_file(), 'recovered notifier source missing')
        env = {'HERMES_STATUS_CHAT_ID': '-1001234567890', 'HERMES_STATUS_BOT_ID': '123456',
               'HERMES_STATUS_JOB_IDS': 'aaaaaaaaaaaa,bbbbbbbbbbbb'} if configured else {}
        with mock.patch.dict(os.environ, env, clear=True):
            spec = importlib.util.spec_from_file_location('status_under_test', SOURCE)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        return module

    def transport(self, module, calls, *, lose=False, wrong=False, state=None):
        def call(method, payload):
            calls.append((method, payload))
            if state is not None:
                with module.connect(state) as db:
                    self.assertEqual(db.execute('SELECT status FROM sends').fetchone()[0],
                                     'sent' if method == 'editMessageText' else 'intent')
            if method == 'getMe':
                return {'ok': True, 'result': {'id': module.BOT}}
            if method == 'getChat':
                return {'ok': True, 'result': {'id': module.CHAT, 'type': 'supergroup'}}
            if method == 'getChatMember':
                return {'ok': True, 'result': {'user': {'id': module.BOT}, 'status': 'administrator'}}
            if method == 'sendMessage':
                if lose:
                    raise TimeoutError('private diagnostics must not be persisted')
                return {'ok': True, 'result': {'chat': {'id': 0 if wrong else module.CHAT},
                        'from': {'id': module.BOT}, 'message_id': 123, 'text': payload['text']}}
            return {'ok': False, 'error_code': 400, 'description': 'Bad Request: message is not modified'}
        return call

    def test_no_target_defaults_and_missing_config_fails_before_io(self):
        module = self.load(configured=False)
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'not-created'
            calls = []
            with self.assertRaisesRegex(ValueError, 'configuration'):
                module.send('test:missing', 'test', state=state, transport=lambda *a: calls.append(a))
            self.assertFalse(state.exists())
            self.assertEqual(calls, [])

    def test_intent_is_durable_before_network_and_delivery_is_quiet(self):
        module = self.load()
        with tempfile.TemporaryDirectory() as tmp:
            state, calls = Path(tmp), []
            transport = self.transport(module, calls, state=state)
            first = module.send('test:one', 'test', state=state, transport=transport)
            second = module.send('test:one', 'test', state=state, transport=transport)
            self.assertEqual(first['status'], 'verified')
            self.assertEqual(second['message_id'], 123)
            sends = [payload for method, payload in calls if method == 'sendMessage']
            self.assertEqual(len(sends), 1)
            self.assertEqual(sends[0]['chat_id'], -1001234567890)
            self.assertTrue(sends[0]['disable_notification'])
            self.assertTrue(sends[0]['protect_content'])
            self.assertTrue(sends[0]['link_preview_options']['is_disabled'])

    def test_uncertain_response_is_never_automatically_retried(self):
        module = self.load()
        for lose, wrong in ((True, False), (False, True)):
            with self.subTest(lose=lose, wrong=wrong), tempfile.TemporaryDirectory() as tmp:
                calls, state = [], Path(tmp)
                transport = self.transport(module, calls, lose=lose, wrong=wrong)
                self.assertEqual(module.send('test:uncertain', 'test', state=state,
                                             transport=transport)['status'], 'uncertain')
                module.send('test:uncertain', 'test', state=state, transport=transport)
                self.assertEqual(sum(method == 'sendMessage' for method, _ in calls), 1)
                self.assertNotIn('private diagnostics', (state / 'receipts.db').read_bytes().decode(errors='ignore'))

    def test_receipt_cannot_be_reused_after_target_reconfiguration(self):
        module = self.load()
        with tempfile.TemporaryDirectory() as tmp:
            calls, state = [], Path(tmp)
            transport = self.transport(module, calls)
            module.send('test:target', 'test', state=state, transport=transport)
            module.CHAT = -1009876543210
            before = len(calls)
            with self.assertRaisesRegex(ValueError, 'collision'):
                module.send('test:target', 'test', state=state, transport=transport)
            self.assertEqual(len(calls), before)

    def test_static_content_allowlist_and_connections_close(self):
        module = self.load()
        for event, job in (('PRIVATE OUTPUT', None), ('cron-start', 'cccccccccccc')):
            with self.assertRaises(ValueError):
                module.render(event, job)
        with tempfile.TemporaryDirectory() as tmp:
            with module.connect(Path(tmp)) as db:
                db.execute('SELECT 1')
            with self.assertRaises(sqlite3.ProgrammingError):
                db.execute('SELECT 1')
            labels = Path(tmp) / 'labels.json'
            labels.write_text(json.dumps({'aaaaaaaaaaaa': 'Synthetic task'}))
            with mock.patch.object(module, 'LABELS', labels):
                self.assertEqual(module.render('cron-start', 'aaaaaaaaaaaa'), 'Synthetic task — началась.')
                labels.write_text(json.dumps({'aaaaaaaaaaaa': 'untrusted\nlabel'}))
                with self.assertRaises(ValueError):
                    module.render('cron-start', 'aaaaaaaaaaaa')

    def test_cron_events_only_allowlisted_scheduled_runs_without_payloads(self):
        module = self.load()
        row = dict(id='synthetic-run', job_id='aaaaaaaaaaaa', scheduled_instant='synthetic',
                   started_at='synthetic', status='completed', output='PRIVATE', error='SECRET')
        self.assertEqual(list(module.cron_events([row])), [
            ('cron:synthetic-run:start', 'cron-start', 'aaaaaaaaaaaa'),
            ('cron:synthetic-run:terminal', 'cron-ok', 'aaaaaaaaaaaa')])
        self.assertEqual(list(module.cron_events([dict(row, scheduled_instant=None)])), [])
        self.assertEqual(list(module.cron_events([dict(row, job_id='cccccccccccc')])), [])
        self.assertEqual(list(module.cron_events([dict(row, status='unknown', started_at=None)])), [
            ('cron:synthetic-run:terminal', 'cron-unknown', 'aaaaaaaaaaaa')])

    def test_observer_activation_excludes_history_and_reads_database_only(self):
        module = self.load()
        with tempfile.TemporaryDirectory() as tmp:
            state, home = Path(tmp) / 'state', Path(tmp) / 'home'
            (home / 'cron').mkdir(parents=True)
            source = home / 'cron/executions.db'
            with closing(sqlite3.connect(source)) as db, db:
                db.execute('CREATE TABLE executions(id,job_id,status,scheduled_instant,started_at,claimed_at)')
                db.execute('INSERT INTO executions VALUES(?,?,?,?,?,?)',
                           ('old', 'aaaaaaaaaaaa', 'completed', 'old', 'old', '2000-01-01T00:00:00+00:00'))
            events = []
            def sender(*args, **kwargs):
                events.append(args)
            self.assertEqual(module.observe_once(home=home, state=state, sender=sender), 0)
            with closing(sqlite3.connect(source)) as db, db:
                db.execute('INSERT INTO executions VALUES(?,?,?,?,?,?)',
                           ('new', 'aaaaaaaaaaaa', 'completed', 'new', 'new', '2999-01-01T00:00:00+00:00'))
            before = source.read_bytes()
            self.assertEqual(module.observe_once(home=home, state=state, sender=sender), 2)
            self.assertEqual([e[0] for e in events], ['cron:new:start', 'cron:new:terminal'])
            self.assertEqual(source.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
