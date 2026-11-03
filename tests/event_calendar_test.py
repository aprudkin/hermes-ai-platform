"""Offline synthetic examples only; no account, mail, route or cycle state."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))


def example_event(**changes):
    event = dict(name='Пример: вечер в музее', date='2030-11-04', time='19:00',
                 venue='Третьяковская галерея', address='Москва, Лаврушинский переулок, 10',
                 synthetic=True)
    return dict(event, **changes)


def example_route(**changes):
    route = dict(travel_minutes_used=16, arrival_buffer_minutes=30,
                 observed_minutes_range=[14, 16], observed_at='2030-11-03T12:00:00+03:00',
                 estimate_kind='observed', synthetic=True)
    return dict(route, **changes)


class EventCalendarTests(unittest.TestCase):
    def test_monthly_calendar_preserves_two_month_agenda_without_private_state(self):
        self.assertIsNotNone(importlib.util.find_spec('event_calendar.render_events'),
                             'safe monthly renderer is missing')
        from event_calendar.render_events import render
        from PIL import Image
        events = [example_event(date=d, time=t) for d, t in
                  [('2030-12-19', '20:00'), ('2030-11-06', '19:00'),
                   ('2030-11-17', '18:00'), ('2030-11-25', '21:30')]]
        original = json.dumps(events, ensure_ascii=False)
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / 'month.png'
            manifest = render(events, date(2030, 11, 3), output)
            self.assertEqual(manifest['months'], [[2030, 11], [2030, 12]])
            self.assertEqual(manifest['event_count'], 4)
            self.assertEqual(manifest['event_markers'], 4)
            self.assertEqual(manifest['today_markers'], 1)
            self.assertEqual(manifest['times'], ['19:00', '18:00', '21:30', '20:00'])
            self.assertEqual(manifest['event_dates'], ['2030-11-06', '2030-11-17', '2030-11-25', '2030-12-19'])
            self.assertFalse(manifest['uses_cycle_state'])
            self.assertEqual(json.dumps(events, ensure_ascii=False), original)
            with Image.open(output) as image:
                self.assertEqual(image.size, (1080, 1660))
                self.assertGreater(len(image.getcolors(maxcolors=1000000)), 100)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            for invalid in ([], events + events, [example_event(date=d) for d in
                            ('2030-10-01', '2030-11-01', '2030-12-01')]):
                with self.assertRaises(ValueError):
                    render(invalid, date(2030, 11, 3), output)

    def test_invalid_generic_event_and_route_inputs_fail_before_writing(self):
        from event_calendar.render_day_reminder import render
        from event_calendar.render_events import render as month
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / 'invalid.png'
            for changes in ({'time': '7:00'}, {'time': '24:00'}, {'date': '2030-02-30'},
                            {'name': ''}, {'venue': []}, {'synthetic': 'true'}):
                with self.subTest(event=changes), self.assertRaises(ValueError):
                    render(example_event(**changes), date(2030, 11, 3), output, route=example_route())
            for changes in ({'observed_at': None}, {'observed_at': '2030-11-03T12:00:00'},
                            {'observed_at': '2030-11-04T12:00:00+03:00'},
                            {'estimate_kind': 'tomorrow_forecast'}, {'travel_minutes_used': -1},
                            {'travel_minutes_used': True}, {'arrival_buffer_minutes': -1},
                            {'observed_minutes_range': [20, 10]}, {'observed_minutes_range': [1, 2]}):
                with self.subTest(route=changes), self.assertRaises(ValueError):
                    render(example_event(), date(2030, 11, 3), output, route=example_route(**changes))
            with self.assertRaises(ValueError):
                render(example_event(), date(2030, 11, 3), output)
            with self.assertRaises(ValueError):
                month([example_event(time='7:00')], date(2030, 11, 3), output)
            for time in ('00:30', '23:30'):
                with self.assertRaisesRegex(ValueError, 'midnight'):
                    render(example_event(time=time), date(2030, 11, 3), output, route=example_route())
            self.assertFalse(output.exists())

    def test_direct_cli_survives_foreign_tools_package_and_other_cwd(self):
        with tempfile.TemporaryDirectory() as td:
            shadow = Path(td) / 'tools'
            shadow.mkdir()
            (shadow / '__init__.py').write_text('# synthetic competing regular package\n')
            result = subprocess.run([sys.executable, str(ROOT / 'tools/event_calendar/__main__.py'),
                                     'caption', '--input', str(ROOT / 'tools/event_calendar/examples/synthetic.json'),
                                     '--today', '2030-11-03'], cwd=td,
                                    env=dict(os.environ, PYTHONPATH=td), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIs(json.loads(result.stdout)['show_caption_above_media'], False)

    def test_caption_emphasizes_times_links_destination_and_never_uses_spoilers(self):
        self.assertIsNotNone(importlib.util.find_spec('event_calendar.caption'),
                             'safe below-image caption builder is missing')
        from event_calendar.caption import build_caption
        event = example_event(name='Пример <вечер> & музыка', venue='Музей & зал', address='Москва, <дом> & 10')
        payload = build_caption(event, date(2030, 11, 3), example_route())
        self.assertEqual(payload['parse_mode'], 'HTML')
        self.assertIs(payload['show_caption_above_media'], False)
        self.assertIs(payload['has_spoiler'], False)
        caption = payload['caption']
        self.assertIn('<b>4 ноября 2030</b>', caption)
        self.assertIn('<b>18:10</b>', caption)
        self.assertIn('<b>19:00</b>', caption)
        self.assertIn('Пример &lt;вечер&gt; &amp; музыка', caption)
        self.assertRegex(caption, r'<a href="https://yandex.ru/maps/\?text=[^"<>]+">Музей &amp; зал</a>\n<code>Москва, &lt;дом&gt; &amp; 10</code>')
        self.assertIn('03.11.2030 12:00 МСК', caption)
        self.assertIn('не прогноз', caption)
        self.assertIn('Синтетический пример', caption)
        self.assertNotIn('spoiler', caption)
        with self.assertRaises(ValueError):
            build_caption(dict(event, address=''), date(2030, 11, 3), example_route())

    def test_cli_month_caption_and_input_errors_are_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'input.json'
            output = Path(td) / 'month.png'
            payload = dict(schema_version=1, event=example_event(), events=[example_event()], route=example_route())
            source.write_text(json.dumps(payload))
            base = [sys.executable, str(ROOT / 'tools/event_calendar/__main__.py')]
            for command in ('month', 'caption'):
                result = subprocess.run(base + [command, '--input', str(source), '--today', '2030-11-03'] +
                                        (['--output', str(output)] if command == 'month' else []),
                                        cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                value = json.loads(result.stdout)
                self.assertIn('caption' if command == 'caption' else 'event_count', value)
            for payload in ([], {'schema_version': 2}, {'schema_version': True}, {'schema_version': 1},
                            dict(schema_version=1, events=[example_event(time='9:00')])):
                source.write_text(json.dumps(payload))
                before = output.read_bytes()
                result = subprocess.run(base + ['month', '--input', str(source), '--today', '2030-11-03',
                                                 '--output', str(output)], cwd=ROOT, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('Traceback', result.stderr)
                self.assertEqual(output.read_bytes(), before)

    def test_image_copy_has_synthetic_label_no_private_origin_or_removed_notes(self):
        from event_calendar.render_day_reminder import render
        from PIL import ImageDraw
        from unittest.mock import patch
        texts = []
        original = ImageDraw.ImageDraw.text
        def record(draw, xy, text, *args, **kwargs):
            texts.append(text)
            return original(draw, xy, text, *args, **kwargs)
        with tempfile.TemporaryDirectory() as td, patch.object(ImageDraw.ImageDraw, 'text', record):
            render(example_event(), date(2030, 11, 3), Path(td) / 'day.png', route=example_route())
        self.assertIn('СИНТЕТИЧЕСКИЙ ПРИМЕР', texts)
        self.assertIn('Завтра,', texts)
        for removed in ('За час до выезда', 'Окончание концерта не указано',
                        'Отмечено начало — длительность не придумана',
                        'Эскиз · время по Москве · уведомление не отправлено'):
            self.assertNotIn(removed, texts)
        self.assertTrue(any('Оценка на 03.11 12:00 МСК' == text for text in texts))

    def test_cli_refuses_to_overwrite_input_and_caption_respects_photo_limit(self):
        from event_calendar.caption import build_caption
        with self.assertRaisesRegex(ValueError, '1024'):
            build_caption(example_event(name='N' * 500, address='A' * 500), date(2030, 11, 3), example_route())
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / 'missing.json'
            output = Path(td) / 'existing.png'
            output.write_bytes(b'keep existing artifact')
            missing_result = subprocess.run([sys.executable, str(ROOT / 'tools/event_calendar/__main__.py'), 'day', '--input', str(missing),
                                             '--today', '2030-11-03', '--output', str(output)],
                                            cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(missing_result.returncode, 0)
            self.assertNotIn('Traceback', missing_result.stderr)
            self.assertEqual(output.read_bytes(), b'keep existing artifact')
            source = Path(td) / 'input.json'
            source.write_text(json.dumps(dict(schema_version=1, event=example_event(), route=example_route())))
            before = source.read_bytes()
            result = subprocess.run([sys.executable, str(ROOT / 'tools/event_calendar/__main__.py'), 'day', '--input', str(source),
                                     '--today', '2030-11-03', '--output', str(source)],
                                    cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(source.read_bytes(), before)

    def test_package_renders_portrait_from_explicit_cli_input(self):
        self.assertIsNotNone(importlib.util.find_spec('event_calendar'),
                             'safe event calendar package is missing')
        from PIL import Image
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            parent.chmod(0o755)
            source, output = parent / 'input.json', parent / 'day.png'
            source.write_text(json.dumps(dict(schema_version=1, event=example_event(), route=example_route())))
            result = subprocess.run([sys.executable, str(ROOT / 'tools/event_calendar/__main__.py'), 'day',
                                     '--input', str(source), '--today', '2030-11-03', '--output', str(output)],
                                    cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(result.stdout)
            self.assertEqual(manifest['window_start'], '2030-11-04T17:10:00+03:00')
            self.assertEqual(manifest['window_end'], '2030-11-04T20:00:00+03:00')
            self.assertEqual(manifest['departure'], '2030-11-04T18:10:00+03:00')
            self.assertEqual(manifest['hatching'], 'event_start_marker_only')
            self.assertEqual(manifest['event_end'], None)
            self.assertFalse(manifest['is_actual_event_duration'])
            self.assertEqual(manifest['route_observed_at'], example_route()['observed_at'])
            self.assertEqual(manifest['route_estimate_kind'], 'observed')
            positions = manifest['positions']
            self.assertEqual(positions['start'], 96)
            self.assertEqual(positions['end'], 984)
            self.assertLess(positions['start'], positions['departure'])
            self.assertLess(positions['departure'], positions['event'])
            self.assertLess(positions['event'], positions['end'])
            with Image.open(output) as image:
                self.assertEqual(image.size, (1080, 1640))
                self.assertEqual(image.format, 'PNG')
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(parent.stat().st_mode & 0o777, 0o755,
                             'renderer must not chmod caller-owned directories')


if __name__ == '__main__':
    unittest.main()
