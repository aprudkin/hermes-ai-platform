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
  printf 'SKIP Telegram gateway behavior (runnable ansible-playbook unavailable)\n'
  exit 0
fi

fixture_root="$(mktemp -d)"
case "$fixture_root" in
  /tmp/* | /private/tmp/* | /var/folders/*) ;;
  *) fail "unexpected temporary test root" ;;
esac
trap 'if [[ "${HERMES_TEST_KEEP_FIXTURE:-0}" == "1" ]]; then printf "KEPT: %s\n" "$fixture_root" >&2; else rm -rf "$fixture_root"; fi' EXIT

fake_bin="$fixture_root/bin"
app_dir="$fixture_root/app"
data_dir="$fixture_root/data"
command_log="$fixture_root/docker.log"
telegram_source="$fixture_root/telegram.env"
compose_source="$fixture_root/docker-compose.source.yml"
test_identity="$(id -un)"
test_group="$(id -gn)"
mkdir -p "$fake_bin"

cat >"$fake_bin/docker" <<'FAKE'
#!/usr/bin/env bash

set -euo pipefail
printf '%s\n' "$*" >>"$HERMES_COMMAND_LOG"

if [[ "${1:-}" == "compose" ]]; then
  telegram_env_count=0
  for variable_name in TELEGRAM_BOT_TOKEN TELEGRAM_ALLOWED_USERS TELEGRAM_ALLOWED_CHATS TELEGRAM_REQUIRE_MENTION TELEGRAM_EXCLUSIVE_BOT_MENTIONS TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES; do
    if printenv "$variable_name" >/dev/null 2>&1 && [[ -n "$(printenv "$variable_name")" ]]; then
      telegram_env_count=$((telegram_env_count + 1))
    fi
  done
  printf 'telegram-env-count=%s\n' "$telegram_env_count" >>"$HERMES_COMMAND_LOG"
  expected_prefix="compose --env-file $HERMES_FAKE_APP_DIR/gateway.env --file $HERMES_FAKE_APP_DIR/docker-compose.yml"
  if [[ "$*" == "$expected_prefix config --quiet" ]]; then
    [[ -f "$HERMES_FAKE_APP_DIR/gateway.env" ]] || exit 40
    [[ "${FAIL_COMPOSE_CONFIG:-0}" != "1" ]] || exit 41
    config_count="$(grep -Fxc -- "$expected_prefix config --quiet" "$HERMES_COMMAND_LOG")"
    if [[ "${FAIL_RENDER_COMPOSE:-0}" == "1" && "$config_count" -ge 2 ]]; then
      exit 42
    fi
    exit 0
  fi
  if [[ "$*" == "compose --env-file /dev/null --file $HERMES_FAKE_APP_DIR/docker-compose.yml config --quiet" ]]; then
    [[ "${FAIL_COMPOSE_CONFIG:-0}" != "1" ]] || exit 41
    exit 0
  fi
  if [[ "$*" == "$expected_prefix up --detach --force-recreate hermes" ]]; then
    [[ "${FAIL_COMPOSE_UP:-0}" != "1" ]] || exit 43
    exit 0
  fi
  exit 90
fi

if [[ "${1:-}" == "inspect" ]]; then
  [[ "$*" == 'inspect --format {{.State.Health.Status}} hermes' ]] || exit 91
  inspect_count="$(grep -Fxc -- 'inspect --format {{.State.Health.Status}} hermes' "$HERMES_COMMAND_LOG")"
  if [[ "${RECOVERY_UNHEALTHY_ON_FIRST:-0}" == "1" && "$inspect_count" -eq 1 ]]; then
    printf 'unhealthy\n'
  elif [[ "${FAIL_CONTAINER_HEALTH:-0}" == "1" ]]; then
    printf 'unhealthy\n'
  else
    starting_checks="${STARTING_HEALTH_CHECKS:-0}"
    if [[ "$inspect_count" -ge 2 && "$inspect_count" -le $((starting_checks + 1)) ]]; then
      printf 'starting\n'
    else
      printf 'healthy\n'
    fi
  fi
  exit 0
fi

if [[ "${1:-}" == "logs" ]]; then
  [[ "$*" == 'logs --since 2m hermes' ]] || exit 92
  if [[ "${OMIT_TELEGRAM_MARKERS:-0}" != "1" ]]; then
    printf '[Telegram] Connected to Telegram (polling mode)\n'
    printf 'Gateway running with 1 platform(s)\n'
  fi
  exit 0
fi

[[ "${1:-}" == "exec" ]] || exit 93
shift
[[ "${1:-}" == "--user" && "${2:-}" == "$HERMES_FAKE_IDENTITY:$HERMES_FAKE_GROUP" ]] || exit 94
shift 2
[[ "${1:-}" == "--env" && "${2:-}" == 'HOME=/opt/data' ]] || exit 95
shift 2
[[ "${1:-}" == "--env" && "${2:-}" == 'CODEX_HOME=/opt/data/.codex' ]] || exit 96
shift 2
[[ "${1:-}" == "hermes" && "${2:-}" == "hermes" ]] || exit 97
shift 2

if [[ "${1:-}" == "gateway" && "${2:-}" == "stop" && "${3:-}" == "--all" && "$#" -eq 3 ]]; then
  exit 0
fi

if [[ "${1:-}" == "--profile" && "${3:-}" == "gateway" && "${4:-}" == "start" && "$#" -eq 4 ]]; then
  [[ "${2:-}" == "default" || "${2:-}" == "manager" || "${2:-}" == "devops" ]] || exit 103
  exit 0
fi

if [[ "${1:-}" == "profile" && "${2:-}" == "show" ]]; then
  [[ "${3:-}" == "manager" || "${3:-}" == "devops" ]] || exit 98
  if [[ "${FAIL_PROFILE_SHOW_WITH_PENDING:-0}" == "1" && -e "$HERMES_FAKE_APP_DIR/telegram-reconciliation.pending" ]]; then
    exit 102
  fi
  printf 'Profile: %s\n' "$3"
  exit 0
fi

if [[ "${1:-}" == "--profile" ]]; then
  [[ "${2:-}" == "default" || "${2:-}" == "manager" || "${2:-}" == "devops" ]] || exit 99
  [[ "${3:-}" == "config" && "${4:-}" == "check" && "$#" -eq 4 ]] || exit 100
  printf 'Configuration valid\n'
  exit 0
fi

exit 101
FAKE
chmod +x "$fake_bin/docker"

write_valid_source() {
  {
    printf 'TELEGRAM_BOT_TOKEN=%s:%s\n' '24681012' 'fixture_secret_abcdefghijklmnop'
    printf 'TELEGRAM_ALLOWED_USERS=10101,20202\n'
    printf 'TELEGRAM_ALLOWED_CHATS=-100001,-100002\n'
    printf 'TELEGRAM_REQUIRE_MENTION=true\n'
    printf 'TELEGRAM_EXCLUSIVE_BOT_MENTIONS=true\n'
    printf 'TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES=false\n'
  } >"$telegram_source"
  chmod 600 "$telegram_source"
}

write_rotated_source() {
  {
    printf 'TELEGRAM_BOT_TOKEN=%s:%s\n' '24681012' 'rotated_secret_qrstuvwxyzabcdef'
    printf 'TELEGRAM_ALLOWED_USERS=30303,40404\n'
    printf 'TELEGRAM_ALLOWED_CHATS=-100003,-100004\n'
    printf 'TELEGRAM_REQUIRE_MENTION=true\n'
    printf 'TELEGRAM_EXCLUSIVE_BOT_MENTIONS=true\n'
    printf 'TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES=false\n'
  } >"$telegram_source"
  chmod 600 "$telegram_source"
}

reset_fixture() {
  case "$app_dir:$data_dir" in
    "$fixture_root"/*:"$fixture_root"/*) ;;
    *) fail "fixture paths escaped the disposable root" ;;
  esac
  rm -rf "$app_dir" "$data_dir"
  mkdir -p "$app_dir" "$data_dir/profiles/manager" "$data_dir/profiles/devops"
  printf 'services: {}\n' >"$app_dir/docker-compose.yml"
  printf 'services:\n  hermes: {}\n' >"$compose_source"
  printf 'HERMES_GATEWAY_PROFILE=default\n' >"$app_dir/gateway.env"
  chmod 600 "$app_dir/gateway.env"
  printf 'PROVIDER_KEY=preserve-manager\nCUSTOM_FLAG=manager-tail\n' \
    >"$data_dir/profiles/manager/.env"
  printf 'PROVIDER_KEY=preserve-devops\nCUSTOM_FLAG=devops-tail\n' \
    >"$data_dir/profiles/devops/.env"
  chmod 600 "$data_dir/profiles/manager/.env" "$data_dir/profiles/devops/.env"
  write_valid_source
  : >"$command_log"
}

run_gateway() {
  local output_path="$1"
  local requested_state="$2"
  local requested_source="$3"
  local requested_profile="$4"
  shift 4

  env PATH="$fake_bin:$PATH" \
    ANSIBLE_ROLES_PATH="$repo_root/ansible/roles" \
    HERMES_REPO_ROOT="$repo_root" \
    HERMES_FAKE_COMPOSE_SOURCE="$compose_source" \
    HERMES_FAKE_APP_DIR="$app_dir" \
    HERMES_FAKE_DATA_DIR="$data_dir" \
    HERMES_FAKE_IDENTITY="$test_identity" \
    HERMES_FAKE_GROUP="$test_group" \
    HERMES_COMMAND_LOG="$command_log" \
    HERMES_TELEGRAM_STATE="$requested_state" \
    HERMES_TELEGRAM_ENV_SOURCE="$requested_source" \
    HERMES_GATEWAY_PROFILE="$requested_profile" \
    "$@" "${ansible_command[@]}" \
      --inventory localhost, "$repo_root/tests/fixtures/telegram_gateway.yml" \
      >"$output_path" 2>&1
}

count_command() {
  local literal="$1"
  grep -Fxc -- "$literal" "$command_log" || true
}

file_mode() {
  local target_path="$1"
  if stat -f '%Lp' "$target_path" >/dev/null 2>&1; then
    stat -f '%Lp' "$target_path"
  else
    stat -c '%a' "$target_path"
  fi
}

assert_no_protected_output() {
  local output_path="$1"
  ! grep -q 'fixture_secret_abcdefghijklmnop\|10101,20202\|-100001,-100002' \
    "$output_path" "$command_log" \
    || fail "protected Telegram values escaped into command or Ansible output"
}

run_starting_health_control() {
  reset_fixture
  if ! run_gateway "$fixture_root/starting-health.out" enabled "$telegram_source" manager \
    env STARTING_HEALTH_CHECKS=4; then
    fail "bounded health wait must survive four starting observations"
  fi
  [[ "$(count_command 'inspect --format {{.State.Health.Status}} hermes')" -ge 8 ]] \
    || fail "bounded health wait must continue until the fifth post-recreate probe"
  assert_no_protected_output "$fixture_root/starting-health.out"
  printf 'PASS bounded health wait reaches healthy after four starting observations\n'
}

prepare_active_disable_state() {
  printf 'default\n' >"$app_dir/gateway-profile.pre-telegram"
  printf 'manager\n' >"$app_dir/gateway-profile.telegram-managed"
  printf 'HERMES_GATEWAY_PROFILE=manager\n' >"$app_dir/gateway.env"
  chmod 600 "$app_dir/gateway-profile.pre-telegram" \
    "$app_dir/gateway-profile.telegram-managed" "$app_dir/gateway.env"
}

write_valid_managed_profile_block() {
  local profile_path="$1"
  local original_path="$fixture_root/original-profile-bytes"

  cp "$profile_path" "$original_path"
  {
    printf '# BEGIN HERMES MANAGED TELEGRAM\n'
    printf 'TELEGRAM_BOT_TOKEN=%s:%s\n' '24681012' 'fixture_secret_abcdefghijklmnop'
    printf 'TELEGRAM_ALLOWED_USERS=10101,20202\n'
    printf 'TELEGRAM_ALLOWED_CHATS=-100001,-100002\n'
    printf 'TELEGRAM_REQUIRE_MENTION=true\n'
    printf 'TELEGRAM_EXCLUSIVE_BOT_MENTIONS=true\n'
    printf 'TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES=false\n'
    printf '# END HERMES MANAGED TELEGRAM\n'
    command cat "$original_path"
  } >"$profile_path"
  chmod 600 "$profile_path"
}

prepare_interrupted_enable() {
  local boundary="$1"

  printf 'pending\n' >"$app_dir/telegram-reconciliation.pending"
  chmod 600 "$app_dir/telegram-reconciliation.pending"
  case "$boundary" in
    pending-only) ;;
    backup-only)
      printf 'default\n' >"$app_dir/gateway-profile.pre-telegram"
      chmod 600 "$app_dir/gateway-profile.pre-telegram"
      ;;
    managed-only)
      printf 'manager\n' >"$app_dir/gateway-profile.telegram-managed"
      chmod 600 "$app_dir/gateway-profile.telegram-managed"
      ;;
    both-state-no-block)
      printf 'default\n' >"$app_dir/gateway-profile.pre-telegram"
      printf 'manager\n' >"$app_dir/gateway-profile.telegram-managed"
      chmod 600 "$app_dir/gateway-profile.pre-telegram" \
        "$app_dir/gateway-profile.telegram-managed"
      ;;
    block-written-runtime-pre | runtime-written)
      printf 'default\n' >"$app_dir/gateway-profile.pre-telegram"
      printf 'manager\n' >"$app_dir/gateway-profile.telegram-managed"
      chmod 600 "$app_dir/gateway-profile.pre-telegram" \
        "$app_dir/gateway-profile.telegram-managed"
      write_valid_managed_profile_block "$data_dir/profiles/manager/.env"
      if [[ "$boundary" == "runtime-written" ]]; then
        printf 'HERMES_GATEWAY_PROFILE=manager\n' >"$app_dir/gateway.env"
        chmod 600 "$app_dir/gateway.env"
      fi
      ;;
    *) fail "unknown interrupted enable boundary: $boundary" ;;
  esac
}

run_final_retry_controls() {
  local boundary output_path

  for boundary in block-written-runtime-pre pending-only backup-only managed-only \
    both-state-no-block runtime-written; do
    reset_fixture
    prepare_interrupted_enable "$boundary"
    output_path="$fixture_root/final-retry-$boundary.out"
    if ! run_gateway "$output_path" enabled "$telegram_source" manager; then
      tail -60 "$output_path" >&2 || true
      fail "$boundary interrupted enable must resume"
    fi
    [[ "$(count_command "compose --env-file $app_dir/gateway.env --file $app_dir/docker-compose.yml up --detach --force-recreate hermes")" == "1" ]] \
      || fail "$boundary retry must force exactly one recreation"
    [[ ! -e "$app_dir/telegram-reconciliation.pending" ]] \
      || fail "$boundary retry must clear pending reconciliation after verification"
    cmp -s <(printf 'default\n') "$app_dir/gateway-profile.pre-telegram" \
      || fail "$boundary retry must retain the pre-Telegram profile"
    cmp -s <(printf 'manager\n') "$app_dir/gateway-profile.telegram-managed" \
      || fail "$boundary retry must retain the managed profile"
    cmp -s <(printf 'HERMES_GATEWAY_PROFILE=manager\n') "$app_dir/gateway.env" \
      || fail "$boundary retry must select the managed runtime profile"
    [[ "$(grep -Fxc '# BEGIN HERMES MANAGED TELEGRAM' "$data_dir/profiles/manager/.env")" == "1" ]] \
      || fail "$boundary retry must converge to one managed block"
    assert_no_protected_output "$output_path"
  done

  for boundary in backup-only managed-only; do
    reset_fixture
    if [[ "$boundary" == "backup-only" ]]; then
      printf 'default\n' >"$app_dir/gateway-profile.pre-telegram"
      chmod 600 "$app_dir/gateway-profile.pre-telegram"
    else
      printf 'manager\n' >"$app_dir/gateway-profile.telegram-managed"
      chmod 600 "$app_dir/gateway-profile.telegram-managed"
    fi
    cp "$data_dir/profiles/manager/.env" "$fixture_root/$boundary.profile.before"
    cp "$app_dir/gateway.env" "$fixture_root/$boundary.runtime.before"
    : >"$command_log"
    if run_gateway "$fixture_root/final-retry-$boundary-without-pending.out" \
      enabled "$telegram_source" manager; then
      fail "$boundary state without a pending marker must fail closed"
    fi
    [[ ! -s "$command_log" ]] || fail "$boundary state without pending must fail before Docker"
    cmp -s "$fixture_root/$boundary.profile.before" "$data_dir/profiles/manager/.env" \
      || fail "$boundary state without pending must not mutate the profile"
    cmp -s "$fixture_root/$boundary.runtime.before" "$app_dir/gateway.env" \
      || fail "$boundary state without pending must not mutate runtime selection"
  done
  printf 'PASS pending enable interruptions resume and one-sided unmarked state fails closed\n'
}

run_final_byte_controls() {
  local layout before_path enable_output disable_output

  for layout in missing-terminal-newline prefix-only prefix-middle prefix-middle-suffix; do
    reset_fixture
    case "$layout" in
      missing-terminal-newline)
        printf 'PREFIX=one\nMIDDLE=two\nSUFFIX=three' >"$data_dir/profiles/manager/.env"
        ;;
      prefix-only)
        printf 'PREFIX=one\n' >"$data_dir/profiles/manager/.env"
        ;;
      prefix-middle)
        printf 'PREFIX=one\nMIDDLE=two\n' >"$data_dir/profiles/manager/.env"
        ;;
      prefix-middle-suffix)
        printf 'PREFIX=one\nMIDDLE=two\nSUFFIX=three\n' >"$data_dir/profiles/manager/.env"
        ;;
    esac
    chmod 600 "$data_dir/profiles/manager/.env"
    before_path="$fixture_root/final-bytes-$layout.before"
    enable_output="$fixture_root/final-bytes-$layout-enable.out"
    disable_output="$fixture_root/final-bytes-$layout-disable.out"
    cp "$data_dir/profiles/manager/.env" "$before_path"
    run_gateway "$enable_output" enabled "$telegram_source" manager \
      || fail "$layout enable must succeed"
    run_gateway "$disable_output" disabled '' '' \
      || fail "$layout disable must succeed"
    cmp -s "$before_path" "$data_dir/profiles/manager/.env" \
      || fail "$layout original profile bytes must survive enable then disable"
    [[ "$(file_mode "$data_dir/profiles/manager/.env")" == "600" ]] \
      || fail "$layout restored profile must remain mode 0600"
    assert_no_protected_output "$enable_output"
    assert_no_protected_output "$disable_output"
  done
  printf 'PASS prefix, middle, suffix, and missing-newline profile bytes are exact\n'
}

assert_round2_invalid_structure() {
  local requested_state="$1"
  local case_name="$2"
  local profile_before="$fixture_root/$case_name.profile.before"
  local runtime_before="$fixture_root/$case_name.runtime.before"
  local output_path="$fixture_root/$case_name.out"
  local structure_rc

  cp "$data_dir/profiles/manager/.env" "$profile_before"
  cp "$app_dir/gateway.env" "$runtime_before"
  : >"$command_log"
  set +e
  if [[ "$requested_state" == "enabled" ]]; then
    run_gateway "$output_path" enabled "$telegram_source" manager
  else
    run_gateway "$output_path" disabled '' ''
  fi
  structure_rc=$?
  set -e

  [[ "$structure_rc" -ne 0 ]] || fail "$case_name must fail preflight"
  [[ ! -s "$command_log" ]] || fail "$case_name must fail before Docker"
  cmp -s "$profile_before" "$data_dir/profiles/manager/.env" \
    || fail "$case_name must fail before profile mutation"
  cmp -s "$runtime_before" "$app_dir/gateway.env" \
    || fail "$case_name must fail before runtime mutation"
  [[ ! -e "$app_dir/telegram-reconciliation.pending" ]] \
    || fail "$case_name must fail before pending reconciliation"
  assert_no_protected_output "$output_path"
}

run_round2_structure_controls() {
  reset_fixture
  printf '# BEGIN HERMES MANAGED TELEGRAM stale\n' \
    >>"$data_dir/profiles/manager/.env"
  assert_round2_invalid_structure enabled suffixed-begin-enable
  printf 'PASS suffixed BEGIN marker fails enable before Docker or mutation\n'

  reset_fixture
  prepare_active_disable_state
  printf '# END HERMES MANAGED TELEGRAM stale\n' \
    >>"$data_dir/profiles/manager/.env"
  assert_round2_invalid_structure disabled suffixed-end-disable
  printf 'PASS suffixed END marker fails disable before Docker or mutation\n'

  reset_fixture
  printf '  TELEGRAM_ALLOWED_USERS=90909\n' \
    >>"$data_dir/profiles/manager/.env"
  assert_round2_invalid_structure enabled whitespace-assignment-enable
  printf 'PASS whitespace Telegram assignment fails enable before mutation\n'

  reset_fixture
  prepare_active_disable_state
  printf '  export TELEGRAM_ALLOWED_USERS=90909\n' \
    >>"$data_dir/profiles/manager/.env"
  assert_round2_invalid_structure disabled export-assignment-disable
  printf 'PASS whitespace export Telegram assignment fails disable before mutation\n'
}

if [[ "${HERMES_TEST_CASE:-}" == "starting-health" ]]; then
  run_starting_health_control
  exit 0
fi

if [[ "${HERMES_TEST_CASE:-}" == "round2-structure" ]]; then
  run_round2_structure_controls
  exit 0
fi

if [[ "${HERMES_TEST_CASE:-}" == "final-retry" ]]; then
  run_final_retry_controls
  exit 0
fi

if [[ "${HERMES_TEST_CASE:-}" == "final-bytes" ]]; then
  run_final_byte_controls
  exit 0
fi

reset_fixture
if ! run_gateway "$fixture_root/enable.out" enabled "$telegram_source" manager; then
  tail -80 "$fixture_root/enable.out" >&2 || true
  fail "Telegram enable must succeed"
fi

cat >"$fixture_root/manager.expected" <<'EXPECTED'
# BEGIN HERMES MANAGED TELEGRAM
TELEGRAM_BOT_TOKEN=24681012:fixture_secret_abcdefghijklmnop
TELEGRAM_ALLOWED_USERS=10101,20202
TELEGRAM_ALLOWED_CHATS=-100001,-100002
TELEGRAM_REQUIRE_MENTION=true
TELEGRAM_EXCLUSIVE_BOT_MENTIONS=true
TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES=false
# END HERMES MANAGED TELEGRAM
PROVIDER_KEY=preserve-manager
CUSTOM_FLAG=manager-tail
EXPECTED
cmp -s "$fixture_root/manager.expected" "$data_dir/profiles/manager/.env" \
  || fail "enable must produce the exact managed Telegram block bytes"
cmp -s <(printf 'PROVIDER_KEY=preserve-devops\nCUSTOM_FLAG=devops-tail\n') \
  "$data_dir/profiles/devops/.env" \
  || fail "enable must mutate only the selected profile"
[[ "$(file_mode "$data_dir/profiles/manager/.env")" == "600" ]] \
  || fail "selected profile environment must remain mode 0600"
[[ "$(file_mode "$app_dir/gateway.env")" == "600" ]] \
  || fail "gateway runtime environment must be mode 0600"
[[ "$(file_mode "$app_dir/gateway-profile.pre-telegram")" == "600" ]] \
  || fail "pre-Telegram profile state must be mode 0600"
[[ "$(file_mode "$app_dir/gateway-profile.telegram-managed")" == "600" ]] \
  || fail "managed Telegram profile state must be mode 0600"
cmp -s <(printf 'default\n') "$app_dir/gateway-profile.pre-telegram" \
  || fail "enable must retain the original runtime profile once"
cmp -s <(printf 'manager\n') "$app_dir/gateway-profile.telegram-managed" \
  || fail "enable must retain the Telegram-managed profile"
cmp -s <(printf 'HERMES_GATEWAY_PROFILE=manager\n') "$app_dir/gateway.env" \
  || fail "enable must select the requested gateway profile"
cmp -s "$compose_source" "$app_dir/docker-compose.yml" \
  || fail "targeted enable must synchronize the reviewed Compose definition"
[[ "$(count_command "compose --env-file $app_dir/gateway.env --file $app_dir/docker-compose.yml up --detach --force-recreate hermes")" -eq 1 ]] \
  || fail "two enable includes must recreate exactly one Hermes service once"
grep -Fqx 'telegram-env-count=6' "$command_log" \
  || fail "enable must pass all six selected Telegram variables to Compose"
[[ "$(count_command "exec --user $test_identity:$test_group --env HOME=/opt/data --env CODEX_HOME=/opt/data/.codex hermes hermes gateway stop --all")" -eq 1 ]] \
  || fail "enable must stop every prior supervised gateway before recreation"
[[ "$(count_command "exec --user $test_identity:$test_group --env HOME=/opt/data --env CODEX_HOME=/opt/data/.codex hermes hermes --profile manager gateway start")" -eq 1 ]] \
  || fail "enable must select only the requested supervised gateway"
assert_no_protected_output "$fixture_root/enable.out"
printf 'PASS Telegram enable is profile-scoped, exact, protected, and idempotent\n'

: >"$command_log"
if ! run_gateway "$fixture_root/enable-again.out" enabled "$telegram_source" manager \
  env OMIT_TELEGRAM_MARKERS=1; then
  fail "a later Telegram enable run must succeed"
fi
grep -Eq 'changed=0[[:space:]]' "$fixture_root/enable-again.out" \
  || fail "a fully converged enable run must report changed=0"
[[ "$(count_command "compose --env-file $app_dir/gateway.env --file $app_dir/docker-compose.yml up --detach --force-recreate hermes")" -eq 0 ]] \
  || fail "a converged enable must not recreate Hermes"
[[ "$(count_command 'logs --since 2m hermes')" -eq 0 ]] \
  || fail "a converged enable must not require fresh startup log markers"
assert_no_protected_output "$fixture_root/enable-again.out"
printf 'PASS repeated Telegram enable reports changed=0 without recreation\n'

write_rotated_source
: >"$command_log"
if ! run_gateway "$fixture_root/rotate-values.out" enabled "$telegram_source" manager; then
  fail "protected Telegram value rotation must succeed"
fi
grep -q '^TELEGRAM_BOT_TOKEN=24681012:rotated_secret_qrstuvwxyzabcdef$' \
  "$data_dir/profiles/manager/.env" \
  || fail "protected Telegram value rotation must update the managed block"
[[ "$(count_command "compose --env-file $app_dir/gateway.env --file $app_dir/docker-compose.yml up --detach --force-recreate hermes")" -eq 1 ]] \
  || fail "protected Telegram value rotation must recreate Hermes exactly once"
! grep -q 'rotated_secret_qrstuvwxyzabcdef\|30303,40404\|-100003,-100004' \
  "$fixture_root/rotate-values.out" "$command_log" \
  || fail "rotated protected values must not escape into output"
printf 'PASS protected Telegram value rotation recreates Hermes exactly once\n'

: >"$command_log"
if ! run_gateway "$fixture_root/disable.out" disabled '' ''; then
  rg -m1 'Telegram phase:' "$fixture_root/disable.out" >&2 || true
  fail "Telegram disable must succeed"
fi
cmp -s <(printf 'PROVIDER_KEY=preserve-manager\nCUSTOM_FLAG=manager-tail\n') \
  "$data_dir/profiles/manager/.env" \
  || fail "disable must remove only the exact managed Telegram block"
cmp -s <(printf 'HERMES_GATEWAY_PROFILE=default\n') "$app_dir/gateway.env" \
  || fail "disable must restore the retained pre-Telegram profile"
cmp -s <(printf 'default\n') "$app_dir/gateway-profile.pre-telegram" \
  || fail "disable must retain the original profile evidence"
cmp -s <(printf 'manager\n') "$app_dir/gateway-profile.telegram-managed" \
  || fail "disable must retain the managed profile evidence"
[[ "$(count_command "compose --env-file $app_dir/gateway.env --file $app_dir/docker-compose.yml up --detach --force-recreate hermes")" -eq 1 ]] \
  || fail "two disable includes must recreate exactly one Hermes service once"
grep -Fqx 'telegram-env-count=0' "$command_log" \
  || fail "disable must remove protected Telegram values from the Compose environment"
[[ "$(count_command "exec --user $test_identity:$test_group --env HOME=/opt/data --env CODEX_HOME=/opt/data/.codex hermes hermes gateway stop --all")" -eq 1 ]] \
  || fail "disable must stop every managed supervised gateway before recreation"
[[ "$(count_command "exec --user $test_identity:$test_group --env HOME=/opt/data --env CODEX_HOME=/opt/data/.codex hermes hermes --profile default gateway start")" -eq 1 ]] \
  || fail "disable must restore only the prior supervised gateway"
assert_no_protected_output "$fixture_root/disable.out"
printf 'PASS Telegram disable restores bytes and retains rollback evidence idempotently\n'

: >"$command_log"
if ! run_gateway "$fixture_root/disable-again.out" disabled '' ''; then
  fail "a later Telegram disable run must remain idempotent"
fi
grep -Eq 'changed=0[[:space:]]' "$fixture_root/disable-again.out" \
  || fail "a fully converged disable run must report changed=0"
[[ "$(count_command "compose --env-file $app_dir/gateway.env --file $app_dir/docker-compose.yml up --detach --force-recreate hermes")" -eq 0 ]] \
  || fail "a converged disable must not recreate Hermes"
printf 'PASS repeated Telegram disable reports changed=0 without recreation\n'

: >"$command_log"
if ! run_gateway "$fixture_root/reenable-devops.out" enabled "$telegram_source" devops; then
  fail "enable must permit a different profile after completed disable"
fi
cmp -s <(printf 'PROVIDER_KEY=preserve-manager\nCUSTOM_FLAG=manager-tail\n') \
  "$data_dir/profiles/manager/.env" \
  || fail "profile switching must leave the previous managed profile exact"
grep -q '^# BEGIN HERMES MANAGED TELEGRAM$' "$data_dir/profiles/devops/.env" \
  || fail "profile switching must install Telegram only in the newly selected profile"
cmp -s <(printf 'default\n') "$app_dir/gateway-profile.pre-telegram" \
  || fail "profile switching must not overwrite the original pre-Telegram profile"
cmp -s <(printf 'devops\n') "$app_dir/gateway-profile.telegram-managed" \
  || fail "profile switching must replace only the managed-profile evidence"
[[ "$(count_command "compose --env-file $app_dir/gateway.env --file $app_dir/docker-compose.yml up --detach --force-recreate hermes")" -eq 1 ]] \
  || fail "profile switching must recreate exactly one Hermes service once"
assert_no_protected_output "$fixture_root/reenable-devops.out"
printf 'PASS a completed disable permits a protected switch to another profile\n'

reset_fixture
printf 'default\n' >"$app_dir/gateway-profile.pre-telegram"
printf 'manager\n' >"$app_dir/gateway-profile.telegram-managed"
chmod 600 "$app_dir/gateway-profile.pre-telegram" \
  "$app_dir/gateway-profile.telegram-managed"
cp "$fixture_root/manager.expected" "$data_dir/profiles/manager/.env"
cp "$data_dir/profiles/devops/.env" "$fixture_root/stale-managed-devops.before"
set +e
run_gateway "$fixture_root/stale-managed.out" enabled "$telegram_source" devops
stale_managed_status=$?
set -e
[[ "$stale_managed_status" -ne 0 ]] \
  || fail "profile switching must reject a retained block in the previous managed profile"
cmp -s "$fixture_root/stale-managed-devops.before" "$data_dir/profiles/devops/.env" \
  || fail "a stale previous block must fail before new-profile mutation"
cmp -s <(printf 'manager\n') "$app_dir/gateway-profile.telegram-managed" \
  || fail "a stale previous block must fail before managed-profile replacement"
[[ "$(count_command "compose --env-file $app_dir/gateway.env --file $app_dir/docker-compose.yml up --detach --force-recreate hermes")" -eq 0 ]] \
  || fail "a stale previous block must fail before recreation"
assert_no_protected_output "$fixture_root/stale-managed.out"
printf 'PASS a stale previous managed block prevents profile switching\n'

reset_fixture
set +e
run_gateway "$fixture_root/render-failure.out" enabled "$telegram_source" manager \
  env FAIL_RENDER_COMPOSE=1
render_failure_status=$?
set -e
[[ "$render_failure_status" -ne 0 ]] \
  || fail "post-mutation rendered Compose failure must fail the request"
[[ -f "$app_dir/telegram-reconciliation.pending" ]] \
  || fail "post-mutation rendered Compose failure must retain pending reconciliation"
[[ "$(file_mode "$app_dir/telegram-reconciliation.pending")" == "600" ]] \
  || fail "pending reconciliation state must be mode 0600"
[[ "$(count_command "compose --env-file $app_dir/gateway.env --file $app_dir/docker-compose.yml up --detach --force-recreate hermes")" -eq 0 ]] \
  || fail "rendered Compose failure must stop before recreation"

: >"$command_log"
if ! run_gateway "$fixture_root/render-retry.out" enabled "$telegram_source" manager; then
  fail "retry after rendered Compose failure must succeed"
fi
[[ "$(count_command "compose --env-file $app_dir/gateway.env --file $app_dir/docker-compose.yml up --detach --force-recreate hermes")" -eq 1 ]] \
  || fail "retained rendered-Compose pending state must force exactly one recreation"
[[ ! -e "$app_dir/telegram-reconciliation.pending" ]] \
  || fail "successful rendered-Compose retry must clear pending reconciliation"
assert_no_protected_output "$fixture_root/render-failure.out"
assert_no_protected_output "$fixture_root/render-retry.out"
printf 'PASS rendered Compose failure retains reconciliation and retry recreates once\n'

reset_fixture
set +e
run_gateway "$fixture_root/up-failure.out" enabled "$telegram_source" manager \
  env FAIL_COMPOSE_UP=1
up_failure_status=$?
set -e
[[ "$up_failure_status" -ne 0 ]] || fail "Compose up failure must fail the request"
[[ -f "$app_dir/telegram-reconciliation.pending" ]] \
  || fail "Compose up failure must retain pending reconciliation"
[[ "$(file_mode "$app_dir/telegram-reconciliation.pending")" == "600" ]] \
  || fail "Compose up pending reconciliation state must be mode 0600"

: >"$command_log"
if ! run_gateway "$fixture_root/up-retry.out" enabled "$telegram_source" manager; then
  fail "retry after Compose up failure must succeed"
fi
[[ "$(count_command "compose --env-file $app_dir/gateway.env --file $app_dir/docker-compose.yml up --detach --force-recreate hermes")" -eq 1 ]] \
  || fail "retained Compose-up pending state must force exactly one recreation"
[[ ! -e "$app_dir/telegram-reconciliation.pending" ]] \
  || fail "successful Compose-up retry must clear pending reconciliation"
assert_no_protected_output "$fixture_root/up-failure.out"
assert_no_protected_output "$fixture_root/up-retry.out"
printf 'PASS Compose up failure retains reconciliation and retry recreates once\n'

reset_fixture
printf 'manager\n' >"$app_dir/gateway-profile.telegram-managed"
printf 'HERMES_GATEWAY_PROFILE=manager\n' >"$app_dir/gateway.env"
chmod 600 "$app_dir/gateway-profile.telegram-managed" "$app_dir/gateway.env"
cp "$data_dir/profiles/manager/.env" "$fixture_root/missing-backup.before"
set +e
run_gateway "$fixture_root/missing-backup.out" disabled '' ''
missing_backup_status=$?
set -e
[[ "$missing_backup_status" -ne 0 ]] || fail "disable must reject missing rollback state"
cmp -s "$fixture_root/missing-backup.before" "$data_dir/profiles/manager/.env" \
  || fail "missing rollback state must fail before profile mutation"
[[ "$(count_command "compose --env-file $app_dir/gateway.env --file $app_dir/docker-compose.yml up --detach --force-recreate hermes")" -eq 0 ]] \
  || fail "missing rollback state must fail before recreation"
grep -q 'Telegram phase: .*; Last completed phase:' "$fixture_root/missing-backup.out" \
  || fail "failure output must identify current and last completed phases"
assert_no_protected_output "$fixture_root/missing-backup.out"
printf 'PASS missing rollback state fails closed with value-free phase output\n'

reset_fixture
printf 'default\n' >"$app_dir/gateway-profile.pre-telegram"
printf 'manager extra\n' >"$app_dir/gateway-profile.telegram-managed"
chmod 600 "$app_dir/gateway-profile.pre-telegram" \
  "$app_dir/gateway-profile.telegram-managed"
set +e
run_gateway "$fixture_root/malformed-state.out" enabled "$telegram_source" manager
malformed_state_status=$?
set -e
[[ "$malformed_state_status" -ne 0 ]] || fail "malformed retained state must fail"
[[ ! -s "$command_log" ]] || fail "malformed retained state must fail before Docker"
cmp -s <(printf 'PROVIDER_KEY=preserve-manager\nCUSTOM_FLAG=manager-tail\n') \
  "$data_dir/profiles/manager/.env" \
  || fail "malformed retained state must fail before profile mutation"
assert_no_protected_output "$fixture_root/malformed-state.out"
printf 'PASS malformed retained state fails before Docker or file mutation\n'

reset_fixture
chmod 644 "$telegram_source"
set +e
run_gateway "$fixture_root/invalid-input.out" enabled "$telegram_source" manager
invalid_input_status=$?
set -e
[[ "$invalid_input_status" -ne 0 ]] || fail "enable must reject invalid protected input"
[[ ! -s "$command_log" ]] || fail "invalid protected input must fail before Docker"
grep -q 'Telegram phase: .*; Last completed phase:' "$fixture_root/invalid-input.out" \
  || fail "invalid input failure must include value-free phase output"
assert_no_protected_output "$fixture_root/invalid-input.out"
printf 'PASS invalid protected input fails before Docker without protected output\n'

reset_fixture
cp "$data_dir/profiles/manager/.env" "$fixture_root/compose-failure.before"
set +e
run_gateway "$fixture_root/compose-failure.out" enabled "$telegram_source" manager \
  env FAIL_COMPOSE_CONFIG=1
compose_failure_status=$?
set -e
[[ "$compose_failure_status" -ne 0 ]] || fail "Compose preflight failure must fail the request"
cmp -s "$fixture_root/compose-failure.before" "$data_dir/profiles/manager/.env" \
  || fail "Compose preflight failure must occur before profile mutation"
[[ ! -e "$app_dir/gateway-profile.pre-telegram" ]] \
  || fail "Compose preflight failure must occur before state preservation"
[[ "$(count_command "compose --env-file $app_dir/gateway.env --file $app_dir/docker-compose.yml up --detach --force-recreate hermes")" -eq 0 ]] \
  || fail "Compose preflight failure must not recreate Hermes"
grep -q 'Telegram phase: .*; Last completed phase:' "$fixture_root/compose-failure.out" \
  || fail "Compose failure must include value-free phase output"
assert_no_protected_output "$fixture_root/compose-failure.out"
printf 'PASS Compose failure is detected before every mutation\n'

reset_fixture
set +e
run_gateway "$fixture_root/unhealthy-container.out" enabled "$telegram_source" manager \
  env FAIL_CONTAINER_HEALTH=1
unhealthy_container_status=$?
set -e
[[ "$unhealthy_container_status" -ne 0 ]] || fail "unhealthy Hermes must fail preflight"
[[ ! -e "$app_dir/gateway-profile.pre-telegram" ]] \
  || fail "unhealthy Hermes must fail before state preservation"
cmp -s <(printf 'PROVIDER_KEY=preserve-manager\nCUSTOM_FLAG=manager-tail\n') \
  "$data_dir/profiles/manager/.env" \
  || fail "unhealthy Hermes must fail before profile mutation"
[[ "$(count_command "compose --env-file $app_dir/gateway.env --file $app_dir/docker-compose.yml up --detach --force-recreate hermes")" -eq 0 ]] \
  || fail "unhealthy Hermes must fail before recreation"
assert_no_protected_output "$fixture_root/unhealthy-container.out"
printf 'PASS unhealthy container state fails before every mutation\n'

reset_fixture
printf 'pending\n' >"$app_dir/telegram-reconciliation.pending"
chmod 600 "$app_dir/telegram-reconciliation.pending"
run_gateway "$fixture_root/pending-unhealthy-recovery.out" enabled "$telegram_source" manager \
  env RECOVERY_UNHEALTHY_ON_FIRST=1 FAIL_PROFILE_SHOW_WITH_PENDING=1
[[ ! -e "$app_dir/telegram-reconciliation.pending" ]] \
  || fail "successful unhealthy pending recovery must clear reconciliation state"
[[ "$(count_command "compose --env-file $app_dir/gateway.env --file $app_dir/docker-compose.yml up --detach --force-recreate hermes")" -eq 1 ]] \
  || fail "unhealthy pending recovery must recreate Hermes exactly once"
assert_no_protected_output "$fixture_root/pending-unhealthy-recovery.out"
printf 'PASS validated pending state recovers an unhealthy unavailable runtime\n'

reset_fixture
set +e
run_gateway "$fixture_root/invalid-profile.out" enabled "$telegram_source" unknown
invalid_profile_status=$?
set -e
[[ "$invalid_profile_status" -ne 0 ]] || fail "an unknown selected profile must fail"
[[ ! -s "$command_log" ]] || fail "an unknown selected profile must fail before Docker"
[[ ! -e "$data_dir/profiles/unknown/.env" ]] \
  || fail "an unknown selected profile must not create profile state"
grep -q 'Telegram phase: .*; Last completed phase:' "$fixture_root/invalid-profile.out" \
  || fail "selected-profile failure must include value-free phase output"
assert_no_protected_output "$fixture_root/invalid-profile.out"
printf 'PASS selected profile validation fails closed before Docker\n'

assert_invalid_profile_structure() {
  local case_name="$1"
  local before_path="$fixture_root/$case_name.before"
  local output_path="$fixture_root/$case_name.out"
  cp "$data_dir/profiles/manager/.env" "$before_path"
  : >"$command_log"
  set +e
  run_gateway "$output_path" enabled "$telegram_source" manager
  structure_status=$?
  set -e
  [[ "$structure_status" -ne 0 ]] \
    || fail "$case_name profile structure must fail preflight"
  [[ ! -s "$command_log" ]] \
    || fail "$case_name profile structure must fail before Docker"
  cmp -s "$before_path" "$data_dir/profiles/manager/.env" \
    || fail "$case_name profile structure must fail before file mutation"
  [[ ! -e "$app_dir/telegram-reconciliation.pending" ]] \
    || fail "$case_name profile structure must fail before pending reconciliation"
  assert_no_protected_output "$output_path"
}

reset_fixture
printf 'TELEGRAM_ALLOWED_USERS=90909\n' >>"$data_dir/profiles/manager/.env"
assert_invalid_profile_structure unmanaged-telegram-key
printf 'PASS unmanaged Telegram assignments fail before Docker or mutation\n'

reset_fixture
printf '# BEGIN HERMES MANAGED TELEGRAM\nTELEGRAM_ALLOWED_USERS=90909\n' \
  >>"$data_dir/profiles/manager/.env"
assert_invalid_profile_structure partial-telegram-marker
printf 'PASS partial Telegram markers fail before Docker or mutation\n'

reset_fixture
cp "$fixture_root/manager.expected" "$data_dir/profiles/manager/.env"
sed -n '/^# BEGIN HERMES MANAGED TELEGRAM$/,/^# END HERMES MANAGED TELEGRAM$/p' \
  "$fixture_root/manager.expected" \
  >>"$data_dir/profiles/manager/.env"
assert_invalid_profile_structure duplicate-telegram-block
printf 'PASS duplicate Telegram blocks fail before Docker or mutation\n'

reset_fixture
cp "$fixture_root/manager.expected" "$data_dir/profiles/manager/.env"
printf 'TELEGRAM_WEBHOOK_URL=https://fixture.invalid/hook\n' \
  >>"$data_dir/profiles/manager/.env"
assert_invalid_profile_structure telegram-key-outside-block
printf 'PASS Telegram assignments outside a valid block fail before mutation\n'

reset_fixture
rm "$app_dir/gateway.env"
if ! run_gateway "$fixture_root/absent-runtime-env.out" enabled "$telegram_source" manager; then
  tail -60 "$fixture_root/absent-runtime-env.out" >&2 || true
  fail "an absent runtime environment must be treated as the default profile"
fi
cmp -s <(printf 'default\n') "$app_dir/gateway-profile.pre-telegram" \
  || fail "absent runtime state must preserve the default profile"
cmp -s <(printf 'HERMES_GATEWAY_PROFILE=manager\n') "$app_dir/gateway.env" \
  || fail "enable must atomically create an absent runtime environment"
grep -Fqx "compose --env-file /dev/null --file $app_dir/docker-compose.yml config --quiet" \
  "$command_log" \
  || fail "absent runtime state must still validate Compose before mutation"
assert_no_protected_output "$fixture_root/absent-runtime-env.out"
printf 'PASS absent runtime state defaults safely with pre-mutation Compose validation\n'

reset_fixture
rm "$data_dir/profiles/manager/.env"
if ! run_gateway "$fixture_root/absent-profile-env.out" enabled "$telegram_source" manager; then
  fail "a selected profile without an environment file must be created safely"
fi
[[ "$(file_mode "$data_dir/profiles/manager/.env")" == "600" ]] \
  || fail "a created selected-profile environment must be mode 0600"
grep -q '^# BEGIN HERMES MANAGED TELEGRAM$' "$data_dir/profiles/manager/.env" \
  || fail "a created selected-profile environment must contain the managed block"
assert_no_protected_output "$fixture_root/absent-profile-env.out"
printf 'PASS selected profile environment creation is protected and functional\n'

run_starting_health_control
run_round2_structure_controls

printf 'PASS Ansible Telegram gateway behavior suite\n'
