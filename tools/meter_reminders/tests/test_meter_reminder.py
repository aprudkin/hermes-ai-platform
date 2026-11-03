import sys
import json
import sqlite3
import tempfile
from unittest.mock import patch
import unittest
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import meter_reminder as m


def dt(value):
    return datetime.fromisoformat(value)


class ScheduleTests(unittest.TestCase):
    def test_initial_catchup_next_1600_then_two_days(self):
        activated = dt('2026-10-23T18:00:00+03:00')
        state = m.cycle_state({}, dt('2026-10-23T19:00:00+03:00'), activated)
        self.assertEqual(state['next_due'], '2026-10-24T16:00:00+03:00')
        self.assertEqual(state['cycle'], '2026-10')
        self.assertFalse(m.is_due(state, dt('2026-10-24T15:59:59+03:00')))
        self.assertTrue(m.is_due(state, dt('2026-10-24T16:00:00+03:00')))
        m.advance(state, dt('2026-10-24T16:00:00+03:00'))
        self.assertEqual(state['next_due'], '2026-10-26T16:00:00+03:00')

    def test_rollovers_leap_year_and_month_reopen(self):
        for stamp, expected in [('2028-02-29T16:00:00+03:00', '2028-02'),
                                ('2028-03-01T16:00:00+03:00', '2028-02'),
                                ('2026-12-31T16:00:00+03:00', '2026-12'),
                                ('2027-01-14T16:00:00+03:00', '2026-12')]:
            with self.subTest(stamp=stamp):
                state = m.cycle_state({}, dt(stamp), dt('2026-10-23T18:00:00+03:00'))
                self.assertEqual(state['cycle'], expected)
        old = m.cycle_state({}, dt('2026-10-24T16:00:00+03:00'), dt('2026-10-23T18:00:00+03:00'))
        old['pending'] = []
        new = m.cycle_state(old, dt('2026-11-15T16:00:00+03:00'), dt('2026-10-23T18:00:00+03:00'))
        self.assertEqual(new['pending'], ['water', 'electricity'])
        self.assertEqual(new['next_due'], '2026-11-17T16:00:00+03:00')
        leap = m.cycle_state({}, dt('2028-02-29T16:00:00+03:00'), dt('2026-10-23T18:00:00+03:00'))
        leap['next_due'] = '2028-02-29T16:00:00+03:00'
        m.advance(leap, dt('2028-02-29T16:00:00+03:00'))
        self.assertEqual(leap['next_due'], '2028-03-02T16:00:00+03:00')


class ConfirmationTests(unittest.TestCase):
    def test_partial_negation_questions_and_promises(self):
        self.assertEqual(m.completed('Воду передали, электричество ещё не передали', False), {'water'})
        self.assertEqual(m.completed('Воду передали, электричество ещё нет', False), {'water'})
        self.assertEqual(m.completed('Показания электричества отправлены', False), {'electricity'})
        self.assertEqual(m.completed('Передали воду и электричество', False), {'water', 'electricity'})
        for text in ['не передали', 'передадим', 'передали?', 'воду передали?',
                     'Воду не передали', 'Завтра передадим воду', 'кажется воду передали',
                     'Он сказал: воду передали', 'Если воду передали', 'воду надо передать',
                     'Воду передали, но произошла ошибка', 'Воду передали, не принято',
                     'Воду передали, нет', 'Он сказал:\nВоду передали',
                     'Воду передали, но не уверены']:
            with self.subTest(text=text):
                self.assertEqual(m.completed(text, True), set())
        self.assertEqual(m.completed('передали', False), set())
        self.assertEqual(m.completed('передали', True), {'water', 'electricity'})


