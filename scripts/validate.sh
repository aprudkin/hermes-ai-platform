#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
mode="${1:---all}"
allow_missing_tools="false"
if [[ "$mode" == "--local" ]]; then
  allow_missing_tools="true"
fi

error() {
  printf 'ERROR: %s\n' "$*" >&2
  return 1
}

require_artifacts() {
  local required_files=(
    .gitignore
    configs/hermes.env.example
    terraform/versions.tf
    terraform/.terraform.lock.hcl
    terraform/variables.tf
    terraform/main.tf
    terraform/outputs.tf
    ansible/site.yml
    ansible/verify.yml
    ansible/requirements.yml
    docker/docker-compose.yml
    .github/workflows/validate.yml
    installer/install.sh
    profiles/manager/SOUL.md
    profiles/devops/SOUL.md
    profiles/coding/SOUL.md
    profiles/research/SOUL.md
    scripts/validate.sh
    tests/run.sh
  )
  local relative_path
  local failed=0

  for relative_path in "${required_files[@]}"; do
    if [[ ! -s "$repo_root/$relative_path" ]]; then
      error "required artifact is missing or empty: $relative_path" || true
      failed=1
    fi
  done
  [[ "$failed" -eq 0 ]]
  printf 'PASS repository structure\n'
}

need_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    if [[ "$allow_missing_tools" == "true" ]]; then
      printf 'SKIP %s (tool not installed)\n' "$2"
    else
      error "required command not found: $1"
    fi
    return 1
  fi
  if ! "$1" --version >/dev/null 2>&1; then
    if [[ "$allow_missing_tools" == "true" ]]; then
      printf 'SKIP %s (installed command is not runnable)\n' "$2"
    else
      error "required command is not runnable: $1"
    fi
    return 1
  fi
}

validate_shell() {
  local shell_files=()
  while IFS= read -r source_file; do
    shell_files+=("$source_file")
  done < <(find "$repo_root/installer" "$repo_root/scripts" "$repo_root/tests" -type f -name '*.sh' -print | sort)

  bash -n "${shell_files[@]}"
  printf 'PASS bash syntax\n'
  if need_command shellcheck "ShellCheck"; then
    shellcheck "${shell_files[@]}"
    printf 'PASS ShellCheck\n'
  elif [[ "$allow_missing_tools" != "true" ]]; then
    return 1
  fi
}

validate_terraform() {
  if ! need_command terraform "Terraform fmt/validate"; then
    if [[ "$allow_missing_tools" == "true" ]]; then
      return 0
    fi
    return 1
  fi
  terraform -chdir="$repo_root/terraform" fmt -check -recursive
  terraform -chdir="$repo_root/terraform" init -backend=false -input=false >/dev/null
  terraform -chdir="$repo_root/terraform" validate
  printf 'PASS Terraform fmt and validate\n'
}

validate_ansible() {
  if ! need_command ansible-playbook "Ansible syntax"; then
    if [[ "$allow_missing_tools" == "true" ]]; then
      return 0
    fi
    return 1
  fi
  ANSIBLE_CONFIG="$repo_root/ansible/ansible.cfg" \
    ansible-playbook --syntax-check \
      --inventory "$repo_root/ansible/inventory.example.ini" \
      "$repo_root/ansible/site.yml" \
      --extra-vars "hermes_env_source=$repo_root/configs/hermes.env.example" \
      --extra-vars "hermes_root_ssh_public_key_source=/dev/null"
  printf 'PASS Ansible syntax\n'

  if need_command ansible-lint "ansible-lint"; then
    (cd "$repo_root" && ansible-lint ansible/site.yml)
    printf 'PASS ansible-lint\n'
  elif [[ "$allow_missing_tools" != "true" ]]; then
    return 1
  fi
}

validate_compose() {
  if ! need_command docker "docker compose config"; then
    if [[ "$allow_missing_tools" == "true" ]]; then
      return 0
    fi
    return 1
  fi
  HERMES_DATA_DIR=/opt/hermes/data docker compose \
    --file "$repo_root/docker/docker-compose.yml" config --quiet
  printf 'PASS Docker Compose config\n'
}

validate_secrets() {
  local secret_pattern
  command -v rg >/dev/null 2>&1 \
    || { error "repository secret scan requires ripgrep (rg)"; return 1; }
  secret_pattern='-----BEGIN (OPENSSH|RSA|EC) PRIVATE KEY-----|^[[:space:]]*(HCLOUD_TOKEN|OPENROUTER_API_KEY|ANTHROPIC_API_KEY|OPENAI_API_KEY|TELEGRAM_BOT_TOKEN|DISCORD_BOT_TOKEN|SLACK_BOT_TOKEN|SLACK_APP_TOKEN|GITHUB_TOKEN|GH_TOKEN)=[^[:space:]#].*|gh[pousr]_[A-Za-z0-9_]{30,}|sk-ant-[A-Za-z0-9_-]{20,}|sk-(proj-)?[A-Za-z0-9_-]{20,}'
  if rg --hidden --glob '!.git/**' --glob '!terraform/.terraform/**' \
    --glob '!.generated/**' -- "$secret_pattern" "$repo_root" \
    | rg -v 'secret-scan: allow' >/dev/null; then
    error "a private key, populated credential, or token-shaped value was found in repository files"
  fi
  printf 'PASS repository secret-pattern scan\n'
}

validate_runtime() {
  local inventory_path=""
  shift
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --inventory) inventory_path="${2:-}"; shift 2 ;;
      *) error "unknown runtime validation argument: $1"; exit 2 ;;
    esac
  done
  [[ -n "$inventory_path" && -f "$inventory_path" ]] \
    || { error "runtime validation requires --inventory FILE"; exit 2; }
  command -v ansible-playbook >/dev/null 2>&1 \
    || { error "runtime validation requires ansible-playbook"; exit 1; }
  ANSIBLE_CONFIG="$repo_root/ansible/ansible.cfg" \
    ansible-playbook --inventory "$inventory_path" "$repo_root/ansible/verify.yml"
  printf 'PASS remote runtime and profile probes\n'
}

case "$mode" in
  --structure)
    require_artifacts
    ;;
  --static)
    require_artifacts
    validate_shell
    validate_terraform
    validate_ansible
    validate_compose
    validate_secrets
    ;;
  --secrets)
    validate_secrets
    ;;
  --all)
    require_artifacts
    validate_shell
    validate_terraform
    validate_ansible
    validate_compose
    validate_secrets
    bash "$repo_root/tests/run.sh"
    printf 'PASS behavioral tests\n'
    ;;
  --local)
    require_artifacts
    validate_shell
    validate_terraform
    validate_ansible
    validate_compose
    validate_secrets
    bash "$repo_root/tests/run.sh"
    printf 'PASS locally available validation and behavioral tests\n'
    ;;
  --runtime)
    validate_runtime "$@"
    ;;
  *)
    error "Usage: scripts/validate.sh [--all|--local|--structure|--static|--secrets|--runtime ...]"
    exit 2
    ;;
esac
