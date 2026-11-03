# Reversible preparation integration — offline acceptance only

**Status: the minimal synthetic preparation/recovery path is executable. Production
remains BLOCKED / NOFREEZE.** This is not a production site installation or a
cutover-ready adapter. No live pause, capture, private-state restore, Telegram
operation, timer activation, target startup or migration was performed.

The [processed-state-v1 contract](migration-continuity.md) is unchanged: possible
loss of unprocessed Telegram input is accepted; completed conversations, memory,
files, settings, results, current cancellations and uncertain-effect evidence are
not disposable. No external effect is replayed by this integration.

## The path actually exercised

```text
Controller v3 / migration-site-v2 requests
  -> PreparationSite
  -> synthetic all-writer authority + HostOperations.fence
  -> HostOperations.capture (generated cold gzip, actual full verifier)
  -> RecoveryStage (actual separate byte copy / offline restore / compare)
  -> separate synthetic custody backend (actual copy, modeled host boundary)
  -> Sender (real HTTP to loopback fixture, never Telegram)
  -> AWAITING_CONFIRM, no approval
  -> original preparation deadline
  -> persistent modeled target fence + outstanding-operation revocation
  -> CURRENT cancellation / uncertain-effect reconciliation
  -> HostOperations.recover (original container, start/readback, original policy)
  -> Controller ABORTED
```

The same recovery is exercised after a lost notice response, a failed capture,
and a partially completed fence. Exceptions become retryable `Refused` at the
composition boundary; the controller retains its phase and original deadline.
There is no new timer, timeout renewal or approval-manufacturing endpoint.

`RecoveryStage` receipts remain exactly `ready=false`, `runtime_started=false`,
`independent_copy_verified=false`. The composition never edits these flags.
Controller admission and independent failure-domain custody are **simulated only
by the explicitly labeled test authority**, not inferred from local extraction.
The test custody backend does a real exclusive byte copy and full verification,
but both directories are on this machine. Its independent-host flag is a modeled
premise, not production evidence. No production-ready receipt was produced.

Run from trusted source outside any restored tree:

```sh
python3 tests/migration_reversible_test.py -v
bash tests/migration_controller_test.sh
./scripts/validate.sh --all
```

The Docker executable is a subprocess fixture; tar/gzip/verifier/restore/filesystem
operations are real. This establishes composition and failure handling, not Docker
daemon behavior, live host fencing, Hermes startup, Telegram delivery, host-power-loss
recovery, real clock synchronization or independent storage durability.

## Original source recovery

`HostOperations.recover(run, guard)` is an **in-process trusted adapter primitive**,
not a CLI accepting booleans from an operator or a restored file. Original Docker
inspection was fsynced before the first fence effect; recovery verifies its digest
and container/image/config/mount identity. Controller `saved_states_digest`, when
already committed, must match it. A partial first fence can recover before that
controller checkpoint exists, using the host's durable original record.

Initial `HostOperations.fence` admission permits the observed Docker 26.1.5
mask list (without `/proc/interrupts`) **only for in-place preservation of the
original container**. All other admission gates are unchanged. The saved inspect
is not normalized: subsequent fence/recovery compares the entire HostConfig,
except for the managed restart policy, against that exact original receipt.
Unknown mask lists and changed masks/configuration are refused. This is not
cross-engine restore compatibility: ordinary and cold archive capture retain
strict mask validation because restore Compose does not explicitly serialize
those masks. A refused capture keeps pending evidence and can still take guarded
original-source recovery; it cannot publish a successful archive receipt.

The caller must hold a site-wide recovery lease for the entire call. Under the
stable host and backup locks, recovery requires a fresh guard for the same run:

- target stopped and **persistently fenced**, not merely unreachable;
- outstanding remote work revoked; local capture/fence revoked under the host lock;
- lifetime proof of **no target activity**;
- current cancellations/withdrawn access and uncertain effects reconciled safely;
- exact reconciliation digest, with no automatic external-effect replay.

The guard is checked before recovery, immediately before each enabling command,
and after readback. It is trusted executable policy code, not authenticated merely
because its JSON has these keys. All writers of ownership/cancellation policy must
participate in the same authority; malicious root/same-UID mutation is outside the
primitive's trust model. Missing production enforcement is not solved by a callback.

Recovery durably records `run:source_recover` and `START_INTENT` before Docker start,
then restores only the receipted original restart policy (including retry count),
not a guessed `always`. The source data tree and target delta are never replaced.
`running` means Docker inspection, not application-level health or owner dialogue.
Host timers, Compose/systemd recreation and other writers are the authority's
responsibility; this primitive does not restore those settings.

### Interruption and refusal rules

