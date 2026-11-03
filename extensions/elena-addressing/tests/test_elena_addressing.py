"""Synthetic-only tests; all seed/state writes stay in temporary profiles."""
import collections
import importlib.util
import pathlib
import os
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/elena_addressing.py"
PLUGIN = ROOT / "plugin"
EXPECTED = (("Ле", 300),)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class AddressingTests(unittest.TestCase):
    def helper(self):
        self.assertTrue(HELPER.exists(), "addressing helper is not implemented")
        return load(HELPER, "elena_addressing_test")

    def test_all_slots_exact_weights_and_boundaries(self):
        m = self.helper()
        self.assertEqual(tuple(m.WEIGHTS), EXPECTED)
        counts = collections.Counter(m.name_for_slot(s) for s in range(300))
        self.assertEqual(counts, dict(EXPECTED))
        start = 0
        for name, weight in EXPECTED:
            self.assertEqual(m.name_for_slot(start), name)
            self.assertEqual(m.name_for_slot(start + weight - 1), name)
            start += weight
        for bad in (-1, 300, True, 1.5, "0"):
            with self.assertRaises(ValueError):
                m.name_for_slot(bad)


    def test_seeded_selection_survives_restart_without_event_io(self):
        import tempfile
        import os
        from unittest.mock import patch
        m = self.helper()
        self.assertTrue(hasattr(m, "Selector"), "seeded selector is not implemented")
        with tempfile.TemporaryDirectory(prefix="elena-test-") as d:
            profile = pathlib.Path(d)
            selector = m.Selector.from_profile(profile)
            seed = profile / "plugin-data/elena-addressing/seed"
            self.assertEqual(seed.stat().st_mode & 0o777, 0o600)
            self.assertEqual(len(seed.read_bytes()), 32)
            before = seed.stat().st_mtime_ns
            keys = [("telegram", "-1008000000002", str(i)) for i in range(40)]
            with patch("builtins.open", side_effect=AssertionError("event IO")), patch("os.open", side_effect=AssertionError("event IO")), patch("pathlib.Path.open", side_effect=AssertionError("event IO")), patch("os.urandom", side_effect=AssertionError("event entropy IO")):
                choices = [selector.select(*key) for key in keys]
            restarted = load(HELPER, "elena_addressing_restarted").Selector.from_profile(profile)
            self.assertEqual(choices, [restarted.select(*key) for key in keys])
            self.assertEqual(before, seed.stat().st_mtime_ns)
            self.assertGreater(len(set(slot for _, slot in choices)), 1)
            for name, slot in choices:
                self.assertEqual(name, m.name_for_slot(slot))
            for key in (("telegram", "1", ""), ("telegram", "1", None)):
                with self.assertRaises(ValueError):
                    selector.select(*key)
            os.chmod(seed, 0o644)
            with self.assertRaises(ValueError):
                m.Selector.from_profile(profile)


    @unittest.skipUnless(os.environ.get("HERMES_SOURCE_ROOT"), "set HERMES_SOURCE_ROOT to exercise installed native Hermes hooks")
    def test_gateway_hint_is_conditional_scoped_and_once(self):
        import tempfile
        from dataclasses import replace
        from unittest.mock import patch
        sys.path.insert(0, os.environ["HERMES_SOURCE_ROOT"])
        from gateway.config import Platform
        from gateway.session import SessionSource
        from gateway.platforms.event import MessageEvent, MessageType
        m = self.helper()
        self.assertTrue(hasattr(m, "rewrite_event"), "safe gateway hint is not implemented")
        source = SessionSource(platform=Platform.TELEGRAM, chat_id="-1008000000002",
                               chat_type="group", user_id="810000002", profile="manager")
        event = MessageEvent(text="Synthetic fixture.", source=source, message_id="77", user_id="810000002")
        with tempfile.TemporaryDirectory(prefix="elena-test-") as d:
            selector = m.Selector.from_profile(d)
            with patch("builtins.open", side_effect=AssertionError("event IO")), patch("os.open", side_effect=AssertionError("event IO")), patch("pathlib.Path.open", side_effect=AssertionError("event IO")):
                result = m.rewrite_event(event, selector)
            self.assertEqual(result["action"], "rewrite")
            self.assertTrue(result["text"].startswith(event.text + "\n\n"))
            self.assertIn("Если отвечаешь Елене и обращение уместно:", result["text"])
            self.assertIn("Не относится к Луку. Не добавляй обращение в каждый ответ.", result["text"])
            self.assertEqual(event.text, "Synthetic fixture.")
            self.assertIsNone(m.rewrite_event(replace(event, text=result["text"]), selector))
            alexy = replace(event, source=replace(source, user_id="810000001"), user_id="810000001")
            self.assertIn("Если отвечаешь Елене", m.rewrite_event(alexy, selector)["text"])
            dm = replace(event, source=replace(source, chat_id="810000002", chat_type="dm"))
            self.assertIsNotNone(m.rewrite_event(dm, selector))
            rejected = [replace(event, text=" /help"), replace(event, message_type=MessageType.COMMAND),
                        replace(event, message_id=None), replace(event, message_id=""),
                        replace(event, message_id=True), replace(event, internal=True),
                        replace(event, text=""), replace(event, user_id="555"),
                        replace(event, source=None)]
            for changes in ({"platform": Platform.DISCORD}, {"user_id": "555"},
                            {"user_id": "0810000002"}, {"chat_id": "-100999"},
                            {"chat_id": "810000001", "chat_type": "dm", "user_id": "810000001"},
                            {"profile": "default"}, {"is_bot": True}, {"profile_route_rejected": True},
                            {"chat_type": "dm"}):
                rejected.append(replace(event, source=replace(source, **changes)))
            for item in rejected:
                with self.subTest(item=item):
                    self.assertIsNone(m.rewrite_event(item, selector))


    @unittest.skipUnless(os.environ.get("HERMES_SOURCE_ROOT"), "set HERMES_SOURCE_ROOT to exercise installed native Hermes hooks")
    def test_native_registration_and_gateway_consumption(self):
        import tempfile
        import shutil
        from unittest.mock import patch
        sys.path.insert(0, os.environ["HERMES_SOURCE_ROOT"])
        from hermes_cli.plugins import PluginManager, parse_manifest_file
        from gateway.config import Platform
        from gateway.session import SessionSource
        from gateway.platforms.event import MessageEvent
        from gateway.run_inbound import GatewayInboundMixin
        self.assertTrue((PLUGIN / "plugin.yaml").exists(), "native plugin manifest not implemented")
        self.assertTrue((PLUGIN / "__init__.py").exists(), "native registration not implemented")
        with tempfile.TemporaryDirectory(prefix="elena-test-") as d:
            home = pathlib.Path(d)
            dest = home / "plugins/elena-addressing"
            shutil.copytree(PLUGIN, dest, ignore=shutil.ignore_patterns("__pycache__"))
            (home / "scripts").mkdir()
            shutil.copy2(HELPER, home / "scripts/elena_addressing.py")
            manifest = parse_manifest_file(dest / "plugin.yaml", dest, "user", "")
            self.assertEqual(manifest.provides_hooks, ["pre_gateway_dispatch"])
            manager = PluginManager(scope_key=str(home))
            manager._load_plugin(manifest)
            self.assertTrue(manager._plugins["elena-addressing"].enabled)
            self.assertEqual(manager._plugins["elena-addressing"].hooks_registered, ["pre_gateway_dispatch"])
            source = SessionSource(platform=Platform.TELEGRAM, chat_id="810000002", user_id="810000002")
            event = MessageEvent(text="Synthetic registration.", source=source, message_id="88")
            runner = GatewayInboundMixin()
            with patch("hermes_cli.lifecycle.invoke_hook", manager.invoke_hook):
                rewritten = runner._hm_pre_gateway_dispatch_hook(event, source)
                self.assertIn("[elena-addressing]", rewritten.text)
                self.assertIs(rewritten.source, event.source)
                self.assertEqual(rewritten.message_id, event.message_id)
                self.assertEqual(event.text, "Synthetic registration.")
                self.assertIs(runner._hm_pre_gateway_dispatch_hook(rewritten, source), rewritten)
            self.assertTrue((home / "plugin-data/elena-addressing/seed").exists())
            import json
            probe = json.loads((home / "plugin-data/elena-addressing/runtime.json").read_text())
            self.assertEqual(probe['pid'], os.getpid())
            self.assertEqual(probe['profile_home'], str(home.resolve()))
            self.assertEqual(probe['hook'], 'pre_gateway_dispatch')


    def test_cli_explicit_event_key_and_plain_random(self):
        import tempfile
        import subprocess
        import json
        with tempfile.TemporaryDirectory(prefix="elena-test-") as d:
            cmd = [sys.executable, str(HELPER), "--profile", d,
                   "--event-key", "telegram", "-1008000000002", "99"]
            first = subprocess.run(cmd, capture_output=True, text=True, check=True)
            self.assertTrue(first.stdout.strip(), "CLI selection is not implemented")
            choice = json.loads(first.stdout)
            self.assertEqual(set(choice), {"name", "slot", "total"})
            self.assertEqual(choice["total"], 300)
            self.assertEqual(choice["name"], self.helper().name_for_slot(choice["slot"]))
            self.assertEqual(first.stdout, subprocess.run(cmd, capture_output=True, text=True, check=True).stdout)
            result = subprocess.run([sys.executable, str(HELPER), "--random"], capture_output=True, text=True, check=True)
            random_choice = json.loads(result.stdout)
            self.assertEqual(random_choice["name"], self.helper().name_for_slot(random_choice["slot"]))


if __name__ == "__main__":
    unittest.main()