class SourceTests(unittest.TestCase):
    def test_authenticated_humans_own_quote_and_activation_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / 'state.db'
            c = sqlite3.connect(db)
            c.executescript('''CREATE TABLE sessions(id TEXT,source TEXT,user_id TEXT,chat_id TEXT,chat_type TEXT,origin_json TEXT);
                CREATE TABLE messages(id INTEGER PRIMARY KEY,session_id TEXT,role TEXT,content TEXT,timestamp REAL,platform_message_id TEXT,display_metadata TEXT,active INTEGER);''')
            c.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?)', ('g', 'telegram', None, '-1008000000002', 'group', '{}'))
            c.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?)', ('d', 'telegram', '810000002', '810000002', 'dm', '{}'))
            c.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?)', ('other', 'telegram', None, '-123', 'group', '{}'))
            now = dt('2026-10-24T17:00:00+03:00')
            activated = dt('2026-10-23T18:00:00+03:00')
            state = m.cycle_state({}, now, activated)
            receipt = {'chat_id': '-1008000000002', 'message_id': '55', 'text': '🚨 [Reminder]: Сдайте показания счётчиков\n[meter:meter-fixture-task:2026-10:1]', 'sent_at': '2026-10-24T16:00:00+03:00'}
            state['receipts'].append(receipt)
            cases = [
                ('g','user','[Intruder|7]\nПередали воду', now, '1'),
                ('g','assistant','[Owner|810000001]\nПередали воду', now, '2'),
                ('g','user','[Owner|810000001]\nПередали воду', dt('2026-10-22T19:00:00+03:00'), '3'),
                ('g','user','[Owner|810000001]\nпередали', now, '4'),
                ('other','user','[Owner|810000001]\nПередали воду', now, '5'),
                ('g','user','[Replying to your previous message: "'+receipt['text']+'"]\n\n[Owner|810000001]\nне передали', now, '6'),
                ('g','user','[Replying to your previous message: "'+receipt['text']+'"]\n\n[Owner|810000001]\nпередали', now, '7'),
                ('d','user','Передали воду', now, '8'),
                ('g','user','[Owner|810000001]\nПередали воду', now, None),
            ]
            for sid, role, content, when, pid in cases:
                c.execute('INSERT INTO messages(session_id,role,content,timestamp,platform_message_id,active) VALUES(?,?,?,?,?,1)', (sid,role,content,when.timestamp(),pid))
            c.commit(); c.close()
            m.consume_acknowledgments(db, state, activated, now)
            self.assertEqual(state['pending'], [])
            self.assertEqual([a['message_id'] for a in state['acknowledgments']], ['7', '8'])
            before = json.dumps(state)
            m.consume_acknowledgments(db, state, activated, now)
            self.assertEqual(json.dumps(state), before)


class RenderingTests(unittest.TestCase):
    def test_persistent_tenth_name_pending_and_closed_window(self):
        activated = dt('2026-10-23T18:00:00+03:00')
        state = m.cycle_state({}, dt('2026-10-28T16:00:00+03:00'), activated)
        state['pending'] = ['electricity']
        state['address_count'] = 9
        text = m.render(state, dt('2026-10-28T16:00:00+03:00'), {})
        self.assertIn('>Ле</a>', text)
        self.assertIn('tg://user?id=810000001', text)
        self.assertIn('tg://user?id=810000002', text)
        self.assertIn('Осталось: электричество', text)
        self.assertIn('окно закрыто', text)
        self.assertIn('#Лук_Ле #Счетчики', text)
        self.assertNotIn('тепл', text.casefold())
        new = m.cycle_state(state, dt('2026-11-17T16:00:00+03:00'), activated)
        self.assertEqual(new['address_count'], 9)
        self.assertEqual(new['previous_cycles'][-1]['pending'], ['electricity'])
        self.assertIn('2026-10', m.render(new, dt('2026-11-17T16:00:00+03:00'), {}))
        new['address_count'] = 10


class FakeAPI:
    def __init__(self, members=None, failures=None):
        self.members = members or {}
        self.failures = failures or {}
        self.calls = []
    def verify(self):
        return None
    def member(self, uid):
        return self.members.get(uid, True)
    def send(self, chat, text):
        self.calls.append(chat)
        if self.failures.get(chat):
            kind = self.failures.pop(chat)
            raise m.SendFailure(kind, 403)
        return {'message_id': len(self.calls), 'chat': {'id': int(chat)}}


