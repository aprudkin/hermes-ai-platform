# Keep the running state; rebuild the packaging

This installation is one long-lived Hermes environment for Чеби (Chebi), using
the `manager` profile. This repository maintains and recovers that environment;
it does not provision servers or bootstrap a new installation. Routine work
must not replace personal state with repository reference files.

## Which instructions are authoritative?

The active profile's `SOUL.md`, memory, skills, configuration and scheduled-job
state live in the persistent data directory. The normal mapping is
`/opt/hermes/data` on the host to `/opt/data` in the container. The manager
profile therefore lives at `/opt/hermes/data/profiles/manager` on the host.
Container replacement alone does not replace that mounted directory. Names,
personal instructions, memory/history, skills, plugins, scripts, application
data/databases and scheduler settings belong there. `/opt/hermes/app` holds the
deployed Compose/gateway selection and rollback configuration. The container's
writable image layer, `/tmp`, and unmounted host paths are not a substitute for
persistent state; keep required custom dependencies inside the data boundary
or explicitly document and back up their external home.

`profiles/manager/SOUL.md` in this repository is a versioned snapshot of the
operator-approved Chebi identity. Keep identity revisions deliberate and
reviewable. Do not commit credentials, user-memory files, conversation/session
databases, accounting records or complete backup archives to Git.

The repository seed is not synchronized into the live profile automatically.
Preserve the live identity during maintenance and recovery. A missing identity
on a genuinely new profile may be initialized from the reviewed seed only as
an explicit operator action, not as an implicit update step. Replacing a
personalized identity requires owner approval and a private byte-exact copy of
the previous file before writing; do not commit that private copy to Git.

Before accepting recovery, check that Chebi's restored identity is a nonempty
regular file and matches the intended saved identity, not necessarily the Git
seed. For an explicitly approved seed replacement, compare exact bytes,
including trailing newlines. A file comparison is not proof of the model's
prompt or behavior: a live conversation can still contain an earlier prompt
snapshot. Do not reset sessions or restart a gateway just to make a comparison
look successful.

The repository cannot override the framework's or provider's higher-priority
instructions. Project files such as `AGENTS.md` govern work in the repository;
they are not a reason to impose a developer workflow on ordinary conversation.

## Backups, not a bigger platform

Keep a recent private recovery copy outside this server. A directory inside
`/opt/data` is on the same server and is not an independent backup, even if a
script calls it a controller destination. The operator's computer is a useful
independent destination; independently stored encrypted copies add protection.
Choose and verify a real destination before claiming off-server protection.

The repository already provides:

- [Personal-state backup](personal-backup.md): configuration/authentication,
  identity, memory/history, skills, scripts, plugins and application data;
  no Docker image or recognized dependency/cache trees.
- [Full recovery bundle](backup-restore.md): state plus the exact runtime image
  and retained dependencies for a planned migration.

Both current bundle formats contain secrets and are **not encrypted by the
capture scripts**. A separate [Mail.ru cloud Task](cloud-backup.md) encrypts an
existing full archive's remote copy through the approved crypt configuration,
then verifies a recovery-config download; it does not encrypt the local archive.
Protect transfers and storage; do not describe them as
encrypted or upload them to a new recipient without a real implementation and
an authorized destination. Local validation, checksums and an existing tar file
are not proof of a successful live restore.

The capture helper briefly pauses the source container for a crash-consistent
snapshot. Run live capture from an independent controller/host process, not
from a command inside the container being paused: freezing the initiator can
stall the capture. The SSH account must have the documented read/Docker
permissions; the current wrapper does not automatically add sudo.

The separate [host systemd workflow](server-backup.md) can capture and verify
daily cloud backups after explicit installation, execution and timer-activation
approval. It runs outside Hermes, not as a restored agent job. Repository
contents alone do not establish an active schedule, independent key custody or
working monitoring. No storage account or new cloud resource is provisioned,
and no cancelled reports or mail monitoring are re-enabled. Before activating a
restored snapshot, reconcile every scheduler against the owner's current
approved job list; an older archive or template does not override cancellation.

## A planned move

1. Capture and verify a fresh trusted full recovery bundle, outside the source
   container, while the old server is still available.
2. Keep an independent copy and the means to access/decrypt it available to the
   operator, not solely inside the old server.
3. Prepare a clean compatible Linux target with Docker and Compose already
   installed. Restore using the bundle's guide; do not overwrite recovered state
   with reference configuration or an unrelated setup process.
4. Inspect restored files and dependencies offline first. Do not start a second
   live bot with restored credentials: Telegram polling, cron jobs and external
   writes must have only one active owner.
5. Perform a deliberate cutover, verify actual memory/history and integrations,
   and retain the old server and backup until recovery is accepted.

If the source server has already failed, a pre-existing independent copy is
needed. No agent can first save files from a server it can no longer reach.
External accounts and provider authentication may need recovery separately;
a filesystem archive does not preserve a running process or guarantee that a
third-party credential remains valid.
