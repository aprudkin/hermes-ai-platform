#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
generated_dir="$repo_root/.generated"
terraform_dir="$repo_root/terraform"
playbook="$repo_root/ansible/site.yml"

usage() {
  cat <<'USAGE'
Usage:
  ./installer/install.sh validate
  ./installer/install.sh plan new --location fsn1|nbg1|hel1 --server-type TYPE --hcloud-ssh-key-name NAME --ssh-public-key PATH --ssh-source-cidr CIDR
  ./installer/install.sh plan existing --host HOST --ssh-user USER --ssh-private-key PATH --ssh-source-cidr CIDR
  ./installer/install.sh deploy new --location fsn1|nbg1|hel1 --server-type TYPE --hcloud-ssh-key-name NAME --ssh-public-key PATH \
    --ssh-private-key PATH --ssh-source-cidr CIDR --hermes-env PATH --model-provider PROVIDER --model MODEL --confirm-external-mutation
  ./installer/install.sh deploy existing --host HOST --ssh-user USER \
    --ssh-private-key PATH --ssh-source-cidr CIDR --hermes-env PATH --model-provider PROVIDER --model MODEL --confirm-external-mutation

The plan commands perform local validation. The new-server plan also runs
terraform plan and requires HCLOUD_TOKEN in the environment. Deploy commands
mutate cloud or a real host and refuse to run without the explicit confirmation
flag. Secrets are read from protected environment/files, never CLI values.
USAGE
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

need_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

need_file() {
  [[ -f "$1" ]] || die "required file not found: $1"
}

validate_location() {
  case "$1" in
    fsn1 | nbg1 | hel1) ;;
    *) die "--location must be exactly fsn1, nbg1, or hel1" ;;
  esac
}

validate_server_type() {
  [[ "$1" =~ ^[a-z][a-z0-9-]*$ ]] \
    || die "--server-type must be a non-empty Hetzner Cloud server type name"
}

validate_host() {
  [[ -n "$1" ]] || die "--host is required"
  [[ "$1" =~ ^[A-Za-z0-9.-]+$ ]] || die "--host must be an IPv4 address or DNS name"
}

validate_user() {
  [[ "$1" =~ ^[a-z_][a-z0-9_-]*$ ]] || die "--ssh-user is invalid"
}

validate_key_path() {
  local key_path="$1"
  need_file "$key_path"
  [[ "$key_path" != *[[:space:]]* ]] || die "SSH key paths containing whitespace are not supported"
}

validate_public_key() {
  local key_path="$1"
  validate_key_path "$key_path"
  grep -Eq '^(ssh-(rsa|ed25519)|ecdsa-sha2-nistp(256|384|521))[[:space:]]+[A-Za-z0-9+/=]+' "$key_path" \
    || die "--ssh-public-key is not a recognized OpenSSH public key"
}

validate_cidr() {
  command -v python3 >/dev/null 2>&1 || die "python3 is required to validate CIDRs"
  python3 -c 'import ipaddress, sys; ipaddress.ip_network(sys.argv[1], strict=False)' "$1" \
    >/dev/null 2>&1 || die "--ssh-source-cidr must be a valid IPv4 or IPv6 CIDR"
}

cidrs_json() {
  local separator=""
  local result="["
  local cidr
  for cidr in "$@"; do
    result+="${separator}\"${cidr}\""
    separator=","
  done
  result+="]"
  printf '%s\n' "$result"
}

file_mode() {
  local source_file="$1"
  stat -c '%a' "$source_file" 2>/dev/null || stat -f '%Lp' "$source_file"
}

validate_hermes_env() {
  local source_file="$1"
  local model_provider="$2"
  local required_key
  local mode
  need_file "$source_file"
  mode="$(file_mode "$source_file")"
  case "$mode" in
    400 | 600) ;;
    *) die "--hermes-env must have mode 0400 or 0600 (found $mode)" ;;
  esac
  case "$model_provider" in
    openrouter) required_key="OPENROUTER_API_KEY" ;;
    anthropic) required_key="ANTHROPIC_API_KEY" ;;
    openai-api) required_key="OPENAI_API_KEY" ;;
    *) die "--model-provider must be openrouter, anthropic, or openai-api" ;;
  esac
  grep -Eq "^${required_key}=.+" "$source_file" \
    || die "--hermes-env does not contain the key required by --model-provider"
}

