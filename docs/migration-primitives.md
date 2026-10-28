# Executed migration primitives — still NOFREEZE

These additions close the **missing executable cold capture** gap in PR #49.
They do not close the production migration admission gap. No source pause/stop,
live capture, transfer, restore, message, schedule activation or target startup
was performed. A complete `migration-site-v2` adapter is deliberately **not**
provided: composing incomplete proofs into `ready: true` would be unsafe.

## Current contract (supersedes the original zero-loss blocker)

The owner accepts possible loss of **unprocessed Telegram input only** during
switching. Preserve processed conversations, memory, files, settings, results and
current cancellations; quarantine uncertain external effects, never blind replay.
The absolute G1 zero-loss legacy bootstrap proof is narrowly waived, not solved.
Read the [revised admission contract and tested non-starting recovery stage](migration-continuity.md).
All-writer quiescence, persistent fencing, independent custody, original-DM fresh
approval and recovery remain required. No production readiness is claimed.

## Cold full bundle

`hermes_backup_bundle.py program GUIDE` now embeds a distinct `capture-cold ROOT
hermes` entry point. Ordinary `capture` retains running/unpaused admission and
owned-pause cleanup. Both use the same runtime configuration/mount admission,
image identity/layer checks, archive payloads, hashes and full verifier.

Cold capture requires a clean exited container (`Running/Paused/Restarting/Dead`
false, PID 0, exit code 0, no OOM, restart policy exactly `no`/0). It does not stop
or unpause anything itself. A paused live container is **not** admitted as cold.
It takes the existing stable backup lock, saves the exact inspected image, writes
real GNU tar state with numeric owners/ACLs/xattrs, compares snapshot bytes/stat
against source, and verifies unchanged container inspection and layer diff before
and after snapshot. The source must remain stopped through gzip packaging.
All errors leave the source stopped; partial stdout is not a published archive.
No normal-capture metadata is fabricated and no normal cleanup is suppressed.

The standard seven payloads plus manifest remain. `container-inspect.json` contains
the **actual stopped** inspection. The manifest adds `capture.mode =
cold-stopped-v1` and timestamped snapshot interval. The verifier validates that
provenance and stopped/restart-disabled inspection, while retaining all existing
full-bundle validations. `compose.restore.json` consequently preserves restart
`no` — it must not be silently changed to the old policy on target. The old
running configuration is separately retained by the fence primitive below.
Legacy regular bundles remain supported; migration admission requires the explicit
cold provenance in addition to ordinary full verification.

Tests execute actual tar/gzip/digest/verifier/restore code, real files and SQLite
integrity/data checks; only Docker is a subprocess fixture with a valid synthetic
image layer/config. **Not** a real Docker daemon, live profile restore, image load,
application startup or independent backup copy.

## Source-host operations

`scripts/hermes_migration_host.py` implements real host-local operations:

- `fence`: durably save full original inspection *before* changing restart policy;
  claim a root-scoped run/store identity, hold host and existing backup locks,
  execute `docker update --restart=no` then bounded `docker stop`, inspect exact
  container/image/configuration again. Uncertain update/stop is reconciled on retry
  without replacing original evidence. Wrong run/store/container is rejected.
  The final stopped inspection is saved separately and compared on every later
  operation: restarting/stopping the same container cannot reuse a stale capture.
- `capture`: hold the host lease through the actual generated cold-capture child,
  write exclusive private `full.tar.gz.pending`, fsync, run full verifier, match
  the manifest to the fenced source, publish `full.tar.gz` without overwrite and
  fsync its digest receipt. Repeated success rechecks the bytes/verifier and source.
  Interrupted pending/unreceipted files require review, never automatic success.
- `revoke`: persist revocation and confirm source remains stopped; further capture
  and fence work is refused. It is **not resume/rollback**. An active/orphan child
  holds the inherited host lease, so revoke reports busy until the real child exits.
  An actual parent-SIGKILL test exercises that lock, not a synthetic receipt.
