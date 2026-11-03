"""Reconstruction/portability checks using only synthetic fixture files."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_engine_and_renderer_exist_without_installed_skill(self):
        self.assertTrue((ROOT / 'scripts/cycle_engine.py').is_file(), 'portable cycle engine is missing')
        self.assertTrue((ROOT / 'scripts/render_calendar.py').is_file(), 'portable renderer is missing')

    def test_fixture_render_is_visibly_synthetic(self):
        script = ROOT / 'scripts/render_calendar.py'
        spec = importlib.util.spec_from_file_location('fixture_renderer', script)
        renderer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(renderer)
        from PIL import ImageDraw
        from unittest.mock import patch
        from datetime import date
        texts = []
        original = ImageDraw.ImageDraw.text
        def record(draw, xy, text, *args, **kwargs):
            texts.append(text)
            return original(draw, xy, text, *args, **kwargs)
        with tempfile.TemporaryDirectory() as td, patch.object(ImageDraw.ImageDraw, 'text', record):
            state = json.loads((ROOT / 'examples/synthetic-state.json').read_text())
            renderer.render(state, {'earliest': '2030-02-06', 'latest': '2030-02-08', 'estimate': '2030-02-07'},
                            date(2030, 1, 25), Path(td) / 'synthetic.png')
        self.assertIn('СИНТЕТИЧЕСКИЙ ПРИМЕР', texts)

    def test_runner_requires_explicit_state_and_execution_credentials(self):
        script = ROOT / 'scripts/cycle_reminder_runner.py'
        self.assertTrue(script.exists(), 'portable runner is missing')
        for args in ([], ['--execute'], ['--execute', '--state', 'synthetic-missing.json']):
            result = subprocess.run([sys.executable, str(script)] + args, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('Traceback', result.stderr)

    def test_buttons_accept_other_explicit_configured_recipient(self):
        script = ROOT / 'scripts/cycle_buttons.py'
        self.assertTrue(script.exists(), 'portable buttons are missing')
        # Reuse the synthetic receipt fixture, changing every identity together.
        from test_cycle_buttons import ButtonTests
        helper = ButtonTests()
        helper.setUp()
        try:
            helper.fixture()
            state = helper.s
            state['confirmer_id'] = '3001'
            state['planned_destination'] = 'telegram:-1003001'
            for receipt in (state['runner']['receipts'][-1], state['runner']['outbox']):
                receipt['chat_id'] = '-1003001'
                receipt['returned_message']['chat']['id'] = -1003001
            helper.path.write_text(json.dumps(state))
            result = helper.click(actor_id=3001, chat_id=-1003001)
            self.assertTrue(result['accepted'])
        finally:
            helper.doCleanups()
