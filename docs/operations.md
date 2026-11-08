# Maintain Chebi's existing Hermes installation

This repository is a maintenance and recovery toolbox for one persistent agent:
Чеби (Chebi), using the `manager` profile. It does not provision servers, install
Docker or reconcile a new agent fleet. Start with the existing installation and
[state ownership](state-first.md), not a fresh deployment.

After authorized read-only access, check the selected profile, actual container
and image, loopback health, disk space and age/location of the last verified
independent backup. Do not print credentials, conversation logs or Docker
environment values into shared output. Routine inspection does not require a
restart. Health alone does not prove inference, Telegram behavior or recovery.

Keep personal changes in the host-backed data volume. Preserve Chebi's live
identity and cancelled-job decisions. Before state-affecting changes, capture
and verify an independent backup. For recovery or a server move follow
[backup and restore](backup-restore.md).

## Local checks and their limits

Run from the repository root:

| Purpose | Command | Boundary |
| --- | --- | --- |
| Strict validation | `./scripts/validate.sh --all` or `task validate` | Required local gate; inspect failures and skips, not only exit status. |
| Opportunistic local checks | `./scripts/validate.sh --local` | Missing native tools may be skipped; not readiness proof. |
| Static checks | `./scripts/validate.sh --static` | Repository structure, scripts, Compose and secret-pattern checks; no host access. |
| Behavioral tests | `bash tests/run.sh` | Local fixtures; not evidence of live cloud, Docker runtime, inference or Telegram behavior. |

The retained Compose file is a recovery/reference configuration, not an
installation interface. It uses host networking, a loopback health endpoint and
persistent `/opt/hermes/data` state. Inspect the effective configuration and
protected host inputs before any separately authorized runtime change. In
particular, its default gateway-profile fallback is not proof that `manager`
is selected. Do not print expanded secret-bearing Compose output.

## Telegram and external side effects

Keep one production gateway/long-polling owner for Chebi. Do not start a restored
copy while the source still owns Telegram or scheduled jobs. Preserve the
approved user/chat allowlists, privacy settings and mention/reply/command
handling; passive observation of unmentioned messages requires its own explicit
policy. No webhook or public API exposure is required by the recovery workflow.

For an authorized Telegram or runtime change, record separately:

1. A successful Bot API identity check without sensitive fields.
2. Empty webhook state for long polling and exactly one polling owner.
3. The actual healthy container and selected `manager` profile.
4. A substantive DM response for each configured user.
5. A substantive mention/reply response for each configured user in an approved
   group.
6. Denial of an unconfigured user in an approved group.
7. Denial of an approved user in an unconfigured group.
8. The approved behavior of ordinary unmentioned group messages: no unsolicited
   reply, and no context ingestion unless passive observation was authorized.
9. Loopback API health and a separate actual model-inference check.
10. Readback of profile selection, protected file modes, gateway status and
    retained rollback configuration without exposing their values.

Syntax validation and connected logs do not establish those behaviors. Host
access, protected credential installation, restart/recreation, Bot API probes,
visible messages, group-administrator changes and Git publication are separate
authorization boundaries. Passing local validation does not authorize them.

## Local backups

Run `task backup:hermes` (aliases `task b:hermes` and `task hermes:backup`) from
an independent controller to create and verify a **full recovery bundle**. It
retains state, dependencies and the exact current Docker image.
`task backup:hermes:full` is equivalent. Where the owner's existing global
catalog delegates to this checkout, `task -g backup:hermes` / `task -g b:hermes`
(or `t b:hermes`) invokes the same task; this repository does not install that
catalog.

The default destination is
`~/backup/hermer/hermes-recovery-<UTC timestamp>-<process id>.tar.gz`.
`HERMES_BACKUP_DIR` selects another local destination. Both backup and image
preparation default to the existing `hermes-minimal` SSH alias, using the
controller's SSH configuration. `HERMES_DEPLOY_HOST` overrides the alias/address;
`HERMES_DEPLOY_SSH_USER` and `HERMES_DEPLOY_SSH_PRIVATE_KEY` are optional overrides.
A supplied key must be an existing regular file; empty values are unset. The
alias remains the default even when only user/key is supplied. SSH uses
`accept-new` on first use; confirm the intended host fingerprint separately.

Run capture from the owner's computer or another independent controller,
**not inside the source container that will be paused**. Choose a destination
that is not a mount of the source server. See the [full recovery guide](backup-restore.md)
for permissions, free space, supported runtime boundaries and failure cleanup.

For a lightweight bundle without an image or recognized dependencies/caches,
use `task backup:hermes:personal` / `task b:hermes:personal`. The direct
`./scripts/hermes_backup.sh` CLI without flags selects personal mode; `--full`
selects full mode. See [personal backup](personal-backup.md) for exclusions and
separately required image/dependency reconstruction.

