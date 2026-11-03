import unittest,tempfile,json,sqlite3
from contextlib import closing
from pathlib import Path
from test_cash_ledger_monitor import load_module

class FinanceTests(unittest.TestCase):
    def test_finance_arithmetic_is_saved_without_creating_cash_revenue(self):
        m=load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger=m.Ledger(Path(tmp)/'ledger.db')
            text='[Sender|1]\nФинмониторинг\nМодель: Fixture Model\nДаты: 1–6 февраля\n110+230+70+190+310+90=1,000\n1000*14%=140\n140-6%=131.6\nПроверяй 🙌'
            notice=ledger.check_finance_message(source_row_id=1,timestamp=1791223000.0,content=text)
            self.assertIn('✅ Арифметика верна',notice)
            self.assertIn('$1,000',notice)
            self.assertIn('$131.60',notice)
            self.assertIn('не прибавлены к выручке',notice)
            self.assertEqual(ledger.register_statistics(),{})
            self.assertEqual(ledger.operator_statistics(),{})
            ledger.check_finance_message(source_row_id=1,timestamp=1791223000.0,content=text)
            with ledger._connection() as c:
                rows=c.execute('SELECT status,checks_json FROM finance_checks').fetchall()
                self.assertEqual(len(rows),1)
                self.assertEqual(rows[0]['status'],'ok')
                self.assertEqual(len(json.loads(rows[0]['checks_json'])),3)

    def test_finance_monitor_replies_to_the_source_and_catches_errors(self):
        m=load_module()
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            with closing(sqlite3.connect(home/'state.db')) as c:
                c.executescript('CREATE TABLE sessions(id INTEGER,chat_id TEXT); CREATE TABLE messages(id INTEGER,session_id INTEGER,role TEXT,active INTEGER,content TEXT,timestamp REAL,platform_message_id TEXT);')
                c.execute("INSERT INTO sessions VALUES(1,'chat')")
                c.execute("INSERT INTO messages VALUES(1,1,'user',1,?,1791223000,'54')",('Финмониторинг\nМодель: Тестовый /Примерб\n100+200+0+0=300\n300*14%=43\n42-6%=39.48',))
                c.commit()
            ledger=m.Ledger(home/'ledger.db')
            calls=[]
            args=dict(source_db=home/'state.db',ledger=ledger,state_path=home/'cursor.json',stats_path=home/'stats.json',chat_id='chat',reply_sender=lambda mid,text:calls.append((mid,text)))
            self.assertEqual(m.run_monitor(**args),'')
            self.assertEqual(len(calls),1)
            self.assertEqual(calls[0][0],'54')
            self.assertIn('⚠️ Ошибка в арифметике',calls[0][1])
            self.assertIn('$42',calls[0][1])
            self.assertEqual(m.run_monitor(**args),'')
            self.assertEqual(len(calls),1)
            self.assertEqual(ledger.statistics()['days'],{})

if __name__=='__main__': unittest.main()
