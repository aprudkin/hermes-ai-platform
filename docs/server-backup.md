# Daily host backup — separate from controller Tasks

This host-local workflow maintains backups of Chebi on `hermes-minimal`. It
runs outside the source container and is separate from controller Tasks and
Hermes jobs. It does not change the local full-backup default, global launchers,
the Hermes image, identity, agent jobs or Telegram ownership. **Installation,
production/cloud execution, timer activation and Git publication require their
own authorization**. This guide describes the supported behavior, not evidence
that a particular host has it installed, active or live-verified.

## Agreed policy

- Full capture on the host, outside the paused container, using the existing
  trusted bundle generator/verifier. Direct server → Mail.ru crypt upload;
  metadata-only readback. No reverse archive download, post-download verifier,
  restore check, or completion notifications. No new Hermes reminder/poller.
- Daily **08:00 Europe/Moscow**, explicit in the timer. `Persistent=true`
  requests one catch-up when the timer is activated after a missed calendar
  window, including after reboot. This can pause Hermes outside 08:00. It does
  not replay one backup per missed day, retry a failed service immediately, or
  restart Hermes. A running service is not started a second time by the timer.
- Owner-visible destination: `Backup/Hermes/YY-M-D/`, based on capture-start
  date in Europe/Moscow, with unpadded month/day (for example `26-11-1`).
  If that exact folder already exists, use `YY-M-D-2/`, then `-3/`, etc.,
  skipping occupied folders even when empty or left by an interrupted upload.
  Allocation and upload run under the existing workflow lock. A new `dated-v2`
  receipt binds the actual `cloud_directory`; existing unsuffixed `dated-v1`
  receipts remain readable. Listings never establish deletion ownership.
  The daily crypt root is `mailru-hermes:Backup/Hermes`, with directory-name
  encryption disabled, but **content and archive filenames remain encrypted**
  with the existing keys. Names retain UTC capture time and a random UUID.
- Keep **all copies from the current Moscow calendar date and the two previous
  dates**, using the capture-start date, not upload time/mtime, filename ordering,
  the latest three archives or a rolling 72-hour window. Only earlier dates expire.
  Rotation runs only after local integrity verification/SHA-256, confirmed
  target absence, immutable upload, recovery-config metadata size/name checks
  and confirmed running/unpaused source. Metadata is not a remote SHA-256 check.
  A backwards clock relative to receipts fails closed. Accurate host time is
  required; check synchronization before activation.
- Retention uses a private local ledger of successful receipts, not a cloud
  listing. It calls `deletefile` for one exact receipted basename at a time;
  never `sync`, `purge`, or recursive deletion. An attributable expired date
  directory is removed with nonrecursive `rmdir` only after an empty listing;
  unknown objects prevent directory removal. A missing ledger means unknown
  cloud copies are retained, not rediscovered and deleted. No other writer may
  reuse this namespace or edit its receipts/configs while the service runs.
- Preserve the current verified cloud copy even through prolonged subsequent
  failures. Manual `full/` copies, recovery kits and all objects outside this
  workflow's successful receipt ledger are outside cloud cleanup.
- On the server retain the latest verified original. No readback archive is
  created. Remove previous receipted originals after the new upload metadata
  checks and cloud rotation succeed,
  verifying their recorded size/hash first. Failed/unknown partials and scratch
  files are not automatically erased. Empty run directories and receipts stay
  as audit evidence; they are small, but not subject to the archive-age policy.
- Private safe server journals: **30 days**, **100 MiB total** for recognized
  workflow journals; up to **1 MiB per run**, retaining newest events if a run
  reaches its cap. Cleanup occurs at the next invocation, so age expiry is not
  a separate continuously running deletion service. Unknown/operator log files
  are not touched and do not count toward the workflow quota.

## Host installation boundaries

| Path | Purpose / access |
| --- | --- |
| `/usr/local/lib/hermes-backup/` | Root-owned `0700` package, capture generator output, trusted verifier and approved rclone binary |
| `/etc/hermes-backup/upload.conf` | Dedicated working rclone config, root-only `0600` |
| `/etc/hermes-backup/recovery.conf` | Separately staged copy from the owner's saved recovery config, root-only `0600` |
| `/etc/hermes-backup/daily-upload.conf`, `daily-recovery.conf` | Derived dated-layout configs, same transport/keys, root-only `0600`; original configs remain unchanged for legacy access |
| `/var/lib/hermes-backup/runs/` | Private plaintext original and local-verifier scratch; outside captured `app/data` |
| `/var/lib/hermes-backup/receipts/` | Root-only upload ledger; dated receipts explicitly record metadata checks and `cloud_roundtrip_verified=false`, never restored success |
| `/var/lib/hermes-backup/workflow.lock` | Stable flock inode, never unlinked by the workflow |
| `/var/log/hermes-backup/` | Private JSONL stage/progress/result logs |
| `/etc/systemd/system/hermes-backup.service` and `.timer` | Dedicated host schedule, not a job inside Hermes |

