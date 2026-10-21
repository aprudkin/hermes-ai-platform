# Move Chebi to another hosting provider

This is a route through the existing recovery tools, not a new deployment
platform. The hosting provider can change; the supported target remains a
compatible Linux/Docker host with the saved image's CPU architecture. Buying
resources, host preparation and production cutover are separate authorized
operations. No migration or restored-runtime test is implied by this guide.

## 1. Have a recovery set that does not need the old server

Keep these available on the owner's independent computer/protected storage:

- A trusted **full** recovery bundle, locally or in the configured crypt cloud
  storage. Personal-only archives do not contain the image/dependencies needed
  for this route.
- The independently saved rclone recovery config, including the crypt keys,
  and access to its cloud account. A cloud login alone cannot decrypt a copy.
- Access to the new host/provider console and this repository, or the trusted
  `verify.py` and `RESTORE.md` embedded in a supported bundle.
- The current approved job/access list, so an older snapshot does not revive
  cancelled jobs or withdrawn credentials. Record a usable snapshot date.

A backup contains only files present at capture time. A key or memory saved
later is not retroactively added. The source host, this agent and its SSH access
must not be the only route to the archive or decryption material.

For a planned move, create and verify a fresh full copy from an independent
controller using [the full-backup procedure](backup-restore.md#create-a-recovery-bundle).
Capture resumes the source; subsequent messages and writes are **not** in that
snapshot. Arrange a quiet window and document that boundary. Do not claim a
zero-loss cutover just because the copy is recent. If the source is lost, use
an already existing independent copy and explicitly accept its recovery point.

## 2. Retrieve a scheduled cloud copy without the source

An existing verified local archive can go straight to step 3. For a scheduled
copy, use a trusted controller with rclone and Python available. Keep configs
and downloaded plaintext on private, preferably encrypted storage. The recovery
config must be a trusted private regular file, not a supplied untrusted config.
Read [cloud key custody and configuration](cloud-backup.md) first.

In the same Bash shell, select the independently saved config and list only
this workflow's decrypted-view names. Do not paste private listings into public
reports. Listing is not a proof that an object is verified:

```bash
set -euo pipefail
umask 077
read -r -p 'Absolute path to saved recovery rclone.conf: ' RECOVERY_CONFIG
[[ "$RECOVERY_CONFIG" == /* && -f "$RECOVERY_CONFIG" && ! -L "$RECOVERY_CONFIG" ]] || exit 1
rclone --config "$RECOVERY_CONFIG" lsf hermes-backup:scheduled-v1/ --files-only --max-depth 1
```

Choose an exact scheduled basename, download/decrypt into a new private
directory and verify the result. `TMPDIR`, if set, should be on protected
storage with enough space for the download and verification scratch:

```bash
read -r -p 'Exact scheduled archive basename: ' ARCHIVE_NAME
[[ "$ARCHIVE_NAME" =~ ^hermes-scheduled-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}\.tar\.gz$ ]] || exit 1
RECOVERY_DOWNLOAD=$(mktemp -d)
HERMES_BACKUP_FILE="$RECOVERY_DOWNLOAD/recovery.tar.gz"
export HERMES_BACKUP_FILE
rclone --config "$RECOVERY_CONFIG" copyto "hermes-backup:scheduled-v1/$ARCHIVE_NAME" "$HERMES_BACKUP_FILE"
python3 scripts/hermes_backup_bundle.py verify "$HERMES_BACKUP_FILE" full
```

On failure, retain the private partial download for inspection and use a new
directory for retry. Do not overwrite a previous accepted copy. Manual cloud
uploads are in `hermes-backup:full/` with their original basenames: select the
exact approved object separately, not a scheduled-name pattern. Do not use
`sync`, `purge` or deletion while retrieving recovery material.

If GitHub is also unavailable, use the trusted embedded helper as described in
[recovery without a checkout or old server](backup-restore.md#recover-without-this-checkout-or-the-old-server).
An embedded verifier is executable code from the archive, not an independent
signature; the archive's trusted provenance still matters.

## 3. Prepare the destination, not a second production agent

- Prepare Ubuntu 24.04+ with Docker Engine, its Compose plugin and GNU tar.
  Match the saved image's OS/CPU architecture; do not assume x86 images,
  native dependencies and virtual environments will work on ARM.
- Check the required Docker image-store format, numeric ownership, ACL/xattr
  support and disk budget in [clean-target requirements](backup-restore.md#prepare-a-clean-target).
  Preserve numeric file ownership; the host SSH user is not necessarily the
  container's data UID. Do not recursively chown recovered state to that user.
- Establish approved SSH/administrative access, firewall and provider security
  rules. Outbound cloud/model/Telegram connectivity may differ by provider.
  Keep API/dashboard endpoints on loopback; host networking does not provide
  isolation merely because Compose publishes no ports.
- Require a new destination with no existing `/opt/hermes` and no `hermes`
  container. The restore helper refuses even an existing empty destination.

A new provider means new host keys and usually a new address. Verify the new
SSH host key through the trusted provider/console route. Keep a separate target
alias during rehearsal. Do not disable host-key checks or blindly erase the
old host's pinned key. After accepted cutover, deliberately update controller
aliases and the restored agent's host-access config to the new destination;
retain old connection settings for rollback. Restoring a private key does not
create its authorized account on the new host.

## 4. Restore offline and rehearse in isolation

Follow [file restoration](backup-restore.md#restore-files-without-starting-hermes),
then its exact image loading/tagging and saved `compose.restore.json` procedure.
Use the definition derived from the captured runtime, not the repository's
reference Compose file. Do not run a fresh setup over restored personal state.

Check Chebi's identity, memory/history, SQLite integrity, skills, applications,
dependencies and approved jobs offline. Use disposable copies for checks that
can modify state. If running an offline process, follow
[isolated acceptance](backup-restore.md#isolated-acceptance-before-cutover):
no network, production credentials, normal gateway/scheduler entrypoint,
restart policy or live Docker socket. **Do not use production Compose up as a
rehearsal**, even on a different host.

## 5. Restore host-only settings separately

The full bundle covers Hermes `app/`, `data/` and its image, not the host OS.
It does **not** include host SSH authorization, firewall, provider settings,
Docker installation or the following host backup workflow files:

- `/etc/hermes-backup/` — cloud working/recovery configuration;
- `/usr/local/lib/hermes-backup/` — installed package and pinned rclone binary;
- `/var/lib/hermes-backup/` and `/var/log/hermes-backup/` — receipts/originals/logs;
- `/etc/systemd/system/hermes-backup.service` and `.timer`.

Reinstall the daily backup from trusted current source and independently kept
recovery material using [its dedicated procedure](server-backup.md#install-and-activate-host-backups--separate-authorizations).
Validate its protected paths, approved binary, native unit syntax and timezone.
Do not enable it automatically during rehearsal: `Persistent=true` can cause an
immediate catch-up and a container pause. A cold-start receipt ledger must not
be reconstructed from a cloud listing or used to delete unknown old copies.
Previously unreceipted cloud objects remain outside automatic retention.

## 6. Cut over once, with a rollback point

Follow [ownership switch and acceptance](backup-restore.md#switch-ownership-and-verify-behavior):

1. Before the agreed switch, disable the old host's backup timer and let any
   active capture finish. Record its settings rather than interrupting its pause
   cleanup. Fence the old gateway/container and any restart/recreation paths.
2. Confirm the old installation cannot own polling or scheduled external writes.
   In disaster recovery, an unreachable host is not proof it is stopped: fence
   it through the provider or otherwise establish single ownership first.
3. Start only the accepted restored definition. Verify the actual image/profile,
   loopback health, memory/history, applications, then authorized model and
   Telegram behavior. Restored OAuth/API credentials may need reauthorization;
   do not reactivate withdrawn mail access or cancelled reports.
4. Separately test/activate the new host backup workflow and verify its first
   real timer-triggered result. Update read-only health checks that still point
   at the old server; a check inside Hermes is not an independent outage monitor.

Keep the source stopped but recoverable until acceptance. If the new instance
fails, stop/fence it before returning to the source. Capture/preserve any newer
state first; starting the old snapshot can lose messages or repeat side effects.
Do not delete the old host, accepted archives or recovery keys as part of the
switch. Record independently: archive verified, files restored, isolated checks
passed, production behavior accepted, and new scheduled backup verified.
