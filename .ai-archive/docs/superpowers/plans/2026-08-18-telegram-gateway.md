# Hermes Telegram Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fail-closed, profile-scoped Telegram long-polling gateway path for one or more explicitly allowed users crossed with one or more explicitly allowed groups, without weakening the existing Hermes Minimal deployment or crossing the production-mutation boundary.

**Architecture:** A controller-local Python parser owns the exact protected-input grammar and exposes a value-free check-only interface; the installer and Ansible both invoke it before mutation, and Ansible reads the already validated controller file only inside `no_log` tasks. The existing Compose service gains an explicit gateway profile selected through a protected deployment env file, while a focused Hermes role task manages only the selected profile's marked Telegram block and retained pre-Telegram profile. A targeted playbook and verifier reuse existing host/key inventory behavior but never import Terraform, base, Docker-installation, firewall, or root-credential work.

**Tech Stack:** Bash 3.2-compatible installer/tests, Python 3 standard library, Ansible Core 2.18-2.19, Docker Compose Specification, pinned `nousresearch/hermes-agent:v2026.8.16`, GitHub Actions Ubuntu 24.04.

**Spec:** `docs/superpowers/specs/2026-08-18-telegram-gateway-design.md`

## Global Constraints

- Keep exactly one Hermes Agent Compose service and one long-polling gateway owner; do not add a second bot, webhook, listener, DNS, TLS, proxy, or firewall rule.
- Keep the runtime image pinned to `nousresearch/hermes-agent:v2026.8.16`; revalidate this plan against upstream before changing that tag.
- Accept one or more unique positive decimal user IDs and one or more unique negative decimal group IDs; authorize the global user set crossed with the global group set.
- Use only `TELEGRAM_ALLOWED_USERS` and `TELEGRAM_ALLOWED_CHATS` for access. Reject `TELEGRAM_GROUP_ALLOWED_CHATS`, `TELEGRAM_GROUP_ALLOWED_USERS`, wildcards, webhook keys, and allow-all keys.
- Require `TELEGRAM_REQUIRE_MENTION=true`, `TELEGRAM_EXCLUSIVE_BOT_MENTIONS=true`, and `TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES=false`.
- The protected Telegram source must be outside Git/generated artifacts and mode `0400` or `0600`; never print, hash, log, or place its values in process arguments.
- Validate the protected input before Terraform, Ansible, SSH, Docker, or any other external process. Ansible must repeat validation with `no_log: true` before its first mutation.
- The targeted `telegram` installer flow must not run Terraform, packages, firewall, Docker installation, the base role, or root-credential work.
- Full `new` and `existing` flows remain backward-compatible when Telegram options are absent and require the `--telegram-env`/`--gateway-profile` pair when either is present.
- Disabling removes only the managed Telegram block, restores the retained pre-Telegram gateway profile, recreates only the Hermes service, and preserves profiles, sessions, memory, provider credentials, Codex auth, API credentials, and rollback evidence.
- Local implementation, tests, formatting, static validation, and CI preparation are in scope. Host connection, secret installation, container recreation, Telegram Bot API probes/messages, group administration, GitHub mutation, commit, and push remain separately authorized.
- A connected log/status marker is deployment evidence only; production completion still requires every positive and negative end-to-end control in the spec.

## File Structure

- Create `scripts/telegram_env.py`: exact parser/validator for the six-key protected input with a value-free check-only CLI.
- Create `tests/telegram_env_test.sh`: hermetic grammar, secrecy, and file-mode coverage for the parser.
- Modify `installer/install.sh`: parse the `telegram` target and new options, enforce fail-before-tools ordering, share optional-pair validation with full deploys, and dispatch targeted syntax/deploy/verify phases.
- Modify `tests/installer_test.sh`: top-level target/option contract tests.
- Modify `tests/installer_plan_test.sh`: targeted local-plan tests and full-plan optional-pair tests with fake external tools.
- Modify `tests/installer_deploy_test.sh`: targeted enable/disable phase order, safe-resume, secrecy, and no-Terraform/no-base assertions.
- Modify `docker/docker-compose.yml`: parameterize the pinned gateway command with `HERMES_GATEWAY_PROFILE` while preserving `default` behavior.
- Modify `ansible/roles/hermes/defaults/main.yml`: define Telegram state/source/profile inputs, protected rollback/managed-profile paths, marker text, Compose argv prefix, and verification marker.
- Modify `ansible/roles/hermes/tasks/main.yml`: apply Telegram only after provider credential synchronization and before final profile verification.
- Create `ansible/roles/hermes/tasks/validate_telegram.yml`: repeat controller-local parsing and selected-profile validation with `no_log`.
- Create `ansible/roles/hermes/tasks/telegram_gateway.yml`: enable/disable state machine, exact marked block management, retained profile preservation/restoration, Compose validation, focused recreation, and health/status checks.
- Modify `ansible/roles/hermes/handlers/main.yml`: route ordinary restarts through the same explicit protected Compose env file.
- Create `ansible/telegram_gateway.yml`: existing-host-only targeted mutation playbook; no base or Docker roles.
- Create `ansible/telegram_verify.yml`: targeted read-only runtime/profile/poller verification.
- Create `tests/fixtures/telegram_gateway.yml`: disposable local-filesystem exercise of the production role task.
- Create `tests/ansible_telegram_gateway_test.sh`: managed-block fidelity, mode, idempotence, profile preservation, disable, and failure-path tests.
- Modify `scripts/validate.sh`: require new artifacts, syntax/lint both playbooks, and validate Compose for default and selected profiles.
- Modify `.github/workflows/validate.yml`: no deployment step; continue using the repository strict gate.
- Modify `configs/hermes.env.example`: remove the misleading Telegram credential comment because Telegram uses a separate protected six-key file.
- Modify `README.md`, `QUICKSTART.md`, `INSTALLATION_GUIDE.md`, `docs/operations.md`, and `ansible/README.md`: document implemented interfaces, rollback, evidence boundaries, and separately authorized production procedure.

