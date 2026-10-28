# Manual disposable Docker completion tests

These files are **test fixtures, not an installable authority/backend**. They
perform real Docker create/start/restart/stop operations and deliberate SIGKILL.
They are excluded from the ordinary local/CI behavioral suite. Do not run them
against a real agent or shared Docker daemon. Explicit opt-in without a disposable
environment does not make them safe.

The exercised environment is the retained no-NIC QEMU guest from the isolated
rehearsal. It already has `/opt/ivm/repo/` with the unchanged migration modules,
Docker 26.1.5, and a public locally generated `ivm-generated:fixture` image. These
files go in `/opt/ivm/` inside that guest. Do not rerun the earlier VM setup, attach
a host socket, transfer private state or enable networking to satisfy dependencies.

Only inside that explicitly authorized disposable guest:

```sh
IVM_DISPOSABLE_REVIEW=no-network-generated-state-only \
  python3 /opt/ivm/guest_acceptance_test.py
```

The suite creates unique `ivm-review-*` containers and generated data under
`/var/lib/ivm-review/`. All cases stop their exact containers but deliberately
retain containers, data, original binding, terminal/pending receipts and Docker
events for readback. Export evidence before guest shutdown; retain its disk for
review. There is no prune/global cleanup command. A run without opt-in exits2
before importing or touching Docker.

`serial_authority.py` implements only the closed, trusted **test requester** set:
start/restart of one pre-created full container ID, flock over request+receipt,
boot/nonrenewed deadline binding, terminal HTTP204, and sticky uncertain intent.
The test harness intercepts the atomic receipt call only to place actual SIGKILL
before dispatch or after effect. Docker and its responses are not mocked.
Generated JSON is not an admission interface. Files are assumed protected from
malicious administrator mutation. This is not an authorization proxy and does
not cover arbitrary Docker APIs. The operation lock is advisory, the HTTP client
has a timeout, and unknown results remain blocked rather than becoming cancellation.
The fixture's monotonic clock is same-guest-only; production clock/suspend/remote
lease contracts are not established. Preflight always stays false.

The accepted-restart test proves daemon acceptance using its signal15 event,
then kills the **actual requesting Python process**. A later changed StartedAt
proves the restart proceeded after client death/expiry. The pending receipt is
not erased or upgraded after that observation. The completion/drain test instead
waits for the original live request's terminal response before stopping.

See [review and adopted/rejected assumptions](../../../docs/migration-docker-completion-review.md).
