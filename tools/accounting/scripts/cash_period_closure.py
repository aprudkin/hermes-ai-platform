"""Recipient-scoped confirmation checkpoints, separate from lifetime accruals."""
import json
import os
from datetime import date


SCHEMA = '''CREATE TABLE IF NOT EXISTS period_closures(
    confirmation_source_row_id INTEGER NOT NULL,
    confirmation_message_id TEXT NOT NULL,
    report_source_row_id INTEGER NOT NULL,
    report_message_id TEXT NOT NULL,
    confirmer_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    recipient_kind TEXT NOT NULL,
    recipient_key TEXT NOT NULL,
    recipient_name TEXT NOT NULL,
    register_key TEXT NOT NULL,
    period_start TEXT,
    period_end TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    PRIMARY KEY(confirmation_source_row_id,recipient_kind),
    UNIQUE(recipient_kind,recipient_key,register_key,report_source_row_id))'''


def confirm(ledger, *, confirmation_source_row_id, confirmation_message_id,
            report_source_row_id, report_message_id, confirmer_id, timestamp,
            recipient_kind, recipient_key, recipient_name, period_start, period_end,
            evidence=None):
    from cash_ledger_monitor import _display_date
    if not confirmer_id or str(confirmer_id) != os.environ.get('BABLOMAT_ELENA_ID'):
        raise PermissionError('Period closure requires the authorized confirmer')
    if recipient_kind not in ('model', 'operator'):
        raise ValueError('Only a model (with agency) or an operator may be confirmed')
    if (not confirmation_message_id or not report_message_id
            or report_source_row_id >= confirmation_source_row_id):
        raise ValueError('Exact earlier report and confirmation references are required')
    date.fromisoformat(period_end)
    if period_start is not None and date.fromisoformat(period_start) > date.fromisoformat(period_end):
        raise ValueError('Invalid closure period')
    key = recipient_key.strip().casefold()
    with ledger._connection() as c:
        c.execute('BEGIN IMMEDIATE')
        prior = c.execute('SELECT * FROM period_closures WHERE confirmation_source_row_id=? AND recipient_kind=?',
                          (confirmation_source_row_id, recipient_kind)).fetchone()
        if prior:
            if (prior['recipient_key'], prior['report_source_row_id'], prior['report_message_id'],
                prior['confirmation_message_id'], prior['period_end']) != (
                    key, report_source_row_id, str(report_message_id), str(confirmation_message_id), period_end) or (period_start is not None and period_start != prior['period_start']):
                raise ValueError('Confirmation was already linked to a different report')
            return json.loads(prior['evidence_json'])['notice']
        report = c.execute('SELECT * FROM messages WHERE source_row_id=?', (report_source_row_id,)).fetchone()
        if report is None and c.execute("SELECT 1 FROM sqlite_master WHERE name='finance_checks'").fetchone():
            finance = c.execute('SELECT * FROM finance_checks WHERE source_row_id=?', (report_source_row_id,)).fetchone()
            report = finance_report(finance) if finance else None
        if report is None and recipient_kind == 'operator':
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='compact_sources'").fetchone():
                compact = c.execute("SELECT * FROM compact_sources WHERE source_row_id=? AND status='operator_accrual'",
                                    (report_source_row_id,)).fetchone()
                if compact:
                    report = dict(compact, accounting_date=max(json.loads(compact['dates_json'])), check_status='ok')
        if report is None or report['check_status'] != 'ok' or str(report['platform_message_id']) != str(report_message_id):
            raise ValueError('Report is not a verified accounting source')
        if report['accounting_date'] != period_end:
            raise ValueError('Period end must match the exact report')
        if 'register_name' in report.keys() and report['register_name']:
            newer = c.execute('''SELECT 1 FROM messages WHERE register_name=? AND accounting_date=?
                AND source_row_id>? AND source_row_id<?''', (report['register_name'], period_end,
                report_source_row_id, confirmation_source_row_id)).fetchone()
            if newer:
                raise ValueError('The confirmed source has been superseded')
        register = report['register_name'] if 'register_name' in report.keys() else None
        if not register:
            from cash_compact_formats import parse_compact
            compact = parse_compact(report['raw_content'], report['timestamp'])
            register = compact.name if compact else None
        if not register:
            raise ValueError('The register scope is not established')
        table = recipient_kind + 's'
        names = [r[0] for r in c.execute(f'SELECT {recipient_kind}_name FROM {table} WHERE source_row_id=?',
                                        (report_source_row_id,))]
        if recipient_kind == 'operator' and c.execute("SELECT 1 FROM sqlite_master WHERE name='compact_operator_days'").fetchone():
            names += [r['operator_name'] for r in ledger._compact_operator_rows(0, report_source_row_id + 1)
                      if r['source_row_id'] == report_source_row_id]
        if 'recipient_kind' in report.keys() and report['recipient_kind'] == recipient_kind:
            names.append(report['recipient_name'])
        if not any(name.casefold() == key for name in names):
            raise ValueError('Recipient does not belong to the confirmed report')
        cutoff = max(ledger._closure_cutoff(recipient_kind, key, confirmation_source_row_id, register),
                     ledger._period_cutoff(confirmation_source_row_id),
                     c.execute(f'SELECT COALESCE(MAX(command_source_row_id),0) FROM {recipient_kind}_payouts WHERE {recipient_kind}_key=? AND command_source_row_id<?',
                               (key, confirmation_source_row_id)).fetchone()[0])
        if report_source_row_id <= cutoff:
            raise ValueError('Report already belongs to a closed period')
        if period_start is None and cutoff:
            days = [r['accounting_date'] for r in c.execute(f'''SELECT m.accounting_date,o.{recipient_kind}_name AS name
                FROM messages m JOIN {table} o USING(source_row_id)
                WHERE source_row_id>? AND source_row_id<=?''', (cutoff, report_source_row_id))
                if r['name'].casefold() == key]
            if recipient_kind == 'operator':
                days += [r['accounting_date'] for r in ledger._compact_operator_rows(cutoff, report_source_row_id+1)
                         if r['operator_name'].casefold() == key]
            period_start = min(days) if days else None
        label = 'Модель' if recipient_kind == 'model' else 'Оператор'
        lines = ['**Закрытие периода:**', f'{label}: {recipient_name}',
                 f'С: {_display_date(period_start)}' if period_start else 'Начало периода: не установлено',
                 f'По: {_display_date(period_end)}', 'Считаю выплату сделанной. Начат новый период.']
        notice = '\n'.join(lines)
        audit = dict(evidence or {}, notice=notice, report_raw_content=report['raw_content'])
        kinds = (recipient_kind, 'agency') if recipient_kind == 'model' else (recipient_kind,)
        for kind in kinds:
            c.execute('INSERT INTO period_closures VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                      (confirmation_source_row_id, str(confirmation_message_id), report_source_row_id,
                       str(report_message_id), str(confirmer_id), timestamp, kind, key, recipient_name, register.casefold(),
                       period_start, period_end, json.dumps(audit, ensure_ascii=False)))
    return notice


