# Installation guide

## Supported boundary

Minimal supports Ubuntu 24.04 or newer and one Hermes Agent container. New-host
mode provisions one Hetzner VPS; existing-host mode never invokes Terraform.
Both deployment modes run Ansible against a real host and therefore require
explicit authorization immediately before invocation.

Required controller tools are Bash, Python 3, Terraform, Ansible, and the
`community.general` collection. Docker and Compose are installed on the target
by Ansible. ShellCheck and ansible-lint are required for the full development
validation gate. No tool is installed system-wide by repository scripts.
`./installer/install.sh validate` and `./scripts/validate.sh --all` are strict:
missing or unrunnable required tools fail the gate. The explicitly weaker
`./scripts/validate.sh --local` mode reports unavailable native tools as
`SKIP` and must not be used as readiness evidence.

## Inputs

- `--location`: `fsn1`, `nbg1`, or `hel1`, with `hel1` selected for this deployment;
- `--server-type`: explicit Hetzner type with no default; Terraform requires its
  live provider metadata to be cost-optimized or regular-purpose, available,
  recommended, and not deprecated in the selected location;
- `--hcloud-ssh-key-name`: exact existing key name in the active project;
- `--ssh-public-key`: matching local public key, currently `~/.ssh/luk.pub`;
- `--ssh-private-key`: controller-local key used only by Ansible;
- `--ssh-source-cidr`: repeatable explicit administrative IPv4/IPv6 CIDR;
- `--hermes-env`: external mode-0400/0600 credential file for API-key providers;
- `--codex-auth`: existing protected Codex CLI `auth.json`, required instead of
  `--hermes-env` for the `openai-codex` provider;
- `--model-provider`: `openrouter`, `anthropic`, `openai-api`, or `openai-codex`;
- `--model`: a current model ID supported by that provider;
- `--telegram-env`: separate external mode-0400/0600 six-key Telegram input;
- `--gateway-profile`: explicit Hermes profile paired with `--telegram-env`;
- `--telegram-state`: mandatory `enabled` or `disabled` for the targeted
  `telegram` flow;
- `HCLOUD_TOKEN`: environment-only credential for Terraform new-host mode;
- `--host` and `--ssh-user`: required for existing-host and targeted Telegram
  flows.

The active Hetzner CLI context was read-only verified as `hermes` on
2026-08-17. Terraform uses the token's project; it does not select a CLI
context itself. Confirm the token targets the intended Hermes project before
an authorized apply.

