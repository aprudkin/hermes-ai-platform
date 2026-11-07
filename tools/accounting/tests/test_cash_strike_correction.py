import unittest
import tempfile
import sqlite3
import hashlib
from pathlib import Path
from test_cash_reply_delivery import load_sender

class StrikeCorrectionTests(unittest.TestCase):
    def test_new_correction_automatically_strikes_its_old_bot_target(self):
        module=load_sender()
        calls=[]
        old='Old result $700'
        def post(payload):
            return {'chat':{'id':-1008000000001},'message_id':101,
                    'reply_to_message':{'message_id':100}}
        def edit(payload):
            calls.append(payload)
            return {'chat':{'id':-1008000000001},'message_id':100,'text':old,
                    'entities':[{'type':'strikethrough','offset':0,'length':len(old)}]}
        with tempfile.TemporaryDirectory() as tmp:
            sender=module.ReplySender(Path(tmp),'-1008000000001',post=post,edit=edit)
            with sqlite3.connect(sender.path) as c:
                key=hashlib.sha256(f'{sender.chat_id}:99:{old}'.encode()).hexdigest()
                c.execute('INSERT INTO receipts VALUES(?,?,?,?,?)',(key,'sent',99,100,old));c.commit()
            sender('100','**Исправление**\nNew result $1000')
            self.assertEqual(len(calls),2)
            sender('100','**Исправление**\nNew result $1000')
            self.assertEqual(len(calls),2)

    def test_strikes_only_verified_old_bot_notice_and_preserves_receipts(self):
        module=load_sender()
        calls=[]
        old='Old result $700'
        def edit(payload):
            calls.append(payload)
            return {'chat':{'id':-1008000000001},'message_id':100,'text':old,
                    'entities':[{'type':'strikethrough','offset':0,'length':len(old.encode('utf-16-le'))//2}]}
        with tempfile.TemporaryDirectory() as tmp:
            sender=module.ReplySender(Path(tmp),'-1008000000001',edit=edit)
            with sqlite3.connect(sender.path) as c:
                for source, sent, text in [(99,100,old),(100,101,'**Исправление**\nNew result $1000')]:
                    key=hashlib.sha256(f'{sender.chat_id}:{source}:{text}'.encode()).hexdigest()
                    c.execute('INSERT INTO receipts VALUES(?,?,?,?,?)',(key,'sent',source,sent,text))
                c.commit()
            sender.strike_message(100,101)
            self.assertEqual(calls[0]['text'],'<s>Old result $700</s>')
            self.assertEqual(calls[0]['message_id'],100)
            with sqlite3.connect(sender.path) as c:
                self.assertEqual(c.execute('SELECT text FROM receipts WHERE sent_message_id=100').fetchone()[0],old)
                self.assertEqual(c.execute('SELECT status FROM superseded_notices').fetchone()[0],'struck')
            sender.strike_message(100,101)
            self.assertEqual(len(calls),2)
            with self.assertRaises(ValueError): sender.strike_message(99,101)
