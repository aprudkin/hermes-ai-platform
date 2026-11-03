#!/usr/bin/env python3
"""Read-only daily Бабломат source/answer digest; never changes accounting."""
import argparse
import hashlib
import json
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

CHAT = os.environ.get('BABLOMAT_CHAT_ID', '')
MSK = ZoneInfo('Europe/Moscow')


def _tables(c):
    return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def collect_digest(home, *, end, hours=24, chat_id=CHAT):
    if not chat_id:
        raise ValueError('An explicit Bablomat chat ID is required')
    home = Path(home)
    start = end - hours * 3600
    with closing(sqlite3.connect(f'file:{home / "state.db"}?mode=ro', uri=True)) as c:
        c.row_factory = sqlite3.Row
        raw = c.execute('''SELECT m.id,m.role,m.content,m.timestamp,m.platform_message_id
            FROM messages m JOIN sessions s ON s.id=m.session_id
            WHERE s.chat_id=? AND m.active=1 AND m.role IN ('user','assistant')
            ORDER BY m.id''', (chat_id,)).fetchall()
    sources = {}
    history = []
    for row in raw:
        r = dict(row)
        if r['role'] == 'user':
            mid = r['platform_message_id'] or 'row:' + str(r['id'])
            sources[str(mid)] = {'message_id':str(mid),'source_row_id':r['id'],
                'text':r['content'] or '', 'timestamp':r['timestamp']}
        elif r['content'] and start <= r['timestamp'] < end:
            history.append({'source_row_id':r['id'],'text':r['content'], 'timestamp':r['timestamp']})
    messages = sorted((r for r in sources.values() if start <= r['timestamp'] < end),
                      key=lambda r:(r['timestamp'],r['source_row_id']))
    receipts = []
    metadata = {}
    struck = set()
    path = home / 'cash-ledger' / 'reply-deliveries.db'
    if path.exists():
        with closing(sqlite3.connect(f'file:{path}?mode=ro', uri=True)) as c:
            c.row_factory = sqlite3.Row
            tables = _tables(c)
            if 'delivery_metadata' in tables:
                metadata = {r['key']:dict(r) for r in c.execute('SELECT * FROM delivery_metadata WHERE chat_id=?',(chat_id,))}
            if 'superseded_notices' in tables:
                struck = {r[0] for r in c.execute("SELECT old_message_id FROM superseded_notices WHERE chat_id=? AND status='struck'",(chat_id,))}
            for row in c.execute("SELECT rowid,* FROM receipts WHERE status='sent' ORDER BY rowid"):
                r = dict(row)
                key = hashlib.sha256(f"{chat_id}:{r['source_message_id']}:{r['text']}".encode()).hexdigest()
                if key == r['key']:
                    receipts.append(r)
    by_id = {}
    versions = {}
    for r in receipts:
        versions.setdefault(r['sent_message_id'], []).append(r['text'])
        by_id[r['sent_message_id']] = r
    answers = []
    unknown_old = 0
    for mid,r in by_id.items():
        source = sources.get(str(r['source_message_id']))
        context_source = source
        parent_id = r['source_message_id']
        visited = set()
        while context_source is None and parent_id in by_id and parent_id not in visited:
            visited.add(parent_id)
            parent_id = by_id[parent_id]['source_message_id']
            context_source = sources.get(str(parent_id))
        m = metadata.get(r['key'])
        sent_at = m['sent_at'] if m else None
        if sent_at is not None:
            include = start <= sent_at < end
        else:
            include = context_source is not None and start <= context_source['timestamp'] < end
            if not include:
                unknown_old += 1
        if not include:
            continue
        old_bot = by_id.get(r['source_message_id'])
        answers.append({'message_id':mid,'source_message_id':r['source_message_id'],
            'source_text':source['text'] if source else (old_bot['text'] if old_bot else None),
            'source_type':'user' if source else ('bot' if old_bot else 'unavailable'),
            'text':r['text'],'sent_at':sent_at,'time_basis':'delivery_metadata' if m else 'source_context_only',
            'struck':mid in struck,'previous_versions':list(dict.fromkeys(versions[mid][:-1]))})
    answers.sort(key=lambda r:(r['sent_at'] if r['sent_at'] is not None else end,r['message_id']))
    existing_texts = {r['text'] for r in receipts}
    history = [r for r in history if r['text'] not in existing_texts]
    return {'chat_id':chat_id,'start':start,'end':end,'messages':messages,'answers':answers,
            'session_answers_unverified':history,'legacy_without_time_outside_window':unknown_old,
            'counts':{'messages':len(messages),'answers':len(answers),'session_answers_unverified':len(history)}}