Both modes pause the source for a crash-consistent snapshot, resume it before
compression/transfer, and verify the received archive before publishing its
mode-`0600` final name. Failed unpause is an error. Do not edit source state
concurrently. Local capture does not restore, deploy, upload, configure a
schedule or delete existing backups. Archives contain credentials and are
**plaintext**, not encrypted by these scripts. Whole-host files, controller keys
and external accounts remain outside the bundle boundary.

## Cloud copy and daily host backup

- [Explicit cloud copy](cloud-backup.md): `task backup:hermes:cloud` uploads an
  existing full archive through the approved Mail.ru crypt configuration, then
  downloads/decrypts it using the saved recovery config and verifies it again.
  It does not capture new state, encrypt the local archive, schedule work or
  delete old objects.
- [Daily host backup](server-backup.md): a separate host systemd service/timer
  captures outside the container, uploads through crypt, verifies readback and
  applies narrowly receipted retention. Its installation, manual execution and
  timer activation are distinct authorized actions. Repository files or a green
  fixture test do not prove the schedule is installed or working.

Keep recovery keys available independently of the source host. Distinguish
**archive created**, **integrity verified**, **state restored** and **restored
runtime functionally tested** in every report. None implies the next.

## Image-update preparation only

`task update:hermes` (aliases `task hermes:update` and
`task update:hermes:prepare`) captures and verifies a **full**
backup before querying GitHub for the latest stable
`NousResearch/hermes-agent` release. It prepares a local image-pin change only:
**no automatic commit, push or deployment**. `CONFIRM_PUSH` and `CONFIRM_DEPLOY`
are rejected before remote access; leave them unset.

Preparation requires a clean checkout, the SSH connection described above,
GitHub CLI access to release metadata, and the native strict-validation tools.
It needs no server-provisioning credentials. If the local pin already equals
the release, preparation returns nonzero after the verified backup: **live
runtime deployment is unknown**, not a successful update.

Before changing the pin, supply `HERMES_UPGRADE_REVIEW_FILE` pointing to a
compatibility review JSON file outside the repository. Review the exact official
release notes and current image-related contracts, and run
`./scripts/validate.sh --all` first. Required JSON fields are:

- `tag`: the exact release tag.
- `release_notes_url`: `https://github.com/NousResearch/hermes-agent/releases/tag/<tag>`.
- `compatibility`: exactly `"compatible"`.
- `summary`: a nonempty compatibility explanation.
- `contracts`: a path-to-SHA-256 map with exactly `README.md`,
  `docs/operations.md` and `docker/docker-compose.yml`, hashing the exact reviewed
  local bytes.
- `checks`: command/result records including
  `{"command":"./scripts/validate.sh --all","result":"passed"}`.

Missing, stale, mismatched or incompatible review evidence fails the gate. The
review is an operator attestation, not automatic compatibility analysis. Changes
to any contract file invalidate its recorded hash.

Preparation updates only `docker/docker-compose.yml` and runs
`./scripts/validate.sh --all` against the **candidate** pin. Failure leaves the
diff for inspection; it does not reset Git, weaken validation or publish it.
Correct/review the diff and rerun the strict gate. Rerunning preparation is not
a deployment retry, and its clean-checkout requirement rejects a leftover diff.

## Apply a reviewed image

Use a terminal on an independent computer with this checkout, its declared
validation dependencies, SSH, Python 3 and Bash. It need not be this coding
session or the owner's usual computer. **Do not run the workflow inside the
agent container**: capture pauses that container. A host-local or source-mounted
backup directory is not off-server protection. The confirmation below attests
that the controller and backup destination are independent and the maintenance
window is authorized; the script cannot establish physical storage independence.

There is no chat self-update bridge. Such a bridge would need a separately
approved external executor; do not give the agent a Docker socket or host SSH
keys just to run this command.

The supported host layout is the existing single `hermes` Compose service,
`manager` profile, `/opt/hermes/app/docker-compose.yml`,
`/opt/hermes/app/gateway.env` and `/opt/hermes/data:/opt/data`.
Docker Compose must support `config --hash/--format json` and `up --wait`.
The SSH account needs Docker access and permission to read state and update
`/opt/hermes/app`; there is no automatic sudo. Exactly one replica with the
fixed `hermes` container name is required.
The running container must belong to that exact single Compose file. Its
effective config hash must match the running container's Compose label.
Alternate Compose stacks, interpolated/quoted image fields, drift, unsupported
mounts and unbacked image-layer customizations fail closed rather than being
silently reconstructed. Reconcile them explicitly before updating.

