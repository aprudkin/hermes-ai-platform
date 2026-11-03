"""Notebook day timeline: local PNG only, no scheduling or sends."""
from datetime import date,datetime,timedelta
import json
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo
from PIL import Image,ImageDraw
from . import style
from .data import timeline


def render(event,today,output,route=None):
    start,departure,before,after=timeline(event,today,route)
    image=Image.new('RGB',(1080,1640),style.BG)
    draw=ImageDraw.Draw(image)
    for y in range(28,1640,56):
        draw.line((0,y,1080,y),fill='#f3f6f2',width=1)
    draw.line((54,0,54,1640),fill='#f1dcd7',width=1)

    def text(x,y,value,size,color=style.INK,*,bold=False,serif=False,italic=False,anchor='lt',width=916):
        face=style.font(size,bold=bold,serif=serif,italic=italic)
        while draw.textlength(value,font=face)>width and size>10:
            size-=1
            face=style.font(size,bold=bold,serif=serif,italic=italic)
        draw.text((x,y),value,font=face,fill=color,anchor=anchor)

    text(96,72,'СИНТЕТИЧЕСКИЙ ПРИМЕР' if event.get('synthetic') or route.get('synthetic') else 'ЛИЧНЫЙ БЛОКНОТ',30,style.MUTED,bold=True)
    relative='Завтра' if start.date()==today+timedelta(days=1) else 'Событие'
    text(96,158,f'{relative},',100,serif=True,italic=True)
    text(96,282,f'{start.day} {style.GENITIVE[start.month-1]}',110,serif=True,italic=True)
    text(96,425,f'{start.year} · напоминание за сутки',32,style.MUTED)
    draw.rectangle((96,570,690,616),fill=style.HIGHLIGHT)
    text(96,520,event['name'],86,bold=True,width=916)
    text(96,654,event['venue'],42,style.MUTED)

    left,right,y=96,984,1040
    def x(value):
        return left+(right-left)*(value-before).total_seconds()/(after-before).total_seconds()
    a,b,c=x(before),x(start),x(after)
    draw.line((left,y,right,y),fill=style.LINE,width=3)
    ticks=[before]
    tick=before.replace(minute=before.minute//30*30,second=0,microsecond=0)+timedelta(minutes=30)
    while tick<after:
        ticks.append(tick)
        tick+=timedelta(minutes=30)
    ticks.append(after)
    for moment in ticks:
        xx=x(moment)
        major=moment.minute==0 or moment in (before,after)
        draw.line((xx,y-8,xx,y+12 if major else y+6),fill=style.MUTED,width=2 if major else 1)
        text(xx,y+60,moment.strftime('%H:%M'),35 if major else 28,style.MUTED,anchor='mm',width=108)
    # Hatch only the event label: an unknown end must not become a made-up duration.
    box=(int(b-130),820,int(b+130),924)
    pattern=Image.new('RGB',image.size,'#f7e7e2')
    hatch=ImageDraw.Draw(pattern)
    for offset in range(-110,380,17):
        hatch.line((box[0]+offset,box[3],box[0]+offset+104,box[1]),fill='#ddb7ae',width=2)
    mask=Image.new('L',image.size,0)
    ImageDraw.Draw(mask).rounded_rectangle(box,radius=9,fill=255)
    image.paste(pattern,(0,0),mask)
    draw.line((b,926,b,y+14),fill=style.ROSE,width=5)
    draw.ellipse((b-9,y-9,b+9,y+9),fill=style.ROSE)
    text(b,774,'НАЧАЛО',30,style.MUTED,bold=True,anchor='mm',width=240)
    text(b,872,event['time'],76,bold=True,anchor='mm',width=244)

    if route:
        dx=x(departure)
        if left<=dx<=right:
            draw.line((dx,926,dx,y+14),fill=style.INK,width=4)
            draw.ellipse((dx-7,y-7,dx+7,y+7),fill=style.INK)
            text(dx,774,'ВЫЕЗД',30,style.MUTED,bold=True,anchor='mm',width=240)
            text(dx,872,departure.strftime('%H:%M'),76,bold=True,anchor='mm',width=244)
        observed=datetime.fromisoformat(route['observed_at']).astimezone(ZoneInfo('Europe/Moscow'))
        text(96,1260,'Оценка на '+observed.strftime('%d.%m %H:%M')+' МСК',34,style.MUTED)
        lo,hi=route['observed_minutes_range']
        text(96,1360,f'В дороге {lo}–{hi} мин',54,serif=True)
        text(96,1470,f'Запас до начала: {route["arrival_buffer_minutes"]} мин',36,style.MUTED)
    text(right,1180,'+1 час',28,style.MUTED,anchor='rt',width=150)

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
    return {'output':str(output),'display_day':start.date().isoformat(),'event_start':start.isoformat(),
            'window_start':before.isoformat(),'window_end':after.isoformat(),'axis_labels':[t.strftime('%H:%M') for t in ticks],
            'hatching':'event_start_marker_only','event_end':None,
            'departure':departure.isoformat() if departure else None,
            'route_observed_at':route['observed_at'],'route_estimate_kind':route['estimate_kind'],
            'positions':{'start':a,'departure':dx,'event':b,'end':c},'is_actual_event_duration':False}
