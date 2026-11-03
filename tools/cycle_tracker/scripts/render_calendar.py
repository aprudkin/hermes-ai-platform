"""Reusable, local-only 05-notebook PNG renderer (Pillow + system DejaVu).

render(state, span, today, output) never calculates a new forecast or changes
state. Pass cycle_engine.forecast(state)['next_period'] as span. No browser,
network, scheduler or delivery dependencies. CLI reads state, writes only PNG.
"""
import argparse
import calendar
from datetime import date, datetime, timedelta, timezone
from math import sin, radians, floor
from functools import lru_cache
import json
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont

MONTHS = ['январь','февраль','март','апрель','май','июнь','июль','август','сентябрь','октябрь','ноябрь','декабрь']
SHORT = ['янв','фев','мар','апр','мая','июн','июл','авг','сен','окт','ноя','дек']
GENITIVE = ['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря']
BG = '#fcfcf7'
INK = '#23475b'
MUTED = '#7e9196'
ROSE = '#c0756c'
LINE = '#d6e5e8'
GOLD = '#bf9855'
HIGHLIGHT = '#f3df9f'


def font(size, bold=False, serif=False, italic=False):
    base = Path('/usr/share/fonts/truetype/dejavu')
    family = 'DejaVuSerif' if serif else 'DejaVuSans'
    suffix = '-Bold' if bold else ('-Italic' if italic and serif else '')
    path = base / (family + suffix + '.ttf')
    if serif and italic and not path.exists():
        # Minimal DejaVu installs omit italic; use a local Cyrillic serif.
        path = Path('/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf')
    return ImageFont.truetype(str(path), size)


def day_kind(state, span, d):
    for c in state['cycles']:
        # An unclosed period confirms only its start, not subsequent days.
        end = date.fromisoformat(c['end'] or c['start'])
        if date.fromisoformat(c['start']) <= d <= end:
            return 'confirmed'
    if date.fromisoformat(span['earliest']) <= d <= date.fromisoformat(span['latest']):
        return 'possible_start'
    return 'plain'


def short_date(value):
    d = date.fromisoformat(value)
    return f'{d.day} {GENITIVE[d.month-1]}'


def date_range(first, last):
    """Compact Russian caption, explicit years when a range crosses New Year."""
    a, b = date.fromisoformat(first), date.fromisoformat(last)
    if a == b:
        return short_date(first)
    if a.year != b.year:
        return f'{short_date(first)} {a.year} — {short_date(last)} {b.year}'
    if a.month == b.month:
        return f'{a.day}–{short_date(last)}'
    return f'{short_date(first)} — {short_date(last)}'


