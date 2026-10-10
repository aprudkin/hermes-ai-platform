# Hermes settings and personal-state backup

`task backup:hermes` saves settings and personal state, not a self-contained
copy of the runtime. It keeps configuration and authentication, memory and
history, custom skills and jobs, and custom application source and data. It
omits the Docker image and recognized caches and dependency installations.
Restore requires a separately installed Hermes image and rebuilt dependencies.
Verification does not establish that a live restore or integrations work.

## Create a backup

After authorizing a live backup, run from this repository on the controller:

```bash
HERMES_DEPLOY_HOST=hermes-minimal \
HERMES_DEPLOY_SSH_USER=root \
HERMES_DEPLOY_SSH_PRIVATE_KEY="$HOME/.ssh/luk" \
task backup:hermes
```

`task b:hermes` and `task hermes:backup` are aliases for the same personal-state
backup. With the controller's global go-tasks catalog installed, use
`t backup:hermes` or `t b:hermes` from another directory.

Use the intended SSH alias/address and existing key. The server account needs
permission to read the state, stage a snapshot beneath `/opt/hermes`, and use
Docker without an interactive prompt; the wrapper does not invoke `sudo`.
The controller needs Python 3; the server needs Python 3, Docker and GNU tar.
An omitted `HERMES_DEPLOY_HOST` resolves through `server_ipv4` in local Terraform
state, without applying infrastructure changes.

The default destination is
`~/backup/hermer/hermes-personal-<UTC timestamp>-<process id>.tar.gz`.
Set `HERMES_BACKUP_DIR` to override it. The final archive is mode `0600` and is
published only after successful transfer and verification. Prior backups remain
untouched. There is no schedule, retention policy, automatic restore or upload.

**The archive contains credentials and is not encrypted.** Protect it and any
extracted files, and transfer it only to an authorized recipient over an
encrypted connection. Never attach it to an issue or add it to Git.

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

```bash
python3 scripts/hermes_backup_bundle.py verify /secure/path/hermes-personal.tar.gz personal
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
verify the trusted backup before extracting its state. In a root Bash shell:

```bash
set -euo pipefail
umask 077
BUNDLE=/secure/path/hermes-personal.tar.gz
RECOVERY=$(mktemp -d /root/hermes-personal.XXXXXX)
cd "$RECOVERY"
tar -xOzf "$BUNDLE" verify.py > verify.py
python3 verify.py verify "$BUNDLE" personal
tar -xzf "$BUNDLE"
test ! -e /opt/hermes
docker info >/dev/null
if docker container inspect hermes >/dev/null 2>&1; then
  printf 'Refusing to overwrite an existing Hermes container\n' >&2
  exit 1
fi
mkdir -m 0750 /opt/hermes
tar --extract --file state.tar --directory /opt/hermes \
  --numeric-owner --same-owner --same-permissions --acls --xattrs --xattrs-include='*'
```

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
The existing image-upgrade workflow continues to request this full mode before
an upgrade; the ordinary backup task does not.
