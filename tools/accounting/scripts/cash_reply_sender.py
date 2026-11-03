"""Strict Telegram reply delivery with durable receipts; never fall back to a standalone post."""
import hashlib
import html
import json
import re
import sqlite3
import time
import urllib.request
from contextlib import closing
from pathlib import Path


class ReplySender:
    def __init__(self, home: Path, chat_id: str, *, post=None, edit=None):
        self.home = Path(home)
        self.chat_id = str(chat_id)
        self.post = post or self._post
        self.edit = edit or self._edit
        self.delete = self._delete
        self.verify_absent = self._verify_absent
        self.path = self.home / 'cash-ledger' / 'reply-deliveries.db'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as c:
            c.execute('CREATE TABLE IF NOT EXISTS receipts(key TEXT PRIMARY KEY,status TEXT,source_message_id INTEGER,sent_message_id INTEGER,text TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS delivery_metadata(key TEXT PRIMARY KEY,chat_id TEXT NOT NULL,source_message_id INTEGER NOT NULL,sent_message_id INTEGER NOT NULL,sent_at REAL NOT NULL)')
            c.commit()

    def _post(self, payload):
        from dotenv import dotenv_values
        token = dotenv_values(self.home / '.env').get('TELEGRAM_BOT_TOKEN')
        if not token:
            raise RuntimeError('Telegram token unavailable in this profile')
        request = urllib.request.Request(
            'https://api.telegram.org/bot' + token + '/sendMessage',
            data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                result = json.load(response)
        except Exception as exc:
            raise RuntimeError('Telegram reply delivery failed: ' + type(exc).__name__) from None
        if not result.get('ok'):
            raise RuntimeError('Telegram rejected reply delivery')
        return result['result']

    def _edit(self, payload):
        from dotenv import dotenv_values
        from urllib.error import HTTPError
        token = dotenv_values(self.home / '.env').get('TELEGRAM_BOT_TOKEN')
        if not token:
            raise RuntimeError('Telegram token unavailable')
        request = urllib.request.Request('https://api.telegram.org/bot' + token + '/editMessageText',
            data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                result = json.load(response)
        except HTTPError as exc:
            result = json.loads(exc.read())
            if 'message is not modified' in str(result.get('description','')).lower():
                return {'not_modified': True}
            raise RuntimeError('Telegram rejected strikethrough: ' + str(result.get('description',''))) from None
        except Exception as exc:
            raise RuntimeError('Telegram strikethrough failed: ' + type(exc).__name__) from None
        if not result.get('ok'):
            raise RuntimeError('Telegram rejected strikethrough')
        return result['result']

    def _delete_enabled(self):
        try:
            policy = json.loads((self.home / 'cash-ledger' / 'correction-cleanup.json').read_text())
        except (OSError, ValueError, TypeError):
            return False
        return (isinstance(policy, dict) and policy.get('enabled') is True
                and str(policy.get('chat_id')) == self.chat_id
                and policy.get('mode') == 'delete_superseded_bot_notice')

    def _delete(self, payload):
        from dotenv import dotenv_values
        from urllib.error import HTTPError
        token = dotenv_values(self.home / '.env').get('TELEGRAM_BOT_TOKEN')
        if not token:
            raise RuntimeError('Telegram token unavailable')
        request = urllib.request.Request('https://api.telegram.org/bot' + token + '/deleteMessage',
            data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                result = json.load(response)
        except HTTPError as exc:
            result = json.loads(exc.read())
            if 'message to delete not found' in str(result.get('description', '')).lower():
                return {'already_absent': True}
            raise RuntimeError('Telegram rejected notice deletion: ' + str(result.get('description', ''))) from None
        except Exception as exc:
            raise RuntimeError('Telegram deletion uncertain: ' + type(exc).__name__) from None
        return result

    def _verify_absent(self, message_id, original_text):
        # Bot API has no getMessage. An identical-content edit is a no-op for an
        # existing struck notice; its exact not-found response proves absence.
        rendered = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', html.escape(original_text))
        try:
            self.edit({'chat_id': self.chat_id, 'message_id': message_id,
                       'text': '<s>' + rendered + '</s>', 'parse_mode': 'HTML'})
        except RuntimeError as exc:
            if 'message to edit not found' in str(exc).lower():
                return True
            raise
        return False

    def delete_superseded_message(self, old_message_id, correction_message_id):
        if not self._delete_enabled():
            raise PermissionError('Automatic deletion is not authorized for this chat')
        if old_message_id == correction_message_id:
            raise ValueError('Replacement cannot delete itself')
        with closing(sqlite3.connect(self.path, timeout=30)) as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('''CREATE TABLE IF NOT EXISTS superseded_deletions(
                chat_id TEXT, old_message_id INTEGER, correction_message_id INTEGER,
                original_text TEXT, correction_text TEXT, status TEXT,
                result_json TEXT, verified_at REAL,
                PRIMARY KEY(chat_id,old_message_id,correction_message_id))''')
            def receipt(mid):
                for row in c.execute('SELECT key,status,source_message_id,text FROM receipts WHERE sent_message_id=?', (mid,)):
                    expected = hashlib.sha256((self.chat_id + ':' + str(row[2]) + ':' + row[3]).encode()).hexdigest()
                    if row[0] == expected and row[1] == 'sent':
                        return row
                raise ValueError('No verified bot receipt for this exact chat/message')
            old = receipt(old_message_id)
            correction = receipt(correction_message_id)
            if correction[2] != old_message_id or not correction[3].lstrip().startswith('**Исправление'):
                raise ValueError('Replacement is not a verified correction replying to the old bot notice')
            prior = c.execute('SELECT status FROM superseded_deletions WHERE chat_id=? AND old_message_id=? AND correction_message_id=?',
                (self.chat_id, old_message_id, correction_message_id)).fetchone()
            if prior and prior[0] == 'deleted':
                return
            if prior and prior[0] != 'delete_acknowledged':
                raise RuntimeError('Prior notice deletion is uncertain; refusing blind retry')
            if not prior:
                c.execute('INSERT INTO superseded_deletions VALUES(?,?,?,?,?,?,NULL,NULL)',
                    (self.chat_id, old_message_id, correction_message_id, old[3], correction[3], 'pending'))
            c.commit()  # Preserve both originals before any external deletion.
            if not prior:
                try:
                    result = self.delete({'chat_id': self.chat_id, 'message_id': old_message_id})
                    if not ((result.get('ok') is True and result.get('result') is True)
                            or result.get('already_absent') is True):
                        raise RuntimeError('Deletion did not return verified success')
                except Exception as exc:
                    c.execute("UPDATE superseded_deletions SET status='uncertain',result_json=? WHERE chat_id=? AND old_message_id=? AND correction_message_id=?",
                        (json.dumps({'error_type': type(exc).__name__}), self.chat_id, old_message_id, correction_message_id))
                    c.commit()
                    raise
                c.execute("UPDATE superseded_deletions SET status='delete_acknowledged',result_json=? WHERE chat_id=? AND old_message_id=? AND correction_message_id=?",
                    (json.dumps(result), self.chat_id, old_message_id, correction_message_id))
                c.commit()
            if self.verify_absent(old_message_id, old[3]) is not True:
                raise RuntimeError('Old notice absence not verified; replacement remains sent')
            c.execute("UPDATE superseded_deletions SET status='deleted',verified_at=? WHERE chat_id=? AND old_message_id=? AND correction_message_id=?",
                (time.time(), self.chat_id, old_message_id, correction_message_id))
            c.execute('CREATE TABLE IF NOT EXISTS superseded_notices(chat_id TEXT,old_message_id INTEGER,correction_message_id INTEGER,original_text TEXT,status TEXT,PRIMARY KEY(chat_id,old_message_id,correction_message_id))')
            c.execute('INSERT OR REPLACE INTO superseded_notices VALUES(?,?,?,?,?)',
                (self.chat_id, old_message_id, correction_message_id, old[3], 'deleted'))
            c.commit()

    def _finish_correction(self, old_message_id, correction_message_id, text):
        if not text.lstrip().startswith('**Исправление'):
            return
        with closing(sqlite3.connect(self.path)) as c:
            old_receipts = c.execute('SELECT key,status,source_message_id,text FROM receipts WHERE sent_message_id=?', (old_message_id,)).fetchall()
        verified_old = any(row[1] == 'sent' and row[0] == hashlib.sha256(
            (self.chat_id + ':' + str(row[2]) + ':' + row[3]).encode()).hexdigest() for row in old_receipts)
        if verified_old:
            if self._delete_enabled():
                self.delete_superseded_message(old_message_id, correction_message_id)
            else:
                self.strike_message(old_message_id, correction_message_id)

    def strike_message(self, old_message_id: int, correction_message_id: int):
        with closing(sqlite3.connect(self.path)) as c:
            c.execute('CREATE TABLE IF NOT EXISTS superseded_notices(chat_id TEXT,old_message_id INTEGER,correction_message_id INTEGER,original_text TEXT,status TEXT,PRIMARY KEY(chat_id,old_message_id,correction_message_id))')
            already = c.execute('SELECT status FROM superseded_notices WHERE chat_id=? AND old_message_id=? AND correction_message_id=?',
                (self.chat_id,old_message_id,correction_message_id)).fetchone()
            if already and already[0] in ('struck', 'deleted'):
                return
            def find_receipt(message_id):
                for row in c.execute('SELECT key,status,source_message_id,sent_message_id,text FROM receipts WHERE sent_message_id=?',(message_id,)):
                    key = hashlib.sha256((self.chat_id+':'+str(row[2])+':'+row[4]).encode()).hexdigest()
                    if row[0] == key and row[1] == 'sent':
                        return row
                raise ValueError('No verified bot receipt for this chat/message')
            old = find_receipt(old_message_id)
            correction = find_receipt(correction_message_id)
            if correction[2] != old_message_id or 'Исправление' not in correction[4]:
                raise ValueError('Correction is not a verified reply to the old notice')
            rendered = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', html.escape(old[4]))
            plain = re.sub(r'\*\*(.*?)\*\*', r'\1', old[4])
            payload = {'chat_id':self.chat_id,'message_id':old_message_id,
                       'text':'<s>'+rendered+'</s>','parse_mode':'HTML'}
            def verify(result):
                if result.get('not_modified'):
                    return
                full_length = len(plain.encode('utf-16-le')) // 2
                struck = any(e.get('type')=='strikethrough' and e.get('offset')==0 and e.get('length')==full_length
                             for e in result.get('entities',[]))
                if str(result.get('chat',{}).get('id')) != self.chat_id or result.get('message_id') != old_message_id or result.get('text') != plain or not struck:
                    raise RuntimeError('Strikethrough target/content could not be verified')
            verify(self.edit(payload))
            verify(self.edit(payload))
            c.execute('INSERT OR REPLACE INTO superseded_notices VALUES(?,?,?,?,?)',
                (self.chat_id,old_message_id,correction_message_id,old[4],'struck'))
            c.commit()

    def __call__(self, source_message_id: str, text: str):
        message_id = int(source_message_id)
        if message_id <= 0:
            raise ValueError('Invalid source message ID')
        key = hashlib.sha256((self.chat_id + ':' + str(message_id) + ':' + text).encode()).hexdigest()
        rendered = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', html.escape(text))
        payload = {'chat_id': self.chat_id, 'text': rendered, 'parse_mode': 'HTML',
                   'reply_parameters': {'message_id': message_id, 'allow_sending_without_reply': False}}
        with closing(sqlite3.connect(self.path, timeout=30)) as c:
            c.execute('BEGIN IMMEDIATE')
            # A source gets one optional-format reply, including when combined with
            # its cash/finance notice. A renderer change must not bypass receipts.
            marker = 'Необязательный короткий формат'
            if marker in text:
                previous = c.execute('SELECT key,status,text FROM receipts WHERE source_message_id=? AND instr(text,?)>0',
                    (message_id, marker)).fetchall()
                for old_key, status, old_text in previous:
                    if old_key != hashlib.sha256((self.chat_id + ':' + str(message_id) + ':' + old_text).encode()).hexdigest():
                        continue
                    if status == 'sent':
                        return
                    raise RuntimeError('Prior guidance delivery is uncertain; refusing duplicate reply')
            receipt = c.execute('SELECT status,sent_message_id FROM receipts WHERE key=?', (key,)).fetchone()
            if receipt:
                if receipt[0] == 'sent':
                    c.commit()
                    self._finish_correction(message_id, receipt[1], text)
                    return
                raise RuntimeError('Prior delivery is uncertain; refusing duplicate reply')
            c.execute('INSERT INTO receipts VALUES(?,\'pending\',?,NULL,?)', (key,message_id,text))
            c.commit()
            result = self.post(payload)
            if (str(result.get('chat',{}).get('id')) != self.chat_id
                    or result.get('reply_to_message',{}).get('message_id') != message_id
                    or not result.get('message_id')):
                raise RuntimeError('Telegram did not confirm the required reply target')
            if self._delete_enabled() and text.lstrip().startswith('**Исправление'):
                expected_text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
                if result.get('text') != expected_text:
                    raise RuntimeError('Replacement text not verified; refusing deletion of old notice')
            c.execute("UPDATE receipts SET status='sent',sent_message_id=? WHERE key=?", (result['message_id'],key))
            c.execute('INSERT OR IGNORE INTO delivery_metadata VALUES(?,?,?,?,?)',
                (key,self.chat_id,message_id,result['message_id'],float(result.get('date') or time.time())))
            c.commit()
        self._finish_correction(message_id, result['message_id'], text)
