# Chebi maintenance repository

## Scope

Maintain one existing Hermes Agent: its approved instructions, container
reference, independent backups, recovery and deliberate updates. No server
provisioning, role expansion, new infrastructure platform or historical roadmap.
The active profile is `manager`, identity Чеби / Chebi.

The live profile under the persistent host data mount is authoritative for
personal state. `profiles/manager/SOUL.md` is an approved versioned snapshot,
not a deployment template to overwrite live edits. Never commit credentials,
private memory, histories, databases, SSH keys or backup archives.

Read README.md and the relevant current guide before changing behavior:
- `docs/state-first.md` and `docs/architecture.md`: ownership and runtime layout.
- `docs/operations.md`: current maintenance and image-update boundaries.
- `docs/personal-backup.md`, `docs/backup-restore.md`: capture and recovery.
- `docs/migration.md`: provider-independent relocation, host-only settings and cutover.
- `docs/cloud-backup.md`, `docs/server-backup.md`: explicit cloud/host workflows.

## Implementation

Keep working capture, crypt transfer, narrow receipt-based retention and
verification. Do not replace real behavior with stubs or disable failure gates
to simplify the repository. Keep script/Task aliases used by the owner's global
launcher. Connection defaults come from an existing SSH alias, with optional
explicit host/user/key overrides; no infrastructure-state lookup.

Use a failing regression before a behavior change, then run the affected tests
and the strict gate. Fixtures do not prove a live backup or restore. Inspect
explicit SKIP lines and report unexecuted checks honestly.

## Commands

- `./scripts/validate.sh --all` or `task validate`: strict local static and behavioral checks.
- `./scripts/validate.sh --static`: current artifacts, shell/Python syntax,
  ShellCheck, real Compose rendering and secret-pattern scan.
- `./scripts/validate.sh --local`: opportunistic local checks; not strict proof.
- `bash tests/run.sh`: current behavioral suite only.

Strict dependencies: Git, Bash, Python 3 + PyYAML, ripgrep, ShellCheck, Docker Compose,
and Go Task. CI installs its declared dependencies. No live service should be
started by validation; tests use temporary fixture state and bounded fake I/O.

## Operational boundaries

Keep local edits, publication, deployment and actual behavior distinct. Verify
remote changes by read-back. Use current task authorization; passing CI is not
permission to restore data, start a second bot, spend money or expose secrets.
Do not restart/redeploy the live agent as part of a repository cleanup.

Full captures must run outside the source container. Retain a verified
independent copy and owner-accessible recovery material before risky changes.
A restore needs a clean compatible Linux/Docker target; never overwrite the
running data tree. Block external effects for rehearsal, preserve cancelled-job
state, and use single-owner Telegram/cron cutover with a retained rollback path.

For image changes, review the exact upstream release, preserve the preparation
script's backup/compatibility gates, and validate the candidate pin. Matching a
local pin does not establish a deployed update. Never start an older image over
possibly migrated data without a separately considered recovery plan.
