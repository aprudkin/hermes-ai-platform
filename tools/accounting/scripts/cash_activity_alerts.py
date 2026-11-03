"""Cancelled Bablomat activity alerts; default polling is disabled.

Retain the legacy classifier/baseline for offline tests with injected senders.
Never resolve a production transport or reuse clarification case routing.
"""
import os
import fcntl
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

CHAT_ID = os.environ.get('BABLOMAT_CHAT_ID', '')


def scan_activity(home, *, initialize=False, sender=None):
    # Cancelled workflow: never instantiate the clarification sender or resolve
    # a live transport, even if an old activity baseline reappears. Injected
    # senders remain available only for offline legacy classifier tests.
    if not initialize and sender is None:
        return {'status':'disabled','scanned':0,'alerted':0}
    if not CHAT_ID:
        raise ValueError('BABLOMAT_CHAT_ID is required for explicit legacy classifier use')
    home = Path(home)
    directory = home / 'cash-ledger'
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / 'activity-alerts.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status':'locked','scanned':0,'alerted':0}
        with closing(sqlite3.connect('file:' + str(home / 'state.db') + '?mode=ro', uri=True)) as source:
            rows = source.execute('''SELECT m.id,m.timestamp,m.platform_message_id
                FROM messages m JOIN sessions s ON s.id=m.session_id
                WHERE s.chat_id=? AND m.role='user' AND m.active=1
                AND COALESCE(m._compressed_summary,0)=0 ORDER BY m.id''', (CHAT_ID,)).fetchall()
        with closing(sqlite3.connect(directory / 'activity-alerts.db', timeout=30)) as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS cursor (id INTEGER PRIMARY KEY CHECK(id=1),last_row INTEGER);
                CREATE TABLE IF NOT EXISTS delivered (message_key TEXT PRIMARY KEY,source_row INTEGER);''')
            if initialize:
                db.execute('INSERT OR IGNORE INTO cursor VALUES(1,?)', (max((r[0] for r in rows),default=0),))
                db.commit()
                return {'status':'initialized','scanned':0,'alerted':0}
            cursor = db.execute('SELECT last_row FROM cursor WHERE id=1').fetchone()
            if cursor is None:
                raise RuntimeError('Initialize activity alerts before polling; refusing historical alerts')
            result = {'status':'ok','scanned':0,'alerted':0}
            for row_id,timestamp,message_id in rows:
                if row_id <= cursor[0]:
                    continue
                local = datetime.fromtimestamp(timestamp,ZoneInfo('Europe/Moscow'))
                key = str(message_id) if message_id else 'row:' + str(row_id)
                if not 2 <= local.hour < 10 and not db.execute('SELECT 1 FROM delivered WHERE message_key=?',(key,)).fetchone():
                    weekday = ('пн','вт','ср','чт','пт','сб','вс')[local.weekday()]
                    text = ('В Бабломате сообщение вне окна 02:00–10:00 МСК.\n'
                            + local.strftime('%d.%m') + ' (' + weekday + '), ' + local.strftime('%H:%M') + ' МСК\n')
                    if message_id and str(message_id).isdigit():
                        text += 'https://t.me/c/' + CHAT_ID[4:] + '/' + str(message_id)
                    else:
                        text += 'Ссылка недоступна; сохранённая запись №' + str(row_id)
                    sender(text)
                    db.execute('INSERT INTO delivered VALUES(?,?)',(key,row_id))
                    result['alerted'] += 1
                db.execute('UPDATE cursor SET last_row=MAX(last_row,?) WHERE id=1',(row_id,))
                db.commit()
                result['scanned'] += 1
            return result
