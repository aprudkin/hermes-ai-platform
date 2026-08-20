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
ssh_log="$fixture_root/ssh.log"
ssh_keygen_log="$fixture_root/ssh-keygen.log"
python_log="$fixture_root/python.log"
: >"$terraform_log"
: >"$ansible_log"
: >"$ssh_log"
: >"$ssh_keygen_log"
: >"$python_log"

real_python="$(command -v python3)"

cat >"$fake_bin/terraform" <<'FAKE'
#!/usr/bin/env bash
printf 'location=%s server_type=%s args=%s\n' \
  "${TF_VAR_location:-}" "${TF_VAR_server_type:-}" "$*" >>"$TERRAFORM_LOG"
FAKE
cat >"$fake_bin/ansible-playbook" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$ANSIBLE_LOG"
FAKE
cat >"$fake_bin/python3" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$PYTHON_LOG"
exec "$REAL_PYTHON" "$@"
FAKE
cat >"$fake_bin/ssh-keygen" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$SSH_KEYGEN_LOG"
if [[ "${MISMATCH_KEYPAIR:-0}" == "1" && "${*: -1}" == *.pub ]]; then
  printf '256 SHA256:public-fixture fixture (ED25519)\n'
else
  printf '256 SHA256:matching-fixture fixture (ED25519)\n'
fi
FAKE
cat >"$fake_bin/ssh" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$SSH_LOG"
FAKE
chmod +x "$fake_bin/terraform" "$fake_bin/ansible-playbook" \
  "$fake_bin/python3" "$fake_bin/ssh-keygen" "$fake_bin/ssh"

export TERRAFORM_LOG="$terraform_log"
export ANSIBLE_LOG="$ansible_log"
export SSH_LOG="$ssh_log"
export SSH_KEYGEN_LOG="$ssh_keygen_log"
export PYTHON_LOG="$python_log"
export REAL_PYTHON="$real_python"

reset_external_logs() {
  : >"$terraform_log"
  : >"$ansible_log"
  : >"$ssh_log"
  : >"$ssh_keygen_log"
  : >"$python_log"
}

assert_no_external_tools() {
  [[ ! -s "$terraform_log" ]] || fail "invalid Telegram input reached Terraform"
  [[ ! -s "$ansible_log" ]] || fail "invalid Telegram input reached Ansible"
  [[ ! -s "$ssh_log" ]] || fail "Telegram plan must not contact SSH"
}

public_key="$fixture_root/luk.pub"
multiple_public_keys="$fixture_root/multiple.pub"
private_key="$fixture_root/luk"
printf 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestFixtureOnly hermes-test\n' >"$public_key"
printf '%s\n%s\n' \
  'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestFixtureOnly first' \
  'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAnotherFixtureOnly second' \
  >"$multiple_public_keys"
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
set +e
env PATH="$fake_bin:$PATH" TERRAFORM_LOG="$terraform_log" \
  ANSIBLE_LOG="$ansible_log" HCLOUD_TOKEN="test-only-token" \
  "$repo_root/installer/install.sh" plan new --location hel1 --server-type cx23 \
    --hcloud-ssh-key-name Luk --ssh-public-key "$multiple_public_keys" \
    --ssh-source-cidr 192.0.2.10/32 >"$fixture_root/multiple-public-keys.out" 2>&1
multiple_public_keys_status=$?
set -e

[[ "$multiple_public_keys_status" -ne 0 ]] \
  || fail "new-host plan must reject multiple root public-key records"
[[ ! -s "$terraform_log" ]] \
  || fail "multiple public-key records must fail before Terraform"
[[ ! -s "$ansible_log" ]] \
  || fail "multiple public-key records must fail before Ansible"
grep -q -- '--ssh-public-key must contain exactly one supported OpenSSH public key' \
  "$fixture_root/multiple-public-keys.out" \
  || fail "multiple public-key failure must identify the one-key contract"