write_inventory() {
  local host="$1"
  local ssh_user="$2"
  local private_key="$3"
  local inventory_path="$generated_dir/ansible/inventory.ini"
  local known_hosts_path="$generated_dir/ansible/known_hosts"

  mkdir -p "$(dirname "$inventory_path")"
  umask 077
  touch "$known_hosts_path"
  printf "[hermes]\nhermes-host ansible_host=%s ansible_user=%s ansible_ssh_private_key_file=%s ansible_ssh_common_args='-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=%s'\n" \
    "$host" "$ssh_user" "$private_key" "$known_hosts_path" >"$inventory_path"
  printf '%s\n' "$inventory_path"
}

terraform_plan() {
  local location="$1"
  local server_type="$2"
  local public_key="$3"
  local hcloud_ssh_key_name="$4"
  local ssh_cidrs_json="$5"
  local plan_path="$generated_dir/terraform/hermes.tfplan"

  need_command terraform
  [[ -n "${HCLOUD_TOKEN:-}" ]] || die "HCLOUD_TOKEN must be set in the environment for terraform plan"
  mkdir -p "$(dirname "$plan_path")"
  terraform -chdir="$terraform_dir" init -backend=false -input=false
  terraform -chdir="$terraform_dir" validate
  TF_VAR_location="$location" TF_VAR_server_type="$server_type" \
  TF_VAR_ssh_public_key_path="$public_key" \
  TF_VAR_hcloud_ssh_key_name="$hcloud_ssh_key_name" \
  TF_VAR_ssh_source_cidrs="$ssh_cidrs_json" \
    terraform -chdir="$terraform_dir" plan -input=false -out="$plan_path"
  printf 'Plan saved to %s\n' "$plan_path"
}

ansible_syntax_plan() {
  local inventory_path="$1"
  need_command ansible-playbook
  ansible-playbook --syntax-check --inventory "$inventory_path" "$playbook" \
    --extra-vars "hermes_env_source=$repo_root/configs/hermes.env.example" \
    --extra-vars '{"hermes_ssh_source_cidrs":["192.0.2.10/32"]}'
  printf 'Ansible syntax plan completed; no host connection was attempted.\n'
}

run_ansible() {
  local inventory_path="$1"
  local env_file="$2"
  local model_provider="$3"
  local model="$4"
  local ssh_cidrs_json="$5"
  need_command ansible-playbook
  ANSIBLE_CONFIG="$repo_root/ansible/ansible.cfg" \
    ansible-playbook --inventory "$inventory_path" "$playbook" \
      --extra-vars "hermes_env_source=$env_file" \
      --extra-vars "hermes_model_provider=$model_provider" \
      --extra-vars "hermes_model=$model" \
      --extra-vars "{\"hermes_ssh_source_cidrs\":$ssh_cidrs_json}"
}

current_phase=""
last_completed_phase="none"
inventory_path=""

report_deploy_failure() {
  local status="$1"
  printf 'ERROR: Hermes Minimal deployment failed.\n' >&2
  printf 'Failed phase: %s\n' "$current_phase" >&2
  printf 'Last completed phase: %s\n' "$last_completed_phase" >&2
  printf '%s\n' \
    'Safe resume: fix the reported error, inspect any external state created by completed phases, then rerun the same confirmed deploy command. No automatic cleanup was attempted.' \
    >&2
  exit "$status"
}

run_phase() {
  local status
  current_phase="$1"
  shift
  set +e
  (set -e; "$@")
  status=$?
  set -e
  if [[ "$status" -ne 0 ]]; then
    report_deploy_failure "$status"
  fi
  last_completed_phase="$current_phase"
}

run_phase_capture() {
  local destination="$1"
  local captured
  local status
  current_phase="$2"
  shift 2
  set +e
  captured="$(set -e; "$@")"
  status=$?
  set -e
  if [[ "$status" -ne 0 ]]; then
    report_deploy_failure "$status"
  fi
  printf -v "$destination" '%s' "$captured"
  last_completed_phase="$current_phase"
}

apply_terraform_plan() {
  terraform -chdir="$terraform_dir" apply -input=false -auto-approve \
    "$generated_dir/terraform/hermes.tfplan"
}

deploy_new_target() {
  run_phase infrastructure-plan \
    terraform_plan "$location" "$server_type" "$public_key" "$hcloud_ssh_key_name" "$ssh_cidrs_json"
  run_phase provision apply_terraform_plan
  run_phase_capture host resolve-target \
    terraform -chdir="$terraform_dir" output -raw server_ipv4
  ssh_user="root"
}

