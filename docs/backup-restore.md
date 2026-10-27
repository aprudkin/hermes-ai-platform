# Portable Hermes backup and manual recovery

This guide is included as `RESTORE.md` in each **full** recovery bundle created
with `task backup:hermes` or `./scripts/hermes_backup.sh --full`. For a smaller
[personal-state backup](https://github.com/aprudkin/hermes-ai-platform/blob/main/docs/personal-backup.md)
without an image or recognized caches/dependencies, explicitly select
`task backup:hermes:personal`. This full guide covers one
Hermes container on Ubuntu 24.04 or newer, using host networking and the single
`/opt/hermes/data:/opt/data` bind mount. It is not a whole-server backup or an
automated service recovery/start command. The `restore-state` helper only restores
and compares files; image loading, isolated runtime checks and cutover remain explicit. A successful backup verification does not establish
that a live restore or the bot's integrations have been tested.

## Create a recovery bundle

Run from this repository on an independent controller, after authorizing a live
backup. **Never initiate capture inside the source container**: capture pauses
that container and can freeze its own initiator. A host-side process can capture
safely, but a copy kept only on that host is not independent recovery storage:

```bash
task backup:hermes
```

The command prints total elapsed time (`HH:MM:SS`) while waiting for the source,
then received MiB and the recent transfer rate every five seconds. During local
verification it reports total elapsed time and time spent verifying. The final
verified message includes total duration. No percentage or ETA is shown because
the compressed archive size is unknown until the stream ends. The source also reports actual stage transitions: runtime/space checks, image
export, pause, state snapshot, unpause confirmation, hashing, then compression
and transfer. Each source message includes source elapsed time and the duration
of the preceding stage. Local verification identifies decompression/hashing,
state checks and image-layer checks. Before the first source message, only
connection/startup is known; a heartbeat alone does not prove server progress.
Stage messages come from the generated capture program, so an already running
backup cannot acquire newly added messages; they apply to the next invocation.
Progress is not successful verification or current source health.

This task calls `./scripts/hermes_backup.sh --full`. Its `b:hermes` and
`hermes:backup` aliases, and the explicit `backup:hermes:full` task, all create
full bundles. Where the owner's existing global catalog delegates to this
checkout, `task -g b:hermes` (or `t b:hermes`) invokes the same task from another
directory. This repository does not install that catalog.

The direct script without flags creates a personal backup. Image-update
preparation uses full mode for its pre-update backup and does not deploy.

With no deployment variables set, the wrapper uses the `hermes-minimal` alias
and its user and identity from the controller's `~/.ssh/config`. Configure that
alias for the intended Hermes deployment. `HERMES_DEPLOY_HOST` overrides the
alias/address; `HERMES_DEPLOY_SSH_USER` and `HERMES_DEPLOY_SSH_PRIVATE_KEY` optionally
override the user and key. A supplied key must be an existing regular file.
When only user/key is supplied, the host still defaults to `hermes-minimal`.
Empty values are treated as unset. No infrastructure-state lookup is performed.
SSH uses `accept-new` on first use; confirm the intended host fingerprint
separately before capture.

The SSH account needs root or equivalent permissions to read all Hermes state,
create the lock and private staging beneath `/opt/hermes`, and access Docker
without an interactive privilege prompt. The wrapper does not invoke `sudo`.
`HERMES_BACKUP_DIR` overrides the local destination; its default remains
`~/backup/hermer`.

The result is `hermes-recovery-<UTC timestamp>-<process id>.tar.gz`, mode `0600`.
Only a completed and verified transfer receives that final name. Existing
backups are retained; there is no schedule, retention policy or automatic upload.
An existing full archive can be sent separately using the explicitly authorized
[Mail.ru crypt upload/readback Task](cloud-backup.md); capture never invokes it.
Legacy `hermes-data-*.tar.gz` files remain data-only archives but do not satisfy
the recovery-bundle verifier or `restore-state` contract. Preserve them; manually
inspect/migrate them separately rather than bypassing the current verifier.
See [independent storage and recovery kit](https://github.com/aprudkin/hermes-ai-platform/blob/main/docs/personal-backup.md#independent-storage-and-recovery-kit)
for an owner-computer/external-volume workflow. A copy on the source server is
not independent. Neither encrypted storage nor its recovery keys are provisioned.

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

## Separately admitted cold capture (migration preparation)

The generated program also supports `capture-cold ROOT hermes`, for a clean
stopped container with Docker restart disabled. It never stops, pauses, unpauses
or starts anything, and leaves the source stopped on every error. Ordinary task
aliases do **not** select this mode; their admission and cleanup are unchanged.
The cold path retains full payloads/runtime provenance/verifier checks and adds
verified cold snapshot metadata. A Docker stop is not an input drain or all-host
fence. See [executed primitive tests and remaining blockers](migration-primitives.md)
before using it; no production cold capture or safe chat-confirmation path has
been demonstrated. Existing installed capture programs are not updated by editing
this repository, and a normal backup cannot be relabeled as the final freeze.

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
Compose/gateway selection and any retained Telegram rollback files under
`app/`. Runtime sockets are not useful recovery state. The target runtime must recreate its transient
process state; a filesystem backup does not preserve running processes.

The helper refuses unsupported runtime boundaries rather than quietly omitting
an extra mounted volume or writable-image-layer customization. Outside the data
mount, only transient `/run`, `/tmp`, `/var/tmp` content and the changed parent
`/var` directory metadata are exempt from that refusal. Custom programs or
configuration elsewhere must not silently disappear from recovery.
The bundle does not preserve unrelated host files, Ubuntu packages, host
firewall/SSH policy, controller private keys, host infrastructure records,
provider accounts, Telegram/BotFather settings, DNS or external service data.
Keep access to those services and host infrastructure records separately. It is
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

In Bash, select the actual trusted archive first:

```bash
read -r -p 'Trusted backup archive path: ' HERMES_BACKUP_FILE && export HERMES_BACKUP_FILE
```

Then run the local-only verification task:

```bash
task verify:hermes
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

## Moving to a different hosting provider

The same restoration procedure applies on a compatible provider's Linux/Docker
host; matching image architecture, storage format and data ownership matters
more than the provider name. A step-by-step route, including cloud retrieval
without the source, is in the online
[provider-migration guide](https://github.com/aprudkin/hermes-ai-platform/blob/main/docs/migration.md).
The restoration commands below remain self-contained when this guide is used
as the bundle's `RESTORE.md` without that checkout.

Plan the host rebuild separately. `/etc/hermes-backup`,
`/usr/local/lib/hermes-backup`, `/var/lib/hermes-backup`, `/var/log/hermes-backup`
and its host systemd units are outside `app/data` and **not in this bundle**.
Restore their cloud/decryption configuration from independent protected recovery
material and deliberately reinstall/test the host backup workflow. Likewise,
prepare SSH accounts/authorized keys, firewall, Docker and provider controls
separately. A client key saved inside the data volume is not server-side SSH
authorization; host-access aliases and pinned host keys may still name the old
server. Verify the new host independently instead of disabling host-key checks.

Do not enable new production polling, agent jobs or persistent backup timers
during rehearsal. Stop/fence old owners before accepted cutover, retain rollback
material and review cancelled jobs. Moving the files does not itself establish
new-host authentication, external connectivity or a functioning daily backup.

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
policy before restoring them. Do not overwrite restored state with the
repository reference configuration or a new setup process. Recovery preserves
the snapshot rather than generic defaults. This repository does not install
Docker or provision the target; these steps do not authorize host access.

## Restore files without starting Hermes

Transfer the trusted archive over an authorized encrypted connection. Use a root
Bash shell on the **new target**, not the source. Confirm Docker has no existing
Hermes container; the file-only helper does not inspect or manage Docker.
Select the transferred file using the `HERMES_BACKUP_FILE` prompt above.
With a trusted checkout available, the current step is:

```bash
python3 scripts/hermes_backup_bundle.py restore-state "$HERMES_BACKUP_FILE" /opt/hermes
```

The helper accepts both personal and full bundles and refuses any existing
destination, including an empty directory or symlink. It verifies a private
copy, writes the original bundle payloads to `/opt/hermes/.recovery`, extracts
`app/` and `data/` with GNU tar, then compares file contents and basic stat
metadata (type, size, mode, owner/group, modification time) with the archive.
Any extraction/comparison diagnostic, even with exit zero, fails closed without
printing secret-bearing filenames. GNU tar's comparison does **not** read back
ACL/xattr values. Where those attributes matter, verify them using native target
filesystem/security tools before runtime acceptance; no complete attribute
readback is claimed. It never loads an image, runs hooks, starts Hermes or enables jobs.
Paths beneath a symlink in the archive are rejected by verification. Use only
trusted archives and a private target parent; this is not a hostile-archive
sandbox. Do not edit files concurrently with verification/restoration.

An interrupted/failed restore retains a **partial** target for inspection;
choose a fresh destination for retry rather than overwriting it. Success means
files restored and compared, not a healthy bot. `task restore:hermes:state` is
an equivalent entry point with explicit `HERMES_BACKUP_FILE` and absolute
`HERMES_RESTORE_DIR` environment variables. A rehearsal may use a new directory
other than `/opt/hermes`; the saved production Compose still points to the
original source root and must not be started against a rehearsal directory.

Reserve space in `TMPDIR` for a compressed private copy plus the uncompressed
verification payloads, and at the destination for all payloads **plus extracted
state**. Image import later also consumes Docker storage. Keep temporary and
restored secret-bearing files on private encrypted storage; no encryption is
performed by this helper.

### Recover without this checkout or the old server

New bundles embed the same `restore-state` helper as `verify.py`. On a clean
compatible host with the trusted archive selected, extract just that helper
into a private temporary directory:

```bash
umask 077 && RECOVERY_HELPER=$(mktemp -d) && tar -xOzf "$HERMES_BACKUP_FILE" verify.py > "$RECOVERY_HELPER/verify.py"
```

Then use it without contacting the old server, GitHub or a package registry:

```bash
python3 "$RECOVERY_HELPER/verify.py" restore-state "$HERMES_BACKUP_FILE" /opt/hermes
```

Trust in the archive is essential: executing an embedded verifier does not
authenticate its author. Older bundles may embed a verifier without this command;
use the trusted current repository helper for those. The bundle schema has not
changed; current tooling continues to verify/restore previous supported bundles.

Preserve the archived ownership rather than recursively changing all files to
one UID: the app directory and runtime data have different ownership boundaries.
The explicit xattr include pattern restores namespaces beyond `user.*`, which
GNU tar otherwise omits on extraction; see its
[namespace compatibility explanation](https://lists.nongnu.org/archive/html/bug-tar/2023-05/msg00010.html).
Treat attribute-restoration errors as a failed restore, not harmless warnings.
Review image architecture and the protected recovery Compose definition before
loading or starting anything. Do not print credential-bearing metadata into
shared terminals or logs.

For a **full** bundle, after accepting the restored files, load the archived
image. This imports an image into Docker but does not run a container:

```bash
cd /opt/hermes/.recovery && docker image load --input image.tar
```

Then obtain its exact ID and recovery tag from the protected metadata and
confirm the loaded identity before tagging (Bash, still in `.recovery`):

```bash
IMAGE_ID=$(python3 -c 'import json; print(json.load(open("image-inspect.json"))["Id"])') && RECOVERY_IMAGE=$(python3 -c 'import json; print(json.load(open("compose.restore.json"))["services"]["hermes"]["image"])') && test "$(docker image inspect --format '{{.Id}}' "$IMAGE_ID")" = "$IMAGE_ID" && docker image tag "$IMAGE_ID" "$RECOVERY_IMAGE"
```

Only after reviewing the saved definition, install it privately and validate
its syntax; do not start it yet:

```bash
install -m 0600 compose.restore.json /opt/hermes/app/compose.restore.json && docker compose --file /opt/hermes/app/compose.restore.json config --quiet
```

Configuration validation does not start a container and is not runtime proof.
Keep using this standalone restore file until the deployment configuration has
been deliberately reconciled; switching back to the old template may change
environment interpolation, the selected profile or the image.

## Isolated acceptance before cutover

Keep the production Compose definition stopped: it retains the source's host
network, gateway command, credentials and restart policy. `compose config` is
syntax validation, **not isolation**. Never use `compose up` as a rehearsal.

First inspect files offline: Chebi's nonempty `SOUL.md`, memory and session
availability, application data/manifests, credential file modes, and database
integrity with each application's native offline checker. Work on a disposable
copy for tools that might modify databases. Do not print private rows or tokens.
Inventory cron/scheduled work in all restored profiles and applications as well
as any separately managed host timers. Reconcile it with the owner's current
approved list; older archives may predate cancellation. **Cancelled reports and
mail monitoring stay disabled.** Do not assume a template/archive authorizes them.

If a runtime rehearsal is needed, use a disposable state copy, no production
credentials, jobs disabled, a separate container name, `restart: "no"`, no
published ports, and Docker `network_mode: "none"` (not host networking).
Override the image entrypoint/command with the specific offline check, so its
normal gateway/scheduler startup never runs. These overrides are a separate
reviewed rehearsal configuration, not the saved production Compose. Do not
mount the live Docker socket or host paths beyond the disposable data copy.
Offline checks cannot establish inference or Telegram behavior. If suitable
application-specific checks or the job inventory are unknown, record that
blocker rather than starting the gateway to discover them.

## Switch ownership and verify behavior

**Do not start the restored bot while the source still owns Telegram polling or
scheduled work.** Starting the gateway can immediately run due jobs or send
messages using restored credentials. A disaster-recovery rehearsal must stay
isolated from those external services; merely using a second host is not
isolation.

For a planned move, stop the old Hermes instance immediately before the
separately authorized cutover and ensure nothing restarts it: disable its
container restart policy and any systemd/cron/automation that recreates it.
Record those settings for a deliberate rollback; retain the old files/server. For disaster
recovery, establish that the old instance cannot still run. For minimal data
loss during a planned move, arrange a quiet maintenance window around the final
backup and cutover: the backup resumes the source, so writes after its snapshot
are not present on the destination.

Only after ownership and side effects are authorized, start the restored
service:

```bash
docker compose --file /opt/hermes/app/compose.restore.json up --detach --pull never && docker inspect --format '{{.State.Status}} {{.State.Health.Status}}' hermes
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
