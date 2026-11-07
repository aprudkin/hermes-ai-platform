---
name: cycle-tracker
description: "Use when tracking periods and cycle reminder replies."
version: 1.0.0
license: MIT
metadata:
  hermes:
    tags: [cycle, periods, reminders, privacy]
    related_skills: [hermes-agent, shared-tasks-reminders]
---

# Cycle tracker — portable source snapshot

Use for consensual tracking and explicit start/end replies, not diagnosis.
This reviewed snapshot contains reusable code and synthetic fixtures only.
It does not claim delivery is active or verified, restore private medical data,
install the gateway plugin, enable a scheduler, or authorize a live group test.
The existing no-live-group-test restriction must remain in force.

## State and privacy

Resolve the active profile via Hermes, never a hardcoded account/home.
Sensitive state belongs outside Git in a dedicated0700 directory with0600 JSON
and PNGs. All CLI state/output/database/credential paths are explicit. Never read
another profile's medical state or upload it to image APIs. Examples from2030
and all test identities are synthetic. State is not distributed with this skill.
Keep current private facts, automation IDs, receipts and pending/hold records;
source versioning is not medical-data migration or activation.

## Commands (from this skill directory)

```text
python3 scripts/cycle_engine.py --state STATE forecast
python3 scripts/cycle_engine.py --state STATE preview --at 2030-02-05T10:00:00+03:00
python3 scripts/cycle_engine.py --state STATE simulate --from 2030-02-05 --days 4
python3 scripts/cycle_engine.py --state STATE respond --actor ACTUAL_USER_ID --message-id CHAT_ID:MESSAGE_ID --today YYYY-MM-DD --action start --date YYYY-MM-DD
python3 scripts/render_calendar.py --state STATE --output OUTPUT --today YYYY-MM-DD
python3 scripts/cycle_reminder_runner.py --state STATE --dry-run
bash test.sh
```

`preview`/`simulate` do not mutate the supplied state or send. Simulation delivery
only mutates a fixture/deep copy with stage=fixture. CLI responses use a shared
state.json.lock and atomic0600 saves. `--actor` alone is not proof: obtain the
actual inbound actor/chat/message from trusted Telegram metadata first.

## Notebook calendar

Keep05-notebook paper/ruling, blue ink, rose confirmed days, dotted possible
**start dates**, and an independent today outline. Include only months relevant
to last confirmed interval, today and next-period window, including all months
crossed by either interval. Unknown bleeding end confirms only its first day;
never color intervening days by assumption. No decorative exact ovulation mark.
Renderer consumes engine forecast; state bytes must remain unchanged.

Full-moon crater disks are independent local Meeus calculations, TT→UTC→Moscow,
2000–2100. They neither affect cycle forecast nor imply medical/mood causation.
Reference-date/pixel regressions include leap years, Moscow midnight, and months
with zero/two full moons. Pillow/system DejaVu (+italic fallback) only; no browser.
Render and inspect a synthetic PNG before claiming a visual change verified.

## Explicit answers

Verify real author and authorized group. Never impersonate a confirmer because
someone reports for them. Short yes/no/today/yesterday answers need the exact
latest question reply/marker, current cycle and trusted author. Standalone narrow
“месячные начались/закончились сегодня/вчера/ДД.ММ” may be parsed with metadata.
No private-DM ingestion under group-only authorization. Unsupported/ambiguous,
future, stale, quoted or third-party reports remain pending, never facts.

For “started?” yes/today means explicit start; no means not_started. For “still
bleeding?” yes means ongoing; no requires **last bleeding day**, not an invented
end. Normalize yesterday using local Moscow date. Do not infer end from silence
or usual duration. Unique CHAT_ID:MESSAGE_ID is idempotent and cannot change
meaning. Do not overlap a new cycle with an unclosed one. correct_start/end edit
only the latest cycle, keep before-facts in audit, recalculate; historical edits
require clarification. Resume only explicitly and keep stop/delete requests scoped.

## Forecast and reminders

Cycle length is the interval between confirmed starts, bleeding duration includes
both endpoints. Seed range is a supplied summary, not reconstructed history or
an invented midpoint. With fewer than two observed intervals, expand seed bounds
for observations; leave point=null. With at least two, use up to12 intervals,
median rounded half-day upward and observed min/max. This is a descriptive
heuristic, not calibrated confidence bounds or guaranteed regularity.

An explicitly configured temporary_fixed policy overrides the forecast but not
facts; e.g.28±1 is an **assumption**, not measured regularity. It reanchors only
on confirmed start, never slides with silence, does not silently switch to learned
history and disables ovulation notifications. Do not impose this policy on new
users merely because the synthetic fixture illustrates it.

Expected bleeding end from confirmed-duration median only determines when to
ask, never auto-closes a fact. Conditional ovulation range is next-period earliest
minus16 to latest minus10 days; may occur outside it or not at all. Fewer than two
intervals, spread>7 days, or temporary policy disables actionable ovulation alerts.
The7-day threshold is an engineering filter, not a medical criterion. No safe-day,
contraceptive, pregnancy, mood/personality or diagnostic conclusions.

Runner permits at most one confirmed daily photo, only10:00–10:59 Moscow. Heads-up
is two days before earliest start; then start questions. Open bleeding prioritizes
end questions. Explicit negative/ongoing resets silence and defers to tomorrow;
three unanswered **confirmed deliveries** pause that question, not history.
Preview is not delivery. Runtime status requires private-state/exact-job readback.

## Durable runner and buttons

See [operations/reconstruction](references/live-runner.md) and
[calculation limits](references/design.md). Runner is read-only dry-run by default;
execute requires explicit STATE, DB, credential file and active delivery state.
No getUpdates, second polling connection, DM fallback or automatic uncertain-send
retry. Persist intent and keyboard before HTTP, validate full returned Message
before recording receipt/counters. A sendPhoto response is **not independent
Telegram readback**. Interrupted/preflight/timeout/malformed outcomes hold outbox.
Never reset it just to get a green tick or force a live test with a fake clock.

ct1 buttons use opaque nonce, exact latest confirmed photo/markup, real actor/group/
bot metadata, current cycle/question and Moscow-day expiry. Shared lock enforces
first-answer-wins across text/buttons. “Other date” asks for reply to that same
photo without recording a date or removing keyboard. Gateway must authorize the
callback and run synchronous handler off-loop; only metadata keyboard removal is
allowed, not caption/image edits. Plugin never sends a group message on register.

[Visual comparison notes](references/calendar-variants.md) apply to future mockups;
sensitive design artifacts and task-specific restart/check scripts are not included.
