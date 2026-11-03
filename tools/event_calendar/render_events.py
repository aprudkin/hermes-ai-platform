"""Local notebook-style event calendar; no private-state dependencies."""
import calendar
from datetime import date, datetime
import os
from pathlib import Path
import tempfile
from PIL import Image, ImageDraw

from . import style
from .data import validate_event


def render(events, today, output):
    if not events:
        raise ValueError('No event dates to display')
    if not isinstance(events, list):
        raise ValueError('events must be an array')
    for event in events:
        validate_event(event)
    events = sorted(events, key=lambda e: (e['date'], e['time']))
    months = sorted({(date.fromisoformat(e['date']).year, date.fromisoformat(e['date']).month) for e in events})
    if len(months) > 2 or len(events) > 4:
        raise ValueError('This visual prototype is sized for two months and four events')
    image = Image.new('RGB', (1080,1660), style.BG)
    draw = ImageDraw.Draw(image)
    for y in range(28,1660,56):
        draw.line((0,y,1080,y),fill='#f3f6f2',width=1)
    draw.line((54,0,54,1660),fill='#f1dcd7',width=1)

    def text(x,y,value,size,*,color=style.INK,bold=False,serif=False,italic=False,anchor='lt',width=916):
        face = style.font(size,bold=bold,serif=serif,italic=italic)
        while draw.textlength(value,font=face)>width and size>10:
            size-=1
            face=style.font(size,bold=bold,serif=serif,italic=italic)
        draw.text((x,y),value,font=face,fill=color,anchor=anchor)

    text(96,62,'СИНТЕТИЧЕСКИЙ ПРИМЕР' if any(e.get('synthetic') for e in events) else 'ЛИЧНЫЙ БЛОКНОТ',22,bold=True,color=style.MUTED)
    text(96,120,'Планы на вечер',76,serif=True,italic=True)
    period=' — '.join(style.MONTHS[m-1] for _,m in months)
    period=period[:1].upper()+period[1:]
    underline=draw.textlength(period,font=style.font(58,serif=True))
    draw.rectangle((96,276,96+underline,302),fill=style.HIGHLIGHT)
    text(96,240,period,58,serif=True)
    text(96,330,str(months[0][0])+' · события из писем',24,color=style.MUTED)

    by_date={}
    for number,event in enumerate(events,1):
        by_date.setdefault(event['date'],[]).append((number,event))
    markers=today_markers=0
    for i,(year,month) in enumerate(months):
        left=96+i*480 if len(months)>1 else 336
        text(left,414,style.MONTHS[month-1].capitalize(),38,serif=True,width=330)
        text(left+436,426,str(year),18,color=style.MUTED,anchor='rt',width=80)
        for column,label in enumerate(('ПН','ВТ','СР','ЧТ','ПТ','СБ','ВС')):
            cx=left+(column+.5)*436/7
            text(cx,492,label,17,color=style.MUTED,anchor='mm',width=58)
        for row,days in enumerate(calendar.Calendar(firstweekday=0).monthdayscalendar(year,month)):
            for column,day in enumerate(days):
                if not day:
                    continue
                d=date(year,month,day)
                cx=left+(column+.5)*436/7
                cy=548+row*68
                found=by_date.get(d.isoformat(),[])
                if found:
                    draw.rounded_rectangle((cx-25,cy-27,cx+25,cy+32),radius=13,fill='#f4ded8')
                    markers+=len(found)
                    text(cx,cy+19,found[0][1]['time'],12,bold=True,color=style.ROSE,anchor='mm',width=49)
                    draw.ellipse((cx+13,cy-35,cx+33,cy-15),fill=style.ROSE)
                    text(cx+23,cy-25,str(found[0][0]),11,bold=True,color='white',anchor='mm',width=18)
                if d==today:
                    draw.ellipse((cx-23,cy-26,cx+23,cy+20),outline=style.INK,width=2)
                    today_markers+=1
                text(cx,cy-5,str(day),27,bold=bool(found),anchor='mm',width=56)

    draw.line((96,972,1000,972),fill=style.LINE,width=2)
    text(96,997,'ОТМЕЧЕНО В КАЛЕНДАРЕ',19,bold=True,color=style.MUTED)
    for i,event in enumerate(events):
        y=1044+i*122
        draw.ellipse((96,y+1,132,y+37),fill=style.ROSE)
        text(114,y+19,str(i+1),19,bold=True,color='white',anchor='mm',width=30)
        d=date.fromisoformat(event['date'])
        text(154,y,f'{d.day} {style.GENITIVE[d.month-1]} · {event["time"]}',24,bold=True,width=840)
        text(154,y+34,event['name'],34,serif=True,width=840)
        venue=event['venue']
        if event.get('previous_time'):
            venue+=' · время изменено с '+event['previous_time']
        text(154,y+80,venue,20,color=style.MUTED,width=840)
    draw.ellipse((98,1572,118,1592),outline=style.INK,width=2)
    text(132,1570,'Обведено сегодня. Время — как в письмах.',18,color=style.MUTED,width=850)
    text(96,1610,'Эскиз оформления · без добавления событий в календарь',16,color=style.MUTED)

    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,name=tempfile.mkstemp(dir=output.parent,suffix='.png')
    try:
        with os.fdopen(fd,'wb') as stream:
            image.save(stream,format='PNG')
        os.chmod(name,0o600)
        os.replace(name,output)
    finally:
        if Path(name).exists():
            Path(name).unlink()
    return {'output':str(output),'months':[list(m) for m in months],
            'event_count':len(events),'event_dates':[e['date'] for e in events],
            'times':[e['time'] for e in events], 'event_markers':markers,
            'today_markers':today_markers,'uses_cycle_state':False}