printf 'PASS new-host plan rejects multiple public-key records before external tools\n'

: >"$terraform_log"
: >"$ansible_log"
PATH="$fake_bin:$PATH" \
TERRAFORM_LOG="$terraform_log" \
ANSIBLE_LOG="$ansible_log" \
  "$repo_root/installer/install.sh" plan existing \
    --host 192.0.2.44 --ssh-user ubuntu --ssh-private-key "$private_key" \
    --ssh-public-key "$public_key" \
    --ssh-source-cidr 192.0.2.10/32 >/dev/null

[[ ! -s "$terraform_log" ]] || fail "existing-host plan must not invoke Terraform"
grep -q -- '--syntax-check' "$ansible_log" || fail "existing-host plan must syntax-check Ansible"
grep -q -- "hermes_root_ssh_public_key_source=$public_key" "$ansible_log" \
  || fail "existing-host plan must pass the validated root public-key source to Ansible"
printf 'PASS existing-host plan bypasses Terraform and stays local\n'

: >"$terraform_log"
: >"$ansible_log"
set +e
PATH="$fake_bin:$PATH" \
TERRAFORM_LOG="$terraform_log" \
ANSIBLE_LOG="$ansible_log" \
  "$repo_root/installer/install.sh" plan existing \
    --host 192.0.2.44 --ssh-user ubuntu --ssh-private-key "$private_key" \
    --ssh-source-cidr 192.0.2.10/32 >"$fixture_root/missing-public-key.out" 2>&1
missing_public_key_status=$?
set -e

[[ "$missing_public_key_status" -ne 0 ]] \
  || fail "existing-host plan must require the root public-key source"
[[ ! -s "$terraform_log" ]] || fail "missing public key must fail before Terraform"
[[ ! -s "$ansible_log" ]] || fail "missing public key must fail before Ansible"
grep -q -- '--ssh-public-key is required' "$fixture_root/missing-public-key.out" \
  || fail "missing public-key failure must identify --ssh-public-key"
printf 'PASS existing-host plan requires a root public-key source before external tools\n'

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
    --ssh-public-key "$public_key" \
    --ssh-source-cidr 192.0.2.10/32 --hermes-env "$provider_env" \
    --model-provider openrouter --model test/model \
    >"$fixture_root/existing-deploy.out" 2>&1
existing_deploy_status=$?
set -e

[[ "$existing_deploy_status" -ne 0 ]] || fail "existing-host deploy must require confirmation"
[[ ! -s "$terraform_log" ]] || fail "unconfirmed existing-host deploy must not invoke Terraform"
[[ ! -s "$ansible_log" ]] || fail "unconfirmed existing-host deploy must not invoke Ansible"
printf 'PASS unconfirmed existing-host deploy has no external process side effects\n'

telegram_env="$fixture_root/telegram.env"
invalid_telegram_env="$fixture_root/telegram-invalid.env"
{
  printf 'TELEGRAM_BOT_TOKEN=%s:%s\n' '123456789' 'fixture_value_abcdefghijklmnop'
  printf 'TELEGRAM_ALLOWED_USERS=101,202\n'
  printf 'TELEGRAM_ALLOWED_CHATS=-1001,-1002\n'
  printf 'TELEGRAM_REQUIRE_MENTION=true\n'
  printf 'TELEGRAM_EXCLUSIVE_BOT_MENTIONS=true\n'
  printf 'TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES=false\n'
} >"$telegram_env"
chmod 600 "$telegram_env"
cp "$telegram_env" "$invalid_telegram_env"
chmod 644 "$invalid_telegram_env"

reset_external_logs
env PATH="$fake_bin:$PATH" \
  "$repo_root/installer/install.sh" plan telegram \
    --telegram-state enabled --host 192.0.2.44 --ssh-user ubuntu \
    --ssh-public-key "$public_key" --ssh-private-key "$private_key" \
    --telegram-env "$telegram_env" --gateway-profile manager \
    >"$fixture_root/telegram-enabled.out"

