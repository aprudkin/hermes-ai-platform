"""Local synthetic fixtures only; no network or real notifications."""
import importlib.util
import sys
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / 'scripts/cycle_engine.py'
if ENGINE.exists():
    spec = importlib.util.spec_from_file_location('cycle_engine', ENGINE)
    engine = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = engine
    spec.loader.exec_module(engine)
else:
    engine = None


class ForecastTests(unittest.TestCase):
    def test_explicit_temporary_policy_uses_28_plus_minus_one(self):
        state = engine.new_state('2030-01-10', '2030-01-14', [26, 59], 'fixture-owner')
        state['forecast_policy'] = {'mode': 'temporary_fixed', 'days': 28, 'tolerance': 1}
        result = engine.forecast(state)
        self.assertEqual(result['next_period'], {'earliest':'2030-02-06', 'latest':'2030-02-08', 'estimate':'2030-02-07'})
        self.assertEqual(result['basis'], 'temporary_assumption_28_plus_minus_1')
        self.assertFalse(result['ovulation_actionable'])
        self.assertEqual(state['seed_range'], [26,59])
        self.assertEqual(len(state['cycles']), 1)

    def test_temporary_policy_reanchors_only_on_confirmed_start(self):
        state = engine.new_state('2030-01-10', '2030-01-14', [26, 59], 'fixture-owner')
        state['forecast_policy'] = {'mode': 'temporary_fixed', 'days': 28, 'tolerance': 1}
        engine.respond(state, 'start', '2030-02-12', 'fixture-owner', 'fixture-1', '2030-02-12')
        result = engine.forecast(state)
        self.assertEqual(result['next_period']['estimate'], '2030-03-12')
        self.assertEqual(result['basis'], 'temporary_assumption_28_plus_minus_1')
        self.assertEqual(result['observed_intervals'], [33])
        self.assertFalse(result['ovulation_actionable'])

    def test_seed_range_is_not_an_invented_average(self):
        self.assertIsNotNone(engine, 'Forecast engine not implemented')
        state = engine.new_state('2030-01-10', '2030-01-14', [26, 59], 'fixture-owner')
        result = engine.forecast(state)
        self.assertEqual(result['next_period'], {'earliest': '2030-02-05', 'latest': '2030-03-10', 'estimate': None})
        self.assertEqual(result['basis'], 'seed_range')
        self.assertFalse(result['ovulation_actionable'])
        self.assertFalse(state['delivery_enabled'])


class ResponseTests(unittest.TestCase):
    def make_state(self):
        return engine.new_state('2030-01-10', '2030-01-14', [26, 59], 'fixture-owner')

    def test_backdated_start_and_end_are_facts_not_predictions(self):
        self.assertTrue(callable(getattr(engine, 'respond', None)), 'Response handling absent')
        state = self.make_state()
        engine.respond(state, 'start', '2030-02-07', 'fixture-owner', 'msg-1', '2030-02-08')
        self.assertEqual(state['cycles'][-1], {'start': '2030-02-07', 'end': None})
        engine.respond(state, 'end', '2030-02-11', 'fixture-owner', 'msg-2', '2030-02-12')
        self.assertEqual(state['cycles'][-1]['end'], '2030-02-11')
        self.assertEqual(engine.forecast(state)['observed_intervals'], [28])
        self.assertIsNone(engine.forecast(state)['next_period']['estimate'])

    def test_wrong_person_cannot_confirm(self):
        self.assertTrue(callable(getattr(engine, 'respond', None)), 'Response handling absent')
        state = self.make_state()
        import copy
        before = copy.deepcopy(state)
        with self.assertRaises(PermissionError):
            engine.respond(state, 'start', '2030-02-07', 'someone-else', 'msg-1', '2030-02-08')
        self.assertEqual(state, before)

    def test_duplicate_response_is_idempotent(self):
        self.assertTrue(callable(getattr(engine, 'respond', None)), 'Response handling absent')
        state = self.make_state()
        for _ in range(2):
            engine.respond(state, 'start', '2030-02-07', 'fixture-owner', 'msg-1', '2030-02-08')
        self.assertEqual(len(state['cycles']), 2)
        self.assertEqual(len(state['events']), 1)

    def test_future_fact_rejected(self):
        self.assertTrue(callable(getattr(engine, 'respond', None)), 'Response handling absent')
        with self.assertRaises(ValueError):
            engine.respond(self.make_state(), 'start', '2030-02-09', 'fixture-owner', 'msg-1', '2030-02-08')


