"""Offline cycle tracking. No network, scheduler, diagnosis, or live sender."""
from datetime import date, datetime, timedelta
from statistics import median
from copy import deepcopy
from zoneinfo import ZoneInfo
from pathlib import Path
import argparse
import json
import os
import tempfile
import fcntl


def save_state(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.new', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def propose(state, when):
    """Read-only draft at/after local 10:00; does not send or count delivery."""
    if when.tzinfo is None:
        raise ValueError('Timezone-aware time required')
    local = when.astimezone(ZoneInfo(state['timezone']))
    today = local.date().isoformat()
    if local.hour < state['hour'] or state['last_delivery_day'] == today:
        return None
    current = state['cycles'][-1]
    f = forecast(state)
    q = state['question']
    if q:
        if q['paused'] or q['streak'] >= 3 or today < q['next_due']:
            return None
        kind = q['kind']
    elif current['end'] is None:
        if not f['expected_last_bleeding_day'] or today < f['expected_last_bleeding_day']:
            return None
        kind = 'end'
    elif today >= f['next_period']['earliest']:
        kind = 'start'
    elif today == (day(f['next_period']['earliest']) - timedelta(days=2)).isoformat():
        kind = 'heads_up'
    elif f['ovulation_actionable'] and (day(f['ovulation_range']['earliest']) - timedelta(days=2)).isoformat() <= today <= f['ovulation_range']['latest']:
        kind = 'ovulation_estimate'
        if any(x['cycle'] == current['start'] and x['kind'] == kind for x in state['sent']):
            return None
    else:
        return None
    texts = {
        'start': 'месячные уже начались? Можно ответить «нет», «сегодня» или указать дату. Это вопрос, не подтверждение прогноза.',
        'end': 'месячные ещё идут? Если уже закончились, напиши последний день кровотечения.',
        'heads_up': 'Приближается начало расчётного диапазона следующих месячных: {earliest} — {latest}. Это наш приблизительный прогноз, не точная дата.',
        'ovulation_estimate': 'Расчётный ориентир овуляции: {ov_earliest} — {ov_latest}. Овуляция не подтверждена, может произойти вне диапазона или не произойти. Для контрацепции прогноз не подходит.'}
    text = texts[kind].format(**f['next_period'], ov_earliest=f['ovulation_range']['earliest'], ov_latest=f['ovulation_range']['latest'])
    text += '\n\n#Цикл'
    return {'key': current['start'] + ':' + kind + ':' + today, 'cycle': current['start'],
            'kind': kind, 'day': today, 'text': text, 'simulation_only': True}


def record_simulated_delivery(state, event, when):
    """Simulation only. No network. Caller must use a fixture/deep copy, not real state."""
    if state.get('stage') != 'fixture':
        raise ValueError('Simulated deliveries may only mutate synthetic/copied fixture state')
    if event != propose(state, when):
        raise ValueError('Stale or already recorded simulation')
    state['sent'].append(deepcopy(event))
    state['last_delivery_day'] = event['day']
    if event['kind'] in ('start', 'end'):
        q = state['question']
        streak = q['streak'] + 1 if q and q['kind'] == event['kind'] else 1
        state['question'] = {'kind': event['kind'], 'streak': streak, 'paused': streak >= 3,
                             'last_asked': event['day'], 'next_due': (day(event['day']) + timedelta(days=1)).isoformat()}


def respond(state, action, value, actor, message_id, today):
    """Only call after verifying actual inbound actor and normalizing an explicit reply."""
    if str(actor) != state['confirmer_id']:
        raise PermissionError('Only the configured confirmer can record answers')
    if not message_id:
        raise ValueError('Source message ID required')
    previous = next((e for e in state['events'] if e['message_id'] == str(message_id)), None)
    if previous:
        if (previous['action'], previous['value']) != (action, value):
            raise ValueError('Source message already has a different meaning')
        return False
    current = state['cycles'][-1]
    cycles = deepcopy(state['cycles'])
    q = deepcopy(state['question'])
    if action in ('start', 'end', 'correct_start', 'correct_end'):
        if not value or day(value) > day(today):
            raise ValueError('Fact must have an explicit date not in the future')
        if action == 'start':
            if current['end'] is None or day(value) <= day(current['end']):
                raise ValueError('Close previous bleeding or explicitly correct its dates')
            cycles.append({'start': value, 'end': None})
        elif action in ('end', 'correct_end'):
            if action == 'end' and current['end'] is not None:
                raise ValueError('Use explicit correction for an existing end date')
            if day(value) < day(current['start']):
                raise ValueError('End precedes start')
            cycles[-1]['end'] = value
        else:
            if current['end'] and day(value) > day(current['end']):
                raise ValueError('Start follows end')
            if len(cycles) > 1 and day(value) <= day(cycles[-2]['end'] or cycles[-2]['start']):
                raise ValueError('Overlapping cycles')
            cycles[-1]['start'] = value
        q = None
    elif action in ('not_started', 'ongoing'):
        required = 'start' if action == 'not_started' else 'end'
        if not q or q['kind'] != required:
            raise ValueError('Answer does not match the pending question')
        q.update(streak=0, paused=False, next_due=(day(today) + timedelta(days=1)).isoformat())
    elif action == 'resume':
        if not q:
            raise ValueError('No question to resume')
        q.update(streak=0, paused=False, next_due=today)
    else:
        raise ValueError('Unknown response action')
    event = {'message_id': str(message_id), 'actor': str(actor), 'action': action,
             'value': value, 'recorded_on': today, 'before_cycles': deepcopy(state['cycles'])}
    state['cycles'] = cycles
    state['question'] = q
    state['events'].append(event)
    return True


def day(value):
    return date.fromisoformat(value)


def new_state(start, end, seed_range, confirmer_id):
    if day(end) < day(start):
        raise ValueError('End precedes start')
    low, high = seed_range
    if not 1 <= low <= high:
        raise ValueError('Invalid initial range')
    return {'schema': 1, 'stage': 'draft', 'delivery_enabled': False,
            'timezone': 'Europe/Moscow', 'hour': 10, 'confirmer_id': str(confirmer_id),
            'seed_range': [low, high], 'cycles': [{'start': start, 'end': end}],
            'events': [], 'question': None, 'sent': [], 'last_delivery_day': None}


def forecast(state):
    cycles = state['cycles']
    starts = [day(c['start']) for c in cycles]
    intervals = [(b - a).days for a, b in zip(starts, starts[1:])][-12:]
    low, high = state['seed_range']
    point = None
    basis = 'seed_range'
    if intervals:
        low, high = min([low] + intervals), max([high] + intervals)
        basis = 'seed_range_and_observations'
    if len(intervals) >= 2:
        low, high = min(intervals), max(intervals)
        point = (starts[-1] + timedelta(days=int(median(intervals) + 0.5))).isoformat()
        basis = 'observed_start_intervals'
    policy = state.get('forecast_policy', {})
    temporary = policy.get('mode') == 'temporary_fixed'
    if temporary:
        length, tolerance = policy['days'], policy['tolerance']
        if not isinstance(length, int) or not isinstance(tolerance, int) or not 0 <= tolerance < length:
            raise ValueError('Invalid temporary forecast policy')
        low, high = length - tolerance, length + tolerance
        point = (starts[-1] + timedelta(days=length)).isoformat()
        basis = f'temporary_assumption_{length}_plus_minus_{tolerance}'
    earliest, latest = starts[-1] + timedelta(days=low), starts[-1] + timedelta(days=high)
    durations = [(day(c['end']) - day(c['start'])).days + 1 for c in cycles if c['end']][-12:]
    last_day = (starts[-1] + timedelta(days=int(median(durations) + 0.5) - 1)).isoformat() if durations else None
    return {'next_period': {'earliest': earliest.isoformat(), 'latest': latest.isoformat(), 'estimate': point},
            'basis': basis, 'observed_intervals': intervals,
            'expected_last_bleeding_day': last_day,
            'ovulation_range': {'earliest': (earliest - timedelta(days=16)).isoformat(),
                                'latest': (latest - timedelta(days=10)).isoformat()},
            'ovulation_actionable': not temporary and len(intervals) >= 2 and high - low <= 7,
            'caveat': 'Calendar estimate only; observed bounds are not guaranteed limits. No safe days or confirmed ovulation.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('forecast')
    p = sub.add_parser('preview')
    p.add_argument('--at', required=True, help='ISO timestamp with timezone')
    p = sub.add_parser('simulate')
    p.add_argument('--from', dest='start_day', required=True)
    p.add_argument('--days', type=int, default=4)
    p = sub.add_parser('respond')
    p.add_argument('--actor', required=True)
    p.add_argument('--message-id', required=True)
    p.add_argument('--today', required=True)
    p.add_argument('--action', required=True, choices=['start','end','correct_start','correct_end','not_started','ongoing','resume'])
    p.add_argument('--date')
    args = parser.parse_args()
    path = Path(args.state)
    try:
        if args.command == 'respond':
            # Serializes the entire read -> validate -> append -> atomic write.
            fd = os.open(str(path) + '.lock', os.O_CREAT | os.O_RDWR, 0o600)
            with os.fdopen(fd, 'a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                state = json.loads(path.read_text())
                changed = respond(state, args.action, args.date, args.actor, args.message_id, args.today)
                if changed:
                    save_state(path, state)
                result = {'recorded': changed, 'delivery_enabled': state['delivery_enabled'], 'forecast': forecast(state)}
        else:
            state = json.loads(path.read_text())
            if args.command == 'forecast':
                result = forecast(state)
            elif args.command == 'preview':
                result = propose(state, datetime.fromisoformat(args.at))
            else:
                if not 1 <= args.days <= 366:
                    raise ValueError('Simulation length must be 1..366')
                fixture = deepcopy(state)
                fixture['stage'] = 'fixture'
                days = []
                for i in range(args.days):
                    d = day(args.start_day) + timedelta(days=i)
                    when = datetime.combine(d, datetime.min.time(), tzinfo=ZoneInfo(state['timezone'])).replace(hour=state['hour'])
                    event = propose(fixture, when)
                    days.append(event)
                    if event:
                        record_simulated_delivery(fixture, event, when)
                result = {'simulation_only': True, 'days': days, 'question': fixture['question'], 'real_state_unchanged': True}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, PermissionError, OSError) as error:
        parser.exit(2, f'{type(error).__name__}: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
