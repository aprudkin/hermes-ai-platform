"""Capture native accounting evidence through Hermes' Telegram handler API."""
import importlib.util
import logging
import os
from pathlib import Path
from types import SimpleNamespace


def register(ctx):
    from hermes_constants import get_hermes_home
    home = Path(get_hermes_home()).resolve()
    config = getattr(ctx, 'config', None)
    chat = config.get('chat_id') if isinstance(config, dict) else None
    if config is None and hasattr(ctx, 'get_config'):
        chat = ctx.get_config('chat_id')
    chat = chat if chat is not None else os.environ.get('BABLOMAT_CHAT_ID')
    if not chat:
        return
    chat = str(chat)
    script = Path(__file__).resolve().parents[1] / 'scripts/cash_native_input.py'
    if not script.is_file():
        script = home / 'scripts/cash_native_input.py'
    spec = importlib.util.spec_from_file_location('_cash_native_capture', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def wire(application, adapter):
        from telegram.ext import MessageHandler, filters
        if chat not in adapter._telegram_observe_allowed_chats():
            return  # No new chat access: observe only an already authorized source.
        group = -100
        route = (str(home), chat)
        if any(getattr(h.callback, '_cash_native_route', None) == route
               for h in application.handlers.get(group, [])):
            return

        async def observe(update, context):
            try:
                module.capture(home, chat, SimpleNamespace(raw_message=update.effective_message))
            except Exception:
                logging.getLogger(__name__).warning('Native accounting capture failed; evidence unavailable', exc_info=True)

        observe._cash_native_route = route
        application.add_handler(MessageHandler(filters.Chat(chat_id=int(chat)), observe, block=True), group=group)

    ctx.register_telegram_handler(wire)
