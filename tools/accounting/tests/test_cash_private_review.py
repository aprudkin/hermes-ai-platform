"""Offline contract tests. Transports are synthetic, never Telegram delivery claims."""
import hashlib
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from cash_review_sender import PrivateReviewSender

GROUP = '-1008000000002'
ELENA = '810000002'
OWNER = '810000001'
NOW = 1800000000
QUESTION = ('БАБЛОМАТ — Fixture, 05.10 (пн), https://t.me/c/8000000001/77\n'
            'Неоднозначные строки: Client 15 мин/300\nУточни сумму, пожалуйста.')
NAMES = ['Ле']


@contextmanager
def connect(path):
    with closing(sqlite3.connect(path)) as c, c:
        yield c


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.posts = []
        self.now = NOW

    def post(self, payload):
        self.posts.append(payload)
        return {'chat': {'id': int(payload['chat_id'])}, 'message_id': 100 + len(self.posts),
                'date': int(self.now), 'text': payload['text'],
                'entities': payload.get('entities', [])}

    def sender(self, **kwargs):
        return PrivateReviewSender(self.home, post=kwargs.pop('post', self.post), clock=lambda: self.now, **kwargs)

    def case(self):
        with connect(self.home / 'cash-ledger' / 'review-cases.db') as c:
            c.row_factory = sqlite3.Row
            return dict(c.execute('SELECT * FROM cases').fetchone())

    def test_invalid_group_receipts_become_uncertain_and_never_retry(self):
        changes = [
            {'chat': {'id': int(OWNER)}}, {'chat': {'id': -1008000000001}},
            {'text': 'wrong'}, {'message_id': 0}, {'message_id': True},
            {'date': None}, {'date': -1}, {'date': NOW + 1000},
            {'entities': []}, {'entities': [{'type': 'text_mention', 'offset': 0,
               'length': 5, 'user': {'id': int(OWNER)}}]},
        ]
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as t:
                calls = []
                def wrong(payload):
                    calls.append(payload)
                    result = self.post(payload)
                    result.update(change)
                    return result
                sender = PrivateReviewSender(Path(t), post=wrong, clock=lambda: self.now)
                with self.assertRaises(RuntimeError):
                    sender(QUESTION)
                with self.assertRaises(RuntimeError):
                    sender(QUESTION)
                self.assertEqual(len(calls), 1)
                with connect(sender.path) as c:
                    self.assertEqual(c.execute('SELECT group_state FROM cases').fetchone()[0], 'uncertain')

    def test_legacy_private_receipts_are_read_only_and_not_replayed(self):
        path = self.home / 'cash-ledger' / 'reply-deliveries.db'
        path.parent.mkdir()
        with connect(path) as c:
            c.execute('CREATE TABLE receipts(key TEXT PRIMARY KEY,status TEXT,source_message_id INTEGER,sent_message_id INTEGER,text TEXT)')
            for index, status in enumerate(['sent', 'pending', 'edited']):
                text = QUESTION + status
                key = hashlib.sha256(('private-review:' + OWNER + ':' + text).encode()).hexdigest()
                c.execute('INSERT INTO receipts VALUES(?,?,0,100,?)', (key, status, text))
            c.commit()
        before = path.read_bytes()
        for status in ['sent', 'pending', 'edited']:
            self.assertIsNone(self.sender()(QUESTION + status))
        self.assertEqual(self.posts, [])
        self.assertEqual(path.read_bytes(), before)
        with connect(self.home / 'cash-ledger' / 'review-cases.db') as c:
            self.assertEqual(c.execute('SELECT count(*) FROM cases').fetchone()[0], 0)

    def test_escalation_is_six_hours_later_exact_question_once_only(self):
        sender = self.sender()
        sender(QUESTION)
        self.assertTrue(callable(getattr(sender, 'process_due', None)), 'durable due-case processor required')
        self.now = NOW + 21599
        self.assertEqual(sender.process_due(), 0)
        self.assertEqual(len(self.posts), 1)
        self.now = NOW + 21600
        self.assertEqual(sender.process_due(), 1)
        self.assertEqual(self.sender().process_due(), 0)
        row = self.case()
        self.assertEqual(row['due_at'], NOW + 21600)
        self.assertEqual(row['escalation_state'], 'sent')
        self.assertEqual(row['escalation_message_id'], 102)
        reminder = self.posts[1]
        self.assertEqual(reminder['chat_id'], ELENA)
        self.assertIs(reminder['disable_notification'], False)
        self.assertTrue(reminder['text'].startswith(row['greeting'] + ','))
        self.assertIn(QUESTION, reminder['text'])
        self.assertIn('https://t.me/c/8000000002/101', reminder['text'])
        self.assertNotIn('reply_parameters', reminder)
        self.assertEqual({p['chat_id'] for p in self.posts}, {GROUP, ELENA})

    def observations(self, *, native=False):
        path = self.home / 'state.db'
        with connect(path) as c:
            c.executescript('''CREATE TABLE sessions(id TEXT PRIMARY KEY,chat_id TEXT,source TEXT,user_id TEXT);
                CREATE TABLE messages(id INTEGER PRIMARY KEY,session_id TEXT,role TEXT,active INTEGER,
                content TEXT,timestamp REAL,platform_message_id TEXT,reply_to_message_id TEXT,reply_to_chat_id TEXT);''')
            c.execute('INSERT INTO sessions VALUES(?,?,?,?)', ('group', GROUP, 'telegram', None))
            c.execute('INSERT INTO sessions VALUES(?,?,?,?)', ('dm', ELENA, 'telegram', ELENA))
        return path

    def add_observation(self, *, text='да', sender=ELENA, reply='101', chat=GROUP,
                        active=1, role='user', timestamp=NOW, platform='telegram'):
        with connect(self.home / 'state.db') as c:
            session = 's' + str(c.execute('SELECT count(*) FROM sessions').fetchone()[0])
            c.execute('INSERT INTO sessions VALUES(?,?,?,?)', (session, chat, platform, sender if chat == ELENA else None))
            c.execute('INSERT INTO messages(session_id,role,active,content,timestamp,platform_message_id,reply_to_message_id) VALUES(?,?,?,?,?,?,?)',
                      (session, role, active, f'[Elena|{sender}]\n{text}', timestamp, '500', reply))

    def test_exact_native_elena_reply_suppresses_reminder_without_financial_action(self):
        sender = self.sender()
        sender(QUESTION)
        self.observations()
        self.add_observation()
        self.assertTrue(callable(getattr(sender, 'scan_replies', None)), 'saved observation scanner required')
        self.assertEqual(sender.scan_replies(self.home / 'state.db'), 1)
        self.assertEqual(self.case()['reply_status'], 'responded')
        self.assertEqual(sender.scan_replies(self.home / 'state.db'), 0)
        self.now += 21600
        self.assertEqual(sender.process_due(), 0)
        self.assertEqual(len(self.posts), 1)
        self.assertFalse((self.home / 'cash-ledger' / 'ledger.db').exists())

    def test_case_link_and_full_quote_replies_work_without_native_columns(self):
        for mode in ['case', 'link', 'quote']:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as t:
                self.home = Path(t)
                self.posts = []
                sender = self.sender()
                key = sender(QUESTION)
                self.observations()
                row = self.case()
                reference = {'case': f'[case:{key}]', 'link': 'https://t.me/c/8000000002/101',
                             'quote': f'[Replying to your previous message: "{row["group_text"]}"]'}[mode]
                self.add_observation(text=reference + '\nЭто сумма клиента 300.', reply=None, chat=ELENA)
                with connect(self.home / 'state.db') as c:
                    c.execute('ALTER TABLE messages DROP COLUMN reply_to_message_id')
                    c.execute('ALTER TABLE messages DROP COLUMN reply_to_chat_id')
                before = (self.home / 'state.db').read_bytes()
                self.assertEqual(sender.scan_replies(self.home / 'state.db'), 1)
                self.assertEqual(self.case()['reply_status'], 'responded')
                self.assertEqual((self.home / 'state.db').read_bytes(), before)

    def test_unrelated_or_unverified_observations_do_not_answer_case(self):
        variants = [
            {'reply': None}, {'reply': '999'}, {'sender': '111'}, {'chat': OWNER},
            {'chat': '-1008000000001'}, {'active': 0}, {'role': 'assistant'},
            {'timestamp': NOW - 1}, {'platform': 'discord'},
            {'timestamp': NOW + 1000},
            {'sender': OWNER, 'chat': ELENA, 'reply': None,
             'text': 'https://t.me/c/8000000002/101\nВопрос закрыт.'},
            {'reply': None, 'text': 'Касса Fixture — а сколько денег?'},
            {'text': 'Другой вопрос про Fixture?'},
            {'text': 'Привет!'}, {'text': '🧡'}, {'text': 'Новая касса Fixture'},
            {'text': 'да', 'reply_chat': '-1008000000001'},
            {'reply': None, 'text': 'https://t.me/c/8000000002/1010\nда'},
            {'reply': None, 'text': '[case:wrong]\nда'},
            {'reply': None, 'text': 'https://t.me/c/8000000002/101\n'},
        ]
        for options in variants:
            with self.subTest(options=options), tempfile.TemporaryDirectory() as t:
                self.home = Path(t)
                self.posts = []
                sender = self.sender()
                sender(QUESTION)
                self.observations()
                options = options.copy()
                reply_chat = options.pop('reply_chat', None)
                self.add_observation(**options)
                if reply_chat:
                    with connect(self.home / 'state.db') as c:
                        c.execute('UPDATE messages SET reply_to_chat_id=?', (reply_chat,))
                self.assertEqual(sender.scan_replies(self.home / 'state.db'), 0)
                self.assertEqual(self.case()['reply_status'], 'open')

    def test_owner_must_explicitly_resolve_referenced_question(self):
        sender = self.sender()
        sender(QUESTION)
        self.observations()
        self.add_observation(sender=OWNER, text='да')
        self.assertEqual(sender.scan_replies(self.home / 'state.db'), 0)
        self.add_observation(sender=OWNER, text='Вопрос закрыт.')
        self.assertEqual(sender.scan_replies(self.home / 'state.db'), 1)
        self.assertEqual(self.case()['reply_status'], 'resolved')
        self.now += 21600
        self.assertEqual(sender.process_due(), 0)
        self.assertEqual(len(self.posts), 1)

    def test_diagnostic_case_can_be_cancelled_with_owner_audit(self):
        sender = self.sender()
        key = sender('Прозрачная проверка настройки: тестовый вопрос, не кассовая операция.')
        self.assertTrue(callable(getattr(sender, 'cancel_case', None)), 'auditable diagnostic cancellation required')
        with self.assertRaises(ValueError):
            sender.cancel_case(key, actor_id='111', reason='test')
        with self.assertRaises(ValueError):
            sender.cancel_case(key, actor_id=OWNER, reason='')
        self.assertTrue(sender.cancel_case(key, actor_id=OWNER, reason='setup verification complete'))
        self.assertFalse(sender.cancel_case(key, actor_id=OWNER, reason='duplicate cancellation'))
        self.now += 21600
        self.assertEqual(sender.process_due(), 0)
        self.assertEqual(self.case()['reply_status'], 'cancelled')
        with connect(sender.path) as c:
            event = c.execute('SELECT actor_id,reason FROM cancellations').fetchone()
            self.assertEqual(event, (OWNER, 'setup verification complete'))
        self.assertEqual(len(self.posts), 1)

    def test_sending_is_committed_and_crash_never_retries_either_phase(self):
        for phase in ['group', 'escalation']:
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as t:
                self.home = Path(t)
                self.posts = []
                self.now = NOW
                if phase == 'escalation':
                    self.sender()(QUESTION)
                    self.now += 21600
                def crash(payload):
                    row = self.case()
                    self.assertEqual(row[phase + '_state'], 'sending')
                    self.assertIn(QUESTION, row['group_text' if phase == 'group' else 'escalation_text'])
                    with connect(self.home / 'cash-ledger' / 'review-cases.db') as c:
                        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                        self.assertIn('delivery_attempts', tables, 'commit audit before network')
                        attempt = c.execute('SELECT payload_json FROM delivery_attempts WHERE phase=?', (phase,)).fetchone()
                        self.assertEqual(__import__('json').loads(attempt[0]), payload)
                    raise SystemExit('synthetic process interruption')
                sender = self.sender(post=crash)
                with self.assertRaises(SystemExit):
                    sender(QUESTION) if phase == 'group' else sender.process_due()
                if phase == 'group':
                    with self.assertRaises(RuntimeError):
                        self.sender()(QUESTION)
                self.assertEqual(self.sender().process_due(), 0)
                self.assertEqual(len(self.posts), 0 if phase == 'group' else 1)

    def test_independent_entrypoint_scans_observations_before_sending_due(self):
        from cash_review_escalation_monitor import run_escalations
        self.sender()(QUESTION)
        self.observations()
        self.now += 21600
        # Disabled does not consume replies or alter case/financial state.
        before = (self.home / 'cash-ledger' / 'review-cases.db').read_bytes()
        self.assertEqual(run_escalations(self.home, post=self.post, clock=lambda: self.now), 0)
        self.assertEqual((self.home / 'cash-ledger' / 'review-cases.db').read_bytes(), before)
        self.assertEqual(run_escalations(self.home, enabled=True, post=self.post, clock=lambda: self.now), 1)
        self.assertEqual(run_escalations(self.home, enabled=True, post=self.post, clock=lambda: self.now), 0)
        self.assertEqual(len(self.posts), 2)

    def test_native_dm_reply_to_verified_reminder_is_recorded(self):
        sender = self.sender()
        sender(QUESTION)
        self.now += 21600
        sender.process_due()
        self.observations()
        self.now += 1
        self.add_observation(chat=ELENA, reply='102', text='Это сумма клиента 300.', timestamp=self.now)
        self.assertEqual(sender.scan_replies(self.home / 'state.db'), 1)
        self.assertEqual(self.case()['reply_status'], 'responded')
        self.assertEqual(sender.process_due(), 0)
        self.assertEqual(len(self.posts), 2)

    def test_failed_private_attempt_is_uncertain_audited_and_not_retried(self):
        for failure in ['timeout', 'owner', 'other_chat', 'text', 'id', 'date']:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as t:
                self.home = Path(t)
                self.posts = []
                self.now = NOW
                self.sender()(QUESTION)
                self.now += 21600
                calls = []
                def post(payload):
                    calls.append(payload)
                    self.assertEqual(self.case()['escalation_state'], 'sending')
                    if failure == 'timeout':
                        raise TimeoutError('synthetic timeout, not a Telegram delivery')
                    result = self.post(payload)
                    changes = {'owner': {'chat': {'id': int(OWNER)}}, 'other_chat': {'chat': {'id': int(GROUP)}},
                               'text': {'text': 'wrong'}, 'id': {'message_id': None}, 'date': {'date': None}}
                    result.update(changes[failure])
                    return result
                with self.assertRaises(RuntimeError):
                    self.sender(post=post).process_due()
                self.assertEqual(self.case()['escalation_state'], 'uncertain')
                self.assertEqual(self.sender().process_due(), 0)
                self.assertEqual(len(calls), 1)
                with connect(self.home / 'cash-ledger' / 'review-cases.db') as c:
                    audit = c.execute("SELECT payload_json,response_json,error_type FROM delivery_attempts WHERE phase='escalation'").fetchone()
                    self.assertIsNotNone(audit[0])
                    self.assertEqual(audit[2], 'TimeoutError' if failure == 'timeout' else 'RuntimeError')
                    self.assertEqual(audit[1] is None, failure == 'timeout')

    def test_entrypoint_records_reply_before_due_claim_and_missing_observations_fail_closed(self):
        from cash_review_escalation_monitor import run_escalations
        self.sender()(QUESTION)
        self.now += 21600
        with self.assertRaises(sqlite3.OperationalError):
            run_escalations(self.home, enabled=True, post=self.post, clock=lambda: self.now)
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.case()['escalation_state'], 'none')
        self.observations()
        self.add_observation(text='https://t.me/c/8000000002/101\nЭто деньги клиента.', reply=None)
        self.assertEqual(run_escalations(self.home, enabled=True, post=self.post, clock=lambda: self.now), 0)
        self.assertEqual(self.case()['reply_status'], 'responded')
        self.assertEqual(len(self.posts), 1)

    def test_initialized_empty_cases_are_write_free_noop_even_without_source_database(self):
        from cash_review_escalation_monitor import run_escalations
        sender = self.sender()
        before = sender.path.read_bytes()
        self.assertEqual(run_escalations(self.home, enabled=True, post=self.post, clock=lambda: self.now), 0)
        self.assertEqual(sender.path.read_bytes(), before)
        self.assertEqual(self.posts, [])

    def test_successful_telegram_entities_can_include_real_user_profile_fields(self):
        def post(payload):
            result = self.post(payload)
            result['entities'][0]['user'] = {'id': int(ELENA), 'is_bot': False, 'first_name': 'Elena', 'username': 'FixtureUser'}
            return result
        self.sender(post=post)(QUESTION)
        self.assertEqual(self.case()['group_state'], 'sent')

    def test_real_cash_monitor_integration_keeps_bookkeeping_reply_in_source_chat(self):
        from cash_ledger_monitor import Ledger, run_monitor
        from cash_reply_sender import ReplySender
        from cash_review_escalation_monitor import run_escalations
        self.observations()
        source_chat = '-1008000000001'
        with connect(self.home / 'state.db') as c:
            c.execute('INSERT INTO sessions VALUES(?,?,?,?)', ('bablomat', source_chat, 'telegram', ELENA))
            c.execute('INSERT INTO messages(session_id,role,active,content,timestamp,platform_message_id) VALUES(?,?,?,?,?,?)',
                      ('bablomat', 'user', 1, 'Касса Fixture\n05.10\nClient Hr/500\nСтранная запись 300\nTotal: 800', NOW, '77'))
        def post(payload):
            result = self.post(payload)
            if 'reply_parameters' in payload:
                result['reply_to_message'] = {'message_id': payload['reply_parameters']['message_id']}
            return result
        ledger = Ledger(self.home / 'cash-ledger' / 'ledger.db')
        args = dict(source_db=self.home / 'state.db', ledger=ledger,
                    state_path=self.home / 'cash-ledger' / 'monitor-state.json',
                    stats_path=self.home / 'cash-ledger' / 'daily-stats.json', chat_id=source_chat,
                    reply_sender=ReplySender(self.home, source_chat, post=post), review_sender=self.sender())
        run_monitor(**args)
        run_monitor(**args)
        self.assertEqual(len(self.posts), 2)
        self.assertEqual(self.posts[0]['chat_id'], GROUP)
        self.assertIn('https://t.me/c/8000000001/77', self.case()['question'])
        self.assertIn('Странная запись 300', self.case()['question'])
        self.assertEqual(self.posts[1]['chat_id'], source_chat)
        self.assertEqual(self.posts[1]['reply_parameters'], {'message_id': 77, 'allow_sending_without_reply': False})
        paths = [ledger.path, args['state_path'], args['stats_path'], self.home / 'cash-ledger' / 'reply-deliveries.db']
        before = {p: p.read_bytes() for p in paths}
        self.now += 21600
        self.assertEqual(run_escalations(self.home, enabled=True, post=self.post, clock=lambda: self.now), 1)
        self.assertEqual({p: p.read_bytes() for p in paths}, before)
        self.assertEqual(self.posts[2]['chat_id'], ELENA)

    def test_question_without_source_does_not_get_invented_bablomat_link(self):
        question = 'Касса Fixture — уточни сумму. Источник не указан.'
        sender = self.sender()
        sender(question)
        self.now += 21600
        sender.process_due()
        self.assertEqual(self.case()['question'], question)
        self.assertIn(question, self.posts[1]['text'])
        self.assertNotIn('t.me/c/8000000001/', self.posts[1]['text'])
        self.assertIn('t.me/c/8000000002/101', self.posts[1]['text'])

    def test_due_claim_blocks_a_second_processor_during_transport(self):
        self.sender()(QUESTION)
        self.now += 21600
        def post(payload):
            self.assertEqual(self.sender().process_due(), 0)
            return self.post(payload)
        self.assertEqual(self.sender(post=post).process_due(), 1)
        self.assertEqual(len(self.posts), 2)

    def test_group_question_mentions_elena_preserves_source_and_deduplicates(self):
        sender = self.sender()
        sender(QUESTION)
        self.sender()(QUESTION)
        self.assertEqual(len(self.posts), 1)
        p = self.posts[0]
        self.assertEqual(p['chat_id'], GROUP)
        self.assertIs(p['disable_notification'], False)
        self.assertNotIn('reply_parameters', p)
        self.assertIn(QUESTION, p['text'])
        greeting = p['text'].split(',')[0]
        self.assertIn(greeting, NAMES)
        self.assertEqual(p['entities'], [{'type': 'text_mention', 'offset': 0,
                         'length': len(greeting.encode('utf-16-le')) // 2,
                         'user': {'id': int(ELENA)}}])
        row = self.case()
        self.assertEqual(row['question'], QUESTION)
        self.assertEqual(row['group_text'], p['text'])
        self.assertEqual(row['group_message_id'], 101)
        self.assertEqual(row['group_state'], 'sent')


if __name__ == '__main__':
    unittest.main()