---

### Task 1: Exact protected Telegram input parser

**Files:**
- Create: `scripts/telegram_env.py`
- Create: `tests/telegram_env_test.sh`

**Interfaces:**
- Consumes: `python3 scripts/telegram_env.py check PATH`.
- Produces: exit `0` with no stdout for valid input or exit non-zero with a value-free diagnostic; the parser never emits protected values.
- Produces Python functions `parse_source(path: pathlib.Path) -> dict[str, str]`, `validate_id_list(value: str, *, positive: bool, field: str) -> None`, and `main(argv: Sequence[str]) -> int`.

- [ ] **Step 1: Write the failing parser test matrix**

Create `tests/telegram_env_test.sh` using `tests/test_helper.sh`, a mode-0600 temporary fixture, and a helper that never embeds a production-shaped token in tracked source:

```bash
write_valid_env() {
  local destination="$1"
  local users="${2:-101,202}"
  local chats="${3:--1001,-1002}"
  {
    printf 'TELEGRAM_BOT_TOKEN=%s:%s\n' '123456789' 'fixture_value_abcdefghijklmnop'
    printf 'TELEGRAM_ALLOWED_USERS=%s\n' "$users"
    printf 'TELEGRAM_ALLOWED_CHATS=%s\n' "$chats"
    printf 'TELEGRAM_REQUIRE_MENTION=true\n'
    printf 'TELEGRAM_EXCLUSIVE_BOT_MENTIONS=true\n'
    printf 'TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES=false\n'
  } >"$destination"
  chmod 600 "$destination"
}
```

Test valid single/multiple lists, reordered exact keys, and mode 0400/0600. For each invalid case, rewrite one fixture and require non-zero: missing/unknown/duplicate keys, comment or blank record, leading/trailing whitespace, spaces around `=`, empty CSV element, duplicate ID, user zero/negative, group zero/positive, non-decimal ID, wildcard, malformed/empty token, wrong mention flags, observation `true`, forbidden group-wide keys, webhook keys, allow-all keys, symlink input, and mode 0644. Capture stdout/stderr and assert they contain none of the token fragment, user IDs, or chat IDs.

- [ ] **Step 2: Run the parser test and verify RED**

Run: `bash tests/telegram_env_test.sh`

Expected: FAIL because `scripts/telegram_env.py` does not exist.

- [ ] **Step 3: Implement the strict parser**

Implement the parser with only the standard library and these exact constants/shape:

