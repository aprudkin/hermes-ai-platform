# Hermes AI Platform — Minimal

This repository implements a small, reproducible deployment of one official
Hermes Agent container on Ubuntu 24.04. The Minimal deployment was applied to
Hetzner `hel1` and verified end to end on 2026-08-18.

## What Minimal implements

- Hetzner Terraform for one VPS in selected Finland location `hel1`;
- explicit server-type selection with live plan-time checks for Hetzner's
  cost-optimized or regular-purpose category, location availability,
  recommendation, and deprecation;
- reuse and fail-closed comparison of an existing Hetzner SSH public key;
- an ingress firewall allowing SSH and ICMP only from configured CIDRs;
- a separate existing-host path that creates no cloud resources;
- Ubuntu hardening, Docker installation, and deployment through Ansible;
- one pinned official `nousresearch/hermes-agent:v2026.8.27` container;
- persistent Hermes state at `/opt/hermes/data`, with no public service port;
- a real loopback gateway health check;
- explicit provider/model configuration and a post-deploy inference probe;
- protected reuse of an existing Codex CLI ChatGPT-subscription login through
  Hermes' supported `openai-codex` provider, without an OpenAI API key;
- Manager, DevOps, Coding, and Research as supported Hermes profiles inside
  that one container, each with its own SOUL, sessions, skills, and memory;
- an optional, profile-scoped Telegram long-polling gateway for explicit users
  and groups, with one gateway process and no webhook or inbound listener;
- fail-closed installer modes, behavioral tests, static validation, and CI.

Postgres, Redis, DNS, a dashboard, public API exposure, a private Hetzner
network, monitoring, automated restore, and stages 05–31 are not part of
Minimal.

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
./installer/install.sh plan new --location hel1 --server-type cpx22 --hcloud-ssh-key-name Luk --ssh-public-key ~/.ssh/luk.pub --ssh-source-cidr 203.0.113.10/32
```

`hel1` is the selected location. The `cpx22` choice follows the provider's
regular-performance recommendation observed on 2026-08-17 and must be
rechecked before any future apply.
Replace the documentation-only CIDR with the actual operator network. See
[QUICKSTART.md](QUICKSTART.md) for both modes and
[INSTALLATION_GUIDE.md](INSTALLATION_GUIDE.md) for the snapshot details and
mutation boundary.

## Upstream contracts verified through 2026-08-27

- [Hermes installation](https://hermes-agent.nousresearch.com/docs/getting-started/installation)
- [Hermes Docker layout and health endpoint](https://hermes-agent.nousresearch.com/docs/user-guide/docker)
- [Hermes profile commands](https://hermes-agent.nousresearch.com/docs/reference/profile-commands)
- [Hermes providers, including OpenAI Codex OAuth](https://hermes-agent.nousresearch.com/docs/integrations/providers)
- [Hermes Codex app-server runtime](https://hermes-agent.nousresearch.com/docs/user-guide/features/codex-app-server-runtime)
- [Using Codex with a ChatGPT plan](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan)
- [Hetzner Terraform provider](https://github.com/hetznercloud/terraform-provider-hcloud)
- [Hetzner server-type data source](https://registry.terraform.io/providers/hetznercloud/hcloud/latest/docs/data-sources/server_type)
- [Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/)

The image and provider are pinned in code. Review upstream release notes before
changing either pin.

## Telegram gateway source boundary

Telegram uses a separate controller-local mode-`0400`/`0600` six-key file; it
does not use `configs/hermes.env.example`. The source implementation accepts
only explicit users crossed with explicit groups, requires a command, reply, or
direct mention in groups, and retains Telegram privacy mode. The first intended
production instance selects the `manager` profile, but `manager` is not a
global default: ordinary Compose startup remains on `default`, and the
installer accepts an explicit supported profile.

The targeted plan, enable, and disable interfaces are documented in
[QUICKSTART.md](QUICKSTART.md). Disable removes only the managed Telegram block,
restores the retained pre-Telegram gateway profile, and recreates the single
Hermes service. It preserves provider credentials, Codex auth, profiles,
sessions, memory, API credentials, and rollback evidence.

The gateway contract is pinned to the upstream
[Telegram guide](https://github.com/NousResearch/hermes-agent/blob/v2026.8.27/website/docs/user-guide/messaging/telegram.md)
and [v2026.8.27 release](https://github.com/NousResearch/hermes-agent/releases/tag/v2026.8.27).
Passing syntax, Compose configuration, container health, or a connected log
marker is deployment evidence only; it is not Telegram behavioral proof.

## Verification status

On 2026-08-18, the authorized deployment created one `cpx22` server and one
ingress firewall in `hel1`. A repeat Ansible run completed with `changed=0` and
`failed=0`; independent verification observed a healthy container, exact
profile identities, complete model configuration, and a successful one-shot
inference through the ChatGPT subscription. Local Docker remains unavailable,
so local `docker compose config` is still skipped; the live Docker runtime is
the behavioral deployment evidence for the original Minimal deployment. The
Telegram gateway has not been installed or behaviorally verified in production;
host access, protected credential installation, service recreation, Bot API
probes, visible messages, group-administrator changes, and GitHub mutation each
remain separately authorized.