[[ ! -s "$terraform_log" ]] || fail "targeted Telegram plan must not invoke Terraform"
[[ ! -s "$ssh_log" ]] || fail "targeted Telegram plan must not contact SSH"
grep -q -- '--syntax-check' "$ansible_log" \
  || fail "targeted enabled Telegram plan must syntax-check Ansible"
grep -q -- '/ansible/telegram_gateway.yml' "$ansible_log" \
  || fail "targeted enabled Telegram plan must use only the Telegram playbook"
grep -q -- '/ansible/telegram_verify.yml' "$ansible_log" \
  || fail "targeted enabled Telegram plan must syntax-check the verification playbook"
[[ "$(wc -l <"$ansible_log" | tr -d ' ')" -eq 2 ]] \
  || fail "targeted Telegram plan must syntax-check exactly two targeted playbooks"
grep -q -- 'hermes_telegram_state=enabled' "$ansible_log" \
  || fail "targeted enabled Telegram plan must pass the requested state"
grep -q -- "hermes_telegram_env_source=$telegram_env" "$ansible_log" \
  || fail "targeted enabled Telegram plan must pass only the protected source path"
grep -q -- 'hermes_gateway_profile=manager' "$ansible_log" \
  || fail "targeted enabled Telegram plan must pass the selected profile"
! grep -q -- '/ansible/site.yml' "$ansible_log" \
  || fail "targeted Telegram plan must not run the base site playbook"
! grep -q 'fixture_value_abcdefghijklmnop\|101,202\|-1001,-1002' "$ansible_log" \
  || fail "targeted Telegram plan must not log protected Telegram values"
grep -q 'Telegram Ansible syntax plan completed; no host connection was attempted.' \
  "$fixture_root/telegram-enabled.out" \
  || fail "targeted enabled Telegram plan must report its no-host boundary"
printf 'PASS targeted enabled Telegram plan performs only local Telegram syntax validation\n'

reset_external_logs
env PATH="$fake_bin:$PATH" \
  "$repo_root/installer/install.sh" plan telegram \
    --telegram-state disabled --host 192.0.2.44 --ssh-user ubuntu \
    --ssh-public-key "$public_key" --ssh-private-key "$private_key" \
    >"$fixture_root/telegram-disabled.out"

[[ ! -s "$terraform_log" ]] || fail "disabled Telegram plan must not invoke Terraform"
[[ ! -s "$ssh_log" ]] || fail "disabled Telegram plan must not contact SSH"
grep -q -- '/ansible/telegram_gateway.yml' "$ansible_log" \
  || fail "disabled Telegram plan must use the Telegram playbook"
grep -q -- '/ansible/telegram_verify.yml' "$ansible_log" \
  || fail "disabled Telegram plan must syntax-check the verification playbook"
[[ "$(wc -l <"$ansible_log" | tr -d ' ')" -eq 2 ]] \
  || fail "disabled Telegram plan must syntax-check exactly two targeted playbooks"
grep -q -- 'hermes_telegram_state=disabled' "$ansible_log" \
  || fail "disabled Telegram plan must pass disabled state"
grep -q -- 'hermes_telegram_env_source=' "$ansible_log" \
  || fail "disabled Telegram plan must pass an empty Telegram input source"
grep -q -- 'hermes_gateway_profile=' "$ansible_log" \
  || fail "disabled Telegram plan must pass an empty gateway profile"
printf 'PASS targeted disabled Telegram plan carries no protected Telegram input\n'

reset_external_logs
set +e
MISMATCH_KEYPAIR=1 env PATH="$fake_bin:$PATH" \
  "$repo_root/installer/install.sh" plan telegram \
    --telegram-state enabled --host 192.0.2.44 --ssh-user ubuntu \
    --ssh-public-key "$public_key" --ssh-private-key "$private_key" \
    --telegram-env "$telegram_env" --gateway-profile manager \
    >"$fixture_root/telegram-keypair-mismatch.out" 2>&1
