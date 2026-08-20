#!/usr/bin/env bash

set -euo pipefail
# shellcheck source=tests/test_helper.sh
source "$(dirname "${BASH_SOURCE[0]}")/test_helper.sh"

set +e
output="$("$repo_root/installer/install.sh" nonsense 2>&1)"
status=$?
set -e

[[ "$status" -ne 0 ]] || fail "unknown installer mode must fail"
[[ "$output" == *"Usage:"* ]] || fail "unknown installer mode must print usage"

printf 'PASS installer rejects unknown mode\n'

set +e
output="$("$repo_root/installer/install.sh" plan new --location ash --server-type cx23 --ssh-source-cidr 192.0.2.10/32 --ssh-public-key /dev/null 2>&1)"
status=$?
set -e

[[ "$status" -ne 0 ]] || fail "unsupported Hetzner location must fail before Terraform"
[[ "$output" == *"fsn1, nbg1, or hel1"* ]] || fail "location failure must explain accepted locations"

printf 'PASS installer rejects a location outside the supported allowlist\n'

set +e
output="$("$repo_root/installer/install.sh" plan existing --host '' --ssh-user ubuntu --ssh-source-cidr 192.0.2.10/32 --ssh-private-key /dev/null 2>&1)"
status=$?
set -e

[[ "$status" -ne 0 ]] || fail "existing-host plan without a host must fail"
[[ "$output" == *"--host"* ]] || fail "existing-host failure must identify --host"

printf 'PASS installer requires an existing host target\n'

assert_telegram_rejected() {
  local expected_message="$1"
  shift
  local telegram_output
  local telegram_status

  set +e
  telegram_output="$("$repo_root/installer/install.sh" "$@" 2>&1)"
  telegram_status=$?
  set -e

  [[ "$telegram_status" -ne 0 ]] || fail "Telegram option contract must reject: $*"
  [[ "$telegram_output" == *"$expected_message"* ]] \
    || fail "Telegram option contract must explain $expected_message"
}

assert_telegram_rejected '--telegram-state must be enabled or disabled' \
  plan telegram --telegram-state unknown
printf 'PASS installer rejects an unknown Telegram state\n'

assert_telegram_rejected '--telegram-state is required for the telegram target' \
  plan telegram
printf 'PASS installer requires an explicit targeted Telegram state\n'

assert_telegram_rejected '--telegram-env is required when Telegram is enabled' \
  plan telegram --telegram-state enabled --gateway-profile manager
printf 'PASS installer requires a protected Telegram input when enabling\n'

assert_telegram_rejected '--gateway-profile is required when Telegram is enabled' \
  plan telegram --telegram-state enabled --telegram-env /dev/null
printf 'PASS installer requires a gateway profile when enabling\n'

assert_telegram_rejected '--telegram-env must not be used when Telegram is disabled' \
  plan telegram --telegram-state disabled --telegram-env /dev/null
printf 'PASS installer rejects a protected input when disabling\n'

assert_telegram_rejected '--gateway-profile must not be used when Telegram is disabled' \
  plan telegram --telegram-state disabled --gateway-profile manager
printf 'PASS installer rejects a gateway profile when disabling\n'

assert_telegram_rejected '--telegram-env must not be used when Telegram is disabled' \
  plan telegram --telegram-state disabled --telegram-env ''
printf 'PASS installer rejects an explicitly empty protected input when disabling\n'

assert_telegram_rejected '--gateway-profile must not be used when Telegram is disabled' \
  plan telegram --telegram-state disabled --gateway-profile ''
printf 'PASS installer rejects an explicitly empty gateway profile when disabling\n'

assert_telegram_rejected '--gateway-profile must be a Hermes profile name' \
  plan telegram --telegram-state enabled --telegram-env /dev/null \
  --gateway-profile 'manager profile'
printf 'PASS installer rejects an invalid Telegram gateway profile\n'

assert_telegram_rejected '--location is not supported for the telegram target' \
  plan telegram --telegram-state disabled --location hel1
printf 'PASS installer rejects new-host-only options for Telegram targets\n'

assert_telegram_rejected '--model-provider is not supported for the telegram target' \
  plan telegram --telegram-state disabled --model-provider openrouter
printf 'PASS installer rejects provider options for Telegram targets\n'

assert_telegram_rejected '--telegram-env and --gateway-profile must be supplied together' \
  plan existing --telegram-env /dev/null
printf 'PASS installer requires full-plan Telegram options as an exact pair\n'

assert_telegram_rejected '--telegram-env and --gateway-profile must be supplied together' \
  plan existing --telegram-env ''
printf 'PASS installer treats an explicitly empty full-plan input as supplied\n'

assert_telegram_rejected '--telegram-env and --gateway-profile must be supplied together' \
  plan existing --gateway-profile ''
printf 'PASS installer treats an explicitly empty full-plan profile as supplied\n'

assert_telegram_rejected '--telegram-env is required when Telegram is enabled' \
  plan existing --telegram-env '' --gateway-profile ''
printf 'PASS installer rejects an explicitly empty full-plan option pair\n'
