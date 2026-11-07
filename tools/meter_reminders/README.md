# Meter reminders — portable, explicit routing

Preserved deterministic monthly water/electricity scheduling, conservative
acknowledgment grammar, read-only observation scanning, group/DM membership fallback,
durable send intents/receipts, ambiguous-send holds and sidecar locking. Elena is
addressed only as **Ле**. No live task register, history or recipient is included.

## Offline tests

```sh
PYTHON=python3 sh tests/meter_reminders_test.sh
```

Python 3.10+, Unix `fcntl`, SQLite, IANA timezones, `requests` and `python-dotenv`
are required for the complete source suite. HTTP and token reads are injected;
the inherited guard blocks real sockets and non-temporary state/credential access,
including subprocesses. The suite also exercises the actual cron CLI against a
fresh temporary task register/DB, with both default and explicit `--dry-run` modes.

## Explicit configuration

Set these before import/process startup; there are no production routing defaults:

- `HERMES_HOME`: chosen profile home, or pass `--home` to the CLI.
- `METER_BOT_ID`: expected bot ID, verified with `getMe` only during explicit sending.
- `METER_TASK_ID`: existing canonical meter-task ID; the runner never provisions it.
- `METER_GROUP_ID`: preferred shared Telegram supergroup.
- `METER_USER_IDS`: exactly two distinct numeric user IDs, comma-separated, in owner/Elena order.

The chosen home must contain an explicitly provisioned `shared-tasks/tasks.json`
and compatible saved-observation `state.db`. `reminder_config` must match the
preserved schedule: Europe/Moscow, cycle starts on day 15, first regular reminder
on day 17 at 16:00, repeat every two days, resources `water` and `electricity`, with
preferred group and recipients matching the explicit environment. This package
contains no active task state or schedule-installation code.

Both `scripts/meter_reminder.py` and `scripts/meter_reminder_cron.py` are **read-only,
non-sending by default**, and forward/support `--dry-run`, `--now`, `--report` and
`--home`. Dry-run does not load credentials, check membership, update cursors or
write files. Missing routing fails closed before opening the task register.

Only the explicit `--execute` option enables state updates and real Telegram
operations. It additionally requires a token in the chosen profile's `.env`;
process-environment tokens are not a fallback. Never retry uncertain/inflight sends
without reconciling the canonical reminder state. Preserving this entry point does
not activate a cron job and does not authorize a real send.
