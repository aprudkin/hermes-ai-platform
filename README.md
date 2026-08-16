# Hermes AI Platform — Minimal

This repository implements a small, reproducible deployment of one official
Hermes Agent container on Ubuntu 24.04. It has been locally validated, but it
has not yet been applied to Hetzner or verified on a real host. It must not be
described as deployed until the remote runtime checks pass.

## What Minimal implements

- Hetzner Terraform for one VPS in explicitly selected `fsn1` or `nbg1`;
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

Run all locally available checks:

```bash
./installer/install.sh validate
```

Plan a new server without applying it (requires `HCLOUD_TOKEN` in the process
environment and the already registered key name):

```bash
./installer/install.sh plan new --location fsn1 --hcloud-ssh-key-name Luk --ssh-public-key ~/.ssh/luk.pub --ssh-source-cidr 203.0.113.10/32
```

`fsn1` above is an example, not a selected city. Replace it with the explicit
choice of `fsn1` or `nbg1`, and replace the documentation-only CIDR with the
actual operator network. See [QUICKSTART.md](QUICKSTART.md) for both modes
and [INSTALLATION_GUIDE.md](INSTALLATION_GUIDE.md) for the mutation boundary.

## Upstream contracts verified on 2026-08-16

- [Hermes installation](https://hermes-agent.nousresearch.com/docs/getting-started/installation)
- [Hermes Docker layout and health endpoint](https://hermes-agent.nousresearch.com/docs/user-guide/docker)
- [Hermes profile commands](https://hermes-agent.nousresearch.com/docs/reference/profile-commands)
- [Hetzner Terraform provider](https://github.com/hetznercloud/terraform-provider-hcloud)
- [Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/)

The image and provider are pinned in code. Review upstream release notes before
changing either pin.

## Verification status

Terraform format/schema, ShellCheck, behavioral tests, and ephemeral Ansible
syntax/lint are locally runnable. Docker is not installed on the current
workstation, so `docker compose config` and container health were not exercised
here. CI performs Compose config validation; only an explicitly authorized
deployment can prove host idempotency, runtime health, and the model inference
path (the probe makes one small billed provider request).
