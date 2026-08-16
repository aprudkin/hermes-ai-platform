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

Choose `fsn1` or `nbg1` explicitly. Put `HCLOUD_TOKEN` into the calling
process through your protected credential mechanism, then run one command:

```bash
./installer/install.sh plan new --location fsn1 --hcloud-ssh-key-name Luk --ssh-public-key ~/.ssh/luk.pub --ssh-source-cidr 203.0.113.10/32
```

Both `fsn1` and `203.0.113.10/32` are documentation examples. Select the German
location and substitute the real operator CIDR before running a plan.

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

Copy `configs/hermes.env.example` to a file outside the repository, populate at
least one provider key, and set mode `0600`. The installer rejects a broader
mode. It does not print the file and Ansible uses `no_log` while transferring
it to `/opt/hermes/data/.env`. Deployment also requires an explicit supported
provider (`openrouter`, `anthropic`, or `openai-api`) and a model ID valid for
that provider; the installer checks that the matching credential is populated.

Deployment is intentionally absent from this quickstart because it creates or
changes external systems. See [INSTALLATION_GUIDE.md](INSTALLATION_GUIDE.md).
