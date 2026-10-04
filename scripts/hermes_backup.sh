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
  require_command gzip
  require_command tar
  require_var HERMES_DEPLOY_SSH_USER
  require_file HERMES_DEPLOY_SSH_PRIVATE_KEY
  resolve_deploy_host

  backup_dir="${HERMES_BACKUP_DIR:-$HOME/backup/hermer}"
  mkdir -p -- "$backup_dir"
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  archive="$backup_dir/hermes-data-$timestamp-$$.tar.gz"
  temporary_archive="$(mktemp "$backup_dir/.hermes-data-$timestamp.XXXXXX")"
  trap 'if [[ -n "${temporary_archive:-}" ]]; then rm -f -- "$temporary_archive"; fi' EXIT

  printf 'Creating consistent backup at %s\n' "$archive"
  ssh \
    -i "$HERMES_DEPLOY_SSH_PRIVATE_KEY" \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=accept-new \
    "$HERMES_DEPLOY_SSH_USER@$HERMES_DEPLOY_HOST" \
    'bash -s' >"$temporary_archive" <<'REMOTE_BACKUP'
set -euo pipefail

docker inspect --format '{{.State.Running}}' hermes | grep -qx true
docker inspect --format '{{.State.Paused}}' hermes | grep -qx false
pause_attempted=0
cleanup() {
  local status=$?
  if [[ "$pause_attempted" -eq 1 ]]; then
    docker unpause hermes >&2 || status=$?
  fi
  exit "$status"
}
trap cleanup EXIT
pause_attempted=1
docker pause hermes >&2
tar --numeric-owner --xattrs --acls -C /opt/hermes -czf - data
REMOTE_BACKUP

  [[ -s "$temporary_archive" ]] || fail "remote backup archive is empty"
  gzip --test "$temporary_archive"
  tar --list --gzip --file "$temporary_archive" >/dev/null
  mv -- "$temporary_archive" "$archive"
  printf 'Backup verified: %s\n' "$archive"
}

main "$@"
