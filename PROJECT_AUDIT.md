# Hermes AI Platform — Verified Audit

Audit date: 2026-08-16
Scope: local repository, original downloaded ZIP, and read-only Hetzner project inventory.

## Recovery update — 2026-08-16

The audit findings below describe the downloaded baseline before recovery.
Minimal now has executable Terraform, Ansible, Compose, profile definitions, a
fail-closed installer/validator, behavioral tests, and CI. Current local checks
verified Terraform format/schema, ShellCheck, nine installer/validator behaviors,
ephemeral Ansible syntax/lint, the Compose Specification schema, repository
secret patterns, and existence of the pinned official Docker Hub tag.

Minimal is implemented but not yet deployed or end-to-end verified. No
Terraform plan/apply, cloud mutation, host connection, container start, model
request, Ansible idempotency run, GitHub publication, or CI run occurred during
the recovery work. Docker was unavailable locally, so native
`docker compose config`, image pull, and container health remain untested until
CI or an authorized host run. README and installation docs preserve these
boundaries.

## Baseline verdict before recovery

The supplied project is not ready to deploy. It is mostly a documentation shell whose README and installation guide describe functionality that is not implemented.

The upstream architectural idea is not entirely fabricated: official Hermes Agent documentation supports profiles and recommends running multiple profiles in one container. The false part was the claim that this repository already implemented and validated the platform.

## Baseline evidence

- Original ZIP: 3,551 bytes and 14 regular files.
- Current Git repository: branch `main`, zero tracked files, zero commits, and zero remotes.
- Terraform: zero `.tf` files.
- Ansible: zero playbooks and zero roles.
- Prompt stages: zero implementation files under `prompts/`; only a README claiming stages 00–31.
- Tests: zero test/spec files.
- `installer/install.sh`: prints phase names and performs no installation.
- `scripts/validate.sh`: prints component names and performs no checks.
- GitHub Actions: calls the echo-only validation script, so it can report success without validating the project.
- Docker Compose: uses the unverified image name `hermes-agent` and lacks the documented Hermes data/configuration contract, startup command, and meaningful health check.
- Saved conversation: `CHATGPT_CONVERSATION.md` contains five recovered turn headings, while 47 user/assistant turn pairs were available in the linked thread. It is not a complete transcript.
- Hetzner project `Hermes`: zero servers at audit time. The existing SSH key matched `~/.ssh/luk.pub`; no duplicate was created.

## Baseline claim-to-reality matrix

| Claimed capability | Verified reality | Status |
|---|---|---|
| Ready-to-deploy installer | Echo-only shell script | Blocker |
| Terraform provisioning | README only, no `.tf` files | Blocker |
| Ansible configuration | README only, no playbook or roles | Blocker |
| Hermes runtime | Unverified placeholder image and incomplete Compose | Blocker |
| Prompts 00–31 | No prompt implementation files | Blocker |
| Roles/profiles/skills/memory/policies | No implementation directories or runtime configuration | Blocker |
| Validation and health report | Echo-only script; no tests | Blocker |
| CI validation | Runs the echo-only script | Misleading |
| Complete project history | Five recovered turns only | Incomplete |
| GitHub-ready repository | No tracked files, commit, remote, or `.gitignore` | Incomplete |
| One runtime with profiles | Supported in principle by upstream documentation | Architectural basis only |

## Minimum recovery scope

Minimal must be built as a real vertical slice before later levels are attempted:

1. Repository hygiene and secret-safe configuration templates.
2. Reproducible Hetzner Terraform for a new VPS, plus a separate existing-host path.
3. Idempotent Ansible host setup and hardening.
4. Docker Compose based on the current official Hermes Agent image and configuration contract.
5. One Hermes runtime with verified profiles for Manager, DevOps, Coding, and Research where upstream mechanisms support them.
6. Persistent configuration/data, real health checks, failure-aware validation, tests, and non-misleading CI.
7. Documentation that describes only the behavior actually implemented and verified.

## Upstream references to verify during implementation

- Hermes Agent repository: <https://github.com/NousResearch/hermes-agent>
- Official installation guide: <https://hermes-agent.nousresearch.com/docs/getting-started/installation>
- Official Docker guide: <https://hermes-agent.nousresearch.com/docs/user-guide/docker>

These links are starting points, not frozen specifications. Re-check current upstream behavior before implementation.

## Safety boundary

This audit was read-only. It did not create a server, run Terraform, configure a remote host, or deploy Hermes. Future cloud or remote mutations require separate explicit confirmation.