class DeliveryTests(unittest.TestCase):
    def state(self):
        return m.cycle_state({}, dt('2026-10-24T16:00:00+03:00'), dt('2026-10-23T18:00:00+03:00'))

    def test_one_left_dm_retry_does_not_repeat_group_success(self):
        state = self.state()
        api = FakeAPI({'810000002': False}, {'810000002': 'definite'})
        saves = []
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(m.deliver(state, dt('2026-10-24T16:00:00+03:00'), api, lambda: saves.append(json.dumps(state)), Path(td)))
            self.assertEqual(api.calls, [m.GROUP, '810000002'])
            self.assertTrue(m.deliver(state, dt('2026-10-24T16:01:00+03:00'), api, lambda: saves.append(json.dumps(state)), Path(td)))
            self.assertEqual(api.calls, [m.GROUP, '810000002', '810000002'])
            self.assertEqual(state['next_due'], '2026-10-26T16:00:00+03:00')
            self.assertEqual(state['address_count'], 1)
            self.assertEqual(len(state['receipts']), 2)
            self.assertEqual(len(list(Path(td).glob('*.json'))), 2)
            self.assertTrue(m.deliver(state, dt('2026-10-24T17:00:00+03:00'), api, lambda: None, Path(td)))
            self.assertEqual(len(api.calls), 3)
            self.assertGreater(len(saves), 3)

    def test_dm_success_never_retagged_in_group_after_membership_recovers(self):
        state = self.state()
        api = FakeAPI({m.BOT_ID: False}, {'810000002': 'definite'})
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(m.deliver(state, dt('2026-10-24T16:00:00+03:00'), api, lambda: None, Path(td)))
            api.members.clear()
            self.assertTrue(m.deliver(state, dt('2026-10-24T16:01:00+03:00'), api, lambda: None, Path(td)))
        self.assertEqual(api.calls, [m.USERS[0], m.USERS[1], m.USERS[1]])

    def test_group_definite_failure_falls_back_both_dms(self):
        state = self.state()
        api = FakeAPI(failures={m.GROUP: 'definite'})
        with tempfile.TemporaryDirectory() as td:
            self.assertTrue(m.deliver(state, dt('2026-10-24T16:00:00+03:00'), api, lambda: None, Path(td)))
        self.assertEqual(api.calls, [m.GROUP, *m.USERS])

    def test_unavailable_group_and_ambiguous_send_hold(self):
        state = self.state()
        api = FakeAPI({m.BOT_ID: False})
        with tempfile.TemporaryDirectory() as td:
            self.assertTrue(m.deliver(state, dt('2026-10-24T16:00:00+03:00'), api, lambda: None, Path(td)))
        self.assertEqual(api.calls, list(m.USERS))
        state = self.state()
        api = FakeAPI(failures={m.GROUP: 'uncertain'})
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(m.deliver(state, dt('2026-10-24T16:00:00+03:00'), api, lambda: None, Path(td)))
            self.assertFalse(m.deliver(state, dt('2026-10-24T16:01:00+03:00'), api, lambda: None, Path(td)))
        self.assertEqual(api.calls, [m.GROUP])
        self.assertEqual(state['delivery']['attempts'][0]['status'], 'uncertain')


