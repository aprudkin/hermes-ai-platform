"""Recipient-bound ct1 callbacks, wired through Hermes' native Telegram client.

No second polling connection, no core patch, no group message on installation.
"""
import asyncio
from datetime import datetime
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
from zoneinfo import ZoneInfo

LOG=logging.getLogger('cycle_buttons')


def _profile_home():
    from hermes_constants import get_hermes_home
    return Path(get_hermes_home()).resolve()


def _load_buttons(home):
    path=Path(home)/'skills/productivity/cycle-tracker/scripts/cycle_buttons.py'
    spec=importlib.util.spec_from_file_location('manager_cycle_buttons',path)
    mod=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=mod
    spec.loader.exec_module(mod)
    return mod


def _probe(home):
    directory=home/'cycle-tracker'
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    value={'wired':True,'prefix':'ct1:','pid':os.getpid(),
           'profile_home':str(home),'plugin_version':'1.0.0',
           'wired_at':datetime.now(ZoneInfo('Europe/Moscow')).isoformat()}
    fd,name=tempfile.mkstemp(prefix='.button-handler.',suffix='.json',dir=directory)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w') as stream:
            json.dump(value,stream,ensure_ascii=False,indent=2)
            stream.flush();os.fsync(stream.fileno())
        os.replace(name,directory/'button-handler-runtime.json')
    finally:
        if os.path.exists(name):os.unlink(name)


def register(ctx):
    home=_profile_home()

    def wire(native,adapter):
        # Import at connect time, so CLI discovery needs no Telegram initialization.
        from telegram.ext import CallbackQueryHandler

        async def on_button(update,context):
            query=getattr(update,'callback_query',None)
            if query is None:
                return
            async def answer(text,show_alert=False):
                try:
                    await query.answer(text=text,show_alert=show_alert)
                except Exception:
                    LOG.warning('Cycle button feedback was not acknowledged')
            try:
                data=getattr(query,'data',None)
                if not isinstance(data,str) or not data.startswith('ct1:'):
                    return
                state_path=home/'cycle-tracker/state.json'
                state=json.loads(state_path.read_text())
                actor=str(getattr(getattr(query,'from_user',None),'id',''))
                message=getattr(query,'message',None)
                chat=str(getattr(message,'chat_id',''))
                mid=getattr(message,'message_id',None)
                author=getattr(message,'from_user',None)
                if (state.get('stage')!='active' or state.get('delivery_enabled') is not True
                        or actor!=state.get('confirmer_id')
                        or 'telegram:'+chat!=state.get('planned_destination')
                        or str(getattr(author,'id',''))!=state.get('runner',{}).get('expected_bot_id')
                        or getattr(author,'is_bot',False) is not True
                        or type(mid) is not int or mid<=0):
                    await answer('Эти кнопки недоступны для этого ответа.')
                    return
                auth=getattr(adapter,'_is_callback_user_authorized',None)
                if not callable(auth) or auth(actor,chat_id=getattr(message,'chat_id',None),
                        chat_type=str(getattr(getattr(message,'chat',None),'type','')),
                        thread_id=str(message.message_thread_id) if getattr(message,'message_thread_id',None) is not None else None,
                        user_name=getattr(getattr(query,'from_user',None),'first_name',None)) is not True:
                    await answer('Нет разрешения на этот ответ.')
                    return
                buttons=_load_buttons(home)
                result=await asyncio.to_thread(buttons.handle_button,state_path,
                    actor_id=actor,chat_id=chat,message_id=mid,data=data,
                    callback_id=str(getattr(query,'id','')),
                    now=datetime.now(ZoneInfo('Europe/Moscow')),
                    message_author_id=str(author.id),bot_id=state['runner']['expected_bot_id'])
                if not isinstance(result,dict):
                    raise ValueError('Invalid callback result')
                await answer(str(result.get('text','Ответ не принят.'))[:180],
                             show_alert=result.get('show_alert') is True)
                if result.get('accepted') is True and result.get('clear_keyboard') is True:
                    # Only keyboard metadata changes. Preserve original caption and photo.
                    try:
                        edited=await query.edit_message_reply_markup(reply_markup=None)
                        if (getattr(edited,'message_id',None)!=mid
                                or str(getattr(edited,'chat_id',''))!=chat
                                or getattr(edited,'reply_markup',None) is not None):
                            LOG.warning('Cycle keyboard removal not verified; stored answer retained')
                    except Exception:
                        LOG.warning('Cycle keyboard removal failed; stored answer retained')
            except Exception:
                LOG.error('Cycle button handling failed; inspect private cycle state')
                await answer('Не удалось обработать ответ. Можно ответить текстом через reply.')

        native.add_handler(CallbackQueryHandler(on_button,pattern=r'^ct1:'),group=0)
        _probe(home)

    ctx.register_platform_handler('telegram',wire)
