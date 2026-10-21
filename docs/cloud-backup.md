# Explicit encrypted Mail.ru copy of an existing full bundle

`task backup:hermes:cloud` is separate from `task backup:hermes`. It uploads an
**already created full archive**, not a new server capture. The local backup
Task and its global `b:hermes` launcher remain unchanged. No global cloud launcher
is installed. This workflow does not access SSH, pause Hermes, restore data,
start jobs, delete old copies, create a schedule or provision an account/key.

## Prerequisites and authorization

Use the owner's trusted controller with Python 3, Go Task and rclone already
installed. The rclone flags/crypt behavior were developed against v1.75.2;
missing tools fail rather than being installed. Local tests use bounded fixtures
and cannot establish live Mail.ru availability or credential validity.

Before invocation, authorize the specific archive and the Mail.ru destination
and readback. `HERMES_CONFIRM_CLOUD_UPLOAD=1` is a deliberate invocation gate,
not evidence that the operator granted permission. An authorization to implement
or test this command is not authorization to run it against cloud storage.

The trusted archive and both configs must be absolute paths to regular,
non-symlink files owned by the invoking user, with no group/other permission
bits (normally `0600`). Keep their parent directories private. The archive name
must end in `.tar.gz` and contain only ASCII letters, digits, dots, underscores
or hyphens, starting with a letter or digit. A personal or legacy data-only
archive fails the full-bundle verifier before any cloud operation.

| Environment variable | Meaning / default |
| --- | --- |
| `HERMES_BACKUP_FILE` | Required absolute path to a trusted existing full archive |
| `HERMES_CONFIRM_CLOUD_UPLOAD` | Must equal `1`, after authorization |
| `HERMES_CLOUD_CONFIG` | Working rclone config; default `$HOME/.config/rclone/hermes-backup.conf` |
| `HERMES_CLOUD_RECOVERY_CONFIG` | Separately saved recovery config; default `$HOME/backup/hermes-recovery-kit/rclone.conf` |
| `TMPDIR` | Temporary space on private encrypted local storage; otherwise the OS default |

Configs are never created, printed or updated in place. The default rclone
configuration is not used. The dedicated configs must contain exactly these
two remotes, with matching values in both copies:

- `mailru-hermes`: `type=webdav`, `url=https://webdav.cloud.mail.ru/` (trailing
  slash optional), `vendor=other`, and nonempty `user` and obscured `pass`.
- `hermes-backup`: `type=crypt`,
  `remote=mailru-hermes:Hermes-Backups/crypt-v1`, `filename_encryption=standard`,
  `directory_name_encryption=true`, and nonempty `password` and `password2`.

Extra sections/options, different destinations or mismatched recovery keys are
rejected before upload. This is deliberately an adapter for the existing
approved setup, not a general-purpose remote selector. All inherited
`RCLONE_*` variables are removed from child environments, including remote,
logging, TLS and password-command overrides. Protect the controller, its PATH
and Python environment as part of the trusted execution boundary.

The config contains reversible rclone-obscured credentials and keys: **it is
secret, not an encrypted recovery kit**. Save an independent protected copy
in a password manager or on another secure device. Losing the computer with
the only crypt keys makes the cloud object unusable; a Mail.ru login alone
cannot decrypt it. This command tests the local recovery config, not whether
another independent copy of the keys exists. Never upload the recovery kit to
the archive destination.

## Run only after authorizing upload and readback

From the repository root, in **Bash**, this command asks for the actual archive
path and explicitly enables the cloud action for this invocation only:

```bash
read -r -p 'Authorized full archive path: ' HERMES_BACKUP_FILE && HERMES_BACKUP_FILE="$HERMES_BACKUP_FILE" HERMES_CONFIRM_CLOUD_UPLOAD=1 task backup:hermes:cloud
```

No need to run the local capture Task first when the selected archive already
exists. The helper always verifies its private snapshot again before sending
it, regardless of any earlier verification report.

## Sequence and evidence

1. Validate and privately snapshot the two configs; check the fixed crypt and
   HTTPS Mail.ru routing and that recovery settings match.
2. Privately copy the selected archive, verify it with the repository's trusted
   full-bundle verifier and compute its SHA-256. Later changes to the original
   file cannot change the already verified upload snapshot.
3. Use directory-mode `rclone copy` from a private directory containing **only
   the archive** through crypt to `hermes-backup:full/`, with
   `--immutable --size-only`. The object retains the original archive basename.
   Configs are outside the upload directory. Single-file `copy`/`copyto` can
   bypass immutable conflict checks, so they must not be used for this upload.
   Never use `sync`, `delete` or `purge`. The original archive name selects the
   object; there is no automatic latest-file selection or retention policy.
4. Download/decrypt that object into a fresh private file using a snapshot of
   the **saved recovery config**, not the working config.
5. Compare size and SHA-256, then run the trusted full verifier on the download.
   Only after all steps succeed, emit a JSON receipt on stdout with the remote
   path, size, hash, `recovery_config_used=true` and
   `bundle_integrity_verified=true`. `state_restored` and
   `restored_runtime_verified` remain false.

`--size-only` avoids timestamp reconciliation on existing objects. An existing
same-size object may be skipped during upload, but is never accepted without
readback and SHA-256 verification. A same-name different-size object fails the
immutable upload; a same-size content collision fails readback verification.
Neither is overwritten or deleted automatically. Preserve the existing object,
investigate, and deliberately choose a distinct local archive filename if a
new object is needed. Do not run concurrent writers for the same destination;
WebDAV immutability checks are not a distributed transaction or storage lock.

Source and downloaded archives are plaintext on the controller. Only the crypt
layer encrypts the remote object and its name. Reserve temporary disk space for
**two compressed archive copies plus the verifier's uncompressed payloads**.
Use encrypted storage for that space as well as for the original and configs;
the command does not configure or verify disk encryption.

Each verifier/transfer subprocess has a 90-minute limit; rclone has a 30-second
connection and five-minute idle timeout with bounded retries. This is not a
90-minute limit on the whole workflow. Progress shows phase names only. Child
output is suppressed because it may contain credentials/private paths; a
failed phase returns nonzero and never emits a success receipt. Investigate
credentials, connectivity, quota or the archive privately, without dumping the
config or enabling raw HTTP logs in shared output.

Temporary private snapshots/downloads are removed on normal completion and
handled failure/interruption. A forced kill or machine failure can leave a
private temporary directory; inspect it privately before cleanup. Remote
objects (including an uploaded object whose readback failed) are never cleaned
up automatically. A failed/interrupted run does not prove that no upload
occurred; a retry can verify a previously uploaded identical object.

This establishes a verified encrypted storage round trip, **not restored
personal data or a working recovered Hermes runtime**. Follow the separate
[restore and acceptance guide](backup-restore.md) for that work. Keep previous
accepted copies and the old installation until recovery is accepted.