@lru_cache(maxsize=128)
def full_moons(year, month):
    """Moscow civil dates of astronomical full moons, 2000–2100.

    Local implementation of Meeus, Astronomical Algorithms, ch.49 (full-moon
    series + planetary terms). Convert TT to UTC using the Espenak/Meeus
    Delta-T approximation. Minute-level timing is sufficient for date markers;
    no lunar information enters the period forecast or persisted health state.
    Reference date checks: https://aa.usno.navy.mil/calculated/moon/phases?year=2026
    """
    if not 2000 <= year <= 2100:
        raise ValueError('Full-moon calendar supports years 2000–2100')
    calendar.monthrange(year, month)  # Validate month before calculation.
    epoch = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
    first = datetime(year, month, 1, tzinfo=ZoneInfo('Europe/Moscow'))
    jd = 2451545 + (first.astimezone(timezone.utc) - epoch).total_seconds()/86400
    k0 = floor((jd - 2451550.09765)/29.530588853)
    result = set()
    for n in range(k0-1, k0+4):
        k = n + 0.5
        t = k / 1236.85
        e = 1 - .002516*t - .0000074*t*t
        m = 2.5534 + 29.10535670*k - .0000014*t*t - .00000011*t**3
        p = 201.5643 + 385.81693528*k + .0107582*t*t + .00001238*t**3 - .000000058*t**4
        f = 160.7108 + 390.67050284*k - .0016118*t*t - .00000227*t**3 + .000000011*t**4
        o = 124.7746 - 1.56375588*k + .0020672*t*t + .00000215*t**3
        terms = [(-.40614,p),(.17302*e,m),(.01614,2*p),(.01043,2*f),
                 (.00734*e,p-m),(-.00515*e,p+m),(.00209*e*e,2*m),
                 (-.00111,p-2*f),(-.00057,p+2*f),(.00056*e,2*p+m),
                 (-.00042,3*p),(.00042*e,m+2*f),(.00038*e,m-2*f),
                 (-.00024*e,2*p-m),(-.00017,o),(-.00007,p+2*m),
                 (.00004,2*p-2*f),(.00004,3*m),(.00003,p+m-2*f),
                 (.00003,2*p+2*f),(-.00003,p+m+2*f),(.00003,p-m+2*f),
                 (-.00002,p-m-2*f),(-.00002,3*p+m),(.00002,4*p)]
        planetary = [(.000325,299.77+.107408*k-.009173*t*t),
                     (.000165,251.88+.016321*k),(.000164,251.83+26.651886*k),
                     (.000126,349.42+36.412478*k),(.000110,84.66+18.206239*k),
                     (.000062,141.74+53.303771*k),(.000060,207.14+2.453732*k),
                     (.000056,154.84+7.306860*k),(.000047,34.52+27.261239*k),
                     (.000042,207.19+.121824*k),(.000040,291.34+1.844379*k),
                     (.000037,161.72+24.198154*k),(.000035,239.56+25.513099*k),
                     (.000023,331.55+3.592518*k)]
        jde = (2451550.09765 + 29.530588853*k + .0001337*t*t
               - .000000150*t**3 + .00000000073*t**4
               + sum(a*sin(radians(b % 360)) for a,b in terms+planetary))
        y = year + (month-.5)/12
        u = y - 2000
        if y < 2005:
            dt = 63.86+.3345*u-.060374*u*u+.0017275*u**3+.000651814*u**4+.00002373599*u**5
        elif y < 2050:
            dt = 62.92+.32217*u+.005589*u*u
        else:
            dt = -20+32*((y-1820)/100)**2-.5628*(2150-y)
        local = (epoch + timedelta(days=jde-2451545, seconds=-dt)).astimezone(ZoneInfo('Europe/Moscow')).date()
        if (local.year, local.month) == (year, month):
            result.add(local)
    return frozenset(result)


def draw_moon(draw, cx, cy, radius=8):
    """Small full disk with craters; no emoji-font or network dependency."""
    draw.ellipse((cx-radius,cy-radius,cx+radius,cy+radius), fill='#f5f0d6', outline=INK, width=1)
    draw.ellipse((cx-5,cy-4,cx-2,cy-1), fill='#c9c4ae')
    draw.ellipse((cx+2,cy+2,cx+4,cy+4), fill='#d5d0b9')


