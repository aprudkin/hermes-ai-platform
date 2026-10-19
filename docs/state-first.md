# Keep the running state; rebuild the packaging

This installation is one long-lived Hermes environment, not a platform that
needs continual infrastructure expansion. Terraform and Ansible remain useful
recovery/bootstrap tools, but routine work should not require redeploying the
server or replacing personal state with the original templates.

## Which instructions are authoritative?

The active profile's `SOUL.md`, memory, skills, configuration and scheduled-job
state live in the persistent data directory. The normal mapping is
`/opt/hermes/data` on the host to `/opt/data` in the container. The manager
profile therefore lives at `/opt/hermes/data/profiles/manager` on the host.
Container replacement alone does not replace that mounted directory.

`profiles/manager/SOUL.md` in this repository is a versioned snapshot of the
operator-approved Chebi identity. Keep identity revisions deliberate and
reviewable. Do not commit credentials, user-memory files, conversation/session
databases, accounting records or complete backup archives to Git.

Ordinary Ansible deployment preserves an existing profile identity. A newly
created profile receives its reviewed template even if upstream profile
creation seeded a cloned/default identity. An existing profile with no identity
file receives the template too. Deliberately replacing an existing identity
requires the explicit Ansible variable `hermes_replace_profile_identities=true`;
the copy module keeps a backup of replaced bytes. The default is `false`.

In preserve mode, verification checks that identity files exist and are
nonempty regular files; it does not falsely require locally edited words to
match a historical Git template. In explicit replacement mode, verification
also requires the exact repository bytes, including trailing newlines. This is
not a proof of the model's prompt or behavior: a live conversation can still
contain an earlier prompt snapshot. Do not reset sessions or restart a gateway
just to make a file comparison look successful.

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
existing scripts**. Protect transfers and storage; do not describe them as
encrypted or upload them to a new recipient without a real implementation and
an authorized destination. Local validation, checksums and an existing tar file
are not proof of a successful live restore.

The capture helper briefly pauses the source container for a crash-consistent
snapshot. Run live capture from an independent controller/host process, not
from a command inside the container being paused: freezing the initiator can
stall the capture. The SSH account must have the documented read/Docker
permissions; the current wrapper does not automatically add sudo.

No off-server schedule, encryption service, storage account or new cloud
resource is provisioned by this documentation change. In particular, it does
not re-enable any cancelled Jira or bookkeeping reports.

## A planned move

1. Capture and verify a fresh trusted full recovery bundle, outside the source
   container, while the old server is still available.
2. Keep an independent copy and the means to access/decrypt it available to the
   operator, not solely inside the old server.
3. Prepare a clean compatible target. Restore using the bundle's guide rather
   than running a full installer over the recovered state.
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
