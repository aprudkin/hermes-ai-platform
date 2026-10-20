# Hermes settings and personal-state backup

`task backup:hermes:personal` saves settings and personal state, not a self-contained
copy of the runtime. It keeps configuration and authentication, memory and
history, custom skills and jobs, and custom application source and data. It
omits the Docker image and recognized caches and dependency installations.
Restore requires a separately installed Hermes image and rebuilt dependencies.
Verification does not establish that a live restore or integrations work.

## Create a backup

After authorizing a live backup, run from this repository on the controller:

```bash
task backup:hermes:personal
```

`task b:hermes:personal` is the project-local short alias. The direct
`./scripts/hermes_backup.sh` CLI without flags also retains personal mode.

The ordinary `task backup:hermes`, `task b:hermes` and `task hermes:backup`
now create a **full** recovery bundle instead. The existing global launchers
`t backup:hermes` / `t b:hermes` follow that full default. To run personal mode
from another directory without adding a global launcher:

```bash
task --dir "$HOME/dev/hermes-ai-platform" backup:hermes:personal
```

With no deployment variables set, the wrapper connects to `hermes-minimal` and
lets SSH read its user and identity from the controller's `~/.ssh/config`.
Configure that alias for the intended Hermes server before running the task.
No Terraform lookup is needed for this default.

To override the connection, set `HERMES_DEPLOY_HOST` to an SSH alias or address.
`HERMES_DEPLOY_SSH_USER` and `HERMES_DEPLOY_SSH_PRIVATE_KEY` are optional overrides;
a supplied key must be an existing regular file. For compatibility, supplying
either user or key **without a host** retains the `server_ipv4` lookup from
local Terraform state. Set the host explicitly when overriding credentials
for an alias. Empty values are treated as unset. No Terraform apply is run.

The server account needs permission to read the state, stage a snapshot beneath
`/opt/hermes`, and use Docker without an interactive prompt; the wrapper does
not invoke `sudo`. The controller needs Python 3; the server needs Python 3,
Docker and GNU tar.

The default destination is
`~/backup/hermer/hermes-personal-<UTC timestamp>-<process id>.tar.gz`.
Set `HERMES_BACKUP_DIR` to override it. The final archive is mode `0600` and is
published only after successful transfer and verification. Prior backups remain
untouched. There is no schedule, retention policy, automatic restore or upload.

**The archive contains credentials and is not encrypted.** Protect it and any
extracted files, and transfer it only to an authorized recipient over an
encrypted connection. Never attach it to an issue or add it to Git.

## Independent storage and recovery kit

Run capture from the owner's computer, **not inside the container being paused**.
Set `HERMES_DEPLOY_HOST` to the intended SSH alias/address and choose a private
`HERMES_BACKUP_DIR` on that computer. Verify that it is not merely a mount of the
old server. New archive files use `0600`; keep the containing directory private
(`0700`) and protect both archive and temporary verification space with encrypted
storage. The tools do not configure or verify disk encryption.

Another destination may be an owner-approved encrypted external volume mounted
on the controller, or a separately authorized remote storage service. For a
mounted volume, point `HERMES_BACKUP_DIR` at a private directory on it. For remote
storage, transfer only over authenticated encrypted transport and only after its
access controls and encryption-at-rest/key-recovery arrangement are selected.
No provider/account/key is assumed. Re-download/read the stored copy and run the
verifier again; a successful upload alone is not verification. Keep at least one
previous accepted copy until a replacement has passed verification and a restore
rehearsal; these scripts do not delete old copies or schedule retention.

Keep a recovery kit available **without the old server**: the archive, this guide
and trusted verifier (also embedded in the bundle), access to the destination
and its independently stored recovery credentials, target-host SSH access and
provider/Telegram account recovery access. Test that the owner can access the
copy from their computer. Never keep the only decryption/recovery credential in
the state that needs restoring. Existing `.tar.gz` files remain unencrypted;
permissions and SSH transport do not change that fact.

## What is retained

The state snapshot contains filtered `/opt/hermes/data` and `/opt/hermes/app`
trees, including:

- Current configuration, authentication and profile identities.
- Memory, session/history databases and their WAL files.
- Custom skills, scripts, cron definitions, plugins and application source/data.
- Package manifests and lockfiles needed to reinstall dependencies.
- Deployed Compose, gateway selection and rollback configuration.

Unknown files and custom binaries are retained, not discarded because of size.
This is not a fixed-size or configuration-only archive: personal applications,
logs, databases and unclassified files can still be large.

The bundle also contains `manifest.json`, `container-inspect.json`,
`image-inspect.json`, `compose.restore.json`, `verify.py` and this guide as
`RESTORE.md`. Inspection and Compose metadata can contain credentials. Image
metadata records the source runtime; **there is no `image.tar`**. The saved
Compose definition retains the original image reference, not a local
recovery-image tag. Obtain that image separately or reconcile the reference
before starting; the backup does not prove it is still available.

## What is excluded

The personal-state policy excludes these recognized regeneration paths:

- Paths named `.cache`, `.npm`, `node_modules`, `__pycache__`, `.venv` or
  `.cli-venv` beneath the saved trees.
- uv-managed Python/tool installations under `.local/share/uv`.
- Hermes `lazy-packages` at the default data home or a named profile home.

These exclusions do not remove ordinary `cache/`, `env/`, `bin/` or `.local/`
trees wholesale. They do not apply to the full recovery mode. User changes
stored inside an excluded cache or dependency directory are also excluded;
keep authoritative source/data outside those regeneration paths. Hardlinks to
retained files still preserve their data when a cache-side link is omitted.

