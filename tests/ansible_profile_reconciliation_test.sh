#!/usr/bin/env bash

set -euo pipefail
# shellcheck source=tests/test_helper.sh
source "$(dirname "${BASH_SOURCE[0]}")/test_helper.sh"

ansible_command=()
if ansible-playbook --version >/dev/null 2>&1; then
  ansible_command=(ansible-playbook)
elif [[ "${HERMES_TEST_ALLOW_UVX:-0}" == "1" ]] \
  && command -v uvx >/dev/null 2>&1 \
  && command -v python3.13 >/dev/null 2>&1; then
  uv_python="$(command -v python3.13)"
  ansible_command=(
    uvx --python "$uv_python"
    --from 'ansible-core>=2.18,<2.20' ansible-playbook
  )
else
  printf 'SKIP profile reconciliation behavior (runnable ansible-playbook unavailable)\n'
  exit 0
fi

fixture_root="$(mktemp -d)"
trap 'rm -rf "$fixture_root"' EXIT
fake_bin="$fixture_root/bin"
state_dir="$fixture_root/state"
command_log="$fixture_root/hermes.log"
mkdir -p "$fake_bin" "$state_dir/profiles" "$state_dir/config"

cat >"$fake_bin/docker" <<'FAKE'
#!/usr/bin/env bash

set -euo pipefail
printf '%s\n' "$*" >>"$HERMES_COMMAND_LOG"

if [[ "${1:-}" == "compose" ]]; then
  exit 0
fi

[[ "${1:-}" == "exec" ]] || exit 90
shift
[[ "${1:-}" == "--user" && "${2:-}" == "10000:10000" ]] || exit 94
shift 2
[[ "${1:-}" == "--env" && "${2:-}" == "HOME=/opt/data" ]] || exit 95
shift 2
[[ "${1:-}" == "--env" && "${2:-}" == "CODEX_HOME=/opt/data/.codex" ]] || exit 96
shift 2
[[ "${1:-}" == "hermes" ]] || exit 97
shift
[[ "${1:-}" == "hermes" ]] || exit 91
shift

if [[ "${1:-}" == "profile" ]]; then
  action="${2:-}"
  profile="${3:-}"
  case "$action" in
    show)
      if [[ "${FAIL_PROFILE_SHOW:-}" == "$profile" ]]; then
        printf 'fixture profile query failed unexpectedly\n' >&2
        exit 19
      fi
      if [[ "${NEAR_MISS_PROFILE_SHOW:-}" == "$profile" ]]; then
        printf "Error: Profile '%s' does not exist.\n" "$profile"
        printf 'fixture additional profile error\n'
        exit 1
      fi
      if [[ -f "$FAKE_HERMES_STATE_DIR/profiles/$profile" ]]; then
        printf 'Profile: %s\n' "$profile"
        exit 0
      fi
      printf "Error: Profile '%s' does not exist.\n" "$profile"
      exit 1
      ;;
    create)
      mkdir -p "$FAKE_HERMES_STATE_DIR/config/$profile"
      : >"$FAKE_HERMES_STATE_DIR/profiles/$profile"
      exit 0
      ;;
  esac
fi

if [[ "${1:-}" == "--profile" ]]; then
  profile="${2:-}"
  [[ "${3:-}" == "config" ]] || exit 92
  action="${4:-}"
  key="${5:-}"
  value_path="$FAKE_HERMES_STATE_DIR/config/$profile/$key"
  case "$action" in
    get)
      if [[ "${FAIL_CONFIG_GET:-}" == "$profile:$key" ]]; then
        printf 'fixture config query failed unexpectedly\n' >&2
        exit 23
      fi
      if [[ "${NEAR_MISS_CONFIG_GET:-}" == "$profile:$key" ]]; then
        printf 'Config key not set: %s\n' "$key" >&2
        printf 'fixture additional config error\n' >&2
        exit 1
      fi
      if [[ -f "$value_path" ]]; then
        command cat "$value_path"
        exit 0
      fi
      printf 'Config key not set: %s\n' "$key" >&2
      exit 1
      ;;
    set)
      mkdir -p "$(dirname "$value_path")"
      printf '%s\n' "${6:-}" >"$value_path"
      exit 0
      ;;
  esac
fi

exit 93
FAKE
chmod +x "$fake_bin/docker"

write_config() {
  local profile="$1"
  local key="$2"
  local value="$3"
  mkdir -p "$state_dir/config/$profile"
  printf '%s\n' "$value" >"$state_dir/config/$profile/$key"
}

for profile in default manager coding research; do
  : >"$state_dir/profiles/$profile"
  write_config "$profile" model.provider openrouter
  write_config "$profile" model.default test/model
  if [[ "$profile" != "coding" ]]; then
    write_config "$profile" tool_loop_guardrails.hard_stop_enabled true
  fi
