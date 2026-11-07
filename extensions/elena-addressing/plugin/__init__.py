"""Native profile-local hook; intentionally not auto-enabled."""
import importlib.util
from pathlib import Path


def register(ctx):
    # Resolve the active home under the loader's profile scope; never a global default.
    from hermes_constants import get_hermes_home
    home = Path(get_hermes_home()).resolve()
    # Refuse cross-profile loading of this profile-local plugin/helper pair.
    if Path(__file__).resolve().parents[2] != home:
        raise ValueError("elena-addressing must be loaded from the active profile")
    spec = importlib.util.spec_from_file_location(
        "_elena_addressing_helper", home / "scripts/elena_addressing.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    if not helper.configured():
        raise ValueError('Explicit addressing profile and recipient/group routing is required')
    selector = helper.Selector.from_profile(home)

    def pre_gateway_dispatch(*, event, gateway=None, session_store=None, **kwargs):
        return helper.rewrite_event(event, selector)

    ctx.register_hook("pre_gateway_dispatch", pre_gateway_dispatch)
    # Registration receipt only: no messages, names or seed; never written per event.
    import os, json, tempfile
    from datetime import datetime, timezone
    target = home / 'plugin-data/elena-addressing/runtime.json'
    fd, temp = tempfile.mkstemp(dir=target.parent, prefix='.runtime-')
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump({'pid': os.getpid(), 'profile_home': str(home),
                       'hook': 'pre_gateway_dispatch', 'version': '1.0.0',
                       'loaded_at': datetime.now(timezone.utc).isoformat()}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
