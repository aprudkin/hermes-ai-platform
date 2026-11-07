import importlib.util
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/cycle_reminder_runner.py'

def load():
    spec = importlib.util.spec_from_file_location('cycle_runner', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.r = load()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.json'
        self.s = self.r.engine.new_state('2030-01-01', '2030-01-05', [26, 59], '1001')
        self.s.update(stage='active', delivery_enabled=True, planned_destination='telegram:-1001001',
                      forecast_policy={'mode':'temporary_fixed','days':28,'tolerance':1})
        self.s['runner'] = {'schema':1, 'activated_at':'2030-01-25T09:00:00+03:00',
                            'cursor':100, 'activation_cursor':100, 'expected_bot_id':'2001',
                            'receipts':[], 'outbox':None, 'pending':[]}
        self.path.write_text(json.dumps(self.s))
        self.now = datetime.fromisoformat('2030-01-28T10:02:00+03:00')

    def test_linked_short_answers_match_promised_phrases(self):
        today = self.now.date()
        self.assertEqual(self.r.normalize('ещё нет', 'start', True, today), ('not_started', None))
        self.assertEqual(self.r.normalize('начались', 'start', True, today), ('start', '2030-01-28'))
        self.assertEqual(self.r.normalize('начались вчера', 'start', True, today), ('start', '2030-01-27'))
        self.assertEqual(self.r.normalize('закончились вчера', 'end', True, today), ('end', '2030-01-27'))
        self.assertIsNone(self.r.normalize('начались вчера', 'start', False, today))

    def test_private_dm_is_outside_group_only_activation(self):
        self.consume(self.row('месячные начались сегодня', chat='1001'))
        self.assertEqual(len(self.s['cycles']), 1)
        self.assertEqual(self.s['events'], [])

    def test_sql_does_not_load_private_dm_rows(self):
        import sqlite3
        db = self.setup_db()
        from contextlib import closing
        with closing(sqlite3.connect(db)) as c, c:
            c.execute('INSERT INTO sessions VALUES(?,?,?,?)', ('dm','telegram','1001','1001'))
            c.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?,?)', (102,'dm','user','месячные начались сегодня','102',self.now.timestamp(),1,0))
        self.assertEqual(self.r.read_rows(db, self.s, self.now), [])

    def test_due_only_ten_oclock_window(self):
        self.assertIsNotNone(self.r.plan(self.s, self.now))
        for hour in (0, 3, 9, 11, 23):
            self.assertIsNone(self.r.plan(self.s, self.now.replace(hour=hour)))

    def test_dry_run_has_no_network_or_writes(self):
        before = self.path.read_bytes()
        entries = sorted(Path(self.tmp.name).iterdir())
        with patch('socket.socket', side_effect=AssertionError('network')), patch.object(self.r.engine, 'save_state', side_effect=AssertionError('write')):
            self.r.run(self.path, Path(self.tmp.name)/'missing.db', self.now, execute=False)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(sorted(Path(self.tmp.name).iterdir()), entries)

    def row(self, text, actor='1001', ident=101, quote='', stamp=None, chat='-1001001'):
        content = (f'[Replying to: "{quote}"]\n\n' if quote else '') + f'[Fixture|{actor}]\n' + text
        return {'id':ident, 'content':content, 'platform_message_id':str(ident),
                'timestamp':stamp or self.now.timestamp(), 'chat_id':chat, 'user_id':None}

    def receipt(self, kind='start'):
        text = 'Участник, месячные уже начались?\n\n#Участник #Цикл\n[cycle:2030-01-01:start:2030-01-28]'
        self.s['runner']['receipts'].append({'chat_id':'-1001001','message_id':44,
                'text':text,'kind':kind,'cycle':'2030-01-01', 'sent_at':self.now.replace(minute=0).isoformat()})
        self.s['question'] = {'kind':kind,'streak':2,'paused':False,'next_due':'2030-01-29'}
        return text

    def consume(self, row):
        return self.r.consume_rows(self.s, [row], self.now)

    def test_explicit_start_and_deduplication(self):
        row = self.row('месячные начались вчера')
        self.consume(row)
        self.consume(row)
        self.assertEqual(self.s['cycles'][-1], {'start':'2030-01-27','end':None})
        self.assertEqual(len(self.s['events']), 1)
        self.assertEqual(self.s['runner']['cursor'], 101)

    def test_wrong_actor_and_body_id_not_authorization(self):
        self.consume(self.row('месячные начались сегодня 1001', actor='111'))
        self.assertEqual(len(self.s['cycles']), 1)

    def test_unsupported_and_ambiguous_are_pending_without_fact(self):
        for i, text in enumerate(('да','месячные начались','кажется месячные начались сегодня','месячные не начались сегодня','месячные начались сегодня?','она сказала месячные начались сегодня')):
            self.consume(self.row(text, ident=101+i))
        self.assertEqual(len(self.s['cycles']), 1)
        self.assertTrue(self.s['runner']['pending'])

    def test_bare_negative_requires_exact_latest_quote(self):
        text = self.receipt()
        self.consume(self.row('нет', quote='wrong'))
        self.assertEqual(self.s['question']['streak'], 2)
        self.consume(self.row('нет', ident=102, quote=text))
        self.assertEqual(self.s['question']['streak'], 0)
        self.assertEqual(self.s['question']['next_due'], '2030-01-29')

    def test_marker_in_body_not_reply_linkage(self):
        text = self.receipt()
        self.consume(self.row('нет\n' + text))
        self.assertEqual(self.s['question']['streak'], 2)

    def test_end_no_requires_clarification_not_guessed_date(self):
        self.s['cycles'].append({'start':'2030-01-22','end':None})
        text = self.receipt('end')
        self.s['runner']['receipts'][-1]['cycle'] = '2030-01-22'
        self.consume(self.row('нет', quote=text))
        self.assertIsNone(self.s['cycles'][-1]['end'])
        self.assertEqual(self.s['runner']['clarification']['kind'], 'end_date')

    def test_stale_future_and_startup_rows_ignored(self):
        self.receipt()
        for row in (self.row('месячные начались сегодня', ident=99),
                    self.row('месячные начались сегодня', stamp=self.now.timestamp()+10),
                    self.row('месячные начались сегодня', ident=102, stamp=self.now.timestamp()-300)):
            self.consume(row)
        self.assertEqual(len(self.s['cycles']), 1)

    def test_explicit_date_backdate_future_and_invalid(self):
        self.consume(self.row('месячные начались 26.01'))
        self.assertEqual(self.s['cycles'][-1]['start'], '2030-01-26')
        self.consume(self.row('месячные закончились 31.02', ident=102))
        self.consume(self.row('месячные закончились 30.01', ident=103))
        self.assertIsNone(self.s['cycles'][-1]['end'])

    def test_paused_explicit_answer_resumes(self):
        text = self.receipt()
        self.s['question']['paused'] = True
        self.consume(self.row('нет', quote=text))
        self.assertFalse(self.s['question']['paused'])

    def test_pause_requires_cycle_context(self):
        self.consume(self.row('стоп'))
        self.assertFalse(self.s['runner'].get('paused', False))
        self.consume(self.row('приостанови напоминания о цикле', ident=102))
        self.assertTrue(self.s['runner']['paused'])
        self.consume(self.row('возобнови напоминания о цикле', ident=103))
        self.assertFalse(self.s['runner']['paused'])

    def setup_db(self, rows=()):
        import sqlite3
        db = Path(self.tmp.name) / 'state.db'
        from contextlib import closing
        with closing(sqlite3.connect(db)) as c, c:
            c.executescript('CREATE TABLE sessions(id TEXT, source TEXT, chat_id TEXT, user_id TEXT); CREATE TABLE messages(id INTEGER, session_id TEXT, role TEXT, content TEXT, platform_message_id TEXT, timestamp REAL, active INTEGER, observed INTEGER);')
            c.execute('INSERT INTO sessions VALUES(?,?,?,?)', ('g','telegram','-1001001',None))
            for row in rows:
                c.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?,?)',(row['id'],'g','user',row['content'],row['platform_message_id'],row['timestamp'],1,row.get('observed',0)))
        return db

    def fake_api(self, mode='ok'):
        test = self
        class FakeAPI:
            calls = 0
            checks = 0
            def verify(self, state):
                self.checks += 1
            def send_photo(self, chat_id, caption, photo, reply_to=None, reply_markup=None):
                self.calls += 1
                stored = json.loads(test.path.read_text())
                test.assertEqual(stored['runner']['outbox']['status'], 'inflight')
                if mode == 'timeout':
                    raise TimeoutError('secret token URL must never leak')
                if mode == '403':
                    raise test.r.SendFailure('rejected',403)
                result = {'message_id':501, 'date':int(test.now.timestamp()),
                          'chat':{'id':int(chat_id),'type':'supergroup'},
                          'from':{'id':2001,'is_bot':True},
                          'caption':test.r.plain(caption), 'photo':[{'file_id':'private-photo','width':100,'height':100}],
                          'has_protected_content':True,
                          'caption_entities':[{'type':'text_mention','offset':0,'length':8,'user':{'id':1001}}]}
                if reply_markup is not None and mode != 'missing_keyboard':
                    result['reply_markup'] = json.loads(json.dumps(reply_markup))
                if mode == 'bad':
                    result['chat']['id'] = -100999
                return result
        return FakeAPI()

    def execute(self, api=None, rows=(), now=None):
        self.path.write_text(json.dumps(self.s))
        db = self.setup_db(rows)
        def render(state, forecast, today, output):
            from PIL import Image
            Image.new('RGB',(20,20)).save(output)
        result = self.r.run(self.path, db, now or self.now, execute=True, api=api or self.fake_api(), renderer=render)
        self.s = json.loads(self.path.read_text())
        return result

    def test_confirmed_photo_receipt_and_no_duplicate(self):
        api = self.fake_api()
        self.execute(api)
        self.assertEqual(api.calls, 1)
        self.assertEqual(len(self.s['sent']), 1)
        self.assertEqual(self.s['question']['streak'], 1)
        receipt = self.s['runner']['receipts'][-1]
        self.assertEqual(receipt['message_id'], 501)
        self.assertEqual(receipt['verification_basis'], 'sendPhoto_returned_Message')
        self.assertTrue(receipt['text'].endswith(receipt['marker']))
        self.assertEqual(self.s['runner']['outbox']['status'], 'confirmed')
        self.r.run(self.path, Path(self.tmp.name)/'state.db', self.now, execute=True, api=api)
        self.assertEqual(api.calls, 1)

    def test_buttons_persisted_before_preflight_and_verified_in_receipt(self):
        api = self.fake_api()
        def verify(state):
            stored = json.loads(self.path.read_text())['runner']['outbox']
            self.assertEqual(stored['status'], 'prepared')
            self.assertIn('buttons', stored)
            self.assertIn('reply_markup', stored)
            self.assertIn(stored['buttons']['nonce'], stored['reply_markup']['inline_keyboard'][0][0]['callback_data'])
        api.verify = verify
        self.execute(api)
        outbox = self.s['runner']['outbox']
        receipt = self.s['runner']['receipts'][-1]
        self.assertEqual(receipt['buttons'], outbox['buttons'])
        self.assertEqual(receipt['reply_markup'], outbox['reply_markup'])
        self.assertEqual(receipt['reply_markup'], receipt['returned_message']['reply_markup'])

    def test_missing_keyboard_is_uncertain_not_fake_receipt(self):
        self.execute(self.fake_api('missing_keyboard'))
        self.assertEqual(self.s['runner']['outbox']['status'], 'uncertain')
        self.assertEqual(self.s['runner']['receipts'], [])

    def test_modified_keyboard_is_uncertain(self):
        api = self.fake_api()
        send = api.send_photo
        def altered(*args):
            msg = send(*args)
            if 'reply_markup' in msg:
                msg['reply_markup']['inline_keyboard'][0][0]['callback_data'] += 'x'
            return msg
        api.send_photo = altered
        self.execute(api)
        self.assertEqual(self.s['runner']['outbox']['status'], 'uncertain')

    def test_transport_json_encoded_inline_keyboard(self):
        import httpx
        env = Path(self.tmp.name)/'test.env'
        env.write_text('TELEGRAM_BOT_TOKEN=123:synthetic_test_only\n')
        photo = Path(self.tmp.name)/'photo.png'
        photo.write_bytes(b'fixture')
        markup = {'inline_keyboard':[[{'text':'Сегодня','callback_data':'ct1:test:today'}]]}
        calls = []
        def handler(request):
            calls.append(request.read())
            self.assertIn(b'name="reply_markup"', calls[-1])
            self.assertIn(json.dumps(markup,ensure_ascii=False).encode(), calls[-1])
            return httpx.Response(200,json={'ok':True,'result':{}})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            self.r.TelegramAPI(env,client=client).send_photo('-1001001','caption',photo,reply_markup=markup)
        self.assertEqual(len(calls),1)

    def test_sent_photo_buttons_callback_commits(self):
        self.execute()
        receipt = self.s['runner']['receipts'][-1]
        data = receipt['returned_message']['reply_markup']['inline_keyboard'][0][0]['callback_data']
        result = self.r.buttons.handle_button(self.path,actor_id=1001,chat_id=-1001001,
                    message_id=501,data=data,callback_id='integration-1',now=self.now,
                    message_author_id=2001,bot_id=2001)
        self.assertTrue(result['accepted'])
        self.assertEqual(json.loads(self.path.read_text())['cycles'][-1]['start'],'2030-01-28')

    def button_click(self, action='today', callback_id='integration-1'):
        receipt = self.s['runner']['receipts'][-1]
        data = receipt['reply_markup']['inline_keyboard'][0][0]['callback_data'].rsplit(':',1)[0] + ':' + action
        result = self.r.buttons.handle_button(self.path,actor_id=1001,chat_id=-1001001,
                    message_id=501,data=data,callback_id=callback_id,now=self.now,
                    message_author_id=2001,bot_id=2001)
        self.s = json.loads(self.path.read_text())
        return result

    def test_other_date_allows_text_reply_to_same_photo(self):
        self.execute()
        receipt = self.s['runner']['receipts'][-1]
        self.assertTrue(self.button_click('other')['accepted'])
        self.now += __import__('datetime').timedelta(seconds=1)
        self.consume(self.row('26.01',quote=receipt['text']))
        self.assertEqual(self.s['cycles'][-1]['start'],'2030-01-26')

    def test_text_negative_then_button_cannot_replace_first_answer(self):
        self.execute()
        text = self.s['runner']['receipts'][-1]['text']
        self.now += __import__('datetime').timedelta(seconds=1)
        self.consume(self.row('нет',quote=text))
        self.path.write_text(json.dumps(self.s))
        self.assertFalse(self.button_click()['accepted'])
        self.assertEqual(len(self.s['cycles']),1)

    def test_button_negative_then_linked_text_cannot_replace_first_answer(self):
        self.execute()
        text = self.s['runner']['receipts'][-1]['text']
        self.assertTrue(self.button_click('negative')['accepted'])
        self.now += __import__('datetime').timedelta(seconds=1)
        self.consume(self.row('сегодня',quote=text))
        self.assertEqual(len(self.s['cycles']),1)

    def test_clarify_end_buttons_accept_date_with_end_question(self):
        self.s['cycles'].append({'start':'2030-01-22','end':None})
        text = self.receipt('end')
        self.s['runner']['receipts'][-1]['cycle'] = '2030-01-22'
        self.consume(self.row('нет',quote=text))
        self.execute()
        self.assertEqual(self.s['runner']['receipts'][-1]['kind'],'end_date')
        self.assertTrue(self.button_click('yesterday')['accepted'])
        self.assertEqual(self.s['cycles'][-1]['end'],'2030-01-27')
        self.assertNotIn('clarification',self.s['runner'])

    def test_unknown_send_is_held_without_retry_or_counter(self):
        api = self.fake_api('timeout')
        self.execute(api)
        self.assertEqual(self.s['runner']['outbox']['status'], 'uncertain')
        self.assertEqual(len(self.s['sent']), 0)
        self.r.run(self.path, Path(self.tmp.name)/'state.db', self.now, execute=True, api=api)
        self.assertEqual(api.calls, 1)

    def test_definitive_failure_no_counter_and_nonretryable(self):
        self.execute(self.fake_api('403'))
        self.assertEqual(self.s['runner']['outbox']['status'], 'rejected')
        self.assertFalse(self.s['runner']['outbox']['retryable'])
        self.assertEqual(len(self.s['sent']), 0)

    def test_invalid_telegram_response_is_uncertain(self):
        self.execute(self.fake_api('bad'))
        self.assertEqual(self.s['runner']['outbox']['status'], 'uncertain')
        self.assertEqual(len(self.s['sent']), 0)

    def test_crash_inflight_is_uncertain_never_resent(self):
        self.s['runner']['outbox'] = {'status':'inflight','key':'unknown'}
        api = self.fake_api()
        self.execute(api)
        self.assertEqual(api.calls, 0)
        self.assertEqual(self.s['runner']['outbox']['status'], 'uncertain')

    def test_execution_disabled_is_no_write_no_network(self):
        self.s['stage'] = 'draft'
        self.s['delivery_enabled'] = False
        self.path.write_text(json.dumps(self.s))
        before = self.path.read_bytes()
        api = self.fake_api()
        self.r.run(self.path, Path(self.tmp.name)/'missing.db', self.now, execute=True, api=api)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(api.checks, 0)

    def test_nondue_consumes_both_observed_modes_without_network(self):
        api = self.fake_api()
        row = self.row('месячные начались вчера')
        row['observed'] = 1
        self.execute(api, [row], now=self.now.replace(hour=3)+__import__('datetime').timedelta(days=1))
        self.assertEqual(self.s['cycles'][-1]['start'], '2030-01-27')
        self.assertEqual(api.calls, 0)
        self.assertEqual(api.checks, 0)

    def test_schema_invalid_fails_closed(self):
        self.s['runner']['cursor'] = -1
        with self.assertRaises(ValueError):
            self.execute()

    def test_three_confirmed_questions_pause(self):
        self.s['question'] = {'kind':'start','streak':2,'paused':False,'next_due':'2030-01-28'}
        self.execute()
        self.assertTrue(self.s['question']['paused'])
        self.assertEqual(self.s['question']['streak'], 3)

    def test_send_response_clock_advances_during_request(self):
        message = {'message_id':1, 'date':int(self.now.timestamp())+3,
                   'chat':{'id':-1001001,'type':'supergroup'},
                   'from':{'id':2001,'is_bot':True}, 'caption':'text',
                   'photo':[{'file_id':'x','width':10,'height':10}], 'has_protected_content':True,
                   'caption_entities':[{'type':'text_mention','offset':0,'length':8,'user':{'id':1001}}]}
        self.r.validate_message(message,self.s,{'chat_id':'-1001001','text':'text'},self.now)

    def test_reply_to_clarification_accepts_explicit_relative_date(self):
        self.s['cycles'].append({'start':'2030-01-22','end':None})
        text = self.receipt('end_date')
        self.s['runner']['receipts'][-1]['cycle'] = '2030-01-22'
        self.s['question'].update(kind='end',paused=True)
        self.consume(self.row('вчера',quote=text))
        self.assertEqual(self.s['cycles'][-1]['end'], '2030-01-27')

    def test_duplicate_source_clarification_is_not_requeued(self):
        self.s['cycles'].append({'start':'2030-01-22','end':None})
        text = self.receipt('end')
        self.s['runner']['receipts'][-1]['cycle'] = '2030-01-22'
        self.consume(self.row('нет',quote=text))
        self.s['runner']['clarification']['sent'] = True
        row = self.row('нет',quote=text,ident=102)
        row['platform_message_id'] = '101'
        self.consume(row)
        self.assertTrue(self.s['runner']['clarification']['sent'])

    def test_pause_duplicate_source_cannot_override_later_resume(self):
        self.consume(self.row('приостанови напоминания о цикле'))
        self.consume(self.row('возобнови напоминания о цикле',ident=102))
        row = self.row('приостанови напоминания о цикле',ident=103)
        row['platform_message_id'] = '101'
        self.consume(row)
        self.assertFalse(self.s['runner']['paused'])

    def test_preflight_failure_is_persisted_safe_hold(self):
        api = self.fake_api()
        def reject(state):
            raise self.r.SendFailure('membership_unverified')
        api.verify = reject
        self.execute(api)
        self.assertEqual(api.calls,0)
        self.assertEqual(self.s['runner']['outbox']['status'],'rejected')

    def test_actual_renderer_integrates_without_state_mutation(self):
        self.path.write_text(json.dumps(self.s))
        db = self.setup_db()
        api = self.fake_api()
        before = list(self.s['cycles'])
        self.r.run(self.path,db,self.now,execute=True,api=api)
        self.s = json.loads(self.path.read_text())
        self.assertEqual(api.calls,1)
        self.assertEqual(self.s['cycles'],before)
        self.assertTrue((self.path.parent/'reminder-calendar.png').is_file())

    def test_response_requires_real_text_mention(self):
        api = self.fake_api()
        send = api.send_photo
        def without_mention(*args):
            message = send(*args)
            message.pop('caption_entities',None)
            return message
        api.send_photo = without_mention
        self.execute(api)
        self.assertEqual(self.s['runner']['outbox']['status'],'uncertain')

    def test_transport_fixed_origin_multipart_privacy_and_reply(self):
        import httpx
        calls = []
        def handler(request):
            calls.append(request)
            self.assertEqual(request.url.host,'api.telegram.org')
            self.assertEqual(request.url.scheme,'https')
            body = request.read()
            for value in (b'name="protect_content"\r\n\r\ntrue',b'name="disable_notification"\r\n\r\nfalse',b'name="allow_paid_broadcast"\r\n\r\nfalse',b'filename="calendar.png"',b'tg://user?id=1001', b'"allow_sending_without_reply": false'):
                self.assertIn(value,body)
            return httpx.Response(200,json={'ok':True,'result':{'message_id':1}})
        env = Path(self.tmp.name)/'test.env'
        env.write_text('TELEGRAM_BOT_TOKEN=123:synthetic_test_only\n')
        photo = Path(self.tmp.name)/'photo.png'
        photo.write_bytes(b'fixture')
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            api = self.r.TelegramAPI(env,client=client)
            caption,_ = self.r.caption_for(self.s,self.r.plan(self.s,self.now))
            api.send_photo('-1001001',caption,photo,44)
        self.assertEqual(len(calls),1)

    def test_transport_redirect_is_not_followed_and_error_is_redacted(self):
        import httpx
        env = Path(self.tmp.name)/'test.env'
        env.write_text('TELEGRAM_BOT_TOKEN=123:synthetic_test_only\n')
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(302,headers={'Location':'https://evil.example/'},text='secret')
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            api = self.r.TelegramAPI(env,client=client)
            with self.assertRaises(self.r.SendFailure) as caught:
                api._request('getMe',{})
            self.assertNotIn('synthetic',str(caught.exception))
        self.assertEqual(len(calls),1)

    def test_bare_date_requires_latest_question_quote(self):
        text = self.receipt()
        self.consume(self.row('26.01',quote=text))
        self.assertEqual(self.s['cycles'][-1]['start'],'2030-01-26')

    def test_explicit_fact_on_stale_quote_is_not_accepted(self):
        self.receipt()
        self.consume(self.row('месячные начались сегодня',quote='a previous cycle question'))
        self.assertEqual(len(self.s['cycles']),1)

    def test_repeated_no_after_clarification_does_not_repeat_question(self):
        self.s['cycles'].append({'start':'2030-01-22','end':None})
        text = self.receipt('end')
        self.s['runner']['receipts'][-1]['cycle'] = '2030-01-22'
        self.consume(self.row('нет',quote=text))
        self.s['runner']['clarification']['sent'] = True
        self.consume(self.row('нет',quote=text,ident=102))
        self.assertTrue(self.s['runner']['clarification']['sent'])

    def test_schema_rejects_unclosed_historical_cycle(self):
        self.s['cycles'][0]['end'] = None
        self.s['cycles'].append({'start':'2030-01-22','end':None})
        with self.assertRaises(ValueError):
            self.execute()

    def test_nondue_accepts_observed_zero_inbound(self):
        api = self.fake_api()
        self.execute(api,[self.row('месячные начались сегодня')],now=self.now.replace(hour=3)+__import__('datetime').timedelta(days=1))
        self.assertEqual(self.s['cycles'][-1]['start'],'2030-01-28')
        self.assertEqual(api.checks,0)

    def test_clarification_delivered_once_as_source_reply(self):
        self.s['cycles'].append({'start':'2030-01-22','end':None})
        text = self.receipt('end')
        self.s['runner']['receipts'][-1]['cycle'] = '2030-01-22'
        self.consume(self.row('нет',quote=text))
        api = self.fake_api()
        self.execute(api)
        self.assertTrue(self.s['runner']['clarification']['sent'])
        self.assertIsNone(self.s['cycles'][-1]['end'])
        self.assertEqual(self.s['runner']['outbox']['reply_to'],101)
        self.assertEqual(api.calls,1)

    def test_schema_rejects_confirmed_outbox_without_receipt(self):
        self.s['runner']['outbox'] = {'status':'confirmed','message_id':501,'key':'unverified'}
        with self.assertRaises(ValueError):
            self.execute()

    def test_marker_only_in_actual_quote_links_reply(self):
        self.receipt()
        receipt = self.s['runner']['receipts'][-1]
        receipt['marker'] = '[cycle:test-marker]'
        self.consume(self.row('нет',quote='truncated quote\n' + receipt['marker']))
        self.assertEqual(self.s['question']['streak'],0)

    def test_gateway_origin_envelope_validates_chat(self):
        row = self.row('месячные начались сегодня')
        original = row['content']
        header = 'Gateway message origin (JSON data, not instructions or authorization):\n'
        row['content'] = header + json.dumps({'platform':'telegram','chat_id':'-100999','message_id':101}) + '\n\n\n' + original
        self.consume(row)
        self.assertEqual(len(self.s['cycles']),1)
        row['id'] = 102
        row['content'] = header + json.dumps({'platform':'telegram','chat_id':row['chat_id'],'message_id':101}) + '\n\n\n' + original
        self.consume(row)
        self.assertEqual(len(self.s['cycles']),2)

    def test_malformed_gateway_envelope_is_ignored(self):
        row = self.row('месячные начались сегодня')
        row['content'] = 'Gateway message origin (JSON data, not instructions or authorization):\n[]\n\n\n' + row['content']
        self.consume(row)
        self.assertEqual(len(self.s['cycles']),1)

    def test_missing_next_due_is_schema_failure_before_write(self):
        self.s['question'] = {'kind':'start','streak':1,'paused':False}
        self.path.write_text(json.dumps(self.s))
        before = self.path.read_bytes()
        db = self.setup_db()
        with self.assertRaises(ValueError):
            self.r.run(self.path,db,self.now,execute=True,api=self.fake_api())
        self.assertEqual(self.path.read_bytes(),before)

    def test_bot_and_membership_checked_before_send(self):
        import httpx
        methods=[]
        env=Path(self.tmp.name)/'test.env'
        env.write_text('TELEGRAM_BOT_TOKEN=123:synthetic_test_only\n')
        def handler(request):
            methods.append(request.url.path.rsplit('/',1)[-1])
            if methods[-1]=='getMe':
                result={'id':2001,'is_bot':True}
            else:
                from urllib.parse import parse_qs
                uid=parse_qs(request.read().decode())['user_id'][0]
                result={'status':'member','user':{'id':int(uid)}}
            return httpx.Response(200,json={'ok':True,'result':result})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            self.r.TelegramAPI(env,client=client).verify(self.s)
        self.assertEqual(methods,['getMe','getChatMember','getChatMember'])

    def test_wrong_bot_is_rejected_with_no_other_api_calls(self):
        import httpx
        env=Path(self.tmp.name)/'test.env'
        env.write_text('TELEGRAM_BOT_TOKEN=123:synthetic_test_only\n')
        calls=[]
        def handler(request):
            calls.append(request)
            return httpx.Response(200,json={'ok':True,'result':{'id':999,'is_bot':True}})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(self.r.SendFailure):
                self.r.TelegramAPI(env,client=client).verify(self.s)
        self.assertEqual(len(calls),1)

    def test_cli_errors_do_not_leak_exception_urls(self):
        import io
        from contextlib import redirect_stderr
        out=io.StringIO()
        with patch.object(self.r,'run',side_effect=RuntimeError('https://api.telegram.org/botSECRET/sendPhoto')),redirect_stderr(out):
            code=self.r.main(['--dry-run','--state',str(self.path)])
        self.assertEqual(code,2)
        self.assertNotIn('SECRET',out.getvalue())
        self.assertNotIn('https:',out.getvalue())

    def test_group_without_trusted_prefix_and_other_dm_rejected(self):
        for ident,chat in ((101,'-1001001'),(102,'111')):
            row=self.row('месячные начались сегодня',ident=ident,chat=chat)
            row.update(content='месячные начались сегодня',user_id='1001')
            self.consume(row)
        self.assertEqual(len(self.s['cycles']),1)

    def test_ambiguous_new_year_date_is_pending_not_guessed_previous_year(self):
        self.consume(self.row('месячные начались 31.12'))
        self.assertEqual(len(self.s['cycles']),1)
        self.assertTrue(self.s['runner']['pending'])

    def test_real_cli_execute_nondue_three_am_is_silent_offline(self):
        import io
        from contextlib import redirect_stdout, redirect_stderr
        now = self.now.replace(hour=3)
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):
                return now.astimezone(tz) if tz else now
        self.path.write_text(json.dumps(self.s))
        before = self.path.read_bytes()
        db = self.setup_db()
        out,err=io.StringIO(),io.StringIO()
        with patch.object(self.r,'datetime',Clock),patch('socket.socket',side_effect=AssertionError('NO NETWORK')),redirect_stdout(out),redirect_stderr(err):
            code = self.r.main(['--execute','--state',str(self.path),'--db',str(db),'--env-file',str(Path(self.tmp.name)/'unused.env')])
        self.assertEqual(code,0)
        self.assertEqual(out.getvalue(),'')
        self.assertEqual(err.getvalue(),'')
        self.assertEqual(self.path.read_bytes(),before)

    def test_transport_definitive_4xx_classification(self):
        import httpx
        env=Path(self.tmp.name)/'test.env'
        env.write_text('TELEGRAM_BOT_TOKEN=123:synthetic_test_only\n')
        with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(403,json={'ok':False,'error_code':403,'description':'forbidden tokenless fixture'}))) as client:
            api=self.r.TelegramAPI(env,client=client)
            with self.assertRaises(self.r.SendFailure) as caught:
                api._request('sendPhoto',{})
        self.assertEqual(caught.exception.kind,'rejected')
        self.assertEqual(caught.exception.code,403)
        self.assertNotIn('description',str(caught.exception))

    def test_yes_to_end_date_clarification_is_not_ongoing_fact(self):
        self.s['cycles'].append({'start':'2030-01-22','end':None})
        text=self.receipt('end_date')
        self.s['runner']['receipts'][-1]['cycle']='2030-01-22'
        self.s['question'].update(kind='end',paused=True)
        self.consume(self.row('да',quote=text))
        self.assertTrue(self.s['question']['paused'])
        self.assertEqual(self.s['events'],[])

    def test_invalid_photo_shape_does_not_confirm_delivery(self):
        api=self.fake_api()
        send=api.send_photo
        def invalid_photo(*args):
            msg=send(*args)
            msg['photo'][0]['width']=-1
            return msg
        api.send_photo=invalid_photo
        self.execute(api)
        self.assertEqual(self.s['runner']['outbox']['status'],'uncertain')
        self.assertEqual(self.s['sent'],[])

if __name__ == '__main__':
    unittest.main()
