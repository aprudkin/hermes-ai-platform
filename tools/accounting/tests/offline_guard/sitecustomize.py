"""Inherited by child Python processes: offline tests cannot reach transports/state."""
import os
import sys
import tempfile
from pathlib import Path

TEMP = Path(tempfile.gettempdir()).resolve()
def audit(event, args):
    if event in ('socket.connect', 'socket.connect_ex', 'socket.getaddrinfo', 'socket.bind'):
        raise AssertionError('Offline test attempted network access')
    if event in ('open', 'sqlite3.connect') and args and isinstance(args[0], (str, bytes, os.PathLike)):
        raw = os.fsdecode(args[0])
        if raw.startswith('file:'):
            raw = raw[5:].split('?', 1)[0]
        path = Path(raw).resolve()
        if (event == 'sqlite3.connect' or path.name in ('state.db', '.env')) and not path.is_relative_to(TEMP):
            raise AssertionError('Offline test attempted non-temporary state/credential access')
sys.addaudithook(audit)