Both configs must match the existing dedicated configuration schema; arbitrary
remotes, password commands, TLS overrides and extra config options are refused.
Child environments are allowlisted, not inherited from `RCLONE_*`, `PYTHONPATH`
or credential variables. Config values and raw subprocess diagnostics are
never printed. The journal allows fixed capture-stage strings and bounded
numeric rclone counters only; private filenames, HTTP diagnostics and message
text from rclone are discarded in memory, not written to temporary raw logs.
The journal records phase starts/exits, return codes, durations, capture byte
counts, transfer counters/speed, rotation and terminal status. Transfer byte
counters may include retries; they are not proof of final archive size.

These configs contain reversibly obscured secrets, **not encrypted secrets at
rest**. Root compromise exposes cloud access and decryption keys. Preserve the
recovery kit on the owner's independent controller and another protected device
or password manager. Verify that independent access rather than assuming it.
Two files on this server do not make the recovery keys independent. Local
original/readback archives are also plaintext protected by permissions, unlike
the crypt-encrypted cloud objects. The host backup installer does not configure
disk encryption, accounts, quotas or a secret-management service.

The host workflow supports only the approved **Linux amd64 rclone v1.75.2**
binary, SHA-256
`ed7ab1f17876bb006c3df3949a3044959671afd9112362dacaa5dd1647735bc1`.
No download or package installation occurs implicitly. Obtain/stage that
upstream binary through a separately authorized, checksum-verified process.
Single-file rclone `copy`/`copyto` is **not used for uploads**: directory-mode
`copy --immutable --size-only` has the required collision behavior. A same-size
skip must not be used to establish a new successful copy: the exact target
must first be absent. The workflow assumes a single namespace writer; this is
not a distributed lock. Remote metadata does not prove remote content integrity.

## Failure and resource behavior

The whole workflow has an exclusive local lock; the existing capture helper
also holds its source capture lock. Neither lock prevents unrelated deployment
or administration: avoid concurrent state edits. Capture owns only its own
pause; it refuses an already paused source and confirms unpause before
hashing/compression/upload. It does not restore data, start a container, probe
Telegram/inference, or revive cancelled jobs.

Space admission reuses the capture estimator and reserves a conservative
`3 × estimated raw payload + 1 GiB` of currently free space for capture,
compressed original and local verification. Runtime and workflow state must
be on the same filesystem in this version. It is an estimate, not a reservation;
concurrent growth or unusual compression overhead can still exhaust storage.
I/O failure is non-success. Prior verified copies are not removed to make room
for an unverified new one. Failed leftovers require deliberate inspection and
cleanup; repeated failures can eventually block new captures for lack of space.

Capture has a two-hour outer deadline; other subprocess phases have 90 minutes.
The systemd service has a four-hour ceiling, no automatic service restart, and
`KillMode=mixed` with a 240-second stop allowance. On interruption the parent
terminates the capture first and allows 180 seconds for its owned-pause cleanup
before a last-resort process-group kill. Process/host failure can still leave
Hermes paused. After an abnormal termination inspect actual running/paused
state before retrying; no automatic unpause of an unknown owner's pause.

An interrupted upload may exist without a receipt; it is retained and is not
reused or automatically deleted. Each later scheduled attempt has a new unique
run identity. Rotation can partially succeed before a later deletion fails:
completed deletions are marked individually in durable receipts, the new
metadata-checked copy remains, the run returns failure and keeps previous local
originals. `encrypted_upload_metadata_checked` followed by failure means upload
metadata passed but later housekeeping/source checks did not. Legacy
`cloud_roundtrip_verified` events describe only the old downloaded path. Only terminal `success`
means the entire workflow completed. Neither status means restored data or a
functionally verified restored runtime.

