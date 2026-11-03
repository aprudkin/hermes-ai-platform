"""Durable clarification cases, separate from financial state and old receipts.

PrivateReviewSender retains its historical import name, not its old DM route.
"""
import os
import hashlib
import json
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from cash_reply_sender import ReplySender

GROUP = os.environ.get('BABLOMAT_REVIEW_CHAT_ID', '')
ELENA = os.environ.get('BABLOMAT_ELENA_ID', '')
OWNER = os.environ.get('BABLOMAT_OWNER_ID', '')
GREETINGS = ('Ле',)


class PrivateReviewSender:
    def __init__(self, home, *, post=None, clock=time.time):
        if not (GROUP.startswith('-100') and GROUP[4:].isdigit() and ELENA.isdigit() and int(ELENA) > 0 and OWNER.isdigit() and int(OWNER) > 0):
            raise ValueError('Explicit Bablomat review group, Elena and owner routing is required')
        self.home = Path(home)
        self.clock = clock
        self.post = post or self._post
        self.path = self.home / 'cash-ledger' / 'review-cases.db'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as c:
            c.execute('''CREATE TABLE IF NOT EXISTS cases (
                case_id TEXT PRIMARY KEY, question TEXT NOT NULL, greeting TEXT NOT NULL,
                group_text TEXT NOT NULL, group_state TEXT NOT NULL,
                group_message_id INTEGER, group_sent_at REAL, due_at REAL,
                reply_status TEXT NOT NULL DEFAULT 'open',
                escalation_state TEXT NOT NULL DEFAULT 'none', escalation_text TEXT,
                escalation_message_id INTEGER, escalation_sent_at REAL)''')
            c.execute('''CREATE TABLE IF NOT EXISTS delivery_attempts(
                case_id TEXT NOT NULL, phase TEXT NOT NULL, started_at REAL NOT NULL,
                payload_json TEXT NOT NULL, response_json TEXT, error_type TEXT,
                PRIMARY KEY(case_id,phase))''')
            c.commit()

    _post = ReplySender._post

    def _deliver(self, c, key, phase, payload):
        # Cases are the state machine; this append-only attempt is delivery evidence.
        # Never log exception messages: an injected/network exception may contain secrets.
        started = self.clock()
        c.execute('INSERT INTO delivery_attempts(case_id,phase,started_at,payload_json) VALUES(?,?,?,?)',
                  (key, phase, started, json.dumps(payload, ensure_ascii=False)))
        c.commit()
        try:
            result = self.post(payload)
            c.execute('UPDATE delivery_attempts SET response_json=? WHERE case_id=? AND phase=?',
                      (json.dumps(result, ensure_ascii=False), key, phase))
            c.commit()
            self._verify(result, payload, started)
        except Exception as exc:
            # phase is internal, never participant-controlled SQL.
            c.execute(f"UPDATE cases SET {phase}_state='uncertain' WHERE case_id=?", (key,))
            c.execute('UPDATE delivery_attempts SET error_type=? WHERE case_id=? AND phase=?',
                      (type(exc).__name__, key, phase))
            c.commit()
            raise RuntimeError('Review delivery uncertain; ' + type(exc).__name__) from None
        return result

    def _verify(self, result, payload, started):
        message_id, date = result.get('message_id'), result.get('date')
        if (str(result.get('chat', {}).get('id')) != payload['chat_id']
                or result.get('text') != payload['text']
                or type(message_id) is not int or message_id <= 0
                or type(date) is not int or not max(1, started - 60) <= date <= self.clock() + 60):
            raise RuntimeError('Telegram did not confirm review target/text/id/date')
        for expected in payload.get('entities', []):
            if not any(e.get('type') == 'text_mention' and e.get('offset') == expected['offset']
                       and e.get('length') == expected['length']
                       and str(e.get('user', {}).get('id')) == ELENA
                       for e in result.get('entities', [])):
                raise RuntimeError('Telegram did not confirm Elena mention')

    def cancel_case(self, case_id, *, actor_id, reason):
        """Local operator action, not an authorization inferred from chat prose.

        Use to retire a transparent setup-test case; preserves all send evidence.
        This API does not change amounts, payouts, or any financial resolution.
        """
        if str(actor_id) != OWNER or not reason.strip():
            raise ValueError('Cancellation requires owner authorization and an audit reason')
        with closing(sqlite3.connect(self.path, timeout=30)) as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT reply_status FROM cases WHERE case_id=?', (case_id,)).fetchone()
            if not row:
                raise ValueError('Unknown clarification case')
            if row[0] != 'open':
                return False
            c.execute('''CREATE TABLE IF NOT EXISTS cancellations(case_id TEXT PRIMARY KEY,
                         actor_id TEXT NOT NULL, reason TEXT NOT NULL, timestamp REAL NOT NULL)''')
            c.execute('INSERT INTO cancellations VALUES(?,?,?,?)', (case_id, str(actor_id), reason, self.clock()))
            c.execute("UPDATE cases SET reply_status='cancelled' WHERE case_id=?", (case_id,))
            c.commit()
        return True

    def scan_replies(self, source_db):
        """Read active saved Telegram observations; never touch the financial ledger."""
        with closing(sqlite3.connect(Path(source_db).resolve().as_uri() + '?mode=ro', uri=True)) as source:
            source.row_factory = sqlite3.Row
            columns = {r[1] for r in source.execute('PRAGMA table_info(messages)')}
            optional = ''.join(',m.' + name for name in ('reply_to_message_id', 'reply_to_chat_id') if name in columns)
            rows = source.execute('''SELECT m.id,m.content,m.timestamp,m.platform_message_id,s.chat_id,s.user_id
                ''' + optional + ''' FROM messages m JOIN sessions s ON s.id=m.session_id
                WHERE s.source='telegram' AND m.active=1 AND m.role='user' AND s.chat_id IN (?,?)
                ORDER BY m.timestamp,m.id''', (GROUP, ELENA)).fetchall()
        count = 0
        with closing(sqlite3.connect(self.path, timeout=30)) as c:
            c.row_factory = sqlite3.Row
            c.execute('BEGIN IMMEDIATE')
            c.execute('''CREATE TABLE IF NOT EXISTS responses(case_id TEXT PRIMARY KEY,
                         source_row_id INTEGER, chat_id TEXT, message_id TEXT,
                         timestamp REAL, sender_id TEXT, evidence_json TEXT)''')
            for case in c.execute("SELECT * FROM cases WHERE group_state='sent' AND reply_status='open'").fetchall():
                for row in rows:
                    content = row['content'] or ''
                    author = re.match(r'^\[[^|\]\n]+\|(\d+)\]\n', content)
                    sender_id = author.group(1) if author else (row['user_id'] if row['chat_id'] == ELENA else None)
                    body = content[author.end():].strip() if author else content.strip()
                    if (sender_id not in (ELENA, OWNER) or not body or not row['platform_message_id']
                            or not case['group_sent_at'] <= row['timestamp'] <= self.clock()
                            or (row['chat_id'] == ELENA and (sender_id != ELENA or row['user_id'] != ELENA))):
                        continue
                    target_id = case['group_message_id'] if row['chat_id'] == GROUP else (
                        case['escalation_message_id'] if case['escalation_state'] == 'sent' else None)
                    matched = ('reply_to_message_id' in columns and target_id is not None
                               and str(row['reply_to_message_id']) == str(target_id)
                               and ('reply_to_chat_id' not in columns or row['reply_to_chat_id'] in (None, row['chat_id'])))
                    if not matched:
                        references = [f"[case:{case['case_id']}]",
                                      f"https://t.me/c/{GROUP[4:]}/{case['group_message_id']}",
                                      f'[Replying to your previous message: "{case["group_text"]}"]',
                                      f'[Replying to: "{case["group_text"]}"]']
                        for reference in references:
                            if body.startswith(reference + '\n'):
                                body = body[len(reference):].strip()
                                matched = True
                                break
                    # A new question is not an answer, even if it names the same model.
                    if not matched or not body or '?' in body or '？' in body:
                        continue
                    if sender_id == OWNER and body.casefold().rstrip('.! ') not in ('вопрос закрыт', 'уточнение подтверждено'):
                        continue
                    # Conservative lexical response gate, not a financial parser:
                    # exact linkage alone must not turn a greeting/new report into an answer.
                    if sender_id == ELENA and not re.match(
                            r'^(?:да|нет|верно|вс[её] верно|подтверждаю|это|сумма|деньги|'
                            r'не знаю|уточню|исправление|оператор|опер|модель|модели|агентство|клиент|'
                            r'yes|no|correct|confirmed)\b|^[+$€₽\-]?\d', body, re.IGNORECASE):
                        continue
                    status = 'resolved' if sender_id == OWNER else 'responded'
                    c.execute('UPDATE cases SET reply_status=? WHERE case_id=?', (status, case['case_id']))
                    c.execute('INSERT INTO responses VALUES(?,?,?,?,?,?,?)',
                              (case['case_id'], row['id'], row['chat_id'], row['platform_message_id'],
                               row['timestamp'], sender_id, json.dumps(dict(row), ensure_ascii=False)))
                    count += 1
                    break
            c.commit()
        return count

    def process_due(self):
        """Send each still-open due case at most once; never retry ambiguity."""
        sent = 0
        with closing(sqlite3.connect(self.path, timeout=30)) as c:
            c.row_factory = sqlite3.Row
            keys = [r[0] for r in c.execute("SELECT case_id FROM cases WHERE group_state='sent' AND reply_status='open' AND escalation_state='none' AND due_at<=? ORDER BY due_at,case_id", (self.clock(),))]
            for key in keys:
                c.execute('BEGIN IMMEDIATE')
                row = c.execute("SELECT * FROM cases WHERE case_id=? AND reply_status='open' AND escalation_state='none' AND due_at<=?", (key, self.clock())).fetchone()
                if row is None:
                    c.rollback()
                    continue
                text = (f"{row['greeting']}, пожалуйста, уточни или подтверди вопрос из Hermes / БАБЛОМАТ:"
                        f"\n\n{row['question']}\n\nОбсуждение: https://t.me/c/{GROUP[4:]}/{row['group_message_id']}"
                        f"\n[case:{key}]")
                c.execute("UPDATE cases SET escalation_state='sending',escalation_text=? WHERE case_id=?", (text, key))
                c.commit()
                payload = {'chat_id': ELENA, 'text': text, 'disable_notification': False}
                result = self._deliver(c, key, 'escalation', payload)
                c.execute("UPDATE cases SET escalation_state='sent',escalation_message_id=?,escalation_sent_at=? WHERE case_id=?",
                          (result['message_id'], result['date'], key))
                c.commit()
                sent += 1
        return sent

    def __call__(self, text):
        # Never migrate, resend, or create timers for historical private questions,
        # including ambiguous attempts. The old receipts and cursor stay untouched.
        legacy = self.home / 'cash-ledger' / 'reply-deliveries.db'
        if legacy.exists():
            old_key = hashlib.sha256(('private-review:' + OWNER + ':' + text).encode()).hexdigest()
            with closing(sqlite3.connect(legacy.resolve().as_uri() + '?mode=ro', uri=True)) as old:
                if old.execute('SELECT 1 FROM receipts WHERE key=?', (old_key,)).fetchone():
                    return None
        key = hashlib.sha256(text.encode()).hexdigest()
        with closing(sqlite3.connect(self.path, timeout=30)) as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT group_state FROM cases WHERE case_id=?', (key,)).fetchone()
            if row:
                if row[0] == 'sent':
                    return key
                raise RuntimeError('Prior group review delivery is uncertain; refusing duplicate')
            greeting = GREETINGS[int(key[:8], 16) % len(GREETINGS)]
            rendered = f'{greeting}, помоги уточнить:\n{text}\n\n[case:{key}]'
            c.execute('INSERT INTO cases(case_id,question,greeting,group_text,group_state) VALUES(?,?,?,?,?)',
                      (key, text, greeting, rendered, 'sending'))
            c.commit()
            payload = {'chat_id': GROUP, 'text': rendered, 'disable_notification': False,
                       'entities': [{'type': 'text_mention', 'offset': 0,
                                     'length': len(greeting.encode('utf-16-le')) // 2,
                                     'user': {'id': int(ELENA)}}]}
            result = self._deliver(c, key, 'group', payload)
            sent_at = max(float(result['date']), self.clock())
            c.execute("UPDATE cases SET group_state='sent',group_message_id=?,group_sent_at=?,due_at=? WHERE case_id=?",
                      (result['message_id'], sent_at, sent_at + 21600, key))
            c.commit()
            return key
