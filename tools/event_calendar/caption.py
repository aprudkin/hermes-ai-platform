"""HTML photo-caption payload only. No accounts, senders or network."""
from datetime import datetime
from html import escape, unescape
import re
from urllib.parse import urlencode

from .data import MOSCOW, timeline, validate_event
from .style import GENITIVE


def build_caption(event, today, route):
    validate_event(event, require_address=True)
    start, departure, _, _ = timeline(event, today, route)
    observed = datetime.fromisoformat(route['observed_at']).astimezone(MOSCOW)
    link = 'https://yandex.ru/maps/?' + urlencode({'text': event['venue'] + ', ' + event['address']})
    lo, hi = route['observed_minutes_range']
    prefix = 'Синтетический пример — не реальное событие и не наблюдение трафика.\n\n' if event.get('synthetic') or route.get('synthetic') else ''
    caption = (prefix + f'<b>{start.day} {GENITIVE[start.month-1]} {start.year}</b> · {escape(event["name"])}\n'
               f'Выезд: <b>{departure:%H:%M}</b> · начало: <b>{start:%H:%M}</b> (МСК)\n\n'
               f'<a href="{escape(link, quote=True)}">{escape(event["venue"])}</a>\n'
               f'<code>{escape(event["address"])}</code>\n\n'
               f'Сохранённая оценка дороги: {lo}–{hi} мин, на {observed:%d.%m.%Y %H:%M} МСК; '
               'не прогноз на день события.\n'
               f'Для расчёта: {route["travel_minutes_used"]} мин дороги + {route["arrival_buffer_minutes"]} мин запаса. '
               'Выезд округлён вниз до 5 минут; ожидание такси не включено.')
    if len(unescape(re.sub(r'<[^>]*>', '', caption)).encode('utf-16-le')) // 2 > 1024:
        raise ValueError('Photo caption exceeds 1024 UTF-16 units')
    return {'caption': caption, 'parse_mode': 'HTML',
            'show_caption_above_media': False, 'has_spoiler': False}
