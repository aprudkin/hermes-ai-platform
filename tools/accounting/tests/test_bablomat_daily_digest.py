import unittest
import tempfile
import sqlite3
import hashlib
import importlib.util
from pathlib import Path
from contextlib import closing
from test_cash_reply_delivery import load_sender

PATH=Path(__file__).resolve().parents[1]/'scripts'/'bablomat_daily_digest.py'

class DigestTests(unittest.TestCase):
    def load(self):
        spec=importlib.util.spec_from_file_location('digest',PATH)
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

    def test_new_reply_records_actual_destination_and_delivery_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            sender=load_sender().ReplySender(Path(tmp),'-1008000000001',post=lambda payload:{
                'chat':{'id':-1008000000001},'message_id':100,'date':1000000,
                'reply_to_message':{'message_id':99}})
            sender('99','ok')
            sender('99','ok')
            with closing(sqlite3.connect(sender.path)) as c:
                rows=c.execute('SELECT chat_id,source_message_id,sent_message_id,sent_at FROM delivery_metadata').fetchall()
            self.assertEqual(rows,[('-1008000000001',99,100,1000000.0)])

    def test_exact_window_chat_and_reply_anchors_include_late_correction(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);(home/'cash-ledger').mkdir()
            with closing(sqlite3.connect(home/'state.db')) as c, c:
                c.executescript('CREATE TABLE sessions(id TEXT,chat_id TEXT); CREATE TABLE messages(id INTEGER,session_id TEXT,role TEXT,content TEXT,timestamp REAL,platform_message_id TEXT,active INTEGER);')
                c.executemany('INSERT INTO sessions VALUES(?,?)',[('cash','-1008000000001'),('dm','810000001')])
                c.executemany('INSERT INTO messages VALUES(?,?,\'user\',?,?,?,1)',[(1,'cash','old original',1000000-90000,'77'),(2,'cash','new original unchanged',1000000-100,'99'),(3,'dm','private excluded',1000000-100,'99')])
            with closing(sqlite3.connect(home/'cash-ledger/reply-deliveries.db')) as c, c:
                c.executescript('CREATE TABLE receipts(key TEXT PRIMARY KEY,status TEXT,source_message_id INTEGER,sent_message_id INTEGER,text TEXT); CREATE TABLE delivery_metadata(key TEXT PRIMARY KEY,chat_id TEXT,source_message_id INTEGER,sent_message_id INTEGER,sent_at REAL); CREATE TABLE superseded_notices(chat_id TEXT,old_message_id INTEGER,correction_message_id INTEGER,original_text TEXT,status TEXT);')
                for source,sent,text,time in [(77,88,'late answer',999950),(99,100,'warning',999970),(100,101,'correction',999980),(77,76,'old reply',800000)]:
                    key=hashlib.sha256(f'-1008000000001:{source}:{text}'.encode()).hexdigest()
                    c.execute('INSERT INTO receipts VALUES(?,\'sent\',?,?,?)',(key,source,sent,text))
                    c.execute('INSERT INTO delivery_metadata VALUES(?,?,?,?,?)',(key,'-1008000000001',source,sent,time))
                c.execute('INSERT INTO superseded_notices VALUES(?,?,?,?,?)',('-1008000000001',100,101,'warning','struck'))
                c.execute('INSERT INTO receipts VALUES(?,\'sent\',?,?,?)',('not-this-chat',99,123,'wrong chat'))
            d=self.load().collect_digest(home,end=1000000)
            self.assertEqual([r['message_id'] for r in d['messages']],['99'])
            self.assertEqual([r['message_id'] for r in d['answers']],[88,100,101])
            self.assertEqual(d['answers'][0]['source_text'],'old original')
            self.assertEqual(d['answers'][2]['source_text'],'warning')
            self.assertTrue(d['answers'][1]['struck'])
            self.assertEqual(d['messages'][0]['text'],'new original unchanged')
            with closing(sqlite3.connect(home/'cash-ledger/reply-deliveries.db')) as c, c:
                c.execute('DELETE FROM delivery_metadata WHERE sent_message_id=101')
            legacy=self.load().collect_digest(home,end=1000000)
            self.assertIn(101,[r['message_id'] for r in legacy['answers']])
            correction=next(r for r in legacy['answers'] if r['message_id']==101)
            self.assertIsNone(correction['sent_at'])
            self.assertEqual(correction['source_text'],'warning')