deploy_runtime() {
  if [[ -z "$inventory_path" ]]; then
    run_phase_capture inventory_path inventory \
      write_inventory "$host" "$ssh_user" "$private_key"
  else
    last_completed_phase="inventory"
  fi
  run_phase configure \
    run_ansible "$inventory_path" "$hermes_env" "$model_provider" "$model" "$ssh_cidrs_json"
  run_phase verify \
    "$repo_root/scripts/validate.sh" --runtime --inventory "$inventory_path"
  printf 'Hermes Minimal deployment verified successfully.\n'
}

validate_common_request() {
  "$repo_root/scripts/validate.sh" --structure
  [[ "${#ssh_source_cidrs[@]}" -gt 0 ]] \
    || die "at least one --ssh-source-cidr is required"
  ssh_cidrs_json="$(cidrs_json "${ssh_source_cidrs[@]}")"
}

prepare_new_request() {
  validate_location "$location"
  [[ -n "$server_type" ]] || die "--server-type is required"
  validate_server_type "$server_type"
  [[ -n "$hcloud_ssh_key_name" ]] || die "--hcloud-ssh-key-name is required"
  [[ -n "$public_key" ]] || die "--ssh-public-key is required"
  validate_public_key "$public_key"
}

prepare_existing_request() {
  validate_host "$host"
  [[ -n "$ssh_user" ]] || die "--ssh-user is required"
  [[ -n "$private_key" ]] || die "--ssh-private-key is required"
  validate_user "$ssh_user"
  validate_key_path "$private_key"
  inventory_path="$(write_inventory "$host" "$ssh_user" "$private_key")"
}

validate_deploy_request() {
  [[ "$confirmed" == "true" ]] || die "deploy requires --confirm-external-mutation"
  [[ -n "$private_key" ]] || die "--ssh-private-key is required"
  [[ -n "$hermes_env" ]] || die "--hermes-env is required"
  [[ -n "$model_provider" ]] || die "--model-provider is required"
  [[ -n "$model" ]] || die "--model is required"
  if [[ "$target" == "new" ]]; then
    validate_key_path "$private_key"
  fi
  validate_hermes_env "$hermes_env" "$model_provider"
}

dispatch_plan() {
  case "$target" in
    new)
      terraform_plan "$location" "$server_type" "$public_key" "$hcloud_ssh_key_name" "$ssh_cidrs_json"
      ansible_syntax_plan "$repo_root/ansible/inventory.example.ini"
      ;;
    existing)
      ansible_syntax_plan "$inventory_path"
      ;;
  esac
}

dispatch_deploy() {
  last_completed_phase="request-validation"
  if [[ "$target" == "new" ]]; then
    deploy_new_target
  fi
  deploy_runtime
}

action="${1:-}"
target="${2:-}"
if [[ -z "$action" ]]; then
  usage
  exit 2
fi
if [[ "$action" == "validate" ]]; then
  [[ $# -eq 1 ]] || die "validate accepts no additional arguments"
  exec "$repo_root/scripts/validate.sh"
fi
if [[ "$action" != "plan" && "$action" != "deploy" ]]; then
  usage
  exit 2
fi
if [[ "$target" != "new" && "$target" != "existing" ]]; then
  usage
  exit 2
fi
shift 2

location=""
server_type=""
public_key=""
hcloud_ssh_key_name=""
private_key=""
host=""
ssh_user=""
hermes_env=""
model_provider=""
model=""
ssh_source_cidrs=()
confirmed="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --location | --server-type | --hcloud-ssh-key-name | --ssh-public-key | --ssh-private-key | --host | --ssh-user | --hermes-env | --model-provider | --model)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      option="$1"
      value="$2"
      shift 2
      case "$option" in
        --location) location="$value" ;;
        --server-type) server_type="$value" ;;
        --hcloud-ssh-key-name) hcloud_ssh_key_name="$value" ;;
        --ssh-public-key) public_key="$value" ;;
        --ssh-private-key) private_key="$value" ;;
        --host) host="$value" ;;
        --ssh-user) ssh_user="$value" ;;
        --hermes-env) hermes_env="$value" ;;
        --model-provider) model_provider="$value" ;;
        --model) model="$value" ;;
      esac
      ;;
    --confirm-external-mutation)
      confirmed="true"
      shift
      ;;
    --ssh-source-cidr)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      validate_cidr "$2"
      ssh_source_cidrs+=("$2")
      shift 2
      ;;
    *) die "unknown argument: $1" ;;
  esac
done

validate_common_request

if [[ "$target" == "new" ]]; then
  prepare_new_request
else
  prepare_existing_request
fi

case "$action" in
  plan)
    dispatch_plan
    ;;
  deploy)
    validate_deploy_request
    dispatch_deploy
    ;;
esac
