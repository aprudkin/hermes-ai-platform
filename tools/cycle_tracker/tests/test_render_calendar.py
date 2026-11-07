"""Synthetic renderer checks, no network or private state."""
import importlib.util
import unittest
from pathlib import Path
from datetime import date
import tempfile

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/render_calendar.py'
if SCRIPT.exists():
    spec = importlib.util.spec_from_file_location('renderer', SCRIPT)
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
else:
    renderer = None


class RenderTests(unittest.TestCase):
    def fixture(self):
        return {'cycles': [{'start':'2030-01-10','end':'2030-01-14'}]}

    def test_full_moon_is_independent_of_cycle_and_today(self):
        import copy
        from PIL import Image
        state = {'cycles': [{'start': '2026-10-26', 'end': '2026-10-26'}]}
        span = {'earliest': '2026-11-22', 'latest': '2026-11-24', 'estimate': '2026-11-23'}
        before = copy.deepcopy((state, span))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'moon.png'
            manifest = renderer.render(state, span, date(2026, 10, 26), path)
            self.assertEqual(manifest.get('full_moon_dates'), ['2026-10-26', '2026-11-24'])
            self.assertEqual(manifest['full_moon_timezone'], 'Europe/Moscow')
            self.assertEqual(manifest['confirmed_count'], 1)
            self.assertEqual(manifest['possible_start_count'], 3)
            self.assertEqual(manifest['today_count'], 1)
            self.assertEqual(manifest['moon_legend'], 'Полнолуние')
            markers = manifest['full_moon_markers']
            self.assertEqual(len(markers), 2)
            with Image.open(path) as im:
                for marker in markers:
                    self.assertEqual(im.getpixel(tuple(marker['center'])), (245, 240, 214))
        self.assertEqual((state, span), before)

    def test_full_moon_reference_dates_and_moscow_midnight(self):
        # US Naval Observatory primary phases, UTC converted to Europe/Moscow.
        expected = ['2026-01-03', '2026-02-02', '2026-03-03', '2026-04-02',
                    '2026-05-01', '2026-05-31', '2026-06-30', '2026-07-29',
                    '2026-08-28', '2026-09-26', '2026-10-26', '2026-11-24', '2026-12-24']
        actual = sorted(d.isoformat() for m in range(1, 13) for d in renderer.full_moons(2026, m))
        self.assertEqual(actual, expected)
        self.assertEqual(renderer.full_moons(2032, 2), {date(2032, 2, 26)})
        self.assertEqual(renderer.full_moons(2032, 12), {date(2032, 12, 16)})
        self.assertEqual(renderer.full_moons(2018, 2), set())
        self.assertEqual(renderer.full_moons(2018, 1), {date(2018, 1, 2), date(2018, 1, 31)})
        with self.assertRaises(ValueError):
            renderer.full_moons(2101, 1)
        with self.assertRaises(ValueError):
            renderer.full_moons(2026, 13)

    def test_fact_and_possible_start_are_separate(self):
        self.assertIsNotNone(renderer, 'Calendar renderer absent')
        span = {'earliest':'2030-02-05','latest':'2030-03-10','estimate':None}
        self.assertEqual(renderer.day_kind(self.fixture(), span, date(2030,1,10)), 'confirmed')
        self.assertEqual(renderer.day_kind(self.fixture(), span, date(2030,2,5)), 'possible_start')
        self.assertEqual(renderer.day_kind(self.fixture(), span, date(2030,3,10)), 'possible_start')
        self.assertEqual(renderer.day_kind(self.fixture(), span, date(2030,3,11)), 'plain')

    def test_notebook_uses_only_relevant_months(self):
        from PIL import Image
        state = {'cycles': [{'start': '2030-10-19', 'end': '2030-10-23'}],
                 'forecast_policy': {'mode': 'temporary_fixed', 'days': 28, 'tolerance': 1}}
        span = {'earliest': '2030-11-15', 'latest': '2030-11-17', 'estimate': '2030-11-16'}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'notebook.png'
            manifest = renderer.render(state, span, date(2030, 10, 26), path)
            self.assertEqual(manifest['months'], ['2030-10', '2030-11'])
            self.assertEqual(manifest['confirmed_count'], 5)
            self.assertEqual(manifest['possible_start_count'], 3)
            self.assertEqual(manifest['style'], '05-notebook')
            self.assertEqual(manifest['today_count'], 1)
            with Image.open(path) as im:
                self.assertEqual(im.getpixel((0, 0)), (252, 252, 247))
                self.assertIn((35, 71, 91), {color for _, color in im.getcolors(100000)})

    def test_month_boundary_keeps_confirmed_tail_in_previous_month(self):
        state = {'cycles': [{'start': '2030-01-30', 'end': '2030-02-02'}]}
        span = {'earliest': '2030-03-01', 'latest': '2030-03-03', 'estimate': None}
        with tempfile.TemporaryDirectory() as tmp:
            manifest = renderer.render(state, span, date(2030, 3, 1), Path(tmp) / 'boundary.png')
        self.assertEqual(manifest['months'], ['2030-01', '2030-02', '2030-03'])
        self.assertEqual(manifest['confirmed_count'], 4)
        self.assertEqual(manifest['possible_start_count'], 3)

    def test_forecast_spans_all_months_across_year_transition(self):
        state = {'cycles': [{'start': '2030-12-03', 'end': '2030-12-07'}]}
        span = {'earliest': '2030-12-31', 'latest': '2031-03-01', 'estimate': None}
        with tempfile.TemporaryDirectory() as tmp:
            manifest = renderer.render(state, span, date(2030, 12, 10), Path(tmp) / 'years.png')
        self.assertEqual(manifest['months'], ['2030-12', '2031-01', '2031-02', '2031-03'])
        self.assertEqual(manifest['possible_start_count'],
                         (date(2031, 3, 1) - date(2030, 12, 31)).days + 1)
        self.assertEqual(manifest['today_count'], 1)

    def test_same_month_future_start_is_not_duplicated(self):
        state = {'cycles': [{'start': '2030-01-01', 'end': '2030-01-05'}]}
        span = {'earliest': '2030-01-28', 'latest': '2030-01-30', 'estimate': '2030-01-29'}
        with tempfile.TemporaryDirectory() as tmp:
            manifest = renderer.render(state, span, date(2030, 1, 20), Path(tmp) / 'same.png')
        self.assertEqual(manifest['months'], ['2030-01'])
        self.assertEqual(manifest['confirmed_count'], 5)
        self.assertEqual(manifest['possible_start_count'], 3)
        self.assertEqual(manifest['today_count'], 1)

    def test_unknown_end_confirms_only_first_day_not_today(self):
        from PIL import Image
        state = {'cycles': [{'start': '2030-10-19', 'end': None}]}
        span = {'earliest': '2030-11-15', 'latest': '2030-11-17', 'estimate': '2030-11-16'}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'open.png'
            manifest = renderer.render(state, span, date(2030, 10, 26), path)
            self.assertEqual(manifest['confirmed_count'], 1)
            self.assertEqual(renderer.day_kind(state, span, date(2030, 10, 26)), 'plain')
            self.assertEqual(manifest.get('confirmed_label'), '19 октября · конец не указан')
            self.assertEqual(manifest['today_count'], 1)
            with Image.open(path) as im:
                # Today's cell has an outline but never a pink fill.
                import calendar
                d = date(2030, 10, 26)
                row = next(i for i, week in enumerate(calendar.monthcalendar(2030, 10)) if 26 in week)
                cx = round(96 + (d.weekday() + .5) * 436 / 7)
                cy = 568 + 146 + row * 72
                self.assertNotEqual(im.getpixel((cx, cy + 20)), (192, 117, 108))

    def test_year_transition_has_unambiguous_caption(self):
        state = {'cycles': [{'start': '2030-12-03', 'end': '2030-12-07'}]}
        span = {'earliest': '2030-12-31', 'latest': '2031-01-02', 'estimate': '2031-01-01'}
        with tempfile.TemporaryDirectory() as tmp:
            manifest = renderer.render(state, span, date(2030, 12, 20), Path(tmp) / 'caption.png')
        self.assertEqual(manifest['forecast_label'], '31 декабря 2030 — 2 января 2031')
        self.assertEqual(manifest['confirmed_label'], '3–7 декабря')
        self.assertEqual(manifest['months'], ['2030-12', '2031-01'])
        self.assertEqual(manifest['possible_start_count'], 3)

    def test_cli_refuses_to_overwrite_input_state(self):
        import json
        import subprocess
        import sys
        state = {'seed_range': [27, 30], 'cycles': [{'start': '2030-01-01', 'end': '2030-01-05'}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            original = json.dumps(state).encode()
            path.write_bytes(original)
            result = subprocess.run([sys.executable, str(SCRIPT), '--state', str(path),
                                     '--output', str(path), '--today', '2030-01-20'],
                                    text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(path.read_bytes(), original)
            self.assertIn('output must not overwrite state', result.stderr.lower())

    def test_invalid_forecast_does_not_replace_existing_png(self):
        invalid = [
            {'earliest': '2030-02-03', 'latest': '2030-02-01', 'estimate': None},
            {'earliest': '2030-02-01', 'latest': '2030-02-03', 'estimate': '2030-02-04'},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'existing.png'
            for span in invalid:
                with self.subTest(span=span):
                    path.write_bytes(b'existing artifact')
                    with self.assertRaises(ValueError):
                        renderer.render(self.fixture(), span, date(2030, 1, 25), path)
                    self.assertEqual(path.read_bytes(), b'existing artifact')

    def test_cli_uses_engine_forecast_read_only_and_private_permissions(self):
        import json
        import stat
        import subprocess
        import sys
        state = {'seed_range': [24, 45], 'cycles': [{'start': '2030-10-19', 'end': '2030-10-23'}],
                 'forecast_policy': {'mode': 'temporary_fixed', 'days': 28, 'tolerance': 1}}
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'state.json'
            source.write_text(json.dumps(state))
            before = source.read_bytes()
            output = Path(tmp) / 'private' / 'cli.png'
            result = subprocess.run([sys.executable, str(SCRIPT), '--state', str(source),
                                     '--output', str(output), '--today', '2030-10-26'],
                                    text=True, capture_output=True, check=True)
            manifest = json.loads(result.stdout)
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(manifest['confirmed_label'], '19–23 октября')
            self.assertEqual(manifest['forecast_label'], '15–17 ноября')
            self.assertEqual(manifest['possible_start_count'], 3)
            self.assertFalse(manifest['ovulation_marked'])
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(output.parent.stat().st_mode), 0o700)

    def test_repeatable_bytes_and_no_input_mutation(self):
        import copy
        state = self.fixture()
        span = {'earliest': '2030-02-05', 'latest': '2030-02-07', 'estimate': '2030-02-06'}
        before = copy.deepcopy((state, span))
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / 'a.png', Path(tmp) / 'b.png'
            renderer.render(state, span, date(2030, 1, 25), a)
            renderer.render(state, span, date(2030, 1, 25), b)
            self.assertEqual(a.read_bytes(), b.read_bytes())
        self.assertEqual((state, span), before)

    def test_date_range_and_fact_precedence_regressions(self):
        for first, last, label in [('2032-02-29', '2032-02-29', '29 февраля'),
                                   ('2032-02-29', '2032-03-02', '29 февраля — 2 марта')]:
            with self.subTest(first=first):
                self.assertEqual(renderer.date_range(first, last), label)
        span = {'earliest': '2030-01-10', 'latest': '2030-01-11', 'estimate': None}
        self.assertEqual(renderer.day_kind(self.fixture(), span, date(2030, 1, 10)), 'confirmed')

    def test_render_is_real_png_and_state_unchanged(self):
        self.assertIsNotNone(renderer, 'Calendar renderer absent')
        import copy
        from PIL import Image
        state = self.fixture()
        span = {'earliest':'2030-02-05','latest':'2030-03-10','estimate':None}
        before = copy.deepcopy(state)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'calendar.png'
            manifest = renderer.render(state, span, date(2030,1,25), path)
            with Image.open(path) as im:
                self.assertEqual(im.format, 'PNG')
                self.assertEqual(im.width, 1080)
                self.assertGreater(im.height, 1000)
                im.verify()
            self.assertEqual(len(manifest['months']), 3)
            self.assertEqual(manifest['confirmed_count'], 5)
            self.assertEqual(manifest['today'], '2030-01-25')
            self.assertEqual(state, before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
