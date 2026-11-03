# Runtime observability and historical notices

Use this procedure when a screenshot, service banner, model label or delayed background result appears inconsistent with the running agent. Diagnose before changing settings; a question about a notice is not a request to switch models, disable compression or restart the gateway.

## 1. Identify the event being explained

- Inspect an attached image with the image-reading tool, then use the original quoted message when available. Preserve what is actually visible; do not invent clipped text.
- Resolve the platform, chat, reply target and original timestamp where retained. Do not identify an old notification from message-number ordering alone.
- Treat internal `platform_message_id` matches as candidates, not proof. Synthetic background notices or imported history can reuse a value; require matching conversation, content, role and chronology. If the original send time is not stored, say so rather than assigning it the timestamp of a later quote.

## 2. Establish current model selection

1. Read only selected nonsecret configuration fields: active profile/home, model default and provider, explicit session overrides and auxiliary-model selections relevant to the symptom.
2. Inspect the current session record for the exact conversation. A group and a private chat can retain different selections; an old session row is not the active session.
3. Filter recent runtime logs for actual request entries belonging to that session, including timestamp, requested model and provider. Do not dump unrelated conversation text, credentials or full configuration.
4. Explain the strongest supported fact: configuration describes the default; a session record describes its selection; a recent request log shows the alias actually requested. None independently proves the provider's internal model weights.

## 3. Trace how the historical notice was constructed

For Hermes Codex compression notices, locate the active implementation rather than assuming a similarly named configuration key selects the model. Useful source discovery:

```python
search_files(pattern='caps context at|autoraise_notice',
             path='<runtime-source>/agent', file_glob='*.py')
```

Read the matching notice builder and marker helper with `read_file`. In implementations that retain the legacy Codex autoraise mechanism, `agent/agent_init.py` exposes the rendered model/from/to fields and a profile-scoped marker path through `_codex_gpt55_autoraise_notice_marker()`.

- Compare the exact model and threshold tuple with the marker's contents and tool-read file metadata. A marker can survive a later model switch and therefore describe an earlier configuration.
- Use marker modification time only as evidence of a recorded write. It does not by itself establish the exact Telegram delivery time or prove that a later duplicate was never sent.
- Separate the notice's context-window/compaction policy from model selection. A command named in a compression notice may affect only the threshold, even when its legacy name mentions an older model family.
- If recent request logs and the notice disagree, state the current request evidence and the historical record separately. Investigate cached presentation or an older event before alleging a live fallback, silently switching models or calling the display broken.

## 4. Handle delayed background results without regressing state

1. Compare the run's start and completion with later actions, especially cancellations and access withdrawal.
2. Distinguish an old read-only observation from a completed external mutation. A late probe showing monitoring enabled cannot override a subsequently verified disabled configuration.
3. For consequential writes, reconcile the exact current external target before reporting success. For unchanged read-only diagnostics, absorb the result without another user-facing service message.
4. Do not reopen cancelled monitoring, recover removed credentials or authenticate to a withdrawn integration merely to repeat an old check. Verify cancellation through scheduler/configuration state and credential presence flags instead.
5. Keep process completion, agent output, network reads and public writes as separate outcomes. A successful run returning silence proves completion, not a feed visit, a chosen subjective motive or a published contribution.

## Diagnose slow replies without assuming weak hardware

- Measure host CPU idle/iowait/steal, MemAvailable, swap, PSI memory/I/O, Docker limits and recent OOM records. A quiet snapshot does not rule out historical spikes, but do not recommend a server upgrade without evidence of resource pressure.
- For specific completed turns, query only the authorized conversation in read-only `state.db`. Normalize SQLite and log timestamps to the same timezone, then match assistant message timestamps to `API call #... latency=...s` completion log timestamps within a narrow tolerance (0.25s worked). Require a unique match and report unmatched calls instead of assigning them by API-call number: concurrent agents interleave logs and call numbers can repeat.
- Sum matched model-call latencies with code and subtract from user-to-saved-final elapsed time. Label the remainder as other time, including tools and orchestration, not pure tool execution. SQLite saved-final time is not a verified Telegram delivery receipt.
- Separate remote model latency, excessive sequential model/tool rounds, provider errors/compression and local resource pressure. A large input context is an observation, not a demonstrated cause of slowness without an A/B test. Collect token counts, not prompt contents; never expose unrelated conversations, credential values or full request dumps.
- For perceived latency, distinguish time to first visible text from time to complete response. In current Hermes, `display.streaming` is CLI-only; gateway streaming resolves the top-level `streaming` configuration and per-platform display overrides (`gateway/display_config.py`). Check actual applicable settings before blaming Telegram buffering. Read reasoning effort, per-model/session overrides and service tier separately; a configured `high` is a hypothesis for slowness, not a measured speedup from changing it. Output-token totals may include reasoning; do not invent a hidden-token breakdown when usage details are unavailable.

### Compare a local client with the gateway

1. Identify the actual client/harness from the user's latest clarification or measurement, not an earlier guess. Record model/provider, effort/service tier, fresh versus existing context, tool use and output size when available. A ChatGPT UI label, a Codex CLI selection and a Pi session log do not establish identical requests or infrastructure.
2. Use the exact same neutral prompt in both surfaces. A short creative task with clear start/end markers avoids search, arithmetic tools and external dependencies. Ask for roughly bounded length rather than elaborate counting constraints, which can themselves add reasoning work.
3. Measure request-to-first-visible-text and request-to-completed-response separately. If a log only records the request and saved final, retain that boundary and leave first-text timing unknown; compute the difference in code and preserve user-reported versus locally verified provenance. Do not invent a missing calendar date.
4. Keep the measured turn free of instrumentation. Read its transcript and API timings on the following turn; do not call tools or append a timing report inside a benchmark that explicitly requests only the response payload.
5. Compare matched workloads before comparing durations. A greeting and a longer story are not a controlled pair. Fresh client versus long-running gateway measures their current end-to-end conditions, not the isolated effect of the harness; an absent paired run remains absent.
6. Only attribute a speed difference to a setting after a comparison that holds the other relevant conditions constant. Where the user's local settings cannot be inspected, request those settings rather than inferring them from perceived speed.

## Report briefly

Give the current verified state, the best-supported explanation of the old message and any remaining uncertainty. Do not repeat the full investigation, infer a delivery date from a marker alone, or promise a configuration change that was neither requested nor performed.