```python
#!/usr/bin/env python3
from __future__ import annotations

import os
import pathlib
import re
import stat
import sys
from collections.abc import Sequence

EXPECTED_KEYS = (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_USERS",
    "TELEGRAM_ALLOWED_CHATS",
    "TELEGRAM_REQUIRE_MENTION",
    "TELEGRAM_EXCLUSIVE_BOT_MENTIONS",
    "TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES",
)
TOKEN_RE = re.compile(r"^[1-9][0-9]*:[A-Za-z0-9_-]{20,}$")
ASSIGNMENT_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")

class InvalidTelegramEnv(ValueError):
    pass

def validate_id_list(value: str, *, positive: bool, field: str) -> None:
    records = value.split(",")
    if not records or any(not item or item != item.strip() for item in records):
        raise InvalidTelegramEnv(f"{field} must be a trimmed non-empty CSV")
    expected = re.compile(r"^[1-9][0-9]*$" if positive else r"^-[1-9][0-9]*$")
    if any(item == "*" or expected.fullmatch(item) is None for item in records):
        raise InvalidTelegramEnv(f"{field} contains an invalid identifier")
    if len(records) != len(set(records)):
        raise InvalidTelegramEnv(f"{field} contains duplicate identifiers")

def parse_source(path: pathlib.Path) -> dict[str, str]:
    if path.is_symlink():
        raise InvalidTelegramEnv("Telegram input must be a regular file, not a symlink")
    source_stat = path.stat()
    if not stat.S_ISREG(source_stat.st_mode):
        raise InvalidTelegramEnv("Telegram input must be a regular file")
    file_mode = stat.S_IMODE(source_stat.st_mode)
    if file_mode not in {0o400, 0o600}:
        raise InvalidTelegramEnv("Telegram input mode must be 0400 or 0600")
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    if len(lines) != len(EXPECTED_KEYS) or any(not line for line in lines):
        raise InvalidTelegramEnv("Telegram input must contain exactly six assignments")
    values: dict[str, str] = {}
    for line in lines:
        match = ASSIGNMENT_RE.fullmatch(line)
        if match is None or match.group(1) in values:
            raise InvalidTelegramEnv("Telegram input contains an invalid or duplicate assignment")
        values[match.group(1)] = match.group(2)
    if set(values) != set(EXPECTED_KEYS):
        raise InvalidTelegramEnv("Telegram input keys do not match the contract")
    if TOKEN_RE.fullmatch(values["TELEGRAM_BOT_TOKEN"]) is None:
        raise InvalidTelegramEnv("TELEGRAM_BOT_TOKEN is structurally invalid")
    validate_id_list(values["TELEGRAM_ALLOWED_USERS"], positive=True, field="TELEGRAM_ALLOWED_USERS")
    validate_id_list(values["TELEGRAM_ALLOWED_CHATS"], positive=False, field="TELEGRAM_ALLOWED_CHATS")
    if values["TELEGRAM_REQUIRE_MENTION"] != "true":
        raise InvalidTelegramEnv("TELEGRAM_REQUIRE_MENTION must be true")
    if values["TELEGRAM_EXCLUSIVE_BOT_MENTIONS"] != "true":
        raise InvalidTelegramEnv("TELEGRAM_EXCLUSIVE_BOT_MENTIONS must be true")
    if values["TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES"] != "false":
        raise InvalidTelegramEnv("TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES must be false")
    return values

def main(argv: Sequence[str]) -> int:
    if len(argv) != 2 or argv[0] != "check":
        print("ERROR: usage: telegram_env.py check PATH", file=sys.stderr)
        return 2
    try:
        source_candidate = pathlib.Path(argv[1])
        if source_candidate.is_symlink():
            raise InvalidTelegramEnv("Telegram input must be a regular file, not a symlink")
        source_path = source_candidate.resolve(strict=True)
        repo_value = os.environ.get("HERMES_REPO_ROOT", "")
        if not repo_value:
            raise InvalidTelegramEnv("HERMES_REPO_ROOT is required")
        repo_path = pathlib.Path(repo_value).resolve(strict=True)
        if source_path == repo_path or repo_path in source_path.parents:
            raise InvalidTelegramEnv("Telegram input must be outside the repository")
        values = parse_source(source_path)
    except (InvalidTelegramEnv, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

Because `.generated` is inside the repository, the repository-boundary check also rejects it. Error messages must name only the violated contract, never the rejected line or value.

- [ ] **Step 4: Run focused parser and syntax checks**

Run: `python3 -m py_compile scripts/telegram_env.py && bash tests/telegram_env_test.sh`

Expected: PASS for the complete matrix, with no protected values in captured output.

- [ ] **Step 5: Review task diff; commit only if separately authorized**

Run: `git diff --check -- scripts/telegram_env.py tests/telegram_env_test.sh && git diff -- scripts/telegram_env.py tests/telegram_env_test.sh`

Expected: clean whitespace check and only the parser/test slice. If commit authorization exists, use `git add scripts/telegram_env.py tests/telegram_env_test.sh && git commit -m "Add fail-closed Telegram input parser (aimem#795)"`; otherwise leave reviewed changes uncommitted.

---

### Task 2: Installer grammar and fail-before-tools planning paths

**Files:**
- Modify: `installer/install.sh`
- Modify: `tests/installer_test.sh`
- Modify: `tests/installer_plan_test.sh`

**Interfaces:**
- Consumes: `plan|deploy telegram`, `--telegram-state enabled|disabled`, optional `--telegram-env PATH`, optional `--gateway-profile NAME`.
- Produces shell helpers `validate_gateway_profile`, `validate_telegram_input`, `validate_telegram_option_contract`, `prepare_telegram_request`, and `telegram_syntax_plan`.
- Preserves: existing `new`/`existing` command lines and outputs when no Telegram options are present.

- [ ] **Step 1: Add RED tests for argument and plan behavior**

Extend `tests/installer_test.sh` with unknown `--telegram-state`, missing targeted state, enable missing either paired option, disable receiving either option, invalid profile name, and Telegram target receiving new-host-only or provider/model options.

Extend `tests/installer_plan_test.sh` with fake `python3`, `ssh-keygen`, `ansible-playbook`, `terraform`, and `ssh` loggers. Assert:

```bash
assert_no_external_tools() {
  [[ ! -s "$terraform_log" ]] || fail "invalid Telegram input reached Terraform"
  [[ ! -s "$ansible_log" ]] || fail "invalid Telegram input reached Ansible"
  [[ ! -s "$ssh_log" ]] || fail "Telegram plan must not contact SSH"
}
```

Cover targeted enabled/disabled syntax plans, keypair mismatch before Ansible, valid/invalid protected input, `new`/`existing` optional-pair behavior, no-options backward compatibility, and prove `plan telegram` logs no Terraform/SSH/base/site playbook command.

- [ ] **Step 2: Run installer tests and verify RED**

Run: `bash tests/installer_test.sh && bash tests/installer_plan_test.sh`

Expected: FAIL because `telegram`, `--telegram-state`, `--telegram-env`, and `--gateway-profile` are unknown.

- [ ] **Step 3: Refactor request validation into external-tool-free and target-specific stages**

In `installer/install.sh`, run `validate_telegram_option_contract` immediately after argument parsing and before `validate_common_request`, inventory generation, key tooling, Terraform, or Ansible. Treat the validator's own Python process as the validation boundary; no other subprocess may run first for a Telegram-enabled request. Keep `validate_common_request` limited to `scripts/validate.sh --structure`; move CIDR requirements into `prepare_new_request`/`prepare_existing_request`. Add:

```bash
validate_gateway_profile() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9_-]*$ ]] \
    || die "--gateway-profile must be a Hermes profile name"
}

