import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import cash_activity_alerts as activity


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        with closing(sqlite3.connect(self.home / 'state.db')) as db, db:
            db.executescript('''CREATE TABLE sessions(id TEXT,chat_id TEXT);
                INSERT INTO sessions VALUES('b','-1008000000001');
                CREATE TABLE messages(id INTEGER PRIMARY KEY,session_id TEXT,role TEXT,active INTEGER,
                timestamp REAL,platform_message_id TEXT,_compressed_summary INTEGER);''')

    def add(self, row_id, hour=12, minute=0, *, message_id=None, role='user', active=1, summary=0):
        ts = datetime(2026,10,10,hour,minute,tzinfo=ZoneInfo('Europe/Moscow')).timestamp()
        with closing(sqlite3.connect(self.home / 'state.db')) as db, db:
            db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)',
                (row_id,'b',role,active,ts,str(message_id or row_id),summary))

    def test_wrapper_never_reenables_cancelled_activity_alerts_from_old_baseline(self):
        from unittest.mock import patch
        import cash_ledger_reply_monitor as wrapper
        calls = []
        activity.scan_activity(self.home,initialize=True)
        with patch.object(sys,'argv',['watcher','--home',str(self.home)]), \
                patch.object(wrapper,'Ledger'), patch.object(wrapper,'ReplySender'), \
                patch.object(wrapper,'PrivateReviewSender'), \
                patch.object(wrapper,'run_monitor',side_effect=lambda **kw:calls.append('ledger')), \
                patch.object(wrapper,'scan_activity',create=True,side_effect=lambda home:calls.append('alerts')):
            wrapper.main()
        self.assertEqual(calls,['ledger'])

    def test_wrapper_without_alert_baseline_keeps_legacy_behavior(self):
        from unittest.mock import patch
        import cash_ledger_reply_monitor as wrapper
        calls = []
        with patch.object(sys,'argv',['watcher','--home',str(self.home)]), \
                patch.object(wrapper,'Ledger'), patch.object(wrapper,'ReplySender'), \
                patch.object(wrapper,'PrivateReviewSender'), \
                patch.object(wrapper,'run_monitor',side_effect=lambda **kw:calls.append('ledger')), \
                patch.object(wrapper,'scan_activity',create=True,side_effect=lambda home:calls.append('alerts')):
            wrapper.main()
        self.assertEqual(calls,['ledger'])

    def test_outside_window_alerts_have_source_links_and_are_deduplicated(self):
        activity.scan_activity(self.home,initialize=True)
        self.add(1,1,59)
        self.add(2,2,0)
        self.add(3,9,59)
        self.add(4,10,0)
        self.add(5,10,0,message_id=4)
        self.add(6,12,0,role='assistant')
        self.add(7,12,0,active=0)
        self.add(8,12,0,summary=1)
        sent = []
        result = activity.scan_activity(self.home,sender=sent.append)
        self.assertEqual(result['alerted'],2)
        self.assertIn('01:59 МСК',sent[0])
        self.assertIn('https://t.me/c/8000000001/1',sent[0])
        self.assertIn('10:00 МСК',sent[1])
        self.assertIn('https://t.me/c/8000000001/4',sent[1])
        self.assertEqual(activity.scan_activity(self.home,sender=sent.append)['alerted'],0)
        self.assertEqual(len(sent),2)

    def test_cancelled_default_delivery_never_creates_clarification_cases(self):
        activity.scan_activity(self.home,initialize=True)
        self.add(1)
        from unittest.mock import patch
        with patch('cash_review_sender.PrivateReviewSender', side_effect=AssertionError('cancelled alerts must not create review cases')):
            self.assertEqual(activity.scan_activity(self.home), {'status':'disabled','scanned':0,'alerted':0})
            self.assertEqual(activity.scan_activity(self.home), {'status':'disabled','scanned':0,'alerted':0})
        self.assertFalse((self.home / 'cash-ledger' / 'review-cases.db').exists())

    def test_reinitialization_preserves_pending_new_messages(self):
        self.add(1)
        activity.scan_activity(self.home,initialize=True)
        self.add(2)
        activity.scan_activity(self.home,initialize=True)
        sent = []
        self.assertEqual(activity.scan_activity(self.home,sender=sent.append)['alerted'],1)
        self.assertIn('/2',sent[0])

    def test_missing_baseline_fails_closed(self):
        self.add(1)
        with self.assertRaisesRegex(RuntimeError,'Initialize'):
            activity.scan_activity(self.home,sender=lambda text:self.fail('No historical sends'))

    def test_initialize_does_not_alert_history(self):
        self.add(1)
        sent = []
        self.assertEqual(activity.scan_activity(self.home,initialize=True)['status'],'initialized')
        self.assertEqual(activity.scan_activity(self.home,sender=sent.append)['alerted'],0)
        self.assertEqual(sent,[])


if __name__ == '__main__':
    unittest.main()
