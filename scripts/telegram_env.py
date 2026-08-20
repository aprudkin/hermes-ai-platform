#!/usr/bin/env python3
from __future__ import annotations

import os
import pathlib
import re
import stat
import sys
from collections.abc import Sequence

EXPECTED_KEYS = (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_USERS",
    "TELEGRAM_ALLOWED_CHATS",
    "TELEGRAM_REQUIRE_MENTION",
    "TELEGRAM_EXCLUSIVE_BOT_MENTIONS",
    "TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES",
)
TOKEN_RE = re.compile(r"^[1-9][0-9]*:[A-Za-z0-9_-]{20,}$")
ASSIGNMENT_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


class InvalidTelegramEnv(ValueError):
    pass


def validate_id_list(value: str, *, positive: bool, field: str) -> None:
    records = value.split(",")
    if not records or any(not item or item != item.strip() for item in records):
        raise InvalidTelegramEnv(f"{field} must be a trimmed non-empty CSV")
    expected = re.compile(r"^[1-9][0-9]*$" if positive else r"^-[1-9][0-9]*$")
    if any(item == "*" or expected.fullmatch(item) is None for item in records):
        raise InvalidTelegramEnv(f"{field} contains an invalid identifier")
    if len(records) != len(set(records)):
        raise InvalidTelegramEnv(f"{field} contains duplicate identifiers")


def parse_source(path: pathlib.Path) -> dict[str, str]:
    if path.is_symlink():
        raise InvalidTelegramEnv("Telegram input must be a regular file, not a symlink")
    source_stat = path.stat()
    if not stat.S_ISREG(source_stat.st_mode):
        raise InvalidTelegramEnv("Telegram input must be a regular file")
    file_mode = stat.S_IMODE(source_stat.st_mode)
    if file_mode not in {0o400, 0o600}:
        raise InvalidTelegramEnv("Telegram input mode must be 0400 or 0600")
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    if len(lines) != len(EXPECTED_KEYS) or any(not line for line in lines):
        raise InvalidTelegramEnv("Telegram input must contain exactly six assignments")
    values: dict[str, str] = {}
    for line in lines:
        match = ASSIGNMENT_RE.fullmatch(line)
        if match is None or match.group(1) in values:
            raise InvalidTelegramEnv("Telegram input contains an invalid or duplicate assignment")
        values[match.group(1)] = match.group(2)
    if set(values) != set(EXPECTED_KEYS):
        raise InvalidTelegramEnv("Telegram input keys do not match the contract")
    if TOKEN_RE.fullmatch(values["TELEGRAM_BOT_TOKEN"]) is None:
        raise InvalidTelegramEnv("TELEGRAM_BOT_TOKEN is structurally invalid")
    validate_id_list(values["TELEGRAM_ALLOWED_USERS"], positive=True, field="TELEGRAM_ALLOWED_USERS")
    validate_id_list(values["TELEGRAM_ALLOWED_CHATS"], positive=False, field="TELEGRAM_ALLOWED_CHATS")
    if values["TELEGRAM_REQUIRE_MENTION"] != "true":
        raise InvalidTelegramEnv("TELEGRAM_REQUIRE_MENTION must be true")
    if values["TELEGRAM_EXCLUSIVE_BOT_MENTIONS"] != "true":
        raise InvalidTelegramEnv("TELEGRAM_EXCLUSIVE_BOT_MENTIONS must be true")
    if values["TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES"] != "false":
        raise InvalidTelegramEnv("TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES must be false")
    return values


def main(argv: Sequence[str]) -> int:
    if len(argv) != 2 or argv[0] != "check":
        print("ERROR: usage: telegram_env.py check PATH", file=sys.stderr)
        return 2
    try:
        source_candidate = pathlib.Path(argv[1])
        if source_candidate.is_symlink():
            raise InvalidTelegramEnv("Telegram input must be a regular file, not a symlink")
        source_path = source_candidate.resolve(strict=True)
        repo_value = os.environ.get("HERMES_REPO_ROOT", "")
        if not repo_value:
            raise InvalidTelegramEnv("HERMES_REPO_ROOT is required")
        repo_path = pathlib.Path(repo_value).resolve(strict=True)
        if source_path == repo_path or repo_path in source_path.parents:
            raise InvalidTelegramEnv("Telegram input must be outside the repository")
        parse_source(source_path)
    except (InvalidTelegramEnv, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