| Observation | Result |
|---|---|
| No approval / notice response lost | Original deadline triggers target fencing and guarded source recovery; no notice resend after uncertain send |
| Partial source fence / failed capture | Preserve original inspection and pending bytes; revoke and recover only after guards |
| SIGKILL before start effect, after durable intent | Source stays stopped; ambiguous start is **not retried**; operator reconciliation required |
| SIGKILL after start effect, before controller receipt | Fresh inspection reconciles running original container, restores original policy, no second start |
| Unknown/unreachable/unfenced target, unrevoked work | No source start |
| New cancellation/effect policy after snapshot | No start until CURRENT policy is reconciled; never restore an old jobs file |
| Any target activity, even unexpected | Controller goes to delta preservation; this narrow adapter refuses unsupported delta/resume operations and retains data |
| Changed original/container/recovery receipt | Refuse; do not repair or overwrite evidence |

Tests use real SIGKILL before/after the synthetic Docker start, verify lock exclusion,
operation identity, original settings and unchanged deadline. Earlier controller,
host-orphan capture and custody SIGKILL regressions remain in the focused suite.
Conservative before-start refusal intentionally sacrifices automatic availability
rather than risking replay of a start that ran and exited without a receipt.

## Trusted authority port — explicit missing production implementation

`PreparationSite(host, stage, sender, authority=None)` fails preflight when no
reviewed authority is supplied. There is no default ready backend, installed site
executable, restored code loader or untrusted-JSON approval route. The composition
implements only pre-cutover preparation and no-target-activity source recovery.
Target restore/start/dialogue, delta preservation and `source_resume` fail closed.
Do not install this partial composition as a complete production adapter.

A future trusted authority must implement these concrete methods:

| Method | Obligation |
|---|---|
| `hold(request)` | Continuous site-wide lease; bind run/operation and nonrenewable expiry, prevent conflicting ownership/policy writes |
| `preflight(request)` | Read-only **all production gates**, not a checklist returning success; incomplete adapter cannot claim readiness |
| `source_quiesce`, `source_probe` | Durable original states and verified all-writer/input/recreation fence, beyond Docker |
| `forward_guard(request)` | Fresh expiry/revocation check at each effect; remote enforcement and bounded orphan completion |
| `independent_copy(request, archive, staged)` | Real separately retained failure-domain copy, digest/full verification, exact run/archive binding |
| `target_fence`, `target_probe` | Persistent fence and remote revoke; lifetime activity evidence, unknown is not stopped |
| `recovery_guard(request)` | Current cancellation/withdrawal/effect reconciliation under that fence and lease; explicit no-activity proof |

The added host `before_effect` seam checks before restart-policy update, stop and
capture dispatch. Checking before a local Docker command does **not** prove that a
remote daemon enforces expiry after queued RPC work or that it has been revoked.
Production must supply that enforcement and orphan receipts. Source originals,
operation stores and verifier code must remain outside restored/live runtime trees.

## Read-only production admission diagnostic

