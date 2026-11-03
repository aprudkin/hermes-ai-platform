"""Local Elena-only addressing selection. Standard library; no network or model calls."""
import hashlib
import json
import os
from pathlib import Path
import random
import stat

WEIGHTS = (("Ле", 300),)
TOTAL = 300
ELENA_ID = os.environ.get("ELENA_ADDRESSING_USER_ID", "")
OWNER_ID = os.environ.get("ELENA_ADDRESSING_OWNER_ID", "")
GROUP_ID = os.environ.get("ELENA_ADDRESSING_GROUP_ID", "")
PROFILE_NAME = os.environ.get("ELENA_ADDRESSING_PROFILE", "")


def name_for_slot(slot):
    """Map one uniform integer in [0, 299] to the literal weighted name."""
    if type(slot) is not int or not 0 <= slot < TOTAL:
        raise ValueError("slot must be an integer in 0..299")
    boundary = 0
    for name, weight in WEIGHTS:
        boundary += weight
        if slot < boundary:
            return name


class Selector:
    """Seed loaded once; event keys contain platform/chat/message IDs, never text."""

    def __init__(self, seed):
        self._seed = seed

    @classmethod
    def from_profile(cls, profile):
        path = Path(profile) / "plugin-data/elena-addressing/seed"
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # O_EXCL avoids replacing an existing seed. No seed or content is logged.
        flags = os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            fd = os.open(path, flags | os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as stream:
                stream.write(os.urandom(32))
        fd = os.open(path, flags | os.O_RDONLY)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError("seed must be a regular file with mode 0600")
            seed = stream.read(33)
        if len(seed) != 32:
            raise ValueError("seed must contain exactly 32 bytes")
        return cls(seed)

    def select(self, platform, chat_id, message_id):
        """Return (name, slot); stable retries. randrange uses rejection, not modulo."""
        if not all(isinstance(v, str) and v for v in (platform, chat_id, message_id)):
            raise ValueError("platform, chat_id and message_id must be nonempty strings")
        key = json.dumps([platform, chat_id, message_id], ensure_ascii=True,
                         separators=(",", ":")).encode("ascii")
        digest = hashlib.blake2b(key, key=self._seed, digest_size=32).digest()
        slot = random.Random(int.from_bytes(digest, "big")).randrange(TOTAL)
        return name_for_slot(slot), slot


NOTE_MARKER = "[elena-addressing]"


def configured():
    return bool(ELENA_ID.isdigit() and int(ELENA_ID) > 0
                and OWNER_ID.isdigit() and int(OWNER_ID) > 0
                and ELENA_ID != OWNER_ID and GROUP_ID.startswith('-100')
                and GROUP_ID[4:].isdigit() and PROFILE_NAME)


def rewrite_event(event, selector):
    """Return only a text rewrite; host still performs its normal authentication.

    Source IDs come from adapter SessionSource, not text, usernames or replies.
    This conditional style hint is only for Elena, even on Alexy's group turns.
    """
    if not configured():
        return None
    source = getattr(event, "source", None)
    if source is None or getattr(event, "internal", False):
        return None
    platform = getattr(source, "platform", None)
    if getattr(platform, "value", platform) != "telegram":
        return None
    if (getattr(source, "is_bot", False)
            or getattr(source, "profile_route_rejected", False)
            or getattr(source, "profile", None) not in (None, PROFILE_NAME)):
        return None
    sender = getattr(source, "user_id", None)
    chat = getattr(source, "chat_id", None)
    if sender not in (ELENA_ID, OWNER_ID):
        return None
    mirrored = getattr(event, "user_id", None)
    if mirrored is not None and mirrored != sender:
        return None
    chat_type = getattr(source, "chat_type", None)
    group = chat == GROUP_ID and chat_type in ("group", "supergroup", "forum")
    dm = chat == ELENA_ID and sender == ELENA_ID and chat_type == "dm"
    if not (group or dm):
        return None
    text = getattr(event, "text", None)
    message_id = getattr(event, "message_id", None)
    kind = getattr(event, "message_type", None)
    if (not isinstance(text, str) or not text.strip() or text.lstrip().startswith("/")
            or NOTE_MARKER in text or getattr(kind, "value", kind) == "command"
            or not isinstance(message_id, str) or not message_id):
        return None
    name, _ = selector.select("telegram", chat, message_id)
    hint = (f"{NOTE_MARKER} Если отвечаешь Елене и обращение уместно: «{name}». "
            "Не относится к Луку. Не добавляй обращение в каждый ответ.")
    return {"action": "rewrite", "text": text + "\n\n" + hint}


def main(argv=None):
    """Print only selection metadata, never the seed or source message text."""
    import argparse
    import secrets
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=Path(__file__).resolve().parents[1])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--event-key", nargs=3, metavar=("PLATFORM", "CHAT_ID", "MESSAGE_ID"))
    mode.add_argument("--random", action="store_true")
    args = parser.parse_args(argv)
    if args.event_key:
        name, slot = Selector.from_profile(args.profile).select(*args.event_key)
    else:
        slot = secrets.randbelow(TOTAL)
        name = name_for_slot(slot)
    print(json.dumps({"name": name, "slot": slot, "total": TOTAL}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
