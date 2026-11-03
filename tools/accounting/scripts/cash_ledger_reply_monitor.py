#!/usr/bin/env python3
"""Source-anchored cash checks; ambiguity questions use separate Hermes cases."""
import argparse
import os
from pathlib import Path
from cash_ledger_monitor import Ledger, run_monitor
from cash_reply_sender import ReplySender
from cash_review_sender import PrivateReviewSender


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home',type=Path,default=Path(os.environ['HERMES_HOME']) if os.environ.get('HERMES_HOME') else None, required=not bool(os.environ.get('HERMES_HOME')))
    parser.add_argument('--chat-id', default=os.environ.get('BABLOMAT_CHAT_ID'), required=not bool(os.environ.get('BABLOMAT_CHAT_ID')))
    args=parser.parse_args()
    home=args.home
    run_monitor(source_db=home/'state.db',ledger=Ledger(home/'cash-ledger'/'ledger.db'),
                state_path=home/'cash-ledger'/'monitor-state.json',
                stats_path=home/'cash-ledger'/'daily-stats.json',
                chat_id=args.chat_id,reply_sender=ReplySender(home,args.chat_id),
                review_sender=PrivateReviewSender(home))


if __name__=='__main__':
    main()