done
write_config manager model.default old/model

run_reconciliation() {
  local output_path="$1"
  shift
  env PATH="$fake_bin:$PATH" \
    ANSIBLE_ROLES_PATH="$repo_root/ansible/roles" \
    FAKE_HERMES_STATE_DIR="$state_dir" HERMES_COMMAND_LOG="$command_log" \
    "$@" "${ansible_command[@]}" \
      --inventory localhost, "$repo_root/tests/fixtures/profile_reconciliation.yml" \
      >"$output_path" 2>&1
}

count_commands() {
  local pattern="$1"
  grep -c -- "$pattern" "$command_log" || true
}

: >"$command_log"
if ! run_reconciliation "$fixture_root/first.out" env; then
  rg -m1 'Could not find|FAILED!' "$fixture_root/first.out" >&2 || true
  fail "initial profile reconciliation run must succeed"
fi

if grep '^exec ' "$command_log" \
    | grep -qv '^exec --user 10000:10000 --env HOME=/opt/data --env CODEX_HOME=/opt/data/.codex hermes hermes '; then
  fail "every Hermes CLI invocation must use the runtime identity and Codex home"
fi

[[ "$(count_commands 'hermes profile show ')" -eq 4 ]] \
  || fail "reconciliation must query every named profile through Hermes CLI"
[[ "$(count_commands 'hermes profile create ')" -eq 1 ]] \
  || fail "reconciliation must create only the missing profile"
grep -q 'hermes profile create devops ' "$command_log" \
  || fail "reconciliation must create the missing devops profile"
[[ "$(count_commands ' config get ')" -eq 20 ]] \
  || fail "reconciliation must read the desired matrix for all profiles"
[[ "$(count_commands ' config set ')" -eq 10 ]] \
  || fail "reconciliation must write only missing or changed values"
for profile in default manager devops coding research; do
  [[ "$(<"$state_dir/config/$profile/stt.language")" == "ru" ]] \
    || fail "reconciliation must set Russian STT for $profile"
done
printf 'PASS profile reconciliation uses canonical state and one desired matrix\n'

: >"$command_log"
if ! run_reconciliation "$fixture_root/second.out" env; then
  rg -m1 'Could not find|FAILED!' "$fixture_root/second.out" >&2 || true
  fail "second profile reconciliation run must succeed"
fi

[[ "$(count_commands 'hermes profile create ')" -eq 0 ]] \
  || fail "second reconciliation must not recreate profiles"
[[ "$(count_commands ' config get ')" -eq 20 ]] \
  || fail "second reconciliation must still verify every desired value"
[[ "$(count_commands ' config set ')" -eq 0 ]] \
  || fail "second reconciliation must be idempotent"
printf 'PASS profile reconciliation is idempotent\n'

: >"$command_log"
set +e
run_reconciliation "$fixture_root/profile-error.out" \
  env FAIL_PROFILE_SHOW=research
status=$?
set -e

[[ "$status" -ne 0 ]] || fail "unexpected profile query errors must fail reconciliation"
[[ "$(count_commands 'hermes profile create ')" -eq 0 ]] \
  || fail "unexpected profile query errors must stop before creation"
[[ "$(count_commands ' config get ')" -eq 0 ]] \
  || fail "unexpected profile query errors must stop before config reads"
printf 'PASS unexpected profile query errors fail closed\n'

: >"$command_log"
set +e
run_reconciliation "$fixture_root/profile-near-miss.out" \
  env NEAR_MISS_PROFILE_SHOW=research
status=$?
set -e

[[ "$status" -ne 0 ]] || fail "profile absence output must match exactly"
[[ "$(count_commands 'hermes profile create ')" -eq 0 ]] \
  || fail "profile absence near-misses must stop before creation"
[[ "$(count_commands ' config get ')" -eq 0 ]] \
  || fail "profile absence near-misses must stop before config reads"
printf 'PASS profile absence near-misses fail closed\n'

: >"$command_log"
set +e
run_reconciliation "$fixture_root/config-error.out" \
  env FAIL_CONFIG_GET=research:model.default
status=$?
set -e

[[ "$status" -ne 0 ]] || fail "unexpected config query errors must fail reconciliation"
[[ "$(count_commands ' config set ')" -eq 0 ]] \
  || fail "unexpected config query errors must stop before config writes"
printf 'PASS unexpected config query errors fail closed\n'

: >"$command_log"
set +e
run_reconciliation "$fixture_root/config-near-miss.out" \
  env NEAR_MISS_CONFIG_GET=research:model.default
status=$?
set -e

[[ "$status" -ne 0 ]] || fail "config absence output must match exactly"
[[ "$(count_commands ' config set ')" -eq 0 ]] \
  || fail "config absence near-misses must stop before config writes"
printf 'PASS config absence near-misses fail closed\n'
