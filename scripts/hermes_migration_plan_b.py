#!/usr/bin/env python3
"""Portable owner Plan B. Python 3 stdlib + OpenSSH, no repository imports.

Default/--check reads Docker status only. --rollback submits intent to the ONE
source host controller; it cannot bypass fencing, delta or acceptance gates.
No production controller/site adapter is installed by this script.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

CONTROLLER = "/usr/local/lib/hermes-migration/hermes_migration_controller.py"
PROBE = "sudo -n docker container ls --all --filter 'name=^/hermes$' --format '{{json .State}}'"
FALLBACK = (
    "Do not start source. Use the verified target provider console to stop/fence "
    "Hermes and its restart/recreation writers persistently; retain its disks. "
    "Restore controller access, preserve target delta and reconcile replay/jobs "
    "through the reviewed controller. SSH timeout is not a fence."
)


class Refused(Exception):
    pass


def execute(args):
    try:
        result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=35, check=True)
        if len(result.stdout) > 16384:
            raise Refused("oversized remote response")
        return result.stdout.decode("utf-8")
    except (OSError, UnicodeError, subprocess.SubprocessError):
        raise Refused("SSH/controller unavailable; diagnostics withheld") from None


def ssh_args(args, alias, command):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", alias):
        raise Refused("use a literal SSH alias, not options, user@host or shell text")
    result = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
              "-o", "ForwardAgent=no", "-o", "IdentitiesOnly=yes",
              "-o", "ControlMaster=no", "-o", "ControlPath=none",
              "-o", "ConnectTimeout=10", "-o", "ConnectionAttempts=1",
              "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=2",
              "-o", "ClearAllForwardings=yes", "-o", "RequestTTY=no"]
    for option, value in (("-F", args.ssh_config), ("-i", args.identity)):
        if value:
            if not Path(value).is_file():
                raise Refused("supplied SSH file is unavailable")
            result += [option, str(Path(value).absolute())]
    if args.known_hosts:
        if not Path(args.known_hosts).is_file():
            raise Refused("supplied known-hosts file is unavailable")
        result += ["-o", "UserKnownHostsFile=" + str(Path(args.known_hosts).absolute())]
    return result + [alias, command]


def remote_status(text):
    value = json.loads(text)
    phases = {"FENCING_TARGET", "PRESERVING_DELTA", "RECONCILING", "RESUMING_SOURCE",
              "ROLLED_BACK", "RECOVERING_SOURCE", "ABORTED"}
    if (not isinstance(value, dict) or value.get("version") != 3
            or value.get("phase") not in phases
            or not isinstance(value.get("run_id"), str)
            or not re.fullmatch(r"[0-9a-f]{32}", value["run_id"])):
        raise Refused("invalid controller status")
    return {"phase": value["phase"], "run_id": value.get("run_id")}


def run(argv=None, runner=execute):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="verified source SSH alias")
    parser.add_argument("--target", required=True, help="verified target SSH alias")
    parser.add_argument("--ssh-config")
    parser.add_argument("--identity")
    parser.add_argument("--known-hosts")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true", help="read-only (default)")
    modes.add_argument("--rollback", action="store_true", help="request, never bypass, safe rollback")
    parser.add_argument("--confirm-request", action="store_true")
    parser.add_argument("--run-id", help="exact run ID from this run's readiness notice")
    args = parser.parse_args(argv)
    # Validate both before making even the first connection.
    probes = {name: ssh_args(args, getattr(args, name), PROBE) for name in ("source", "target")}
    if args.source == args.target:
        raise Refused("source and target aliases must differ")
    if args.rollback:
        if not args.confirm_request:
            raise Refused("rollback intent requires --confirm-request; no action taken")
        if not re.fullmatch(r"[0-9a-f]{32}", args.run_id or ""):
            raise Refused("rollback requires exact --run-id; no action taken")
        request = "sudo -n python3 " + CONTROLLER + " request-rollback --execute --run-id " + args.run_id
        requested = remote_status(runner(ssh_args(args, args.source, request)))
        observed = remote_status(runner(ssh_args(args, args.source,
                                                "sudo -n python3 " + CONTROLLER + " status")))
        if requested["run_id"] != observed["run_id"] or observed["run_id"] != args.run_id:
            raise Refused("controller identity changed during request")
        return {"action": "rollback-requested", "controller": observed,
                "completed": observed["phase"] in ("ROLLED_BACK", "ABORTED"),
                "note": "Intent recorded only; external watchdog must advance the same run. " + FALLBACK}
    report = {"action": "check", "safe_to_start_source": False,
              "note": "Status is not fencing or deployment readiness. " + FALLBACK}
    for name, command in probes.items():
        try:
            text = runner(command)
            states = [json.loads(line) for line in text.splitlines() if line.strip()]
            if len(states) > 1 or any(state not in
                    ("created", "running", "paused", "restarting", "removing", "exited", "dead")
                    for state in states):
                raise Refused("unexpected Docker status")
            report[name] = {"reachable": True, "containers": len(states),
                            "state": states[0] if states else "absent"}
        except (Refused, ValueError, TypeError):
            report[name] = {"reachable": False, "state": "unknown"}
    return report


def main():
    try:
        result = run()
        print(json.dumps(result, sort_keys=True))
        return 0 if result["action"] != "check" or all(result[side]["reachable"] for side in ("source", "target")) else 2
    except (Refused, ValueError, OSError, TypeError):
        print("Plan B refused/unavailable; no direct source start. " + FALLBACK, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
