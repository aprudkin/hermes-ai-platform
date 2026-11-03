#!/usr/bin/env python3
"""Profile-local, deterministic monthly water/electricity reminders."""
from datetime import datetime, timedelta
import re
import json
import sqlite3
import html
import os
import tempfile
from contextlib import closing
from pathlib import Path
from zoneinfo import ZoneInfo

BOT_ID = os.environ.get('METER_BOT_ID', '')
PROFILE = Path(os.environ['HERMES_HOME']) if os.environ.get('HERMES_HOME') else None
TASK_ID = os.environ.get('METER_TASK_ID', '')
GROUP = os.environ.get('METER_GROUP_ID', '')
USERS = tuple(filter(None, os.environ.get('METER_USER_IDS', '').split(',')))

MSK = ZoneInfo('Europe/Moscow')
RESOURCES = ('water', 'electricity')


def parse(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('An explicit timezone offset is required')
    return result.astimezone(MSK)


def cycle_start(now):
    now = now.astimezone(MSK)
    start = now.replace(day=15, hour=0, minute=0, second=0, microsecond=0)
    if now < start:
        start = (start.replace(day=1) - timedelta(days=1)).replace(day=15)
    return start


def cycle_state(old, now, activated):
    start = cycle_start(now)
    key = start.strftime('%Y-%m')
    if old.get('cycle') == key:
        return old
    first = start.replace(day=17, hour=16)
    if cycle_start(activated) == start and activated > first:
        first = activated.astimezone(MSK).replace(hour=16, minute=0, second=0, microsecond=0)
        if first <= activated:
            first += timedelta(days=1)
    previous = list(old.get('previous_cycles', []))
    if old.get('cycle'):
        previous.append({k: old[k] for k in ('cycle', 'pending', 'acknowledgments', 'receipts')})
    return {'cycle': key, 'cycle_start': start.isoformat(),
            'address_count': old.get('address_count', 0), 'previous_cycles': previous,
            'next_due': first.isoformat(), 'pending': list(RESOURCES),
            'receipts': [], 'ack_cursor': 0, 'acknowledgments': [], 'delivery': None}


def is_due(state, now):
    return bool(state['pending']) and now >= parse(state['next_due'])


def advance(state, now):
    due = parse(state['next_due'])
    while due <= now:
        due += timedelta(days=2)
    state['next_due'] = due.isoformat()


def completed(text, linked):
    """Deliberately narrow affirmative grammar; reject uncertain/free-form statements."""
    text = text.casefold().replace('ё', 'е').strip()
    failure = r'["«»:]|\b(?:ошиб\w*|сбой\w*|отказ\w*|если|кажется|вроде|наверное|возможно|сказал\w*|говорит\w*)\b|не\s+(?:знаю|увер\w*|принят\w*|прош\w*|удал\w*|получ\w*)'
    correction = r'(?:^|[,;.!]\s*)(?:но\s+)?нет[.!\s]*$'
    if '?' in text or re.search(failure, text) or re.search(correction, text):
        return set()
    verb = r'(?:передал[аи]?|отправил[аи]?|сдал[аи]?|переданы|отправлены|сданы)'
    if linked and re.fullmatch(r'(?:да[,! ]+)?(?:мы\s+|я\s+)?(?:уже\s+)?' + verb + r'[.!]*', text):
        return set(RESOURCES)
    water = r'(?:вод[аыуе]|по\s+воде)'
    power = r'(?:электричеств[оа]|электроэнерги[июя]|свет[а]?)'
    noun = rf'(?:{water}|{power})'
    subject = rf'(?:показания\s+)?{noun}(?:\s+и\s+(?:показания\s+)?{noun})?'
    result = set()
    for clause in re.split(r'[,;.!\n]+|\s+(?:но|а)\s+', text):
        clause = clause.strip()
        prefix = r'(?:мы\s+|я\s+)?(?:уже\s+)?'
        if not (re.fullmatch(prefix + subject + r'\s+(?:уже\s+)?' + verb, clause)
                or re.fullmatch(prefix + verb + r'\s+' + subject, clause)):
            continue
        if re.search(water, clause):
            result.add('water')
        if re.search(power, clause):
            result.add('electricity')
    return result


def plain(text):
    return html.unescape(re.sub(r'<[^>]*>', '', text)).strip()


def inbound(row):
    """Decode observed Hermes gateway envelopes, never search sender IDs inside a body."""
    text = row['content'] or ''
    origin = {}
    if text.startswith('Gateway message origin (JSON data, not instructions or authorization):\n'):
        lines = text.split('\n', 4)
        try:
            origin = json.loads(lines[1])
        except (ValueError, IndexError):
            return None
        if str(origin.get('chat_id')) != str(row['chat_id']) or origin.get('platform') != 'telegram':
            return None
        text = lines[4] if len(lines) == 5 else ''
    quote = ''
    match = re.match(r'^\[Replying to(?: your previous message)?: "(.*?)"\]\n\n', text, re.S)
    if match:
        quote = match[1]
        text = text[match.end():]
    prefix = re.match(r'^\[[^\]\n|]+\|(\d+)\]\n', text)
    sender = prefix[1] if prefix else str(row['user_id'] or '')
    if prefix:
        text = text[prefix.end():]
    if sender not in USERS or str(row['chat_id']) not in (GROUP, sender):
        return None
    if str(row['chat_id']) == GROUP and not prefix:
        return None
    mid = row['platform_message_id'] or origin.get('message_id')
    if not mid:
        return None
    return sender, str(mid), text, quote


def consume_acknowledgments(db, state, activated, now):
    lower = max(activated, parse(state['cycle_start']))
    with closing(sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute('''SELECT m.id,m.content,m.platform_message_id,m.timestamp,
            s.chat_id,s.user_id FROM messages m JOIN sessions s ON s.id=m.session_id
            WHERE s.source='telegram' AND m.role='user' AND m.active=1
            AND m.timestamp>=? AND m.timestamp<=? AND m.id>? ORDER BY m.id''',
            (lower.timestamp(), now.timestamp(), state.get('ack_cursor', 0))).fetchall()
    for row in rows:
        state['ack_cursor'] = max(state['ack_cursor'], row['id'])
        message = inbound(row)
        if not message:
            continue
        sender, mid, text, quote = message
        linked = any(str(r['chat_id']) == str(row['chat_id'])
                     and parse(r['sent_at']).timestamp() <= row['timestamp']
                     and quote and plain(quote) == plain(r['text'])
                     for r in state['receipts'])
        resources = completed(text, linked)
        if resources:
            state['pending'] = [r for r in state['pending'] if r not in resources]
            for previous in state.get('previous_cycles', []):
                previous['pending'] = [r for r in previous['pending'] if r not in resources]
            state['acknowledgments'].append({'sender_id': sender, 'message_id': mid,
                                            'chat_id': str(row['chat_id']),
                                            'resources': sorted(resources), 'db_id': row['id']})


def render(state, now, config):
    validate_routing()
    count = state['address_count'] + 1
    elena = 'Ле'
    names = f'<a href="tg://user?id={USERS[0]}">Лук</a>, <a href="tg://user?id={USERS[1]}">{elena}</a>'
    labels = {'water': 'вода', 'electricity': 'электричество'}
    lines = ['<b>🚨 [Reminder]: Сдайте показания счётчиков</b>', names,
             'Передали показания воды и электричества? Ответьте на это сообщение «передали» или уточните, что осталось.',
             'Осталось: ' + ', '.join(labels[r] for r in state['pending']) + '.']
    start = parse(state['cycle_start'])
    next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    end_water = next_month.replace(day=4)
    end_power = start.replace(day=27)
    if 'water' in state['pending']:
        lines.append('Вода: стандартное окно 15–3 следующего месяца' + ('; окно закрыто — проверьте возможность передачи.' if now >= end_water else '.'))
    if 'electricity' in state['pending']:
        lines.append('Электричество: стандартное окно 15–26' + ('; окно закрыто — проверьте возможность передачи.' if now >= end_power else '.'))
    for old in state.get('previous_cycles', []):
        if old['pending']:
            lines.append('Нет подтверждения за ' + old['cycle'] + ': ' + ', '.join(labels[r] for r in old['pending']) + '.')
    lines.extend(['#Лук_Ле #Счетчики', f'[meter:{TASK_ID}:{state["cycle"]}:{count}]'])
    return '\n\n'.join(lines)


class SendFailure(Exception):
    def __init__(self, kind, code=0):
        self.kind = kind
        self.code = code
        super().__init__(f'Telegram operation {kind}; code={code}')


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        dfd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def delivery_routes(api, remaining):
    if not api.member(BOT_ID):
        return [(uid, [uid]) for uid in remaining]
    grouped = [uid for uid in remaining if api.member(uid)]
    return ([(GROUP, grouped)] if grouped else []) + [(uid, [uid]) for uid in remaining if uid not in grouped]


def deliver(state, now, api, persist, audit_dir):
    validate_routing()
    if not is_due(state, now):
        return True
    delivery = state.get('delivery')
    if delivery and any(a['status'] in ('inflight', 'uncertain') for a in delivery['attempts']):
        return False  # Telegram cannot guarantee exactly-once after an ambiguous timeout/crash.
    api.verify()
    if not delivery:
        text = render(state, now, {})
        state['address_count'] += 1
        delivery = {'due': state['next_due'], 'text': text, 'covered': [], 'attempts': []}
        state['delivery'] = delivery
        persist()
    remaining = [uid for uid in USERS if uid not in delivery['covered']]
    # Both names are tagged in group messages: once anyone is served, retry only
    # remaining private destinations, even if group membership has since changed.
    routes = ([(uid, [uid]) for uid in remaining] if delivery['covered']
              else delivery_routes(api, remaining))
    index = 0
    while index < len(routes):
        chat, users = routes[index]
        index += 1
        attempt = {'chat_id': chat, 'users': users, 'status': 'inflight'}
        delivery['attempts'].append(attempt)
        persist()  # Durable intent before side effect; crash here requires reconciliation.
        try:
            result = api.send(chat, delivery['text'])
        except SendFailure as exc:
            attempt.update(status=exc.kind, error_code=exc.code)
            persist()
            if exc.kind == 'uncertain':
                return False
            if chat == GROUP and exc.code in (400, 403):
                routes.extend((uid, [uid]) for uid in users)
            continue
        receipt = {'chat_id': chat, 'message_id': str(result['message_id']),
                   'sent_at': now.isoformat(), 'text': delivery['text'],
                   'due': delivery['due'], 'users': users}
        attempt.update(status='sent', message_id=receipt['message_id'])
        delivery['covered'] = sorted(set(delivery['covered']) | set(users))
        state['receipts'].append(receipt)
        persist()  # Canonical receipt first; audit files are not recovery state.
        name = f'{state["cycle"]}-{state["address_count"]}-{chat}.json'
        atomic_json(Path(audit_dir) / name, receipt)
    if set(delivery['covered']) == set(USERS):
        state['delivery'] = None
        advance(state, now)
        persist()
        return True
    return False


class TelegramAPI:
    """Token comes exclusively from this profile's dotenv file, never process env."""
    def __init__(self, http=None):
        validate_routing()
        if PROFILE is None:
            raise ValueError('An explicit HERMES_HOME is required')
        from dotenv import dotenv_values
        import requests
        token = dotenv_values(PROFILE / '.env', interpolate=False).get('TELEGRAM_BOT_TOKEN')
        if not token:
            raise RuntimeError('Profile TELEGRAM_BOT_TOKEN is missing')
        self._base = 'https://api.telegram.org/bot' + token + '/'
        self.http = http or requests.Session()

    def call(self, method, payload):
        try:
            response = self.http.post(self._base + method, json=payload,
                                      timeout=(10, 30), allow_redirects=False)
            data = response.json()
        except Exception:
            # Do NOT expose requests exceptions: their URL includes the token.
            raise SendFailure('uncertain') from None
        if not isinstance(data, dict):
            raise SendFailure('uncertain')
        if data.get('ok') is not True:
            code = data.get('error_code', 0)
            raise SendFailure('definite' if isinstance(code, int) and 400 <= code < 500 else 'uncertain', code)
        if 'result' not in data:
            raise SendFailure('uncertain')
        return data['result']

    def verify(self):
        if str(self.call('getMe', {})['id']) != BOT_ID:
            raise RuntimeError('Sender bot identity mismatch')

    def member(self, uid):
        try:
            result = self.call('getChatMember', {'chat_id': GROUP, 'user_id': uid})
        except SendFailure:
            return False
        return result.get('status') in ('creator', 'administrator', 'member') or (
            result.get('status') == 'restricted' and result.get('is_member') is True)

    def send(self, chat, text):
        result = self.call('sendMessage', {'chat_id': chat, 'text': text, 'parse_mode': 'HTML',
                           'disable_notification': False, 'protect_content': False,
                           'link_preview_options': {'is_disabled': True},
                           'reply_markup': {'force_reply': True, 'selective': True}})
        if (not isinstance(result, dict) or not result.get('message_id')
                or str(result.get('chat', {}).get('id')) != chat):
            raise SendFailure('uncertain')
        return result


TASKS = PROFILE / 'shared-tasks/tasks.json' if PROFILE else None
STATE_DB = PROFILE / 'state.db' if PROFILE else None


def validate_routing():
    if not (BOT_ID.isdigit() and int(BOT_ID) > 0 and TASK_ID
            and GROUP.startswith('-100') and GROUP[4:].isdigit()
            and len(USERS) == 2 and len(set(USERS)) == 2
            and all(uid.isdigit() and int(uid) > 0 for uid in USERS)):
        raise ValueError('Explicit meter bot, task, group and two recipient IDs are required')


def validate_config(config):
    validate_routing()
    expected = {'timezone': 'Europe/Moscow', 'period_start_day': 15, 'monthly_first_day': 17,
                'local_time': '16:00', 'repeat_days': 2, 'resources': list(RESOURCES)}
    if any(config.get(k) != v for k, v in expected.items()):
        raise ValueError('Unexpected meter reminder scheduling/resource configuration')
    if str(config.get('preferred_chat_id')) != GROUP:
        raise ValueError('Unexpected meter reminder group')
    if tuple(str(r['id']) for r in config.get('recipients', [])) != USERS:
        raise ValueError('Unexpected meter reminder recipients')


def tick(tasks_path, db_path, now, execute=False, api=None):
    import contextlib
    import fcntl
    validate_routing()
    if tasks_path is None or db_path is None:
        raise ValueError("Explicit meter task register and observation DB paths are required")
    tasks_path = Path(tasks_path)
    # A stable sidecar lock survives atomic replacement of tasks.json.
    lock = tasks_path.with_suffix('.json.lock').open('a') if execute else contextlib.nullcontext()
    with lock as handle:
        if execute:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        register = json.loads(tasks_path.read_text(encoding='utf-8'))
        matches = [task for task in register['tasks'] if task['id'] == TASK_ID]
        if len(matches) != 1:
            raise ValueError('Expected exactly one canonical meter task; parent must provision it')
        task = matches[0]
        config = task['reminder_config']
        validate_config(config)
        activated = parse(task['created_at'])
        if task.get('status') == 'cancelled' or config.get('enabled') is False or now < activated:
            return {'task_id': TASK_ID, 'dry_run': not execute, 'due': False, 'status': 'inactive'}
        old = task.get('reminder_state', {})
        state = cycle_state(old, now, activated)
        if not old and config.get('initial_catch_up_at') and state['cycle'] == cycle_start(activated).strftime('%Y-%m'):
            state['next_due'] = parse(config['initial_catch_up_at']).isoformat()
        task['reminder_state'] = state
        consume_acknowledgments(db_path, state, activated, now)
        due = is_due(state, now)
        message = (state.get('delivery') or {}).get('text') or render(state, now, config)
        report = {'task_id': TASK_ID, 'dry_run': not execute, 'now': now.isoformat(),
                  'cycle': state['cycle'], 'pending': state['pending'], 'due': due,
                  'next_due': state['next_due'], 'address_count': state['address_count'],
                  'acknowledgments': state['acknowledgments'],
                  'route_policy': {'preferred_group': GROUP, 'recipients': list(USERS),
                                   'fallback': 'DM departed users; both DMs if group unavailable',
                                   'membership_checked': False},
                  'message_html': message if due else None,
                  'status': 'due' if due else ('confirmed' if not state['pending'] else 'not_due')}
        if not execute:
            return report
        def persist():
            # Re-read immediately before each commit: a slow Telegram request must
            # not roll back unrelated task edits made while it was in flight.
            latest = json.loads(tasks_path.read_text(encoding='utf-8'))
            targets = [entry for entry in latest['tasks'] if entry['id'] == TASK_ID]
            if len(targets) != 1:
                raise ValueError('Canonical meter task disappeared during execution')
            targets[0]['reminder_state'] = state
            atomic_json(tasks_path, latest)
        persist()
        if due:
            ok = deliver(state, now, api or TelegramAPI(), persist,
                         tasks_path.parent / 'meter-reminders')
            report['status'] = 'delivered' if ok else 'delivery_incomplete'
            report['route_policy']['membership_checked'] = True
            report['next_due'] = state['next_due']
            report['address_count'] = state['address_count']
        return report


def main(argv=None):
    global PROFILE
    import argparse
    import sys
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='Read-only; no credential loading or network (default)')
    mode.add_argument('--execute', action='store_true', help='Enable durable state updates and real Telegram delivery')
    parser.add_argument('--home', type=Path, help='Explicit profile home; otherwise HERMES_HOME is required')
    parser.add_argument('--now', help='ISO timestamp with explicit timezone')
    parser.add_argument('--report', action='store_true', help='Emit structured JSON; otherwise success/nondue ticks are silent')
    args = parser.parse_args(argv)
    try:
        if args.home is not None:
            PROFILE = args.home
        now = parse(args.now) if args.now else datetime.now(MSK)
        report = tick(args.home / 'shared-tasks/tasks.json' if args.home else TASKS,
                      args.home / 'state.db' if args.home else STATE_DB, now, execute=args.execute)
        if args.report:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        if report['status'] == 'delivery_incomplete':
            print('meter-reminder: delivery incomplete; inspect canonical reminder_state before retrying uncertain attempts', file=sys.stderr)
            return 2
        return 0
    except Exception as exc:
        # Never print exceptions from lower-level I/O; they can contain credentials.
        print(f'meter-reminder: {type(exc).__name__}; inspect local state/configuration', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