- `recover(run, guard)` (trusted in-process caller only): revoke local forward
  operations, verify current target fence/revocation/no-activity and cancellation/
  effect reconciliation, then recover the original container and restart policy.
  Durable start intent suppresses uncertain replay; no unguarded recovery CLI.
  See the [executed reversible integration and authority boundary](migration-reversible.md).

These primitives intentionally report `all_writers_fenced: false` and
`independent_copy_verified: false`; they cannot satisfy controller admission.
Docker restart `no` persists in Docker metadata, but does **not** fence a Compose
recreation, host service, another administrator or external app/job. A complete
writer/input/restart inventory, owner/operator authority and proven input drain
must precede real use. The script has no unguarded source-start CLI, target start,
target fence, restore-and-start or permissive preflight method.

Conditional command shapes (not executed on either host):

```text
python3 scripts/hermes_migration_host.py fence --execute --root RUNTIME --state-dir PRIVATE_EXISTING_STORE --run-id RUN
python3 scripts/hermes_migration_host.py capture --execute --root RUNTIME --state-dir PRIVATE_EXISTING_STORE --run-id RUN
python3 scripts/hermes_migration_host.py revoke --execute --root RUNTIME --state-dir PRIVATE_EXISTING_STORE --run-id RUN
```

Run outside the source container using trusted pinned code/dependencies and PATH.
The store must already be private, real, owner-controlled and **outside** the
runtime. Retain the root-scoped owner marker, original inspection, lock inode,
partial files and receipts across interruption. Do not remove them to force a retry.
Keep helpers and `docs/backup-restore.md` in their reviewed repository layout;
this is not yet a host package/installer. A local original is not independent
protection and file permissions are not encryption. Cold capture may need source
raw staging, compressed output and verification scratch simultaneously; budget
that peak explicitly rather than reuse the normal streaming-only space estimate.

## Fixed outbound sender

`scripts/hermes_migration_notice.py` sends only `POST
https://api.telegram.org/bot<locally-resolved-token>/sendMessage` to the configured
positive private owner DM. There is no configurable URL, method, redirect, proxy,
polling or webhook endpoint. The private configuration has exactly `owner_id`,
`chat_id` (equal to owner ID) and absolute `token_file`; token remains local.
Unknown fields and unsafe credential files are rejected. Never put that private
configuration or its token in this repository.

It validates run/owner/chat/nonce/digest/expiry and notification phase, constructs
fixed plain-text ready/blocked messages, and fsyncs intent **before** networking.
Response must confirm exact private DM, bot identity, text and numeric message ID.
A completed identical retry returns the existing receipt. Unknown response,
connection loss, rejection, interruption or response mismatch retains uncertain
intent and prevents all automatic resend. Telegram has no sendMessage idempotency
key/message-readback API: reconcile manually; do not delete intent to retry.
No token or raw HTTP error is logged. Tests exercise real loopback HTTP bytes and
lost/wrong/rejected responses, never Telegram. The injectable connection factory
exists only for in-process tests; the CLI cannot override the endpoint.

Conditional command shape, **no live invocation performed**:

```text
python3 scripts/hermes_migration_notice.py --execute --kind ready --config PRIVATE_CONFIG --state-dir PRIVATE_EXISTING_STORE --controller-state PRIVATE_STATE
```

This is outbound delivery, **not a confirmation bridge**, proof of return-path
availability or independently installed watchdog. Do not send a ready notice
until the whole adapter and the single-receiver confirmation path are proven.
The current `confirm` JSON endpoint alone is not an authenticated Telegram event.
The former SSH forced-command alternative was never accepted by the owner.

## Telegram input-preservation blocker

Read-only inspection on 2026-10-27 matched the running source adapter file to the
locally inspected code, SHA256:

`ce4b5ca688bb94691012b6a62b1767b349c94851e9ec9bcd7aa56d32fe3e3506`

Actual installed `plugins/platforms/telegram/adapter.py`:

