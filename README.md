# Hermes AI Platform — Minimal

This repository implements a small, reproducible deployment of one official
Hermes Agent container on Ubuntu 24.04. It has been locally validated, but it
has not yet been applied to Hetzner or verified on a real host. It must not be
described as deployed until the remote runtime checks pass.

## What Minimal implements

- Hetzner Terraform for one VPS in selected Finland location `hel1`;
- explicit server-type selection with live plan-time checks for Hetzner's
  cost-optimized category, location availability, recommendation, and deprecation;
- reuse and fail-closed comparison of an existing Hetzner SSH public key;
- an ingress firewall allowing SSH and ICMP only from configured CIDRs;
- a separate existing-host path that creates no cloud resources;
- Ubuntu hardening, Docker installation, and deployment through Ansible;
- one pinned official `nousresearch/hermes-agent:v2026.8.16` container;
- persistent Hermes state at `/opt/hermes/data`, with no public service port;
- a real loopback gateway health check;
- explicit provider/model configuration and a post-deploy inference probe;
- Manager, DevOps, Coding, and Research as supported Hermes profiles inside
  that one container, each with its own SOUL, sessions, skills, and memory;
- fail-closed installer modes, behavioral tests, static validation, and CI.

Postgres, Redis, DNS, a dashboard, public API exposure, a private Hetzner
network, monitoring, backups, and stages 05–31 are not part of Minimal.

## Safe entry points

Run the strict validation gate (all required native tools must be runnable):

```bash
./installer/install.sh validate
```

Use `./scripts/validate.sh --local` only for an opportunistic workstation pass.
It reports unavailable native tools as `SKIP` and therefore is not readiness
proof.

Plan a new server without applying it (requires `HCLOUD_TOKEN` in the process
environment and the already registered key name):

```bash
./installer/install.sh plan new --location hel1 --server-type cx23 --hcloud-ssh-key-name Luk --ssh-public-key ~/.ssh/luk.pub --ssh-source-cidr 203.0.113.10/32
```

`hel1` is the selected location. The `cx23` choice reflects a read-only
2026-08-17 catalog snapshot and must be rechecked before any future apply.
Replace the documentation-only CIDR with the actual operator network. See
[QUICKSTART.md](QUICKSTART.md) for both modes and
[INSTALLATION_GUIDE.md](INSTALLATION_GUIDE.md) for the snapshot details and
mutation boundary.

## Upstream contracts verified through 2026-08-17

- [Hermes installation](https://hermes-agent.nousresearch.com/docs/getting-started/installation)
- [Hermes Docker layout and health endpoint](https://hermes-agent.nousresearch.com/docs/user-guide/docker)
- [Hermes profile commands](https://hermes-agent.nousresearch.com/docs/reference/profile-commands)
- [Hetzner Terraform provider](https://github.com/hetznercloud/terraform-provider-hcloud)
- [Hetzner server-type data source](https://registry.terraform.io/providers/hetznercloud/hcloud/latest/docs/data-sources/server_type)
- [Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/)

The image and provider are pinned in code. Review upstream release notes before
changing either pin.

## Verification status

Terraform format/schema, ShellCheck, the secret-pattern scan, and behavioral
tests passed locally on 2026-08-17. The installed `ansible-playbook` is currently
not runnable and Docker is not installed, so local mode explicitly skipped
Ansible syntax/profile checks and `docker compose config`; the strict local gate
therefore remains unmet. CI performs Compose config validation; only an
explicitly authorized deployment can prove host idempotency, runtime health,
and the model inference path (the probe makes one small billed provider request).

On 2026-08-17, a read-only catalog check and safe Terraform plan verified
`hel1` with explicit `cx23`, the existing `Luk` key, and a protected operator
IPv4 `/32`. The complete applyable plan contained two creates (firewall and
server), zero updates, and zero deletes. Terraform apply was not run and no
host was contacted.
