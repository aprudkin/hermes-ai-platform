"""Deterministic, opt-in Bablomat compact normalization; never rewrites sources.

This module has no transport, config writes, or live database initialization.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re

NUMBER = r'\d+(?:[.,]\d{1,2})?'
METHOD = r'(?:CashApp|Cash|Venmo|Zelle|PayPal|Apple\s+Pay)'
SENDER = re.compile(r'^\[[^|\]]+\|\d+\]$')


@dataclass(frozen=True)
class Compact:
    kind: str
    name: str
    dates: tuple[str, ...]
    normalized: str
    review_lines: tuple[str, ...] = ()
    operator: str | None = None
    daily: tuple[tuple[str, str], ...] = ()
    standard: bool = True


def body_lines(content):
    return [line.strip() for line in content.splitlines()
            if line.strip() and not SENDER.fullmatch(line.strip())]


def business_day(timestamp):
    local = datetime.fromtimestamp(timestamp, ZoneInfo('America/Los_Angeles'))
    return local.date() - timedelta(days=1) if local.hour < 6 else local.date()


def resolve_dates(heading, timestamp):
    """Bare days mean the source business month, never a guessed historical month."""
    current = business_day(timestamp)
    try:
        explicit = re.fullmatch(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', heading)
        if explicit:
            day = datetime(int(explicit[3]), int(explicit[2]), int(explicit[1])).date()
        elif re.fullmatch(r'\d{1,2}', heading):
            day = current.replace(day=int(heading))
        else:
            match = re.fullmatch(r'(\d{1,2})\s*[–—-]\s*(\d{1,2})', heading)
            if not match:
                return ()
            first, last = map(int, match.groups())
            end = current.replace(day=last)
            if end > current:
                return ()
            if first <= last:
                start = end.replace(day=first)
            elif first >= 25 and last <= 7:
                previous = end.replace(day=1) - timedelta(days=1)
                start = previous.replace(day=first)
            else:
                return ()
            return tuple((start + timedelta(days=i)).isoformat() for i in range((end-start).days + 1))
        return (day.isoformat(),) if day <= current else ()
    except ValueError:
        return ()


def save_source(ledger, source_row_id, timestamp, platform_message_id, content, compact, status):
    """Audit optional sources separately, including dates that cannot be resolved."""
    import json
    with ledger._connection() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS compact_sources(
            source_row_id INTEGER PRIMARY KEY, timestamp REAL, platform_message_id TEXT,
            raw_content TEXT NOT NULL, kind TEXT, dates_json TEXT, status TEXT)''')
        c.execute('INSERT OR IGNORE INTO compact_sources VALUES(?,?,?,?,?,?,?)',
            (source_row_id, timestamp, platform_message_id, content, compact.kind,
             json.dumps(compact.dates), status))
        for no, line in enumerate(compact.review_lines, 1):
            c.execute('INSERT OR IGNORE INTO parse_reviews VALUES(?,?,?)', (source_row_id, no, line))


def canonical_name(value):
    name = ' '.join(re.findall(r'[^\W_]+', value, re.UNICODE))
    return name.capitalize() if name.isupper() or name.islower() else name


def operator_name(value):
    name = canonical_name(value).title()
    return 'Анна' if name.casefold() in ('anna', 'анна') else name


def parse_compact(content, timestamp):
    lines = body_lines(content)
    if len(lines) >= 3 and re.match(r'^Модель\s', lines[0], re.I) and (re.match(r'^(?:Опер|Оператор)\s', lines[1], re.I) or re.search(r'\sOperator$', lines[1], re.I)):
        from decimal import Decimal
        model = canonical_name(re.sub(r'^Модель\s*:?', '', lines[0], flags=re.I))
        operator = operator_name(re.sub(r'^(?:Опер|Оператор)\s+|\s+Operator$', '', lines[1], flags=re.I).strip())
        daily = []
        reviews = []
        declared_total = None
        for line in lines[2:]:
            match = re.fullmatch(rf'(\d{{1,2}}\.\d{{1,2}}\.\d{{4}})\s*\+\s*({NUMBER})\s*[^\w\d]*', line)
            total = re.fullmatch(rf'(?:Итого|Итог|Тотал|Total)\s*:?\s*({NUMBER})\s*[^\w\d]*', line, re.I)
            if match:
                resolved = resolve_dates(match[1], timestamp)
                if resolved:
                    daily.append((resolved[0], match[2]))
                else:
                    reviews.append('Дата требует уточнения: ' + match[1])
            elif total:
                declared_total = Decimal(total[1].replace(',', '.'))
            else:
                reviews.append(line)
        dates = tuple(day for day, amount in daily)
        if len(set(dates)) != len(dates) or dates != tuple(sorted(dates)):
            reviews.append('Повторяющиеся или непоследовательные даты требуют уточнения')
        if declared_total is not None and sum((Decimal(amount.replace(',', '.')) for day, amount in daily), Decimal(0)) != declared_total:
            reviews.append('Итого в источнике не совпадает со строками: ' + str(declared_total))
        if not dates:
            reviews.append('Нет однозначных дат начисления')
        return Compact('operator', model, dates, '', tuple(reviews), operator, tuple(daily), standard=False)
    lines = [line for line in lines if line.casefold() != 'финмониторинг']
    if len(lines) < 3 or not re.fullmatch(r'[\d.\s–—/-]+', lines[0]):
        return None
    name = lines[1]
    dates = resolve_dates(lines[0], timestamp)
    if not re.search(r'[^\W\d_]', name, re.UNICODE) or name.count('/') > 1:
        return Compact('cash', name, dates, '', ('Имя / модель требует уточнения: ' + name,))
    if any('%' in line and '=' in line for line in lines[2:]):
        equations = []
        previous = None
        reviews = [] if dates else ['Дата требует уточнения: ' + lines[0]]
        for line in lines[2:]:
            compact_line = re.sub(r'\s+', '', line).replace('−', '-')
            short = re.fullmatch(rf'(-?)({NUMBER})%=({NUMBER})', compact_line)
            if short and previous is not None:
                compact_line = f'{previous}{"-" if short[1] else "*"}{short[2]}%={short[3]}'
            if '=' in compact_line:
                equations.append(compact_line)
                right = compact_line.rsplit('=', 1)[-1]
                previous = right if re.fullmatch(NUMBER, right) else None
            else:
                reviews.append(line)
        return Compact('finance', name, dates,
            '\n'.join(['Финмониторинг', 'Модель: ' + name] + equations), tuple(reviews))
    if '/' in name:
        operator, model = (part.strip() for part in name.split('/', 1))
        operator, model = operator_name(operator), canonical_name(model)
        reviews = [] if dates and operator and model else ['Дата или имена требуют уточнения: ' + lines[0]]
        daily = ((dates[0], lines[2]),) if len(lines) == 3 and re.fullmatch(NUMBER, lines[2]) and len(dates) == 1 else ()
        if len(dates) > 1:
            matches = [re.fullmatch(rf'(\d{{1,2}})\s*[–—-]\s*({NUMBER})', line) for line in lines[2:]]
            if len(matches) == len(dates) and all(matches) and [int(m[1]) for m in matches] == [int(d[-2:]) for d in dates]:
                daily = tuple((day, m[2]) for day, m in zip(dates, matches))
        if not daily:
            reviews.extend(lines[2:])
        return Compact('operator', model, dates, '', tuple(reviews), operator, daily)
    if not any(re.match(r'(?:Итого|Total)\b', line, re.I) or re.fullmatch(rf'{NUMBER}\s+{METHOD}', line, re.I) for line in lines[2:]):
        return None
    if len(dates) != 1:
        return Compact('cash', name, (), '', ('Дата требует уточнения: ' + lines[0],))
    name = canonical_name(name)
    day = dates[0]
    normalized = [f'Касса {name}', datetime.fromisoformat(day).strftime('%d.%m.%Y')]
    after_total = False
    reviews = []
    for line in lines[2:]:
        total = re.fullmatch(rf'(?:Итого|Total)\s*:?\s*({NUMBER})', line, re.I)
        if total:
            if after_total:
                reviews.append(line)
                continue
            normalized.append('Итого: ' + total[1])
            after_total = True
            continue
        if not after_total:
            payment = re.fullmatch(rf'({NUMBER}(?:\s*\+\s*{NUMBER})*)\s+({METHOD})', line, re.I)
            if payment:
                amount = re.sub(r'\s+', '', payment[1])
                normalized.append(f'Client Hr/{amount} {payment[2]}')
            else:
                split = re.fullmatch(rf'({NUMBER})\s*=\s*(.+)', line)
                terms = [re.fullmatch(rf'\s*({METHOD})\s+({NUMBER})\s*', term, re.I)
                         for term in split[2].split('+')] if split else []
                if len(terms) >= 2 and all(terms):
                    from decimal import Decimal
                    amount = lambda token: Decimal(token.replace(',', '.'))
                    normalized.append(f'Client Hr/{split[1]}')
                    if sum(amount(term[2]) for term in terms) != amount(split[1]):
                        reviews.append(line)
                else:
                    reviews.append(line)
            continue
        share = re.fullmatch(rf'(Модели|Агентству)\s*:?\s*({NUMBER})', line, re.I)
        if share:
            label = 'Модели' if share[1].casefold() == 'модели' else 'Агентских'
            normalized.append(f'{label}: {share[2]}')
        else:
            operator = re.fullmatch(rf'([^\d:+=/]+?)\s+({NUMBER})', line)
            if operator and not re.fullmatch(METHOD, operator[1], re.I):
                normalized.append(f'Оператор {operator_name(operator[1])}: {operator[2]}')
            else:
                reviews.append(line)
    if not after_total:
        reviews.append('Итого ? — в источнике нет Total')
    return Compact('cash', name, (day,), '\n'.join(normalized), tuple(reviews))


def record_operator(ledger, source_row_id, timestamp, platform_message_id, content, compact):
    from cash_ledger_monitor import _amount_minor
    from dataclasses import replace
    reviews = list(compact.review_lines)
    pending = []
    with ledger._connection() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS compact_operator_days(
            source_row_id INTEGER, accounting_date TEXT, register_name TEXT,
            operator_name TEXT, amount_minor INTEGER,
            UNIQUE(register_name, accounting_date, operator_name))''')
        for day, amount in compact.daily:
            minor = _amount_minor(amount)
            report = c.execute('''SELECT source_row_id FROM messages
                WHERE lower(register_name)=lower(?) AND accounting_date=?
                ORDER BY source_row_id DESC LIMIT 1''', (compact.name, day)).fetchone()
            if report:
                existing = [r['amount_minor'] for r in c.execute(
                    'SELECT operator_name,amount_minor FROM operators WHERE source_row_id=?', (report[0],))
                    if r['operator_name'].casefold() == compact.operator.casefold()]
                if existing != [minor]:
                    reviews.append(f'{day}: {compact.operator} {amount} — кассовая запись требует сверки')
                continue
            prior = c.execute('''SELECT amount_minor FROM compact_operator_days
                WHERE lower(register_name)=lower(?) AND accounting_date=? AND lower(operator_name)=lower(?)''',
                (compact.name, day, compact.operator)).fetchone()
            if prior:
                if prior[0] != minor:
                    reviews.append(f'{day}: {compact.operator} {amount} — другое начисление уже записано')
                continue
            boundaries = [r[0] for r in c.execute('SELECT timestamp FROM period_starts WHERE source_row_id<?', (source_row_id,))]
            boundaries += [r[0] for r in c.execute('SELECT command_timestamp FROM operator_payouts WHERE command_source_row_id<? AND operator_key=?',
                (source_row_id, compact.operator.casefold()))]
            if any(day <= business_day(value).isoformat() for value in boundaries):
                reviews.append(f'{day}: {compact.operator} {amount} — историческое начисление после закрытия периода')
                continue
            pending.append((source_row_id, day, compact.name, compact.operator, minor))
        if not reviews:
            c.executemany('INSERT OR IGNORE INTO compact_operator_days VALUES(?,?,?,?,?)', pending)
    status = 'unverified' if reviews else 'operator_accrual'
    save_source(ledger, source_row_id, timestamp, platform_message_id, content,
                replace(compact, review_lines=tuple(reviews)), status)
    return status


def plain_amount(minor):
    if minor is None:
        return '?'
    from decimal import Decimal
    return format(Decimal(minor) / 100, '.2f').rstrip('0').rstrip('.') if minor % 100 else str(minor // 100)


def format_guidance(content, timestamp, *, is_bot=False):
    """Copy declared source data, not computed/corrected totals or balances."""
    if is_bot:
        return None
    compact = parse_compact(content, timestamp)
    if compact and compact.standard and not compact.review_lines:
        return None
    prefix = 'Необязательный короткий формат с теми же исходными суммами (? — неизвестно):\n'
    if compact and compact.standard and compact.review_lines:
        raw = [line for line in body_lines(content) if line.casefold() != 'финмониторинг']
        heading = raw[0] if compact.dates else '?'
        return prefix + '\n'.join([heading, raw[1], ''] + raw[2:]) + '\nДля уточнения: ' + '; '.join(compact.review_lines)
    if compact and compact.kind == 'operator':
        day = str(int(compact.dates[0][-2:])) if len(compact.dates) == 1 else '?'
        if len(compact.dates) == 1 and compact.dates[0][:7] != business_day(timestamp).isoformat()[:7]:
            day = datetime.fromisoformat(compact.dates[0]).strftime('%d.%m.%Y')
        if len(compact.daily) > 1:
            short_range = f'{int(compact.dates[0][-2:])}–{int(compact.dates[-1][-2:])}'
            day = short_range if resolve_dates(short_range, timestamp) == compact.dates else '?'
            details = '\n'.join(f'{int(d[-2:]) if day != "?" else datetime.fromisoformat(d).strftime("%d.%m.%Y")} — {amount}' for d, amount in compact.daily)
        else:
            details = compact.daily[0][1] if len(compact.daily) == 1 else '?'
        review = ('\nДля уточнения: ' + '; '.join(compact.review_lines)) if compact.review_lines else ''
        return prefix + f'{day}\n{compact.operator} / {compact.name}\n\n{details}' + review
    if re.search(r'^\s*Финмониторинг\s*$', content, re.M | re.I):
        name = re.search(r'^\s*Модель\s*:\s*(.+)$', content, re.M | re.I)
        equations = [line for line in body_lines(content) if '=' in line]
        if not equations:
            return None
        period = [line for line in body_lines(content) if re.match(r'^(?:Даты|Период)\s*:', line, re.I)]
        return prefix + '?\n' + (name[1] if name else '?') + '\n' + '\n'.join(equations + period)
    from cash_ledger_monitor import parse_message, _extract_accounting_date
    parsed = parse_message(content)
    if parsed.register_name is None or not (parsed.entries or parsed.operators or parsed.claimed_total_minor is not None
            or parsed.model_amount_minor is not None or parsed.agency_amount_minor is not None or parsed.review_lines):
        return None
    day = _extract_accounting_date(content, timestamp)
    heading = str(int(day[-2:])) if day[:7] == business_day(timestamp).isoformat()[:7] else datetime.fromisoformat(day).strftime('%d.%m.%Y')
    template = [heading, parsed.register_name, '']
    raw = body_lines(content)
    groups = {}
    for entry in parsed.entries:
        groups.setdefault(entry.label, []).append(entry.amount_minor)
    for index, label in enumerate(raw):
        if label not in groups or not groups[label]:
            continue
        from cash_ledger_monitor import HR_AMOUNT_RE, PLUS_AMOUNT_RE
        count = len(HR_AMOUNT_RE.findall(label)) + len(PLUS_AMOUNT_RE.findall(label)) or 1
        amounts, groups[label] = groups[label][:count], groups[label][count:]
        methods = re.findall(METHOD, label, re.I)
        following = raw[index + 1] if index + 1 < len(raw) else ''
        if not methods:
            methods = [following] if re.fullmatch(METHOD, following, re.I) else []
        terms = [re.fullmatch(rf'\s*({METHOD})\s*\(\s*({NUMBER})\s*\)\s*', term, re.I) for term in following.split('+')]
        if len(amounts) == 1 and len(terms) >= 2 and all(terms):
            template.append(plain_amount(amounts[0]) + ' = ' + ' + '.join(f'{term[1]} {term[2]}' for term in terms))
            continue
        method = methods[0] if len(methods) == 1 else '?'
        template.append('+'.join(plain_amount(a) for a in amounts) + ' ' + method)
    if len(template) == 3:
        template.append('? ?')
    template += ['', 'Итого ' + plain_amount(parsed.claimed_total_minor),
                 'Модели ' + plain_amount(parsed.model_amount_minor),
                 'Агентству ' + plain_amount(parsed.agency_amount_minor)]
    template += [f'{op.name} {plain_amount(op.amount_minor)}' for op in parsed.operators] or ['? ?']
    suffix = ('\nНеоднозначные строки сохранены без изменений:\n' + '\n'.join(parsed.review_lines)) if parsed.review_lines else ''
    payment_context = [line for line in raw if re.search(METHOD, line, re.I)
        and line not in groups and not re.fullmatch(METHOD, line, re.I)]
    if payment_context:
        suffix += '\nПлатежные сведения из источника (не новые клиенты):\n' + '\n'.join(payment_context)
    return ('Необязательный короткий формат с теми же исходными суммами (? — неизвестно):\n'
            + '\n'.join(template) + suffix)


def operator_rows(ledger, cutoff=0, before=9223372036854775807):
    """Additional operator rows; kept outside cash reports to avoid superseding them."""
    with ledger._connection() as c:
        exists = c.execute("SELECT 1 FROM sqlite_master WHERE name='compact_operator_days'").fetchone()
        if not exists:
            return []
        rows = [dict(r) for r in c.execute('''SELECT * FROM compact_operator_days
            WHERE source_row_id>? AND source_row_id<? ORDER BY accounting_date, source_row_id''',
            (cutoff, before))]
        return [row for row in rows if not c.execute('''SELECT 1 FROM messages
            WHERE lower(register_name)=lower(?) AND accounting_date=? AND source_row_id<?''',
            (row['register_name'], row['accounting_date'], before)).fetchone()]