telegram_keypair_status=$?
set -e

[[ "$telegram_keypair_status" -ne 0 ]] \
  || fail "targeted Telegram plan must reject mismatched keypairs"
assert_no_external_tools
grep -q 'SSH public and private keys do not match' \
  "$fixture_root/telegram-keypair-mismatch.out" \
  || fail "targeted Telegram keypair mismatch must identify the contract"
printf 'PASS targeted Telegram plan rejects keypair mismatch before Ansible\n'

reset_external_logs
set +e
env PATH="$fake_bin:$PATH" \
  "$repo_root/installer/install.sh" plan telegram \
    --telegram-state enabled --host 192.0.2.44 --ssh-user ubuntu \
    --ssh-public-key "$public_key" --ssh-private-key "$private_key" \
    --telegram-env "$invalid_telegram_env" --gateway-profile manager \
    >"$fixture_root/telegram-invalid-input.out" 2>&1
telegram_invalid_input_status=$?
set -e

[[ "$telegram_invalid_input_status" -ne 0 ]] \
  || fail "targeted Telegram plan must reject invalid protected input"
assert_no_external_tools
[[ ! -s "$ssh_keygen_log" ]] \
  || fail "invalid Telegram input must fail before SSH key validation"
grep -q -- '--telegram-env failed the protected Telegram input contract' \
  "$fixture_root/telegram-invalid-input.out" \
  || fail "invalid Telegram input must identify the protected input contract"
printf 'PASS invalid Telegram input fails before key, Terraform, Ansible, or SSH tools\n'

reset_external_logs
env PATH="$fake_bin:$PATH" HCLOUD_TOKEN="test-only-token" \
  "$repo_root/installer/install.sh" plan new --location hel1 --server-type cx23 \
    --hcloud-ssh-key-name Luk --ssh-public-key "$public_key" \
    --ssh-source-cidr 192.0.2.10/32 --telegram-env "$telegram_env" \
    --gateway-profile manager >/dev/null

grep -q -- 'hermes_telegram_state=enabled' "$ansible_log" \
  || fail "full new-host plan with Telegram options must pass enabled state"
grep -q -- "hermes_telegram_env_source=$telegram_env" "$ansible_log" \
  || fail "full new-host plan with Telegram options must pass only source path"
grep -q -- 'hermes_gateway_profile=manager' "$ansible_log" \
  || fail "full new-host plan with Telegram options must pass gateway profile"
printf 'PASS full new-host plan forwards a complete Telegram option pair\n'

reset_external_logs
env PATH="$fake_bin:$PATH" \
  "$repo_root/installer/install.sh" plan existing \
    --host 192.0.2.44 --ssh-user ubuntu --ssh-private-key "$private_key" \
    --ssh-public-key "$public_key" --ssh-source-cidr 192.0.2.10/32 \
    --telegram-env "$telegram_env" --gateway-profile manager >/dev/null

grep -q -- 'hermes_telegram_state=enabled' "$ansible_log" \
  || fail "full existing-host plan with Telegram options must pass enabled state"
printf 'PASS full existing-host plan forwards a complete Telegram option pair\n'

reset_external_logs
env PATH="$fake_bin:$PATH" \
  "$repo_root/installer/install.sh" plan existing \
    --host 192.0.2.44 --ssh-user ubuntu --ssh-private-key "$private_key" \
    --ssh-public-key "$public_key" --ssh-source-cidr 192.0.2.10/32 >/dev/null

! grep -q -- 'hermes_telegram_' "$ansible_log" \
  || fail "full existing-host plan without Telegram options must preserve its Ansible invocation"
printf 'PASS full existing-host plan remains backward compatible without Telegram options\n'
