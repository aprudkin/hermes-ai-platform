#!/usr/bin/env python3
"""Local controller tests; synthetic hosts are NOT migration evidence."""
import importlib.util
import json
from pathlib import Path
import tempfile
import hashlib
import os
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts/hermes_migration_controller.py"


class FixtureSite:
    """Synthetic effect boundary, deliberately not a production backend."""
    def __init__(self):
        self.calls = []
        self.source_running = True
        self.target_running = False
        self.completed = {}

    def call(self, action, request):
        self.calls.append(action)
        run = request["run_id"]
        if action == "preflight":
            return {"run_id": run, "ready": True, "contract": "migration-site-v2"}
        if action == "source_probe":
            return {"run_id": run, "fenced": not self.source_running,
                    "running": self.source_running, "writers_stopped": not self.source_running}
        if action == "source_fence":
            self.source_running = False
            return {"run_id": run, "fenced": True, "writers_stopped": True,
                    "saved_states_digest": "a" * 64}
        if action == "capture":
            assert not self.source_running
            return {"run_id": run, "verified": True,
                    "independent_copy_verified": True, "archive_format": "tar.gz", "archive_digest": "b" * 64}
        if action == "notify_ready":
            return {"run_id": run, "delivered": True, "chat_id": request["chat_id"],
                    "owner_id": request["owner_id"], "nonce": request["nonce"],
                    "archive_digest": request["archive_digest"], "notice_id": "ready-fixture"}
        if action == "restore":
            assert not self.source_running and not self.target_running
            return {"run_id": run, "verified": True, "fenced": True,
                    "message_highwater": 100}
        if action == "target_start":
            assert not self.source_running
            self.target_running = True
            return self.completed.setdefault(action, {"run_id": run, "running": True,
                "instance_id": "instance-fixture", "started_at": 1000,
                "challenge_id": "challenge-fixture"})
        if action == "target_probe":
            return {"run_id": run, "running": self.target_running,
                    "instance_id": "instance-fixture"}
        raise AssertionError(action)


