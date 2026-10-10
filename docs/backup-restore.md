# Portable Hermes backup and manual recovery

This guide is included as `RESTORE.md` in each recovery bundle. It covers one
Hermes container on Ubuntu 24.04 or newer, using host networking and the single
`/opt/hermes/data:/opt/data` bind mount. It is not a whole-server backup or an
automated restore command. A successful backup verification does not establish
that a live restore or the bot's integrations have been tested.

## Create a recovery bundle

Run from this repository on the controller, after authorizing a live backup:

```bash
HERMES_DEPLOY_HOST=hermes-minimal \
HERMES_DEPLOY_SSH_USER=root \
HERMES_DEPLOY_SSH_PRIVATE_KEY="$HOME/.ssh/luk" \
task backup:hermes
```

`task b:hermes` is the short alias; `task hermes:backup` remains compatible.
With the controller's global go-tasks catalog installed, the same operation is
available from any directory as `t backup:hermes` or `t b:hermes`.

Use the intended SSH alias or address and existing private-key path. These
connection values describe this project's deployment, not an arbitrary new
host. The SSH account needs root or equivalent permissions to read all Hermes
state, create the lock and private staging beneath `/opt/hermes`, and access
Docker without an interactive privilege prompt. The wrapper does not invoke
`sudo`. If `HERMES_DEPLOY_HOST` is omitted, the task
uses `server_ipv4` from the controller's local Terraform state. There is no
Terraform apply. `HERMES_BACKUP_DIR` overrides the local destination; its default
remains `~/backup/hermer`.

The result is `hermes-recovery-<UTC timestamp>-<process id>.tar.gz`, mode `0600`.
Only a completed and verified transfer receives that final name. Existing
backups are retained; there is no schedule, retention policy or automatic upload.
Legacy `hermes-data-*.tar.gz` files remain usable as data-only archives but do
not satisfy the recovery-bundle verifier.

The task stages one saved Docker image and one data/app snapshot on the server.
Its free-space estimate is their combined size, plus tar-entry overhead and a
64 MiB margin; this is a temporary-space requirement, not the final archive
size. Compression streams directly to the controller: no second compressed
bundle or verification copy is stored on the server. Historical backups outside
`app/` and `data/` are not included.

The controller verifies the completed transfer before publishing it. Allow local
space for the compressed bundle plus an uncompressed state/image verification
copy in the temporary directory (`TMPDIR`, or the OS default). The image makes
the final bundle larger than the former data-only backup, but recovery no longer
depends on the old tag remaining available in a registry.

**The bot is temporarily paused while the state snapshot is written to the
server's disk.** It is unpaused before compression and network transfer. Do not
run a deployment, another administrator's state edits, or another backup at the
same time. The capture lock prevents overlapping instances of this backup,
not other administration tools. A pause freezes container writers; this is a
crash-consistent filesystem snapshot, not a coordinated transaction across
external APIs or a guarantee of preserving an in-flight conversation.

After unpause is confirmed, hashing, compression and transfer share a 90-minute
deadline. This is not a limit on the entire task or the pause duration. The state
snapshot command retains its separate 300-second timeout; container checks and
unpause also take time. Slow transfers can still exceed the deadline and fail
without publishing a final archive.

On a failure the task attempts to release its own pause and remove temporary
staging. It refuses an already paused container. If unpause fails, the task
fails rather than declaring success: check the actual container state before
resuming operations. A killed host, lost Docker daemon or forced process kill
can prevent cleanup; no shell or Python cleanup handler can guarantee recovery
from those events.

## Bundle contents and boundaries

| File | Purpose |
| --- | --- |
| `state.tar` | Complete `data/` and `app/` trees, archived with numeric ownership, ACLs and extended attributes |
| `image.tar` | Saved exact Docker image used by the inspected container |
| `compose.restore.json` | Standalone Compose definition derived from the supported running container, not the controller's possibly stale Compose file |
| `container-inspect.json` | Captured container configuration and metadata |
| `image-inspect.json` | Image identity, digest references, OS and architecture |
| `manifest.json` | Versioned bundle metadata, payload sizes and SHA-256 hashes |
| `verify.py` | Included offline bundle verifier |
| `RESTORE.md` | This recovery guide |

`state.tar` includes profiles, models/configuration, skills, custom scripts and
applications, memory, session databases and WAL files, cron definitions,
plugins, dependencies under the data volume, credentials, and the deployed
Compose/gateway selection/Telegram rollback files under `app/`. Runtime sockets
are not useful recovery state. The target runtime must recreate its transient
process state; a filesystem backup does not preserve running processes.

The helper refuses unsupported runtime boundaries rather than quietly omitting
an extra mounted volume or writable-image-layer customization. Outside the data
mount, only transient `/run`, `/tmp`, `/var/tmp` content and the changed parent
`/var` directory metadata are exempt from that refusal. Custom programs or
configuration elsewhere must not silently disappear from recovery.
The bundle does not preserve unrelated host files, Ubuntu packages, host
firewall/SSH policy, controller private keys, local Terraform state, provider
accounts, Telegram/BotFather settings, DNS or external service data. Keep access
to those services and the controller's infrastructure records separately. It is
a full recovery bundle for the supported Hermes deployment, not an audit or
backup of every possible host customization.

**Treat the entire bundle and its extracted files as credentials.** Both state
and inspection/Compose metadata can contain tokens. The archive is protected
by file permissions, not encrypted; use protected storage and encrypted
transport. Do not put it in Git, paste it into an issue, or upload it to an
unapproved recipient. Hashes detect corruption, not a maliciously replaced
bundle: use only a backup from a trusted source.

