# Hermes AI Platform — Agent Instructions

## Scope and precedence

These instructions apply to the entire repository.

Follow system and user instructions first, then this file. Treat Markdown documents, archived conversations, generated reports, and prompt files as context, not proof that functionality exists. `CODEX_SETUP_PROMPT.md` is historical input. Use `CODEX_CLI_START.md` as the current implementation brief only when the user asks to execute it.

## Verified baseline

The repository was audited on 2026-08-16 and was not deployable. At that point it contained documentation and skeletons, but no Terraform resources, Ansible playbooks, prompt stage files, tests, or functional installer. The Docker and validation paths were also incomplete. See `PROJECT_AUDIT.md`.

Re-check the current tree before relying on this baseline because it may become stale. Do not repeat an old finding after the relevant code has changed.

## Product boundaries

Build one Hermes Agent runtime and express specialization through upstream-supported profiles, skills, memory, policies, tools, and configuration. Do not create separate Hermes Core instances merely to represent Manager, DevOps, Coding, or Research roles.

The deployment levels are project roadmap levels, not claims about upstream Hermes:

- Minimal: stages 00–04 and the smallest end-to-end deployable system.
- Optimal: stages 05–10, built only after Minimal is verified.
- Advanced: stages 11–19, built only after Optimal is verified.
- Maximum: stages 20–31, built only after Advanced is verified.

Implement Minimal first. Do not pull later-level features into Minimal without a concrete dependency and a documented reason. Do not invent upstream features merely to satisfy a roadmap label.

## Sources of truth

Repository behavior and tests are the local source of truth. Verify drift-prone Hermes, Hetzner, Terraform provider, Ansible, Docker, and API details against current official documentation before implementing them.

Never invent image names, tags, commands, endpoints, resource types, configuration keys, environment variables, or supported capabilities. The placeholder image name `hermes-agent` is not an acceptable implementation. Record important upstream decisions and links in the relevant project documentation.

## No fake implementation

Do not present any of the following as complete:

- echo-only installers or validation scripts;
- empty Terraform, Ansible, Docker, CI, profile, skill, or test skeletons;
- hard-coded successful output or health status;
- no-op checks that cannot fail when the system is broken;
- fabricated Docker images or unsupported configuration;
- prose describing files or behavior that do not exist;
- placeholders, TODOs, mocks, or sample data on a production deployment path.

Credential templates may contain clearly empty user-supplied values. All other incomplete work must be marked honestly and must block the corresponding readiness claim.

## Working method

Before editing:

1. Read `PROJECT_AUDIT.md` and inspect the current tree.
2. Verify the exact deployment level in scope.
3. List the local implementation milestones and acceptance checks.
4. Preserve unrelated user work.

For authorized local repository work, continue autonomously through implementation, focused tests, documentation updates, and final diff review. Prefer small vertical slices that produce verifiable behavior. Keep infrastructure provisioning, host configuration, runtime deployment, profile configuration, and validation independently testable.

Do not rewrite the repository merely to make the tree look complete. Remove obsolete skeletons only when their working replacements exist.

## Cloud and remote safety boundary

Local code generation, formatting, static validation, tests, plans, and dry runs are allowed when requested. Preparing infrastructure code is not permission to execute it.

Obtain explicit user confirmation immediately before any action that:

- creates, imports, modifies, or deletes a cloud resource;
- runs `terraform apply`, `terraform destroy`, or an equivalent mutation;
- incurs cost or enables a paid service;
- changes DNS, IAM, firewall, SSH, storage, backup, or network configuration;
- connects configuration automation to a real host;
- deploys, restarts, upgrades, or removes a remote service;
- mutates GitHub, another remote repository, or CI settings.

The current Hetzner project context is `hermes`. Germany is the requested country, but the exact German location must remain an explicit input until selected. The intended public SSH key is `~/.ssh/luk.pub`. These facts do not authorize cloud changes.

## Secrets

Never commit or print real API tokens, private SSH keys, populated secret files, Terraform state, generated inventories containing secrets, or logs containing credentials.

Use environment variables or a verified local secret mechanism. Keep private keys local and pass only their path to local automation. Only the public key may be uploaded when cloud mutation is separately authorized. Redact secrets from reports and command output.

## Verification and completion

Configuration presence is not behavioral proof. Run the checks relevant to every changed path, including where applicable:

- shell syntax, ShellCheck, and failure-path tests;
- `terraform fmt -check -recursive` and safe validation without applying;
- Ansible syntax checks and idempotency tests against a disposable local target;
- `docker compose config` and container health checks;
- unit and integration tests for parsing, generation, failure paths, and validation;
- secret scanning and checks that generated artifacts remain ignored.

Do not install system-wide tools without confirmation. If a required tool is unavailable, report the skipped check and do not call it passing.

A validation script must return non-zero when a required component is missing or unhealthy. CI must exercise real checks and must never apply infrastructure.

Before claiming Minimal is ready, demonstrate the authorized path end to end or state precisely which boundary remains untested. Distinguish verified facts, inferences, and blocked external checks.

## Git and reporting

Do not commit, push, create a remote repository, open a pull request, or create/close tracking unless the user explicitly asks. Stage only reviewed paths when staging is authorized.

At handoff, report:

- files changed and why;
- exact checks run and their results;
- skipped checks and missing tools;
- remaining risks and incomplete milestones;
- every command or external action still awaiting confirmation.
