# Hermes AI Platform

## Scope and architecture

- Maintain one official Hermes Agent container on Ubuntu 24.04 or newer.
  Manager, DevOps, Coding, and Research are upstream-supported profiles inside
  that runtime, with separate identities, sessions, skills, and memory—not
  separate Hermes Core instances. Read `docs/architecture.md` when changing
  runtime boundaries.
- Minimal covers stages 00–04. Optimal (05–10), Advanced (11–19), and Maximum
  (20–31) are project roadmap levels, not upstream feature claims. Verify the
  preceding level before implementing the next; bring later features into
  Minimal only for a concrete dependency with a documented reason.
- Minimal excludes databases, Redis, public dashboard/API exposure, private
  cloud networking, monitoring, and automated restore. Do not invent upstream
  capabilities or production placeholders to satisfy roadmap labels.
- Production paths must not contain TODOs, mocks, sample data, fabricated
  images, echo-only installers/validators, empty skeletons, hard-coded success,
  or checks incapable of failing on broken behavior. Empty credential-template
  values are allowed; other incomplete work blocks its associated readiness claim.
- `PROJECT_AUDIT.md` and `CODEX_SETUP_PROMPT.md` are historical context, not the
  current implementation baseline. Check current code before repeating old
  findings. Read `CODEX_CLI_START.md` only for requested implementation-brief
  work. Read `prompts/README.md` before adding roadmap stage prompts; they need
  a real consumer and acceptance test.

## Change locations

- `installer/install.sh` owns CLI input validation, planning, ignored inventory
  generation, and the explicit external-mutation gate.
- `terraform/` owns the optional Hetzner server and ingress firewall only.
  Read `terraform/README.md` for cloud changes; existing-host mode skips Terraform.
- `ansible/roles/base/` owns host hardening; `ansible/roles/docker/` installs
  Docker; `ansible/roles/hermes/` owns runtime state, credentials, and profiles.
  Read `ansible/README.md` before changing roles or targeted playbooks.
- `docker/docker-compose.yml` owns the official image pin and loopback health
  contract. `profiles/*/SOUL.md` supplies runtime identities, not Pi skills.
  `scripts/telegram_env.py` validates protected Telegram input.
- For image/provider pin changes, review upstream release notes and the
  contracts linked from `README.md`; preserve the Terraform dependency lock.
  `terraform/.terraform.lock.hcl` is maintained by `terraform init`.
- `.generated/` contains installer-generated local artifacts; Terraform state,
  plans, provider caches, inventories, and populated credential files stay
  ignored. Change their generators, not deployment-specific generated copies.

## Commands and evidence

Run these commands from the repository root; their definitions are in
`scripts/validate.sh`, `tests/run.sh`, and `.github/workflows/validate.yml`.

| Purpose | Command | Boundary |
| --- | --- | --- |
| Strict readiness gate | `./installer/install.sh validate` | Delegates to `./scripts/validate.sh --all`; includes behavioral tests. |
| Opportunistic local pass | `./scripts/validate.sh --local` | Missing/unrunnable native tools may be skipped; not readiness proof. |
| Static validation | `./scripts/validate.sh --static` | Structure, Bash/ShellCheck, Terraform, Ansible/lint, Compose, secret-pattern checks. |
| Full behavioral suite | `bash tests/run.sh` | Executes every `tests/*_test.sh`; inspect skips as well as exit status. |
| One parser test | `bash tests/telegram_env_test.sh` | Uses temporary protected fixture files and Python 3. |
| Terraform formatting | `terraform -chdir=terraform fmt -check -recursive` | Formatting only; not schema or deployment proof. |

- Tooling uses native CLIs, not an application npm/pip package. The full gate
  needs Bash, Python 3, ripgrep, ShellCheck, Terraform, runnable Ansible,
  ansible-lint, Docker Compose, and Go Task (used by the upgrade task test).
  CI specifies Terraform 1.15.8, ansible-core `>=2.18,<2.20`, and ansible-lint
  `>=25,<26`; collection constraints live in `ansible/requirements.yml`.
- Validation is not uniformly offline: Terraform checks run
  `init -backend=false -input=false`, which can download providers. Some
  Ansible tests offer an opt-in `HERMES_TEST_ALLOW_UVX=1` dependency fallback;
  do not describe that branch as dependency-free. Inspect relevant test
  prerequisites before choosing a check.
- Tests use `tests/test_helper.sh`, temporary fixtures, and fake external
  commands for bounded behavior checks. Those fixtures do not establish live
  cloud, container, inference, or Telegram behavior.
- No separate application build/dev-server or standalone Python typecheck
  command is defined. Use source search and the relevant CLI checks when LSP
  is unavailable; an absent or stale diagnostic snapshot is not fresh evidence.

## Deployment and operations

- Before planning or deploying, read `INSTALLATION_GUIDE.md` for inputs,
  authorization, credential handling, and success criteria. Use the installer's
  current usage/validation for required flags; existing-host flows require
  `--ssh-public-key` as well as the private key.
- The intended Hetzner project is `hermes`, location `hel1`, with public key
  `~/.ssh/luk.pub`. Confirm the token's project before an authorized apply.
  Select a cost-optimized or regular-purpose type explicitly after reviewing
  current price, availability, recommendation, and deprecation in `hel1`;
  previous server-type selections are not durable defaults.
- Keep provider credentials outside Compose, Terraform state, inventory, and
  Git. Preserve protected file modes and `no_log`; Codex subscription auth and
  API-key credentials are mutually exclusive input paths.
- Deployment requires explicit authorization immediately before invocation
  and `--confirm-external-mutation`. Validation/CI does not authorize host
  access, credential installation, service recreation, Bot API probes, visible
  messages, group-administrator changes, or GitHub mutation. Already granted
  authorization applies only to the agreed action and target.
- For Telegram changes, read `ansible/README.md` and the ten-control checklist
  in `docs/operations.md`. Preserve one long-polling owner, explicit user/group
  allowlists, mention/reply/command dispatch, privacy mode, and rollback state.
  `manager` is an instance selection, not the global gateway default. Do not
  infer behavioral success from syntax, health, or connected-log checks.
- Before an authorized image upgrade, read `docs/operations.md` and inspect
  `scripts/hermes_upgrade.sh`. `task hermes:update` is not a local check: it
  backs up remote state before release lookup and may commit, push, and deploy.
  Preserve its backup and confirmation gates; check its generated commit
  against applicable commit rules before using the automated delivery path.

## Issue tracking

- For tracked work in this repository, read `docs/agents/issue-tracker.json`
  for the target and approved project/area labels; apply the global issue
  lifecycle, journal, and commit-reference rules. Legacy remote labels do not
  replace the configured vocabulary.