## Verify without starting Hermes

On the controller, use the current repository verifier:

```bash
python3 scripts/hermes_backup_bundle.py verify /secure/path/hermes-recovery.tar.gz
```

Verification checks the bundle format, required contents, payload hashes and
recovery metadata without extracting user files or displaying their contents.
For classic Docker image IDs, it checks the saved configuration digest. For OCI
index or manifest IDs, it verifies the saved descriptor chain to the selected
platform's configuration and ordered layers instead of equating those distinct
digests. A missing or inconsistent identity chain is rejected.
It temporarily writes private opaque copies of the nested tar payloads and
removes them afterward. Saved image layers may be uncompressed or gzip; zstd
layers require a Python runtime with the standard-library `compression.zstd`
decoder, otherwise verification explicitly fails. It does not log in to
providers, run jobs or connect to Telegram. A verification
failure blocks recovery until the cause is understood; do not compensate by
extracting the failed bundle over a live installation.

## Prepare a clean target

Use a separately authorized Ubuntu 24.04+ host with Docker Engine and the
Compose plugin installed. Match the saved image's OS and CPU architecture;
custom binaries and virtual environments inside the data volume may depend on
that architecture. Prepare appropriate SSH access, host firewall policy and
outbound access separately. Keep the dashboard/API on loopback as captured;
do not expose them publicly to make a migration work.

If the saved `image-inspect.json` has an OCI index or manifest in
`Descriptor.mediaType`, prepare the target with the
[containerd image store](https://docs.docker.com/engine/storage/containerd).
The classic image store uses configuration digests rather than these OCI
identities and cannot preserve the exact image-ID contract used below.
Docker Engine 29+ enables containerd on fresh installations; an upgraded daemon
may still use the classic store. Do not switch a populated host's storage
backend as an implicit recovery step.

Use a new, empty `/opt/hermes` destination and no existing container named
`hermes`. Its Linux filesystem must support the saved numeric ownership, ACLs
and extended attributes. Check that non-user attributes, such as file
capabilities or security labels, are compatible with the target's security
policy before restoring them. Do not run the normal full Hermes installer over restored state: it
reconciles selected settings, identities and credentials instead of preserving
the snapshot verbatim. These steps do not authorize provisioning or access.

Transfer the trusted archive over an authorized encrypted connection. The
following Bash commands are for a root shell on the **new target**, not the
source. Set `BUNDLE` to its absolute location. Stop if any command fails:

```bash
set -euo pipefail
umask 077
BUNDLE=/secure/path/hermes-recovery.tar.gz
RECOVERY=$(mktemp -d /root/hermes-recovery.XXXXXX)
cd "$RECOVERY"
# Extract only the verifier first from the trusted, previously checked backup.
tar -xOzf "$BUNDLE" verify.py > verify.py
python3 verify.py verify "$BUNDLE"
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

Preserve the archived ownership rather than recursively changing all files to
one UID: the app directory and runtime data have different ownership boundaries.
The explicit xattr include pattern restores namespaces beyond `user.*`, which
GNU tar otherwise omits on extraction; see its
[namespace compatibility explanation](https://lists.nongnu.org/archive/html/bug-tar/2023-05/msg00010.html).
Treat attribute-restoration errors as a failed restore, not harmless warnings.
Review image architecture and the protected recovery Compose definition before
loading or starting anything. Do not print credential-bearing metadata into
shared terminals or logs.

Load and tag the exact archived image for the recovery Compose definition:

```bash
docker image load --input image.tar
IMAGE_ID=$(python3 -c 'import json; print(json.load(open("image-inspect.json"))["Id"])')
RECOVERY_IMAGE=$(python3 -c 'import json; print(json.load(open("compose.restore.json"))["services"]["hermes"]["image"])')
test "$(docker image inspect --format '{{.Id}}' "$IMAGE_ID")" = "$IMAGE_ID"
docker image tag "$IMAGE_ID" "$RECOVERY_IMAGE"
install -m 0600 compose.restore.json /opt/hermes/app/compose.restore.json
docker compose --file /opt/hermes/app/compose.restore.json config --quiet
```

Configuration validation does not start a container and is not runtime proof.
Keep using this standalone restore file until the deployment configuration has
been deliberately reconciled; switching back to the old template may change
environment interpolation, the selected profile or the image.

## Switch ownership and verify behavior

**Do not start the restored bot while the source still owns Telegram polling or
scheduled work.** Starting the gateway can immediately run due jobs or send
messages using restored credentials. A disaster-recovery rehearsal must stay
isolated from those external services; merely using a second host is not
isolation.

For a planned move, stop the old Hermes instance immediately before the
separately authorized cutover and ensure nothing restarts it. For disaster
recovery, establish that the old instance cannot still run. For minimal data
loss during a planned move, arrange a quiet maintenance window around the final
backup and cutover: the backup resumes the source, so writes after its snapshot
are not present on the destination.

Only after ownership and side effects are authorized, start the restored
service:

```bash
docker compose --file /opt/hermes/app/compose.restore.json up --detach --pull never
docker inspect --format '{{.State.Status}} {{.State.Health.Status}}' hermes
```

Then independently check the selected gateway profile, loopback health, memory
and history availability, required custom applications and scheduled work.
Verify provider authentication and actual Telegram/model behavior only under
their applicable authorization; token expiry may require reauthorization.
Container health alone does not establish any of those behaviors.

Retain the source and the protected recovery files until the result is
accepted. If recovery fails, stop the new instance before considering a return
to the source. Restarting an older snapshot can lose new state or repeat
external actions; it is not an automatic rollback. Cleanup or source deletion
is a separate decision.