If the owner externally removes old cloud copies, reconcile fresh metadata
before cleanup. Preserve the historical receipts, marking absent legacy copies
`cloud_removed_externally=true` without calling that workflow deletion. They
must not authorize new deletions or be reported as current cloud protection.
Do not recreate the deleted `Hermes-Backups/crypt-v1` namespace. Keep the original
configs/keys privately for recovery; a dated upload does not relocate old copies.

Receipt updates use unique private staging names before an atomic rename. A
crash may leave a staging file behind, including the older fixed `.json.new`
format. Recognized private regular staging files are retained for inspection
but ignored when loading successful receipts; they never authorize rotation.
Symlinks, public staging files, oversized entries and unknown names still fail
closed. A later run can therefore proceed without deleting or overwriting the
interrupted evidence. Do not manually promote a staging file to a receipt.

## Install and activate host backups — separate authorizations

Use only the dedicated host-backup installer described below. It installs the
backup package and units, not Docker or Hermes. The timer runs the installed
workflow, not a one-use maintenance command or an agent cron job.

1. Obtain immediate authorization for the exact target, protected transfer,
   permanent rclone/config installation, and read-only host preflight. Confirm
   the intended SSH alias/fingerprint and permissions, Ubuntu/systemd, amd64,
   Docker access, source state, time synchronization, disk capacity, private
   path ancestry and absence of another backup schedule. Verify the owner's
   working config matches the independent recovery kit without printing values.
2. Stage this reviewed checkout, the two separately sourced configs and the
   approved binary into a new private root-owned directory outside `app/data`.
   The staged checkout and its ancestry must satisfy the installer's root-owned
   trusted-path checks. Config/binary inputs must be root-owned regular files
   without symlinks or group/other permissions. Do not transfer secret values
   through command strings, captured stdin or logs.
3. The prepared host-local entry point is
   `scripts/install_server_backup.py`. Its required arguments are
   `--confirm-external-mutation`, `--upload-config`, `--recovery-config`, and
   `--rclone-binary`, each path absolute and referring to the protected staged
   file. It performs an **initial install only**: refuses existing target paths
   or loaded units, validates copies, installs the package and units, runs native
   `systemd-analyze verify` and `systemctl daemon-reload`. It **does not start or
   enable** the service/timer, download anything, or access cloud/Docker.
   Failed installation may leave partial files; inspect rather than overwriting
   them or automatically rolling back. Staged inputs are retained, not silently
   removed. Package/config updates are deliberate maintenance, not supported by
   rerunning this initial installer.
4. Check installed code/binary hashes, credential modes and unit contents without
   printing configs. Use native `systemd-analyze calendar` to confirm the next
   `08:00 Europe/Moscow` event. Installation is not runtime verification.
5. Obtain authorization for one service start: full capture/pause, upload,
   metadata checks and the agreed narrow retention. Run the installed service, observe
   its terminal exit status and safe journal/receipt, and independently inspect
   source running/unpaused state. Fixtures and static review cannot replace this.
6. Only after accepting that live result, obtain authorization immediately before
   enabling/starting **the timer**. Confirm enabled/active state, next trigger,
   selected timezone and persistent catch-up behavior. Activation may cause a
   catch-up. Do not claim daily autonomous operation from an installed unit alone;
   observe the first actual timer-triggered result separately.

The approved stop action when subsequently requested is disabling/stopping
`hermes-backup.timer`, then checking whether the service is still running.
Stopping the timer does not cancel a current capture. Normally allow the active
service to finish; interrupt it only deliberately with the owned-unpause limits
above and verify source state afterward. Keep all code, credentials, receipts
and archives for inspection; disabling is not uninstalling or deleting data.

## Local evidence and operational acceptance

`bash tests/hermes_server_backup_test.sh` uses temporary fixture paths, fake
Docker/rclone, real archive generation/verifiers and subprocess termination.
It never contacts the host or Mail.ru. The existing cloud suite additionally
covers real local rclone crypt immutability when rclone is available. Linux
systemd unit parsing, installed root permissions, host pause cleanup, actual
cloud deletion/metadata checks, catch-up and timer execution remain deployment-stage
checks. Do not conflate local green tests, a successful installer, a successful
manual live backup, and an observed scheduled backup.

Check freshness and failures from a process outside the Hermes container: a
paused or failed agent cannot reliably report its own backup failure. This
repository does not establish an independent alerting service. Record the
actual runner/access and a verified alert or freshness check before claiming
monitoring is active. After recovery, separately review the host backup timer
as well as agent schedules; never revive cancelled reports or mail monitoring.
