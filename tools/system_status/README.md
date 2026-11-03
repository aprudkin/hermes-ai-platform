# Content-free System status notifier

Recovered from the existing host's
`/usr/local/lib/hermes-manager-status/hermes_manager_status.py` using a read-only
Python source read through the configured SSH alias. Original source SHA-256:
`be80c3e6080ce527a247bcd145a2816c4fa54b8f99c9c7d6287e0dcb0bc141c2`.
The checked-in copy removes host-specific Telegram/chat/job identifiers, adds
fail-closed target configuration, and binds deduplication receipts to the target.
This is source recovery, **not installation, activation or a live-delivery test**.

This standalone standard-library sender emits fixed Russian technical status
text for backup lifecycle events and explicitly allowlisted scheduled jobs.
It does not import social publishers, inspect task prompts/results/errors, handle
inbound messages, or change jobs/schedules. Every send requests
`disable_notification=true`, content protection, and disabled link previews.
It checks bot/chat/admin identity before sending and verifies the returned
message via Telegram's edit/no-change response. This is not independent message
retrieval, nor a guarantee of delivery after an ambiguous network failure.

## Configuration (private, supplied by the operator)

No production Telegram identifiers are defaults in this package.

- `HERMES_STATUS_CHAT_ID`: explicit negative target supergroup ID (required).
- `HERMES_STATUS_BOT_ID`: explicit positive expected manager bot ID (required).
- `HERMES_STATUS_JOB_IDS`: comma-separated reviewed job IDs; absent means no job
  notifications. Excluded jobs stay silent. Never copy historical live job lists
  into Git or infer activation from this source.
- `HERMES_STATUS_LABELS`: path to a private reviewed JSON object mapping allowed
  job IDs to static human-readable technical labels. Default is `job-labels.json`
  beside the installed script; that file is deliberately **not included**.
  Labels must be 5–90 characters, without newlines; review their content because
  configuration is trusted, not automatically redacted.

Existing host paths are preserved: manager home
`/opt/hermes/data/profiles/manager` and private state
`/var/lib/hermes-manager-status`. The runtime transport reads the existing
manager `.env` credential internally; do not print it, copy it into this package,
or pass the token in command arguments. No credential file was read during
source recovery or tests.

## Packaging boundaries

An operator may separately review packaging the script into the existing
root-owned private package directory. The recovered observer service model is
`python3 -I /usr/local/lib/hermes-manager-status/hermes_manager_status.py observe`,
with root-owned configuration supplied to its process environment. Existing
backup unit hooks invoke `backup start` and `backup terminal` using systemd's
`INVOCATION_ID` and `SERVICE_RESULT`. A capture integration can separately emit
`pause-planned` and `unpause-confirmed`; this repository does **not** add capture
hooks or silently create extra notifications.

No installer, service unit, timer, environment file, labels file, deployment
script, or automatic live test is added here. A new/changed installation needs
separate authorization, service hardening review, protected config/receipt paths,
and an actual quiet-delivery acceptance check. Source tests do not establish
that the deployed service uses this configured copy. In particular the existing
host is unchanged and still has its original bindings.

## Durable delivery and observation

The sender fsyncs SQLite intent before network I/O. Existing intent, sent, or
uncertain receipts are never automatically resent. The first observer run
persists an activation cutoff and does not replay historical executions. It
reads selected execution metadata through SQLite read-only/query-only access;
it does not read final outputs, prompts, histories, or error text. Receipt rows
are private runtime state and are never included in Git. Preserve them during
maintenance: changing/removing them changes deduplication and replay behavior.

A target change with an existing event key is refused as a receipt collision;
do not delete receipts just to force a retry. API identity mismatch, lost response,
or failed verification leaves an uncertain receipt requiring deliberate operator
reconciliation, not blind resending. A durable intent may exist without a sent
message; this is at-most-one-attempt behavior, not exactly-once delivery.

## Offline checks

From the repository root:

```sh
/opt/hermes/.venv/bin/python tests/system_status_test.py -v
```

Tests use synthetic identifiers, temporary databases and an injected transport.
They cover quiet payloads, durable intent, no uncertain retry, explicit target
configuration, target-bound receipts, allowlisting, activation cutoff, query-only
observation and connection cleanup. They never call Telegram, read runtime
credentials, SSH to a host, run backups, or install anything.