- `_start_polling_mode`, lines 2952–2954, passes
  `drop_pending_updates=not is_reconnect`. It does **not** contain a
  `drop_pending_on_cold_boot` knob. The later documentation audit did not find
  that setting in the fetched official page either; the earlier claim about
  latest docs was not substantiated. An unsupported flag proves nothing.
- `_held_inbound_events` and text/photo batches are process-memory lists/maps.
  Comments explicitly note PTB has advanced the offset before this hold queue;
  Telegram will not redeliver those events. A filesystem snapshot excludes them.
- Installed PTB `_updater.py`, lines 364–366, enqueues updates then advances
  `_last_update_id`, independently of application completion. Its shutdown cleanup
  (390–414) calls getUpdates at that offset to acknowledge already queued updates.

Offline execution of those **exact AST-extracted method bodies** with an in-process
fake bot confirmed cold drop=true/reconnect drop=false and shutdown acknowledgement
of an update still unhandled in the queue. This is a source-behavior probe, not
live polling. The live process's offset, queue depth and in-flight external effects
were not exported/read: **unknown, not zero**. Do not claim they were preserved.
No getUpdates call, webhook change, competing receiver or live message was made.

Current authoritative docs:
[Telegram cold boot and repeated updates](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/telegram).
A documentation setting or a newer upstream version would not prove behavior
of this installed revision. The exact installed probes, not an assumed feature
name, establish the observed ACK/cold-boot behavior.

The live read-only DB schema distinguishes `messages.id` (local row ID) from
`messages.platform_message_id` and contains session source/profile/user/chat/type.
There is no basis to accept a plain imported JSON approval or treat a DB row as
confirmed Telegram delivery. A future trusted dialogue bridge must bind:

1. target process instance + startup receipt + exact run/nonce;
2. new owner update/message in the original private DM, above both restored row
   and Telegram baselines (different identifiers, not interchangeable);
3. reply to this run's challenge, real assistant turn and actual send receipt;
4. original bounded acceptance window, current cancellations and replay decisions.

**Superseded zero-loss requirement:** the earlier gate demanded a complete
commit-before-ACK legacy export/replay path for every input. The owner has now
accepted loss at the unprocessed-input boundary only. That historical guarantee
is not claimed and is no longer an absolute prerequisite for this transition.
What remains mandatory is processed-state quiescence, preservation/reconciliation
of started or uncertain effects, single polling ownership and authenticated fresh
owner approval. See [the exact revised admission obligations](migration-continuity.md).
An inbox file alone does not provide an approval bridge or application replay.
No such production integration is claimed here.

## Remaining production gates and timing

Target independent host-key/provider identity, owner rescue/recovery keys,
all-host fencing/recreation authority, independent fresh archive copy, target
isolated restore/application acceptance, target delta preservation/reconciliation,
and a working owner Plan B still block activation. The existing Plan B submits
intent to the controller; it is not a standalone proven host-recovery executor.
No host package, service or timer was installed and no target was touched.

The controller's 30-minute preparation default includes capture, owner wait and
restore. It is an implementer-selected bound, **not** a guaranteed duration or
owner-agreed SLA. Historical ordinary backups unpause early and sometimes approach
that bound already; no cold full-duration or direct-transfer measurement exists.
Review split budgets with the operator before activation. Expiry cannot force
safe source resumption when target fencing or new-state preservation is unknown.
At the appointment, unproven admission still means **NOFREEZE**.

## Reproduce without production effects

```bash
python3 tests/migration_cold_capture_test.py -v
python3 tests/migration_host_test.py -v
python3 tests/migration_notice_test.py -v
bash tests/migration_controller_test.sh
./scripts/validate.sh --all
```

New tests are wired into the strict suite. Report optional skips distinctly.
The Docker image fixture is synthetic and derived from its actual layer/config;
production image identities must come only from live read-only inspect and the
matching manifest/receipts, never a copied conversational digest.
