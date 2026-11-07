#!/usr/bin/env python3
"""Independent deterministic clarification escalation; opt-in, local cron output."""
import argparse
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from cash_review_sender import PrivateReviewSender


def run_escalations(home, *, enabled=False, post=None, clock=time.time):
    home = Path(home)
    path = home / 'cash-ledger' / 'review-cases.db'
    if not enabled or not path.exists():
        return 0
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as c:
        if not c.execute("SELECT 1 FROM cases WHERE group_state='sent' AND reply_status='open' LIMIT 1").fetchone():
            return 0
    sender = PrivateReviewSender(home, post=post, clock=clock)
    # Missing/unreadable observations fail closed: no blind reminder without checking replies.
    sender.scan_replies(home / 'state.db')
    return sender.process_due()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path(os.environ['HERMES_HOME']) if os.environ.get('HERMES_HOME') else None, required=not bool(os.environ.get('HERMES_HOME')))
    parser.add_argument('--enabled', action='store_true', help='Explicitly enable six-hour private escalations')
    args = parser.parse_args(argv)
    run_escalations(args.home, enabled=args.enabled)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
