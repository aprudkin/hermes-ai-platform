import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from email.message import EmailMessage
import sys
sys.path.insert(0, os.environ.get('MAIL_EVENTS_CODE_DIR', str(Path(__file__).resolve().parents[1]/'tools/mail_event_discovery')))
from mail_event_discovery_test import BodyIMAP

SPEC = importlib.util.find_spec('mail_events')
if SPEC:
    import mail_events as m
else:
    m = None

class MailEventsTests(unittest.TestCase):
    def test_mime_keeps_plain_html_and_inline_calendar_privately(self):
        self.assertIsNotNone(m, 'collector/extractor not implemented')
        msg = EmailMessage()
        msg['Subject'] = 'Встреча в 19:00'
        msg['Message-ID'] = '<one@example.org>'
        msg.set_content('Plain event 19:00')
        msg.add_alternative('<html><script>evil()</script><body>HTML event <b>20:00</b><img src="https://tracker.invalid/pixel"></body></html>', subtype='html')
        ics = 'BEGIN:VCALENDAR\r\nMETHOD:CANCEL\r\nBEGIN:VEVENT\r\nUID:one\r\nSEQUENCE:3\r\nDTSTART;TZID=Europe/Moscow:20261104T190000\r\nRRULE:FREQ=WEEKLY;COUNT=3\r\nSTATUS:CANCELLED\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n'
        msg.add_attachment(ics.encode(), maintype='text', subtype='calendar', filename='../../invite.ics', disposition='inline')
        with tempfile.TemporaryDirectory() as td:
            rec = m.extract_message(msg.as_bytes(), Path(td)/'message')
            text = Path(rec['text_path']).read_text()
            self.assertIn('Plain event 19:00', text)
            self.assertIn('HTML event', text)
            self.assertNotIn('evil()', text)
            self.assertEqual(rec['subject'], 'Встреча в 19:00')
            att = rec['attachments'][0]
            self.assertEqual(att['status'], 'calendar_preserved_unexpanded')
            self.assertIn('RRULE:FREQ=WEEKLY;COUNT=3', Path(att['text_path']).read_text())
            self.assertTrue(Path(att['path']).is_relative_to(Path(td)/'message'))
            self.assertEqual(Path(att['path']).stat().st_mode & 0o777, 0o600)
            self.assertEqual((Path(td)/'message').stat().st_mode & 0o777, 0o700)
            self.assertEqual(Path(rec['raw_path']).read_bytes(), msg.as_bytes())

    def test_documents_extract_offline_and_report_visual_or_unsupported_gaps(self):
        import io
        import zipfile
        msg = EmailMessage()
        msg.set_content('Documents')
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>DOCX meeting 21:30</w:t></w:r></w:p></w:body></w:document>')
        msg.add_attachment(buf.getvalue(), maintype='application', subtype='vnd.openxmlformats-officedocument.wordprocessingml.document', filename='event.docx')
        msg.add_attachment(b'not executed', maintype='application', subtype='zip', filename='macro.zip')
        msg.add_attachment(b'not an image', maintype='image', subtype='png', filename='poster.png')
        with tempfile.TemporaryDirectory() as td:
            rec = m.extract_message(msg.as_bytes(), Path(td)/'message')
            atts = {a['name']: a for a in rec['attachments']}
            self.assertIn('21:30', Path(atts['event.docx']['text_path']).read_text())
            self.assertEqual(atts['macro.zip']['status'], 'unsupported_archive')
            self.assertEqual(atts['poster.png']['status'], 'needs_visual_review')

    def test_dedup_preserves_source_refs_but_never_merges_conflicting_bodies(self):
        self.assertTrue(hasattr(m, 'store_message'), 'safe dedup store missing')
        a = EmailMessage()
        a['Message-ID'] = '<same@example.org>'
        a['Subject'] = 'Original'
        a.set_content('Event at 18:00')
        b = EmailMessage()
        b['Message-ID'] = '<same@example.org>'
        b['Subject'] = 'Original'
        b.set_content('CANCELLED event')
        with tempfile.TemporaryDirectory() as td:
            index = {'messages': []}
            m.store_message(a.as_bytes(), {'folder': 'INBOX', 'uid': '1', 'uidvalidity': '42'}, Path(td), index)
            m.store_message(a.as_bytes(), {'folder': 'Archive', 'uid': '2', 'uidvalidity': '43'}, Path(td), index)
            m.store_message(b.as_bytes(), {'folder': 'Trash', 'uid': '3', 'uidvalidity': '44'}, Path(td), index)
            self.assertEqual(len(index['messages']), 2)
            self.assertEqual(len(index['messages'][0]['source_refs']), 2)
            self.assertEqual(len(index['messages'][1]['source_refs']), 1)
            self.assertTrue(all(Path(s['raw_path']).exists() for x in index['messages'] for s in x['source_refs']))
            self.assertTrue(index['messages'][1]['message_id_collision'])

    def test_collection_uses_all_folders_peek_and_exact_internaldate_window(self):
        from datetime import datetime, timezone
        self.assertTrue(hasattr(m, 'collect'), 'read-only collector missing')
        start = datetime.fromisoformat('2026-10-20T14:58:46.730087+00:00')
        end = datetime.fromisoformat('2026-11-03T14:58:46.730087+00:00')
        raw = b'Message-ID: <live-fixture@example.org>\r\nSubject: Example\r\n\r\nBody at 18:00\r\n'
        class FakeIMAP(BodyIMAP):
            def __init__(self):
                super().__init__()
                self.folder = None
                self.calls = []
            def list(self):
                return 'OK', [b'(\\HasNoChildren) "|" "INBOX"', b'(\\HasNoChildren) "|" "Trash"']
            def select(self, folder, readonly=False):
                assert readonly is True
                self.folder = folder.strip('"')
                self.calls.append(('select', self.folder, readonly))
                return 'OK', [b'4' if self.folder == 'INBOX' else b'0']
            def response(self, field):
                assert field == 'UIDVALIDITY'
                return 'UIDVALIDITY', [b'12345']
            def uid(self, command, *args):
                self.calls.append((command, args))
                if command == 'SEARCH':
                    assert args == (None, 'SINCE', '19-Oct-2026')
                    return 'OK', [b'1 2 3 4' if self.folder == 'INBOX' else b'']
                assert command == 'FETCH'
                uid, fields = args
                dates = {'1': '20-Oct-2026 14:58:46 +0000', '2': '20-Oct-2026 14:58:47 +0000', '3': '03-Nov-2026 14:58:46 +0000', '4': '03-Nov-2026 14:58:47 +0000'}
                if 'INTERNALDATE' in fields:
                    return 'OK', [f'1 (UID {uid} INTERNALDATE "{dates[uid]}" FLAGS (\\Seen))'.encode()]
                return super().uid(command, *args)
        fake = FakeIMAP()
        with tempfile.TemporaryDirectory() as td:
            coverage, index = m.collect(fake, Path(td), start, end)
            self.assertTrue(coverage['complete'])
            self.assertEqual(coverage['totals']['candidate_refs'], 4)
            self.assertEqual(coverage['totals']['in_window_refs'], 2)
            self.assertEqual(coverage['totals']['collected_refs'], 2)
            self.assertEqual(coverage['totals']['unique_messages'], 2)
            self.assertEqual(coverage['folders'][0]['in_window_uids'], ['2', '3'])
            self.assertEqual(coverage['folders'][0]['excluded_uids'], ['1', '4'])
            self.assertEqual(coverage['folders'][1]['candidate_uids'], [])
            self.assertEqual(coverage['folders'][0]['uidvalidity'], '12345')
            self.assertEqual(len(index['messages'][0]['source_refs']), 1)
            self.assertTrue(Path(td, 'coverage.json').exists())
            self.assertTrue(Path(td, 'index.json').exists())
            self.assertEqual(len([x for x in fake.calls if x[0] == 'select']), 2)

    def test_octet_stream_html_receipt_is_extracted_into_readable_without_execution(self):
        msg = EmailMessage()
        msg.set_content('Your receipt attached')
        msg.add_attachment(b'<html><head><script>DO_NOT_EXECUTE</script></head><body>Concert receipt 23 December 19:00<img src="https://tracking.invalid/a"></body></html>', maintype='application', subtype='octet-stream', filename='receipt.html')
        with tempfile.TemporaryDirectory() as td:
            rec = m.extract_message(msg.as_bytes(), Path(td)/'message')
            att = rec['attachments'][0]
            self.assertEqual(att['status'], 'text_extracted')
            self.assertIn('23 December 19:00', Path(att['text_path']).read_text())
            readable = Path(rec['text_path']).read_text()
            self.assertIn('23 December 19:00', readable)
            self.assertIn('receipt.html', readable)
            self.assertNotIn('DO_NOT_EXECUTE', readable)

    def test_offline_reextract_preserves_coverage_and_source_identity(self):
        self.assertTrue(hasattr(m, 'reextract'), 'offline re-extraction missing')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            msg = EmailMessage()
            msg['Message-ID'] = '<offline@example.org>'
            msg.set_content('Offline event 19:00')
            index = {'messages': []}
            rec = m.store_message(msg.as_bytes(), {'folder': 'INBOX', 'uid': '7', 'uidvalidity': '42'}, root, index)
            identity = {k: rec[k] for k in ('key', 'content_sha256', 'source_refs')}
            m.save_json(root/'index.json', index)
            m.save_json(root/'coverage.json', {'complete': True, 'totals': {'collected_refs': 1}, 'folders': [{'name': 'INBOX', 'collected_uids': ['7']}]})
            Path(rec['text_path']).write_text('stale extraction')
            output = root.parent/(root.name+'-reextract')
            self.addCleanup(lambda: __import__('shutil').rmtree(output, ignore_errors=True))
            coverage, refreshed = m.reextract(root, output)
            self.assertTrue(coverage['complete'])
            self.assertEqual(coverage['totals']['collected_refs'], 1)
            self.assertEqual(coverage['folders'][0]['collected_uids'], ['7'])
            self.assertEqual({k: refreshed['messages'][0][k] for k in identity}, identity)
            self.assertIn('Offline event 19:00', Path(refreshed['messages'][0]['text_path']).read_text())
            self.assertEqual(Path(rec['text_path']).read_text(), 'stale extraction')
            import subprocess
            import sys
            cli_output = output.parent/(output.name+'-cli')
            self.addCleanup(lambda: __import__('shutil').rmtree(cli_output, ignore_errors=True))
            command = subprocess.run([sys.executable, str(Path(m.__file__)), 'reextract', '--input', str(root), '--output', str(cli_output)], capture_output=True, text=True)
            self.assertEqual(command.returncode, 0, command.stderr)
            self.assertIn('Offline event 19:00', Path(json.loads((cli_output/'index.json').read_text())['messages'][0]['text_path']).read_text())
            self.assertEqual(coverage['totals']['attachments'], 0)

if __name__ == '__main__':
    unittest.main()
