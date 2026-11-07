"""Offline-only synthetic callback tests; never touches live tracker state."""
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

HOME = Path(__file__).resolve().parents[1]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

class ButtonTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((HOME/'scripts/cycle_buttons.py').is_file(), 'buttons module missing')
        self.b = load('cycle_buttons_test', HOME/'scripts/cycle_buttons.py')

    def test_keyboard_payload_labels_and_opaque_size(self):
        event = {'kind':'start','day':'2030-01-28','cycle':'2030-01-01','key':'synthetic'}
        now = datetime.fromisoformat('2030-01-28T10:00:00+03:00')
        buttons = self.b.prepare_buttons(event, now)
        markup = self.b.reply_markup(buttons)
        flat = [b for row in markup['inline_keyboard'] for b in row]
        self.assertEqual([b['text'] for b in flat], ['Сегодня','Вчера','Ещё нет','Другая дата'])
        for button in flat:
            self.assertTrue(button['callback_data'].startswith('ct1:'))
            self.assertLessEqual(len(button['callback_data'].encode()), 64)
            self.assertNotIn('2030', button['callback_data'])
        self.assertNotEqual(buttons['nonce'], self.b.prepare_buttons(event, now)['nonce'])
        self.assertIsNone(self.b.prepare_buttons(dict(event,kind='heads_up'), now))
        self.assertIsNone(self.b.reply_markup(None))

    def fixture(self, kind='start'):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)/'state.json'
        self.now = datetime.fromisoformat('2030-01-28T10:02:00+03:00')
        engine = load('button_engine_fixture', HOME/'scripts/cycle_engine.py')
        s = engine.new_state('2030-01-01','2030-01-05',[26,59],'1001')
        s.update(stage='active',delivery_enabled=True,planned_destination='telegram:-1001001')
        if kind != 'start':
            s['cycles'].append({'start':'2030-01-22','end':None})
        event = {'kind':kind,'day':'2030-01-28','cycle':s['cycles'][-1]['start'],'key':'fixture:'+kind}
        buttons = self.b.prepare_buttons(event,self.now)
        buttons['question_last_asked'] = '2030-01-28'
        markup = self.b.reply_markup(buttons)
        message = {'message_id':501,'date':int(self.now.timestamp()),'chat':{'id':-1001001,'type':'supergroup'},
                   'from':{'id':2001,'is_bot':True},'reply_markup':markup}
        receipt = dict(event,chat_id='-1001001',message_id=501,sent_at=self.now.isoformat(),buttons=buttons,
                       reply_markup=markup,returned_message=message,verification_basis='sendPhoto_returned_Message')
        s['question'] = {'kind':'start' if kind=='start' else 'end','streak':2,'paused':False,
                         'next_due':'2030-01-29','last_asked':'2030-01-28'}
        s['runner'] = {'schema':1,'expected_bot_id':'2001','receipts':[receipt],
                       'outbox':dict(receipt,status='confirmed'),'pending':[],'paused':False}
        self.path.write_text(json.dumps(s))
        self.s = s
        self.data = markup['inline_keyboard'][0][0]['callback_data']
        return s

    def click(self, **changes):
        args = dict(actor_id=1001,chat_id=-1001001,message_id=501,data=self.data,
                    callback_id='query-1',now=self.now,message_author_id=2001,bot_id=2001)
        args.update(changes)
        with patch('socket.socket',side_effect=AssertionError('NO NETWORK')):
            return self.b.handle_button(self.path,**args)

    def read(self):
        return json.loads(self.path.read_text())

    def test_today_commits_real_source_without_simulation(self):
        self.fixture()
        self.assertTrue(hasattr(self.b,'handle_button'), 'callback API missing')
        result = self.click()
        self.assertTrue(result['accepted'])
        self.assertTrue(result['clear_keyboard'])
        s = self.read()
        self.assertEqual(s['cycles'][-1],{'start':'2030-01-28','end':None})
        self.assertEqual(s['events'][-1]['message_id'],'callback:query-1')
        self.assertEqual(s['stage'],'active')
        self.assertTrue(s['delivery_enabled'])
        self.assertIsNone(s['question'])

    def test_wrong_metadata_no_state_or_lock_write(self):
        self.fixture()
        before = self.path.read_bytes()
        for changes in ({'actor_id':111}, {'chat_id':-100999}, {'message_id':500},
                        {'message_author_id':111}, {'bot_id':111}, {'bot_id':None},
                        {'data':'ct1:1001:today'}, {'callback_id':''}, {'now':self.now.replace(tzinfo=None)}):
            with self.subTest(changes=changes):
                result = self.click(**changes)
                self.assertFalse(result['accepted'])
                self.assertFalse(result['clear_keyboard'])
                self.assertEqual(self.path.read_bytes(), before)
                if 'actor_id' in changes or 'chat_id' in changes:
                    self.assertFalse(Path(str(self.path)+'.lock').exists())

    def test_only_latest_current_cycle_and_day_receipt(self):
        for mutation in ('newer','cycle','day','expires','inactive','disabled','paused','unverified',
                         'wrong_question','question_changed','unconfirmed','markup','returned_author','old_receipt'):
            with self.subTest(mutation=mutation):
                s = self.fixture()
                r = s['runner']['receipts'][-1]
                if mutation == 'newer':
                    s['runner']['receipts'].append(dict(r,message_id=502))
                elif mutation == 'cycle':
                    r['cycle'] = '2029-12-01'
                elif mutation == 'day':
                    r['buttons']['day'] = '2030-01-27'
                elif mutation == 'expires':
                    r['buttons']['expires_at'] = self.now.isoformat()
                elif mutation == 'inactive':
                    s['stage'] = 'draft'
                elif mutation == 'disabled':
                    s['delivery_enabled'] = False
                elif mutation == 'paused':
                    s['runner']['paused'] = True
                elif mutation == 'unverified':
                    r['verification_basis'] = 'invented'
                elif mutation == 'wrong_question':
                    s['question']['kind'] = 'end'
                elif mutation == 'question_changed':
                    s['question']['last_asked'] = '2030-01-27'
                elif mutation == 'unconfirmed':
                    s['runner']['outbox']['status'] = 'uncertain'
                elif mutation == 'markup':
                    r['returned_message']['reply_markup'] = {}
                elif mutation == 'returned_author':
                    r['returned_message']['from']['id'] = 111
                elif mutation == 'old_receipt':
                    r.pop('buttons')
                self.path.write_text(json.dumps(s))
                before = self.path.read_bytes()
                self.assertFalse(self.click()['accepted'])
                self.assertEqual(self.path.read_bytes(),before)

    def test_first_answer_wins_across_callback_ids_and_restart(self):
        self.fixture()
        self.assertTrue(self.click()['accepted'])
        before = self.path.read_bytes()
        self.b = load('buttons_restart',HOME/'scripts/cycle_buttons.py')
        for ident in ('query-1','query-2'):
            self.assertFalse(self.click(callback_id=ident)['accepted'])
            self.assertEqual(self.path.read_bytes(),before)

    def test_old_day_buttons_expire_at_moscow_midnight(self):
        self.fixture()
        before = self.path.read_bytes()
        self.assertFalse(self.click(now=datetime.fromisoformat('2030-01-28T21:00:00+00:00'))['accepted'])
        self.assertEqual(self.path.read_bytes(),before)

    def choice(self, action):
        return self.data.rsplit(':',1)[0] + ':' + action

    def test_yesterday_uses_callback_moscow_date(self):
        self.fixture()
        result = self.click(data=self.choice('yesterday'),now=datetime.fromisoformat('2030-01-28T20:30:00+00:00'))
        self.assertTrue(result['accepted'])
        self.assertEqual(self.read()['cycles'][-1]['start'],'2030-01-27')

    def test_end_buttons_record_explicit_last_bleeding_day(self):
        for kind in ('end','end_date'):
            for action,value in (('today','2030-01-28'),('yesterday','2030-01-27')):
                with self.subTest(kind=kind,action=action):
                    self.fixture(kind)
                    self.assertTrue(self.click(data=self.choice(action))['accepted'])
                    self.assertEqual(self.read()['cycles'][-1]['end'],value)
                    self.assertIsNone(self.read()['question'])

    def test_negative_resets_silence_and_consumes_only_this_receipt(self):
        for kind,action in (('start','not_started'),('end','ongoing')):
            with self.subTest(kind=kind):
                self.fixture(kind)
                before_cycles = self.s['cycles']
                result = self.click(data=self.choice('negative'))
                self.assertTrue(result['accepted'])
                self.assertTrue(result['clear_keyboard'])
                s = self.read()
                self.assertEqual(s['cycles'],before_cycles)
                self.assertEqual(s['question']['streak'],0)
                self.assertFalse(s['question']['paused'])
                self.assertEqual(s['question']['next_due'],'2030-01-29')
                self.assertEqual(s['events'][-1]['action'],action)
                before = self.path.read_bytes()
                self.assertFalse(self.click(callback_id='query-2')['accepted'])
                self.assertEqual(self.path.read_bytes(),before)

    def test_other_date_keeps_same_prompt_and_keyboard_for_date_reply(self):
        self.fixture('end')
        result = self.click(data=self.choice('other'))
        self.assertTrue(result['accepted'])
        self.assertFalse(result['clear_keyboard'])
        self.assertEqual(result['text'],'Ответь на это сообщение датой ДД.ММ')
        s = self.read()
        self.assertIsNone(s['cycles'][-1]['end'])
        self.assertEqual(s['question']['streak'],0)
        self.assertEqual(s['question']['next_due'],'2030-01-29')
        self.assertEqual(s['events'][-1]['action'],'request_date')
        self.assertNotIn('button_answer',s['runner']['receipts'][-1])
        before = self.path.read_bytes()
        self.assertFalse(self.click(data=self.choice('other'))['accepted'])
        self.assertEqual(self.path.read_bytes(),before)
        self.assertTrue(self.click(callback_id='query-2')['accepted'])
        self.assertEqual(self.read()['cycles'][-1]['end'],'2030-01-28')

    def test_end_keyboard_explicit_labels_and_clarification_only_dates(self):
        self.fixture('end')
        labels = [item['text'] for row in self.s['runner']['receipts'][-1]['reply_markup']['inline_keyboard'] for item in row]
        self.assertEqual(labels,['Закончились сегодня','Закончились вчера','Ещё идут','Другая дата'])
        self.fixture('end_date')
        before = self.path.read_bytes()
        self.assertFalse(self.click(data=self.choice('negative'))['accepted'])
        self.assertEqual(self.path.read_bytes(),before)

    def test_invalid_choice_does_not_consume_receipt(self):
        self.fixture('end')
        s = self.read()
        s['cycles'][-1]['start'] = '2030-01-28'
        for target in (s['runner']['receipts'][-1],s['runner']['outbox']):
            target['cycle'] = '2030-01-28'
            target['buttons']['cycle'] = '2030-01-28'
        self.path.write_text(json.dumps(s))
        before = self.path.read_bytes()
        self.assertFalse(self.click(data=self.choice('yesterday'))['accepted'])
        self.assertEqual(self.path.read_bytes(),before)
        self.assertTrue(self.click(callback_id='query-2')['accepted'])

    def test_concurrent_clicks_have_exactly_one_committed_decision(self):
        from concurrent.futures import ThreadPoolExecutor
        self.fixture()
        def run(pair):
            ident,action = pair
            return self.b.handle_button(self.path,actor_id=1001,chat_id=-1001001,message_id=501,
                data=self.choice(action),callback_id=ident,now=self.now,message_author_id=2001,bot_id=2001)
        with patch('socket.socket',side_effect=AssertionError('NO NETWORK')),ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run,[('race-1','today'),('race-2','negative')]))
        self.assertEqual(sum(r['accepted'] for r in results),1)
        self.assertEqual(len(self.read()['events']),1)

    def test_malformed_callbacks_are_neutral_noops(self):
        self.fixture()
        before = self.path.read_bytes()
        for data in (None,{},'ct1:'+'a'*24+':today','ct1:'+'a'*80+':today',self.choice('delete'), '\ud800'):
            with self.subTest(data=repr(data)):
                result = self.click(data=data)
                self.assertFalse(result['accepted'])
                self.assertEqual(self.path.read_bytes(),before)

    def test_gateway_plugin_api_without_optional_metadata(self):
        self.fixture()
        with patch('socket.socket',side_effect=AssertionError('NO NETWORK')):
            result = self.b.handle_button(self.path,actor_id='1001',chat_id='-1001001',
                message_id=501,data=self.data,callback_id='plugin-1',now=self.now)
        self.assertTrue(result['accepted'])

if __name__ == '__main__':
    unittest.main()
