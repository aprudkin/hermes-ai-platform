# Two-phase migration controller — preparation, NOT live readiness

Related journal: [#48](https://github.com/aprudkin/hermes-ai-platform/issues/48).
This is a tested executable **control kernel and portable Plan B**, not a shipped
production host adapter. No source pause/capture, secret transfer, deployment,
production notice, owner-key enrollment or timer activation was performed here.
**Do not enable these units with a fixture adapter.** Missing admission evidence
means no freeze, even at the agreed time.

## Current continuity contract

The owner accepts possible loss of **unprocessed Telegram inputs only** at the
transition. The earlier absolute zero-loss legacy bootstrap gate is superseded,
not proven solved. Preserve processed conversations, memory, files, settings,
results and current cancellations. Started/uncertain external effects require
preservation and reconciliation, never blind replay. See the explicit revised
[admission contract and non-starting recovery stage](migration-continuity.md).
All other production gates, state v3 and migration-site-v2 remain unchanged.
This waiver is not approval to freeze or cut over; production remains NOFREEZE.

## Agreed time and authority

The owner confirmed **2026-10-28 10:00 Europe/Moscow (07:00 UTC)** for phase 1:
freeze ordinary inputs/writers, produce a fresh full backup, independently verify
it, then send a readiness/return-path notice. Phase 2 (restore/cutover/start) needs
**another fresh owner confirmation of this exact run**. Date/time confirmation,
old conversations, outbound delivery and a green test suite are not that approval.
The timer is a review artifact, not an installed schedule. Parent/operator review
and activation permission remain mandatory. Preserve current availability until
then. The proposed dispatch tolerance is 60 seconds, not a late catch-up window;
review it before activation. A missed/unready start becomes terminal `BLOCKED`.

## Executable artifacts and actual boundaries

- `scripts/hermes_migration_controller.py`: Python 3 stdlib Linux controller,
  private atomic/fsynced state, stable flock, run/operation IDs, dated admission,
  two-phase owner gate, external watch loop, reboot-only resume, safe rollback.
- `scripts/hermes_migration_plan_b.py`: standalone Python 3 + OpenSSH owner tool;
  default/`--check` only reads both Docker states. No repository imports needed.
- `systemd/hermes-migration.{service,timer}`: dated host-side trigger/supervisor.
- `systemd/hermes-migration-recovery.service`: boot recovery for an already-started
  run only; it cannot initiate a `PREPARED` freeze. Both entry points serialize on
  the same controller lock and state, not separate migration owners.
- `tests/migration_controller_test.sh`: wired into the normal strict suite;
  synthetic hosts, real private filesystem state and subprocess execution.

Production operations are supplied by a **reviewed, SHA256-pinned executable**
`/usr/local/lib/hermes-migration/site-adapter`. No complete site adapter is bundled.
[Cold capture, source-host primitives and outbound sender](migration-primitives.md)
are now executable and exercised on isolated fixtures, but deliberately cannot
report production readiness. There is no pretend-success backend or permissive
backup patch.
`CommandSite` actually invokes the pinned executable with an action argument and
JSON request on stdin; requires one JSON object response, suppresses raw stderr,
uses an allowlisted environment, and kills the local process group on timeout.
Timeout cleanup does not drain inherited stdout and has only a 0.2-second bounded
direct-child reap; a detached pipe holder cannot keep the controller lock held.
A local timeout does NOT stop an already detached remote operation. The site
adapter must revoke/verify remote operations before authorizing recovery.
Long capture/transfer work must be a durable **host operation** queried in bounded
calls (default 60 seconds); never a detached SSH shell with no receipt/lease.
No controller files or credentials belong inside the source Hermes mount.
Test code/validators must also come from a trusted checkout outside restored
state, not from the imported agent workspace. The tests here use private disposable
fixture data, never a production restored profile as executable test authority.

## State machine and bounded recovery

```text
PREPARED -> read-only preflight -> FENCING_SOURCE -> CAPTURING
 -> NOTIFYING_READY -> AWAITING_CONFIRM
 [fresh enrolled owner approval for run + nonce + archive hash + notice ID]
 -> RESTORING -> STARTING_TARGET -> WAITING -> ACCEPTED
```

Nothing restores or starts a target while waiting for pre-cutover confirmation.
The readiness notification must carry run ID, nonce, compressed archive SHA256,
expiry, confirmation route and Plan B. An uncertain notification is not readiness.
The nonce is not a password and is not sufficient authentication by itself.

Defaults, chosen by the implementer and **not owner-specified durations**:
- 30 minutes from the preflight admission for **all** freeze/capture/notice/
  confirmation/restore preparation, bounded by the original persisted deadline;
- 30 minutes from the target's original, receipted startup for new owner dialogue.

An absent/late pre-cutover answer causes target fencing and safe source recovery
(`ABORTED`), not silent approval. Preparation exceptions retain phase; the external
watcher reaches the same deadline on its next iteration. No timer reset on retry.
Target startup intent is persisted **before** calling its adapter, so an interrupted
start is treated as possibly live and must preserve target delta during fallback.

Both budgets now retain wall/`CLOCK_BOOTTIME`/Linux boot-ID anchors in private
state. Elapsed time includes suspend and survives controller-process restart on
the same boot. Expiry of either bound, a different boot, absent clock evidence,
or wall/elapsed divergence greater than 5 seconds conservatively requests target
fencing; it never grants a new window. This policy can deliberately abort early
after a forward clock step. Clock uncertainty refuses a new approval. It does
not automatically resume source or prove clock correctness on remote hosts.
Blocking boundaries before/after target start and dialogue are rechecked; a late
or uncertain startup cannot enter normal `WAITING`, nor can a late dialogue RPC
accept the run. Remote authorization expiry remains an adapter obligation below.

The dated first-freeze window is persisted with admission, separately from the
longer preparation budget. Before its first `source_fence` call the controller
persists intent. On late recovery with **no** intent it becomes `BLOCKED` without
freezing; with intent (including a crash before the effect or after completion)
it requests conservative fencing/recovery instead of retrying a possibly late
first freeze. Keep receipts and the original window; never recreate state to
extend it. A `BLOCKED` notice still needs the scheduled entry's delivery retry or
an independent operator; terminal state alone does not prove notification.

After possible target activity, even **without local startup intent**, rollback is:

```text
FENCING_TARGET -> PRESERVING_DELTA -> RECONCILING -> RESUMING_SOURCE -> ROLLED_BACK
```

Only fresh, durable adapter proof `no_target_activity_verified: true`, covering
the entire run and all target writers/recreation paths, permits the shorter
`RECOVERING_SOURCE -> ABORTED` path when there was no start intent. Stopped/absent
Docker state alone is not that proof. The proof is checked again before recovery;
missing/revoked proof returns to delta preservation. Delta receipts require exact
lowercase 64-hex SHA256 plus both verification flags. Missing/null/malformed
digests cause retryable refusal, not an unhandled missing-key exit.

Target unreachable or stop failure is **not** a fence. Do not start source without
independently verified persistent target fencing (including provider-console fence
when necessary). Preserve new target data independently before source restart;
never overwrite source with it automatically. Replay/external effects and current
job cancellations need review. These gates may intentionally block automatic
recovery: a safe bound on waiting is not a guarantee of restored availability
through host/SSH/provider failure. An independent operator must monitor that case.

`ACCEPTED`, `ABORTED`, `ROLLED_BACK`, `BLOCKED` suppress late actions. `cancel`
means **disarm, leave hosts as-is**, not resume; use `request-rollback` for recovery.
A cancelled frozen run requires manual review, not deleting the state file. Exact
confirmation retry is idempotent; wrong run/user/chat/notice/nonce is refused.
State version **3** is required; versions 1/2 and unknown phases are rejected by
all load paths, including manual rollback, without rewriting state. Do not convert
old active state by editing its version: operator recovery must retain original
receipts and determine actual host ownership. No deployed state was upgraded here.

## Owner route while ALL ordinary inputs are stopped

**The owner expects fresh approval in the original Telegram chat.** A fully
stopped gateway cannot receive it. The earlier draft's SSH forced-command route
was an implementer proposal, **not an agreed replacement**; do not enroll keys or
present it as the owner's chosen channel. The low-level confirmation endpoint
below remains for a future trusted bridge, not permission to manufacture approval.
A reviewed single-owner approval transport remains an admission blocker. The
legacy zero-loss bootstrap proof is no longer mandatory under the revised
contract; processed-state quiescence and uncertain-effect reconciliation still are.
The following SSH enrollment description is an **unaccepted alternative only**.

Install a dedicated owner-held key, not an agent-held administrator key, in a
restricted account. Its `authorized_keys` entry must use `restrict` plus a forced
command that sets fixed `--owner-id`, `--chat-id`, `--state-dir` and `confirm
--execute`. Do not parse `SSH_ORIGINAL_COMMAND`, allow shell/sftp/forwarding, or
permit callers to select an identity, run directory, adapter or command. Use only
a narrowly allowlisted root-owned wrapper in sudoers, **not unrestricted sudo
python**, if privilege separation requires sudo. The wrapper/account/key setup is
not included or installed here and must be reviewed/tested independently.

The implemented confirmation endpoint accepts at most 4096 bytes of JSON on stdin:

```json
{"run_id":"<this run>","nonce":"<readiness nonce>","archive_digest":"<compressed file sha256>","notice_id":"<readiness message ID>"}
```

The administrator's fixed command invokes:

```text
/usr/bin/python3 -I /usr/local/lib/hermes-migration/hermes_migration_controller.py confirm --execute --owner-id ENROLLED_OWNER --chat-id ORIGINAL_OWNER_DM --state-dir /var/lib/hermes-migration/current
```

The owner submits that exact readiness object over their restricted SSH alias and
checks the returned run ID/phase. No generic agent tool may manufacture approval.
The root administrator is necessarily trusted; root can modify this controller.
Set a connection/input timeout in the wrapper; do not leave blocking SSH stdin
sessions with unlimited lifetime. No key, nonce, private ID or real reply is put
in GitHub.

External notices use a reviewed host-side sender restricted by its application
code to the enrolled DM. Telegram bot tokens are not intrinsically send-only:
protect the token, fixed endpoint/destination, no arbitrary method/URL, and keep
it outside normal logs. Require a successful `sendMessage` API response with the
exact destination and message ID; uncertain send receipts need reconciliation,
not unlimited duplicate sends. `scripts/hermes_migration_notice.py` now implements
this outbound-only primitive with a fixed HTTPS host/method/private DM, local
credential resolution and durable uncertain-send suppression. Real HTTP request/
response tests use a loopback fixture, **not Telegram**. It has no confirmation
receiver or live delivery proof; see [primitive status](migration-primitives.md).

There is **no second getUpdates consumer**, webhook swap, offset advancement,
`drop_pending_updates`, or imported-history confirmation introduced by this PR.
**Do not assume Telegram backlog will survive source restart.** Read-only source
inspection found that the installed adapter hardcodes cold-boot drop, lacks a
`drop_pending_on_cold_boot` knob, and holds acknowledged events in
process memory. Offline execution of those exact installed method bodies (fake
network only) confirmed cold boot requests drop and PTB shutdown acknowledges
queued updates before processing. Live offsets/inflight counts are **unknown,
not zero**. Loss of only unprocessed inputs is now accepted; this does not prove
processed-state quiescence or owner approval transport. Those and the other
production gates still prohibit freeze. Details and source hashes:
[ingress evidence](migration-primitives.md#telegram-input-preservation-blocker).

After target startup, the trusted dialogue adapter must establish all of:
new instance/run/nonce, exact private owner and chat, post-start inbound user
message above the restored baseline, reply to this challenge, linked assistant
response and confirmed delivery before the deadline. An outbound challenge or
a database row alone is never acceptance. Target gateway remains the sole poller.

## Production adapter contract — blockers, not operator checkboxes

Every request carries `run_id` and stable `operation_id = run_id:action`; every
response must carry the same run ID. Side-effect handlers must durably record
intent, observe actual state after the effect, and replay the same operation
receipt or safely reconcile uncertainty. Probe responses must be fresh, not
cached success. Root-owned private ancestors, immutable pinned code/dependencies,
one deployment state directory and one site-wide migration lease are prerequisites.

Contract **`migration-site-v2`** replaces v1; old adapters cannot pass preflight.
Forward side-effect requests carry immutable `effect_expires_at` (preparation
deadline, or the earlier dated first-freeze deadline). The adapter must enforce
that authorization **at the remote effect**, not only at receipt of an RPC: use
durable operation IDs, trusted clock/skew evidence and non-renewable bounded
leases, refuse late new effects, and revoke outstanding work before recovery.
An already completed operation may return its original durable receipt, never
repeat the effect or extend its authorization. Controller boot-ID/elapsed values
are not a clock shared with the target. A fixture claiming v2 is not proof of a
real remote lease/fence. No production v2 adapter is bundled or installed.

| Action | Required evidence/behavior |
|---|---|
| `preflight` | Read-only; `ready: true`, `contract: migration-site-v2` only after ALL gates below, including remotely enforced effect expiry. An absent gate fails closed. No freeze in this action. |
| `source_fence` / `source_probe` | Save original settings durably before change (`saved_states_digest`), drain/stop inputs and every writer, fence restart/recreation persistently; verify `fenced` and `writers_stopped`. |
| `capture` | Final frozen **full gzip bundle**, exact compressed file SHA256, `archive_format: tar.gz`, full verifier success and independent-copy verification; source remains fenced throughout. |
| `notify_ready` | Actual delivery receipt, exact run/nonce/owner/chat/archive digest and nonempty `notice_id`; no restore or target start. |
| `notify_blocked` | Independent failure notice to exact enrolled chat, delivery receipt; cannot freeze/start anything. |
| `restore` | Restore into a fresh destination, offline checks, target remains fenced, `verified`, `fenced`, integer restored `message_highwater`. |
| `target_start` / `target_probe` | Source still fenced; idempotent original startup time and instance/challenge IDs; current running state. Persist/fence all restart paths. |
| `dialogue` | Authenticated evidence described above, not direct untrusted JSON from a user/history. |
| `target_fence` / `target_probe` | Revoke outstanding operations; verify stopped + persistent fencing + all target writers stopped. Unreachable is unknown. |
| `preserve_delta` | New immutable independently verified target snapshot, digest; no overwrite/deletion of original source. |
| `reconcile` | Explicit safe-to-resume, replay reviewed, current cancelled jobs preserved. Preserve externally performed actions even if rollback cannot undo them. |
| `source_recover` / `source_resume` | Restore only receipted original states after target fence, no cancelled-job resurrection; source health readback. Pre-start recovery must handle a partially completed source fence. |

The following remain **required before installation/activation**:

1. Independent target host-key/provider identity verification; TOFU is unresolved.
   Working owner provider-console/rescue access and independent recovery keys.
2. Full fresh **live inventory** of writers/inputs: gateway, all profiles/jobs,
   delegates, application workers, host timers/backups, restart/recreation and
   administration paths. The active inventory includes an AgentMail inbox check;
   old summaries of absent email jobs must not be used. Preserve each task's
   actual current enabled/disabled state, including current cancellations.
3. Tested external controller/notice path and owner authentication in the original
   Telegram chat through a proven single-owner approval transport; processed-state
   quiescence and reconciliation under [processed-state-v1](migration-continuity.md);
   verified watchdog/boot recovery and time synchronization. The unaccepted SSH
   alternative must not silently replace this gate. Establish a source-side fence
   against all restart/recreation paths that survives a host reboot.
4. Compatible frozen capture, unchanged admission/verifier guarantees and rollback
   of partial freeze. **The installed capture requires running/unpaused source,
   pauses only its own snapshot and unpauses before packaging. It cannot be
   called after a full container fence or blindly used as a zero-delta backup.**
   Do not bypass its checks, fake running metadata or kill its cleanup. The new
   separate `capture-cold` path and host primitives have real fixture capture/
   restore tests, but are not deployed and do not prove input quiescence, all-host
   fencing, independent storage or production recovery. See [actual boundaries](migration-primitives.md).
5. Enough private protected storage for archive, verification scratch, image import,
   restoration and independent delta. Verify exact image compatibility and restore
   rehearsal, cancellation/replay policy and independently retained cloud copy.
6. Rehearse every production adapter operation and interruption on isolated hosts.
   Local mock-host tests do not establish host fencing, owner delivery or restore.

## Gzip and direct transfer (not executed)

The owner explicitly requested gzip. Transfer one immutable **`.tar.gz`** full
bundle; the existing normal capture already streams gzip, so **do not gzip it a
second time**. Kernel rejects a non-`tar.gz` capture receipt. Prefer resumable
rsync-over-strict-SSH of the verified source-local original over an unnecessary
cloud download hop. Use a new private run destination, never a live runtime path.
Do not use rsync `-z`, `--inplace`, `--delete` or an overwrite of accepted backups.
Keep any partial transfer separate and retain previous verified originals.

Illustrative commands only, after host trust and transfer authorization:

```bash
# ARCHIVE is the exact immutable .tar.gz; paths/aliases are private reviewed inputs.
gzip -t -- "$ARCHIVE"
sha256sum -- "$ARCHIVE"
python3 scripts/hermes_backup_bundle.py verify "$ARCHIVE" full
rsync --partial --partial-dir=.rsync-partial --protect-args --chmod=F600,D700 \
  -e 'ssh -F /PRIVATE/ssh_config -o BatchMode=yes -o StrictHostKeyChecking=yes -o ForwardAgent=no -o ClearAllForwardings=yes' \
  -- "$ARCHIVE" target-verified:/PRIVATE/NEW-RUN/inbox/
# On target: compare exact transferred file SHA256 to the source receipt,
# then gzip -t and the trusted full-bundle verifier with its compatible Python.
```

A matching SHA256 covers the **transmitted compressed bytes**; also require gzip
integrity and full-bundle verification before restore. Rsync exit 0 is not enough.
A cloud roundtrip remains independent recovery protection; it is not necessary as
a transport hop when the original is available. Parent timing evidence observed
recent daily backups taking about 12–13 minutes, with one about 27-minute outlier;
that workflow unpauses early, so these are neither frozen-downtime estimates nor
a direct-transfer benchmark. Direct-transfer speed is unmeasured. Target has rsync
but authenticated target cloud retrieval is not proven; do not weaken SSH's
forwarding restrictions to work around the blocked relay test.

## Installation/activation runbook — conditional, NOT performed

These commands are for the reviewed source **host**, outside Hermes. Before
executing, finish every admission blocker above and verify the exact reviewed
revision. They describe installation, not evidence that installation succeeded.
The units have native local parser/calendar checks; host deployment/sudo/SSH
permissions and live systemd lifecycle have not been tested by this PR.

1. Stage reviewed controller/Plan B/units plus the **separately implemented,
   reviewed and rehearsed adapter** in a root-owned private directory. Use strict
   host-key checking. Do not create the fixed `current` path over an earlier run.
2. Install only after authorization, checking every destination is absent first:

```bash
sudo install -d -m 0700 /usr/local/lib/hermes-migration /etc/hermes-migration /var/lib/hermes-migration
sudo install -m 0700 scripts/hermes_migration_controller.py /usr/local/lib/hermes-migration/
sudo install -m 0700 /PRIVATE/REVIEWED/site-adapter /usr/local/lib/hermes-migration/site-adapter
# Prepare root-owned 0600 controller.env containing only the reviewed
# MIGRATION_ADAPTER_SHA256=<exact SHA256>. Never a placeholder or fixture pin.
sudo install -m 0600 /PRIVATE/REVIEWED/controller.env /etc/hermes-migration/controller.env
sudo install -m 0644 systemd/hermes-migration.service systemd/hermes-migration-recovery.service systemd/hermes-migration.timer /etc/systemd/system/
sudo python3 -I /usr/local/lib/hermes-migration/hermes_migration_controller.py create --execute \
  --owner-id "$ENROLLED_OWNER" --chat-id "$ORIGINAL_OWNER_DM" \
  --preparation-seconds 1800 --timeout-seconds 1800
sudo systemd-analyze verify /etc/systemd/system/hermes-migration.service /etc/systemd/system/hermes-migration-recovery.service /etc/systemd/system/hermes-migration.timer
sudo systemd-analyze calendar '2026-10-28 10:00:00 Europe/Moscow'
sudo systemctl daemon-reload
```

3. Read back installed hashes, private ownership/modes, exact run ID, actual clock,
   and all unit definitions. Verify adapter preflight read-only on the real host
   without calling `advance/watch/scheduled`; it must report missing readiness as
   failure. Confirm operator Plan B from their own machine and scoped key route.
   Installation must not change gateway/jobs/backup timer.
4. **Only after independent parent review and activation approval**, while still
   before the intended time and with `PREPARED` state:

```bash
sudo systemctl enable hermes-migration-recovery.service
sudo systemctl enable --now hermes-migration.timer
sudo systemctl show hermes-migration.timer -p ActiveState -p UnitFileState -p NextElapseUSecRealtime -p LastTriggerUSec
sudo systemctl cat hermes-migration.timer hermes-migration.service hermes-migration-recovery.service
sudo python3 -I /usr/local/lib/hermes-migration/hermes_migration_controller.py status
```

Expected next elapse: **2026-10-28 07:00:00 UTC**. Never `start` the migration
service as an installation test. `Persistent=false` avoids a catch-up freeze;
if the host is down at the appointment, recovery service will not initiate a
`PREPARED` run. An independent observer must report the missed appointment; the
source-host controller alone cannot notify through source-host failure.
If gates are not met, leave timer disabled and send an honest blocked notice
through the independent reviewed sender/operator, keeping Chebi online.

## Owner Plan B

Copy only `hermes_migration_plan_b.py` to an independent owner computer. Keep
verified SSH aliases/known-hosts/keys outside the repo. Read-only check:

```bash
python3 hermes_migration_plan_b.py --check --source source-verified --target target-verified --ssh-config /PRIVATE/ssh_config --known-hosts /PRIVATE/known_hosts
```

An unavailable target is reported unknown and **never** safe to start source.
After deliberately requesting rollback, supply this run's exact ID:

```bash
python3 hermes_migration_plan_b.py --rollback --confirm-request --run-id "$RUN_ID" --source source-verified --target target-verified --ssh-config /PRIVATE/ssh_config --known-hosts /PRIVATE/known_hosts
```

This submits intent to the same external controller and reads that controller
back. It does not itself start Docker directly. It validates version 3, exact run
ID and a rollback/recovery phase on **both** replies; unknown phases, old schema,
`PREPARED`, `ACCEPTED` or `CANCELLED` are not a successful rollback request.
`completed: true` only reflects `ROLLED_BACK`/`ABORTED` readback.
It requires the reviewed installed controller, scoped permissions and a running
external watcher. Without those, this is **not yet an operational Plan B**.
With controller/source unreachable: use verified provider console to fence target
persistently, preserve its disks/delta, restore controller access and reconcile
before source restart. Never assume SSH timeout means off, destroy disks, or
start two Telegram/job owners.

Before trigger, stopping/disabling **only this migration timer** prevents the
appointment; do not disable unrelated jobs. After freeze, merely disabling the
timer does not recover the source: request rollback on the exact current run.
Retain state, original settings, archives and receipts. Do not uninstall a running
controller or delete its stable lock. Accepted/aborted runs are not reused.

## Verification sources

- Current [Hermes messaging gateway](https://hermes-agent.nousresearch.com/docs/user-guide/messaging): gateway receives platforms and runs scheduler; ordinary silence is not input suspension.
- [Telegram Bot API](https://core.telegram.org/bots/api#getupdates): polling/webhook ownership and retention limits.
- Repository [full recovery](backup-restore.md), [migration](migration.md), [host backups](server-backup.md), and read-only inspection of the installed capture confirmed its auto-unpause boundary.

Run `bash tests/migration_controller_test.sh`, then `./scripts/validate.sh --all`.
Report explicit optional skips. Do not label local fixtures, native unit parsing,
reviewable publication or a prepared dated timer as installed/live acceptance.
