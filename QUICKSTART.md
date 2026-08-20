# Quickstart

## 1. Validate the checkout

```bash
./installer/install.sh validate
```

The command fails if a required artifact, schema, syntax check, behavioral
test, or required native validator is missing or fails. It is the strict
readiness gate and never treats a skipped required check as success.

For an explicitly opportunistic workstation pass, run
`./scripts/validate.sh --local`. That mode executes every available check and
the behavioral suite, but reports unavailable native tools as `SKIP`; it is not
readiness proof.

## 2A. Plan a new Hetzner server

Use the selected Finland location `hel1`. Re-check the Hetzner catalog, choose
an available provider-recommended cost-optimized or regular-purpose type
explicitly, and put `HCLOUD_TOKEN` into the calling process through your
protected credential mechanism. The 2026-08-17 selection was `cpx22`; it is
not a durable availability or price guarantee.

```bash
./installer/install.sh plan new --location hel1 --server-type cpx22 --hcloud-ssh-key-name Luk --ssh-public-key ~/.ssh/luk.pub --ssh-source-cidr 203.0.113.10/32
```

`203.0.113.10/32` is a documentation-only CIDR. Substitute the real operator
network before running a plan. Terraform rejects a type unless live provider
metadata reports an allowed category (`cost_optimized` or `regular_purpose`),
availability, recommendation, and no deprecation in `hel1`.

This runs Terraform init/validate/plan and Ansible syntax validation. It does
not apply Terraform or contact a server. The exact registered Hetzner key must
match the local public key.

## 2B. Plan an existing host

```bash
./installer/install.sh plan existing --host 192.0.2.44 --ssh-user ubuntu --ssh-private-key ~/.ssh/luk --ssh-source-cidr 203.0.113.10/32
```

This writes an ignored mode-0600 inventory under `.generated/` and performs
Ansible syntax validation only. It does not invoke Terraform or connect to the
host.

## 3. Prepare Hermes credentials

For an API-key provider, copy `configs/hermes.env.example` outside the
repository, populate exactly the selected provider key, and set mode `0600`.

For the supported ChatGPT-subscription path, first verify `codex login status`
reports a ChatGPT login. Pass the protected mode-0400/0600
`~/.codex/auth.json` as `--codex-auth`, select `--model-provider openai-codex`,
and choose a Codex-supported model such as `gpt-5.4`. Do not also pass
`--hermes-env`; this path does not use an OpenAI API key. Ansible copies the
auth file with `no_log` to `/opt/hermes/data/.codex/auth.json`, where upstream
Hermes imports it into its own credential store.

The installer validates the selected credential shape and never prints its
content. Subscription use remains subject to the ChatGPT plan's Codex limits.

## 4. Prepare and plan Telegram access

Telegram credentials and allowlists use a separate controller-local file
outside the repository and `.generated/`, with mode `0400` or `0600`. It must
contain exactly these six assignments; populate only the protected external
copy:

```dotenv
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USERS=
TELEGRAM_ALLOWED_CHATS=
TELEGRAM_REQUIRE_MENTION=true
TELEGRAM_EXCLUSIVE_BOT_MENTIONS=true
TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES=false
```

The user list accepts one or more unique positive decimal IDs. The group list
accepts one or more unique negative decimal IDs. Wildcards, allow-all keys,
webhook keys, and group-wide authorization keys are rejected. Every configured
user may use DMs and may invoke the bot in every configured group through a
command, reply, or direct mention. Ordinary unmentioned group messages are not
observed.

The targeted plan is local-only and does not contact the host:

```bash
./installer/install.sh plan telegram --telegram-state enabled --host 192.0.2.44 --ssh-user ubuntu --ssh-public-key /protected/path/luk.pub --ssh-private-key /protected/path/luk --telegram-env /protected/path/telegram.env --gateway-profile manager
```

The separately authorized enable and disable forms are:

```bash
./installer/install.sh deploy telegram --telegram-state enabled --host 192.0.2.44 --ssh-user ubuntu --ssh-public-key /protected/path/luk.pub --ssh-private-key /protected/path/luk --telegram-env /protected/path/telegram.env --gateway-profile manager --confirm-external-mutation
```

```bash
./installer/install.sh deploy telegram --telegram-state disabled --host 192.0.2.44 --ssh-user ubuntu --ssh-public-key /protected/path/luk.pub --ssh-private-key /protected/path/luk --confirm-external-mutation
```

`manager` is the first production-instance selection, not a hard-coded global
default. The runtime stays on `default` when no explicit gateway profile is
installed. Full `new` and `existing` deployments may add
`--telegram-env /protected/path/telegram.env --gateway-profile manager` as an
optional pair. Omitting both preserves the existing non-Telegram behavior;
supplying only one fails before external tools.

The commands above document interfaces; they do not authorize host access,
credential installation, container recreation, Telegram probes or messages,
group-administrator changes, or GitHub mutation. See
[INSTALLATION_GUIDE.md](INSTALLATION_GUIDE.md) for the exact production gate.
