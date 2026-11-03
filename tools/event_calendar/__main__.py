"""Explicit local input/output; never discovers mail, routes or accounts."""
import argparse
from datetime import date
import json
from pathlib import Path
import sys

# Direct execution avoids collision with Hermes' unrelated top-level tools package.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = 'event_calendar'

from .caption import build_caption
from .render_day_reminder import render as render_day
from .render_events import render as render_month


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['day', 'month', 'caption'])
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--today', required=True, type=date.fromisoformat)
    parser.add_argument('--output', type=Path, help='Required for day/month PNG; caption payload is stdout only')
    args = parser.parse_args()
    if args.command != 'caption' and args.output is None:
        parser.error('--output is required for day/month')
    if args.command == 'caption' and args.output is not None:
        parser.error('caption writes JSON to stdout; omit --output')
    try:
        if args.output is not None and (args.input.resolve() == args.output.resolve()
                or (args.output.exists() and args.input.samefile(args.output))):
            parser.error('Output must not overwrite input')
        data = json.loads(args.input.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or type(data.get('schema_version')) is not int or data['schema_version'] != 1:
            raise ValueError('schema_version must be 1')
        if args.command == 'month':
            manifest = render_month(data['events'], args.today, args.output)
        elif args.command == 'day':
            manifest = render_day(data['event'], args.today, args.output, route=data['route'])
        else:
            manifest = build_caption(data['event'], args.today, data['route'])
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == '__main__':
    main()
