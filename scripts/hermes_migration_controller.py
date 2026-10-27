#!/usr/bin/env python3
"""Durable cutover control kernel. No production site adapter is bundled.

Default CLI operations are read-only. See docs/migration-controller.md for the
adapter trust boundary and remaining deployment gates. Never run in Hermes.
"""
import contextlib
import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import signal
import stat
import subprocess
import sys
import tempfile
import time


class Refused(Exception):
    """Fixed, non-secret operator diagnostic."""


def require(condition, message):
    if not condition:
        raise Refused(message)


def clock_sample(now=None):
    """Linux suspend-aware elapsed time; boot identity survives process restart.

    Explicit `now` is a deterministic in-process test clock, never a CLI option.
    Mixing clock domains fails closed rather than resetting an elapsed budget.
    """
    if now is not None:
        return {"wall": now, "elapsed": now, "boot": "injected-test-clock"}
    return {"wall": time.time(), "elapsed": time.clock_gettime(time.CLOCK_BOOTTIME),
            "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip()}


def clock_valid(anchor, current):
    if not isinstance(anchor, dict) or anchor.get("boot") != current["boot"]:
        return False
    if not all(type(anchor.get(k)) in (int, float) and math.isfinite(anchor[k])
               for k in ("wall", "elapsed")):
        return False
    elapsed = current["elapsed"] - anchor["elapsed"]
    return elapsed >= 0 and abs(current["wall"] - anchor["wall"] - elapsed) <= 5


def expired(state, current, prefix):
    anchor = state.get(prefix + "_clock")
    return (not clock_valid(anchor, current)
            or current["wall"] >= state[prefix + "_deadline"]
            or current["elapsed"] - anchor["elapsed"] >=
            state[prefix + "_deadline"] - anchor["wall"])


def atomic_json(path, value):
    """Commit with fsync+rename+directory fsync; retain interrupted temps."""
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    with os.fdopen(fd, "w") as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(value, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(name, path)
    directory = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def valid_dialogue(state, evidence, now):
    """Evaluate authenticated adapter evidence, never infer delivery from DB text."""
    if not isinstance(evidence, dict):
        return False
    exact = {key: state[key] for key in ("run_id", "instance_id", "nonce", "owner_id", "chat_id")}
    exact.update(platform="telegram", chat_type="private", inbound_role="user",
                 response_role="assistant", reply_to=state["challenge_id"])
    if any(evidence.get(key) != value for key, value in exact.items()):
        return False
    ids = (evidence.get("inbound_id"), evidence.get("response_to"), evidence.get("response_id"))
    times = (evidence.get("inbound_at"), evidence.get("response_at"))
    if not all(type(value) is int for value in ids):
        return False
    if not all(type(value) in (int, float) for value in times):
        return False
    return (ids[0] > state["baseline"] and ids[1] == ids[0] and ids[2] > ids[0]
            and state["started_at"] < times[0] <= times[1] <= min(now, state["deadline"])
            and evidence.get("delivered") is True)


class Controller:
    def __init__(self, directory):
        self.directory = Path(directory)
        info = self.directory.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
                and info.st_mode & 0o077 == 0, "unsafe controller directory")
        self.path = self.directory / "state.json"

    @classmethod
    def create(cls, directory, owner_id, chat_id, timeout_seconds=1800, preparation_seconds=1800):
        require(isinstance(owner_id, str) and owner_id and isinstance(chat_id, str)
                and chat_id, "owner and chat must be explicit")
        require(type(timeout_seconds) is int and 60 <= timeout_seconds <= 86400,
                "timeout outside supported range")
        require(type(preparation_seconds) is int and 60 <= preparation_seconds <= 7200,
                "preparation timeout outside supported range")
        directory = Path(directory)
        directory.mkdir(mode=0o700, parents=False, exist_ok=False)
        atomic_json(directory / "state.json", {
            "version": 3, "run_id": secrets.token_hex(16), "phase": "PREPARED",
            "owner_id": owner_id, "chat_id": chat_id, "nonce": secrets.token_hex(24),
            "timeout_seconds": timeout_seconds, "preparation_seconds": preparation_seconds,
            "audit": [], "target_start_intent": False, "source_fence_intent": False,
        })
        return cls(directory)

    @contextlib.contextmanager
    def lock(self):
        fd = os.open(self.directory / "controller.lock",
                     os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            require(stat.S_ISREG(os.fstat(fd).st_mode), "unsafe controller lock")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Refused("controller busy") from None
            yield
        finally:
            os.close(fd)

    def load(self):
        fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as stream:
            info = os.fstat(stream.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                    and info.st_mode & 0o077 == 0, "unsafe controller state")
            value = json.load(stream)
        require(isinstance(value, dict) and value.get("version") == 3,
                "unsupported controller state; no automatic upgrade")
        require(value.get("phase") in {
            "PREPARED", "FENCING_SOURCE", "CAPTURING", "NOTIFYING_READY", "AWAITING_CONFIRM",
            "RESTORING", "STARTING_TARGET", "WAITING", "FENCING_TARGET", "PRESERVING_DELTA",
            "RECONCILING", "RESUMING_SOURCE", "RECOVERING_SOURCE", "ACCEPTED", "CANCELLED",
            "ROLLED_BACK", "ABORTED", "BLOCKED"}, "unknown controller phase; operator recovery required")
        require(isinstance(value.get("run_id"), str)
                and re.fullmatch(r"[0-9a-f]{32}", value["run_id"])
                and type(value.get("target_start_intent")) is bool
                and type(value.get("source_fence_intent")) is bool
                and isinstance(value.get("audit"), list), "invalid controller state")
        return value

    def commit(self, state, phase, now, **values):
        state.update(values)
        state["phase"] = phase
        state["audit"].append({"phase": phase, "at": now})
        atomic_json(self.path, state)

    def invoke(self, site, action, state):
        request = {**state, "operation_id": state["run_id"] + ":" + action}
        if action in ("source_fence", "capture", "notify_ready", "restore", "target_start"):
            request["effect_expires_at"] = state["prepare_deadline"]
            if action == "source_fence" and "freeze_latest" in state:
                request["effect_expires_at"] = min(state["freeze_latest"], state["prepare_deadline"])
        receipt = site.call(action, request)
        require(isinstance(receipt, dict) and receipt.get("run_id") == state["run_id"],
                "adapter receipt belongs to another run")
        return receipt

    def source_fenced(self, site, state):
        receipt = self.invoke(site, "source_probe", state)
        require(receipt.get("fenced") is True and receipt.get("writers_stopped") is True,
                "source fencing is not confirmed")

    def advance(self, site, now=None):
        """One durable transition; re-entry repeats only idempotent site operations."""
        live_clock = now is None
        current = clock_sample(now)
        now = current["wall"]
        with self.lock():
            state = self.load()
            phase = state["phase"]

            def preparation_expired():
                nonlocal now, current
                current = clock_sample(None if live_clock else now)
                now = current["wall"]
                if expired(state, current, "prepare"):
                    self.commit(state, "FENCING_TARGET", now, rollback_reason="preparation-timeout-or-clock")
                    return True
                return False
            if phase == "FENCING_SOURCE" and "freeze_latest" in state and (
                    not state["freeze_start"] <= now <= state["freeze_latest"]
                    or not clock_valid(state.get("prepare_clock"), current)):
                # No local intent proves this controller made no freeze request.
                # With intent, the remote effect is uncertain: revoke/fence, do not retry.
                self.commit(state, "FENCING_TARGET" if state["source_fence_intent"] else "BLOCKED",
                            now, rollback_reason="first-freeze-window-missed",
                            blocked_notice_delivered=False)
                return self.status()
            if phase in ("FENCING_SOURCE", "CAPTURING", "NOTIFYING_READY", "AWAITING_CONFIRM",
                         "RESTORING", "STARTING_TARGET") and expired(state, current, "prepare"):
                self.commit(state, "FENCING_TARGET", now, rollback_reason="preparation-timeout")
                return self.status()
            if phase == "PREPARED":
                receipt = self.invoke(site, "preflight", state)
                require(receipt.get("ready") is True
                        and receipt.get("contract") == "migration-site-v2",
                        "site preflight not approved")
                self.commit(state, "FENCING_SOURCE", now,
                            prepare_deadline=now + state["preparation_seconds"], prepare_clock=current)
            elif phase == "FENCING_SOURCE":
                if not state["source_fence_intent"]:
                    self.commit(state, "FENCING_SOURCE", now, source_fence_intent=True)
                current = clock_sample(None if live_clock else now)
                now = current["wall"]
                if preparation_expired() or ("freeze_latest" in state
                        and not state["freeze_start"] <= now <= state["freeze_latest"]):
                    if state["phase"] == "FENCING_SOURCE":
                        self.commit(state, "FENCING_TARGET", now, rollback_reason="first-freeze-window-missed")
                    return self.status()
                receipt = self.invoke(site, "source_fence", state)
                if preparation_expired():
                    return self.status()
                self.source_fenced(site, state)
                saved = receipt.get("saved_states_digest")
                require(isinstance(saved, str) and len(saved) == 64,
                        "prior writer state not saved")
                self.commit(state, "CAPTURING", now, saved_states_digest=saved)
            elif phase == "CAPTURING":
                self.source_fenced(site, state)
                if preparation_expired():
                    return self.status()
                receipt = self.invoke(site, "capture", state)
                if preparation_expired():
                    return self.status()
                require(receipt.get("verified") is True
                        and receipt.get("independent_copy_verified") is True
                        and receipt.get("archive_format") == "tar.gz"
                        and isinstance(receipt.get("archive_digest"), str)
                        and re.fullmatch(r"[0-9a-f]{64}", receipt["archive_digest"]),
                        "gzip capture and independent copy must verify with exact SHA256")
                self.source_fenced(site, state)
                self.commit(state, "NOTIFYING_READY", now, archive_digest=receipt["archive_digest"])
            elif phase == "NOTIFYING_READY":
                self.source_fenced(site, state)
                if preparation_expired():
                    return self.status()
                receipt = self.invoke(site, "notify_ready", state)
                if preparation_expired():
                    return self.status()
                require(receipt.get("delivered") is True
                        and all(receipt.get(k) == state[k] for k in
                                ("owner_id", "chat_id", "nonce", "archive_digest"))
                        and isinstance(receipt.get("notice_id"), str) and receipt["notice_id"],
                        "readiness notice delivery not confirmed")
                self.commit(state, "AWAITING_CONFIRM", now, ready_at=now,
                            notice_id=receipt["notice_id"])
            elif phase == "AWAITING_CONFIRM":
                pass  # No Telegram receiver; only the independent owner action can approve.
            elif phase == "RESTORING":
                self.source_fenced(site, state)
                if preparation_expired():
                    return self.status()
                receipt = self.invoke(site, "restore", state)
                if preparation_expired():
                    return self.status()
                require(receipt.get("verified") is True and receipt.get("fenced") is True
                        and type(receipt.get("message_highwater")) is int,
                        "offline restore or baseline not confirmed")
                self.commit(state, "STARTING_TARGET", now, baseline=receipt["message_highwater"])
            elif phase == "STARTING_TARGET":
                self.source_fenced(site, state)
                if preparation_expired():
                    return self.status()
                if not state["target_start_intent"]:
                    self.commit(state, "STARTING_TARGET", now, target_start_intent=True)
                if preparation_expired():
                    return self.status()
                receipt = self.invoke(site, "target_start", state)
                if preparation_expired():
                    return self.status()
                probe = self.invoke(site, "target_probe", state)
                if preparation_expired():
                    return self.status()
                started = receipt.get("started_at")
                require(type(started) in (int, float) and 0 < started <= now
                        and started < state["prepare_deadline"]
                        and receipt.get("running") is True and probe.get("running") is True
                        and receipt.get("instance_id") == probe.get("instance_id")
                        and bool(receipt.get("instance_id"))
                        and isinstance(receipt.get("challenge_id"), str) and receipt["challenge_id"],
                        "target startup not confirmed")
                self.commit(state, "WAITING", now, started_at=started,
                            instance_id=receipt["instance_id"], challenge_id=receipt["challenge_id"],
                            deadline=started + state["timeout_seconds"],
                            accept_deadline=started + state["timeout_seconds"],
                            accept_clock={**state["prepare_clock"], "wall": started,
                                "elapsed": state["prepare_clock"]["elapsed"] +
                                started - state["prepare_clock"]["wall"]})
            elif phase == "WAITING":
                if expired(state, current, "accept"):
                    self.commit(state, "FENCING_TARGET", now, rollback_reason="acceptance-timeout-or-clock")
                    return self.status()
                try:
                    receipt = self.invoke(site, "dialogue", state)
                except Refused:
                    current = clock_sample(None if live_clock else now)
                    if not expired(state, current, "accept"):
                        raise
                    receipt = {}  # An unreadable target is NOT acceptance or fencing.
                current = clock_sample(None if live_clock else now)
                now = current["wall"]
                if expired(state, current, "accept"):
                    self.commit(state, "FENCING_TARGET", now, rollback_reason="acceptance-timeout-or-clock")
                    return self.status()
                if valid_dialogue(state, receipt.get("evidence"), now):
                    self.commit(state, "ACCEPTED", now)
                elif now >= state["deadline"]:
                    self.commit(state, "FENCING_TARGET", now, rollback_reason="timeout")
            elif phase == "FENCING_TARGET":
                self.invoke(site, "target_fence", state)
                probe = self.target_fenced(site, state)
                no_activity = (not state["target_start_intent"]
                               and probe.get("no_target_activity_verified") is True)
                self.commit(state, "RECOVERING_SOURCE" if no_activity else "PRESERVING_DELTA", now)
            elif phase == "RECOVERING_SOURCE":
                probe = self.target_fenced(site, state)
                if probe.get("no_target_activity_verified") is not True:
                    self.commit(state, "PRESERVING_DELTA", now)
                    return self.status()
                receipt = self.invoke(site, "source_recover", state)
                require(all(receipt.get(k) is True for k in
                            ("running", "safe_to_resume", "cancelled_jobs_preserved", "replay_reviewed")),
                        "pre-cutover recovery not confirmed")
                probe = self.invoke(site, "source_probe", state)
                require(probe.get("running") is True, "source recovery probe failed")
                self.commit(state, "ABORTED", now)
            elif phase == "PRESERVING_DELTA":
                self.target_fenced(site, state)
                receipt = self.invoke(site, "preserve_delta", state)
                require(receipt.get("verified") is True
                        and receipt.get("independent_copy_verified") is True
                        and isinstance(receipt.get("delta_digest"), str)
                        and re.fullmatch(r"[0-9a-f]{64}", receipt["delta_digest"]),
                        "target delta not independently preserved with exact SHA256")
                self.commit(state, "RECONCILING", now, delta_digest=receipt["delta_digest"])
            elif phase == "RECONCILING":
                self.target_fenced(site, state)
                receipt = self.invoke(site, "reconcile", state)
                require(all(receipt.get(key) is True for key in
                            ("safe_to_resume", "cancelled_jobs_preserved", "replay_reviewed")),
                        "rollback replay or cancellations need operator review")
                self.commit(state, "RESUMING_SOURCE", now)
            elif phase == "RESUMING_SOURCE":
                self.target_fenced(site, state)
                receipt = self.invoke(site, "source_resume", state)
                probe = self.invoke(site, "source_probe", state)
                require(receipt.get("running") is True and probe.get("running") is True,
                        "source restart not confirmed")
                self.commit(state, "ROLLED_BACK", now)
            elif phase not in ("ACCEPTED", "CANCELLED", "ROLLED_BACK", "ABORTED", "BLOCKED"):
                raise Refused("unknown controller phase")
        return self.status()

    def confirm(self, request, *, owner_id, chat_id, now=None):
        """Called ONLY by a trusted owner-authenticated route, never by chat history.

        owner_id/chat_id are fixed by the installed forced-command enrollment,
        not taken from request. Possession of a nonce alone is not authentication.
        """
        current = clock_sample(now)
        now = current["wall"]
        with self.lock():
            state = self.load()
            require(state["phase"] in ("AWAITING_CONFIRM", "RESTORING", "STARTING_TARGET", "WAITING", "ACCEPTED"),
                    "not awaiting owner approval")
            require(owner_id == state["owner_id"] and chat_id == state["chat_id"],
                    "wrong enrolled owner or chat")
            require(isinstance(request, dict) and set(request) ==
                    {"run_id", "nonce", "archive_digest", "notice_id"}
                    and all(request[k] == state[k] for k in request),
                    "approval is not for this readiness notice")
            if "approved_at" in state:
                return self.status()  # exact authenticated retry, not a new approval
            require(state["ready_at"] <= now and not expired(state, current, "prepare"),
                    "approval outside readiness window")
            self.commit(state, "RESTORING", now, approved_at=now)
        return self.status()

    def cancel(self, now=None):
        """Disarm only: preserve current host states; never silently resume either."""
        with self.lock():
            state = self.load()
            require(state["phase"] not in ("ACCEPTED", "ROLLED_BACK", "ABORTED", "BLOCKED"), "run is terminal")
            if state["phase"] != "CANCELLED":
                self.commit(state, "CANCELLED", time.time() if now is None else now)
        return self.status()

    def rollback(self, now=None, run_id=None):
        """Record Plan B intent under the timer's lock, not a direct docker start."""
        with self.lock():
            state = self.load()
            require(run_id is None or run_id == state["run_id"], "rollback belongs to another run")
            require(state["phase"] not in ("PREPARED", "ACCEPTED", "CANCELLED", "ROLLED_BACK", "ABORTED", "BLOCKED"),
                    "rollback not allowed in this phase")
            if state["phase"] not in ("FENCING_TARGET", "PRESERVING_DELTA", "RECONCILING", "RESUMING_SOURCE", "RECOVERING_SOURCE"):
                self.commit(state, "FENCING_TARGET", time.time() if now is None else now,
                            rollback_reason="manual")
        return self.status()

    def target_fenced(self, site, state):
        receipt = self.invoke(site, "target_probe", state)
        require(receipt.get("running") is False and receipt.get("fenced") is True
                and receipt.get("writers_stopped") is True,
                "target fencing not confirmed; never start source on uncertainty")
        return receipt

    def scheduled(self, site, start_at, latest_start, clock=None, sleep=time.sleep):
        """One dated admission window. No catch-up freeze after a missed gate.

        Preflight must be read-only. BLOCKED is terminal for migration; a blocked
        notice can be retried with the same operation ID after interruption.
        """
        wall = clock or time.time
        require(start_at <= latest_start <= start_at + 60, "invalid start window")
        with self.lock():
            state = self.load()
            if state["phase"] == "PREPARED":
                now = wall()
                try:
                    require(start_at <= now <= latest_start, "outside scheduled start window")
                    receipt = self.invoke(site, "preflight", state)
                    require(receipt.get("ready") is True and receipt.get("contract") == "migration-site-v2",
                            "site preflight not approved")
                    now = wall()
                    require(start_at <= now <= latest_start, "preflight missed start window")
                except Refused:
                    self.commit(state, "BLOCKED", wall(), blocked_notice_delivered=False)
                else:
                    self.commit(state, "FENCING_SOURCE", now,
                                prepare_deadline=now + state["preparation_seconds"],
                                freeze_start=start_at, freeze_latest=latest_start,
                                prepare_clock=clock_sample(now if clock else None))
            if state["phase"] == "BLOCKED" and not state.get("blocked_notice_delivered"):
                receipt = self.invoke(site, "notify_blocked", state)
                require(receipt.get("delivered") is True and receipt.get("chat_id") == state["chat_id"],
                        "blocked notice not delivered; independent operator notification required")
                self.commit(state, "BLOCKED", wall(), blocked_notice_delivered=True)
        return self.watch(site, clock=clock, sleep=sleep)

    def resume(self, site, clock=None, sleep=time.sleep):
        """Boot recovery only; PREPARED must wait for its separately dated trigger."""
        if self.status()["phase"] == "PREPARED":
            return self.status()
        return self.watch(site, clock=clock, sleep=sleep)

    def watch(self, site, clock=None, sleep=time.sleep):
        """External supervisor loop; no schedule installation and no gateway dependency.

        Refusal retains the phase and retries; uncertainty is never permission
        to start either owner. Operator must monitor blocked phases externally.
        """
        while self.status()["phase"] not in ("ACCEPTED", "ABORTED", "CANCELLED", "ROLLED_BACK", "BLOCKED"):
            try:
                self.advance(site, now=clock() if clock else None)
            except Refused:
                print("migration: gate blocked; state retained", file=sys.stderr)
            sleep(5)
        return self.status()

    def status(self):
        # Atomic read: no lock file creation, no adapter calls, no state writes.
        state = self.load()
        return {key: state[key] for key in ("version", "run_id", "phase", "timeout_seconds")}


class CommandSite:
    """Pinned trusted executable, JSON stdin/stdout, bounded process-group lifetime.

    This transports real site operations; it does not implement production host
    fencing/capture. A SHA pin authenticates code identity, not correct behavior.
    The installed adapter and all its ancestors must be operator-controlled.
    """
    def __init__(self, executable, digest, timeout=60):
        self.executable = Path(executable)
        require(self.executable.is_absolute() and re.fullmatch(r"[0-9a-f]{64}", digest or ""),
                "absolute adapter path and SHA256 pin required")
        require(type(timeout) is int and 1 <= timeout <= 300, "invalid adapter timeout")
        self.digest, self.timeout = digest, timeout

    def call(self, action, request):
        info = self.executable.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and info.st_mode & 0o022 == 0 and info.st_mode & 0o100
                and hashlib.sha256(self.executable.read_bytes()).hexdigest() == self.digest,
                "untrusted or changed site adapter")
        # Adapter is trusted operator code. Never inherit API credentials or Python hooks.
        environment = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"}
        try:
            child = subprocess.Popen([str(self.executable), action], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     env=environment, start_new_session=True)
            try:
                try:
                    output, _ = child.communicate(json.dumps(request).encode(), timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(child.pid, signal.SIGKILL)
                    # Never drain inherited pipes or use Popen's unbounded __exit__.
                    # An escaped descendant/remote operation remains uncertain.
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        child.wait(timeout=0.2)
                    raise Refused("site operation timed out; effect uncertain") from None
                require(child.returncode == 0 and len(output) <= 65536, "site operation failed")
                result = json.loads(output)
                require(isinstance(result, dict), "invalid site response")
                return result
            finally:
                if child.stdin is not None:
                    child.stdin.close()
                if child.stdout is not None:
                    child.stdout.close()
        except (OSError, ValueError, subprocess.SubprocessError):
            raise Refused("site unavailable; diagnostics withheld") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "create", "advance", "watch", "scheduled", "resume", "request-rollback", "cancel", "confirm"))
    parser.add_argument("--state-dir", default="/var/lib/hermes-migration/current")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--owner-id")
    parser.add_argument("--chat-id")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--preparation-seconds", type=int, default=1800)
    parser.add_argument("--adapter")
    parser.add_argument("--adapter-sha256")
    parser.add_argument("--run-id")
    parser.add_argument("--start-at", type=int)
    parser.add_argument("--latest-start", type=int)
    args = parser.parse_args(argv)
    try:
        require(args.command == "status" or args.execute, "mutation requires --execute")
        if args.command == "create":
            controller = Controller.create(args.state_dir, args.owner_id, args.chat_id,
                                           args.timeout_seconds, args.preparation_seconds)
            result = controller.status()
        else:
            controller = Controller(args.state_dir)
            if args.command in ("advance", "watch", "scheduled", "resume"):
                require(bool(args.adapter), "reviewed site adapter required; none bundled")
                site = CommandSite(args.adapter, args.adapter_sha256)
                if args.command == "scheduled":
                    require(args.start_at is not None and args.latest_start is not None, "explicit dated window required")
                    result = controller.scheduled(site, args.start_at, args.latest_start)
                elif args.command == "resume":
                    result = controller.resume(site)
                else:
                    result = controller.watch(site) if args.command == "watch" else controller.advance(site)
            elif args.command == "request-rollback":
                require(bool(re.fullmatch(r"[0-9a-f]{32}", args.run_id or "")), "exact --run-id required")
                result = controller.rollback(run_id=args.run_id)
            elif args.command == "cancel":
                result = controller.cancel()
            elif args.command == "confirm":
                # Forced SSH command sets owner/chat itself; never parse SSH_ORIGINAL_COMMAND.
                raw = sys.stdin.buffer.read(4097)
                require(len(raw) <= 4096, "oversized approval")
                result = controller.confirm(json.loads(raw), owner_id=args.owner_id, chat_id=args.chat_id)
            else:
                result = controller.status()
        print(json.dumps(result, sort_keys=True))
        return 0
    except Refused as error:
        print("migration refused: " + str(error), file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError):
        print("migration refused: invalid or unavailable private state", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