def finance_report(row):
    import re
    from datetime import datetime
    from cash_compact_formats import parse_compact, canonical_name
    if ('platform_message_id' not in row.keys() or 'timestamp' not in row.keys()
            or row['status'] != 'ok' or not row['platform_message_id']):
        return None
    compact = parse_compact(row['raw_content'], row['timestamp'])
    period = re.search(r'^Период:\s*(\d{2}\.\d{2}\.\d{4})\s*[—–-]\s*(\d{2}\.\d{2}\.\d{4})\s*$', row['raw_content'], re.M | re.I)
    try:
        dates = tuple(datetime.strptime(d,'%d.%m.%Y').date().isoformat() for d in period.groups()) if period else (compact.dates if compact else ())
    except ValueError:
        return None
    if not dates or dates[0] > dates[-1]:
        return None  # Receipt day is not the financial period's end.
    operator = re.search(r'^Оператор:\s*([^\d\n]+?)\s*$',row['raw_content'],re.M | re.I)
    register = canonical_name(row['model_name'])
    name = operator[1].strip() if operator else register
    return dict(row, register_name=register, accounting_date=dates[-1],
                period_start=dates[0], check_status='ok', recipient_name=name,
                recipient_kind='operator' if operator else 'model')


def _report_text(content):
    from cash_message_context import message_body
    from cash_ledger_monitor import SENDER_RE
    lines = message_body(content).splitlines()
    if lines and SENDER_RE.fullmatch(lines[0]):
        lines = lines[1:]
    return '\n'.join(lines).strip()


