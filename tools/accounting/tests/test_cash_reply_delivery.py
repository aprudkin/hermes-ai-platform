import unittest
import sqlite3
import tempfile
import subprocess
from pathlib import Path
from contextlib import closing
import importlib.util
import sys
from test_cash_ledger_monitor import load_module


def load_sender():
    spec = importlib.util.spec_from_file_location('cash_reply_sender', Path(__file__).resolve().parents[1]/'scripts'/'cash_reply_sender.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

class ReplyDeliveryTests(unittest.TestCase):
    def test_each_notice_replies_to_its_own_source_once(self):
        m = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            db = home / 'state.db'
            with closing(sqlite3.connect(db)) as c:
                c.executescript('CREATE TABLE sessions(id INTEGER,chat_id TEXT); CREATE TABLE messages(id INTEGER,session_id INTEGER,role TEXT,active INTEGER,content TEXT,timestamp REAL,platform_message_id TEXT);')
                c.execute("INSERT INTO sessions VALUES(1,'chat')")
                for row, day, message_id in [(1,'03.10',39),(2,'04.10',40)]:
                    c.execute('INSERT INTO messages VALUES(?,1,\'user\',1,?,1791100000,?)', (row,f'Касса Fixture\n{day}\nHr/900\nTotal: 900',str(message_id)))
                c.commit()
            calls=[]
            args=dict(source_db=db,ledger=m.Ledger(home/'ledger.db'),state_path=home/'cursor.json',stats_path=home/'stats.json',chat_id='chat',reply_sender=lambda mid,text: calls.append((mid,text)))
            self.assertEqual(m.run_monitor(**args),'')
            self.assertEqual([x[0] for x in calls],['39','40'])
            self.assertTrue(calls[0][1].startswith('**03.10 (сб):**'))
            self.assertEqual(m.run_monitor(**args),'')
            self.assertEqual(len(calls),2)

    def test_sender_requires_exact_reply_and_deduplicates_delivery(self):
        module = load_sender()
        calls=[]
        def post(payload):
            calls.append(payload)
            return {'message_id':45,'chat':{'id':-1008000000001},'reply_to_message':{'message_id':39}}
        with tempfile.TemporaryDirectory() as tmp:
            sender = module.ReplySender(Path(tmp), '-1008000000001', post=post)
            sender('39', '**03.10:**\nBalance $260')
            sender('39', '**03.10:**\nBalance $260')
            self.assertEqual(len(calls),1)
            self.assertEqual(calls[0]['reply_parameters'], {'message_id':39,'allow_sending_without_reply':False})
            self.assertEqual(calls[0]['text'], '<b>03.10:</b>\nBalance $260')
            self.assertEqual(calls[0]['parse_mode'],'HTML')

    def test_scheduled_script_sends_no_standalone_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            with closing(sqlite3.connect(home/'state.db')) as c:
                c.executescript('CREATE TABLE sessions(id INTEGER,chat_id TEXT); CREATE TABLE messages(id INTEGER,session_id INTEGER,role TEXT,active INTEGER,content TEXT,timestamp REAL,platform_message_id TEXT);')
            script=Path(__file__).resolve().parents[1]/'scripts'/'cash_ledger_reply_monitor.py'
            result=subprocess.run([sys.executable,str(script),'--home',str(home)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout,'')

if __name__ == '__main__':
    unittest.main()
