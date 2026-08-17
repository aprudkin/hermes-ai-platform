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