validate_telegram_input() {
  local source_file="$1"
  need_file "$source_file"
  HERMES_REPO_ROOT="$repo_root" python3 "$repo_root/scripts/telegram_env.py" check "$source_file" \
    || die "--telegram-env failed the protected Telegram input contract"
}

validate_telegram_option_contract() {
  if [[ "$telegram_state" == "enabled" ]]; then
    [[ -n "$telegram_env" ]] || die "--telegram-env is required when Telegram is enabled"
    [[ -n "$gateway_profile" ]] || die "--gateway-profile is required when Telegram is enabled"
    validate_gateway_profile "$gateway_profile"
    validate_telegram_input "$telegram_env"
  elif [[ "$telegram_state" == "disabled" ]]; then
    [[ -z "$telegram_env" ]] || die "--telegram-env must not be used when Telegram is disabled"
    [[ -z "$gateway_profile" ]] || die "--gateway-profile must not be used when Telegram is disabled"
  elif [[ -n "$telegram_env" || -n "$gateway_profile" ]]; then
    die "--telegram-env and --gateway-profile must be supplied together"
  fi
}
```

For full targets, set `telegram_state=enabled` only when the pair is supplied; otherwise leave it empty. For targeted `telegram`, require explicit enabled/disabled, validate host/user/public/private key and keypair, but do not require CIDRs/provider/model credentials.

- [ ] **Step 4: Add targeted syntax-plan dispatch without host contact**

Define `telegram_playbook="$repo_root/ansible/telegram_gateway.yml"` and:

```bash
telegram_syntax_plan() {
  need_command ansible-playbook
  local telegram_vars=(
    --extra-vars "hermes_telegram_state=$telegram_state"
    --extra-vars "hermes_telegram_env_source=$telegram_env"
    --extra-vars "hermes_gateway_profile=$gateway_profile"
  )
  ANSIBLE_CONFIG="$repo_root/ansible/ansible.cfg" \
    ansible-playbook --syntax-check --inventory "$inventory_path" \
      "$telegram_playbook" "${telegram_vars[@]}"
  printf 'Telegram Ansible syntax plan completed; no host connection was attempted.\n'
}
```

The disabled path passes empty source/profile values, never protected contents. Dispatch `plan telegram` only to this helper. Full `new`/`existing` plans pass the optional pair to the existing site syntax check so both playbook parse paths are exercised.

- [ ] **Step 5: Run focused installer checks**

Run: `bash -n installer/install.sh tests/installer_test.sh tests/installer_plan_test.sh && bash tests/installer_test.sh && bash tests/installer_plan_test.sh`

Expected: PASS; invalid protected input and mismatched keys produce empty Terraform/Ansible/SSH logs.

- [ ] **Step 6: Review task diff; commit only if separately authorized**

Run: `git diff --check -- installer/install.sh tests/installer_test.sh tests/installer_plan_test.sh && git diff -- installer/install.sh tests/installer_test.sh tests/installer_plan_test.sh`

If authorized, commit as `Add Telegram installer planning contract (aimem#795)`; otherwise leave the reviewed slice uncommitted.

---

### Task 3: Explicit Compose gateway profile and protected runtime env

**Files:**
- Modify: `docker/docker-compose.yml`
- Modify: `ansible/roles/hermes/defaults/main.yml`
- Modify: `ansible/roles/hermes/tasks/main.yml`
- Modify: `ansible/roles/hermes/handlers/main.yml`
- Create: `tests/compose_gateway_profile_test.sh`

**Interfaces:**
- Consumes: `HERMES_GATEWAY_PROFILE`, defaulting to `default`.
- Produces: Compose command `['-p', PROFILE, 'gateway', 'run']` and role list `hermes_compose_argv_prefix` that always supplies `--env-file {{ hermes_gateway_runtime_env_path }}`.
- Produces protected files `{{ hermes_app_dir }}/gateway.env`, `{{ hermes_app_dir }}/gateway-profile.pre-telegram`, and `{{ hermes_app_dir }}/gateway-profile.telegram-managed`.

- [ ] **Step 1: Write RED Compose/profile tests**

Create `tests/compose_gateway_profile_test.sh`. If Docker is runnable, render twice and inspect JSON/YAML output; otherwise use a hermetic Python YAML text assertion for the exact exec-form command. Require:

```text
default:  -p default gateway run
selected: -p manager gateway run
```

Also assert exactly one `gateway` and one `run` token, one Compose service, and no webhook/listener/port addition.

- [ ] **Step 2: Run the test and verify RED**

Run: `bash tests/compose_gateway_profile_test.sh`

Expected: FAIL because the current command is only `gateway run`.

- [ ] **Step 3: Parameterize the Compose command and centralize Compose argv**

Change `docker/docker-compose.yml` to:

```yaml
command: ["-p", "${HERMES_GATEWAY_PROFILE:-default}", "gateway", "run"]
```

Add defaults:

```yaml
hermes_gateway_profile: ""
hermes_telegram_state: ""
hermes_telegram_env_source: ""
hermes_repo_root: "{{ playbook_dir }}/.."
hermes_gateway_runtime_env_path: "{{ hermes_app_dir }}/gateway.env"
hermes_gateway_profile_backup_path: "{{ hermes_app_dir }}/gateway-profile.pre-telegram"
hermes_gateway_managed_profile_path: "{{ hermes_app_dir }}/gateway-profile.telegram-managed"
hermes_telegram_block_marker: "# {mark} HERMES MANAGED TELEGRAM"
hermes_compose_argv_prefix:
  - docker
  - compose
  - --env-file
  - "{{ hermes_gateway_runtime_env_path }}"
  - --file
  - "{{ hermes_app_dir }}/docker-compose.yml"
```

Before the first Compose invocation in the full role, create `gateway.env` as root:root mode `0600` containing `HERMES_GATEWAY_PROFILE=default` only when absent. Replace all role/handler literal Compose argv with `hermes_compose_argv_prefix + [...]` and keep `HERMES_DATA_DIR` in the task environment.

- [ ] **Step 4: Prove default compatibility and selected profile propagation**

Run: `bash tests/compose_gateway_profile_test.sh && bash tests/ansible_runtime_initialization_test.sh && bash tests/ansible_profile_reconciliation_test.sh`

Expected: PASS. Existing fake Docker expectations may need their Compose prefix updated, but Hermes CLI argv remains unchanged.

- [ ] **Step 5: Review task diff; commit only if separately authorized**

Run: `git diff --check -- docker/docker-compose.yml ansible/roles/hermes tests/compose_gateway_profile_test.sh && git diff -- docker/docker-compose.yml ansible/roles/hermes tests/compose_gateway_profile_test.sh`

If authorized, commit as `Parameterize the Hermes gateway profile (aimem#795)`.

---

### Task 4: Idempotent Ansible Telegram enable/disable state machine

**Files:**
- Create: `ansible/roles/hermes/tasks/validate_telegram.yml`
- Create: `ansible/roles/hermes/tasks/telegram_gateway.yml`
- Create: `tests/fixtures/telegram_gateway.yml`
- Create: `tests/ansible_telegram_gateway_test.sh`
- Modify: `ansible/roles/hermes/tasks/main.yml`

**Interfaces:**
- Consumes role vars `hermes_telegram_state: enabled|disabled`, `hermes_telegram_env_source`, and `hermes_gateway_profile`.
- Produces facts `hermes_telegram_values: dict[str, str]`, `hermes_telegram_profile`, `hermes_selected_profile_env_path`, and `hermes_pre_telegram_gateway_profile` under `no_log` where values are sensitive; no command emits protected values.
- Mutates only the selected profile `.env`, gateway runtime env, backup file, and the single Hermes Compose service.

- [ ] **Step 1: Write the disposable-filesystem RED test**

Create a localhost fixture playbook that overrides `hermes_app_dir`, `hermes_data_dir`, owners/groups to the current test identity, disables real restart, and includes `tasks_from: telegram_gateway` twice for idempotence. In `tests/ansible_telegram_gateway_test.sh`, provide a fake Docker that accepts only:

```text
compose --env-file ... --file ... config --quiet
compose --env-file ... --file ... up --detach --force-recreate hermes
inspect --format ... hermes
exec ... hermes hermes --profile manager config check
logs --since ... hermes
```

Assert exact marked block bytes, unrelated prefix/suffix preservation, mode 0600, retained original profile, second-run `changed=0`, selected-profile-only mutation, disable restoration/removal, missing backup failure, invalid input before Docker, and no sensitive values in Ansible output or Docker log.

- [ ] **Step 2: Run the Ansible behavior test and verify RED**

Run: `HERMES_TEST_ALLOW_UVX=1 bash tests/ansible_telegram_gateway_test.sh`

Expected: FAIL because the fixture and role tasks do not exist.

- [ ] **Step 3: Implement repeated protected validation**

In `validate_telegram.yml`, assert the state/profile contract, then invoke the shared parser on the controller:

```yaml
- name: Revalidate the protected Telegram input on the controller
  ansible.builtin.command:
    argv:
      - python3
      - "{{ hermes_repo_root }}/scripts/telegram_env.py"
      - check
      - "{{ hermes_telegram_env_source }}"
  environment:
    HERMES_REPO_ROOT: "{{ hermes_repo_root }}"
  delegate_to: localhost
  become: false
  changed_when: false
  no_log: true
  when: hermes_telegram_state == "enabled"

- name: Read validated Telegram assignments into protected memory
  ansible.builtin.set_fact:
    hermes_telegram_values: >-
      {{ dict(
        lookup('ansible.builtin.file', hermes_telegram_env_source).splitlines()
        | map('split', '=', 1)
      ) }}
  no_log: true
  when: hermes_telegram_state == "enabled"
```

Then assert the selected profile appears in `hermes_profile_names` and use only value-free `fail_msg` text. The disposable fixture overrides `hermes_repo_root` with the actual checkout root. For disabled state, reject a source/profile and do not invoke the parser; the later preflight derives `hermes_telegram_profile` from the retained managed-profile file.

- [ ] **Step 4: Implement preflight and profile preservation before mutation**

In `telegram_gateway.yml`, import validation first. Query container health, Compose definition, selected profile (`hermes_cli_argv_prefix + ['profile', 'show', hermes_gateway_profile]`), and current runtime env before any copy/block/restart task. Parse only an exact `HERMES_GATEWAY_PROFILE=<valid-name>` runtime file; treat an absent file as `default`; reject malformed/multi-key files.

For enable, write `gateway-profile.pre-telegram` only when absent, root:root mode 0600, and record the selected Telegram profile in `gateway-profile.telegram-managed` with the same ownership/mode. Never overwrite the pre-Telegram value on rerun; fail before mutation if an active managed profile differs from the newly requested profile. For disable, require and validate both files, derive `hermes_telegram_profile` from the managed-profile file, require that the current runtime profile matches it, and use the backup as the restore value. Retain both state files as rollback/read-back evidence after disable; a later enable may replace only the managed-profile file after proving the old managed block is absent and the runtime currently equals the retained pre-Telegram profile.

- [ ] **Step 5: Manage the exact Telegram block and runtime profile**

Use `ansible.builtin.blockinfile` on `{{ hermes_data_dir }}/profiles/{{ hermes_telegram_profile }}/.env` with owner/runtime group mode 0600, `create: true`, and:

```yaml
marker: "{{ hermes_telegram_block_marker }}"
block: |-
  {{ 'TELEGRAM_BOT_TOKEN' }}={{ hermes_telegram_values.TELEGRAM_BOT_TOKEN }}
  TELEGRAM_ALLOWED_USERS={{ hermes_telegram_values.TELEGRAM_ALLOWED_USERS }}
  TELEGRAM_ALLOWED_CHATS={{ hermes_telegram_values.TELEGRAM_ALLOWED_CHATS }}
  TELEGRAM_REQUIRE_MENTION=true
  TELEGRAM_EXCLUSIVE_BOT_MENTIONS=true
  TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES=false
```

Set `state: present` for enable and `state: absent` for disable. Mark every value-bearing task `no_log: true`. Render `gateway.env` atomically as root:root mode 0600 with `manager` (or selected profile) on enable and the validated backup value on disable. Flush the focused handler only after all validation and file operations succeed.

- [ ] **Step 6: Validate Compose, recreate one service, and check bounded runtime evidence**

Run `hermes_compose_argv_prefix + ['config', '--quiet']`, then `hermes_compose_argv_prefix + ['up', '--detach', '--force-recreate', hermes_container_name]`. Wait for health, run `hermes --profile PROFILE config check`, and inspect only bounded post-recreate logs for both `[Telegram] Connected to Telegram (polling mode)` and `Gateway running with 1 platform(s)` when enabled. On disable, require healthy runtime and absence of Telegram keys from the selected profile file; do not claim Telegram E2E success.

Wrap the ordered role work in one Ansible `block`/`rescue`. Set a value-free `hermes_telegram_current_phase` before each of the eight spec phases and update `hermes_telegram_last_completed_phase` only after that phase succeeds. The rescue must fail with `Telegram phase: <current>; Last completed phase: <last>` and must not print `ansible_failed_result`, parsed values, paths containing secrets, or raw command output. All mutation tasks notify/recreate only after the complete preflight block succeeds. Do not auto-disable or loop restarts on failure.

- [ ] **Step 7: Run Ansible behavior and regression tests**

Run: `HERMES_TEST_ALLOW_UVX=1 bash tests/ansible_telegram_gateway_test.sh && bash tests/ansible_directory_ownership_test.sh && bash tests/ansible_codex_auth_test.sh && bash tests/ansible_profile_reconciliation_test.sh`

Expected: PASS, including exact byte preservation outside the managed block and second-run idempotence.

- [ ] **Step 8: Review task diff; commit only if separately authorized**

Run focused `git diff --check` and `git diff` for the five task files. If authorized, commit as `Manage profile-scoped Telegram gateway state (aimem#795)`.

---

### Task 5: Targeted playbooks, deploy phases, and full-deploy reuse

**Files:**
- Create: `ansible/telegram_gateway.yml`
- Create: `ansible/telegram_verify.yml`
- Modify: `ansible/site.yml`
- Modify: `ansible/verify.yml`
- Modify: `installer/install.sh`
- Modify: `tests/installer_deploy_test.sh`
- Modify: `tests/installer_plan_test.sh`

**Interfaces:**
- Produces targeted phases `telegram-preflight`, `telegram-configure`, and `telegram-verify` using the existing `run_phase` failure report.
- Produces `run_telegram_ansible INVENTORY` and `run_telegram_verify INVENTORY` without Terraform/base/site playbook invocation.
- Full deployment imports `telegram_gateway` only when the validated optional pair is present, after provider credential synchronization.

- [ ] **Step 1: Write RED targeted deploy phase tests**

Extend the fake Ansible dispatcher to distinguish `ansible/telegram_gateway.yml`, `ansible/telegram_verify.yml`, `ansible/site.yml`, and `ansible/verify.yml`. Add enabled/disabled successes and failures in targeted configure/verify. Assert zero Terraform calls; exact two targeted Ansible calls; no site/base/root playbook path; phase/status propagation; safe-resume text; no automatic disable/cleanup; and no token/ID fragment in stdout, stderr, or command logs.

Add full `new`/`existing` cases with and without the option pair, asserting Telegram extra-vars appear only as source path/profile/state, never file contents.

- [ ] **Step 2: Run installer deploy tests and verify RED**

Run: `bash tests/installer_deploy_test.sh && bash tests/installer_plan_test.sh`

Expected: FAIL because targeted playbooks and dispatch functions do not exist.

- [ ] **Step 3: Add the targeted mutation and verification playbooks**

Create `ansible/telegram_gateway.yml` with one `hosts: hermes`, `become: true`, `gather_facts: false` play. Its pre-tasks wait for the authorized target, gather minimal facts, and assert an existing healthy Docker/Hermes installation. Its only role action is:

```yaml
- name: Apply targeted Telegram gateway state
  ansible.builtin.include_role:
    name: hermes
    tasks_from: telegram_gateway
```

Create `ansible/telegram_verify.yml` as a read-only play that derives the managed profile from the protected managed-profile state file and checks container health, exactly one gateway process matching the expected runtime profile, selected profile config, protected file modes, runtime profile selection, retained backup/managed-profile state, exact managed-block key names without returning values, and bounded polling connection markers. It must not call Telegram Bot API or send messages.

- [ ] **Step 4: Wire targeted installer deploy phases**

Add:

```bash
run_telegram_ansible() {
  ANSIBLE_CONFIG="$repo_root/ansible/ansible.cfg" \
    ansible-playbook --inventory "$inventory_path" "$telegram_playbook" \
      --extra-vars "hermes_telegram_state=$telegram_state" \
      --extra-vars "hermes_telegram_env_source=$telegram_env" \
      --extra-vars "hermes_gateway_profile=$gateway_profile"
}

run_telegram_verify() {
  ANSIBLE_CONFIG="$repo_root/ansible/ansible.cfg" \
    ansible-playbook --inventory "$inventory_path" "$telegram_verify_playbook" \
      --extra-vars "hermes_telegram_state=$telegram_state" \
      --extra-vars "hermes_gateway_profile=$gateway_profile"
}
```

Targeted deploy sets `last_completed_phase=request-validation`, reuses the prepared inventory, then calls `run_phase telegram-configure run_telegram_ansible` and `run_phase telegram-verify run_telegram_verify`. `--confirm-external-mutation` remains mandatory and is checked before either command.

- [ ] **Step 5: Integrate optional Telegram into the full role after credential synchronization**

In `ansible/site.yml`, extend preflight assertions so the optional pair/state is internally consistent. In `ansible/roles/hermes/tasks/main.yml`, include `telegram_gateway.yml` immediately after the named-profile provider `.env` synchronization and only when `hermes_telegram_state == 'enabled'`. Ensure the provider whole-file copy happens first on every idempotent run so it cannot erase the final managed Telegram block.

Pass only source paths/profile/state from installer `run_ansible`; never pass parsed Telegram values. Extend `ansible/verify.yml` to include non-secret Telegram structural/runtime assertions only when Telegram was requested.

- [ ] **Step 6: Run installer and Ansible integration checks**

Run: `bash tests/installer_plan_test.sh && bash tests/installer_deploy_test.sh && HERMES_TEST_ALLOW_UVX=1 bash tests/ansible_telegram_gateway_test.sh`

Expected: PASS for targeted enable/disable, full optional pair, phase failures, and backward compatibility.

- [ ] **Step 7: Review task diff; commit only if separately authorized**

Run focused whitespace/diff review. If authorized, commit as `Add targeted Telegram deployment workflow (aimem#795)`.

---

### Task 6: Strict validation, documentation, and source acceptance gate

**Files:**
- Modify: `scripts/validate.sh`
- Modify: `.github/workflows/validate.yml`
- Modify: `configs/hermes.env.example`
- Modify: `README.md`
- Modify: `QUICKSTART.md`
- Modify: `INSTALLATION_GUIDE.md`
- Modify: `docs/operations.md`
- Modify: `ansible/README.md`
- Modify: `tests/validate_test.sh`

**Interfaces:**
- `./scripts/validate.sh --all` remains the single strict CI gate and never applies infrastructure.
- Documentation exposes the three installer commands from the spec using placeholder paths/IDs only, plus an explicit production-authorization checklist.

- [ ] **Step 1: Write RED validation-gate tests**

Extend `tests/validate_test.sh` to remove each new required artifact in an isolated repository and require `--structure` to fail. Add assertions that strict Ansible validation names both targeted playbooks, Compose validation runs with `HERMES_GATEWAY_PROFILE=default` and `manager`, and token-shaped fixtures are allowed only under a narrowly named hermetic fixture path while populated credentials elsewhere still fail.

- [ ] **Step 2: Run validation tests and verify RED**

Run: `bash tests/validate_test.sh`

Expected: FAIL until the strict gate knows the new artifacts/playbooks/profile render.

- [ ] **Step 3: Extend strict static gates without deployment behavior**

Add new files to `require_artifacts`. Syntax-check and lint both `ansible/site.yml` and `ansible/telegram_gateway.yml`; syntax-check `ansible/telegram_verify.yml`. Run Compose config twice:

```bash
HERMES_DATA_DIR=/opt/hermes/data HERMES_GATEWAY_PROFILE=default docker compose \
  --file "$repo_root/docker/docker-compose.yml" config --quiet
HERMES_DATA_DIR=/opt/hermes/data HERMES_GATEWAY_PROFILE=manager docker compose \
  --file "$repo_root/docker/docker-compose.yml" config --quiet
```

Keep `.github/workflows/validate.yml` limited to dependency installation and `./scripts/validate.sh --all`; do not add deploy, Bot API, SSH, Terraform apply, secrets, or message steps.

- [ ] **Step 4: Update operator documentation to match implemented behavior**

Remove the Telegram comment from `configs/hermes.env.example` and document the separate six-key protected input without populated sample values. Add:

- targeted plan/enable/disable one-line invocations with placeholder paths;
- full deploy optional-pair behavior and no-options compatibility;
- `manager` as the first instance selection, not a global hard-coded default;
- one poller, privacy retained, minimum-permission group administrator, and mention/reply/command triggers;
- retained rollback file and exact disable scope;
- explicit statement that syntax/config/log status is not Telegram behavioral proof;
- the ten separately authorized production controls from the spec;
- exact boundaries still awaiting approval: host connection, credential install, recreate/restart, Bot API probes, visible messages, group admin changes, GitHub mutation.

Record the pinned upstream Telegram and release URLs already present in the spec. Do not copy real token, IDs, chat names, message text, or raw updates into documentation.

- [ ] **Step 5: Run the complete local source gate**

Run: `./scripts/validate.sh --local`

Expected: all available checks PASS and unavailable tools are explicitly `SKIP`. Record each skipped tool; do not call this readiness proof.

Then, when all strict dependencies are runnable, run: `./scripts/validate.sh --all`

Expected: PASS with Bash/ShellCheck, Terraform fmt/validate, all Ansible syntax/lint, both Compose renders, secret scan, and the complete behavioral suite. If a tool is unavailable, strict mode must fail and remain unverified.

- [ ] **Step 6: Review the complete implementation against the design**

Run:

```bash
git diff --check
rg -n 'TODO|TBD|FIXME|TELEGRAM_GROUP_ALLOWED|TELEGRAM_WEBHOOK|ALLOW_ALL|\*' \
  installer scripts ansible docker configs tests README.md QUICKSTART.md \
  INSTALLATION_GUIDE.md docs .github
git status --short
git diff --stat
git diff
```

Expected: no placeholders; every forbidden-key hit is an explicit rejection/test/documentation statement; no secret value; no unrelated file; no Terraform/base/firewall/root-credential addition; one Compose service and one gateway owner.

- [ ] **Step 7: Run hosted CI only after separate GitHub authorization**

If and only if commit/push/CI authorization is granted, commit the reviewed remaining files with `aimem#795`, push the exact reviewed commit, wait for the GitHub Actions run to finish, and inspect the terminal result. A local exit 0 does not substitute for hosted CI, and a hosted CI request does not authorize production deployment.

- [ ] **Step 8: Stop at the source/production boundary**

Report files changed, exact local/hosted results, skipped tools, remaining risks, and every pending external action. Do not connect to the host, install credentials, recreate the container, call Telegram Bot API, send messages, change group administration, or close aimem#795 without the next exact authorization and the full production evidence chain.

---

## Plan Self-Review Result

- Spec coverage: protected input, exact allowlists, selected profile, one poller, targeted/full flows, enable/disable rollback, failure reporting, hermetic tests, static/CI gates, documentation, and the separate production evidence chain all map to explicit tasks above.
- Scope: the plan remains one testable subsystem (Telegram access for the existing single Hermes runtime); production deployment is an authorization-gated execution phase, not a second implementation subsystem.
- Placeholder scan: no `TBD`, `TODO`, `FIXME`, “similar to,” or unspecified error-handling step is used as implementation content.
- Type/interface consistency: `hermes_telegram_state`, `hermes_telegram_env_source`, `hermes_gateway_profile`, `hermes_gateway_runtime_env_path`, `hermes_gateway_profile_backup_path`, and `hermes_compose_argv_prefix` retain the same names from installer through playbooks, role tasks, tests, and verification.
- Safety review: invalid protected input fails before external tools; value-bearing parser/Ansible paths are `no_log`; targeted work excludes Terraform/base/Docker/root tasks; production/GitHub actions remain explicitly unauthorized by this plan.
