"""Separate participant text from rendered Telegram reply history."""
import re


REPLY_CONTEXT = re.compile(
    r'\A\s*\[Replying to(?: your previous message)?: "(.*?)"\](?:\r?\n|$)',
    re.DOTALL,
)


def message_body(content: str) -> str:
    while content.lstrip().startswith('[Replying to'):
        match = REPLY_CONTEXT.match(content)
        if match is None:
            return ''  # Incomplete history is not a financial instruction.
        content = content[match.end():]
    content = re.sub(r'<blockquote\b[^>]*>.*?(?:</blockquote\s*>|$)', '', content,
                     flags=re.IGNORECASE | re.DOTALL)
    return '\n'.join(line for line in content.splitlines()
                     if not line.lstrip().startswith('>')).strip()
