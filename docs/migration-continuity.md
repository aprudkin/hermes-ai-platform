# Revised continuity contract and non-starting recovery stage

**Preparation only; production BLOCKED / NOFREEZE.** This revision supersedes
only the earlier *absolute zero-loss legacy Telegram bootstrap requirement*.
The owner's decision is recorded in [issue 48](https://github.com/aprudkin/hermes-ai-platform/issues/48#issuecomment-6456271387).
It does not authorize live runtime changes, migration timers or cutover.

## `processed-state-v1`: the permitted loss boundary

| State at transition | Required treatment |
|---|---|
| Unprocessed Telegram inputs, including unknown legacy ACKed RAM-only backlog | The owner accepts possible loss during switching. No guarantee of preservation or claim that the queue is empty. |
| Already processed conversations, memory, files, settings, identity and completed results | Preserve in the fresh consistent capture, verified copy and restore; do not reset history or replace state with templates. |
| Started work or uncertain external effects | Not disposable unprocessed input. Preserve available intent/results/evidence, stop dispatch, complete or reconcile before proceeding. Never replay automatically. |
| Pending inputs/recovery artifacts already on disk | Preserve bytes too; the waiver is not permission to delete available records or purge queues. |
| Jobs/access decisions | Preserve current cancellations and withdrawn access; an older archive cannot reactivate them. |

The former G1 bootstrap **proof requirement is narrowly waived, not technically
solved**. Legacy live offsets/inflight remain unknown. New code cannot recover
historical RAM. That fact no longer blocks ordinary offline preparation by itself.
No new receiver, webhook, offset change or Telegram request is introduced here.

### Revised admission obligations

The production adapter must still establish a boundary where processed state is
saved and writers cannot change it: suppress new business dispatch, account for
running turns/tools/jobs, retain uncertain-effect evidence, then verify all-writer
and persistent restart/recreation fencing before fresh cold capture. A zero active
agent count, quiet chat, successful Docker stop or this contract string is **not**
that proof. Unknown started work must block admission or obtain explicit operator
reconciliation; it cannot silently be classified as unprocessed input.

An owner approval consumer while the gateway is stopped still needs a reviewed
single-owner transport and fresh authenticated approval in the original DM. The
waiver does not create that bridge, authorize a competing poller or accept the
previous SSH proposal. Archive verification, independent custody, target trust,
recovery access, remote effect expiry/revocation, delta preservation and new-runtime
dialogue acceptance remain mandatory. Cutover requires fresh owner approval after
verified readiness for the exact run/archive/notice, not this preparation decision.

State schema **3**, **`migration-site-v2`** and all seven safety corrections are
unchanged. No preflight gate was changed to true, no old active state upgraded,
and no timer enabled. Future adapter admission must implement this revised
preservation contract without removing the unrelated gates.

## Working primitive: `scripts/hermes_migration_recovery.py`

This is an importable, non-starting library primitive, **not a site adapter or
host installer**. A trusted caller supplies `RecoveryStage(private_directory)` and
calls `stage(run_id=..., archive=..., archive_digest=..., container_id=...,
image_id=..., continuity_contract='processed-state-v1')`. No CLI dispatch is offered.
Run identity and SHA256/image/container identifiers must have their exact formats.
The contract argument identifies this limited custody policy, not owner approval.

Behavior executed by the tests:

1. Lock an existing real private operation directory; durably bind intent to the
   exact run, compressed archive digest and source container/image identities.
2. Exclusively copy the full gzip bundle to `full.tar.gz`, without hardlinks to the
   original, flush/fsync and verify its bytes, full format and cold provenance.
3. Use the trusted repository restore implementation to extract into a fresh
   `restored/` directory. Never execute captured code or Compose. Verify restored
   state against the archive-bound `state.tar` before publishing a `STAGED` receipt.
4. A completed identical call validates both intent and exact receipt, rechecks the
   archive and compares state again. Altered/corrupt bytes or changed identity fail
   closed without repair or overwrite. Symlinked custody archive/restore roots are
   refused. Operation files and private ancestors must remain trusted/exclusive;
   this is not a defense against a malicious same-UID/root concurrent writer.
5. Any interrupted, unreceipted directory remains for review. Even a fully extracted
   tree after process death is not silently promoted to success or extracted again.
   Retain original intent, partial data and stable lock; do not delete to retry.

Receipts always have `ready: false`, `independent_copy_verified: false` and
`runtime_started: false`. A local byte-independent copy is not an independent host
or failure domain. The primitive does **not** fence a host, enforce a remote lease,
transfer across hosts, resume source, start target, replay effects, send a notice,
accept owner approval or return a controller `restore` response. In particular it
does not invent `fenced` or `message_highwater` evidence. Its directory must be
outside all live runtime/restored trees, with protected storage and sufficient
space for archive, verifier scratch, recovery payloads and extracted data.

The fsynced archive and operation records preserve recovery material; tests cover
process death, not disk/host power loss. A receipt is revalidated, never treated as
a substitute for data readback. GNU tar comparison covers bytes/basic stat metadata,
not independent ACL/xattr value verification. This is file restoration, not actual
Hermes application startup or proof that every live writer has persisted results.
No production profile was restored in these tests.

## Executed offline acceptance

```sh
python3 tests/migration_recovery_stage_test.py -v
bash tests/migration_controller_test.sh
./scripts/validate.sh --all
```

Synthetic Docker supplies inspect/image fixtures; actual generated cold capture,
GNU tar/gzip, SHA256, full verifier, file copy, restore and SQLite are exercised.
The synthetic manager retains a processed message, memory, identity, configuration,
completed result, cancellation, pending record and uncertain-effect ledger. No
application/effect is executed or replayed. Additional tests reject identity/digest
mismatch, interrupted/replaced custody and changed success flags/intent. Real child
SIGKILL before and after restore checks lock exclusion and retained intent without
a success receipt. These are not live Docker, Telegram, independent-host or real
model acceptance tests. Report optional strict-suite skips separately.

## Reversible integration and next gate

The **reversible source preparation/recovery integration** is now exercised against
synthetic hosts and local HTTP: fence, real cold bundle/custody, notice, missing
approval or failure, positive modeled target fence/revoke, current reconciliation,
and original-source recovery. Real SIGKILL tests cover recovery start intent before
and after the effect. Unknown target and target activity remain fail-closed.

See [the executable path, evidence boundaries and next bounded gate](migration-reversible.md).
The next gate is production authority/admission binding with read-only inventory,
not another legacy zero-loss prototype. The custody stage still cannot claim real
independent-host protection. Full site adapter installation, private-state restore
and live cutover remain unauthorized; fresh original-DM approval is still mandatory.