1. Review the release and prepare/validate the local pin as above. Preparation
   uses hashes of the **old** contract bytes; after preparation, refresh the
   review hashes against the **candidate** and rerun strict validation. Source
   publication is a separate workflow, not a deployment prerequisite or proof.
2. Run `task update:hermes:inspect`. This performs read-only SSH inspection,
   with no backup, pull or recreation. Save its JSON as the `source` object in
   the private review. It contains container/image IDs and hashes of deployed
   Compose, gateway inputs and live identity; no credentials or file contents.
3. In that same private JSON, retain all preparation-review fields and add:
   - `image`: the exact reviewed official image
     `nousresearch/hermes-agent:<tag>@sha256:<64 lowercase hex digits>`.
     Resolve and review its digest for the existing platform; do not use a
     floating tag alone. The tag must match the prepared local pin.
   - `source`: the complete object returned by inspection.
   - `maintenance_window`: a nonempty description of the authorized window.
   - `rollback_plan`: a nonempty, reviewed recovery plan, including the
     possibility of migrated databases and isolated full-bundle recovery.
   These are operator attestations, not automatic compatibility analysis or
   calendar enforcement. Store the file **outside the repository**, privately.
4. During that window, from the independent controller:

   ```sh
   HERMES_UPGRADE_REVIEW_FILE=/private/path/update-review.json \
   HERMES_CONFIRM_UPDATE=1 task update:hermes:apply
   ```

   The same SSH overrides and `HERMES_BACKUP_DIR` as capture apply. This command
   reruns strict validation and checks the reviewed source, then captures and
   verifies a new **full** bundle in a private `update-*` subdirectory of the
   backup destination. It rejects a source mismatch or a capture taking over
   30 minutes; old/preparation-time bundles cannot satisfy this gate.
5. Apply takes the existing capture lock, checks source fingerprints again,
   pulls the digest-pinned image, checks platform and rechecks the source.
   It saves the original Compose/gateway files and a durable intent under
   `/opt/hermes/app/update-*/` (private directory, mode-0600 files). It atomically
   changes **only the literal deployed image pin**, verifies the effective
   configuration differs only by image, and runs Compose for the same project
   and service with no build, dependencies or volume deletion. It does not copy
   repository reference configuration, identity, skills or jobs to the host.
6. A successful apply reports the observed image, manager profile, supported
   mount, unchanged identity/gateway inputs and Docker health. Its exit zero
   means **apply checks passed**, while `functional_acceptance: pending` remains
   explicit. Verify actual memory/history, custom applications/dependencies,
   approved jobs and retained cancellations, model inference and authorized
   Telegram behavior before accepting the update. The local Compose-owner
   check cannot rule out a polling copy on another host.

On failure or SSH loss, deployment may be partial or unknown. Do not blindly
rerun, restore the old Compose file, or start the old image. Inspect the actual
container/image/configuration and the private `intent.json`; a completed apply
also has `result.json`. An incomplete intent blocks subsequent apply attempts.
After manually reconciling the observed state and authorizing a new attempt,
retain the entire old attempt directory in a separately named private archive
(outside the `app/update-*` match), then inspect and review afresh. Do not fake a
success receipt or delete the evidence to bypass the gate. Even a recorded
successful apply is not functional acceptance. No failure causes an automatic
retry, rollback or data restore.

### Apply and acceptance are separate operator decisions

1. Inspect the candidate and validation output, update release-specific contracts
   where required, and repeat validation. Commit/push only when separately
   authorized. Neither a commit nor merge proves runtime deployment.
2. Before any authorized runtime update, retain a recent verified **full**
   off-server bundle and agree on a maintenance window and rollback plan. A
   preparation-time backup may already be stale.
3. Review the existing host's actual Compose definition, protected inputs, image,
   selected `manager` profile and persistent mount. This repository has no
   bootstrap command. Use the explicitly authorized apply workflow above only
   for its supported deployed layout; other host-specific recreation must be
   separately reviewed. Do not replace live configuration or identity with a
   generic reference file.
4. On failure, record the result and inspect actual image/service state and any
   partial changes before reauthorizing a retry. Local pin equality is not
   evidence that the host was updated.
5. Verify image/profile, health, Chebi's identity, memory/history, applications,
   approved jobs and separately authorized inference/Telegram behavior. Report
   local validation, published pin, deployed image and working behavior separately.

A failed update may already have migrated runtime databases. Do not blindly
start an older image over newer state. Preserve newer state, then use the
retained full bundle on a clean isolated target and follow
[recovery and single-owner cutover](backup-restore.md) if rollback requires old
state. Cancelled jobs stay cancelled. Keep the source and recovery evidence
until the owner accepts the result.
