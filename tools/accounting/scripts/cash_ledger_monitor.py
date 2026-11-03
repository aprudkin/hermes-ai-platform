#!/usr/bin/env python3
"""Monitor Telegram cash messages, verify totals, and keep daily statistics."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SENDER_RE = re.compile(r"^\[([^|\]]+)\|(\d+)\]\s*$")
TOTAL_RE = re.compile(r"\b(?:total|итого|итог|тотал|всего|общий\s+итог)\b", re.IGNORECASE)
ACCOUNTING_RE = re.compile(
    r"\b(?:касс\w*|налич\w*|безнал\w*|карт\w*|выручк\w*|приход\w*|расход\w*|"
    r"перевод\w*|оплат\w*|руб\w*)\b|₽",
    re.IGNORECASE,
)
TIME_RE = re.compile(r"^.*\b\d{1,2}:\d{2}\b.*$")
DATE_RE = re.compile(r"^\s*\d{1,2}\s*[./-]\s*\d{1,2}(?:\s*[./-]\s*\d{2,4})?\s*$")
ACCOUNTING_DATE_RE = re.compile(
    r"^\s*(\d{1,2})\s*[./-]\s*(\d{1,2})(?:\s*[./-]\s*(\d{2,4}))?\s*$"
)
AMOUNT_RE = re.compile(r"[-+]?\d+(?:[ .]\d{3})*(?:[,.]\d{1,2})?")
BARE_AMOUNT_RE = re.compile(r"^[-+]?\d+(?:[ .]\d{3})*(?:[,.]\d{1,2})?\s*(?:₽|руб\.?|р\.?)?$")
REGISTER_HEADING_RE = re.compile(r"^(?:касса|profit\s+register)\s+([^:\d].*?)\s*$", re.IGNORECASE)
HR_AMOUNT_RE = re.compile(r"\b(?:H{1,2}r|\d+\s*(?:hrs?|hours?)|\d+\s*min|qv)\s*/\s*(\d+(?:[,.]\d{1,2})?)", re.IGNORECASE)
PLUS_AMOUNT_RE = re.compile(r"\+\s*(\d+(?:[,.]\d{1,2})?)")
EXPLICIT_EXTRA_SUFFIX_RE = re.compile(r"\s*\$?\s*доп(?:ы|олнительно|лата)?\b", re.IGNORECASE)
RU_OPERATOR_RE = re.compile(
    r"^Оператор\s+([^\d:+]+?)\s*[:+]?\s*([+-]?\d+(?:[,.]\d{1,2})?)\s*$",
    re.IGNORECASE,
)
EN_OPERATOR_RE = re.compile(
    r"^([^\d:+]+?)\s+Operator\s*[:+]?\s*([+-]?\d+(?:[,.]\d{1,2})?)",
    re.IGNORECASE,
)
MODEL_AMOUNT_RE = re.compile(r"^(?:модели|модель|yours)\s*:\s*(\d+(?:[,.]\d{1,2})?)\s*(?:\$)?\s*$", re.IGNORECASE)
AGENCY_AMOUNT_RE = re.compile(r"^(?:агентских|агентство|agent\s+fees)\s*:\s*(\d+(?:[,.]\d{1,2})?)\s*(?:\$)?\s*$", re.IGNORECASE)
PAYOUT_COMMAND_RE = re.compile(r"^выдача\s+(.+?)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Entry:
    label: str
    amount_minor: int


@dataclass(frozen=True)
class OperatorAmount:
    name: str
    amount_minor: int


@dataclass(frozen=True)
class ParsedMessage:
    sender_id: str | None
    sender_name: str | None
    register_name: str | None
    entries: tuple[Entry, ...]
    operators: tuple[OperatorAmount, ...]
    claimed_total_minor: int | None
    model_amount_minor: int | None = None
    agency_amount_minor: int | None = None
    review_lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProcessResult:
    status: str
    computed_total_minor: int | None
    claimed_total_minor: int | None
    difference_minor: int | None


@dataclass(frozen=True)
class PayoutResult:
    status: str
    operator_name: str
    by_date: tuple[tuple[str, int], ...]
    total_minor: int
    report: str


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    source_row_id INTEGER PRIMARY KEY,
                    platform_message_id TEXT,
                    accounting_date TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    sender_id TEXT,
                    sender_name TEXT,
                    raw_content TEXT NOT NULL,
                    claimed_total_minor INTEGER,
                    computed_total_minor INTEGER,
                    difference_minor INTEGER,
                    check_status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_row_id INTEGER NOT NULL,
                    line_no INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    amount_minor INTEGER NOT NULL,
                    FOREIGN KEY(source_row_id) REFERENCES messages(source_row_id),
                    UNIQUE(source_row_id, line_no)
                );
                CREATE TABLE IF NOT EXISTS period_starts (
                    source_row_id INTEGER PRIMARY KEY,
                    platform_message_id TEXT,
                    timestamp REAL NOT NULL,
                    raw_content TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS parse_reviews (
                    source_row_id INTEGER NOT NULL,
                    line_no INTEGER NOT NULL,
                    line TEXT NOT NULL,
                    PRIMARY KEY(source_row_id, line_no)
                );
                CREATE TABLE IF NOT EXISTS operators (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_row_id INTEGER NOT NULL,
                    line_no INTEGER NOT NULL,
                    operator_name TEXT NOT NULL,
                    amount_minor INTEGER NOT NULL,
                    FOREIGN KEY(source_row_id) REFERENCES messages(source_row_id),
                    UNIQUE(source_row_id, line_no)
                );
                CREATE TABLE IF NOT EXISTS models (
                    source_row_id INTEGER PRIMARY KEY,
                    model_name TEXT NOT NULL,
                    amount_minor INTEGER NOT NULL,
                    FOREIGN KEY(source_row_id) REFERENCES messages(source_row_id)
                );
                CREATE TABLE IF NOT EXISTS operator_payouts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    command_source_row_id INTEGER NOT NULL UNIQUE,
                    operator_key TEXT NOT NULL,
                    operator_name TEXT NOT NULL,
                    command_timestamp REAL NOT NULL,
                    requester_id TEXT,
                    requester_name TEXT,
                    previous_cutoff_source_row_id INTEGER NOT NULL,
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    total_minor INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operator_payout_items (
                    payout_id INTEGER NOT NULL,
                    accounting_date TEXT NOT NULL,
                    amount_minor INTEGER NOT NULL,
                    FOREIGN KEY(payout_id) REFERENCES operator_payouts(id),
                    UNIQUE(payout_id, accounting_date)
                );
                CREATE TABLE IF NOT EXISTS model_payouts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    command_source_row_id INTEGER NOT NULL UNIQUE,
                    model_key TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    command_timestamp REAL NOT NULL,
                    requester_id TEXT,
                    requester_name TEXT,
                    previous_cutoff_source_row_id INTEGER NOT NULL,
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    total_minor INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_payout_items (
                    payout_id INTEGER NOT NULL,
                    accounting_date TEXT NOT NULL,
                    amount_minor INTEGER NOT NULL,
                    FOREIGN KEY(payout_id) REFERENCES model_payouts(id),
                    UNIQUE(payout_id, accounting_date)
                );
                CREATE TABLE IF NOT EXISTS agency_payouts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    command_source_row_id INTEGER NOT NULL UNIQUE,
                    agency_key TEXT NOT NULL,
                    agency_name TEXT NOT NULL,
                    command_timestamp REAL NOT NULL,
                    requester_id TEXT,
                    requester_name TEXT,
                    previous_cutoff_source_row_id INTEGER NOT NULL,
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    total_minor INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agency_payout_items (
                    payout_id INTEGER NOT NULL,
                    accounting_date TEXT NOT NULL,
                    amount_minor INTEGER NOT NULL,
                    FOREIGN KEY(payout_id) REFERENCES agency_payouts(id),
                    UNIQUE(payout_id, accounting_date)
                );
                """
            )
            message_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(messages)").fetchall()
            }
            if "register_name" not in message_columns:
                connection.execute("ALTER TABLE messages ADD COLUMN register_name TEXT")
            if "agency_amount_minor" not in message_columns:
                connection.execute("ALTER TABLE messages ADD COLUMN agency_amount_minor INTEGER")
            connection.execute("""CREATE VIEW IF NOT EXISTS agencies AS
                SELECT source_row_id, register_name AS agency_name, agency_amount_minor AS amount_minor
                FROM messages WHERE register_name IS NOT NULL AND agency_amount_minor IS NOT NULL
            """)
            for row in connection.execute("SELECT source_row_id, raw_content FROM messages WHERE register_name IS NOT NULL AND agency_amount_minor IS NULL").fetchall():
                parsed = parse_message(row["raw_content"])
                if parsed.agency_amount_minor is not None:
                    connection.execute("UPDATE messages SET agency_amount_minor=? WHERE source_row_id=?",
                        (parsed.agency_amount_minor, row["source_row_id"]))
            # Add the new metadata to existing reports, without replaying notices or payouts.
            for row in connection.execute("""
                SELECT m.source_row_id, m.raw_content FROM messages m
                LEFT JOIN models o ON o.source_row_id = m.source_row_id
                WHERE m.register_name IS NOT NULL AND o.source_row_id IS NULL
            """).fetchall():
                parsed = parse_message(row["raw_content"])
                if parsed.register_name is not None and parsed.model_amount_minor is not None:
                    connection.execute(
                        "INSERT OR IGNORE INTO models (source_row_id, model_name, amount_minor) VALUES (?, ?, ?)",
                        (row["source_row_id"], parsed.register_name, parsed.model_amount_minor),
                    )

    def process_message(
        self,
        *,
        source_row_id: int,
        timestamp: float,
        platform_message_id: str | None,
        content: str,
        compact_enabled: bool = False,
    ) -> ProcessResult:
        if compact_enabled:
            with self._connection() as c:
                existing = c.execute('SELECT check_status,computed_total_minor,claimed_total_minor,difference_minor FROM messages WHERE source_row_id=?', (source_row_id,)).fetchone()
            if existing is not None:
                return ProcessResult(*existing)
            with self._connection() as c:
                if c.execute("SELECT 1 FROM sqlite_master WHERE name='compact_sources'").fetchone():
                    existing = c.execute('SELECT status FROM compact_sources WHERE source_row_id=?', (source_row_id,)).fetchone()
                    if existing is not None:
                        return ProcessResult(existing[0], None, None, None)
        parsed = parse_message(content)
        accounting_date = _extract_accounting_date(content, timestamp)
        if compact_enabled:
            from cash_compact_formats import parse_compact
            compact = parse_compact(content, timestamp)
            if compact is not None and compact.kind == 'operator':
                from cash_compact_formats import record_operator
                status = record_operator(self, source_row_id, timestamp, platform_message_id, content, compact)
                return ProcessResult(status, None, None, None)
            if compact is not None and compact.kind == 'cash':
                from dataclasses import replace
                from cash_compact_formats import save_source
                if not compact.dates or not compact.normalized:
                    save_source(self, source_row_id, timestamp, platform_message_id, content, compact, 'unverified')
                    return ProcessResult('unverified', None, None, None)
                parsed = replace(parse_message(compact.normalized), sender_id=parsed.sender_id, sender_name=parsed.sender_name,
                    review_lines=compact.review_lines + parse_message(compact.normalized).review_lines)
                accounting_date = compact.dates[0]
            if parsed.register_name:
                collisions = []
                for prior in self._compact_operator_rows(0, source_row_id):
                    if prior['register_name'].casefold() != parsed.register_name.casefold() or prior['accounting_date'] != accounting_date:
                        continue
                    values = [op.amount_minor for op in parsed.operators if op.name.casefold() == prior['operator_name'].casefold()]
                    if values != [prior['amount_minor']]:
                        collisions.append(f"{accounting_date}: {prior['operator_name']} — начисление не совпадает с отдельной операторской записью; нужна сверка")
                if collisions:
                    from cash_compact_formats import Compact, save_source
                    review = Compact('cash', parsed.register_name, (accounting_date,), '', tuple(collisions))
                    save_source(self, source_row_id, timestamp, platform_message_id, content, review, 'unverified')
                    return ProcessResult('unverified', None, parsed.claimed_total_minor, None)
        if parsed.register_name is not None and parsed.claimed_total_minor is not None:
            computed = sum(entry.amount_minor for entry in parsed.entries)
        elif parsed.entries:
            computed = sum(entry.amount_minor for entry in parsed.entries)
        elif parsed.claimed_total_minor is not None:
            computed = self._pending_total_minor(accounting_date, source_row_id)
        else:
            computed = None
        claimed = parsed.claimed_total_minor
        if parsed.review_lines:
            computed = None
        difference = None if claimed is None or computed is None else claimed - computed
        if compact_enabled and parsed.review_lines:
            status = 'unverified'
        elif claimed is None:
            status = "no_total"
        elif computed is None:
            status = "unverified"
        elif difference == 0:
            status = "ok"
        else:
            status = "mismatch"

        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO messages (
                    source_row_id, platform_message_id, accounting_date, timestamp,
                    sender_id, sender_name, raw_content, claimed_total_minor,
                    computed_total_minor, difference_minor, check_status, register_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_row_id,
                    platform_message_id,
                    accounting_date,
                    timestamp,
                    parsed.sender_id,
                    parsed.sender_name,
                    content,
                    claimed,
                    computed,
                    difference,
                    status,
                    parsed.register_name,
                ),
            )
            for line_no, entry in enumerate(parsed.entries, 1):
                connection.execute(
                    "INSERT OR IGNORE INTO entries (source_row_id, line_no, label, amount_minor) VALUES (?, ?, ?, ?)",
                    (source_row_id, line_no, entry.label, entry.amount_minor),
                )
            for line_no, line in enumerate(parsed.review_lines, 1):
                connection.execute(
                    "INSERT OR IGNORE INTO parse_reviews VALUES (?, ?, ?)",
                    (source_row_id, line_no, line),
                )
            for line_no, operator in enumerate(parsed.operators, 1):
                connection.execute(
                    """
                    INSERT OR IGNORE INTO operators
                    (source_row_id, line_no, operator_name, amount_minor)
                    VALUES (?, ?, ?, ?)
                    """,
                    (source_row_id, line_no, operator.name, operator.amount_minor),
                )
            if parsed.register_name is not None and parsed.model_amount_minor is not None:
                connection.execute(
                    "INSERT OR IGNORE INTO models (source_row_id, model_name, amount_minor) VALUES (?, ?, ?)",
                    (source_row_id, parsed.register_name, parsed.model_amount_minor),
                )
            if parsed.agency_amount_minor is not None:
                connection.execute("UPDATE messages SET agency_amount_minor=? WHERE source_row_id=? AND agency_amount_minor IS NULL",
                    (parsed.agency_amount_minor, source_row_id))
        return ProcessResult(status, computed, claimed, difference)

    def check_finance_message(self, *, source_row_id: int, timestamp: float, content: str,
                              compact_enabled: bool = False) -> str | None:
        raw_content = content
        compact = None
        if compact_enabled:
            from cash_compact_formats import parse_compact
            compact = parse_compact(content, timestamp)
            if compact is not None and compact.kind == 'finance':
                content = compact.normalized
            else:
                compact = None
        if not re.search(r"^\s*Финмониторинг\s*$", content, re.IGNORECASE | re.MULTILINE):
            return None
        name_match = re.search(r"^\s*Модель\s*:\s*(.+)$", content, re.IGNORECASE | re.MULTILINE)
        name = name_match.group(1).strip() if name_match else "без имени"
        # Financial summaries verify arithmetic only; they are never another revenue entry.
        number_pattern = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?"
        def number(token):
            if not re.fullmatch(number_pattern, token):
                raise ValueError("Ambiguous or unsupported number")
            return Decimal(token.replace(',', ''))
        checks = []
        for raw_line in content.splitlines():
            if '=' not in raw_line:
                continue
            line = re.sub(r'\s+', '', raw_line)
            try:
                left, right = line.split('=')
                claimed = number(right)
                percent = re.fullmatch(f'({number_pattern})([*×-])({number_pattern})%', left)
                if percent:
                    base, operator, rate = percent.groups()
                    share = number(base) * number(rate) / Decimal(100)
                    computed = share if operator in ('*','×') else number(base) - share
                else:
                    computed = sum((number(part) for part in left.split('+')), Decimal(0))
                computed = computed.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                checks.append({'line':raw_line.strip(),'computed':str(computed),'claimed':str(claimed),'ok':computed==claimed})
            except (ValueError, InvalidOperation):
                checks.append({'line':raw_line.strip(),'computed':None,'claimed':None,'ok':None})
        status = 'unverified' if not checks or any(c['ok'] is None for c in checks) or (compact and compact.review_lines) else ('ok' if all(c['ok'] for c in checks) else 'mismatch')
        local = datetime.fromtimestamp(timestamp, ZoneInfo('America/Los_Angeles'))
        day = local.date() - timedelta(days=1) if local.hour < 6 else local.date()
        date = day.isoformat()
        with self._connection() as c:
            c.execute('CREATE TABLE IF NOT EXISTS finance_checks(source_row_id INTEGER PRIMARY KEY,checked_date TEXT,model_name TEXT,raw_content TEXT,status TEXT,checks_json TEXT)')
            c.execute('INSERT OR IGNORE INTO finance_checks VALUES(?,?,?,?,?,?)',
                      (source_row_id,date,name,raw_content,status,json.dumps(checks,ensure_ascii=False)))
        if compact:
            from cash_compact_formats import save_source
            save_source(self, source_row_id, timestamp, None, raw_content, compact, status)
        heading = {'ok':'✅ Арифметика верна','mismatch':'⚠️ Ошибка в арифметике','unverified':'⚠️ Не все выражения удалось проверить'}[status]
        period = _display_date(date)
        if compact:
            if not compact.dates:
                period = 'Дата / период требует уточнения'
            elif len(compact.dates) == 1:
                period = _display_date(compact.dates[0])
            else:
                period = f'{_display_date(compact.dates[0])} — {_display_date(compact.dates[-1])}'
        lines = [f"**{period}:**", f"Финмониторинг — {name}", heading]
        for check in checks:
            if check['computed'] is None:
                lines.append(f"Не проверено: {check['line']}")
            else:
                amount = _format_money(int(Decimal(check['computed'])*100))
                lines.append(f"{'✅' if check['ok'] else '⚠️'} {check['line']} → {amount}")
        lines.append('Проверены вычисления; исходные суммы не сверены со старой историей и не прибавлены к выручке.')
        return '\n'.join(lines)

    def cash_notice(self, source_row_id: int) -> str:
        def money(amount: int) -> str:
            value = _format_money(amount).replace("$", "")
            return (value[:-3] if value.endswith(".00") else value) + "$"

        def short_date(value: str) -> str:
            return _display_date(value)

        with self._connection() as connection:
            report = connection.execute("SELECT * FROM messages WHERE source_row_id=?", (source_row_id,)).fetchone()
            if report is None or report["check_status"] != "ok":
                return ""
            lines = [f"**{short_date(report['accounting_date'])}:**",
                     f"✅ Итого: {money(report['claimed_total_minor'])} — сходится ✅"]
            people = [("model", r["model_name"]) for r in connection.execute(
                "SELECT model_name FROM models WHERE source_row_id=?", (source_row_id,))]
            people += [("operator", r["operator_name"]) for r in connection.execute(
                "SELECT DISTINCT operator_name FROM operators WHERE source_row_id=? ORDER BY line_no", (source_row_id,))]
            if report["agency_amount_minor"] is not None:
                people.append(("agency", report["register_name"]))
            for kind, name in people:
                table = "agencies" if kind == "agency" else kind + "s"
                payout_kind = "model" if kind == "agency" else kind
                payout = connection.execute(f"""
                    SELECT command_source_row_id, command_timestamp FROM {payout_kind}_payouts
                    WHERE {payout_kind}_key=? AND command_source_row_id<?
                    ORDER BY command_source_row_id DESC LIMIT 1
                """, (name.casefold(), source_row_id)).fetchone()
                start = self._period_cutoff(source_row_id)
                cutoff = max(start, payout["command_source_row_id"] if payout else 0)
                rows = connection.execute(f"""
                    WITH latest AS (
                        SELECT register_name, accounting_date, MAX(source_row_id) AS source_row_id
                        FROM messages WHERE register_name IS NOT NULL AND source_row_id>? AND source_row_id<=?
                        GROUP BY register_name, accounting_date
                    )
                    SELECT m.accounting_date, o.{kind}_name AS name, o.amount_minor
                    FROM latest l JOIN messages m USING(source_row_id)
                    JOIN {table} o USING(source_row_id) ORDER BY m.accounting_date
                """, (cutoff, source_row_id)).fetchall()
                rows = [r for r in rows if r["name"].casefold() == name.casefold()]
                if kind == 'operator':
                    rows += [dict(accounting_date=r['accounting_date'], name=r['operator_name'], amount_minor=r['amount_minor'])
                        for r in self._compact_operator_rows(cutoff, source_row_id + 1)
                        if r['operator_name'].casefold() == name.casefold()]
                    rows.sort(key=lambda r: r['accounting_date'])
                amount = sum(r["amount_minor"] for r in rows)
                if start and (not payout or start > payout["command_source_row_id"]):
                    date = short_date(rows[0]["accounting_date"] if rows else report["accounting_date"])
                    period = f"новый период с {date}"
                elif payout:
                    date = _display_date(datetime.fromtimestamp(payout["command_timestamp"], timezone.utc).date().isoformat())
                    period = f"с выплаты {date}"
                else:
                    date = short_date(rows[0]["accounting_date"] if rows else report["accounting_date"])
                    period = f"с {date} (выплат ещё не было)"
                label = "Агентство" if kind == "agency" else name
                emoji = {"model": "🫦", "operator": "🥷🏻", "agency": "🎩"}[kind]
                lines.append(f"{emoji} {label}: {money(amount)} — {period}")
        if not lines[-1].endswith("✅"):
            lines[-1] += " ✅"
        return "\n".join(lines)

    def record_period_start(self, *, source_row_id: int, timestamp: float,
                            platform_message_id: str | None, content: str) -> bool:
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if not lines or not SENDER_RE.fullmatch(lines[0]):
            return False
        sender_id = SENDER_RE.fullmatch(lines[0]).group(2)
        if sender_id not in set(filter(None, os.environ.get("BABLOMAT_PERIOD_AUTHORIZED_IDS", "").split(","))):
            return False
        if len(lines) != 2 or not re.fullmatch(r"новый\s+расч[её]т\s*[!.]*", lines[1], re.IGNORECASE):
            return False
        with self._connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO period_starts VALUES (?, ?, ?, ?)",
                (source_row_id, platform_message_id, timestamp, content),
            )
        return True

    def _period_cutoff(self, before_row_id: int) -> int:
        with self._connection() as connection:
            return int(connection.execute(
                "SELECT COALESCE(MAX(source_row_id),0) FROM period_starts WHERE source_row_id < ?",
                (before_row_id,),
            ).fetchone()[0])

    def register_statistics(self) -> dict[str, int]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                WITH latest_reports AS (
                    SELECT register_name, accounting_date, MAX(source_row_id) AS source_row_id
                    FROM messages
                    WHERE register_name IS NOT NULL
                    GROUP BY register_name, accounting_date
                )
                SELECT m.register_name, COALESCE(SUM(m.computed_total_minor), 0) AS total_minor
                FROM latest_reports AS latest
                JOIN messages AS m ON m.source_row_id = latest.source_row_id
                WHERE m.computed_total_minor IS NOT NULL
                GROUP BY m.register_name
                ORDER BY m.register_name COLLATE NOCASE
                """
            ).fetchall()
        return {row["register_name"]: int(row["total_minor"]) for row in rows}

    def _compact_operator_rows(self, cutoff=0, before=9223372036854775807):
        with self._connection() as c:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE name='compact_operator_days'").fetchone():
                return []
        from cash_compact_formats import operator_rows
        return operator_rows(self, cutoff, before)

    def operator_statistics(self) -> dict[str, int]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                WITH latest_reports AS (
                    SELECT register_name, accounting_date, MAX(source_row_id) AS source_row_id
                    FROM messages
                    WHERE register_name IS NOT NULL
                    GROUP BY register_name, accounting_date
                )
                SELECT o.operator_name, COALESCE(SUM(o.amount_minor), 0) AS total_minor
                FROM latest_reports AS latest
                JOIN operators AS o ON o.source_row_id = latest.source_row_id
                GROUP BY o.operator_name
                ORDER BY o.operator_name COLLATE NOCASE
                """
            ).fetchall()
        totals = {row["operator_name"]: int(row["total_minor"]) for row in rows}
        for row in self._compact_operator_rows():
            name = row['operator_name']
            totals[name] = totals.get(name, 0) + row['amount_minor']
        return totals

    def model_statistics(self) -> dict[str, int]:
        with self._connection() as connection:
            rows = connection.execute("""
                WITH latest_reports AS (
                    SELECT register_name, accounting_date, MAX(source_row_id) AS source_row_id
                    FROM messages WHERE register_name IS NOT NULL
                    GROUP BY register_name, accounting_date
                )
                SELECT o.model_name, SUM(o.amount_minor) AS total_minor
                FROM latest_reports AS latest
                JOIN models AS o ON o.source_row_id = latest.source_row_id
                GROUP BY o.model_name ORDER BY o.model_name COLLATE NOCASE
            """).fetchall()
        return {row["model_name"]: int(row["total_minor"]) for row in rows}

    def agency_statistics(self) -> dict[str, int]:
        with self._connection() as connection:
            rows = connection.execute("""
                WITH latest_reports AS (
                    SELECT register_name, accounting_date, MAX(source_row_id) AS source_row_id
                    FROM messages WHERE register_name IS NOT NULL
                    GROUP BY register_name, accounting_date
                )
                SELECT o.agency_name, SUM(o.amount_minor) AS total_minor
                FROM latest_reports AS latest
                JOIN agencies AS o ON o.source_row_id = latest.source_row_id
                GROUP BY o.agency_name ORDER BY o.agency_name COLLATE NOCASE
            """).fetchall()
        return {row["agency_name"]: int(row["total_minor"]) for row in rows}

    def operator_report(self) -> str:
        statistics = self.operator_statistics()
        lines = ["Отчёт по операторам"]
        for name, amount_minor in statistics.items():
            lines.append(f"{name}: {_format_money(amount_minor)}")
        lines.append(f"Итого операторам: {_format_money(sum(statistics.values()))}")
        return "\n".join(lines)

    def create_operator_payout(
        self,
        *,
        operator_name: str,
        command_source_row_id: int,
        command_timestamp: float,
        requester_id: str | None,
        requester_name: str | None,
    ) -> PayoutResult:
        requested_key = operator_name.strip().casefold()
        with self._connection() as connection:
            existing = connection.execute(
                """
                SELECT id, operator_name, period_start, period_end, total_minor
                FROM operator_payouts
                WHERE command_source_row_id = ?
                """,
                (command_source_row_id,),
            ).fetchone()
            if existing is not None:
                item_rows = connection.execute(
                    """
                    SELECT accounting_date, amount_minor
                    FROM operator_payout_items
                    WHERE payout_id = ?
                    ORDER BY accounting_date
                    """,
                    (existing["id"],),
                ).fetchall()
                existing_by_date = tuple(
                    (row["accounting_date"], int(row["amount_minor"])) for row in item_rows
                )
                existing_total = int(existing["total_minor"])
                existing_report = _format_payout_report(
                    existing["operator_name"],
                    existing["period_start"],
                    existing["period_end"],
                    existing_by_date,
                    existing_total,
                )
                return PayoutResult(
                    "existing",
                    existing["operator_name"],
                    existing_by_date,
                    existing_total,
                    existing_report,
                )

            known_names = [row["operator_name"] for row in connection.execute(
                "SELECT DISTINCT operator_name FROM operators ORDER BY operator_name COLLATE NOCASE"
            )]
            known_names += [row['operator_name'] for row in self._compact_operator_rows()]
            canonical_name = next(
                (name for name in known_names if name.casefold() == requested_key),
                None,
            )
            if canonical_name is None:
                report = f"Оператор {operator_name.strip()} не найден. Период выдачи не закрыт."
                return PayoutResult("not_found", operator_name.strip(), (), 0, report)

            previous = connection.execute(
                """
                SELECT command_source_row_id
                FROM operator_payouts
                WHERE operator_key = ? AND command_source_row_id < ?
                ORDER BY command_source_row_id DESC
                LIMIT 1
                """,
                (requested_key, command_source_row_id),
            ).fetchone()
            previous_cutoff = max(int(previous["command_source_row_id"]) if previous else 0,
                                  self._period_cutoff(command_source_row_id))
            rows = connection.execute(
                """
                WITH latest_reports AS (
                    SELECT register_name, accounting_date, MAX(source_row_id) AS source_row_id
                    FROM messages
                    WHERE source_row_id > ?
                      AND source_row_id < ?
                      AND register_name IS NOT NULL
                    GROUP BY register_name, accounting_date
                )
                SELECT m.accounting_date, o.operator_name, o.amount_minor
                FROM latest_reports AS latest
                JOIN messages AS m ON m.source_row_id = latest.source_row_id
                JOIN operators AS o ON o.source_row_id = m.source_row_id
                ORDER BY m.accounting_date, m.source_row_id, o.line_no
                """,
                (previous_cutoff, command_source_row_id),
            ).fetchall()
            rows = list(rows) + self._compact_operator_rows(previous_cutoff, command_source_row_id)
            daily: dict[str, int] = {}
            for row in rows:
                if row["operator_name"].casefold() == requested_key:
                    daily[row["accounting_date"]] = daily.get(row["accounting_date"], 0) + int(row["amount_minor"])

            command_date = datetime.fromtimestamp(command_timestamp, timezone.utc).date().isoformat()
            period_start = min(daily) if daily else command_date
            period_end = max(daily) if daily else command_date
            total_minor = sum(daily.values())
            cursor = connection.execute(
                """
                INSERT INTO operator_payouts (
                    command_source_row_id, operator_key, operator_name, command_timestamp,
                    requester_id, requester_name, previous_cutoff_source_row_id,
                    period_start, period_end, total_minor
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    command_source_row_id, requested_key, canonical_name, command_timestamp,
                    requester_id, requester_name, previous_cutoff, period_start, period_end, total_minor,
                ),
            )
            payout_id = int(cursor.lastrowid)
            for accounting_date, amount_minor in sorted(daily.items()):
                connection.execute(
                    """
                    INSERT INTO operator_payout_items (payout_id, accounting_date, amount_minor)
                    VALUES (?, ?, ?)
                    """,
                    (payout_id, accounting_date, amount_minor),
                )

        by_date = tuple(sorted(daily.items()))
        report = _format_payout_report(canonical_name, period_start, period_end, by_date, total_minor)
        return PayoutResult("created", canonical_name, by_date, total_minor, report)

    def create_model_payout(
        self,
        *,
        model_name: str,
        command_source_row_id: int,
        command_timestamp: float,
        requester_id: str | None,
        requester_name: str | None,
    ) -> PayoutResult:
        requested_key = model_name.strip().casefold()
        with self._connection() as connection:
            existing = connection.execute(
                """
                SELECT id, model_name, period_start, period_end, total_minor
                FROM model_payouts
                WHERE command_source_row_id = ?
                """,
                (command_source_row_id,),
            ).fetchone()
            if existing is not None:
                item_rows = connection.execute(
                    """
                    SELECT accounting_date, amount_minor
                    FROM model_payout_items
                    WHERE payout_id = ?
                    ORDER BY accounting_date
                    """,
                    (existing["id"],),
                ).fetchall()
                existing_by_date = tuple(
                    (row["accounting_date"], int(row["amount_minor"])) for row in item_rows
                )
                existing_total = int(existing["total_minor"])
                existing_report = _format_payout_report(
                    existing["model_name"],
                    existing["period_start"],
                    existing["period_end"],
                    existing_by_date,
                    existing_total,
                )
                agency = self.create_agency_payout(
                    agency_name=existing["model_name"], command_source_row_id=command_source_row_id,
                    command_timestamp=command_timestamp, requester_id=requester_id,
                    requester_name=requester_name, _connection=connection)
                if agency.status != "not_found":
                    existing_report += "\n\n" + agency.report
                return PayoutResult(
                    "existing",
                    existing["model_name"],
                    existing_by_date,
                    existing_total,
                    existing_report,
                )

            known_names = [row["model_name"] for row in connection.execute(
                "SELECT DISTINCT model_name FROM models ORDER BY model_name COLLATE NOCASE"
            )]
            canonical_name = next(
                (name for name in known_names if name.casefold() == requested_key),
                None,
            )
            if canonical_name is None:
                report = f"Модель {model_name.strip()} не найден. Период выдачи не закрыт."
                return PayoutResult("not_found", model_name.strip(), (), 0, report)

            previous = connection.execute(
                """
                SELECT command_source_row_id
                FROM model_payouts
                WHERE model_key = ? AND command_source_row_id < ?
                ORDER BY command_source_row_id DESC
                LIMIT 1
                """,
                (requested_key, command_source_row_id),
            ).fetchone()
            previous_cutoff = max(int(previous["command_source_row_id"]) if previous else 0,
                                  self._period_cutoff(command_source_row_id))
            rows = connection.execute(
                """
                WITH latest_reports AS (
                    SELECT register_name, accounting_date, MAX(source_row_id) AS source_row_id
                    FROM messages
                    WHERE source_row_id > ?
                      AND source_row_id < ?
                      AND register_name IS NOT NULL
                    GROUP BY register_name, accounting_date
                )
                SELECT m.accounting_date, o.model_name, o.amount_minor
                FROM latest_reports AS latest
                JOIN messages AS m ON m.source_row_id = latest.source_row_id
                JOIN models AS o ON o.source_row_id = m.source_row_id
                ORDER BY m.accounting_date, m.source_row_id
                """,
                (previous_cutoff, command_source_row_id),
            ).fetchall()
            daily: dict[str, int] = {}
            for row in rows:
                if row["model_name"].casefold() == requested_key:
                    daily[row["accounting_date"]] = daily.get(row["accounting_date"], 0) + int(row["amount_minor"])

            command_date = datetime.fromtimestamp(command_timestamp, timezone.utc).date().isoformat()
            period_start = min(daily) if daily else command_date
            period_end = max(daily) if daily else command_date
            total_minor = sum(daily.values())
            cursor = connection.execute(
                """
                INSERT INTO model_payouts (
                    command_source_row_id, model_key, model_name, command_timestamp,
                    requester_id, requester_name, previous_cutoff_source_row_id,
                    period_start, period_end, total_minor
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    command_source_row_id, requested_key, canonical_name, command_timestamp,
                    requester_id, requester_name, previous_cutoff, period_start, period_end, total_minor,
                ),
            )
            payout_id = int(cursor.lastrowid)
            for accounting_date, amount_minor in sorted(daily.items()):
                connection.execute(
                    """
                    INSERT INTO model_payout_items (payout_id, accounting_date, amount_minor)
                    VALUES (?, ?, ?)
                    """,
                    (payout_id, accounting_date, amount_minor),
                )


            agency = self.create_agency_payout(
                agency_name=canonical_name, command_source_row_id=command_source_row_id,
                command_timestamp=command_timestamp, requester_id=requester_id,
                requester_name=requester_name, _connection=connection)

        by_date = tuple(sorted(daily.items()))
        report = _format_payout_report(canonical_name, period_start, period_end, by_date, total_minor)
        if agency.status != "not_found":
            report += "\n\n" + agency.report
        return PayoutResult("created", canonical_name, by_date, total_minor, report)

    def create_agency_payout(
        self,
        *,
        agency_name: str,
        command_source_row_id: int,
        command_timestamp: float,
        requester_id: str | None,
        requester_name: str | None,
        _connection: sqlite3.Connection | None = None,
    ) -> PayoutResult:
        if _connection is None:
            return PayoutResult("linked_only", agency_name, (), 0,
                f"Выплата агентства совпадает с выплатой модели. Используйте: Выдача {agency_name}.")
        requested_key = agency_name.strip().casefold()
        with nullcontext(_connection) as connection:
            existing = connection.execute(
                """
                SELECT id, agency_name, period_start, period_end, total_minor
                FROM agency_payouts
                WHERE command_source_row_id = ?
                """,
                (command_source_row_id,),
            ).fetchone()
            if existing is not None:
                item_rows = connection.execute(
                    """
                    SELECT accounting_date, amount_minor
                    FROM agency_payout_items
                    WHERE payout_id = ?
                    ORDER BY accounting_date
                    """,
                    (existing["id"],),
                ).fetchall()
                existing_by_date = tuple(
                    (row["accounting_date"], int(row["amount_minor"])) for row in item_rows
                )
                existing_total = int(existing["total_minor"])
                existing_report = _format_payout_report(
                    "Агентству " + existing["agency_name"],
                    existing["period_start"],
                    existing["period_end"],
                    existing_by_date,
                    existing_total,
                )
                return PayoutResult(
                    "existing",
                    existing["agency_name"],
                    existing_by_date,
                    existing_total,
                    existing_report,
                )

            known_names = [row["agency_name"] for row in connection.execute(
                "SELECT DISTINCT agency_name FROM agencies ORDER BY agency_name COLLATE NOCASE"
            )]
            canonical_name = next(
                (name for name in known_names if name.casefold() == requested_key),
                None,
            )
            if canonical_name is None:
                report = f"Агентство {agency_name.strip()} не найден. Период выдачи не закрыт."
                return PayoutResult("not_found", agency_name.strip(), (), 0, report)

            previous = connection.execute(
                """
                SELECT command_source_row_id
                FROM agency_payouts
                WHERE agency_key = ? AND command_source_row_id < ?
                ORDER BY command_source_row_id DESC
                LIMIT 1
                """,
                (requested_key, command_source_row_id),
            ).fetchone()
            previous_cutoff = max(int(previous["command_source_row_id"]) if previous else 0,
                                  self._period_cutoff(command_source_row_id))
            rows = connection.execute(
                """
                WITH latest_reports AS (
                    SELECT register_name, accounting_date, MAX(source_row_id) AS source_row_id
                    FROM messages
                    WHERE source_row_id > ?
                      AND source_row_id < ?
                      AND register_name IS NOT NULL
                    GROUP BY register_name, accounting_date
                )
                SELECT m.accounting_date, o.agency_name, o.amount_minor
                FROM latest_reports AS latest
                JOIN messages AS m ON m.source_row_id = latest.source_row_id
                JOIN agencies AS o ON o.source_row_id = m.source_row_id
                ORDER BY m.accounting_date, m.source_row_id
                """,
                (previous_cutoff, command_source_row_id),
            ).fetchall()
            daily: dict[str, int] = {}
            for row in rows:
                if row["agency_name"].casefold() == requested_key:
                    daily[row["accounting_date"]] = daily.get(row["accounting_date"], 0) + int(row["amount_minor"])

            command_date = datetime.fromtimestamp(command_timestamp, timezone.utc).date().isoformat()
            period_start = min(daily) if daily else command_date
            period_end = max(daily) if daily else command_date
            total_minor = sum(daily.values())
            cursor = connection.execute(
                """
                INSERT INTO agency_payouts (
                    command_source_row_id, agency_key, agency_name, command_timestamp,
                    requester_id, requester_name, previous_cutoff_source_row_id,
                    period_start, period_end, total_minor
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    command_source_row_id, requested_key, canonical_name, command_timestamp,
                    requester_id, requester_name, previous_cutoff, period_start, period_end, total_minor,
                ),
            )
            payout_id = int(cursor.lastrowid)
            for accounting_date, amount_minor in sorted(daily.items()):
                connection.execute(
                    """
                    INSERT INTO agency_payout_items (payout_id, accounting_date, amount_minor)
                    VALUES (?, ?, ?)
                    """,
                    (payout_id, accounting_date, amount_minor),
                )

        by_date = tuple(sorted(daily.items()))
        report = _format_payout_report("Агентству " + canonical_name, period_start, period_end, by_date, total_minor)
        return PayoutResult("created", canonical_name, by_date, total_minor, report)

    def _pending_total_minor(self, accounting_date: str, before_row_id: int) -> int:
        with self._connection() as connection:
            prior_total = connection.execute(
                """
                SELECT COALESCE(MAX(source_row_id), 0) AS row_id
                FROM messages
                WHERE accounting_date = ?
                  AND claimed_total_minor IS NOT NULL
                  AND source_row_id < ?
                """,
                (accounting_date, before_row_id),
            ).fetchone()["row_id"]
            row = connection.execute(
                """
                SELECT COALESCE(SUM(e.amount_minor), 0) AS total
                FROM entries AS e
                JOIN messages AS m ON m.source_row_id = e.source_row_id
                WHERE m.accounting_date = ?
                  AND m.source_row_id > ?
                  AND m.source_row_id < ?
                """,
                (accounting_date, prior_total, before_row_id),
            ).fetchone()
        return int(row["total"])

    def report(self, start_date: str, end_date: str, *, details: bool = True) -> str:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT m.accounting_date, m.source_row_id, e.line_no, e.label, e.amount_minor
                FROM entries AS e
                JOIN messages AS m ON m.source_row_id = e.source_row_id
                WHERE m.accounting_date BETWEEN ? AND ?
                ORDER BY m.accounting_date, m.source_row_id, e.line_no
                """,
                (start_date, end_date),
            ).fetchall()
            checks = connection.execute(
                """
                SELECT check_status, COUNT(*) AS count
                FROM messages
                WHERE accounting_date BETWEEN ? AND ?
                  AND claimed_total_minor IS NOT NULL
                GROUP BY check_status
                """,
                (start_date, end_date),
            ).fetchall()

        by_date: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            by_date.setdefault(row["accounting_date"], []).append(row)
        lines = [f"Отчёт {_display_date(start_date)} — {_display_date(end_date)}"]
        grand_total = 0
        for accounting_date, day_rows in by_date.items():
            day_total = sum(int(row["amount_minor"]) for row in day_rows)
            grand_total += day_total
            lines.append(f"{_display_date(accounting_date)}: {_format_money(day_total)}")
            if details:
                for row in day_rows:
                    lines.append(f"  • {row['label']}: {_format_money(int(row['amount_minor']))}")
        if not by_date:
            lines.append("Нет сохранённых кассовых записей за этот период.")
        lines.append(f"Итого за период: {_format_money(grand_total)}")
        check_counts = {row["check_status"]: int(row["count"]) for row in checks}
        if check_counts:
            lines.append(
                "Проверки total: "
                f"верных — {check_counts.get('ok', 0)}, "
                f"с расхождением — {check_counts.get('mismatch', 0)}, "
                f"непроверенных — {check_counts.get('unverified', 0)}."
            )
        return "\n".join(lines)

    def daily_total_minor(self, accounting_date: str) -> int:
        day = self.statistics()["days"].get(accounting_date)
        return int(day["total_minor"]) if day else 0

    def statistics(self) -> dict:
        with self._connection() as connection:
            day_rows = connection.execute(
                """
                WITH latest_reports AS (
                    SELECT register_name, accounting_date, MAX(source_row_id) AS source_row_id
                    FROM messages
                    WHERE register_name IS NOT NULL
                    GROUP BY register_name, accounting_date
                ), combined AS (
                    SELECT m.accounting_date,
                           COALESCE(m.computed_total_minor, 0) AS total_minor,
                           COUNT(e.id) AS entry_count
                    FROM latest_reports AS latest
                    JOIN messages AS m ON m.source_row_id = latest.source_row_id
                    LEFT JOIN entries AS e ON e.source_row_id = m.source_row_id
                    GROUP BY m.source_row_id
                    UNION ALL
                    SELECT m.accounting_date,
                           COALESCE(SUM(e.amount_minor), 0) AS total_minor,
                           COUNT(e.id) AS entry_count
                    FROM messages AS m
                    JOIN entries AS e ON e.source_row_id = m.source_row_id
                    WHERE m.register_name IS NULL
                    GROUP BY m.source_row_id
                )
                SELECT accounting_date,
                       SUM(total_minor) AS total_minor,
                       SUM(entry_count) AS entry_count
                FROM combined
                GROUP BY accounting_date
                ORDER BY accounting_date
                """
            ).fetchall()
            check_rows = connection.execute(
                """
                WITH latest_reports AS (
                    SELECT register_name, accounting_date, MAX(source_row_id) AS source_row_id
                    FROM messages
                    WHERE register_name IS NOT NULL
                    GROUP BY register_name, accounting_date
                ), current_checks AS (
                    SELECT m.accounting_date, m.check_status
                    FROM latest_reports AS latest
                    JOIN messages AS m ON m.source_row_id = latest.source_row_id
                    WHERE m.claimed_total_minor IS NOT NULL
                    UNION ALL
                    SELECT accounting_date, check_status
                    FROM messages
                    WHERE register_name IS NULL
                      AND claimed_total_minor IS NOT NULL
                )
                SELECT accounting_date, check_status, COUNT(*) AS count
                FROM current_checks
                GROUP BY accounting_date, check_status
                """
            ).fetchall()
        days = {
            row["accounting_date"]: {
                "total_minor": int(row["total_minor"]),
                "entry_count": int(row["entry_count"]),
                "checks": {"ok": 0, "mismatch": 0, "unverified": 0},
            }
            for row in day_rows
        }
        for row in check_rows:
            day = days.setdefault(
                row["accounting_date"],
                {"total_minor": 0, "entry_count": 0, "checks": {"ok": 0, "mismatch": 0, "unverified": 0}},
            )
            if row["check_status"] in day["checks"]:
                day["checks"][row["check_status"]] = int(row["count"])
        return {
            "currency": "USD",
            "timezone": "America/Los_Angeles",
            "business_day_cutoff_hour": 6,
            "days": days,
            "registers": self.register_statistics(),
            "operators": self.operator_statistics(),
            "models": self.model_statistics(),
            "agencies": self.agency_statistics(),
        }


