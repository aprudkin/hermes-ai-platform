"""Content-free host sender. Configured manager bot/chat; no inbound Telegram operations."""
from contextlib import contextmanager, closing
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request

CHAT = int(os.environ.get('HERMES_STATUS_CHAT_ID', '0'))
BOT = int(os.environ.get('HERMES_STATUS_BOT_ID', '0'))
HOME = Path('/opt/hermes/data/profiles/manager')
STATE = Path('/var/lib/hermes-manager-status')
JOBS = tuple(filter(None, os.environ.get('HERMES_STATUS_JOB_IDS', '').split(',')))
LABELS = Path(os.environ.get('HERMES_STATUS_LABELS', str(Path(__file__).with_name('job-labels.json'))))
TEXT = {
    'test': 'Технические уведомления: проверка доставки.',
    'pause-planned': 'Hermes: сейчас планируется краткая пауза для снимка состояния. После подтверждённого возобновления сообщу отдельно.',
    'unpause-confirmed': 'Hermes: контейнер работает, снятие паузы после снимка состояния подтверждено.',
    'backup-start': 'Задача manager: резервное копирование — старт.',
    'backup-ok': 'Задача manager: резервное копирование — завершена.',
    'backup-failed': 'Задача manager: резервное копирование — ошибка. Подробности сохранены локально.',
}


def render(event, job=None):
    if event in TEXT and job is None:
        return TEXT[event]
    words = {'cron-start': 'началась', 'cron-ok': 'завершена',
             'cron-failed': 'ошибка', 'cron-unknown': 'исход неизвестен'}
    if event not in words or job not in JOBS:
        raise ValueError('event not allowlisted')
    # Read every time: later vetted label corrections need no daemon reload.
    labels = json.loads(LABELS.read_text())
    label = labels.get(job)
    if not isinstance(label, str) or not 5 <= len(label) <= 90 or '\n' in label:
        raise ValueError('reviewed task label unavailable')
    return f'{label} — {words[event]}.'


@contextmanager
def connect(state):
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    c = sqlite3.connect(state / 'receipts.db', timeout=15)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA synchronous=FULL')
    c.execute('CREATE TABLE IF NOT EXISTS sends (key TEXT PRIMARY KEY, event TEXT, job TEXT, text TEXT, status TEXT, chat_id INTEGER, bot_id INTEGER, message_id INTEGER, created_at TEXT, verified_at TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)')
    try:
        with c:
            yield c
    finally:
        c.close()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def token():
    # Parse only the approved single profile credential, never log .env or URL.
    text = (HOME / '.env').read_text()
    match = re.search(r'^\s*(?:export\s+)?TELEGRAM_BOT_TOKEN\s*=\s*(.+?)\s*$', text, re.M)
    if not match:
        raise ValueError('manager credential unavailable')
    value = match[1].strip().strip('\"\'')
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', value):
        raise ValueError('manager credential format invalid')
    return value


