---
name: migration-controller-review
description: "Use when reviewing migration safety controllers."
metadata:
  hermes:
    related_skills: [github-code-review, agent-runtime-continuity, systematic-debugging]
---

# Migration controller adversarial review

- Pin the requested full commit SHA in a detached private worktree; keep reproducers and logs outside tracked source, and never publish a review or invoke live lifecycle operations without separate authority.
- Run existing focused tests and the strict gate. If tooling is missing, discover already-provisioned isolated toolchains before installing anything; report exact PATH/Compose configuration and optional skips.
- Test both clock discontinuities and an RPC straddling a deadline. A wall-clock expiry alone is not an elapsed-time bound, and a check before a slow probe does not constrain a later side effect. Use a coherent injected wall/elapsed/boot clock for every stage; mixing a synthetic admission clock with a real runtime clock can make a regression pass only because clock-domain uncertainty aborts it.
- When adding durable elapsed/boot anchors or remote effect-expiry obligations, reject older active state rather than inventing missing evidence, version the adapter contract, and test the old contract's admission refusal. A passed request deadline is not proof that the absent production adapter enforces a remote lease.
- Exercise first-freeze crash recovery at admission, before effect and after durable effect with actual SIGKILL. Retain the original dated window and distinguish no request from uncertain request; never renew authorization on restart. Run final strict checks from an exact-commit trusted checkout outside restored data and keep RED/GREEN, publication and exact-head CI receipts separately.
- Test real SIGKILL before and after a fixture side effect using a durable fixture receipt ledger. Verify intent survives, the operation ID is reused, and original deadlines are retained; in-process exceptions alone do not exercise process death.
- Test timeout cleanup with a short-lived detached child retaining stdout. A second unbounded communicate can hold the controller lock after its advertised timeout; clean up only task-owned test processes.
- Test unexpected target autostart before local start intent, unknown phases, invalid proof digests, and crash after dated admission but before the first freeze. Do not equate absence of local intent with proof that no target delta exists.
- Separate kernel bugs, conditional failure-recovery gaps, and missing production acceptance. A trusted adapter contract and passing fixtures do not prove host fencing, receipt durability, authenticated owner approval, input preservation, or a real target dialogue.
- Report exact file/line, severity, triggering precondition, observed result and one narrow correction direction. Preserve source originals, target deltas and current cancellations; uncertainty must never authorize starting a second owner.
