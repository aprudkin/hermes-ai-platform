#!/usr/bin/env bash

set -euo pipefail
# shellcheck source=tests/test_helper.sh
source "$(dirname "${BASH_SOURCE[0]}")/test_helper.sh"

if [[ "${HERMES_VALIDATE_TEST_NO_RECURSE:-0}" == "1" ]]; then
  printf 'SKIP nested Telegram verifier behavior test\n'
  exit 0
fi

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
  printf 'SKIP Telegram verifier behavior (runnable ansible-playbook unavailable)\n'
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
profile_env="$data_dir/profiles/manager/.env"
docker_log="$fixture_root/docker.log"
test_identity="$(id -un)"
test_group="$(id -gn)"
alternate_group=""
for candidate_group in $(id -Gn); do
  if [[ "$candidate_group" != "$test_group" ]]; then
    alternate_group="$candidate_group"
    break
  fi
done
[[ -n "$alternate_group" ]] \
  || fail "ownership controls require one supplementary disposable group"
mkdir -p "$fake_bin" "$app_dir" "$(dirname "$profile_env")"

cat >"$fake_bin/docker" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$HERMES_VERIFY_DOCKER_LOG"
case "${1:-}" in
  inspect)
    printf 'healthy\n'
    ;;
  top)
    printf 'COMMAND\nhermes -p manager gateway run\n'
    ;;
  exec)
    printf 'Configuration valid\n'
    ;;
  logs)
    printf '[Telegram] Connected to Telegram (polling mode)\n'
    printf 'Gateway running with 1 platform(s)\n'
    ;;
  *) exit 90 ;;
esac
FAKE
chmod +x "$fake_bin/docker"

printf 'default\n' >"$app_dir/gateway-profile.pre-telegram"
printf 'manager\n' >"$app_dir/gateway-profile.telegram-managed"
printf 'HERMES_GATEWAY_PROFILE=manager\n' >"$app_dir/gateway.env"
chmod 600 "$app_dir/gateway-profile.pre-telegram" \
  "$app_dir/gateway-profile.telegram-managed" "$app_dir/gateway.env"

write_valid_profile_env() {
  {
    printf 'UNRELATED_PROVIDER_KEY=fixture-only\n'
    printf '# BEGIN HERMES MANAGED TELEGRAM\n'
    printf 'TELEGRAM_BOT_TOKEN=%s:%s\n' '123456789' 'fixture_value_abcdefghijklmnop'
    printf 'TELEGRAM_ALLOWED_USERS=101,202\n'
    printf 'TELEGRAM_ALLOWED_CHATS=-1001,-1002\n'
    printf 'TELEGRAM_REQUIRE_MENTION=true\n'
    printf 'TELEGRAM_EXCLUSIVE_BOT_MENTIONS=true\n'
    printf 'TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES=false\n'
    printf '# END HERMES MANAGED TELEGRAM\n'
  } >"$profile_env"
  chmod 600 "$profile_env"
}

run_verifier() {
  local output_path="$1"

  PATH="$fake_bin:$PATH" HERMES_VERIFY_DOCKER_LOG="$docker_log" \
  ANSIBLE_CONFIG="$repo_root/ansible/ansible.cfg" \
    "${ansible_command[@]}" --inventory hermes, \
      "$repo_root/ansible/telegram_verify.yml" --connection local \
      --extra-vars ansible_become=false \
      --extra-vars hermes_telegram_state=enabled \
      --extra-vars hermes_gateway_profile=manager \
      --extra-vars "hermes_app_dir=$app_dir" \
      --extra-vars "hermes_data_dir=$data_dir" \
      --extra-vars "hermes_app_owner=$test_identity" \
      --extra-vars "hermes_app_group=$test_group" \
      --extra-vars "hermes_runtime_owner=$test_identity" \
      --extra-vars "hermes_runtime_group=$test_group" \
      >"$output_path" 2>&1
}

assert_invalid_outside_assignment() {
  local case_name="$1"
  local assignment="$2"
  local output_path="$fixture_root/$case_name.out"
  local verify_status

  write_valid_profile_env
  printf '%s\n' "$assignment" >>"$profile_env"
  : >"$docker_log"
  set +e
  run_verifier "$output_path"
  verify_status=$?
  set -e
  [[ "$verify_status" -ne 0 ]] \
    || fail "$case_name must reject the unmanaged Telegram assignment"
  [[ ! -s "$docker_log" ]] \
    || fail "$case_name must fail before Docker inspection"
  ! grep -Eq 'fixture_value_abcdefghijklmnop|101,202|-1001,-1002' "$output_path" \
    || fail "$case_name must not return protected Telegram values"
}

assert_wrong_group_rejected() {
  local case_name="$1"
  local target_file="$2"
  local output_path="$fixture_root/$case_name.out"
  local verify_status

  chgrp "$alternate_group" "$target_file"
  : >"$docker_log"
  set +e
  run_verifier "$output_path"
  verify_status=$?
  set -e
  chgrp "$test_group" "$target_file"
  [[ "$verify_status" -ne 0 ]] \
    || fail "$case_name must reject the wrong protected group"
  [[ ! -s "$docker_log" ]] \
    || fail "$case_name must fail before Docker inspection"
  ! grep -Eq 'fixture_value_abcdefghijklmnop|101,202|-1001,-1002' "$output_path" \
    || fail "$case_name must not return protected Telegram values"
}

write_valid_profile_env
: >"$docker_log"
run_verifier "$fixture_root/valid.out"
grep -q '^inspect ' "$docker_log" \
  || fail "valid verifier must read container health"
grep -q '^top ' "$docker_log" \
  || fail "valid verifier must read process arguments"
grep -q '^exec ' "$docker_log" \
  || fail "valid verifier must check the selected profile"
grep -q '^logs --tail 200 ' "$docker_log" \
  || fail "valid verifier must read only bounded logs"
! grep -Ev '^(inspect|top|exec|logs --tail 200) ' "$docker_log" >/dev/null \
  || fail "valid verifier must use only read-only Docker operations"
printf 'PASS Telegram verifier accepts the exact managed block\n'

assert_wrong_group_rejected wrong-runtime-env-group "$app_dir/gateway.env"
assert_wrong_group_rejected wrong-retained-backup-group \
  "$app_dir/gateway-profile.pre-telegram"
assert_wrong_group_rejected wrong-retained-managed-group \
  "$app_dir/gateway-profile.telegram-managed"
assert_wrong_group_rejected wrong-profile-env-group "$profile_env"
printf 'PASS Telegram verifier rejects wrong ownership before Docker access\n'

assert_invalid_outside_assignment export-assignment \
  'export TELEGRAM_ALLOWED_USERS=303'
assert_invalid_outside_assignment indented-assignment \
  '  TELEGRAM_ALLOWED_CHATS=-1003'
assert_invalid_outside_assignment forbidden-group-key \
  ' export TELEGRAM_GROUP_ALLOWED_CHATS=-1003'
printf 'PASS Telegram verifier rejects export, indentation, and forbidden outside-block keys\n'
