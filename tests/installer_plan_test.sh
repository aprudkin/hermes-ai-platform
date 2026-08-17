#!/usr/bin/env bash

set -euo pipefail
# shellcheck source=tests/test_helper.sh
source "$(dirname "${BASH_SOURCE[0]}")/test_helper.sh"

fixture_root="$(mktemp -d)"
trap 'rm -rf "$fixture_root"' EXIT
fake_bin="$fixture_root/bin"
mkdir -p "$fake_bin"
terraform_log="$fixture_root/terraform.log"
ansible_log="$fixture_root/ansible.log"
: >"$terraform_log"
: >"$ansible_log"

cat >"$fake_bin/terraform" <<'FAKE'
#!/usr/bin/env bash
printf 'location=%s server_type=%s args=%s\n' \
  "${TF_VAR_location:-}" "${TF_VAR_server_type:-}" "$*" >>"$TERRAFORM_LOG"
FAKE
cat >"$fake_bin/ansible-playbook" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$ANSIBLE_LOG"
FAKE
chmod +x "$fake_bin/terraform" "$fake_bin/ansible-playbook"

public_key="$fixture_root/luk.pub"
private_key="$fixture_root/luk"
printf 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestFixtureOnly hermes-test\n' >"$public_key"
: >"$private_key"

env PATH="$fake_bin:$PATH" TERRAFORM_LOG="$terraform_log" \
  ANSIBLE_LOG="$ansible_log" HCLOUD_TOKEN="test-only-token" \
  "$repo_root/installer/install.sh" plan new --location hel1 --server-type cx23 \
    --hcloud-ssh-key-name Luk --ssh-public-key "$public_key" \
    --ssh-source-cidr 192.0.2.10/32 >/dev/null

grep -q 'init ' "$terraform_log" || fail "new-host plan must initialize Terraform"
grep -q 'validate' "$terraform_log" || fail "new-host plan must validate Terraform"
grep -q ' plan ' "$terraform_log" || fail "new-host plan must execute Terraform plan"
! grep -q 'apply' "$terraform_log" || fail "new-host plan must never execute Terraform apply"
grep -q 'location=hel1 server_type=cx23 args=.* plan ' "$terraform_log" \
  || fail "new-host plan must pass the selected hel1 location and server type to Terraform"
grep -q -- '--syntax-check' "$ansible_log" || fail "new-host plan must syntax-check Ansible"
printf 'PASS hel1 new-host plan passes the selected server type and never applies\n'

: >"$terraform_log"
: >"$ansible_log"
set +e
env PATH="$fake_bin:$PATH" TERRAFORM_LOG="$terraform_log" \
  ANSIBLE_LOG="$ansible_log" HCLOUD_TOKEN="test-only-token" \
  "$repo_root/installer/install.sh" plan new --location hel1 \
    --hcloud-ssh-key-name Luk --ssh-public-key "$public_key" \
    --ssh-source-cidr 192.0.2.10/32 >"$fixture_root/missing-server-type.out" 2>&1
missing_server_type_status=$?
set -e

[[ "$missing_server_type_status" -ne 0 ]] || fail "new-host plan must require an explicit server type"
[[ ! -s "$terraform_log" ]] || fail "missing server type must fail before Terraform"
[[ ! -s "$ansible_log" ]] || fail "missing server type must fail before Ansible"
grep -q -- '--server-type is required' "$fixture_root/missing-server-type.out" \
  || fail "missing server type failure must identify --server-type"
printf 'PASS new-host plan requires an explicit server type before external tools\n'

: >"$terraform_log"
: >"$ansible_log"
PATH="$fake_bin:$PATH" \
TERRAFORM_LOG="$terraform_log" \
ANSIBLE_LOG="$ansible_log" \
  "$repo_root/installer/install.sh" plan existing \
    --host 192.0.2.44 --ssh-user ubuntu --ssh-private-key "$private_key" \
    --ssh-source-cidr 192.0.2.10/32 >/dev/null

[[ ! -s "$terraform_log" ]] || fail "existing-host plan must not invoke Terraform"
grep -q -- '--syntax-check' "$ansible_log" || fail "existing-host plan must syntax-check Ansible"
printf 'PASS existing-host plan bypasses Terraform and stays local\n'

provider_env="$fixture_root/hermes.env"
printf 'OPENROUTER_API_KEY=test-only-provider-value\n' >"$provider_env"
chmod 600 "$provider_env"

: >"$terraform_log"
: >"$ansible_log"
set +e
env PATH="$fake_bin:$PATH" TERRAFORM_LOG="$terraform_log" \
  ANSIBLE_LOG="$ansible_log" HCLOUD_TOKEN="test-only-token" \
  "$repo_root/installer/install.sh" deploy new --location hel1 --server-type cx23 \
    --hcloud-ssh-key-name Luk --ssh-public-key "$public_key" \
    --ssh-private-key "$private_key" --ssh-source-cidr 192.0.2.10/32 \
    --hermes-env "$provider_env" --model-provider openrouter \
    --model test/model >"$fixture_root/new-deploy.out" 2>&1
new_deploy_status=$?
set -e

[[ "$new_deploy_status" -ne 0 ]] || fail "new-host deploy must require confirmation"
[[ ! -s "$terraform_log" ]] || fail "unconfirmed new-host deploy must not invoke Terraform"
[[ ! -s "$ansible_log" ]] || fail "unconfirmed new-host deploy must not invoke Ansible"
printf 'PASS unconfirmed new-host deploy has no external process side effects\n'

: >"$terraform_log"
: >"$ansible_log"
set +e
PATH="$fake_bin:$PATH" \
TERRAFORM_LOG="$terraform_log" \
ANSIBLE_LOG="$ansible_log" \
  "$repo_root/installer/install.sh" deploy existing \
    --host 192.0.2.44 --ssh-user ubuntu --ssh-private-key "$private_key" \
    --ssh-source-cidr 192.0.2.10/32 --hermes-env "$provider_env" \
    --model-provider openrouter --model test/model \
    >"$fixture_root/existing-deploy.out" 2>&1
existing_deploy_status=$?
set -e

[[ "$existing_deploy_status" -ne 0 ]] || fail "existing-host deploy must require confirmation"
[[ ! -s "$terraform_log" ]] || fail "unconfirmed existing-host deploy must not invoke Terraform"
[[ ! -s "$ansible_log" ]] || fail "unconfirmed existing-host deploy must not invoke Ansible"
printf 'PASS unconfirmed existing-host deploy has no external process side effects\n'
