# One agent, persistent state and a recovery toolbox

The maintained installation is one persistent Hermes Agent: Чеби (Chebi), in
the `manager` profile, running in one official Hermes container. This repository
holds approved maintenance code, recovery instructions, a protected identity
seed and a Compose recovery/reference configuration. It is not a server
provisioner, a bootstrap platform or a multi-agent service fleet.

## Runtime and ownership

- The normal host layout is `/opt/hermes/data` mounted at `/opt/data` in the
  container. `profiles/manager` beneath that data root contains Chebi's live
  profile. Inspect the actual mount before assuming this layout.
- Identity, configuration/authentication, memory/history, SQLite databases,
  skills, plugins, custom scripts/applications, dependencies and job state are
  runtime-owned persistent data. Container replacement must not erase them.
  The repository adds no separate database or Redis service; upstream Hermes
  keeps its own data under the persistent home.
- `/opt/hermes/app` retains the deployed Compose definition, gateway selection
  and any existing rollback configuration. Those files are included in backups,
  but their presence does not mean this repository actively reconciles them.
- `profiles/manager/SOUL.md` in Git is the approved identity seed, not authority
  to overwrite a personalized live identity. Personal databases, memories, keys,
  authentication and full archives never belong in Git. See
  [state ownership](state-first.md).

`docker/docker-compose.yml` pins an official image and describes one `hermes`
service with host networking, bounded Docker logs and a loopback-only API/health
endpoint. It is a reference, not proof of the actual host configuration. Its
`HERMES_GATEWAY_PROFILE` fallback is `manager`, matching Chebi's current
selection. An explicit override is available, but only inspection of the
effective runtime configuration establishes which profile is actually running.
Credentials remain in protected runtime files, never filled into tracked Compose files.

No public port, webhook, DNS or TLS service is added by this toolbox. With host
networking, the lack of a Compose `ports` entry is not a firewall: preserve
loopback binding and inspect the host's actual exposure separately.

## Maintenance and recovery boundaries

| Component | Responsibility | Does not do |
| --- | --- | --- |
| Local full/personal capture | SSH to the existing alias/explicit host, pause/snapshot/unpause, transfer and verify a private archive | Provision hosts, restore, upload or delete old copies |
| Bundle verifier and `restore-state` | Offline integrity checks; restore and compare files into a new clean Linux destination | Install Docker, start a gateway, enable jobs or prove integrations |
| Explicit cloud copy | Upload an existing full bundle through approved crypt, recovery-config readback and verification | Encrypt local files, capture new state, schedule or rotate copies |
| Daily host systemd backup | Capture outside the container, crypt upload/readback, narrow successful-receipt retention | Run as a Hermes job, bootstrap the agent, restore it or test its behavior |
| Image-update preparation | Verified full backup, release/review gate, local image-pin change and strict validation | Commit, push or apply the pin to the host |
| Explicit image apply | Fresh full off-server backup, reviewed source/digest, image-only deployed config change, same-service recreation and runtime checks | Bootstrap, Git publication, automatic retry/rollback, or claim functional acceptance from health |

Full bundles retain the exact runtime image and dependencies; personal bundles
exclude the image and recognized regeneration paths. Both contain secrets and
remain plaintext locally. Only the separately configured crypt layer encrypts
remote objects. Keys and at least one usable copy must remain independent of
the source server. See [personal backup](personal-backup.md),
[full recovery](backup-restore.md), [cloud security](cloud-backup.md) and
[host scheduling](server-backup.md).

Recovery targets a clean compatible Linux host with Docker already installed:
restore files → offline/isolated checks → authorized single-owner cutover →
functional verification. Never activate two production bots or schedulers, and
never revive cancelled jobs from an older snapshot. Archive creation, verified
integrity, restored files and a tested restored runtime are separate outcomes.
Keep the source and recovery evidence until the owner accepts recovery.
