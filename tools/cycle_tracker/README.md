# Cycle tracker — portable source v1.0.0

Vetted, generic reconstruction of the installed engine,05-notebook renderer,
deterministic reminder/reply runner, durable button handler and native callback
plugin. Code and documentation only: no private state, account IDs, cron records,
receipts, medical-history images or browser designs. The event-calendar package
is separate and never imports this package or reads its state.

## Offline use and tests

Engine: Python3.11+ standard library (Linux `fcntl`). Renderer: Pillow and system
DejaVu Sans/Serif, plus DejaVu Serif Italic or Liberation Serif Italic.
Runner transport tests additionally use httpx and python-dotenv. Native plugin
unit tests use python-telegram-bot (22.8 tested), not a live Telegram connection.
The full test command fails on missing dependencies rather than silently skipping:

```sh
PYTHON=python3 bash tools/cycle_tracker/test.sh
python3 tools/cycle_tracker/scripts/cycle_engine.py --state tools/cycle_tracker/examples/synthetic-state.json forecast
python3 tools/cycle_tracker/scripts/render_calendar.py --state tools/cycle_tracker/examples/synthetic-state.json --today 2030-01-25 --output /tmp/cycle-example/calendar.png
python3 tools/cycle_tracker/scripts/cycle_reminder_runner.py --state tools/cycle_tracker/examples/synthetic-state.json --dry-run --at 2030-02-06T10:00:00+03:00
```

The committed fixture uses invented2030 dates, non-account confirmer identity,
stage=fixture and delivery_enabled=false. Never use it as a person's state.
Tests deny outbound socket connections/DNS in their process; Telegram responses
are clearly synthetic MockTransport/fake-API fixtures, not delivery evidence.
CLI subprocesses only receive temporary/synthetic paths and never execute a due
real transport. No cron/service/plugin is enabled by these commands.

## Source layout and deliberate portability changes

- `SKILL.md`, `references/`: reviewed portable skill snapshot and reconstruction
  constraints; no claims about a specific person's activation or schedule.
- `scripts/cycle_engine.py`, `render_calendar.py`: genuine forecast/facts/atomic
  persistence/renderer code, with forecast limitations and full-moon tests.
- `scripts/cycle_reminder_runner.py`: read-only default; group-only SQL ingestion,
  source-reply parsing, outbox, verified returned-Message receipts and safe holds.
- `scripts/cycle_buttons.py`: current receipt-bound opaque callbacks/expiry and
  first-answer-wins shared lock. Recipient/group now come from explicit state,
  not installation-specific numeric literals. Unauthorized identities are rejected
  before lock/write after a read of the explicit state's configured recipient.
- `scripts/cycle_reminder_cron.py`: optional argument-forwarding no-agent entrypoint,
  not a scheduler installer. No interpreter/home hardcoded; STATE/DB/ENV required.
- `plugin/`: native Hermes callback hook; uses active profile resolution, authorization
  and actual message metadata, `asyncio.to_thread`, verified keyboard-only removal.
- `tests/`: preserved engine/renderer/runner/button/plugin regressions plus
  reconstruction checks, with all installation-specific test identities replaced.

Scripts load siblings, never an installed skill/source from an absolute profile
path. Runner CLI has required `--state`; execute additionally needs `--db` and
`--env-file` and rejects `--at`. No automatic credential/home discovery. Mention
label is state `confirmer_label` (default generic “Участник”), HTML escaped and
returned-entity length checked in UTF-16 units. No person's name/hashtag is baked
into questions or captions. Public Bot API HTTPS origin is intentionally fixed;
redirects, paid broadcasts, unprotected content and DM fallback remain disabled.

## Reconstruction is a separate authorized operation

Do not install from this checkout into live runtime during source reconciliation.
For a future approved reconstruction, preserve private state independently, review
adapter/schema compatibility and consent, and follow `references/live-runner.md`.
A skill installation places this tree at
`$HERMES_HOME/skills/productivity/cycle-tracker/`; optional plugin files go to an
explicit profile-local plugin directory. The plugin loader expects the sibling
scripts in that skill installation (not the former top-level scripts location).
This differs from the current runtime and is **not a drop-in cron change**:
future job invocation must supply absolute STATE/DB/ENV paths. Preserve existing
job IDs/destination/cadence unless separately approved; source versioning alone
changes none of them. No restart helper or live first-day probe is included.

## Known limits

- Only explicit Russian response grammar is parsed. Ambiguous reports stay pending.
- Corrections target only latest cycle. No health-account integration/medical model.
- Moscow timezone/daily10:00 window and supergroup destinations are intentional.
- Uncertain sends cannot be independently queried by Bot API; reconcile manually,
  never clear hold or retry blindly. Receipts are sendPhoto responses, not readback.
- Plugin tests cover callback/factory behavior with a synthetic native client;
  installed Hermes hook compatibility/activation and actual delivery are not proved.
- Medical state is not migrated/initialized; source snapshot does not reconstruct
  a real person's timeline or activation metadata. No live group test is permitted.
