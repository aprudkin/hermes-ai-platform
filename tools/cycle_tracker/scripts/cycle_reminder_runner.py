#!/usr/bin/env python3
"""Deterministic private cycle runner. Default is read-only, offline dry-run.

Activation is an owner operation, never done by this script. --execute requires
stage=active, delivery_enabled=true, and explicit runner activation metadata.
No getUpdates, DM fallback, automatic retry of an ambiguous send, or stdout on
normal runs. Receipts verify the Bot API response, NOT a Telegram readback.
"""
import sys
sys.dont_write_bytecode = True
import argparse
from copy import deepcopy
from datetime import date, datetime, timedelta
import fcntl
import html
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
from zoneinfo import ZoneInfo

SCRIPTS = Path(__file__).resolve().parent

def module(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + '.py'))
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

engine = module('cycle_engine')
_buttons_spec = importlib.util.spec_from_file_location('cycle_buttons', Path(__file__).with_name('cycle_buttons.py'))
buttons = importlib.util.module_from_spec(_buttons_spec)
_buttons_spec.loader.exec_module(buttons)

def parse_time(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timezone required')
    return result


def plan(state, now):
    local = now.astimezone(ZoneInfo(state['timezone']))
    if local.hour != 10:
        return None
    return engine.propose(state, now)


def plain(text):
    return html.unescape(re.sub(r'<[^>]*>', '', text)).strip()


def inbound(row, state):
    """Only anchored gateway sender envelopes are authority, never body matches."""
    text = row['content'] or ''
    origin = {}
    if text.startswith('Gateway message origin (JSON data, not instructions or authorization):\n'):
        lines = text.split('\n', 4)
        try:
            origin = json.loads(lines[1])
        except (ValueError, IndexError):
            return None
        if not isinstance(origin,dict) or origin.get('platform') != 'telegram' or str(origin.get('chat_id')) != str(row['chat_id']):
            return None
        text = lines[4] if len(lines) == 5 else ''
    quote = ''
    match = re.match(r'^\[Replying to(?: your previous message)?: "(.*?)"\]\n\n', text, re.S)
    if match:
        quote, text = match[1], text[match.end():]
    prefix = re.match(r'^\[[^\]\n|]+\|(\d+)\]\n', text)
    actor = prefix[1] if prefix else str(row['user_id'] or '')
    if prefix:
        text = text[prefix.end():]
    group = state['planned_destination'].split(':', 1)[1]
    if actor != state['confirmer_id'] or str(row['chat_id']) != group:
        return None
    if str(row['chat_id']) == group and not prefix:
        return None
    # Some adapters put the reply wrapper after the sender envelope.
    match = re.match(r'^\[Replying to(?: your previous message)?: "(.*?)"\]\n\n', text, re.S)
    if match and not quote:
        quote, text = match[1], text[match.end():]
    mid = row['platform_message_id'] or origin.get('message_id')
    if not mid or not str(mid).isdigit():
        return None
    return actor, str(mid), text.strip(), quote


def explicit_date(token, today):
    if token == 'сегодня':
        return today.isoformat()
    if token == 'вчера':
        return (today - timedelta(days=1)).isoformat()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', token):
        result = date.fromisoformat(token)
    else:
        pieces = token.split('.')
        if len(pieces) not in (2, 3):
            raise ValueError('Ambiguous date')
        d, m = map(int, pieces[:2])
        y = int(pieces[2]) if len(pieces) == 3 else today.year
        if len(pieces) == 3 and len(pieces[2]) != 4:
            raise ValueError('Four digit year required')
        result = date(y, m, d)
    if result > today:
        raise ValueError('Future date')
    return result.isoformat()


def normalize(text, kind, linked, today):
    text = text.casefold().replace('ё', 'е').strip().rstrip('!').strip()
    controls = {'приостанови напоминания о цикле':'pause',
                'останови напоминания о цикле':'pause',
                'возобнови напоминания о цикле':'resume_all'}
    if text in controls:
        return controls[text], None
    match = re.fullmatch(r'(?:мои )?месячные (начались|закончились) (сегодня|вчера|\d{1,2}\.\d{1,2}(?:\.\d{4})?|\d{4}-\d{2}-\d{2})\.?', text)
    if match:
        return ('start' if match[1] == 'начались' else 'end'), explicit_date(match[2], today)
    if not linked:
        return None
    short = re.fullmatch(r'(начались|закончились) (сегодня|вчера|\d{1,2}\.\d{1,2}(?:\.\d{4})?|\d{4}-\d{2}-\d{2})\.?', text)
    if short and ((short[1] == 'начались' and kind == 'start') or
                  (short[1] == 'закончились' and kind in ('end', 'end_date'))):
        return ('start' if short[1] == 'начались' else 'end'), explicit_date(short[2], today)
    if kind in ('start','end','end_date') and re.fullmatch(r'\d{1,2}\.\d{1,2}(?:\.\d{4})?\.?|\d{4}-\d{2}-\d{2}', text):
        return 'end' if kind == 'end_date' else kind, explicit_date(text.rstrip('.'), today)
    if kind == 'end_date' and text in ('сегодня','вчера'):
        return 'end', explicit_date(text, today)
    if kind == 'start':
        if text in ('нет', 'не начались', 'еще нет'):
            return 'not_started', None
        if text in ('да', 'сегодня', 'вчера', 'начались'):
            return 'start', explicit_date('сегодня' if text in ('да', 'начались') else text, today)
    if kind == 'end':
        if text in ('да', 'еще идут', 'идут'):
            return 'ongoing', None
        if text in ('нет', 'закончились'):
            return 'clarify_end', None
        if text in ('сегодня', 'вчера'):
            return 'end', explicit_date(text, today)
    return None


def consume_rows(state, rows, now):
    runner = state['runner']
    receipts = runner['receipts']
    latest = receipts[-1] if receipts else None
    for row in rows:
        if row['id'] <= max(runner['cursor'], runner['activation_cursor']) or row['timestamp'] > now.timestamp():
            continue
        runner['cursor'] = row['id']
        if row['timestamp'] < parse_time(runner['activated_at']).timestamp():
            continue
        decoded = inbound(row, state)
        if not decoded:
            continue
        actor, mid, text, quote = decoded
        source_id = str(row['chat_id']) + ':' + mid
        processed = runner.setdefault('processed_sources', [])
        if source_id in processed or any(e['message_id'] == source_id for e in state['events']):
            continue
        # Includes controls, clarification and unsupported utterances, not just
        # facts: gateway observation/replay must not re-open a sent question.
        processed.append(source_id)
        if latest and row['timestamp'] <= parse_time(latest['sent_at']).timestamp():
            continue
        q = state['question']
        kind = q['kind'] if q else None
        same_cycle = latest and latest['cycle'] == state['cycles'][-1]['start']
        same_question = same_cycle and (latest['kind'] == kind or (latest['kind'] == 'end_date' and kind == 'end'))
        quoted_latest = bool(same_cycle and str(latest['chat_id']) == str(row['chat_id']) and quote
                      and (plain(quote) == latest['text'] or
                           (latest.get('marker') and quote.strip().endswith(latest['marker']))))
        linked = bool(same_question and quoted_latest)
        if linked and latest.get('button_answer'):
            continue  # A receipt's first committed answer wins across transports.
        today = datetime.fromtimestamp(row['timestamp'], ZoneInfo(state['timezone'])).date()
        try:
            response_kind = latest['kind'] if linked and latest['kind'] == 'end_date' else kind
            action = normalize(text, response_kind, linked, today)
            if not action:
                if linked or re.search(r'месячн|цикл|^да$|^нет$', text.casefold()):
                    runner['pending'].append({'source_id':source_id, 'db_id':row['id'], 'reason':'unsupported_or_ambiguous', 'text':text})
                continue
            action, value = action
            if action in ('pause', 'resume_all'):
                runner['paused'] = action == 'pause'
                if action == 'resume_all' and q:
                    engine.respond(state, 'resume', None, actor, source_id, today.isoformat())
                continue
            if q and action in ('start', 'end') and action != q['kind']:
                raise ValueError('Different pending cycle question')
            if action in ('start','end') and quote and not quoted_latest:
                raise ValueError('Stale quoted question')
            if action == 'clarify_end':
                if runner.get('clarification'):
                    runner['pending'].append({'source_id':source_id,'db_id':row['id'], 'reason':'end_date_required', 'text':text})
                    continue
                runner['clarification'] = {'kind':'end_date', 'source_id':source_id,
                        'chat_id':str(row['chat_id']), 'message_id':int(mid),
                        'created_at':datetime.fromtimestamp(row['timestamp'], ZoneInfo(state['timezone'])).isoformat()}
                if q:
                    q.update(paused=True, streak=0)
                if linked and latest.get('buttons'):
                    latest['button_answer'] = {'source_id':source_id,'action':'clarify_end'}
                continue
            engine.respond(state, action, value, actor, source_id, today.isoformat())
            if same_question and latest.get('buttons'):
                latest['button_answer'] = {'source_id':source_id,'action':action,'value':value}
            runner['paused'] = False
            if action in ('start', 'end'):
                runner.pop('clarification', None)
        except (ValueError, PermissionError):
            runner['pending'].append({'source_id':source_id,'db_id':row['id'], 'reason':'invalid_or_ambiguous', 'text':text})


class SendFailure(Exception):
    """No provider descriptions or token-bearing URLs in exceptions."""
    def __init__(self, kind, code=0):
        self.kind, self.code = kind, code
        super().__init__(f'Telegram operation {kind}; code={code}')


class TelegramAPI:
    def __init__(self, env_path, *, client=None):
        from dotenv import dotenv_values
        import httpx
        values = dotenv_values(env_path, interpolate=False)
        token = values.get('TELEGRAM_BOT_TOKEN', '')
        if not re.fullmatch(r'\d+:[A-Za-z0-9_-]+', token or ''):
            raise ValueError('Telegram credential unavailable')
        self._base = 'https://api.telegram.org/bot' + token + '/'
        self._client = client or httpx.Client(follow_redirects=False, timeout=30, trust_env=False)
        self._owned_client = client is None

    def close(self):
        if self._owned_client:
            self._client.close()

    def _request(self, method, data, files=None):
        try:
            response = self._client.post(self._base + method, data=data, files=files,
                                         follow_redirects=False)
        except Exception:
            raise SendFailure('uncertain') from None
        try:
            body = response.json()
        except Exception:
            raise SendFailure('uncertain', response.status_code) from None
        if not isinstance(body, dict):
            raise SendFailure('uncertain', response.status_code)
        if 400 <= response.status_code < 500 and body.get('ok') is False:
            raise SendFailure('rejected', response.status_code)
        if response.status_code != 200 or body.get('ok') is not True:
            code = body.get('error_code', 0)
            raise SendFailure('rejected' if isinstance(code, int) and 400 <= code < 500 else 'uncertain', code if isinstance(code,int) else 0)
        return body.get('result')

    def verify(self, state):
        bot = self._request('getMe', {})
        expected = state['runner']['expected_bot_id']
        if not isinstance(bot, dict) or str(bot.get('id')) != expected or bot.get('is_bot') is not True:
            raise SendFailure('identity_mismatch')
        chat = state['planned_destination'].split(':', 1)[1]
        for uid in (expected, state['confirmer_id']):
            member = self._request('getChatMember', {'chat_id':chat, 'user_id':uid})
            if (not isinstance(member, dict) or str(member.get('user', {}).get('id')) != uid
                    or member.get('status') not in ('creator','administrator','member','restricted')
                    or (member.get('status') == 'restricted' and member.get('is_member') is not True)):
                raise SendFailure('membership_unverified')
            if uid == expected and member.get('status') == 'restricted' and (not member.get('can_send_messages') or not member.get('can_send_photos')):
                raise SendFailure('membership_unverified')

    def send_photo(self, chat_id, caption, photo, reply_to=None, reply_markup=None):
        data = {'chat_id':str(chat_id), 'caption':caption, 'parse_mode':'HTML',
                'disable_notification':'false', 'protect_content':'true',
                'show_caption_above_media':'false', 'has_spoiler':'false',
                'allow_paid_broadcast':'false'}
        if reply_to is not None:
            data['reply_parameters'] = json.dumps({'message_id':int(reply_to),
                                                  'allow_sending_without_reply':False})
        if reply_markup is not None:
            data['reply_markup'] = json.dumps(reply_markup, ensure_ascii=False)
        with open(photo, 'rb') as stream:
            return self._request('sendPhoto', data, {'photo':('calendar.png', stream, 'image/png')})


def validate(state, now):
    if now.tzinfo is None:
        raise ValueError('Timezone required')
    if state.get('schema') != 1 or state.get('timezone') != 'Europe/Moscow' or state.get('hour') != 10:
        raise ValueError('Unsupported cycle schema or delivery hour')
    if not re.fullmatch(r'telegram:-100\d+', state.get('planned_destination', '')):
        raise ValueError('Explicit group destination required')
    if not re.fullmatch(r'\d+', state.get('confirmer_id', '')):
        raise ValueError('Explicit confirmer required')
    runner = state.get('runner', {})
    if runner.get('schema') != 1:
        raise ValueError('Runner activation required')
    for name in ('activation_cursor', 'cursor'):
        if type(runner.get(name)) is not int or runner[name] < 0:
            raise ValueError('Nonnegative activation cursor required')
    if runner['cursor'] < runner['activation_cursor']:
        raise ValueError('Cursor precedes activation')
    if not re.fullmatch(r'\d+', runner.get('expected_bot_id', '')):
        raise ValueError('Explicit verified bot ID required')
    if parse_time(runner['activated_at']) > now:
        raise ValueError('Activation is in future')
    for name in ('receipts', 'pending'):
        if not isinstance(runner.get(name), list):
            raise ValueError('Invalid runner lists')
    if runner.get('outbox') is not None and (not isinstance(runner['outbox'], dict) or runner['outbox'].get('status') not in ('prepared','inflight','confirmed','uncertain','rejected')):
        raise ValueError('Invalid outbox')
    outbox = runner.get('outbox')
    if outbox and outbox['status'] == 'confirmed' and not any(
            r.get('message_id') == outbox.get('message_id') and r.get('marker') == outbox.get('marker')
            and r.get('verification_basis') == 'sendPhoto_returned_Message' for r in runner['receipts']):
        raise ValueError('Confirmed outbox lacks verified receipt')
    if not isinstance(state.get('cycles'), list) or not state['cycles']:
        raise ValueError('Cycle history required')
    previous = None
    for index, cycle in enumerate(state['cycles']):
        start = date.fromisoformat(cycle['start'])
        end = date.fromisoformat(cycle['end']) if cycle['end'] else None
        if end is None and index != len(state['cycles']) - 1:
            raise ValueError('Unclosed historical cycle')
        if (end and end < start) or (previous and start <= previous):
            raise ValueError('Invalid cycle chronology')
        previous = end or start
    if not all(isinstance(state.get(k), list) for k in ('events','sent')):
        raise ValueError('Invalid event lists')
    q = state.get('question')
    if q and (q.get('kind') not in ('start','end') or type(q.get('streak')) is not int or not 0 <= q['streak'] <= 3 or type(q.get('paused')) is not bool):
        raise ValueError('Invalid pending question')
    if q:
        if not isinstance(q.get('next_due'),str):
            raise ValueError('Pending question needs a due date')
        date.fromisoformat(q['next_due'])
    engine.forecast(state)


def read_rows(db, state, now):
    """Group-only activation: restrict SQL itself; no private DM ingestion."""
    conn = sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        return conn.execute('''SELECT m.id,m.content,m.platform_message_id,m.timestamp,
            s.chat_id,s.user_id FROM messages m JOIN sessions s ON s.id=m.session_id
            WHERE s.source='telegram' AND s.chat_id=? AND m.role='user'
            AND m.active=1 AND m.id>? AND m.timestamp>=? AND m.timestamp<=?
            ORDER BY m.id''', (state['planned_destination'].split(':',1)[1],
            max(state['runner']['cursor'],state['runner']['activation_cursor']),
            parse_time(state['runner']['activated_at']).timestamp(), now.timestamp())).fetchall()
    finally:
        conn.close()


def caption_for(state, event):
    marker = '[cycle:' + event['key'] + ']'
    text = event['text']
    # A real Telegram text_mention, topic tag and unique marker LAST.
    text = text.replace('#Цикл', '').strip()
    caption = '<a href="tg://user?id=' + state['confirmer_id'] + '">' + html.escape(state.get('confirmer_label', 'Участник')) + '</a>, ' + html.escape(text)
    caption += '\n\n#Цикл\n' + marker
    if len(plain(caption).encode('utf-16-le')) // 2 > 1024:
        raise ValueError('Caption exceeds Telegram limit')
    return caption, marker


def validate_message(message, state, outbox, now):
    if not isinstance(message, dict):
        raise ValueError('Invalid sendPhoto response')
    if (type(message.get('message_id')) is not int or message['message_id'] <= 0
            or type(message.get('date')) is not int
            or not -120 <= now.timestamp() - message['date'] <= 300
            or str(message.get('chat',{}).get('id')) != outbox['chat_id']
            or message.get('chat',{}).get('type') != 'supergroup'
            or str(message.get('from',{}).get('id')) != state['runner']['expected_bot_id']
            or message.get('from',{}).get('is_bot') is not True
            or message.get('caption') != outbox['text']
            or message.get('has_protected_content') is not True
            or not isinstance(message.get('photo'), list) or not message['photo']):
        raise ValueError('Unverified sendPhoto result')
    entities = message.get('caption_entities', [])
    if 'reply_markup' in outbox and message.get('reply_markup') != outbox['reply_markup']:
        raise ValueError('Telegram inline keyboard not verified')
    if not any(isinstance(e,dict) and e.get('type') == 'text_mention' and e.get('offset') == 0
               and e.get('length') == len(state.get('confirmer_label', 'Участник').encode('utf-16-le')) // 2 and str(e.get('user',{}).get('id')) == state['confirmer_id'] for e in entities):
        raise ValueError('Telegram mention not verified')
    for photo in message['photo']:
        if (not isinstance(photo, dict) or not isinstance(photo.get('file_id'),str) or not photo['file_id']
                or type(photo.get('width')) is not int or photo['width'] <= 0
                or type(photo.get('height')) is not int or photo['height'] <= 0):
            raise ValueError('Unverified photo result')
    return message


def confirmed_delivery(state, event, receipt):
    """Called only with validated returned Message under state.json.lock."""
    runner = state['runner']
    if any(r['message_id'] == receipt['message_id'] and r['chat_id'] == receipt['chat_id'] for r in runner['receipts']):
        return
    runner['receipts'].append(receipt)
    sent = deepcopy(event)
    sent.pop('simulation_only', None)
    sent.update(message_id=receipt['message_id'], verification_basis=receipt['verification_basis'])
    state['sent'].append(sent)
    state['last_delivery_day'] = event['day']
    if event['kind'] in ('start','end'):
        q = state['question']
        streak = q['streak'] + 1 if q and q['kind'] == event['kind'] else 1
        state['question'] = {'kind':event['kind'], 'streak':streak, 'paused':streak >= 3,
                'last_asked':event['day'], 'next_due':(date.fromisoformat(event['day']) + timedelta(days=1)).isoformat()}
    elif event['kind'] == 'end_date':
        runner['clarification']['sent'] = True


def run(path, db, now, *, execute=False, api=None, renderer=None, env_path=None):
    path = Path(path)
    if now.tzinfo is None:
        raise ValueError('Timezone required')
    if not execute:
        state = json.loads(path.read_text())
        return plan(state, now)
    # Disabled drafts do not even create the lock or read the database.
    initial = json.loads(path.read_text())
    if initial.get('stage') != 'active' or initial.get('delivery_enabled') is not True:
        return
    fd = os.open(str(path) + '.lock', os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(path.read_text())
        if state.get('stage') != 'active' or state.get('delivery_enabled') is not True:
            return
        validate(state, now)
        before = deepcopy(state)
        runner = state['runner']
        outbox = runner.get('outbox')
        if outbox and outbox['status'] in ('prepared', 'inflight'):
            outbox.update(status='uncertain', retryable=False, reason='interrupted_attempt')
        consume_rows(state, read_rows(db, state, now), now)
        if state != before:
            engine.save_state(path, state)
        outbox = runner.get('outbox')
        if outbox and outbox['status'] != 'confirmed':
            return
        if runner.get('paused'):
            return
        event = plan(state, now)
        local = now.astimezone(ZoneInfo(state['timezone']))
        clarification = runner.get('clarification')
        if (clarification and not clarification.get('sent') and local.hour == 10
                and state['last_delivery_day'] != local.date().isoformat()
                and clarification['chat_id'] == state['planned_destination'].split(':',1)[1]):
            event = {'key':state['cycles'][-1]['start'] + ':end_date:' + local.date().isoformat(),
                     'cycle':state['cycles'][-1]['start'], 'kind':'end_date', 'day':local.date().isoformat(),
                     'text':'Уточни последний день кровотечения: сегодня, вчера или точную дату. Дату окончания пока не записываю.'}
        if not event:
            return
        caption, marker = caption_for(state, event)
        output = path.parent / 'reminder-calendar.png'
        if renderer is None:
            renderer = module('render_calendar').render
        renderer(state, engine.forecast(state)['next_period'], local.date(), output)
        os.chmod(output, 0o600)
        # Verify output locally before any API calls.
        from PIL import Image
        with Image.open(output) as image:
            if image.format != 'PNG':
                raise ValueError('Calendar must be PNG')
            image.verify()
        owned = api is None
        if api is None and env_path is None:
            raise ValueError('Explicit env_path required for Telegram transport')
        api = api or TelegramAPI(env_path)
        try:
            outbox = {'key':event['key'], 'status':'prepared', 'chat_id':state['planned_destination'].split(':',1)[1],
                    'caption_html':caption, 'text':plain(caption), 'marker':marker, 'event':deepcopy(event),
                    'created_at':now.isoformat(), 'retryable':False}
            if event['kind'] == 'end_date':
                outbox['reply_to'] = clarification['message_id']
            prepared_buttons = buttons.prepare_buttons(event, now)
            if prepared_buttons is not None:
                prepared_buttons['question_last_asked'] = (event['day'] if event['kind'] in ('start','end')
                        else (state.get('question') or {}).get('last_asked'))
                outbox['buttons'] = prepared_buttons
                outbox['reply_markup'] = buttons.reply_markup(prepared_buttons)
            runner['outbox'] = outbox
            engine.save_state(path, state)
            try:
                api.verify(state)
            except Exception as error:
                outbox.update(status='rejected', reason='telegram_preflight_not_confirmed',
                              error_code=error.code if isinstance(error, SendFailure) else 0,
                              retryable=False)
                engine.save_state(path, state)
                return
            outbox['status'] = 'inflight'
            engine.save_state(path, state)
            try:
                args = [outbox['chat_id'], caption, output, outbox.get('reply_to')]
                if 'reply_markup' in outbox:
                    args.append(outbox['reply_markup'])
                message = api.send_photo(*args)
                validate_message(message, state, outbox, now)
            except Exception as error:
                outbox.update(status='rejected' if isinstance(error, SendFailure) and error.kind == 'rejected' else 'uncertain',
                              error_code=error.code if isinstance(error, SendFailure) else 0,
                              reason='telegram_send_not_confirmed', retryable=False)
                engine.save_state(path, state)
                return
            receipt = {'chat_id':outbox['chat_id'], 'message_id':message['message_id'],
                    'text':message['caption'], 'caption_html':caption, 'marker':marker,
                    'key':event['key'], 'day':event['day'], 'cycle':event['cycle'], 'kind':event['kind'],
                    'sent_at':datetime.fromtimestamp(message['date'], ZoneInfo(state['timezone'])).isoformat(),
                    'verification_basis':'sendPhoto_returned_Message', 'returned_message':message}
            if 'buttons' in outbox:
                receipt['buttons'] = deepcopy(outbox['buttons'])
                receipt['reply_markup'] = deepcopy(outbox['reply_markup'])
            confirmed_delivery(state, event, receipt)
            outbox.update(status='confirmed', confirmed_at=now.isoformat(), message_id=message['message_id'])
            engine.save_state(path, state)
        finally:
            if owned:
                api.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--db', type=Path)
    parser.add_argument('--env-file', type=Path, help='Explicit protected Telegram credential file; execute only')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--dry-run', action='store_true')
    parser.add_argument('--at', help='Offline dry-run timestamp only; execute uses real clock')
    args = parser.parse_args(argv)
    if args.execute and (args.db is None or args.env_file is None):
        parser.error('--execute requires --db and --env-file')
    if args.execute and args.at:
        parser.error('--at is dry-run only')
    try:
        now = parse_time(args.at) if args.at else datetime.now(ZoneInfo('Europe/Moscow'))
        run(args.state, args.db, now, execute=args.execute, env_path=args.env_file)
        return 0
    except Exception:
        # Deliberately no exception repr: third-party errors may contain token URLs.
        print('cycle reminder runner: local validation/preflight failed; inspect private state', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
