#!/usr/bin/env bash

set -euo pipefail
# shellcheck source=tests/test_helper.sh
# shellcheck disable=SC1091,SC2154
source "$(dirname "${BASH_SOURCE[0]}")/test_helper.sh"

# shellcheck disable=SC2154
compose_file="$repo_root/docker/docker-compose.yml"

assert_rendered_compose() {
  local expected_profile="$1"
  local rendered_file="$2"

  python3 - "$expected_profile" "$rendered_file" <<'PY'
import json
import sys

expected_profile, rendered_file = sys.argv[1:]
with open(rendered_file, encoding="utf-8") as source:
    rendered = json.load(source)

services = rendered.get("services")
if not isinstance(services, dict) or len(services) != 1:
    raise SystemExit("expected exactly one Compose service")

service = services.get("hermes")
if not isinstance(service, dict):
    raise SystemExit("expected the sole Compose service to be hermes")

command = service.get("command")
expected_command = ["hermes", "-p", expected_profile, "gateway", "run"]
if command != expected_command:
    raise SystemExit(f"expected command {expected_command!r}, got {command!r}")
if command.count("gateway") != 1 or command.count("run") != 1:
    raise SystemExit("gateway command must contain exactly one gateway and one run token")
if "ports" in service:
    raise SystemExit("gateway Compose service must not publish ports")
environment = service.get("environment")
required_telegram_environment = {
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_USERS",
    "TELEGRAM_ALLOWED_CHATS",
    "TELEGRAM_REQUIRE_MENTION",
    "TELEGRAM_EXCLUSIVE_BOT_MENTIONS",
    "TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES",
}
if not isinstance(environment, dict) or not required_telegram_environment.issubset(environment):
    raise SystemExit("gateway Compose service must expose the selected Telegram environment")
if environment.get("HERMES_TELEGRAM_DISABLE_FALLBACK_IPS") != "true":
    raise SystemExit("gateway Compose service must use direct Telegram DNS for the pinned image")
if environment.get("HOME") != "/opt/data":
    raise SystemExit("gateway Compose service must set the Hermes runtime home")
if environment.get("CODEX_HOME") != "/opt/data/.codex":
    raise SystemExit("gateway Compose service must set the Codex auth home")
if any(key.startswith("TELEGRAM_GROUP_") for key in environment):
    raise SystemExit("gateway Compose service must not expose group-wide authorization keys")
serialized = json.dumps(rendered).lower()
if "webhook" in serialized or "listener" in serialized:
    raise SystemExit("gateway Compose configuration must not add a webhook or listener")
PY
}

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  fixture_root="$(mktemp -d)"
  trap 'rm -rf "$fixture_root"' EXIT

  docker compose --file "$compose_file" config --format json >"$fixture_root/default.json"
  assert_rendered_compose default "$fixture_root/default.json"
  printf 'PASS Compose default profile renders -p default gateway run\n'

  HERMES_GATEWAY_PROFILE=manager \
    docker compose --file "$compose_file" config --format json >"$fixture_root/manager.json"
  assert_rendered_compose manager "$fixture_root/manager.json"
  printf 'PASS Compose selected profile renders -p manager gateway run\n'
else
  printf 'SKIP actual Compose rendering (runnable docker compose unavailable)\n'
  python3 - "$compose_file" <<'PY'
import re
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    compose = source.read()

expected = 'command: ["hermes", "-p", "${HERMES_GATEWAY_PROFILE:-default}", "gateway", "run"]'
if expected not in compose:
    raise SystemExit("expected explicit gateway profile command in Compose source")

services_match = re.search(r"^services:\n((?:^[^\n].*\n|^  .*\n)*)", compose, re.MULTILINE)
if services_match is None:
    raise SystemExit("expected Compose services mapping")
services = services_match.group(1)
service_names = re.findall(r"^  ([A-Za-z0-9_-]+):\n", services, re.MULTILINE)
if service_names != ["hermes"]:
    raise SystemExit(f"expected exactly one hermes service, got {service_names!r}")
if re.search(r"^    ports:\s*$", services, re.MULTILINE):
    raise SystemExit("gateway Compose service must not publish ports")
required_telegram_environment = (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_USERS",
    "TELEGRAM_ALLOWED_CHATS",
    "TELEGRAM_REQUIRE_MENTION",
    "TELEGRAM_EXCLUSIVE_BOT_MENTIONS",
    "TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES",
)
for key in required_telegram_environment:
    if re.search(rf"^      {key}:\s*", services, re.MULTILINE) is None:
        raise SystemExit(f"gateway Compose service must expose {key}")
if not re.search(
    r'^      HERMES_TELEGRAM_DISABLE_FALLBACK_IPS:\s*"true"\s*$',
    services,
    re.MULTILINE,
):
    raise SystemExit("gateway Compose service must disable the pinned image fallback-IP transport")
if not re.search(r'^      HOME:\s*"/opt/data"\s*$', services, re.MULTILINE):
    raise SystemExit("gateway Compose service must set the Hermes runtime home")
if not re.search(r'^      CODEX_HOME:\s*"/opt/data/\.codex"\s*$', services, re.MULTILINE):
    raise SystemExit("gateway Compose service must set the Codex auth home")
if "TELEGRAM_GROUP_" in services:
    raise SystemExit("gateway Compose service must not expose group-wide authorization keys")
if re.search(r"webhook|listener", services, re.IGNORECASE):
    raise SystemExit("gateway Compose configuration must not add a webhook or listener")
PY
  printf 'PASS fallback structural guard expects explicit -p profile gateway run\n'
fi
