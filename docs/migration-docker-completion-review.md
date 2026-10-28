# Docker requester completion review — disposable evidence, not admission

## Decision

Do **not** add a universal root-bypass prevention gate. Trusted administrators
already control Docker and the host. Deliberately issuing a new privileged start
in violation of the migration lock is a trust-boundary violation, not an automatic
restart mechanism which this migration must somehow defeat. It must invalidate
readiness and trigger reconciliation, not be described as prevented.

Keep the **real outstanding-operation gate**. A killed client, expired wrapper,
`docker ps`, `inspect`, `wait`, a successful unrelated stop, or an empty local
process list is not evidence that another accepted Docker RPC cannot still start
an owner. There is no assumed daemon-wide flush/revoke API here.

The actual rehearsal's authorized actors were one SSH operator driving the guest
serial console, its task-owned test workers, Docker restart policy and the retained
synthetic systemd/Compose owner. Test containers have no Docker socket or network;
there are no guest remote clients. The real source was not touched. Earlier source
metadata identified Compose management, Docker restart policy, backup timer and
cron/atd; it was not a complete current actor census. No live migration start was
issued by this stage, and the shared target daemon remained container-empty.
Those facts do not justify inventing a pending production start, nor do they prove
all source browser/job/delegate effects settled.

The minimum selected protocol is **closed requester set + serialized completion
before fencing**:

1. Inventory actual enabling actors: the external migration operator/controller,
   watchdog, Compose/systemd owners, timers/cron, delegates and remote sessions
   with relevant control access. Disable automatic recreation durably, retain
   original settings and obtain positive requester termination/revocation receipts.
   Administrators coordinate through the same maintenance lock. An unknown actor
   or pre-existing unknown request blocks this protocol; do not invent an empty
   ledger from a process scan. Unrelated workloads are not targets of this lock.
2. One external owner holds the operation lock from a durable run/operation/
   container/boot/deadline intent through a **specific RPC's terminal response**
   and durable receipt. Recheck original expiry after acquiring the lock, before
   dispatch. Do not renew deadlines on restart or retry uncertain operations.
3. Close future admission. Allow a known in-flight operation to finish under the
   lock; do not confuse stopping its client with revoking its daemon work. Only
   after terminal receipts for every relevant request, apply restart=no, disable
   recreation owners, stop the exact container and read back the persistent fence.
   A successful response for an unrelated RPC is not a queue barrier.
4. Lost receipt, disconnected client, boot discontinuity or nonterminal operation
   means **uncertain: no second owner / no source resume**. Retain intent and all
   data. Readback can detect activity but cannot fabricate terminal completion.
   Manual investigation/resource-specific fencing is exceptional recovery, not
   permission to replay, delete the container or restart the shared daemon.
5. Any target activity, including late activity, still requires target-delta
   preservation and CURRENT cancellation/withdrawal/effect reconciliation. A
   stopped target is not a lifetime no-activity proof. The existing unsupported
   target-delta/source_resume paths remain refused.

This replaces an unbounded design goal (“prevent all possible root bypass and
cancel every RPC inside Docker”) with finite observable obligations. It does
**not** assert an effect-time lease in Docker. A deadline bounds admission; an
already accepted operation can finish later. The safety boundary is that no
conflicting owner is admitted until it is terminal and the fence is established.
If bounded recovery cannot be proved, remain blocked rather than extend approval.

**No production contract or executable safety gate is changed by this review.**
The current `migration-site-v2` wording still requires remote effect expiry.
The manual fixture is not compatible production authority and always returns
preflight `ready=false` / `production_ready=false`. Adoption of the completion
protocol in that contract needs an explicit follow-up review of its ordering,
all-requester coverage and failure behavior, not changing a diagnostic JSON flag.
This does not waive processed-state preservation or permit deadline renewal.

## Why this is grounded

Official Docker documentation says `restart=no` prevents **automatic** restart,
not manual start, and that only trusted users should control the Docker daemon:

- [Restart policies](https://docs.docker.com/engine/containers/start-containers-automatically/)
- [Daemon security boundary](https://docs.docker.com/engine/security/)

The version-matched upstream source for the guest's Docker 26.1.5 is more specific:

- [`daemon/restart.go`](https://github.com/moby/moby/blob/v26.1.5/daemon/restart.go)
  explicitly uses `compatcontext.WithoutCancel`: request cancellation must not
  cancel stop→start. This is why a dead client does not establish revocation.
- [`container_routes.go`](https://github.com/moby/moby/blob/v26.1.5/api/server/router/container/container_routes.go)
  sends HTTP204 for start/restart **after** that backend call returns. It is a
  per-request terminal response, not proof about other requests or future actors.
- [`daemon/start.go`](https://github.com/moby/moby/blob/v26.1.5/daemon/start.go)
  takes the container lock but also uses noncancelable task-start work. There is
  no migration lease/revocation parameter.

Upstream source is not a claim that every vendor patch was audited. Actual guest
execution below independently reproduced the relevant cancellation behavior.

## Real disposable execution

A retained no-NIC QEMU/TCG guest, using public/generated state only, exercised
`tests/manual/docker_request_completion/`. It uses the **unchanged existing
PreparationSite** port. No host Docker/socket is shared with the guest.

The prior Compose/systemd fixture stayed fenced and its processed-data digest
was unchanged on this stage's cold boot. New cases use separate generated
containers, network=none, read-only root, nonroot UID, dropped capabilities,
32MiB/0.25CPU/PIDs32 and separate synthetic data binds. No live Hermes drain,
private data, Telegram delivery or custody claim is made.

Executed cases:

- completed start → terminal receipt → actual stop/readback → scoped fence;
- revoked future request and expired-before-dispatch request refused;
- real SIGKILL after durable intent, before dispatch: uncertainty remains;
- real SIGKILL after Docker effect, before receipt: running state/delta preserved,
  no replay, no successful fence proof;
- **accepted restart survives killed client and original deadline**: the daemon's
  signal15 event proves entry into the restart stop phase; client is SIGKILLed;
  `StartedAt` subsequently changes after expiry. Durable intent remains pending,
  and fencing/admission remains false even after the late effect is observed;
- privileged manual start bypasses the fence as expected; fresh probe detects it;
- wrong boot and foreign-container completion refuse proof;
- uncertain start blocks a different enabling operation too;
- concurrent fence waits for the known restart RPC's terminal receipt, then
  stops/readbacks. It never treats a pending operation as revoked.

The retained guest was also really rebooted: all 294 accumulated fixture files
were byte-identical, all 42 containers from the executed iterations remained
stopped, and old-boot receipts were not promoted into fresh authority. These
counts include RED/GREEN iterations, not 42 independent acceptance tests.

These are real Docker processes/RPCs, not fake Docker responses. The authority is
still a **synthetic closed-requester model**: root can mutate its files or bypass
it, and the fixture has no general create/exec/update/browser/delegate coverage.
Its positive `remote_operations_revoked` value means future requests revoked AND
known requests terminal within this explicitly isolated scope; it is not a
production or daemon-wide attestation. Unknown operations stay blocked.

## Rejected alternatives and next step

- A global daemon restart is not an acceptable barrier on the shared production
  host: unrelated workloads, live-restore and queued recreation make it neither
  scoped nor a substitute for requester control. No such restart was performed.
- Removing a container can fence old-ID starts but destroys its writable layer
  and does not stop create/recreate requests. It was not adopted; originals,
  synthetic deltas and uncertain records remain retained.
- A universal root-proof proxy/plugin would enlarge the task without establishing
  the actual writer census. A local CLI wrapper alone is also insufficient.
- Do not clear the existing production gate because these tests passed.

**Next bounded unit:** map the actual finite enabling actors to this completion
protocol (including the external watchdog), review whether they can all use one
serialized executor, then bind the existing preparation/no-target recovery path
in the disposable guest. Prefer the no-target-activity preparation branch: no
restore/start RPC is even admitted there. Rehearse original-policy recovery and
current-policy changes with real Docker; retain the existing refusal on any
uncertainty or target activity. Do not add another abstract authority library.
If an actual actor cannot be revoked/receipted, identify that actor and the
specific required boundary instead of reopening a generic “protect against root”
project. Production custody, rescue, processed-writer drain, approval/watchdog,
Hermes startup/delta/dialogue remain distinct gates. Cutover still needs fresh
original-owner DM approval **after readiness**.
