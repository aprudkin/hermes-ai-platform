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
- `HCLOUD_TOKEN`: environment-only credential for Terraform new-host mode;
- `--host` and `--ssh-user`: required only for existing-host mode.

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
./installer/install.sh deploy existing --host 192.0.2.44 --ssh-user ubuntu --ssh-private-key ~/.ssh/luk --ssh-source-cidr 203.0.113.10/32 --hermes-env /protected/path/hermes.env --model-provider openrouter --model anthropic/claude-sonnet-4.6 --confirm-external-mutation
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