def api(method, payload):
    if method not in ('getMe', 'getChat', 'getChatMember', 'sendMessage', 'editMessageText'):
        raise ValueError('method not allowlisted')
    req = urllib.request.Request('https://api.telegram.org/bot' + token() + '/' + method,
                                 json.dumps(payload).encode(), {'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        # Return structured Telegram response, never serialize exception URL.
        return json.loads(e.read())


def configured():
    if not (CHAT < 0 and BOT > 0):
        raise ValueError('explicit chat and bot configuration required')


def identity(transport=api):
    configured()
    me = transport('getMe', {})
    chat = transport('getChat', {'chat_id': CHAT})
    member = transport('getChatMember', {'chat_id': CHAT, 'user_id': BOT})
    if not (me.get('ok') and me['result'].get('id') == BOT
            and chat.get('ok') and chat['result'].get('id') == CHAT
            and chat['result'].get('type') == 'supergroup'
            and member.get('ok') and member['result'].get('user', {}).get('id') == BOT
            and member['result'].get('status') == 'administrator'):
        raise ValueError('target identity mismatch')
    return {'bot_id': BOT, 'chat_id': CHAT, 'type': 'supergroup', 'member': 'administrator'}


def verify(row, transport=api):
    result = transport('editMessageText', {'chat_id': CHAT, 'message_id': row['message_id'], 'text': row['text']})
    if result.get('ok'):
        r = result['result']
        return (r.get('chat', {}).get('id') == CHAT and r.get('message_id') == row['message_id']
                and r.get('text') == row['text'] and r.get('from', {}).get('id') == BOT)
    return (result.get('error_code') == 400 and 'message is not modified' in result.get('description', '').lower())


def send(key, event, job=None, state=STATE, transport=api):
    configured()
    text = render(event, job)
    if not re.fullmatch(r'[A-Za-z0-9:_-]{1,240}', key):
        raise ValueError('bad event key')
    with connect(state) as c:
        c.execute('BEGIN IMMEDIATE')
        old = c.execute('SELECT * FROM sends WHERE key=?', (key,)).fetchone()
        if old:
            if (old['event'] != event or old['job'] != job or old['text'] != text
                    or old['chat_id'] != CHAT or old['bot_id'] != BOT):
                raise ValueError('receipt collision')
            return dict(old)  # intent/uncertain NEVER auto-retried
        c.execute('INSERT INTO sends (key,event,job,text,status,chat_id,bot_id,created_at) VALUES (?,?,?,?,?,?,?,?)',
                  (key, event, job, text, 'intent', CHAT, BOT, now()))
        c.commit()  # durable before any network or effect
        try:
            identity(transport)
            result = transport('sendMessage', {'chat_id': CHAT, 'text': text, 'disable_notification': True,
                                               'protect_content': True, 'link_preview_options': {'is_disabled': True}})
            r = result.get('result', {})
            if not (result.get('ok') and r.get('chat', {}).get('id') == CHAT
                    and r.get('from', {}).get('id') == BOT and r.get('text') == text
                    and isinstance(r.get('message_id'), int)):
                raise ValueError('unverified send response')
            c.execute('UPDATE sends SET message_id=?,status=? WHERE key=?', (r['message_id'], 'sent', key))
            c.commit()
            row = c.execute('SELECT * FROM sends WHERE key=?', (key,)).fetchone()
            if not verify(row, transport):
                raise ValueError('message readback failed')
            c.execute('UPDATE sends SET status=?,verified_at=? WHERE key=?', ('verified', now(), key))
        except Exception:
            c.execute('UPDATE sends SET status=? WHERE key=?', ('uncertain', key))
        return dict(c.execute('SELECT * FROM sends WHERE key=?', (key,)).fetchone())


def cron_events(rows):
    for r in rows:
        if r['job_id'] not in JOBS or not r['scheduled_instant']:
            continue
        key = 'cron:' + r['id']
        if r['started_at']:
            yield (key + ':start', 'cron-start', r['job_id'])
        if r['status'] in ('completed', 'failed', 'unknown'):
            yield (key + ':terminal', {'completed': 'cron-ok', 'failed': 'cron-failed', 'unknown': 'cron-unknown'}[r['status']], r['job_id'])


def observe_once(home=HOME, state=STATE, sender=send):
    with connect(state) as c:
        row = c.execute("SELECT value FROM meta WHERE key='cutoff'").fetchone()
        if row is None:
            c.execute("INSERT INTO meta VALUES ('cutoff',?)", (now(),))
            return 0  # no historic replay on activation
        cutoff = row[0]
    with closing(sqlite3.connect('file:' + str(home / 'cron/executions.db') + '?mode=ro', uri=True, timeout=5)) as db:
        db.execute('PRAGMA query_only=ON')
        db.row_factory = sqlite3.Row
        rows = db.execute('SELECT id,job_id,status,scheduled_instant,started_at FROM executions WHERE claimed_at>=? ORDER BY claimed_at,id', (cutoff,)).fetchall()
    with connect(state) as c:
        known = {r[0] for r in c.execute('SELECT key FROM sends')}
    events = [e for e in cron_events(rows) if e[0] not in known]
    for key, event, job in events:
        sender(key, event, job, state=state)
    return len(events)


def main():
    configured()
    os.umask(0o077)
    if sys.argv[1:] == ['observe']:
        STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (STATE / 'observer.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            while True:
                try:
                    observe_once()
                except Exception:
                    print('manager status observer: local source unavailable', file=sys.stderr, flush=True)
                time.sleep(1)
    elif len(sys.argv) == 3 and sys.argv[1] == 'backup':
        invocation = os.environ.get('INVOCATION_ID', '')
        if not re.fullmatch('[a-f0-9]{32}', invocation):
            raise ValueError('missing systemd invocation')
        event = 'backup-start' if sys.argv[2] == 'start' else ('backup-ok' if os.environ.get('SERVICE_RESULT') == 'success' else 'backup-failed')
        print(json.dumps(send('backup:' + invocation + ':' + sys.argv[2], event)))
    elif sys.argv[1:] == ['test']:
        print(json.dumps(send('approved-group-test-v1', 'test'), ensure_ascii=False))
    elif len(sys.argv) == 3 and sys.argv[1] == 'verify':
        with connect(STATE) as c:
            row = c.execute('SELECT * FROM sends WHERE key=?', (sys.argv[2],)).fetchone()
        print(json.dumps({'key': sys.argv[2], 'message_id': row['message_id'], 'verified': verify(row)}))
    else:
        raise ValueError('unsupported action')

if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('manager status: operation failed; inspect local receipts, do not retry blindly', file=sys.stderr)
        sys.exit(1)
