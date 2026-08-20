#!/usr/bin/env bash

set -euo pipefail
# shellcheck source=tests/test_helper.sh
source "$(dirname "${BASH_SOURCE[0]}")/test_helper.sh"

fixture_root="$(mktemp -d)"
trap 'rm -rf "$fixture_root"' EXIT
runtime_bin="$fixture_root/bin"
runtime_log="$fixture_root/ansible.log"
runtime_inventory="$fixture_root/inventory.ini"
mkdir -p "$runtime_bin"
: >"$runtime_inventory"

cat >"$runtime_bin/ansible-playbook" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$RUNTIME_ANSIBLE_LOG"
FAKE
chmod +x "$runtime_bin/ansible-playbook"

: >"$runtime_log"
PATH="$runtime_bin:$PATH" RUNTIME_ANSIBLE_LOG="$runtime_log" \
  bash "$repo_root/scripts/validate.sh" --runtime \
    --inventory "$runtime_inventory" >/dev/null
! grep -q -- 'hermes_telegram_' "$runtime_log" \
  || fail "ordinary runtime validation must not add Telegram variables"

: >"$runtime_log"
PATH="$runtime_bin:$PATH" RUNTIME_ANSIBLE_LOG="$runtime_log" \
  bash "$repo_root/scripts/validate.sh" --runtime \
    --inventory "$runtime_inventory" --telegram-state enabled \
    --gateway-profile manager >/dev/null
grep -q -- 'ansible/verify.yml .*hermes_telegram_state=enabled .*hermes_gateway_profile=manager' \
  "$runtime_log" \
  || fail "Telegram runtime validation must forward only state and profile"

: >"$runtime_log"
set +e
PATH="$runtime_bin:$PATH" RUNTIME_ANSIBLE_LOG="$runtime_log" \
  bash "$repo_root/scripts/validate.sh" --runtime \
    --inventory "$runtime_inventory" --telegram-state enabled \
    >"$fixture_root/partial.out" 2>&1
runtime_partial_status=$?
set -e
[[ "$runtime_partial_status" -ne 0 ]] \
  || fail "runtime validation must reject a partial Telegram state/profile pair"
[[ ! -s "$runtime_log" ]] \
  || fail "partial Telegram runtime validation must fail before Ansible"

for invalid_case in \
  '--gateway-profile manager' \
  '--telegram-state disabled --gateway-profile manager' \
  '--telegram-state enabled --gateway-profile bad/profile'; do
  : >"$runtime_log"
  read -r -a invalid_args <<<"$invalid_case"
  set +e
  PATH="$runtime_bin:$PATH" RUNTIME_ANSIBLE_LOG="$runtime_log" \
    bash "$repo_root/scripts/validate.sh" --runtime \
      --inventory "$runtime_inventory" "${invalid_args[@]}" \
      >"$fixture_root/invalid.out" 2>&1
  invalid_status=$?
  set -e
  [[ "$invalid_status" -ne 0 ]] \
    || fail "invalid runtime Telegram arguments must be rejected: $invalid_case"
  [[ ! -s "$runtime_log" ]] \
    || fail "invalid runtime Telegram arguments must fail before Ansible"
done
printf 'PASS runtime validation forwards only an exact Telegram state/profile pair\n'
