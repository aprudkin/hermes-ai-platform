# Bablomat accounting source archive

Deterministic cash/finance parsing, operator-only compact accruals, payout checkpoints,
source-anchored replies, correction receipts, clarification cases and an on-demand
Bablomat digest. This is **not** Yandex/Jira mail monitoring. Nothing here installs
or activates a service, plugin or schedule. The digest schedule remains cancelled;
the six-hour escalation remains paused and activity scanning remains retired.

## Portable accounting (without unrelated conversations)

[`PORTABILITY.md`](PORTABILITY.md) describes the offline `export`, `verify` and
`import` helper in `scripts/bablomat_portable.py`. It keeps the complete accounting
ledger and delivery audit, filters linked source evidence out of the shared Hermes
history, preserves Telegram access settings, and prepares a new inactive profile.
The cleaned [Bablomat skill](skills/bablomat-accounting/SKILL.md) contains accounting
rules without the old infrastructure/social scheduling instructions. Neither the
helper nor source publication captures a live profile or activates a bot.

## Offline verification

```sh
HERMES_SRC=/path/to/pinned/hermes PYTHON=python3 sh tests/accounting_test.sh
```

Run from the repository root. Uses Python 3.10+ standard library `unittest`, SQLite
and system IANA timezone data. The inherited test guard blocks socket operations
and any non-temporary SQLite/credential access, including child Python processes.
Portability tests additionally require Python 3.11+, PyYAML, python-dotenv and the
same real Hermes checkout pinned in the root README, for schema reopen/append
coverage. An in-memory SQLite schema probe is allowed; non-temporary file-backed
state and socket operations remain blocked.
Fixtures explicitly inject synthetic routing IDs and temporary profiles; those IDs
are not production defaults. Long source-shaped report fixtures have new sample
amounts/dates and fictitious participants/holders. Ordinary small arithmetic
examples are anonymized. The implemented Anna/Анна canonicalization remains because
it is a business rule, not routing information.

## Configuration and retained entry points

No profile home or Telegram recipient is built in. Set `HERMES_HOME` or pass
`--home` explicitly. Every operational observation DB, ledger, cursor, receipt and
export stays under that explicitly chosen home; none is included here.

| Variable | Meaning |
| --- | --- |
| `BABLOMAT_CHAT_ID` | Source bookkeeping supergroup; CLI also supports `--chat-id` |
| `BABLOMAT_REVIEW_CHAT_ID` | Shared clarification supergroup, not the source group |
| `BABLOMAT_ELENA_ID` | Elena's numeric Telegram user ID |
| `BABLOMAT_OWNER_ID` | Owner's numeric Telegram user ID |
| `BABLOMAT_PERIOD_AUTHORIZED_IDS` | Comma-separated authorized IDs for exact new-period markers; empty means nobody |

Set configuration **before import/process startup**. Missing review routing fails
before case DB creation. Home/source-chat CLI requirements fail before ledger
initialization. Pure parsers need no routes. Historical `PrivateReviewSender` keeps
its import name, but clarification delivery goes to the configured shared group
with an exact Elena mention and the current address **Ле**.

`scripts/cash_ledger_monitor.py` calculates/reports without a transport.
`scripts/cash_ledger_reply_monitor.py` is the retained source-reply sender; manually
invoking it with configured routing is a real operation, not a dry run.
Live sending additionally requires `python-dotenv` and a token in the explicitly
chosen profile's `.env`; credentials are neither copied nor loaded by the tests.
The escalation monitor and preserved shell entry point require an explicit
`--enabled` for six-hour processing; the shell wrapper does not add it. The retired
activity classifier resolves no transport and is disabled without an explicitly
injected offline sender. Digest collection/export has no sending/scheduling code.

## Known unfixed source defects — not a production readiness claim

1. **`Ledger.confirm_period_closure` is absent.** A fresh isolated run of the original
   source and original tests reproduces `AttributeError`; this is not a stale harness
   import. The original intended-behavior test is retained as `expectedFailure` in
   `tests/test_cash_period_closures.py`. No closure method or automatic
   confirmation-to-payment support has been invented. Further assertions in that
   originally failing test are not verified.
2. **Quoted old reports can be parsed again and create duplicate clarifications.**
   A synthetic old-report quote produces two clarification requests where only one
   should exist. `tests/test_cash_quoted_report.py` records this as an
   `expectedFailure`; the parser/monitor behavior is deliberately not fixed here.
   Repeated-question deduplication by exact question text is not a fix: the new
   source-message reference makes the question different.

A successful wrapper reports both expected failures explicitly. It does **not**
mean those business defects pass. Unexpected successes also fail the suite so that
future fixes require removing the corresponding debt annotation. No private ledger,
source report archive, DB, credentials, receipts, cursor or live task register is
part of this source package.
