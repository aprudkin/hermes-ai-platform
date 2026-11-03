"""End-to-end confirmation handling through the deterministic polling path."""
import json
import os
import sqlite3
from contextlib import closing
import tempfile
import unittest
from types import SimpleNamespace as NS
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from test_cash_ledger_monitor import load_module


class ConfirmationMonitorTests(unittest.TestCase):
    def run_case(self, home, approval, *, sender='810000002', target='51', quote=None, operator=False, finance=False, native=False):
        m = load_module()
        report = '[Fixture Reporter|810000003]\nКасса Fixture\n03.10.2026\nClient Hr/137\nTotal: 137\nМодели: 83\nАгентских: 54\nОператор Анна: 11'
        if operator:
            report = '[Fixture Reporter|810000003]\nМодель Fixture\nОпер Анна\n03.10.2026 + 11'
            (home/'format-guidance.json').write_text(json.dumps({'enabled': True, 'after_source_row_id': 0, 'guidance_enabled': False}))
        if finance:
            report = '[Fixture Reporter|810000003]\nФинмониторинг\nМодель: Fixture\nПериод: 01.10.2026 — 03.10.2026\n100+37=137'
        if finance == 'unknown_period':
            report = report.replace('Период: 01.10.2026 — 03.10.2026','Период: с 28–1')
        if quote == 'source':
            quote = report.split('\n',1)[1]
        body = f'[{sender}|{sender}]\n{approval}'
        if quote is not None:
            body = f'[Replying to: "{quote}"]\n\n' + body
        with closing(sqlite3.connect(home/'source.db')) as db:
            db.executescript('''CREATE TABLE sessions(id INTEGER,chat_id TEXT);
                CREATE TABLE messages(id INTEGER,session_id INTEGER,role TEXT,active INTEGER,
                content TEXT,timestamp REAL,platform_message_id TEXT,reply_to_message_id TEXT,reply_to_chat_id TEXT,sender_id TEXT,sender_is_bot INTEGER);''')
            db.execute("INSERT INTO sessions VALUES(1,'fixture-chat')")
            db.executemany("INSERT INTO messages VALUES(?,1,'user',1,?,1791252477,?,?,?,?,?)",
                           [(1,report,'51',None,None,'810000003',0), (3,body,'59',target,'fixture-chat',sender,0)])
            if native:
                db.execute('UPDATE messages SET sender_id=NULL,sender_is_bot=NULL,reply_to_message_id=NULL,reply_to_chat_id=NULL')
            db.commit()
        if native:
            from cash_native_input import capture
            msg = NS(chat=NS(id='fixture-chat'), message_id='59',
                     from_user=NS(id=sender,is_bot=False), text=approval, caption=None,
                     date=datetime.fromtimestamp(1791252477,timezone.utc),quote=None,
                     reply_to_message=NS(chat=NS(id='fixture-chat'),message_id=target,
                                         text=report.split('\n',1)[1],caption=None))
            capture(home,'fixture-chat',NS(raw_message=msg))
        ledger = m.Ledger(home/'ledger.db')
        calls, reviews = [], []
        args = dict(source_db=home/'source.db', ledger=ledger, state_path=home/'cash-ledger/cursor.json', guidance_path=home/'format-guidance.json',
                    stats_path=home/'stats.json', chat_id='fixture-chat',
                    reply_sender=lambda mid,text: calls.append((mid,text)), review_sender=reviews.append)
        with patch.dict(os.environ, BABLOMAT_ELENA_ID='810000002'):
            m.run_monitor(**args)
            m.run_monitor(**args)
        return ledger, calls, reviews, report

    def test_explicit_financial_confirmation_closes_exact_native_report_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger, calls, reviews, report = self.run_case(Path(tmp), 'Подтверждаю выплату модели Fixture')
            self.assertEqual([mid for mid,text in calls], ['51','59'])
            self.assertIn('**Закрытие периода:**', calls[-1][1])
            with ledger._connection() as db:
                rows = db.execute('SELECT * FROM period_closures ORDER BY recipient_kind').fetchall()
            self.assertEqual([r['recipient_kind'] for r in rows], ['agency','model'])
            self.assertEqual(rows[0]['report_message_id'], '51')
            self.assertEqual(json.loads(rows[0]['evidence_json'])['confirmation_raw_content'], '[810000002|810000002]\nПодтверждаю выплату модели Fixture')
            self.assertEqual(reviews, [])

    def test_full_quote_without_native_reply_linkage_cannot_authorize_closure(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger, calls, _, _ = self.run_case(Path(tmp), 'Подтверждаю выплату модели Fixture', target=None, quote='source')
            self.assertNotIn('**Закрытие периода:**', calls[-1][1])
            with ledger._connection() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM period_closures').fetchone()[0], 0)

    def test_generic_operator_confirmation_uses_operator_not_model_heading(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger, calls, _, _ = self.run_case(Path(tmp), 'Тут да все верно 🙌', target='51', quote='source', operator=True)
            self.assertIn('Оператор: Анна', calls[-1][1])
            with ledger._connection() as db:
                rows = db.execute('SELECT recipient_kind,recipient_key FROM period_closures').fetchall()
            self.assertEqual([tuple(r) for r in rows], [('operator', 'анна')])

    def test_generic_model_finance_confirmation_uses_explicit_period(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger, calls, _, _ = self.run_case(Path(tmp), 'Да все верно к выдаче', finance=True)
            self.assertIn('Модель: Fixture',calls[-1][1])
            self.assertIn('По: 03.10 (сб)',calls[-1][1])
            self.assertIn('С: 01.10 (чт)',calls[-1][1])
            self.assertEqual(ledger.register_statistics(),{})

    def test_native_sidecar_closes_with_actual_observed_schema_without_reply_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger,calls,_,_=self.run_case(Path(tmp),'Тут да все верно 🙌',operator=True,native=True)
            self.assertIn('**Закрытие периода:**',calls[-1][1])
            with ledger._connection() as db:
                evidence=json.loads(db.execute('SELECT evidence_json FROM period_closures').fetchone()[0])
            self.assertEqual(evidence['native_input']['reply_to_message_id'],'51')
            self.assertEqual(evidence['native_input']['sender_id'],'810000002')

    def test_unknown_financial_period_stays_pending_with_one_shared_question(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger,calls,reviews,_=self.run_case(Path(tmp),'Тут да все верно 🙌',finance='unknown_period')
            with ledger._connection() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM period_closures').fetchone()[0],0)
            self.assertEqual(len(reviews),1)
            self.assertIn('период',reviews[0].casefold())

    def test_retry_after_cursor_failure_reuses_frozen_notice_and_sender_receipts(self):
        from cash_reply_sender import ReplySender
        m=load_module()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,BABLOMAT_ELENA_ID='810000002'):
            home=Path(tmp)
            with closing(sqlite3.connect(home/'source.db')) as db, db:
                db.executescript('''CREATE TABLE sessions(id INTEGER,chat_id TEXT);
                    CREATE TABLE messages(id INTEGER,session_id INTEGER,role TEXT,active INTEGER,
                    content TEXT,timestamp REAL,platform_message_id TEXT,reply_to_message_id TEXT,
                    reply_to_chat_id TEXT,sender_id TEXT,sender_is_bot INTEGER);''')
                db.execute("INSERT INTO sessions VALUES(1,'fixture-chat')")
                db.executemany("INSERT INTO messages VALUES(?,1,'user',1,?,1791252477,?,?,?,?,?)",[
                    (1,'[Reporter|810000003]\nКасса Fixture\n03.10.2026\nClient Hr/137\nTotal: 137\nМодели: 83\nАгентских: 54','51',None,None,'810000003',0),
                    (3,'[Confirmer|810000002]\nПодтверждаю выплату модели Fixture','59','51','fixture-chat','810000002',0)])
            payloads=[]
            def post(payload):
                payloads.append(payload)
                return {'chat':{'id':'fixture-chat'},'message_id':100+len(payloads),
                        'reply_to_message':{'message_id':payload['reply_parameters']['message_id']}}
            sender=ReplySender(home,'fixture-chat',post=post)
            ledger=m.Ledger(home/'ledger.db')
            args=dict(source_db=home/'source.db',ledger=ledger,state_path=home/'cursor.json',
                stats_path=home/'stats.json',chat_id='fixture-chat',reply_sender=sender)
            with patch.object(m,'_atomic_json_write',side_effect=OSError('fixture cursor failure')):
                with self.assertRaises(OSError):
                    m.run_monitor(**args)
            m.run_monitor(**args)
            self.assertEqual([p['reply_parameters']['message_id'] for p in payloads],[51,59])
            self.assertTrue(all(p['reply_parameters']['allow_sending_without_reply'] is False for p in payloads))
            with ledger._connection() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM period_closures').fetchone()[0],2)

    def test_native_reference_disagreeing_with_quote_is_not_a_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger, calls, _, _ = self.run_case(Path(tmp), 'Подтверждаю выплату модели Fixture', quote='Отчёт другой модели')
            with ledger._connection() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM period_closures').fetchone()[0], 0)

    def test_control_approval_unknown_sender_or_unlinked_confirmation_cannot_close(self):
        cases = [('Да, всё верно', '810000002', '51'),
                 ('Да, удали старый отчёт', '810000002', '51'),
                 ('Подтверждаю выплату модели Fixture', '810000009', '51'),
                 ('Подтверждаю выплату модели Fixture', '810000002', None),
                 ('Подтверждаю выплату модели Other', '810000002', '51')]
        for body,sender,target in cases:
            with self.subTest(body=body,sender=sender,target=target), tempfile.TemporaryDirectory() as tmp:
                ledger, calls, reviews, _ = self.run_case(Path(tmp), body, sender=sender, target=target)
                with ledger._connection() as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM period_closures').fetchone()[0], 0)
                self.assertFalse(any('**Закрытие периода:**' in text for _,text in calls))