The diagnostic is part of `PreparationSite`, not a second authority library:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/hermes_migration_preparation.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/hermes_migration_preparation.py --inventory /private/observations.json
python3 tests/migration_admission_test.py -v
```

Both diagnostic commands return JSON **`ready=false`, `status=BLOCKED`, exit 2**.
Without an authority, `PreparationSite.call('preflight', request)` returns the same
report bound to the controller run. `Controller.advance` refuses admission and
leaves the durable state exactly `PREPARED`: no freeze intent or deadline is created.
Supplying `inventory=` explicitly selects diagnostic-only mode even when an authority
object is also supplied: it never calls `hold`, host/stage/sender or any effects.
The existing explicitly synthetic executable authority tests remain separate.

Inventory is optional, **untrusted observations**, not a signed attestation or an
executable policy loader. Each of `identity`, `writers`, `recreation`,
`remote_operations`, `policy`, `custody`, `rescue`, `approval`, `watchdog` and
`target_runtime` may hold a metadata object. Each row identifies the existing
trusted authority method and missing production obligation. A nonempty object is
only `present-unverified`; an absent/malformed row is `missing-or-invalid`.
**Every row stays BLOCKED even for a complete inventory containing `verified=true`.**
No inventory key can set ready/custody/start flags. Raw input values (including
paths, operation IDs or accidental private data) are not copied into the report.

Optional hazard fields give narrower diagnostics, never permission:

```json
{
  "recreation": {"reboot_recreation_possible": true},
  "remote_operations": {"pending": ["synthetic-operation"]},
  "policy": {
    "current": {"cancellations": "v2", "withdrawals": "v1", "effects": "v2"},
    "reconciled": {"cancellations": "v1", "withdrawals": "v1", "effects": "v1"}
  }
}
```

Missing/non-list pending work is **unknown**, not zero. Missing reconciliation is
reported separately from changed revisions. Policy is reread from the supplied
inventory on every diagnosis; the caller must obtain fresh observations itself.
An empty hazard list is not proof that queues are empty, revisions authentic or
reconciliation safe. There is deliberately no production verifier/backend to
upgrade these observations into admission. The authority's continuous lease,
remote effect enforcement and current reconciliation still require real design
and isolated-host proof, not more booleans.

Tests exercise complete/incomplete inventories through the real controller,
each absent gate, reboot recreation, pending/unknown remote effects, changed
cancellation/withdrawal/effect revisions, malicious ready flags, refusal of every
preparation effect in diagnostic mode, and read-only/sanitized CLI behavior.

### Selected host observations, not production proof

Read-only source inspection observed a running Compose-managed container with
`unless-stopped`, a writable data bind, enabled Docker/containerd, an active enabled
backup timer, and enabled cron/atd. Those are real writer/recreation owners, not
fences. Process names and selected active-manager file hashes were read without
message bodies, credentials, process arguments or Docker environment. Delegate
interrupts/process checkpoints and local/CDP/cloud browser support do not establish
remote operation expiry/revocation. The full manual/user-unit/remote-writer census,
current cancellation/withdrawal/effect authority, independent custody and owner
rescue access remain unproven. A fresh target read attempt using the handoff's
literal login was denied (publickey); it was not replaced with a historical login.
No assertion of an empty or persistently fenced target follows from that failure.
Private observation timestamps, exact commands and failures remain in the task
report, not this public repository.

## Concrete next gate and handoff

**Follow-up review:** the real disposable VM has now exercised accepted Docker
restart after client SIGKILL, serialized terminal completion, sticky uncertainty
and scoped fencing. See [Docker completion review](migration-docker-completion-review.md)
for the selected finite-requester protocol, rejected universal-root gate and
manual executable tests. It supersedes the generic root-bypass design goal and
outdated target-login/environment blockers below, **not production admission or
any executable safety gate**. Actual Docker effect-time expiry is not claimed;
contract adoption remains explicitly separate.

The old disconnected-primitives gate is closed **at the synthetic integration
level**. The next gate is **production authority and admission binding**, not more
legacy zero-loss prototypes and not permission to freeze.

The read-only diagnostic is now connected and exercised; it closes **reporting and
refusal**, not production admission. The next step is not another JSON verifier.
Resolve the literal target-login discrepancy and independently confirm target
identity/owner rescue access first. Do not silently substitute a historical account.

**Next separately authorized rehearsal:** on an explicitly disposable isolated
Linux/Docker VM, exercise a single source-like synthetic writer plus a real
systemd/Compose recreation owner. Use the retained public image, generated files,
no production data/credentials/bot/network delivery, no host-global Docker stop.
Installing task-scoped units/authority state and rebooting that disposable VM are
new host changes and need specific authorization; do not reboot a shared target.

1. Define the exact task-owned resource IDs and trusted host-side enforcement
   point outside restored state. Require all fixture writers/recreators to consult
   the same durable fence/operation authority; a Docker stop alone is insufficient.
2. Through the existing `PreparationSite` authority port, demonstrate original
   settings capture, fence persistence across daemon/VM reboot, queued/late remote
   operation refusal after nonrenewable expiry, positive revoke, and SIGKILL around
   partial fence/recovery. If Docker RPC cannot be fenced at its actual effect,
   stop and specify the missing enforcement mechanism; do not install a shim.
3. Change a synthetic cancellation/withdrawal/effect revision while recovery is
   pending: no source start until current reconciliation, no blind replay. Retain
   original settings, uncertain intent and synthetic target delta through failures.
4. Read back exact receipts, demonstrate recovery only under a positive persistent
   target fence, then remove only task-owned fixture resources. Report real Docker,
   reboot and lease results separately from still-simulated custody/approval.

This bounded rehearsal closes one authority enforcement/recovery gate; it does not
install a production site, activate timers, restore private state, enable Telegram,
prove independent final custody or authorize cutover. If no isolated rebootable VM
is authorized, the concrete blocker is that environment and the host-change scope,
not permission to keep adding disconnected offline helpers.

Before any production freeze, still required: independently verified target and
owner rescue/key access; processed-state quiescence/all-writer durable fencing;
actual independent final copy; production authority/revocation and partial-fence
recovery rehearsal; single-owner authenticated original-DM confirmation transport;
reviewed external watchdog/boot recovery and owner-runnable Plan B. Target startup,
state/delta preservation and new owner-dialogue acceptance remain separate gates.
The final cutover requires **fresh confirmation from the original DM owner after
readiness**; it is not delegated to this adapter, parent or worker.