def _date(timestamp):
    d=datetime.fromtimestamp(timestamp, MSK)
    weekday=('пн','вт','ср','чт','пт','сб','вс')[d.weekday()]
    return d.strftime('%d.%m') + f' ({weekday}) ' + d.strftime('%H:%M')


def _link(chat_id, message_id):
    if str(chat_id).startswith('-100') and str(message_id).isdigit():
        return f'https://t.me/c/{str(chat_id)[4:]}/{message_id}'
    return 'Telegram-ссылка отсутствует в сохранённых данных'


def export_digest(home, data):
    directory=Path(home)/'cash-ledger'/'digests'
    directory.mkdir(parents=True,exist_ok=True)
    stamp=datetime.fromtimestamp(data['end'],MSK).strftime('%Y%m%d_%H%M%S')
    path=directory/f'bablomat_{stamp}.txt'
    lines=['БАБЛОМАТ — ежедневная сводка', f"Период: {_date(data['start'])} — {_date(data['end'])} МСК",
           f"Сообщений участников: {data['counts']['messages']}; моих ответов в сводке: {data['counts']['answers']}.",'',
           'ИСХОДНЫЕ СООБЩЕНИЯ ЗА СУТКИ','']
    for r in data['messages']:
        lines += [f"Сообщение №{r['message_id']} — {_date(r['timestamp'])} МСК", _link(data['chat_id'],r['message_id']),r['text'],'', '---','']
    if not data['messages']:
        lines.append('За этот период новых сообщений участников не сохранено.')
    lines += ['', 'МОИ ОТВЕТЫ И ИСПРАВЛЕНИЯ','']
    for r in data['answers']:
        timing=_date(r['sent_at'])+' МСК' if r['sent_at'] is not None else 'точное время отправки в старой квитанции отсутствует'
        lines += [f"Ответ №{r['message_id']} — {timing}", _link(data['chat_id'],r['message_id']),
                  f"Ответ на сообщение №{r['source_message_id']}",_link(data['chat_id'],r['source_message_id']),
                  'Исходный текст:',r['source_text'] if r['source_text'] is not None else 'Исходный текст недоступен в сохранённых данных.',
                  'Мой ответ'+(' (ЗАЧЁРКНУТ в чате):' if r['struck'] else ':'),r['text']]
        if r['previous_versions']:
            lines += ['Ранее сохранённые версии этого же сообщения:', *r['previous_versions']]
        lines += ['', '---','']
    if not data['answers']:
        lines.append('Подтверждённых ответов за этот период не найдено.')
    if data['session_answers_unverified']:
        lines += ['', 'ТЕКСТЫ ОТВЕТОВ ИЗ ИСТОРИИ СЕССИИ БЕЗ КВИТАНЦИИ ОТПРАВКИ','']
        for r in data['session_answers_unverified']:
            lines += [_date(r['timestamp'])+' МСК',r['text'],'']
    if any(r['sent_at'] is None for r in data['answers']) or data['legacy_without_time_outside_window']:
        lines += ['', 'ПРИМЕЧАНИЕ О СТАРЫХ ДАННЫХ',
                  'В старых квитанциях не сохранялось время отправки. Для них показаны ответы к исходным сообщениям этого периода; точное время не выдумано. Старые ответы к более ранним сообщениям без времени отправки нельзя уверенно отнести к этим суткам. Новые квитанции сохраняют время отправки.']
    path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    path.with_suffix('.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return path


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--home',type=Path,default=Path(os.environ['HERMES_HOME']) if os.environ.get('HERMES_HOME') else None, required=not bool(os.environ.get('HERMES_HOME')))
    p.add_argument('--end-at',help='ISO timestamp; optional read-only audit window end')
    p.add_argument('--chat-id', default=CHAT, required=not bool(CHAT))
    args=p.parse_args(argv)
    end=datetime.fromisoformat(args.end_at).timestamp() if args.end_at else time.time()
    data=collect_digest(args.home,end=end,chat_id=args.chat_id)
    path=export_digest(args.home,data)
    print('**БАБЛОМАТ — сводка за сутки**')
    print(f"{_date(data['start'])} — {_date(data['end'])} МСК")
    print(f"Сообщений участников: {data['counts']['messages']}. Моих ответов в сводке: {data['counts']['answers']}.")
    print('В файле — полные исходные сообщения, мои ответы, исправления и ссылки на них.')
    print('MEDIA:'+str(path.resolve()))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
