# Bablomat accounting source archive

Deterministic cash/finance parsing, operator-only compact accruals, payout checkpoints,
source-anchored replies, correction receipts, clarification cases and an on-demand
Bablomat digest. This is **not** Yandex/Jira mail monitoring. Nothing here installs
or activates a service, plugin or schedule. The digest schedule remains cancelled;
the six-hour escalation remains paused and activity scanning remains retired.

## Offline verification

```sh
PYTHON=python3 sh tests/accounting_test.sh
```

Run from the repository root. Uses Python 3.10+ standard library `unittest`, SQLite
and system IANA timezone data. The inherited test guard blocks socket operations
and any non-temporary SQLite/credential access, including child Python processes.
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

## Quote and confirmation boundaries

`cash_message_context.message_body` removes native rendered reply history and
Markdown/HTML quote blocks before classification, date inference, arithmetic or
clarification creation. A fresh report outside a quote still ingests normally;
raw sources stay in the audit. Quoted control/formatting approvals are not money.
The former expected failures now run as ordinary regressions.

`Ledger.confirm_period_closure` validates exact report/event references and the
configured `BABLOMAT_ELENA_ID`, then appends recipient/register-scoped checkpoints.
Models and linked agency close in one SQLite transaction; operator confirmation
closes only that operator's confirmed register. Lifetime accruals remain intact.
Balances and explicit payouts exclude only covered source rows AND accounting
dates, preserving later days even when posted before the confirmed summary.
Late historical reports are retained for review, not reopened as new accruals.

The monitor handles explicit financial confirmations and ordinary approvals of
unambiguous operator/finance summaries. A simple approval of daily cash arithmetic
or a control action is not financial approval. A finance period needs explicit
full dates or an unambiguous enabled compact period; receipt time is not its end.
Unknown historical starts stay unknown. Ambiguities stay pending and use the
existing shared review sender. Replayed confirmations return the frozen notice.
No cursor reset or historical confirmation backfill is included.

### Native Telegram evidence: separate activation

The ordinary Hermes observation table does not currently preserve native reply
IDs or per-message sender identity. Rendered quotations and session user IDs
**cannot** authorize a closure. The monitor accepts trusted native columns when
available, otherwise reads the exact chat/message record from
`cash-ledger/native-inputs.db` through `cash_native_input.read_native`.
Missing or conflicting evidence fails closed.

`plugin/` is an optional startup extension using the installed
`ctx.register_telegram_handler` API. It attaches an exact-chat PTB handler in a
separate negative dispatch group before normal observed/triggered handling. It
neither consumes core handlers nor polls/sends, rewrites prompts, patches Hermes
methods, expands chat access or changes schedules. It records actual native
sender/bot status, new text, reply IDs/full target text, partial quote and time.
Conflicting message reuse preserves every variant and becomes unusable evidence.

For separately authorized activation, place the plugin directory at the chosen
profile's `plugins/accounting-native-input/`, install its companion script in
`scripts/`, set `plugins.entries.accounting-native-input.settings.chat_id` via
`hermes config set`, and deliberately enable it with the normal plugin CLI.
The route has no built-in default and must already be authorized for observation.
A fresh CLI test does not activate an already-running gateway: a safe gateway
restart and later native-record readback are separate activation/verification gates.
Do not replay historical observations or enable the plugin merely to run tests.

The standard offline suite explicitly skips the optional real-Hermes adapter
checks if its dependencies are unavailable. Exercise them separately with the
installed/pinned Hermes source and test dependencies:

```sh
PYTHONPATH="$HERMES_SRC:tools/accounting/scripts:tools/accounting/tests" \
  "$HERMES_TEST_PYTHON" -m unittest test_cash_native_input -v
```

These checks use synthetic PTB messages and temporary state, including both
observed and triggered attribution paths. They do not prove a live Telegram
confirmation, native capture activation or acknowledgment delivery. No private
ledger, source report, credentials, receipts, cursor or task register is published.