class ControllerTest(unittest.TestCase):
    def module(self):
        spec = importlib.util.spec_from_file_location("migration", MODULE)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_capture_stops_at_readiness_until_fresh_owner_approval(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            c = module.Controller.create(Path(tmp) / "run", "owner-fixture", "dm-fixture")
            site = FixtureSite()
            for _ in range(3):
                c.advance(site, now=1000)
            self.assertEqual(c.status()["phase"], "NOTIFYING_READY")
            self.assertNotIn("restore", site.calls)
            self.assertFalse(site.target_running)

    def approve(self, c, now: int | float | None = 1000):
        s = c.load()
        c.confirm({key: s[key] for key in
                   ("run_id", "nonce", "archive_digest", "notice_id")},
                  owner_id=s["owner_id"], chat_id=s["chat_id"], now=now)

    def start(self, c, site):
        for _ in range(4):
            c.advance(site, now=1000)
        self.assertEqual(c.status()["phase"], "AWAITING_CONFIRM")
        for _ in range(3):
            c.advance(site, now=1000)
        self.assertNotIn("restore", site.calls)
        self.approve(c)
        for _ in range(2):
            c.advance(site, now=1000)

    def test_cutover_orders_fence_capture_restore_and_start(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            c = module.Controller.create(Path(tmp) / "run", "owner-fixture", "dm-fixture")
            site = FixtureSite()
            self.assertTrue(hasattr(c, "advance"), "cutover state machine is missing")
            self.start(c, site)
            self.assertEqual(c.status()["phase"], "WAITING")
            self.assertFalse(site.source_running)
            self.assertTrue(site.target_running)
            self.assertLess(site.calls.index("source_fence"), site.calls.index("capture"))
            self.assertLess(site.calls.index("capture"), site.calls.index("target_start"))
            state = c.load()
            self.assertEqual(state["deadline"], 2800)
            self.assertEqual(state["baseline"], 100)
            self.assertEqual(state["audit"][-1]["phase"], "WAITING")

    def test_timeout_fences_target_preserves_delta_before_source_start(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            c = module.Controller.create(Path(tmp) / "run", "owner-fixture", "dm-fixture")
            site = FixtureSite()
            original = site.call

            def call(action, request):
                run = request["run_id"]
                if action == "dialogue":
                    return {"run_id": run, "evidence": None}
                if action == "target_fence":
                    site.calls.append(action)
                    site.target_running = False
                    return {"run_id": run, "fenced": True, "writers_stopped": True}
                if action == "target_probe" and not site.target_running:
                    return {"run_id": run, "running": False, "fenced": True, "writers_stopped": True}
                if action == "preserve_delta":
                    assert not site.target_running
                    site.calls.append(action)
                    return {"run_id": run, "verified": True, "independent_copy_verified": True,
                            "delta_digest": "d" * 64}
                if action == "reconcile":
                    site.calls.append(action)
                    return {"run_id": run, "safe_to_resume": True, "cancelled_jobs_preserved": True,
                            "replay_reviewed": True}
                if action == "source_resume":
                    assert not site.target_running
                    site.calls.append(action)
                    site.source_running = True
                    return {"run_id": run, "running": True}
                return original(action, request)

            site.call = call
            self.start(c, site)
            c.advance(site, now=2799)
            self.assertEqual(c.status()["phase"], "WAITING")
            for _ in range(5):
                c.advance(site, now=2800)
            self.assertEqual(c.status()["phase"], "ROLLED_BACK")
            self.assertTrue(site.source_running)
            self.assertFalse(site.target_running)
            self.assertLess(site.calls.index("target_fence"), site.calls.index("preserve_delta"))
            self.assertLess(site.calls.index("preserve_delta"), site.calls.index("source_resume"))
            self.assertEqual(c.load()["delta_digest"], "d" * 64)

    def waiting(self, directory):
        module = self.module()
        c = module.Controller.create(directory, "owner-fixture", "dm-fixture")
        site = FixtureSite()
        self.start(c, site)
        return module, c, site

    def evidence(self, c):
        s = c.load()
        return {"run_id": s["run_id"], "instance_id": s["instance_id"],
                "nonce": s["nonce"], "owner_id": s["owner_id"], "chat_id": s["chat_id"],
                "platform": "telegram", "chat_type": "private", "inbound_role": "user",
                "inbound_id": 101, "inbound_at": 1100, "reply_to": "challenge-fixture",
                "response_to": 101, "response_id": 102, "response_at": 1101,
                "response_role": "assistant", "delivered": True}

    def test_verified_new_owner_dialogue_accepts_and_never_rolls_back_later(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, c, site = self.waiting(Path(tmp) / "run")
            original = site.call
            site.call = lambda action, req: ({"run_id": req["run_id"], "evidence": self.evidence(c)}
                if action == "dialogue" else original(action, req))
            c.advance(site, now=1200)
            self.assertEqual(c.status()["phase"], "ACCEPTED")
            before = list(site.calls)
            c.advance(site, now=9000)
            self.assertEqual(site.calls, before)

    def test_dialogue_rejects_history_wrong_identity_outbound_and_unlinked_reply(self):
        variants = [
            {"run_id": "other"}, {"instance_id": "old-instance"}, {"nonce": "old"},
            {"owner_id": "stranger"}, {"chat_id": "other-dm"}, {"chat_type": "group"},
            {"platform": "other"}, {"inbound_role": "assistant"}, {"inbound_id": 100},
            {"inbound_at": 999}, {"response_to": 99}, {"response_id": 100},
            {"delivered": False}, {"reply_to": "old-challenge"},
            {"response_role": "tool"}, {"response_at": 1099}, {"response_at": 2801},
        ]
        for changes in variants:
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as tmp:
                _, c, site = self.waiting(Path(tmp) / "run")
                original = site.call
                site.call = lambda action, req: ({"run_id": req["run_id"],
                    "evidence": {**self.evidence(c), **changes}}
                    if action == "dialogue" else original(action, req))
                c.advance(site, now=1200)
                self.assertEqual(c.status()["phase"], "WAITING")

    def test_cancel_is_durable_and_manual_rollback_cannot_override_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp:
            module, c, site = self.waiting(Path(tmp) / "run")
            self.assertTrue(hasattr(c, "cancel"), "durable cancellation missing")
            c.cancel(now=1200)
            c = module.Controller(c.directory)
            self.assertEqual(c.status()["phase"], "CANCELLED")
            before = list(site.calls)
            c.advance(site, now=9999)
            with self.assertRaises(module.Refused):
                c.rollback(now=9999)
            self.assertEqual(site.calls, before)

    def test_manual_rollback_refuses_other_run_under_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            module, c, site = self.waiting(Path(tmp) / "run")
            with self.assertRaises(module.Refused):
                c.rollback(now=1200, run_id="b" * 32)
            self.assertEqual(c.status()["phase"], "WAITING")

    def test_manual_rollback_uses_same_fencing_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, c, _ = self.waiting(Path(tmp) / "run")
            self.assertTrue(hasattr(c, "rollback"), "manual rollback request missing")
            c.rollback(now=1200)
            self.assertEqual(c.status()["phase"], "FENCING_TARGET")
            c.rollback(now=1201)
            self.assertEqual(c.status()["phase"], "FENCING_TARGET")

    def test_unreachable_dialogue_after_deadline_requests_fencing_not_source_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            module, c, site = self.waiting(Path(tmp) / "run")
            original = site.call
            def unavailable(action, request):
                if action in ("dialogue", "target_fence", "target_probe"):
                    raise module.Refused("target unreachable")
                return original(action, request)
            site.call = unavailable
            c.advance(site, now=2800)
            self.assertEqual(c.status()["phase"], "FENCING_TARGET")
            with self.assertRaises(module.Refused):
                c.advance(site, now=2900)
            self.assertFalse(site.source_running)
            self.assertTrue(site.target_running)

    def test_interrupted_target_start_retries_same_operation_without_resetting_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = self.module()
            c = module.Controller.create(Path(tmp) / "run", "owner-fixture", "dm-fixture")
            site = FixtureSite()
            for _ in range(4):
                c.advance(site, now=1000)
            self.approve(c)
            c.advance(site, now=1000)
            original = site.call
            operation_ids = []
            def interrupt(action, request):
                result = original(action, request)
                if action == "target_start":
                    operation_ids.append(request["operation_id"])
                    if len(operation_ids) == 1:
                        raise KeyboardInterrupt("simulated controller termination after effect")
                return result
            site.call = interrupt
            with self.assertRaises(KeyboardInterrupt):
                c.advance(site, now=1000)
            c = module.Controller(c.directory)
            self.assertEqual(c.status()["phase"], "STARTING_TARGET")
            c.advance(site, now=2000)
            self.assertEqual(operation_ids[0], operation_ids[1])
            self.assertEqual(c.load()["deadline"], 2800)

    def test_lock_excludes_concurrent_manual_and_timer_operations(self):
        with tempfile.TemporaryDirectory() as tmp:
            module, c, site = self.waiting(Path(tmp) / "run")
            with c.lock(), self.assertRaises(module.Refused):
                module.Controller(c.directory).advance(site, now=2800)

    def test_command_adapter_executes_real_subprocess_and_suppresses_diagnostics(self):
        module = self.module()
        self.assertTrue(hasattr(module, "CommandSite"), "subprocess effect boundary missing")
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "adapter"
            executable.write_text('#!' + sys.executable + '\nimport json,sys\n'
                'request=json.load(sys.stdin)\n'
                'print(json.dumps({"run_id":request["run_id"], "ready":True}))\n')
            executable.chmod(0o700)
            digest = hashlib.sha256(executable.read_bytes()).hexdigest()
            site = module.CommandSite(executable, digest)
            self.assertEqual(site.call("preflight", {"run_id": "fixture"})["ready"], True)
            executable.write_text('#!' + sys.executable + '\nimport sys\n'
                                  'print("PRIVATE-DIAGNOSTIC",file=sys.stderr)\nsys.exit(1)\n')
            with self.assertRaises(module.Refused) as context:
                site.call("preflight", {"run_id": "fixture"})
            self.assertNotIn("PRIVATE-DIAGNOSTIC", str(context.exception))
            site = module.CommandSite(executable, hashlib.sha256(executable.read_bytes()).hexdigest())
            with self.assertRaises(module.Refused) as context:
                site.call("preflight", {"run_id": "fixture"})
            self.assertNotIn("PRIVATE-DIAGNOSTIC", str(context.exception))

    def test_preparation_timeout_aborts_without_starting_target(self):
        module = self.module()
        for steps in (1, 2, 3, 4):
            with self.subTest(steps=steps), tempfile.TemporaryDirectory() as tmp:
                c = module.Controller.create(Path(tmp) / "run", "owner-fixture", "dm-fixture")
                site = FixtureSite()
                for _ in range(steps):
                    c.advance(site, now=1000)
                original = site.call
                def recover(action, request):
                    if action in ("target_fence", "target_probe"):
                        return {"run_id": request["run_id"], "running": False,
                                "fenced": True, "writers_stopped": True,
                                "no_target_activity_verified": True}
                    if action == "source_recover":
                        site.source_running = True
                        return {"run_id": request["run_id"], "running": True,
                                "safe_to_resume": True, "cancelled_jobs_preserved": True,
                                "replay_reviewed": True}
                    return original(action, request)
                site.call = recover
                c.advance(site, now=2800)
                self.assertEqual(c.status()["phase"], "FENCING_TARGET")
                for _ in range(2):
                    c.advance(site, now=2801)
                self.assertEqual(c.status()["phase"], "ABORTED")
                self.assertTrue(site.source_running)
                self.assertFalse(site.target_running)
                c.advance(site, now=9000)
                with self.assertRaises(module.Refused):
                    c.rollback(now=9000)

    def test_confirmation_rejects_wrong_owner_chat_old_run_and_expired_nonce(self):
        module = self.module()
        for changes in ({"owner_id": "other"}, {"chat_id": "other"},
                        {"run_id": "old"}, {"nonce": "old"}, {"archive_digest": "old"},
                        {"notice_id": "old"}, {"now": 2800}, {"now": 999}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as tmp:
                c = module.Controller.create(Path(tmp) / "run", "owner-fixture", "dm-fixture")
                site = FixtureSite()
                for _ in range(4):
                    c.advance(site, now=1000)
                s = c.load()
                request = {k: changes.get(k, s[k]) for k in
                           ("run_id", "nonce", "archive_digest", "notice_id")}
                with self.assertRaises(module.Refused):
                    c.confirm(request, owner_id=changes.get("owner_id", s["owner_id"]),
                              chat_id=changes.get("chat_id", s["chat_id"]), now=changes.get("now", 1001))
                self.assertEqual(c.status()["phase"], "AWAITING_CONFIRM")

    def test_duplicate_confirmation_is_idempotent_but_never_revives_aborted_run(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            c = module.Controller.create(Path(tmp) / "run", "owner-fixture", "dm-fixture")
            site = FixtureSite()
            for _ in range(4):
                c.advance(site, now=1000)
            self.approve(c)
            before = c.path.read_bytes()
            self.approve(c, now=1001)
            self.assertEqual(c.path.read_bytes(), before)
            c.rollback(now=1002)
            with self.assertRaises(module.Refused):
                self.approve(c, now=1003)

    def test_watch_advances_outside_gateway_and_stops_at_terminal(self):
        module = self.module()
        self.assertTrue(hasattr(module.Controller, "watch"), "external watch loop missing")
        with tempfile.TemporaryDirectory() as tmp:
            _, c, site = self.waiting(Path(tmp) / "run")
            original = site.call
            site.call = lambda action, req: ({"run_id": req["run_id"], "evidence": self.evidence(c)}
                if action == "dialogue" else original(action, req))
            result = c.watch(site, clock=lambda: 1200, sleep=lambda seconds: None)
            self.assertEqual(result["phase"], "ACCEPTED")

    def test_target_stop_failure_never_reaches_source_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            module, c, site = self.waiting(Path(tmp) / "run")
            c.rollback(now=1200)
            original = site.call
            def fail_stop(action, request):
                if action == "target_fence":
                    return {"run_id": request["run_id"], "fenced": True}
                return original(action, request)  # probe still reports running
            site.call = fail_stop
            with self.assertRaises(module.Refused):
                c.advance(site, now=1201)
            self.assertFalse(site.source_running)
            self.assertEqual(c.status()["phase"], "FENCING_TARGET")

    def test_notice_failure_cannot_become_readiness(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            c = module.Controller.create(Path(tmp) / "run", "owner-fixture", "dm-fixture")
            site = FixtureSite()
            for _ in range(3):
                c.advance(site, now=1000)
            original = site.call
            site.call = lambda action, req: ({"run_id": req["run_id"], "delivered": False}
                if action == "notify_ready" else original(action, req))
            with self.assertRaises(module.Refused):
                c.advance(site, now=1001)
            self.assertEqual(c.status()["phase"], "NOTIFYING_READY")
            self.assertNotIn("restore", site.calls)

    def test_each_forward_effect_interruption_reuses_operation_id(self):
        module = self.module()
        for action in ("source_fence", "capture", "notify_ready", "restore"):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as tmp:
                c = module.Controller.create(Path(tmp) / "run", "owner-fixture", "dm-fixture")
                site = FixtureSite()
                original = site.call
                ids = []
                def interrupt(current, request):
                    result = original(current, request)
                    if current == action:
                        ids.append(request["operation_id"])
                        if len(ids) == 1:
                            raise KeyboardInterrupt("fixture crash after effect")
                    return result
                site.call = interrupt
                for _ in range(10):
                    if c.status()["phase"] == "AWAITING_CONFIRM":
                        self.approve(c)
                    try:
                        c.advance(site, now=1000)
                    except KeyboardInterrupt:
                        c = module.Controller(c.directory)
                    if c.status()["phase"] == "WAITING":
                        break
                self.assertEqual(c.status()["phase"], "WAITING")
                self.assertEqual(len(ids), 2)
                self.assertEqual(ids[0], ids[1])

    def test_real_clock_start_receipt_can_be_later_than_transition_entry(self):
        import time
        module = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            c = module.Controller.create(Path(tmp) / "run", "owner-fixture", "dm-fixture")
            site = FixtureSite()
            for _ in range(4):
                c.advance(site)
            self.approve(c, now=None)
            c.advance(site)
            original = site.call
            def start_now(action, request):
                result = original(action, request)
                if action == "target_start":
                    result["started_at"] = time.time()
                return result
            site.call = start_now
            c.advance(site)
            self.assertEqual(c.status()["phase"], "WAITING")

    def test_scheduled_entry_never_freezes_early_late_or_unready(self):
        module = self.module()
        self.assertTrue(hasattr(module.Controller, "scheduled"), "one-shot gated entry missing")
        for now, ready in ((999, True), (1002, True), (1000, False)):
            with self.subTest(now=now, ready=ready), tempfile.TemporaryDirectory() as tmp:
                c = module.Controller.create(Path(tmp) / "run", "owner-fixture", "dm-fixture")
                site = FixtureSite()
                original = site.call
                def gate(action, request):
                    if action == "notify_blocked":
                        site.calls.append(action)
                        return {"run_id": request["run_id"], "delivered": True,
                                "chat_id": request["chat_id"]}
                    result = original(action, request)
                    if action == "preflight":
                        result["ready"] = ready
                    return result
                site.call = gate
                c.scheduled(site, 1000, 1001, clock=lambda: now, sleep=lambda seconds: None)
                self.assertEqual(c.status()["phase"], "BLOCKED")
                self.assertNotIn("source_fence", site.calls)
                self.assertIn("notify_blocked", site.calls)
                self.assertTrue(site.source_running)
                self.assertTrue(c.load()["blocked_notice_delivered"])
                before = list(site.calls)
                c.scheduled(site, 1000, 1001, clock=lambda: 1000, sleep=lambda seconds: None)
                self.assertEqual(site.calls, before)

    def test_one_shot_units_are_dated_nonpersistent_and_external(self):
        timer = ROOT / "systemd/hermes-migration.timer"
        service = ROOT / "systemd/hermes-migration.service"
        self.assertTrue(timer.is_file() and service.is_file(), "reviewable one-shot units missing")
        text = timer.read_text()
        self.assertIn("OnCalendar=2026-10-28 10:00:00 Europe/Moscow", text)
        self.assertIn("Persistent=false", text)
        self.assertNotIn("OnUnitActiveSec", text)
        text = service.read_text()
        self.assertIn("ConditionVirtualization=!container", text)
        self.assertIn("scheduled --execute", text)
        self.assertIn("--start-at 1793170800 --latest-start 1793170860", text)
        self.assertIn("Restart=on-failure", text)
        self.assertIn("/usr/local/lib/hermes-migration/", text)
        self.assertNotIn("/opt/hermes/data", text)

    def test_boot_recovery_cannot_initiate_freeze(self):
        module = self.module()
        self.assertTrue(hasattr(module.Controller, "resume"), "reboot recovery entry missing")
        with tempfile.TemporaryDirectory() as tmp:
            c = module.Controller.create(Path(tmp) / "run", "owner-fixture", "dm-fixture")
            site = FixtureSite()
            self.assertEqual(c.resume(site)["phase"], "PREPARED")
            self.assertEqual(site.calls, [])
            self.start(c, site)
            original = site.call
            site.call = lambda action, request: ({"run_id": request["run_id"], "evidence": self.evidence(c)}
                if action == "dialogue" else original(action, request))
            self.assertEqual(c.resume(site, clock=lambda: 1200, sleep=lambda seconds: None)["phase"], "ACCEPTED")

    def test_capture_requires_gzip_and_valid_exact_file_digest(self):
        module = self.module()
        for changes in ({"archive_format": "tar.zst"}, {"archive_digest": "not-a-digest"},
                        {"archive_format": None}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as tmp:
                c = module.Controller.create(Path(tmp) / "run", "owner-fixture", "dm-fixture")
                site = FixtureSite()
                for _ in range(2):
                    c.advance(site, now=1000)
                original = site.call
                site.call = lambda action, request: ({**original(action, request), **changes}
                    if action == "capture" else original(action, request))
                with self.assertRaises(module.Refused):
                    c.advance(site, now=1000)
                self.assertEqual(c.status()["phase"], "CAPTURING")

    def test_rejects_pre_two_phase_state_version(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            c = module.Controller.create(Path(tmp) / "run", "owner-fixture", "dm-fixture")
            s = c.load()
            s["version"] = 1
            module.atomic_json(c.path, s)
            with self.assertRaises(module.Refused):
                c.load()

    def test_real_cli_confirmation_readback_and_duplicate_receipt(self):
        import time
        module = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "run"
            base = [sys.executable, "-I", str(MODULE)]
            created = subprocess.run(base + ["create", "--execute", "--state-dir", str(directory),
                "--owner-id", "owner-fixture", "--chat-id", "dm-fixture"], capture_output=True, text=True)
            self.assertEqual(created.returncode, 0, created.stderr)
            c = module.Controller(directory)
            site = FixtureSite()
            for _ in range(4):
                c.advance(site)
            s = c.load()
            payload = json.dumps({k: s[k] for k in ("run_id", "nonce", "archive_digest", "notice_id")})
            command = base + ["confirm", "--execute", "--state-dir", str(directory),
                              "--owner-id", "owner-fixture", "--chat-id", "dm-fixture"]
            wrong = subprocess.run(command[:-1] + ["wrong-chat"], input=payload, capture_output=True, text=True)
            self.assertEqual(wrong.returncode, 2)
            for _ in range(2):
                confirmed = subprocess.run(command, input=payload, capture_output=True, text=True)
                self.assertEqual(confirmed.returncode, 0, confirmed.stderr)
                self.assertEqual(json.loads(confirmed.stdout)["phase"], "RESTORING")
            status = subprocess.run(base + ["status", "--state-dir", str(directory)], capture_output=True, text=True)
            self.assertEqual(json.loads(status.stdout)["run_id"], s["run_id"])
            self.assertLessEqual(c.load()["approved_at"], time.time())
            self.assertFalse(site.target_running)

    def test_interruption_of_each_rollback_effect_retains_same_operation(self):
        for interrupted in ("target_fence", "preserve_delta", "reconcile", "source_resume"):
            with self.subTest(action=interrupted), tempfile.TemporaryDirectory() as tmp:
                module, c, site = self.waiting(Path(tmp) / "run")
                c.rollback(now=1200)
                original = site.call
                ids = []
                def effect(action, request):
                    receipt = {"run_id": request["run_id"]}
                    if action == "target_fence":
                        site.target_running = False
                    elif action == "target_probe":
                        receipt.update(running=site.target_running, fenced=not site.target_running,
                                       writers_stopped=not site.target_running)
                    elif action == "preserve_delta":
                        assert not site.target_running
                        receipt.update(verified=True, independent_copy_verified=True, delta_digest="d" * 64)
                    elif action == "reconcile":
                        receipt.update(safe_to_resume=True, cancelled_jobs_preserved=True, replay_reviewed=True)
                    elif action == "source_resume":
                        assert not site.target_running
                        site.source_running = True
                        receipt["running"] = True
                    else:
                        return original(action, request)
                    if action == interrupted:
                        ids.append(request["operation_id"])
                        if len(ids) == 1:
                            raise KeyboardInterrupt("fixture rollback crash after effect")
                    return receipt
                site.call = effect
                for _ in range(8):
                    try:
                        c.advance(site, now=1201)
                    except KeyboardInterrupt:
                        c = module.Controller(c.directory)
                    if c.status()["phase"] == "ROLLED_BACK":
                        break
                self.assertEqual(c.status()["phase"], "ROLLED_BACK")
                self.assertEqual(len(ids), 2)
                self.assertEqual(ids[0], ids[1])
                self.assertTrue(site.source_running)
                self.assertFalse(site.target_running)

    def test_command_adapter_timeout_is_bounded_and_never_success(self):
        import time
        module = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "slow-adapter"
            executable.write_text('#!' + sys.executable + '\nimport time\ntime.sleep(20)\n')
            executable.chmod(0o700)
            site = module.CommandSite(executable, hashlib.sha256(executable.read_bytes()).hexdigest(), timeout=1)
            started = time.monotonic()
            with self.assertRaises(module.Refused):
                site.call("capture", {"run_id": "fixture"})
            self.assertLess(time.monotonic() - started, 5)

    def test_new_run_is_durable_and_does_not_touch_hosts(self):
        self.assertTrue(MODULE.is_file(), "durable controller is not implemented")
        spec = importlib.util.spec_from_file_location("migration", MODULE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run"
            controller = module.Controller.create(path, "owner-fixture", "dm-fixture")
            state = json.loads((path / "state.json").read_text())
            self.assertEqual(state["phase"], "PREPARED")
            self.assertEqual(state["timeout_seconds"], 1800)
            self.assertEqual(module.Controller(path).status(), controller.status())
            self.assertEqual((path / "state.json").stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
