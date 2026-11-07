"""Strict local inputs and the shared departure/window calculation."""
from datetime import date, datetime, timedelta
import re
from zoneinfo import ZoneInfo

MOSCOW = ZoneInfo('Europe/Moscow')


def validate_event(event, require_address=False):
    if not isinstance(event, dict):
        raise ValueError('event must be an object')
    for key in ('date', 'time', 'name', 'venue') + (('address',) if require_address else ()):
        value = event.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 500 or any(ord(c) < 32 for c in value):
            raise ValueError(f'event.{key} must be nonempty single-line text (max 500 characters)')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', event['date']):
        raise ValueError('event.date must be YYYY-MM-DD')
    date.fromisoformat(event['date'])
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', event['time']):
        raise ValueError('event.time must be HH:MM')
    if 'previous_time' in event and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', str(event['previous_time'])):
        raise ValueError('event.previous_time must be HH:MM')
    if not isinstance(event.get('synthetic', False), bool):
        raise ValueError('event.synthetic must be boolean')


def validate_route(route, today):
    if not isinstance(route, dict):
        raise ValueError('A route estimate is required to anchor the departure timeline')
    if route.get('estimate_kind') != 'observed':
        raise ValueError('route.estimate_kind must be observed, never a future forecast')
    for key in ('travel_minutes_used', 'arrival_buffer_minutes'):
        value = route.get(key)
        minimum = 1 if key == 'travel_minutes_used' else 0
        if type(value) is not int or not minimum <= value <= 1440:
            raise ValueError(f'route.{key} is outside the supported integer range')
    interval = route.get('observed_minutes_range')
    if (not isinstance(interval, (list, tuple)) or len(interval) != 2
            or any(type(v) is not int for v in interval)
            or not 1 <= interval[0] <= route['travel_minutes_used'] <= interval[1] <= 1440):
        raise ValueError('route observed range must contain travel_minutes_used')
    try:
        observed = datetime.fromisoformat(route['observed_at'])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('route.observed_at must be an ISO timestamp with UTC offset') from exc
    if observed.utcoffset() is None or observed.astimezone(MOSCOW).date() > today:
        raise ValueError('route.observed_at needs an offset and cannot be after the reference date')
    if not isinstance(route.get('synthetic', False), bool):
        raise ValueError('route.synthetic must be boolean')


def timeline(event, today, route):
    validate_event(event)
    validate_route(route, today)
    start = datetime.fromisoformat(event['date'] + 'T' + event['time']).replace(tzinfo=MOSCOW)
    departure = start - timedelta(minutes=route['travel_minutes_used'] + route['arrival_buffer_minutes'])
    departure = departure.replace(minute=departure.minute // 5 * 5, second=0, microsecond=0)
    before, after = departure - timedelta(hours=1), start + timedelta(hours=1)
    if before.date() != start.date() or after.date() != start.date():
        raise ValueError('This single-day renderer does not support a window crossing midnight')
    return start, departure, before, after
