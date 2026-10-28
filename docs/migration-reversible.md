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

## Concrete next gate and handoff

The old disconnected-primitives gate is closed **at the synthetic integration
level**. The next gate is **production authority and admission binding**, not more
legacy zero-loss prototypes and not permission to freeze.

Next bounded work, still without live writes:

1. Use only previously pinned, authorized read-only host access to map actual
   source/target identities, container IDs, restart/recreation owners, host units,
   jobs/delegates/browser writers, current cancellations/access withdrawals and
   custody/access locations. Read selected metadata only; do not print secrets.
2. Map each row to the authority port above, its exact effect/revocation mechanism
   and independently testable evidence. Implement a read-only admission command
   that reports each absent production proof as blocked, never fixture success.
3. Exercise that command on synthetic complete/incomplete inventories, including
   reboot recreation, pending remote effects and changed cancellation revisions.
   Identify the exact separately authorized isolated-host rehearsal needed next.
4. Stop at a concrete blocker if persistent host fencing, remote effect leases or
   owner recovery access cannot be established without live changes. Do not install
   a shim returning true or broaden this into another orchestration platform.

Before any production freeze, still required: independently verified target and
owner rescue/key access; processed-state quiescence/all-writer durable fencing;
actual independent final copy; production authority/revocation and partial-fence
recovery rehearsal; single-owner authenticated original-DM confirmation transport;
reviewed external watchdog/boot recovery and owner-runnable Plan B. Target startup,
state/delta preservation and new owner-dialogue acceptance remain separate gates.
The final cutover requires **fresh confirmation from the original DM owner after
readiness**; it is not delegated to this adapter, parent or worker.
