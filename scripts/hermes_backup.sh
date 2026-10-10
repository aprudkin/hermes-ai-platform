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

  umask 077
  require_command ssh
  require_command python3
  require_var HERMES_DEPLOY_SSH_USER
  require_file HERMES_DEPLOY_SSH_PRIVATE_KEY
  resolve_deploy_host

  backup_dir="${HERMES_BACKUP_DIR:-$HOME/backup/hermer}"
  mkdir -p -- "$backup_dir"
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  archive="$backup_dir/hermes-recovery-$timestamp-$$.tar.gz"
  temporary_archive="$(mktemp "$backup_dir/.hermes-recovery-$timestamp.XXXXXX")"
  trap 'if [[ -n "${temporary_archive:-}" ]]; then rm -f -- "$temporary_archive"; fi' EXIT

  printf 'Creating portable Hermes recovery bundle at %s\n' "$archive"
  python3 "$repo_root/scripts/hermes_backup_bundle.py" program \
    "$repo_root/docs/backup-restore.md" | ssh \
    -i "$HERMES_DEPLOY_SSH_PRIVATE_KEY" \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=accept-new \
    "$HERMES_DEPLOY_SSH_USER@$HERMES_DEPLOY_HOST" \
    'python3 - capture /opt/hermes hermes' >"$temporary_archive"

  [[ -s "$temporary_archive" ]] || fail "remote backup archive is empty"
  python3 "$repo_root/scripts/hermes_backup_bundle.py" verify "$temporary_archive"
  mv -- "$temporary_archive" "$archive"
  printf 'Backup verified: %s\n' "$archive"
}

main "$@"