The backup also excludes the image itself, unrelated host files, OS packages,
controller SSH keys and Terraform state, and external service data/settings.
Dependency versions or external downloads may no longer be available later;
this backup does not guarantee offline reconstruction of the exact runtime.

## Snapshot and verification

The helper stages one filtered state tar privately on the server. It does not
export the Docker image. Space planning covers retained state, tar-entry
metadata and a safety margin. The bot is paused while the state snapshot is
written, then unpaused before hashing, compression and SSH transfer.

Do not deploy or edit server state concurrently. The capture lock prevents
another instance of this backup, not other administration. The snapshot is
crash-consistent, not a coordinated transaction with external APIs. The state
tar command has a 300-second timeout; post-unpause processing has a separate
90-minute deadline. Neither is an end-to-end pause-duration guarantee.

Failure cleanup attempts to release the pause it owns and remove staging. It
refuses an already paused container and reports unpause failure rather than
success. Host/process failure can prevent cleanup; check actual runtime state
before resuming operations after an abnormal termination.

The controller temporarily stores uncompressed payloads while verifying them;
allow space for the compressed archive plus retained state in `TMPDIR` or the
OS temporary directory. Verification checks the distinct personal format,
required files, hashes, state boundaries and exclusions. A full recovery bundle
or a legacy data-only tar cannot masquerade as this format.

To verify locally without contacting the server or starting Hermes:

In Bash, select the actual trusted archive (the prompt reads a path, not a secret):

```bash
read -r -p 'Trusted backup archive path: ' HERMES_BACKUP_FILE && export HERMES_BACKUP_FILE
```

Then verify it locally:

```bash
task verify:hermes
```

Hashes detect corruption, not a maliciously replaced backup. Use only a trusted
archive. Verification does not check provider tokens, run jobs or probe Telegram.

## Manual recovery boundary

Prepare a separately authorized, clean Ubuntu 24.04+ target with Docker and
Compose. Use the saved image reference/metadata to obtain a compatible Hermes
image separately. Preserve any architecture requirements of retained custom
binaries. Do not start a second instance with the restored credentials while
the source still owns Telegram polling or scheduled jobs.

On the **new target**, with no existing `/opt/hermes` or `hermes` container,
follow the [offline restoration entry point](https://github.com/aprudkin/hermes-ai-platform/blob/main/docs/backup-restore.md#restore-files-without-starting-hermes).
It supports both personal and full formats. In a root Bash shell with a trusted
checkout and `HERMES_BACKUP_FILE` set to the transferred archive, the current step is:

```bash
python3 scripts/hermes_backup_bundle.py restore-state "$HERMES_BACKUP_FILE" /opt/hermes
```

This verifies a private copy, restores `app/` and `data/`, and compares file
contents/basic stat metadata with the saved state using GNU tar. Any extraction
or comparison diagnostic fails closed, including warning-only ACL/xattr writes.
GNU tar does not compare ACL/xattr values; verify those separately with native
target tools where required before runtime acceptance. It refuses any existing destination (including a
symlink), retains recovery payloads in `/opt/hermes/.recovery`, and never contacts
Docker or starts the gateway/jobs. An interrupted/failed extraction leaves a
partial directory: retain it for inspection and choose a fresh destination for
retry; do not treat it as restored. The command requires GNU tar and compatible
Linux ownership/ACL/xattr support. It is not a running-container acceptance test.

Allow space for the compressed private copy plus uncompressed verifier payloads
in `TMPDIR`, and retained payloads **plus extracted state** at the destination.
Use private encrypted storage for both locations. This deliberate duplication
keeps original recovery evidence available through acceptance.

Preserve numeric ownership, ACLs and attributes on a compatible Linux
filesystem; do not recursively assign everything to one UID. Attribute errors
mean the restore is incomplete. Do not run the normal full installer over the
restored state: it reconciles configuration rather than preserving it verbatim.

Rebuild excluded dependency environments using retained manifests/lockfiles
and each application's installation instructions. Check custom applications
and scheduled jobs for missing tools; this guide cannot supply undocumented
application dependencies. Review the saved Compose definition and install it
as `/opt/hermes/app/compose.restore.json` with mode `0600`. Validate it with
`docker compose --file /opt/hermes/app/compose.restore.json config --quiet`;
this does not start Hermes or prove runtime behavior.

Use `/opt/hermes/.recovery/compose.restore.json` as the saved definition.
Before startup, review every restored scheduler/job definition against the owner's
current decisions. Keep cancelled reports and mail monitoring disabled even if
they appear in an older archive. See the full guide's isolated checks and cutover.

Only after dependencies, single-owner cutover and external side effects have
been separately authorized should the restored service be started. Starting
can immediately run jobs or send messages. Check memory/history, custom apps,
authentication and actual integrations separately; container health alone is
not sufficient. Keep the source and backup until recovery is accepted.

## When a full recovery bundle is needed

For explicit self-contained runtime migration, use
`./scripts/hermes_backup.sh --full` instead. It retains dependencies and exports
the exact Docker image. See the repository's
[full recovery guide](https://github.com/aprudkin/hermes-ai-platform/blob/main/docs/backup-restore.md).
Both the ordinary `task backup:hermes` and the image-upgrade preparation
workflow request full mode. Personal mode remains an explicit lightweight option.
