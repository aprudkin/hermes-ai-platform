#!/usr/bin/env bash

set -euo pipefail
# shellcheck source=tests/test_helper.sh
source "$(dirname "${BASH_SOURCE[0]}")/test_helper.sh"

if ! command -v terraform >/dev/null 2>&1 || ! terraform --version >/dev/null 2>&1; then
  printf 'SKIP Terraform public-key identity behavior (runnable terraform unavailable)\n'
  exit 0
fi

fixture_root="$(mktemp -d)"
trap 'rm -rf "$fixture_root"' EXIT
public_key="$fixture_root/luk.pub"
printf 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestFixtureOnly operator-comment\n' >"$public_key"

identity="$(
  printf 'local.ssh_public_key_identity\n' \
    | terraform -chdir="$repo_root/terraform" console \
      -var='location=hel1' \
      -var='server_type=cx23' \
      -var="ssh_public_key_path=$public_key" \
      -var='hcloud_ssh_key_name=Luk' \
      -var='ssh_source_cidrs=["192.0.2.10/32"]'
)"

[[ "$identity" == '"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestFixtureOnly"' ]] \
  || fail "Terraform must compare an OpenSSH public key by type and key material, without its comment"

printf 'PASS Terraform normalizes OpenSSH public-key identity without its comment\n'