def process_confirmation(ledger, row, *, chat_id, native=None, review_sender=None):
    import re
    from cash_message_context import message_body, REPLY_CONTEXT
    from cash_ledger_monitor import SENDER_RE
    content = row['content'] or ''
    lines = message_body(content).splitlines()
    author = SENDER_RE.fullmatch(lines[0]) if lines else None
    sender_id = native.get('sender_id') if native else (row['sender_id'] if 'sender_id' in row.keys() else None)
    is_bot = native.get('sender_is_bot') if native else (row['sender_is_bot'] if 'sender_is_bot' in row.keys() else True)
    if (not author or str(sender_id) != os.environ.get('BABLOMAT_ELENA_ID')
            or author.group(2) != str(sender_id) or is_bot):
        return None
    if native and (native.get('sender_is_bot') is not False
                   or _report_text(content) != (native.get('text') or '').strip()):
        return None
    body = '\n'.join(lines[1:]).strip()
    explicit = re.fullmatch(r'подтверждаю\s+выплату\s+(модели|оператору)\s+([^\n]+?)[.!]*', body, re.IGNORECASE)
    generic = re.fullmatch(r'(?:тут\s+)?(?:да[,\s]*)?(?:вс[её]\s+)?верно(?:[,\s]+к\s+выдаче)?[\s.!🙌✅👍]*', body, re.IGNORECASE)
    if not explicit and not generic:
        return None
    target = native.get('reply_to_message_id') if native else (row['reply_to_message_id'] if 'reply_to_message_id' in row.keys() else None)
    if not target:
        return '' if explicit else None
    if native and native.get('reply_to_chat_id') != chat_id:
        return ''
    if 'reply_to_chat_id' in row.keys() and row['reply_to_chat_id'] not in (None, chat_id):
        return ''
    def pending():
        if review_sender is not None:
            base = f"https://t.me/c/{chat_id.removeprefix('-100')}/" if chat_id.startswith('-100') else 'сообщение '
            review_sender(f"БАБЛОМАТ — подтверждение выплаты, {base}{row['platform_message_id']}\n"
                f"Отчёт: {base}{target}\nНе удалось однозначно установить получателя или период выплаты. "
                'Уточни точный отчёт и границы периода; выплата не закрыта.')
        return ''

    context = REPLY_CONTEXT.match(content)
    quote = context.group(1) if context else None
    with ledger._connection() as c:
        reports = list(c.execute('SELECT * FROM messages WHERE source_row_id<?', (row['id'],)))
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='compact_sources'").fetchone():
            reports += [dict(r, accounting_date=max(json.loads(r['dates_json'])), check_status='ok')
                        for r in c.execute("SELECT * FROM compact_sources WHERE source_row_id<? AND status='operator_accrual'", (row['id'],))]
    finance_rows = []
    with ledger._connection() as c:
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='finance_checks'").fetchone():
            finance_rows = c.execute('SELECT * FROM finance_checks WHERE source_row_id<?', (row['id'],)).fetchall()
            reports += [r for f in finance_rows if (r := finance_report(f)) is not None]
    if target:
        reports = [r for r in reports if str(r['platform_message_id']) == str(target)]
        if native and native.get('reply_to_text'):
            reports = [r for r in reports if _report_text(native['reply_to_text']) == _report_text(r['raw_content'])]
        if quote:
            reports = [r for r in reports if _report_text(quote) in _report_text(r['raw_content'])]

    if len(reports) != 1:
        known_finance = any('platform_message_id' in f.keys() and str(f['platform_message_id']) == str(target) for f in finance_rows)
        return pending() if explicit or known_finance else ''
    report = reports[0]
    if explicit:
        kind = 'model' if explicit[1].casefold() == 'модели' else 'operator'
        name = explicit[2].strip()
    else:
        from cash_compact_formats import parse_compact
        parsed = parse_compact(report['raw_content'], report['timestamp'])
        if 'recipient_kind' in report.keys():
            kind, name = report['recipient_kind'], report['recipient_name']
        elif parsed and parsed.kind == 'operator' and not parsed.review_lines:
            kind, name = 'operator', parsed.operator
        else:
            return None  # Approving cash arithmetic alone is not approving a payout.
    try:
        return ledger.confirm_period_closure(
            confirmation_source_row_id=row['id'], confirmation_message_id=row['platform_message_id'],
            report_source_row_id=report['source_row_id'], report_message_id=report['platform_message_id'],
            confirmer_id=author.group(2), timestamp=row['timestamp'], recipient_kind=kind,
            recipient_key=name, recipient_name=name,
            period_start=report['period_start'] if 'period_start' in report.keys() else None, period_end=report['accounting_date'],
            evidence={'confirmation_raw_content': content, 'reply_to_message_id': str(target) if target else None,
                      'reply_to_chat_id': chat_id, 'quote': quote,
                      'native_input': native, 'link_kind': 'native'})
    except ValueError as exc:
        if str(exc) == 'Report already belongs to a closed period':
            return ''
        return pending()