class ReminderTests(unittest.TestCase):
    def make_state(self):
        state = engine.new_state('2030-01-10', '2030-01-14', [26, 59], 'fixture-owner')
        state['stage'] = 'fixture'
        return state

    def at(self, d, hour=10):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        return datetime.fromisoformat(d + f'T{hour:02d}:00:00').replace(tzinfo=ZoneInfo('Europe/Moscow'))

    def test_preview_does_not_count_as_delivery(self):
        self.assertTrue(callable(getattr(engine, 'propose', None)), 'Reminder planning absent')
        import copy
        state = self.make_state()
        before = copy.deepcopy(state)
        item = engine.propose(state, self.at('2030-02-05'))
        self.assertEqual(item['kind'], 'start')
        self.assertEqual(state, before)
        self.assertIsNone(engine.propose(state, self.at('2030-02-05', 9)))

    def test_three_unanswered_deliveries_then_pause(self):
        self.assertTrue(callable(getattr(engine, 'record_simulated_delivery', None)), 'Simulation absent')
        state = self.make_state()
        for d in ('2030-02-05', '2030-02-06', '2030-02-07'):
            when = self.at(d)
            event = engine.propose(state, when)
            self.assertEqual(event['kind'], 'start')
            engine.record_simulated_delivery(state, event, when)
            self.assertIsNone(engine.propose(state, when))
        self.assertIsNone(engine.propose(state, self.at('2030-02-08')))
        self.assertEqual(state['cycles'], self.make_state()['cycles'])
        engine.respond(state, 'resume', None, 'fixture-owner', 'resume-1', '2030-02-08')
        self.assertEqual(engine.propose(state, self.at('2030-02-08'))['kind'], 'start')

    def test_explicit_no_resets_silence_streak_and_asks_tomorrow(self):
        self.assertTrue(callable(getattr(engine, 'propose', None)), 'Reminder planning absent')
        state = self.make_state()
        when = self.at('2030-02-05')
        engine.record_simulated_delivery(state, engine.propose(state, when), when)
        engine.respond(state, 'not_started', None, 'fixture-owner', 'no-1', '2030-02-05')
        self.assertEqual(state['question']['streak'], 0)
        self.assertIsNone(engine.propose(state, when))
        self.assertEqual(engine.propose(state, self.at('2030-02-06'))['kind'], 'start')

    def test_end_question_uses_confirmed_start_and_duration(self):
        self.assertTrue(callable(getattr(engine, 'propose', None)), 'Reminder planning absent')
        state = self.make_state()
        engine.respond(state, 'start', '2030-02-07', 'fixture-owner', 'start-1', '2030-02-08')
        self.assertIsNone(engine.propose(state, self.at('2030-02-10')))
        when = self.at('2030-02-11')
        event = engine.propose(state, when)
        self.assertEqual(event['kind'], 'end')
        engine.record_simulated_delivery(state, event, when)
        engine.respond(state, 'ongoing', None, 'fixture-owner', 'ongoing-1', '2030-02-11')
        self.assertEqual(engine.propose(state, self.at('2030-02-12'))['kind'], 'end')
        engine.respond(state, 'end', '2030-02-11', 'fixture-owner', 'end-1', '2030-02-12')
        self.assertNotEqual((engine.propose(state, self.at('2030-02-12')) or {}).get('kind'), 'end')

    def test_no_external_sender_exists(self):
        self.assertTrue(callable(getattr(engine, 'record_simulated_delivery', None)), 'Simulation absent')
        self.assertFalse(hasattr(engine, 'send'))
        self.assertFalse(self.make_state()['delivery_enabled'])


class PersistenceAndLearningTests(unittest.TestCase):
    def test_two_observed_intervals_produce_labeled_estimate(self):
        state = engine.new_state('2030-01-10', '2030-01-14', [26, 59], 'fixture-owner')
        for action, value, msg in [('start','2030-02-07','1'), ('end','2030-02-11','2'), ('start','2030-03-09','3')]:
            engine.respond(state, action, value, 'fixture-owner', msg, '2030-03-10')
        result = engine.forecast(state)
        self.assertEqual(result['observed_intervals'], [28,30])
        self.assertEqual(result['next_period'], {'earliest':'2030-04-06','latest':'2030-04-08','estimate':'2030-04-07'})
        self.assertTrue(result['ovulation_actionable'])
        self.assertIn('not guaranteed', result['caveat'])

    def test_correction_keeps_audit_and_recomputes(self):
        state = engine.new_state('2030-01-10', '2030-01-14', [26, 59], 'fixture-owner')
        engine.respond(state, 'correct_start', '2030-01-09', 'fixture-owner', 'correction-1', '2030-01-15')
        self.assertEqual(state['events'][0]['before_cycles'][0]['start'], '2030-01-10')
        self.assertEqual(engine.forecast(state)['next_period']['earliest'], '2030-02-04')

    def test_private_atomic_storage_and_read_only_cli(self):
        self.assertTrue(callable(getattr(engine, 'save_state', None)), 'Private persistence absent')
        import json, tempfile, subprocess, stat
        state = engine.new_state('2030-01-10', '2030-01-14', [26,59], 'fixture-owner')
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'private' / 'state.json'
            engine.save_state(p, state)
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(p.parent.stat().st_mode), 0o700)
            before = p.read_bytes()
            result = subprocess.run([sys.executable, str(ENGINE), '--state', str(p), 'forecast'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['basis'], 'seed_range')
            self.assertEqual(before, p.read_bytes())
            result = subprocess.run([sys.executable, str(ENGINE), '--state', str(p), 'preview', '--at', '2030-02-05T07:00:00+00:00'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['kind'], 'start')
            self.assertEqual(before, p.read_bytes())
            result = subprocess.run([sys.executable, str(ENGINE), '--state', str(p), 'simulate', '--from', '2030-02-05', '--days', '4'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            simulation = json.loads(result.stdout)
            self.assertEqual([x['kind'] if x else None for x in simulation['days']], ['start','start','start',None])
            self.assertTrue(simulation['question']['paused'])
            self.assertEqual(before, p.read_bytes())


if __name__ == '__main__':
    unittest.main(verbosity=2)
