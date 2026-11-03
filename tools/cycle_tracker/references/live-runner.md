# Durable runner — operations and future reconstruction

## Authority and installation boundary

This repository versions source only. It neither installs code into the active
profile nor enables a job or plugin. Current activity, if any, is defined by the
private state and exact scheduler entry, never this document. Keep the no-live-
group-test restriction: synthetic fixtures do not prove future Telegram delivery.
Do not force a due send or press a live button to satisfy a source-versioning test.

On a separately approved reconstruction, place the reviewed skill tree at
`$HERMES_HOME/skills/productivity/cycle-tracker`; keep all five scripts together.
Plugin files may be installed in the chosen profile's `plugins/cycle-buttons`
directory. Native hook compatibility and explicit enabling are separate actions;
verify installed Hermes APIs/docs before doing so. `get_hermes_home()` resolves
only the active profile. The plugin's loader uses the skill's scripts directory.
No second polling client, core patch, restart utility or new service is supplied.

## Explicit paths and private state

`cycle_reminder_runner.py --state STATE` defaults to offline read-only dry-run.
`--at ISO_TIMESTAMP` is permitted only in that mode. No implicit home/state path,
mail source, DB or credential lookup remains. Execution requires `--execute`,
`--state STATE`, `--db DB`, `--env-file ENV` and active opted-in private state.
The optional cron entrypoint forwards those same arguments with `--execute`;
it does not create/schedule a job. The chosen protected environment file contains
`TELEGRAM_BOT_TOKEN`; no token is included here. Avoid shell/logging token values.

State is schema1, Moscow/hour10, explicit numeric confirmer and
`planned_destination=telegram:<supergroup-id>`, plus confirmed facts and runner
activation cursor/time, expected bot ID, receipts/outbox/pending. Configure an
optional plain-text `confirmer_label`, otherwise generic “Участник”. These fields
must come from actual opt-in/trusted metadata during a later authorized setup,
never from synthetic examples. Do not copy or reset a live private state merely
to match repository code. Runner/button/CLI responses share STATE.lock; use a
dedicated0700 state directory,0600 files. No DB/log/state belongs in Git.

## Timing and reply ingestion

A tick may ingest authorized new user rows outside the send window, but at most
one confirmed daily message is generated only10:00–10:59 Moscow. Reading state.db
is read-only SQL restricted to the exact opted-in group, Telegram source, active
user rows after activation baseline/cursor and no future timestamp. Both observed
modes are accepted; no private DMs/getUpdates/global chat sweep. Verify the actual
gateway DB schema and full source/reply envelope remain compatible before use.
Anchored numeric sender envelopes, row chat and optional origin JSON must agree;
body IDs/third-party names are not authorization.

Narrow explicit facts and exact latest-question linked short replies are accepted.
Unsupported/ambiguous/stale/future text stays private pending, not a guessed fact.
“No” to “still bleeding?” requires clarification of the last bleeding day. That
clarification is once, source-replied, in the next allowed daily window. Negative
and ongoing answers reset silence and defer; three unanswered confirmed questions
pause that poll. Explicit answer/resume may restart it. Silence never writes dates.

## Transport and failure handling

Sender preflight verifies expected bot and both group memberships, with fixed
HTTPS api.telegram.org origin, redirects disabled, explicit protect_content=true,
no paid broadcast and caption below/no spoiler. Persist prepared intent and exact
caption/marker/opaque keyboard **before** any HTTP preflight/send. Validate returned
chat/bot/date/photo/caption/text mention/protection/keyboard before receipt/counters.
Native stdout stays empty; otherwise an outer delivery wrapper could duplicate it.
A verified returned Message is not independent readback (Bot API has no getMessage).

Timeout/crash/inflight/malformed result/preflight rejection persists a nonretryable
hold, not a synthetic receipt. Inspect and reconcile against actual target evidence
under a later authorized operation before any retry. Never clear outbox just to
make a job healthy. No getUpdates fallback or DM send on group failure.

## Callback integration

The plugin checks actual actor/chat/message author and adapter authorization before
calling the synchronous handler with metadata off-loop. Handler rechecks explicit
state identities, latest verified receipt/photo/markup, current question/cycle,
nonce, day/expiry and first-answer-wins under shared lock. “Other date” keeps the
photo/keyboard and requests a reply date, never invents a fact. Accepted final
answers permit removal of keyboard metadata only; preserve caption/image. The
plugin reads back the edit response to verify keyboard removal; failed removal
does not discard an already committed answer. The local wiring probe is private
runtime status, not medical history or Telegram delivery evidence.

## Stop and rollback

On an explicit future stop, pause only the exact known job and disable delivery
under state lock; decide ingestion separately. Preserve history, receipts, pending
and hold state. Do not blindly restore a pre-activation backup or duplicate a job.
Do not restart the gateway/change config as part of source packaging. Operational
cutover, true inbound/delivery verification and independent private-data recovery
remain separate owner-authorized work; local tests cannot certify them.