def render(state, span, today, output):
    """Write a deterministic private PNG atomically; return its manifest.

    Months are deduplicated and sorted, not padded with a third empty month.
    Today is an independent outline, never a claim of ongoing bleeding.
    """
    earliest, latest = date.fromisoformat(span['earliest']), date.fromisoformat(span['latest'])
    if earliest > latest:
        raise ValueError('Forecast earliest follows latest')
    if span.get('estimate') and not earliest <= date.fromisoformat(span['estimate']) <= latest:
        raise ValueError('Forecast estimate outside its window')
    last = state['cycles'][-1]
    dates = [today, date.fromisoformat(last['start']), earliest, latest]
    month_set = {(d.year, d.month) for d in dates}
    ranges = [(date.fromisoformat(last['start']),
               date.fromisoformat(last['end'] or last['start'])),
              (date.fromisoformat(span['earliest']), date.fromisoformat(span['latest']))]
    for start, end in ranges:
        for index in range(start.year*12+start.month-1, end.year*12+end.month):
            y, m = divmod(index, 12)
            month_set.add((y, m+1))
    months = sorted(month_set)
    cal = calendar.Calendar(firstweekday=0)
    weeks = [cal.monthdayscalendar(y, m) for y, m in months]
    row_heights = [146 + max(len(w) for w in weeks[i:i+2]) * 72
                   for i in range(0, len(weeks), 2)]
    legend_y = 568 + sum(row_heights) + max(0, len(row_heights)-1)*28 + 18
    width, height = 1080, max(1578, legend_y + 390)
    im = Image.new('RGB', (width, height), BG)
    draw = ImageDraw.Draw(im)
    for y in range(28, height, 56):
        draw.line((0, y, width, y), fill='#f3f6f2', width=1)
    draw.line((54, 0, 54, height), fill='#f1dcd7', width=1)

    # Text is fitted to its actual available width, including long date ranges.
    def text(x, y, value, size, fill=INK, bold=False, serif=False,
             italic=False, max_width=916, anchor='lt'):
        f = font(size, bold, serif, italic)
        while draw.textlength(value, font=f) > max_width and size > 10:
            size -= 1
            f = font(size, bold, serif, italic)
        draw.text((x, y), value, font=f, fill=fill, anchor=anchor)
        return draw.textlength(value, font=f)

    text(96, 68, 'СИНТЕТИЧЕСКИЙ ПРИМЕР' if state.get('stage') == 'fixture' else 'ЛИЧНЫЙ БЛОКНОТ', 22, MUTED, bold=True)
    text(96, 129, 'Заметки о цикле', 78, serif=True, italic=True)
    cycle_day = (today - date.fromisoformat(last['start'])).days + 1
    text(96, 270, f'{short_date(today.isoformat())} {today.year} · день цикла {cycle_day}', 24, MUTED)
    text(96, 330, 'ПРЕДПОЛАГАЕМОЕ НАЧАЛО', 21, MUTED)
    window = date_range(span['earliest'], span['latest'])
    # Golden underline is a forecast heading accent, not a bleeding-day band.
    fsize = 74
    while draw.textlength(window, font=font(fsize, serif=True)) > 916:
        fsize -= 1
    window_width = draw.textlength(window, font=font(fsize, serif=True))
    draw.rectangle((96, 371 + fsize*.65, 96+window_width, 371+fsize*.99), fill=HIGHLIGHT)
    text(96, 371, window, fsize, serif=True)
    estimate = span.get('estimate')
    text(96, 475, f'Ориентир — {short_date(estimate)}' if estimate else 'Точного ориентира пока нет', 24, MUTED)

    counts = {'confirmed': 0, 'possible_start': 0, 'plain': 0}
    today_count = 0
    moon_dates = set().union(*(full_moons(y, m) for y, m in months))
    moon_markers = []
    ytop = 568
    for i, ((year, month), rows) in enumerate(zip(months, weeks)):
        left = 96 + (i % 2)*480 if len(months) > 1 else 336
        text(left, ytop, MONTHS[month-1].capitalize(), 40, serif=True, max_width=320)
        text(left+436, ytop+8, str(year), 18, MUTED, anchor='rt', max_width=80)
        centers = [left+(col+.5)*436/7 for col in range(7)]
        for col, label in enumerate(('ПН','ВТ','СР','ЧТ','ПТ','СБ','ВС')):
            text(centers[col], ytop+82, label, 18, MUTED, anchor='mm', max_width=60)
        for row, days in enumerate(rows):
            for col, day in enumerate(days):
                if not day:
                    continue
                d = date(year, month, day)
                cx, cy = centers[col], ytop+146+row*72
                kind = day_kind(state, span, d)
                counts[kind] += 1
                if kind == 'confirmed':
                    draw.rounded_rectangle((cx-28,cy-29,cx+28,cy+29), radius=15, fill=ROSE)
                elif kind == 'possible_start':
                    for angle in range(0, 360, 24):
                        draw.arc((cx-27,cy-29,cx+27,cy+29), angle, angle+12, fill=GOLD, width=2)
                if d == today:
                    today_count += 1
                    draw.ellipse((cx-30,cy-32,cx+30,cy+32), outline=INK, width=3)
                text(cx, cy, str(day), 28, 'white' if kind == 'confirmed' else INK,
                     anchor='mm', max_width=56)
                if d in moon_dates:
                    mx, my = round(cx+23), round(cy+23)
                    draw_moon(draw, mx, my)
                    moon_markers.append({'date': d.isoformat(), 'center': [mx, my]})
        if i % 2 == 1 or i == len(months)-1:
            ytop += row_heights[i//2] + 28

    y = legend_y
    for x, label, kind in ((100, 'Подтверждено', 'fact'), (371, 'Прогноз начала', 'forecast'), (674, 'Сегодня', 'today')):
        if kind == 'fact':
            draw.ellipse((x,y,x+18,y+18), fill=ROSE)
        elif kind == 'forecast':
            draw.ellipse((x,y,x+18,y+18), fill=HIGHLIGHT, outline=GOLD, width=1)
        else:
            draw.ellipse((x,y,x+18,y+18), outline=INK, width=2)
        text(x+30, y-1, label, 20, MUTED, max_width=260)
    draw_moon(draw, 110, y+47)
    text(130, y+36, 'Полнолуние · даты по Москве', 20, MUTED, max_width=700)
    actual = (date_range(last['start'], last['end']) if last['end']
              else f'{short_date(last["start"])} · конец не указан')
    for ly, label, value in ((y+88, 'Подтверждено', actual), (y+170, 'Ожидаемое начало', window)):
        text(96, ly, label, 25, MUTED, max_width=340)
        text(1012, ly, value, 25, bold=True, anchor='rt', max_width=550)
        draw.line((96, ly+50, 1012, ly+50), fill=LINE, width=2)
    foot = y+272
    draw.line((96,foot-24,1012,foot-24), fill=LINE, width=2)
    policy = state.get('forecast_policy', {})
    if policy.get('mode') == 'temporary_fixed':
        rule = f'{policy["days"]} дней ±{policy["tolerance"]} день'
        note = 'Временное правило, пока собираем историю.'
    else:
        rule = 'Календарный расчёт'
        note = 'Наблюдаемый диапазон не гарантирован.'
    text(96, foot+12, rule, 20, max_width=340)
    text(1012, foot+12, note, 20, MUTED, anchor='rt', max_width=570)
    text(1012, foot+48, 'Не гарантирует дату начала или овуляции.', 20, MUTED, anchor='rt', max_width=570)
    text(96, foot+86, 'Пунктир — варианты начала, не длительность месячных.', 20, MUTED)

    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(suffix='.png', dir=path.parent)
    os.close(fd)
    try:
        im.save(tmp, format='PNG', optimize=True)
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return {'path': str(path.resolve()), 'size': [width, height],
            'style': '05-notebook', 'today': today.isoformat(),
            'confirmed_label': actual, 'forecast_label': window,
            'months': [f'{y:04d}-{m:02d}' for y,m in months],
            'confirmed_count': counts['confirmed'],
            'possible_start_count': counts['possible_start'], 'today_count': today_count,
            'full_moon_dates': sorted(d.isoformat() for d in moon_dates),
            'full_moon_timezone': 'Europe/Moscow', 'moon_legend': 'Полнолуние',
            'full_moon_markers': moon_markers,
            'ovulation_marked': False, 'state_modified': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--today', help='ISO local date; omit for current Moscow date')
    args = p.parse_args()
    source, target = Path(args.state), Path(args.output)
    if source.resolve() == target.resolve() or (target.exists() and source.samefile(target)):
        p.error('Output must not overwrite state')
    from cycle_engine import forecast
    state = json.loads(source.read_text())
    today = date.fromisoformat(args.today) if args.today else datetime.now(ZoneInfo('Europe/Moscow')).date()
    result = render(state, forecast(state)['next_period'], today, args.output)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