The provider UI selection on 2026-08-17 recommended regular-performance
`cpx22` in `hel1`: x86 AMD, 2 shared vCPU, 4 GB RAM, and 80 GB disk. The UI
displayed USD 0.037/hour and USD 22.99/month. This is a timestamped observation,
not a durable price or capacity guarantee; repeat the catalog check immediately
before any future apply. Terraform plan
independently checks category and location status through the official
[`hcloud_server_type` data source](https://registry.terraform.io/providers/hetznercloud/hcloud/latest/docs/data-sources/server_type).

A safe plan against the `hermes` project completed on 2026-08-17 with
`location=hel1`, `server_type=cpx22`, the registered `Luk` key, and the current
operator IPv4 `/32`. The saved plan was complete and applyable with two creates
(one firewall and one server), zero updates, and zero deletes. The CIDR and
ignored local plan artifact are intentionally not recorded here. The authorized
apply then created exactly that server and firewall; host configuration and
independent inference verification completed on 2026-08-18.

The generated inventory keeps a dedicated mode-0600 known-hosts file under
`.generated/`. First connection uses OpenSSH `accept-new`: it records a new host
key but refuses a changed key later. This is trust-on-first-use, not independent
host identity proof. For a higher-assurance deployment, verify that first key
through an out-of-band Hetzner console before treating SSH identity as proven.

## External mutation commands

The installer refuses deployment unless `--confirm-external-mutation` is
present. New-host deployment plans, applies the saved plan, generates an
ignored inventory from Terraform output, configures the host, and runs the
independent verification playbook. Existing-host deployment skips Terraform.

New-host form:

```bash
./installer/install.sh deploy new --location hel1 --server-type cpx22 --hcloud-ssh-key-name Luk --ssh-public-key ~/.ssh/luk.pub --ssh-private-key ~/.ssh/luk --ssh-source-cidr 203.0.113.10/32 --hermes-env /protected/path/hermes.env --model-provider openrouter --model anthropic/claude-sonnet-4.6 --confirm-external-mutation
```

Existing-host form:

```bash
./installer/install.sh deploy existing --host 192.0.2.44 --ssh-user ubuntu --ssh-public-key /protected/path/luk.pub --ssh-private-key /protected/path/luk --ssh-source-cidr 203.0.113.10/32 --hermes-env /protected/path/hermes.env --model-provider openrouter --model anthropic/claude-sonnet-4.6 --confirm-external-mutation
```

ChatGPT-subscription new-host form:

```bash
./installer/install.sh deploy new --location hel1 --server-type cpx22 --hcloud-ssh-key-name Luk --ssh-public-key ~/.ssh/luk.pub --ssh-private-key ~/.ssh/luk --ssh-source-cidr 203.0.113.10/32 --codex-auth ~/.codex/auth.json --model-provider openai-codex --model gpt-5.4 --confirm-external-mutation
```

The `openai-codex` path is upstream-supported OAuth reuse, not OpenAI API
billing. The controller auth file is copied without logged content to
`/opt/hermes/data/.codex/auth.json` with mode `0600`; Hermes imports it into its
own credential store. Verify `codex login status` before deployment. Never
commit or print the auth file, and do not combine `--codex-auth` with
`--hermes-env`. See the official [Hermes provider
reference](https://hermes-agent.nousresearch.com/docs/integrations/providers)
and [OpenAI ChatGPT-plan Codex
guidance](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan).

These commands are documentation, not authorization. Do not run either until
the target values are real and the operator confirms the external mutation.

## Telegram targeted and full-deploy interfaces

The Telegram source file is separate from the provider credential file and
contains exactly these placeholder-only assignments:

```dotenv
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USERS=
TELEGRAM_ALLOWED_CHATS=
TELEGRAM_REQUIRE_MENTION=true
TELEGRAM_EXCLUSIVE_BOT_MENTIONS=true
TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES=false
```

It must be outside Git and generated artifacts and have mode `0400` or `0600`.
The parser requires one or more unique positive user IDs, one or more unique
negative group IDs, and the exact three safety flags shown above. It rejects
wildcards, webhooks, allow-all settings, and group-wide authorization keys
without printing or hashing protected values.

Local-only targeted syntax plan:

```bash
./installer/install.sh plan telegram --telegram-state enabled --host 192.0.2.44 --ssh-user ubuntu --ssh-public-key /protected/path/luk.pub --ssh-private-key /protected/path/luk --telegram-env /protected/path/telegram.env --gateway-profile manager
```

Separately authorized targeted enable:

```bash
./installer/install.sh deploy telegram --telegram-state enabled --host 192.0.2.44 --ssh-user ubuntu --ssh-public-key /protected/path/luk.pub --ssh-private-key /protected/path/luk --telegram-env /protected/path/telegram.env --gateway-profile manager --confirm-external-mutation
```

Separately authorized targeted disable:

```bash
./installer/install.sh deploy telegram --telegram-state disabled --host 192.0.2.44 --ssh-user ubuntu --ssh-public-key /protected/path/luk.pub --ssh-private-key /protected/path/luk --confirm-external-mutation
```

`manager` is the selected first production instance, not the application-wide
default. Without Telegram options, Compose retains its `default` profile and
full `new`/`existing` deployments retain their existing behavior. A full
deployment may supply `--telegram-env` and `--gateway-profile` together to
enable the same shared role path; either option alone fails before Terraform,
Ansible, SSH, or Docker.

The gateway remains a single upstream long-polling owner. Telegram privacy mode
stays enabled, the bot is an administrator of the configured group only with
the minimum permissions Telegram permits, and group dispatch requires a
command, reply, or direct mention from a configured user. No webhook, public
listener, DNS, TLS, or firewall change is part of this path.

Enable retains `/opt/hermes/app/gateway-profile.pre-telegram` and records the
managed profile separately. Disable removes only the marked Telegram block,
restores the retained pre-Telegram profile, and recreates only the Hermes
service. It does not remove profiles, sessions, memory, provider credentials,
Codex auth, API credentials, or rollback evidence, and it is never attempted
automatically after a failure.

The implementation is pinned to the upstream
[Telegram guide](https://github.com/NousResearch/hermes-agent/blob/v2026.9.14/website/docs/user-guide/messaging/telegram.md)
and [v2026.9.14 release](https://github.com/NousResearch/hermes-agent/releases/tag/v2026.9.14).
Changing the image pin requires revalidation against both. Syntax checks,
Compose rendering, health, and connected log status are not Telegram
behavioral proof.

## Telegram production authorization and evidence

Each of these production controls requires explicit authorization and recorded
evidence; no item is implied by source review or CI:

1. Confirm Bot API identity without retaining sensitive fields.
2. Confirm webhook state is empty and exactly one long-polling owner exists.
3. Confirm the container and selected `manager` profile are healthy.
4. Confirm every configured user receives a substantive DM response.
5. Confirm every configured user receives a substantive response through a
   mention or reply in a configured group.
6. Confirm an unconfigured user is denied in a configured group.
7. Confirm a configured user is denied in an unconfigured group.
8. Confirm an ordinary unmentioned group message gets no response and never
   enters agent context.
9. Re-run the existing loopback API health and model inference probes.
10. Independently read back the deployed profile, protected file modes,
    gateway status, and retained rollback state without exposing values.

The exact actions still awaiting separate approval are host connection,
protected credential installation, service recreate/restart, Bot API probes,
visible test messages, group-administrator changes, and GitHub mutation. Real
tokens, user or chat IDs, message bodies, and raw updates must not enter logs,
documentation, Issue evidence, or command arguments.

## What success means

The installer prints success only after Ansible completes and `verify.yml`
independently observes a healthy container plus all four profiles through the
Hermes CLI, validates the model config, and gets a non-empty one-shot response
from the Manager profile. The inference probe makes one small provider request
and may incur cost. A failed configuration, unhealthy container, missing
profile, unreachable host, or failed inference exits non-zero. Terraform apply
success alone is not platform success.

The first authorized remote run must also be followed by a second Ansible run
to demonstrate idempotency. The 2026-08-18 deployment completed that second run
with `changed=0`, `unreachable=0`, and `failed=0`.