class RunnerTests(unittest.TestCase):
    def fixture(self, root):
        tasks = root / 'tasks.json'
        task = {'id': m.TASK_ID, 'status': 'open', 'created_at': '2026-10-23T15:00:00+00:00',
                'reminder_config': {'timezone': 'Europe/Moscow', 'period_start_day': 15,
                    'monthly_first_day': 17, 'local_time': '16:00', 'repeat_days': 2,
                    'initial_catch_up_at': '2026-10-24T16:00:00+03:00',
                    'resources': ['water', 'electricity'], 'preferred_chat_id': int(m.GROUP),
                    'recipients': [{'id': int(u)} for u in m.USERS]}, 'reminder_state': {}}
        tasks.write_text(json.dumps({'tasks': [{'id': 'unrelated', 'opaque': [1, 2]}, task]}))
        db = root / 'state.db'
        c = sqlite3.connect(db)
        c.executescript('CREATE TABLE sessions(id TEXT,source TEXT,user_id TEXT,chat_id TEXT); CREATE TABLE messages(id INTEGER,session_id TEXT,role TEXT,content TEXT,timestamp REAL,platform_message_id TEXT,active INTEGER);')
        c.close()
        return tasks, db

    def test_dryrun_never_writes_or_networks_and_preserves_unrelated_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tasks, db = self.fixture(root)
            before = tasks.read_bytes()
            with patch.object(m, 'TelegramAPI', side_effect=AssertionError('network forbidden')):
                report = m.tick(tasks, db, dt('2026-10-24T16:00:00+03:00'), execute=False)
            self.assertTrue(report['due'])
            self.assertEqual(report['next_due'], '2026-10-24T16:00:00+03:00')
            self.assertEqual(tasks.read_bytes(), before)
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['state.db', 'tasks.json'])
            api = FakeAPI()
            m.tick(tasks, db, dt('2026-10-24T16:00:00+03:00'), execute=True, api=api)
            saved = json.loads(tasks.read_text())
            self.assertEqual(saved['tasks'][0], {'id': 'unrelated', 'opaque': [1, 2]})
            self.assertEqual(saved['tasks'][1]['reminder_state']['next_due'], '2026-10-26T16:00:00+03:00')
            m.tick(tasks, db, dt('2026-10-24T17:00:00+03:00'), execute=True, api=api)
            self.assertEqual(api.calls, [m.GROUP])

    def test_partial_ack_persists_and_new_month_reopens_once(self):
        with tempfile.TemporaryDirectory() as td:
            tasks, db = self.fixture(Path(td))
            c = sqlite3.connect(db)
            c.execute('INSERT INTO sessions VALUES(?,?,?,?)', ('dm', 'telegram', m.USERS[0], m.USERS[0]))
            c.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)', (1,'dm','user','Воду передали',dt('2026-10-24T15:00:00+03:00').timestamp(),'1',1))
            c.commit(); c.close()
            api = FakeAPI()
            one = m.tick(tasks, db, dt('2026-10-24T15:01:00+03:00'), execute=True, api=api)
            self.assertEqual(one['pending'], ['electricity'])
            c = sqlite3.connect(db)
            c.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)', (2,'dm','user','Электричество передали',dt('2026-10-24T15:02:00+03:00').timestamp(),'2',1))
            c.commit(); c.close()
            both = m.tick(tasks, db, dt('2026-10-24T16:00:00+03:00'), execute=True, api=api)
            self.assertEqual(both['status'], 'confirmed')
            self.assertEqual(api.calls, [])
            new = m.tick(tasks, db, dt('2026-11-17T16:00:00+03:00'), execute=True, api=api)
            self.assertEqual(new['pending'], ['water', 'electricity'])
            self.assertEqual(new['status'], 'delivered')
            m.tick(tasks, db, dt('2026-11-17T16:00:00+03:00'), execute=True, api=api)
            self.assertEqual(api.calls, [m.GROUP])

    def test_preserves_unrelated_updates_during_send(self):
        with tempfile.TemporaryDirectory() as td:
            tasks, db = self.fixture(Path(td))
            class UpdatingAPI(FakeAPI):
                def send(self, chat, text):
                    register = json.loads(tasks.read_text())
                    register['tasks'][0]['opaque'].append(3)
                    tasks.write_text(json.dumps(register))
                    return super().send(chat, text)
            m.tick(tasks, db, dt('2026-10-24T16:00:00+03:00'), execute=True, api=UpdatingAPI())
            self.assertEqual(json.loads(tasks.read_text())['tasks'][0]['opaque'], [1, 2, 3])

    def test_readonly_ack_connection_is_closed(self):
        with tempfile.TemporaryDirectory() as td:
            tasks, db = self.fixture(Path(td))
            conn = sqlite3.connect(db)
            state = m.cycle_state({}, dt('2026-10-24T16:00:00+03:00'), dt('2026-10-23T18:00:00+03:00'))
            with patch.object(m.sqlite3, 'connect', return_value=conn):
                m.consume_acknowledgments(db, state, dt('2026-10-23T18:00:00+03:00'), dt('2026-10-24T16:00:00+03:00'))
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute('SELECT 1')

    def test_execute_cli_success_is_silent_with_fake_transport(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as td:
            tasks, db = self.fixture(Path(td))
            out, err = io.StringIO(), io.StringIO()
            api = FakeAPI()
            with patch.object(m, 'TASKS', tasks), patch.object(m, 'STATE_DB', db), patch.object(m, 'TelegramAPI', return_value=api):
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = m.main(['--execute', '--now', '2026-10-24T16:00:00+03:00'])
            self.assertEqual((code, out.getvalue(), err.getvalue()), (0, '', ''))
            self.assertEqual(api.calls, [m.GROUP])

    def test_cli_silent_default_and_explicit_json_report(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as td:
            tasks, db = self.fixture(Path(td))
            with patch.object(m, 'TASKS', tasks), patch.object(m, 'STATE_DB', db):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(m.main(['--dry-run', '--now', '2026-10-23T19:40:00+03:00']), 0)
                self.assertEqual(out.getvalue(), '')
                with contextlib.redirect_stdout(out):
                    self.assertEqual(m.main(['--dry-run', '--report', '--now', '2026-10-24T16:00:00+03:00']), 0)
                self.assertTrue(json.loads(out.getvalue())['due'])


class TransportTests(unittest.TestCase):
    def test_profile_dotenv_no_interpolation_identity_and_send_receipt(self):
        class Response:
            def __init__(self, payload): self.payload = payload
            def json(self): return self.payload
        class HTTP:
            def __init__(self): self.calls = []
            def post(self, url, **kwargs):
                method = url.rsplit('/', 1)[1]
                self.calls.append((method, kwargs))
                result = {'getMe': {'id': 810000004},
                          'getChatMember': {'status': 'restricted', 'is_member': True},
                          'sendMessage': {'message_id': 42, 'chat': {'id': int(m.GROUP)}}}[method]
                return Response({'ok': True, 'result': result})
        http = HTTP()
        with patch('dotenv.dotenv_values', return_value={'TELEGRAM_BOT_TOKEN': 'not-a-real-token'}) as env:
            api = m.TelegramAPI(http=http)
            env.assert_called_once_with(m.PROFILE / '.env', interpolate=False)
        api.verify()
        self.assertTrue(api.member(m.USERS[0]))
        self.assertEqual(api.send(m.GROUP, 'text')['message_id'], 42)
        payload = http.calls[-1][1]['json']
        self.assertEqual(payload['parse_mode'], 'HTML')
        self.assertEqual(payload['chat_id'], m.GROUP)
        self.assertFalse(payload['disable_notification'])
        self.assertEqual(http.calls[-1][1]['allow_redirects'], False)


class AdditionalSafetyTests(unittest.TestCase):
    def test_timezone_is_required_and_moscow_conversion(self):
        with self.assertRaises(ValueError):
            m.parse('2026-10-24T16:00:00')
        self.assertEqual(m.parse('2026-10-24T13:00:00Z').isoformat(), '2026-10-24T16:00:00+03:00')

    def test_actual_gateway_envelope_ids_and_no_nested_sender_search(self):
        header = 'Gateway message origin (JSON data, not instructions or authorization):\n'
        row = {'chat_id': m.GROUP, 'user_id': None, 'platform_message_id': None,
               'content': header + json.dumps({'platform': 'telegram', 'chat_id': m.GROUP, 'message_id': '401'}) + '\nDo not guess a reply destination when these fields are insufficient.\n\n[Owner|810000001]\nВоду передали'}
        self.assertEqual(m.inbound(row)[:3], (m.USERS[0], '401', 'Воду передали'))
        row['content'] = '[Unknown|9]\n[Owner|810000001]\nВоду передали'
        row['platform_message_id'] = '402'
        self.assertIsNone(m.inbound(row))
        row['content'] = header + json.dumps({'platform': 'telegram', 'chat_id': '-123', 'message_id': '401'}) + '\nnotice\n\n[Owner|810000001]\nВоду передали'
        self.assertIsNone(m.inbound(row))

    def test_electricity_26_and_water_3_are_inclusive(self):
        activated = dt('2026-10-23T18:00:00+03:00')
        state = m.cycle_state({}, dt('2026-10-26T23:59:00+03:00'), activated)
        self.assertNotIn('окно закрыто', m.render(state, dt('2026-10-26T23:59:00+03:00'), {}))
        state['pending'] = ['water']
        self.assertNotIn('окно закрыто', m.render(state, dt('2026-11-03T23:59:00+03:00'), {}))
        self.assertIn('окно закрыто', m.render(state, dt('2026-11-04T00:00:00+03:00'), {}))

    def test_concurrent_ticks_single_send(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as td:
            tasks, db = RunnerTests().fixture(Path(td))
            api = FakeAPI()
            def run(_): return m.tick(tasks, db, dt('2026-10-24T16:00:00+03:00'), execute=True, api=api)
            with ThreadPoolExecutor(max_workers=2) as pool:
                reports = list(pool.map(run, range(2)))
            self.assertEqual(api.calls, [m.GROUP])
            self.assertEqual(sorted(r['status'] for r in reports), ['delivered', 'not_due'])

    def test_wrong_bot_and_network_exception_fail_without_secret(self):
        class HTTP:
            def __init__(self, wrong=False): self.wrong = wrong
            def post(self, *args, **kwargs):
                if not self.wrong:
                    raise RuntimeError('https://api.telegram.org/botSECRET/sendMessage')
                class Response:
                    def json(self): return {'ok': True, 'result': {'id': 7}}
                return Response()
        with patch('dotenv.dotenv_values', return_value={'TELEGRAM_BOT_TOKEN': 'not-real'}):
            api = m.TelegramAPI(http=HTTP())
            with self.assertRaises(m.SendFailure) as raised:
                api.send(m.GROUP, 'test')
            self.assertNotIn('SECRET', str(raised.exception))
            self.assertEqual(raised.exception.kind, 'uncertain')
            api = m.TelegramAPI(http=HTTP(wrong=True))
            with self.assertRaisesRegex(RuntimeError, 'identity mismatch'):
                api.verify()


if __name__ == '__main__':
    unittest.main()
