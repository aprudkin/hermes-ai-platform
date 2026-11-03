"""Native Telegram evidence only; never infer identity/replies from rendered text."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path


def _id(obj, name):
    value = getattr(obj, name, None)
    return str(value) if value is not None else None


def capture(home, chat_id, event):
    """Persist native evidence for the explicitly selected chat, not event.source."""
    msg = getattr(event, 'raw_message', None)
    if not chat_id or _id(getattr(msg, 'chat', None), 'id') != str(chat_id):
        return
    message_id = _id(msg, 'message_id')
    if message_id is None:
        return
    user = getattr(msg, 'from_user', None)
    reply = getattr(msg, 'reply_to_message', None)
    date = getattr(msg, 'date', None)
    payload = dict(chat_id=str(chat_id), message_id=message_id,
                   sender_id=_id(user, 'id'), sender_is_bot=getattr(user, 'is_bot', None),
                   reply_to_chat_id=_id(getattr(reply, 'chat', None), 'id'),
                   reply_to_message_id=_id(reply, 'message_id'),
                   reply_to_text=getattr(reply, 'text', None) or getattr(reply, 'caption', None),
                   quote_text=getattr(getattr(msg, 'quote', None), 'text', None),
                   text=getattr(msg, 'text', None) or getattr(msg, 'caption', None),
                   timestamp=date.isoformat() if date else None)
    path = Path(home) / 'cash-ledger' / 'native-inputs.db'
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not path.exists():
        path.touch(mode=0o600)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS native_inputs '
                   '(chat_id TEXT, message_id TEXT, payload TEXT, conflicted INTEGER DEFAULT 0, '
                   'PRIMARY KEY(chat_id,message_id,payload))')
        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT OR IGNORE INTO native_inputs(chat_id,message_id,payload) VALUES (?,?,?)',
                   (str(chat_id), message_id, json.dumps(payload, sort_keys=True)))
        db.execute('UPDATE native_inputs SET conflicted=1 WHERE chat_id=? AND message_id=? '
                   'AND (SELECT COUNT(*) FROM native_inputs WHERE chat_id=? AND message_id=?)>1',
                   (str(chat_id), message_id, str(chat_id), message_id))


def read_native(path, chat_id, message_id):
    """Read one exact native record without creating or modifying a database."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            rows = db.execute('SELECT payload,conflicted FROM native_inputs WHERE chat_id=? AND message_id=?',
                              (str(chat_id), str(message_id))).fetchall()
        payload = json.loads(rows[0][0]) if len(rows) == 1 and not rows[0][1] else None
        if (isinstance(payload, dict) and payload.get('chat_id') == str(chat_id)
                and payload.get('message_id') == str(message_id)):
            return payload
        return None
    except (sqlite3.Error, ValueError):
        return None