def _atomic_json_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def run_monitor(
    *,
    source_db: Path,
    ledger: Ledger,
    state_path: Path,
    stats_path: Path,
    chat_id: str,
    reply_sender=None,
    review_sender=None,
    guidance_path: Path | None = None,
) -> str:
    guidance_path = Path(guidance_path) if guidance_path else state_path.parent / 'format-guidance.json'
    guidance_after = None
    if guidance_path.exists():
        try:
            gate = json.loads(guidance_path.read_text(encoding='utf-8'))
            after = gate.get('after_source_row_id')
            if gate.get('enabled') is True and type(after) is int and after >= 0:
                guidance_after = after
        except (OSError, ValueError, AttributeError):
            pass  # Missing/invalid opt-in must not change legacy ingestion.
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    else:
        state = {"chat_id": chat_id, "last_seen_message_rowid": 0}
    last_seen = int(state.get("last_seen_message_rowid") or 0)

    connection = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT m.*
            FROM messages AS m
            JOIN sessions AS s ON s.id = m.session_id
            WHERE s.chat_id = ?
              AND m.role = 'user'
              AND m.active = 1
              AND m.id > ?
            ORDER BY m.id ASC
            """,
            (chat_id, last_seen),
        ).fetchall()
    finally:
        connection.close()

    notices: list[str] = []

    def emit(text: str) -> None:
        nonlocal emitted
        if not text:
            return
        if advice and not emitted and text != advice:
            text += '\n\n' + advice
        emitted = True
        if reply_sender is None:
            notices.append(text)
        else:
            message_id = row["platform_message_id"]
            if not message_id:
                raise RuntimeError("No source message ID; refusing a standalone Telegram notice")
            reply_sender(str(message_id), text)

    for row in rows:
        row_id = int(row["id"])
        if any(row[key] == 1 for key in ('is_bot', 'sender_is_bot') if key in row.keys()):
            last_seen = max(last_seen, row_id)
            continue
        content = row["content"] or ""
        enabled = guidance_after is not None and row_id > guidance_after
        compact = None
        advice = None
        emitted = False
        if enabled:
            from cash_compact_formats import parse_compact, format_guidance
            compact = parse_compact(content, float(row['timestamp']))
            advice = format_guidance(content, float(row['timestamp'])) if gate.get('guidance_enabled', True) is True else None
        if ledger.record_period_start(source_row_id=row_id, timestamp=float(row["timestamp"]),
                                      platform_message_id=row["platform_message_id"], content=content):
            last_seen = max(last_seen, row_id)
            continue
        finance_notice = ledger.check_finance_message(source_row_id=row_id,
            timestamp=float(row["timestamp"]), content=content, compact_enabled=enabled)
        if finance_notice is not None:
            if compact and compact.review_lines and review_sender is not None:
                reference = f"https://t.me/c/{chat_id.removeprefix('-100')}/{row['platform_message_id']}" if chat_id.startswith('-100') and row['platform_message_id'] else f"сообщение {row['platform_message_id']}"
                review_sender(f'БАБЛОМАТ — {compact.name}, дата/период требует уточнения, {reference}\n'
                    + '\n'.join(compact.review_lines) + '\nУточни дату/период и исходные выражения. Суммы не добавлены к выручке.')
            emit(finance_notice)
            last_seen = max(last_seen, row_id)
            continue
        payout_command = _parse_payout_command(content)
        if payout_command is not None:
            operator_name, requester_id, requester_name = payout_command
            agency_match = re.fullmatch(r"(?:агентству|агентство)\s+(.+)", operator_name, re.IGNORECASE)
            if agency_match:
                payout = ledger.create_agency_payout(
                    agency_name=agency_match.group(1).strip(),
                    command_source_row_id=row_id,
                    command_timestamp=float(row["timestamp"]),
                    requester_id=requester_id,
                    requester_name=requester_name,
                )
                emit(payout.report)
                last_seen = max(last_seen, row_id)
                continue
            payout = ledger.create_operator_payout(
                operator_name=operator_name,
                command_source_row_id=row_id,
                command_timestamp=float(row["timestamp"]),
                requester_id=requester_id,
                requester_name=requester_name,
            )
            if payout.status == "not_found":
                model_name = re.sub(r"^модели\s+", "", operator_name, flags=re.IGNORECASE)
                payout = ledger.create_model_payout(
                    model_name=model_name,
                    command_source_row_id=row_id,
                    command_timestamp=float(row["timestamp"]),
                    requester_id=requester_id,
                    requester_name=requester_name,
                )
            emit(payout.report)
            last_seen = max(last_seen, row_id)
            continue
        if parse_message(content).register_name is None and compact is None:
            last_seen = max(last_seen, row_id)
            continue
        result = ledger.process_message(
            source_row_id=row_id,
            timestamp=float(row["timestamp"]),
            platform_message_id=row["platform_message_id"],
            content=content,
            compact_enabled=enabled,
        )
        last_seen = max(last_seen, row_id)
        if result.status == 'operator_accrual':
            dates = compact.dates
            date = _display_date(dates[0]) if len(dates) == 1 else f'{_display_date(dates[0])} — {_display_date(dates[-1])}'
            emit(f'**{date}:**\nНачисление оператору {compact.operator} сохранено / сверено; это не выплата.')
        elif result.status == "ok":
            emit(ledger.cash_notice(row_id))
        elif result.status == "mismatch":
            difference = result.difference_minor or 0
            emit(
                "⚠️ Total не сходится: "
                f"по строкам {_format_money(result.computed_total_minor or 0)}, "
                f"указано {_format_money(result.claimed_total_minor or 0)}, "
                f"расхождение {_format_money(difference)}."
            )
        elif result.status == "unverified":
            parsed = parse_message(content)
            with ledger._connection() as c:
                reviews = tuple(r[0] for r in c.execute('SELECT line FROM parse_reviews WHERE source_row_id=? ORDER BY line_no', (row_id,)))
            if reviews:
                if review_sender is not None:
                    date = (_display_date(compact.dates[0]) if compact and compact.dates else 'дата требует уточнения') if compact else _display_date(_extract_accounting_date(content, float(row["timestamp"])))
                    reference = f"https://t.me/c/{chat_id.removeprefix('-100')}/{row['platform_message_id']}" if chat_id.startswith('-100') and row['platform_message_id'] else f"сообщение {row['platform_message_id']}"
                    review_sender(
                        f"БАБЛОМАТ — {compact.name if compact else parsed.register_name}, {date}, {reference}\n"
                        "Неоднозначные строки (не добавлены автоматически):\n"
                        + "\n".join(reviews)
                        + "\nУточни, какие числа здесь суммы денег и к кому относятся. Проверка Total не завершена."
                    )
                emit("⚠️ Проверка Total не завершена: есть нераспознанные суммы. Запись сохранена для уточнения.")
            else:
                emit("⚠️ Total указан, но нет однозначных сумм для проверки.")
        if advice and not emitted:
            emit(advice)

    state.update({"chat_id": chat_id, "last_seen_message_rowid": last_seen})
    _atomic_json_write(state_path, state)
    _atomic_json_write(stats_path, ledger.statistics())
    return "\n".join(notices)


def _display_date(value: str) -> str:
    day = datetime.strptime(value, "%Y-%m-%d")
    weekday = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")[day.weekday()]
    return day.strftime("%d.%m") + f" ({weekday})"


def _format_money(amount_minor: int) -> str:
    sign = "-" if amount_minor < 0 else ""
    absolute = abs(amount_minor)
    whole, cents = divmod(absolute, 100)
    return f"{sign}${whole:,}.{cents:02d}"


def _format_payout_report(
    operator_name: str,
    period_start: str,
    period_end: str,
    by_date: tuple[tuple[str, int], ...],
    total_minor: int,
) -> str:
    def display_date(value: str) -> str:
        return _display_date(value)

    lines = [
        f"Выдача {operator_name}",
        f"Период: {display_date(period_start)} — {display_date(period_end)}",
    ]
    for accounting_date, amount_minor in by_date:
        lines.append(f"{display_date(accounting_date)} — {_format_money(amount_minor)}")
    lines.append(f"Итого к выдаче: {_format_money(total_minor)}")
    return "\n".join(lines)


def _amount_minor(token: str) -> int:
    cleaned = token.replace(" ", "").replace(",", ".")
    if "." in cleaned:
        whole, fraction = cleaned.split(".", 1)
        fraction = (fraction + "00")[:2]
    else:
        whole, fraction = cleaned, "00"
    sign = -1 if whole.startswith("-") else 1
    whole = whole.lstrip("+-") or "0"
    return sign * (int(whole) * 100 + int(fraction))


def _extract_accounting_date(content: str, timestamp: float) -> str:
    fallback = datetime.fromtimestamp(timestamp, timezone.utc)
    is_register_report = parse_message(content).register_name is not None
    if is_register_report:
        fallback = datetime.fromtimestamp(timestamp, ZoneInfo("America/Los_Angeles"))
    for raw_line in content.splitlines():
        match = ACCOUNTING_DATE_RE.match(raw_line)
        if not match:
            continue
        day, month, year = match.groups()
        full_year = fallback.year if year is None else int(year)
        if full_year < 100:
            full_year += 2000
        try:
            return datetime(full_year, int(month), int(day), tzinfo=timezone.utc).date().isoformat()
        except ValueError:
            continue
    # Nightly reports received before 06:00 Pacific belong to the day just ended.
    if is_register_report and fallback.hour < 6:
        return (fallback.date() - timedelta(days=1)).isoformat()
    return fallback.date().isoformat()


def _parse_payout_command(content: str) -> tuple[str, str | None, str | None] | None:
    requester_id = None
    requester_name = None
    body: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        sender = SENDER_RE.match(line)
        if sender:
            requester_name, requester_id = sender.groups()
            continue
        body.append(line)
    if len(body) != 1:
        return None
    match = PAYOUT_COMMAND_RE.fullmatch(body[0])
    if not match:
        return None
    return match.group(1).strip(), requester_id, requester_name


def _payment_split(line: str) -> int | None:
    """Read an explicit deposit/payment addition, not a second client charge."""
    # Amount-bearing parentheses are payment components, unlike holder names.
    terms = line.split('+')
    if len(terms) >= 2:
        amount_terms = [re.fullmatch(
            r"\s*(?:zelle|venmo|cash|cashapp|paypal|apple\s+pay)\s*"
            r"\(\s*(\d+(?:[,.]\d{1,2})?)\s*(?:депозит)?\s*\)\s*",
            term, re.IGNORECASE) for term in terms]
        if all(amount_terms):
            return sum(_amount_minor(term.group(1)) for term in amount_terms)
    clean = re.sub(r"\([^)]*\)", "", line).strip()
    match = re.search(r"(?<![\w:/])([0-9]+(?:[,.][0-9]{1,2})?)\s*\+\s*([0-9]+(?:[,.][0-9]{1,2})?)(?![\w.,])", clean)
    if not match:
        return None
    prefix, suffix = clean[:match.start()].strip(), clean[match.end():].strip()
    payment = r"(?:депозит|zelle|cash|cashapp|venmo|paypal)"
    contextual = bool(re.match(r"^" + payment + r"\b", prefix, re.IGNORECASE))
    bare = not prefix and (not suffix or bool(re.fullmatch(payment, suffix, re.IGNORECASE)))
    if not (contextual or bare) or AMOUNT_RE.search(prefix + " " + suffix):
        return None
    return _amount_minor(match.group(1)) + _amount_minor(match.group(2))


def parse_message(content: str) -> ParsedMessage:
    sender_id = None
    sender_name = None
    register_name = None
    entries: list[Entry] = []
    operators: list[OperatorAmount] = []
    claimed_total = None
    model_amount = None
    agency_amount = None
    review_lines: list[str] = []

    lines = [line.strip() for line in content.splitlines()]
    for line in lines:
        sender = SENDER_RE.match(line)
        if sender:
            sender_name, sender_id = sender.groups()
            continue
        heading = REGISTER_HEADING_RE.match(line)
        if heading:
            words = re.findall(r"[^\W_]+", heading.group(1), re.UNICODE)
            if words:
                raw_name = " ".join(words)
                register_name = raw_name.capitalize() if raw_name.isupper() or raw_name.islower() else raw_name
            break

    if register_name is not None:
        after_total = False
        last_client_total = None
        for line in lines:
            if not line or SENDER_RE.match(line) or REGISTER_HEADING_RE.match(line) or DATE_RE.match(line):
                continue
            amount_matches = list(AMOUNT_RE.finditer(line))
            if TOTAL_RE.search(line) and amount_matches:
                claimed_total = _amount_minor(amount_matches[-1].group(0))
                after_total = True
                continue
            if after_total:
                agency_match = AGENCY_AMOUNT_RE.fullmatch(line)
                if agency_match and agency_amount is None:
                    agency_amount = _amount_minor(agency_match.group(1))
                model_match = MODEL_AMOUNT_RE.fullmatch(line)
                if model_match and model_amount is None:
                    model_amount = _amount_minor(model_match.group(1))
                operator_match = RU_OPERATOR_RE.match(line) or EN_OPERATOR_RE.match(line)
                if operator_match:
                    name = operator_match.group(1).strip().title()
                    operators.append(OperatorAmount(name, _amount_minor(operator_match.group(2))))
                elif re.search(r"\b(?:оператор|опер|operator)\b", line, re.IGNORECASE) and AMOUNT_RE.search(line):
                    review_lines.append(line)
                continue
            tariffs = list(HR_AMOUNT_RE.finditer(line))
            split_total = _payment_split(line) if not tariffs else None
            if split_total is not None:
                if last_client_total is None:
                    entries.append(Entry(label=line, amount_minor=split_total))
                elif split_total != last_client_total:
                    review_lines.append(line)
                # Matching split describes the tariff already counted above.
                continue
            start_entry = len(entries)
            excluded_extra_minor = 0
            for match in tariffs:
                entries.append(Entry(label=line, amount_minor=_amount_minor(match.group(1))))
            for match in PLUS_AMOUNT_RE.finditer(line):
                amount = _amount_minor(match.group(1))
                if EXPLICIT_EXTRA_SUFFIX_RE.match(line[match.end():]):
                    # Keep the original label/raw receipt, but exclude marked
                    # extras from base revenue. Actual payment splits include it.
                    excluded_extra_minor += amount
                elif line[match.start() + 1:match.start() + 2].isspace():
                    # Unlabelled spaced tariff additions remain a review case.
                    review_lines.append(line)
                else:
                    entries.append(Entry(label=line, amount_minor=amount))
            if tariffs:
                last_client_total = sum(e.amount_minor for e in entries[start_entry:]) + excluded_extra_minor
            elif re.search(r"клиент|client", line, re.IGNORECASE):
                last_client_total = None
            # Independent coverage pass: a number not consumed by the money parser
            # must never silently disappear, even when the partial sum matches Total.
            remainder = HR_AMOUNT_RE.sub(" ", line)
            remainder = PLUS_AMOUNT_RE.sub(" ", remainder)
            remainder = re.sub(r"\b\d{1,2}:\d{2}\s*(?:am|pm)?\b", " ", remainder, flags=re.IGNORECASE)
            remainder = re.sub(r"\b\d+(?:[.,]\d+)?\s*(?:min(?:utes)?|mins|мин(?:ут)?|hr|hrs|hours?|час(?:а|ов)?)\b", " ", remainder, flags=re.IGNORECASE)
            remaining_numbers = list(AMOUNT_RE.finditer(remainder))
            transaction = bool(re.search(r"клиент|client", line, re.IGNORECASE))
            ambiguous_price = any(
                not re.fullmatch(r"\d+(?:[.,]\d{1,2})?", token)
                for token in re.findall(r"/\s*(\d+(?:[ ,.\u00a0\u202f]+\d+)*)", line)
            )
            if ambiguous_price or any(_amount_minor(m.group()) > 10000 for m in remaining_numbers) or (
                transaction and not HR_AMOUNT_RE.search(line) and remaining_numbers
            ):
                review_lines.append(line)
        return ParsedMessage(
            sender_id=sender_id,
            sender_name=sender_name,
            register_name=register_name,
            entries=tuple(entries),
            operators=tuple(operators),
            claimed_total_minor=claimed_total,
            model_amount_minor=model_amount,
            agency_amount_minor=agency_amount,
            review_lines=tuple(review_lines),
        )

    for line in lines:
        if not line or line.startswith("[Replying to:"):
            continue
        sender = SENDER_RE.match(line)
        if sender:
            sender_name, sender_id = sender.groups()
            continue
        if TIME_RE.match(line) or DATE_RE.match(line):
            continue
        amount_matches = list(AMOUNT_RE.finditer(line))
        if not amount_matches:
            continue
        amount_match = amount_matches[-1]
        amount = _amount_minor(amount_match.group(0))
        if TOTAL_RE.search(line):
            claimed_total = amount
            continue
        if ":" in line:
            label = line.split(":", 1)[0].strip()
            entries.append(Entry(label=label, amount_minor=amount))
        elif BARE_AMOUNT_RE.match(line):
            entries.append(Entry(label=f"Сумма {len(entries) + 1}", amount_minor=amount))
        elif ACCOUNTING_RE.search(line):
            label = line[: amount_match.start()].strip(" :=—-+") or f"Сумма {len(entries) + 1}"
            entries.append(Entry(label=label, amount_minor=amount))

    return ParsedMessage(
        sender_id=sender_id,
        sender_name=sender_name,
        register_name=register_name,
        entries=tuple(entries),
        operators=tuple(operators),
        claimed_total_minor=claimed_total,
    )


def main(argv: list[str] | None = None) -> int:
    default_home = Path(os.environ["HERMES_HOME"]) if os.environ.get("HERMES_HOME") else None
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=default_home, required=default_home is None)
    parser.add_argument("--chat-id", default=os.environ.get("BABLOMAT_CHAT_ID"))
    parser.add_argument("--ledger", type=Path)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("monitor")
    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("--from-date", required=True)
    report_parser.add_argument("--to-date", required=True)
    report_parser.add_argument("--details", action="store_true")
    args = parser.parse_args(argv)

    if args.command != "report" and not args.chat_id:
        parser.error("--chat-id or BABLOMAT_CHAT_ID is required")
    ledger_path = args.ledger or args.home / "cash-ledger" / "ledger.db"
    ledger = Ledger(ledger_path)
    if args.command == "report":
        print(ledger.report(args.from_date, args.to_date, details=args.details))
        return 0

    output = run_monitor(
        source_db=args.home / "state.db",
        ledger=ledger,
        state_path=args.home / "cash-ledger" / "monitor-state.json",
        stats_path=args.home / "cash-ledger" / "daily-stats.json",
        chat_id=args.chat_id,
    )
    if output:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
