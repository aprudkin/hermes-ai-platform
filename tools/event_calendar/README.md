# Notebook event calendar — v1.0.0

Local Pillow tools, JSON input schema 1. No mail/route discovery, accounts,
credentials, sender, network, scheduling, or cycle-state dependency. The tiny
`style.py` contains only notebook palette/font helpers, not medical logic.
Versioning these files does not activate or change any existing reminder.

## Requirements and CLI

Python 3.11+, Pillow, system DejaVu Sans/Serif; serif italic falls back to
Liberation Serif Italic. On Debian: `fonts-dejavu-core` plus
`fonts-dejavu-extra` (or `fonts-liberation`). No browser or image API.
Run from the repository root, with your chosen Python environment:

```sh
python3 tools/event_calendar/__main__.py day --input tools/event_calendar/examples/synthetic.json --today 2030-11-03 --output /tmp/event-calendar-example/day.png
python3 tools/event_calendar/__main__.py month --input tools/event_calendar/examples/synthetic.json --today 2030-11-03 --output /tmp/event-calendar-example/month.png
python3 tools/event_calendar/__main__.py caption --input tools/event_calendar/examples/synthetic.json --today 2030-11-03
bash tests/event_calendar_test.sh
```

Direct script invocation also works from another directory with absolute paths and
avoids collision with Hermes’ unrelated top-level `tools` package.

All output manifests/payloads are JSON on stdout. `caption` writes no file and
sends nothing. Store its `caption` below the picture with HTML parse mode,
`show_caption_above_media=false`, `has_spoiler=false`; no spoilers. Important
date/departure/start are bold; the destination is linked to a Yandex Maps search
for **venue plus full address**, followed immediately by `<code>address</code>`.
No origin address is needed or displayed. The payload has no chat/account fields.
Caption lengths over 1024 UTF-16 units are rejected rather than truncated.

## Input contract

Root: `schema_version: 1`. `month` needs `events`; `day`/`caption` need `event`
and `route`. The example combines both. Extra root metadata is ignored.
Each event needs nonempty single-line `name`, `venue`, ISO `date` (YYYY-MM-DD),
24-hour `time` (HH:MM). Caption additionally requires full destination `address`.
Optional `previous_time` is shown in monthly agenda. Optional boolean `synthetic`
marks an invented example; all committed examples are explicitly synthetic.
Event/route text is validated; HTML is escaped and map queries URL-encoded.
No event/end/duration or private origin is inferred.

Route input requires integer `travel_minutes_used`, integer
`arrival_buffer_minutes`, ordered `observed_minutes_range` containing the used
value, `observed_at` (ISO timestamp **with offset**) and
`estimate_kind: "observed"`. Timestamp cannot be after the supplied reference
`today` in Moscow. This is saved observed evidence, **not a live lookup and not a
forecast for tomorrow**. Image shows observation date/time; caption also shows
year, evidence caveat, chosen duration, buffer, rounding and no taxi waiting time.
There is no freshness claim: caller must refresh evidence separately if needed.
Synthetic numbers are never presented as actual observed traffic in fixtures.

## Reviewed geometry and limits

Daily v4 remains **1080 × 1640**, notebook palette/type, enlarged labels. Departure
is start minus driving estimate minus explicit buffer, rounded **down** to five
minutes. The horizontal axis is x=96…984 at y=1040; the left boundary is exactly
one hour before departure; right boundary one hour **after event start**. For the
synthetic 19:00/16+30 example: departure18:10, viewport17:10–20:00. Hatching is
only the start label, never a claimed duration. The four removed explanatory
notes/footer stay removed. Cross-midnight windows deliberately fail.
Monthly remains1080×1660, at most two event-bearing months/four numbered events;
today is outlined when visible. Long labels fit available width.

PNG writes are atomic and0600; newly created directories request0700. Existing
caller-owned directory permissions are not changed. Input/output aliases are
rejected by CLI. Output/manifests can contain caller-provided private events;
keep them outside Git. No live sending or cron integration is included.
