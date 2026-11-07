"""Durable cycle inline keyboards. No network or Telegram SDK dependency.

Callback integration API is synchronous and must run off the event loop:
    handle_button(state_path, *, actor_id, chat_id, message_id, data,
                  callback_id, now, message_author_id=None, bot_id=None) -> dict
All IDs must come from Telegram metadata. The gateway MUST verify the actual
message author is its own bot and authorize the callback user before calling.
Optional bot_id/context.bot.id and message_author_id/message.from_user.id
must be supplied together for an additional local cross-check. Never derive
actor or target metadata from callback data. Only the plugin answers the callback
and (when clear_keyboard=True) removes reply_markup, never edits captions.
"""
from datetime import datetime, time, timedelta
from copy import deepcopy
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
from zoneinfo import ZoneInfo

_spec = importlib.util.spec_from_file_location('cycle_button_engine', Path(__file__).with_name('cycle_engine.py'))
engine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine)

MOSCOW = ZoneInfo('Europe/Moscow')


def prepare_buttons(event, now):
    if event['kind'] not in ('start', 'end', 'end_date'):
        return None
    local = now.astimezone(MOSCOW)
    if now.tzinfo is None or event['day'] != local.date().isoformat():
        raise ValueError('Buttons require current Moscow event day')
    return {'nonce':secrets.token_urlsafe(18), 'kind':event['kind'],
            'day':event['day'], 'cycle':event['cycle'], 'key':event['key'],
            'expires_at':datetime.combine(local.date() + timedelta(days=1), time(), MOSCOW).isoformat()}


def reply_markup(buttons):
    if buttons is None:
        return None
    labels = [('Сегодня','today'), ('Вчера','yesterday'), ('Ещё нет','negative'), ('Другая дата','other')]
    if buttons['kind'] == 'end':
        labels = [('Закончились сегодня','today'), ('Закончились вчера','yesterday'), ('Ещё идут','negative'), ('Другая дата','other')]
    elif buttons['kind'] == 'end_date':
        labels = [('Сегодня','today'), ('Вчера','yesterday'), ('Другая дата','other')]
    items = [{'text':label,'callback_data':'ct1:' + buttons['nonce'] + ':' + action} for label,action in labels]
    return {'inline_keyboard':[items[i:i+2] for i in range(0,len(items),2)]}


def handle_button(state_path, *, actor_id, chat_id, message_id, data,
                  callback_id, now, message_author_id=None, bot_id=None):
    """Commit under runner lock; caller owns callback answer/keyboard removal.

    Invalid/stale callbacks never save state. Unauthorized actor/chat never
    create a lock or mutate state; identity is read from explicit state config. Exceptions expose no private details.
    """
    rejected = {'accepted':False,'text':'Эта кнопка сейчас недоступна.','clear_keyboard':False}
    if (not re.fullmatch(r'\d+', str(actor_id)) or not re.fullmatch(r'-100\d+', str(chat_id))
            or not isinstance(now,datetime) or now.tzinfo is None
            or type(message_id) is not int or message_id <= 0
            or not isinstance(data,str) or len(data) > 64
            or not re.fullmatch(r'ct1:[A-Za-z0-9_-]{24}:(today|yesterday|negative|other)',data)
            or not isinstance(callback_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}',callback_id)):
        return rejected
    path = Path(state_path)
    try:
        initial = json.loads(path.read_text())
        if (str(actor_id) != initial.get('confirmer_id')
                or 'telegram:' + str(chat_id) != initial.get('planned_destination')):
            return rejected
        fd = os.open(str(path) + '.lock', os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = json.loads(path.read_text())
            runner = state['runner']
            receipt = runner['receipts'][-1]
            b = receipt['buttons']
            outbox = runner['outbox']
            q = state['question']
            today = now.astimezone(MOSCOW).date()
            expiry = datetime.combine(today + timedelta(days=1),time(),MOSCOW)
            expected = runner['expected_bot_id']
            returned = receipt['returned_message']
            source = 'callback:' + callback_id
            if (state['stage'] != 'active' or state['delivery_enabled'] is not True
                    or state['timezone'] != 'Europe/Moscow'
                    or state['confirmer_id'] != str(actor_id)
                    or state['planned_destination'] != 'telegram:' + str(chat_id)
                    or runner.get('paused') or not q
                    or ((bot_id is not None or message_author_id is not None)
                        and (str(bot_id) != expected or str(message_author_id) != expected))
                    or str(receipt['chat_id']) != str(chat_id) or receipt['message_id'] != message_id
                    or receipt.get('button_answer')
                    or receipt['verification_basis'] != 'sendPhoto_returned_Message'
                    or receipt['cycle'] != state['cycles'][-1]['start']
                    or b['cycle'] != receipt['cycle'] or b['kind'] != receipt['kind']
                    or b['key'] != receipt['key']
                    or b['day'] != today.isoformat() or receipt['day'] != b['day']
                    or datetime.fromisoformat(b['expires_at']) != expiry or now >= expiry
                    or datetime.fromisoformat(receipt['sent_at']) > now
                    or q['kind'] != ('start' if b['kind'] == 'start' else 'end')
                    or q.get('last_asked') != b['question_last_asked']
                    or (b['kind'] == 'start') != (state['cycles'][-1]['end'] is not None)
                    or outbox['status'] != 'confirmed' or outbox['message_id'] != message_id
                    or str(outbox['chat_id']) != str(chat_id) or outbox['buttons'] != b
                    or returned['message_id'] != message_id
                    or str(returned['chat']['id']) != str(chat_id)
                    or returned['chat']['type'] != 'supergroup'
                    or str(returned['from']['id']) != expected or returned['from']['is_bot'] is not True
                    or receipt['reply_markup'] != reply_markup(b)
                    or returned['reply_markup'] != receipt['reply_markup']
                    or any(e['message_id'] == source for e in state['events'])):
                return rejected
            allowed = [item['callback_data'] for row in receipt['reply_markup']['inline_keyboard'] for item in row]
            if data not in allowed:
                return rejected
            action = data.rsplit(':',1)[1]
            if action == 'other':
                q.update(streak=0,paused=False,next_due=(today + timedelta(days=1)).isoformat())
                state['events'].append({'message_id':source,'actor':str(actor_id),
                        'action':'request_date','value':None,'recorded_on':today.isoformat(),
                        'before_cycles':deepcopy(state['cycles'])})
                receipt['date_requested'] = {'source_id':source,'at':now.isoformat()}
                engine.save_state(path,state)
                return {'accepted':True,'text':'Ответь на это сообщение датой ДД.ММ',
                        'clear_keyboard':False,'show_alert':True}
            if action == 'negative':
                decision = 'not_started' if b['kind'] == 'start' else 'ongoing'
                value = None
            else:
                decision = 'start' if b['kind'] == 'start' else 'end'
                value = (today - timedelta(days=1 if action == 'yesterday' else 0)).isoformat()
            if not engine.respond(state, decision, value, str(actor_id), source, today.isoformat()):
                return rejected
            runner['paused'] = False
            if decision in ('start','end'):
                runner.pop('clarification',None)
            receipt['button_answer'] = {'source_id':source,'action':decision,'value':value,'at':now.isoformat()}
            engine.save_state(path,state)
            return {'accepted':True,'text':'Ответ сохранён.','clear_keyboard':True}
    except (OSError,ValueError,KeyError,IndexError,TypeError,AttributeError,PermissionError):
        return rejected
