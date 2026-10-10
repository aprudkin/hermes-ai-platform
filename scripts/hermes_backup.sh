#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
temporary_archive=''

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_var() {
  local name="$1"
  [[ -n "${!name:-}" ]] || fail "${name} must be set"
}

require_file() {
  local name="$1"
  require_var "$name"
  [[ -f "${!name}" ]] || fail "${name} must name an existing regular file"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

resolve_deploy_host() {
  if [[ -n "${HERMES_DEPLOY_HOST:-}" ]]; then
    return
  fi

  require_command terraform
  HERMES_DEPLOY_HOST="$(terraform -chdir="$repo_root/terraform" output -raw server_ipv4)" \
    || fail "failed to resolve HERMES_DEPLOY_HOST from Terraform state"
  require_var HERMES_DEPLOY_HOST
}

main() {
  local backup_dir timestamp archive
  local scope=personal prefix=hermes-personal
  local guide="$repo_root/docs/personal-backup.md"
  local remote_command='python3 - capture /opt/hermes hermes personal'
  local description='Hermes personal-state backup'

  if [[ "$#" -eq 1 && "${1:-}" == --full ]]; then
    scope=full
    prefix=hermes-recovery
    guide="$repo_root/docs/backup-restore.md"
    remote_command='python3 - capture /opt/hermes hermes'
    description='portable Hermes recovery bundle'
  elif [[ "$#" -ne 0 ]]; then
    fail "usage: hermes_backup.sh [--full] (default: personal state)"
  fi

  umask 077
  require_command ssh
  require_command python3
  require_var HERMES_DEPLOY_SSH_USER
  require_file HERMES_DEPLOY_SSH_PRIVATE_KEY
  resolve_deploy_host

  backup_dir="${HERMES_BACKUP_DIR:-$HOME/backup/hermer}"
  mkdir -p -- "$backup_dir"
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  archive="$backup_dir/$prefix-$timestamp-$$.tar.gz"
  temporary_archive="$(mktemp "$backup_dir/.$prefix-$timestamp.XXXXXX")"
  trap 'if [[ -n "${temporary_archive:-}" ]]; then rm -f -- "$temporary_archive"; fi' EXIT

  printf 'Creating %s at %s\n' "$description" "$archive"
  python3 "$repo_root/scripts/hermes_backup_bundle.py" program "$guide" | ssh \
    -i "$HERMES_DEPLOY_SSH_PRIVATE_KEY" \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=accept-new \
    "$HERMES_DEPLOY_SSH_USER@$HERMES_DEPLOY_HOST" \
    "$remote_command" >"$temporary_archive"

  [[ -s "$temporary_archive" ]] || fail "remote backup archive is empty"
  python3 "$repo_root/scripts/hermes_backup_bundle.py" verify "$temporary_archive" "$scope"
  mv -- "$temporary_archive" "$archive"
  printf 'Backup verified: %s\n' "$archive"
}

main "$@"
