#!/usr/bin/env python3
"""Template: emit one Telegram alert after the first matching observed message.

Copy under $HERMES_HOME/scripts/, set CHAT_ID/OWNER_ID, and customize
is_match(). Run from a no-agent cron job; empty stdout intentionally sends
nothing.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path

HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
DB = HOME / "state.db"
STATE_PATH = HOME / "monitor-state" / "first-observed-match.json"
CHAT_ID = "REPLACE_WITH_NEGATIVE_CHAT_ID"
OWNER_ID = "REPLACE_WITH_NUMERIC_USER_ID"
OWNER_LABEL = "Owner"

TERMS = re.compile(
    r"\b(?:total|balance|receipt|expense|income|cash|касс\w*|итог\w*|остаток\w*|"
    r"приход\w*|расход\w*|выручк\w*)\b",
    re.IGNORECASE,
)
NUMBER = re.compile(r"(?<!\w)[-+]?\d+(?:[ .]\d{3})*(?:[,.]\d{1,2})?(?!\w)")


def is_match(content: str) -> bool:
    """Require both domain evidence and a figure; customize for the workflow."""
    body = content.split("\n", 1)[-1].strip()
    return bool(TERMS.search(body) and NUMBER.search(body))


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"last_seen": 0, "alerted": False, "matched": None}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, STATE_PATH)


def main() -> None:
    state = load_state()
    if state.get("alerted"):
        return

    last_seen = int(state.get("last_seen") or 0)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
    try:
        rows = con.execute(
            """
            SELECT m.id, COALESCE(m.content, '')
            FROM messages AS m
            JOIN sessions AS s ON s.id = m.session_id
            WHERE s.chat_id = ?
              AND m.observed = 1
              AND m.active = 1
              AND m.id > ?
            ORDER BY m.id ASC
            """,
            (CHAT_ID, last_seen),
        ).fetchall()
    finally:
        con.close()

    matched = None
    for row_id, content in rows:
        last_seen = max(last_seen, int(row_id))
        if matched is None and is_match(content):
            matched = int(row_id)

    state["last_seen"] = last_seen
    if matched is not None:
        state.update(alerted=True, matched=matched)
    save_state(state)

    if matched is not None:
        print(f"[{OWNER_LABEL}](tg://user?id={OWNER_ID}), the first matching message arrived. What next?")


if __name__ == "__main__":
    main()
