# Ansible deployment

`site.yml` supports Ubuntu 24.04 or newer. It installs baseline SSH/UFW/fail2ban
hardening, Docker Engine from Docker's official apt repository, one Hermes
container, and four Hermes profiles inside that container. The profiles clone
the default profile's supported config and skills, then receive synchronized
mode-0600 credentials, distinct `SOUL.md` identities, and independent
memory/session stores.

The play requires explicit `hermes_model_provider` and `hermes_model` values.
API-key providers use `hermes_env_source`, a controller-local mode-0400/0600
file based on `configs/hermes.env.example`. The `openai-codex` provider instead
uses `hermes_codex_auth_source`, a protected Codex CLI `auth.json`; the role
copies it with `no_log` to the runtime user's `.codex/auth.json` for upstream
Hermes to import. The private SSH key and original credential remain on the
controller.
Use the root installer to generate a local ignored inventory and enforce the
external-mutation confirmation gate. Both new-host and existing-host flows
require the intended root public-key file. The base role normalizes that file
to one `restrict` authorization record, preserves the original authorization
once as `.ssh/authorized_keys.pre-hermes-hardening`, and locks the root
password. The targeted `root_hardening.yml` playbook validates sshd before and
after applying only those credential controls, without running package,
firewall, Docker, or runtime tasks. The preserved file is the exact
authorization rollback source and is never overwritten by later role runs.

## Targeted Telegram gateway playbooks

`telegram_gateway.yml` changes only an existing Hermes installation. It waits
for the authorized host, validates the current Compose/runtime boundary, and
includes `roles/hermes/tasks/telegram_gateway.yml`; it does not import the base,
Docker-installation, firewall, Terraform, or root-credential paths.
`telegram_verify.yml` is the value-free targeted verifier. Both are covered by
the repository strict syntax gate, and the mutation playbook is also linted.

The controller input is a separate external mode-`0400`/`0600` six-key file.
Ansible repeats the parser and selected-profile checks under `no_log` before
mutation. The Compose runtime profile is always supplied through protected
`gateway.env`; ordinary startup uses `default`, while `manager` is only the
first intended production selection. Exactly one service and one long-polling
gateway process remain.

Enable preserves the prior runtime profile once, manages only the selected
profile's marked Telegram block, validates both Compose and runtime state, and
recreates only the Hermes service. Disable derives the managed profile from
retained state, removes only that marked block, restores the preserved runtime
profile, and retains the rollback and managed-profile evidence. It never
deletes profiles, sessions, memory, provider credentials, Codex auth, or API
credentials, and failure handling never performs automatic disable or cleanup.

An ordinary full deployment without Telegram inputs refuses to overwrite an
existing enabled or pending Telegram configuration. To redeploy while Telegram
is enabled, supply the protected `--telegram-env` and `--gateway-profile`
inputs again (which select explicit enable reconciliation), or explicitly
complete a targeted disable before the ordinary deployment. The refusal occurs
before Hermes role mutation; it does not disable or restart the gateway.

Telegram privacy mode and minimum-permission group administration are operator
controls outside Ansible. Commands, replies, and direct mentions are the only
configured group triggers. Host connection, credential installation, service
recreation, Bot API probes, visible messages, group-administrator changes, and
GitHub mutation require separate authorization. Syntax/configuration and
connected-log checks are not end-to-end Telegram proof; use the ten-control
production checklist in `../docs/operations.md`.
