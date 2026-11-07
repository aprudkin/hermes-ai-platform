"""Synthetic/offline regressions. No mailbox, credentials or private fixtures."""
from datetime import datetime
from email.message import EmailMessage
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, os.environ.get('MAIL_EVENTS_CODE_DIR', str(Path(__file__).resolve().parents[1]/'tools/mail_event_discovery')))
import mail_events as m

START = datetime.fromisoformat('2026-10-20T12:00:00+00:00')
END = datetime.fromisoformat('2026-11-03T12:00:00+00:00')


class FailedIMAP:
    def __init__(self, stage):
        self.stage = stage
        self.calls = []
    def list(self):
        self.calls.append('LIST')
        return ('NO', []) if self.stage == 'LIST' else ('OK', [b'() "/" "INBOX"'])
    def select(self, folder, readonly=False):
        assert readonly
        self.calls.append('SELECT')
        return ('NO', []) if self.stage == 'SELECT' else ('OK', [b'1'])
    def response(self, field):
        return 'UIDVALIDITY', [b'42']
    def uid(self, command, *args):
        self.calls.append(command)
        if command == 'SEARCH':
            return 'OK', [b'1']
        return 'NO', []


class BodyIMAP(FailedIMAP):
    """Speaks selected sections only; forbidden fetches raise assertions."""
    structure = b'(("TEXT" "PLAIN" ("CHARSET" "UTF-8") NIL NIL "7BIT" 24 1)("APPLICATION" "PDF" ("NAME" "ticket.pdf") NIL NIL "BASE64" 999 NIL ("ATTACHMENT" ("FILENAME" "ticket.pdf"))) "MIXED")'
    header = b'Message-ID: <body@example.invalid>\r\nSubject: Synthetic\r\n\r\n'
    mime = b'Content-Type: text/plain; charset=utf-8\r\nContent-Transfer-Encoding: 7bit\r\n\r\n'
    body = b'Meeting 21 Nov at 21:30\r\n'
    forbidden_sections = {'2'}
    def __init__(self, stage=None):
        super().__init__(stage)
        self.fetches = []
    def uid(self, command, *args):
        import re
        if command == 'SEARCH':
            return ('NO', []) if self.stage == 'SEARCH' else ('OK', [b'1'])
        uid, fields = args
        self.fetches.append(fields)
        assert 'BODY.PEEK[]' not in fields, 'full MIME downloads excluded PDFs'
        assert not any(f'BODY.PEEK[{s}]' in fields or f'BODY.PEEK[{s}.MIME]' in fields for s in self.forbidden_sections), 'excluded section requested'
        if self.stage == 'FETCH':
            return 'NO', []
        if 'INTERNALDATE' in fields:
            return 'OK', [f'1 (UID {uid} INTERNALDATE "21-Oct-2026 13:00:00 +0000" FLAGS (\\Seen))'.encode()]
        if 'BODYSTRUCTURE' in fields:
            return 'OK', [f'1 (UID {uid} BODYSTRUCTURE '.encode() + self.structure + b')']
        match = re.search(r'BODY.PEEK\[([^]]+)\]<0\.(\d+)>', fields)
        assert match, fields
        section, limit = match.group(1), int(match.group(2))
        values = {'HEADER': self.header, '1.MIME': self.mime, '1': self.body}
        values.update(getattr(self, 'values', {}))
        payload = values[section][:limit]
        if self.stage == section:
            return 'NO', []
        return 'OK', [(f'1 (UID {uid} BODY[{section}]<0> {{{len(payload)}}}'.encode(), payload), b' FLAGS (\\Seen))']


class DiscoveryTests(unittest.TestCase):
    def test_body_only_fetches_exact_sections_never_pdf_or_full_mime(self):
        fake = BodyIMAP()
        with tempfile.TemporaryDirectory() as td:
            cov, idx = m.collect(fake, td, START, END)
            self.assertTrue(cov['complete'], cov)
            self.assertTrue(cov['transport_complete'])
            self.assertTrue(cov['extraction_complete'])
            rec = idx['messages'][0]
            self.assertIn('21:30', Path(rec['text_path']).read_text())
            self.assertEqual(rec['hash_scope'], 'selected_sections_only')
            self.assertNotIn('raw_sha256', rec)
            self.assertEqual(rec['excluded_parts'][0]['section'], '2')
            ref = rec['source_refs'][0]
            self.assertEqual(ref['flags_before'], ref['flags_after'])
            self.assertEqual(Path(ref['sections']['1']['path']).read_bytes(), fake.body)
            self.assertEqual(Path(ref['sections']['HEADER']['path']).read_bytes(), fake.header)
            self.assertFalse(list(Path(td).rglob('*.eml')))
            self.assertFalse(list(Path(td).rglob('*.pdf')))
            for p in Path(td).rglob('*'):
                self.assertEqual(p.stat().st_mode & 0o777, 0o700 if p.is_dir() else 0o600)

    def test_multipart_header_only_fetch_keeps_real_header_defects(self):
        for malformed in (False, True):
            with self.subTest(malformed=malformed), tempfile.TemporaryDirectory() as td:
                fake = BodyIMAP()
                fake.header = (b'Broken header without colon\r\n\r\n' if malformed else
                    b'Message-ID: <multipart@example.invalid>\r\nSubject: Synthetic\r\n'
                    b'Content-Type: multipart/mixed; boundary="fixture"\r\n\r\n')
                cov, idx = m.collect(fake, td, START, END)
                self.assertEqual(cov['complete'], not malformed, cov['body_mime_defects'])
                self.assertEqual(cov['extraction_complete'], not malformed)
                self.assertIn('21:30', Path(idx['messages'][0]['text_path']).read_text())
                if malformed:
                    self.assertIn('MissingHeaderBodySeparatorDefect', idx['messages'][0]['defects'])
                else:
                    self.assertEqual(idx['messages'][0]['defects'], [])

    def test_declared_pdf_filename_variants_are_never_selected(self):
        from body_only import parse_structure, parts
        for params in (b'("NAME" "ticket.pdf")', b'("NAME*" "utf-8\'\'ticket%2Epdf")', b'("NAME*0*" "utf-8\'\'ticket%2E" "NAME*1*" "pdf")'):
            with self.subTest(params=params):
                tree, _ = parse_structure([b'1 (UID 1 BODYSTRUCTURE ("TEXT" "PLAIN" '+params+b' NIL NIL "7BIT" 24 1))'])
                part = list(parts(tree))[0]
                self.assertFalse(part['selected'])
                self.assertEqual(part['reason'], 'pdf_excluded')

    def test_missing_text_line_count_and_mime_header_are_not_complete(self):
        for missing in ('structure', 'mime'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as td:
                fake = BodyIMAP()
                if missing == 'structure':
                    fake.structure = b'("TEXT" "PLAIN" NIL NIL NIL "7BIT" 24)'
                else:
                    fake.mime = b'\r\n'
                cov, _ = m.collect(fake, td, START, END)
                self.assertFalse(cov['complete'])

    def test_nested_text_calendar_receipt_and_literal_bodystructure(self):
        from body_only import parse_structure, parts
        fake = BodyIMAP()
        fake.structure = b'((("TEXT" "PLAIN" NIL NIL NIL "7BIT" 24 1)("TEXT" "HTML" NIL NIL NIL "BASE64" 80 1) "ALTERNATIVE")("TEXT" "CALENDAR" NIL NIL NIL "7BIT" 100 3)("APPLICATION" "OCTET-STREAM" ("NAME" "receipt.html") NIL NIL "7BIT" 80)("APPLICATION" "PDF" NIL NIL NIL "BASE64" 999) "MIXED")'
        fake.forbidden_sections = {'4'}
        import base64
        fake.values = {
            '1.1.MIME': fake.mime, '1.1': fake.body,
            '1.2.MIME': b'Content-Type: text/html\r\nContent-Transfer-Encoding: base64\r\n\r\n',
            '1.2': base64.b64encode(b'<p>HTML 20:30</p><script>BAD_SCRIPT</script>'),
            '2.MIME': b'Content-Type: text/calendar\r\n\r\n', '2': b'BEGIN:VCALENDAR\r\nMETHOD:CANCEL\r\nUID:synthetic\r\nSEQUENCE:3\r\nEND:VCALENDAR\r\n',
            '3.MIME': b'Content-Type: application/octet-stream\r\nContent-Disposition: attachment; filename="receipt.html"\r\n\r\n',
            '3': b'<p>Receipt 19:30</p><script>BAD_SCRIPT</script>'}
        with tempfile.TemporaryDirectory() as td:
            cov, idx = m.collect(fake, td, START, END)
            self.assertTrue(cov['complete'], cov)
            text = Path(idx['messages'][0]['text_path']).read_text()
            for expected in ('21:30', '20:30', '19:30', 'METHOD:CANCEL', 'SEQUENCE:3'):
                self.assertIn(expected, text)
            self.assertNotIn('BAD_SCRIPT', text)
            self.assertEqual([p['section'] for p in idx['messages'][0]['body_parts']], ['1.1', '1.2', '2', '3'])
        tree, _ = parse_structure([(b'1 (UID 1 BODYSTRUCTURE ("TEXT" "PLAIN" ("NAME" {8}', b'note.txt'), b') NIL NIL "7BIT" 24 1))'])
        self.assertEqual(list(parts(tree))[0]['names'], ['note.txt'])

    def test_selected_sources_never_merge_unfetched_attachment_equality(self):
        class Copies(BodyIMAP):
            def uid(self, command, *args):
                if command == 'SEARCH':
                    return 'OK', [b'1 2']
                return super().uid(command, *args)
        with tempfile.TemporaryDirectory() as td:
            cov, idx = m.collect(Copies(), td, START, END)
            self.assertTrue(cov['complete'])
            self.assertEqual(cov['totals']['collected_refs'], 2)
            self.assertEqual(len(idx['messages']), 2)
            self.assertTrue(all(r['hash_scope'] == 'selected_sections_only' for r in idx['messages']))
            self.assertTrue(all(r['message_id_collision'] for r in idx['messages']))
            self.assertEqual([r['source_refs'][0]['uid'] for r in idx['messages']], ['1', '2'])

    def test_bad_list_entry_is_reported_without_losing_other_folders(self):
        class BadList(BodyIMAP):
            def list(self):
                return 'OK', [b'() "/" "bad\xff"', b'unsupported-list-entry', b'() "/" "INBOX"']
        with tempfile.TemporaryDirectory() as td:
            cov, idx = m.collect(BadList(), td, START, END)
            self.assertFalse(cov['complete'])
            self.assertEqual(len(cov['errors']), 2)
            self.assertEqual(cov['totals']['collected_refs'], 1)
            self.assertEqual(len(idx['messages']), 1)

    def test_selected_section_response_validation_and_bounded_fetch(self):
        class Corrupt(BodyIMAP):
            def uid(self, command, *args):
                typ, data = super().uid(command, *args)
                if command == 'FETCH' and 'PEEK[1]' in args[1]:
                    if self.fault == 'uid':
                        data[0] = (data[0][0].replace(b'UID 1', b'UID 999'), data[0][1])
                    elif self.fault == 'section':
                        data[0] = (data[0][0].replace(b'BODY[1]', b'BODY[9]'), data[0][1])
                    elif self.fault == 'missing':
                        data = [b')']
                    else:
                        from body_only import MAX_TEXT
                        data = [(f'1 (UID 1 BODY[1]<0> {{{MAX_TEXT+1}}}'.encode(), b'x'*(MAX_TEXT+1)), b')']
                return typ, data
        for fault in ('uid', 'section', 'missing', 'oversize'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as td:
                fake = Corrupt(); fake.fault = fault
                cov, idx = m.collect(fake, td, START, END)
                self.assertFalse(cov['complete'])
                self.assertEqual(cov['totals']['failed_refs'], 1)
                self.assertEqual(idx['messages'], [])

    def test_untrusted_body_cannot_spoof_fetch_uid_or_flags(self):
        class TrailingUID(BodyIMAP):
            body = b'UID 999 FLAGS (\\Deleted) Meeting 21:30\r\n'
            def uid(self, command, *args):
                typ, data = super().uid(command, *args)
                if command == 'FETCH' and 'PEEK[1]' in args[1]:
                    data[0] = (data[0][0].replace(b'UID 1 ', b''), data[0][1])
                    data[-1] = b' UID 1 FLAGS (\\Seen))'
                return typ, data
        with tempfile.TemporaryDirectory() as td:
            cov, idx = m.collect(TrailingUID(), td, START, END)
            self.assertTrue(cov['complete'], cov)
            self.assertEqual(idx['messages'][0]['source_refs'][0]['flags_after'], ['\\Seen'])

    def test_selected_text_decode_uncertainty_is_explicit_partial(self):
        for mime in (b'Content-Type: text/plain; charset=x-unknown\r\n\r\n',
                     b'Content-Type: text/plain\r\nContent-Transfer-Encoding: x-secret\r\n\r\n'):
            with self.subTest(mime=mime), tempfile.TemporaryDirectory() as td:
                fake = BodyIMAP()
                fake.mime = mime
                cov, idx = m.collect(fake, td, START, END)
                self.assertFalse(cov['complete'])
                self.assertTrue(cov['transport_complete'])
                self.assertTrue(cov['body_coverage_gaps'])
                self.assertIn('21:30', Path(idx['messages'][0]['text_path']).read_text())

    def test_transport_failures_are_checkpointed_partial_without_content_in_errors(self):
        for stage in ('LIST', 'SELECT', 'SEARCH', 'FETCH', 'HEADER', '1.MIME', '1'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as td:
                cov, idx = m.collect(BodyIMAP(stage), td, START, END)
                self.assertFalse(cov['complete'])
                self.assertFalse(cov['transport_complete'])
                self.assertEqual(cov, json.loads(Path(td, 'coverage.json').read_text()))
                self.assertEqual(len(idx['messages']), 0)
                errors = cov['errors'] + [e for f in cov['folders'] for e in f['errors']]
                self.assertTrue(errors)
                self.assertTrue(all('error_type' in e for e in errors))

    def test_enriched_and_oversize_text_have_separate_extraction_gaps(self):
        from body_only import MAX_TEXT
        for structure, reason in ((b'("TEXT" "ENRICHED" NIL NIL NIL "7BIT" 24 1)', 'unsupported_text_format'),
                                  (f'("TEXT" "PLAIN" NIL NIL NIL "7BIT" {MAX_TEXT+1} 1)'.encode(), 'text_size_limit')):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as td:
                fake = BodyIMAP(); fake.structure = structure
                fake.mime = b'Content-Type: text/enriched\r\n\r\n' if reason == 'unsupported_text_format' else fake.mime
                cov, idx = m.collect(fake, td, START, END)
                self.assertTrue(cov['transport_complete'], cov)
                self.assertFalse(cov['extraction_complete'])
                self.assertFalse(cov['complete'])
                self.assertIn(reason, [g['reason'] for g in cov['body_coverage_gaps']])
                if reason == 'unsupported_text_format':
                    self.assertIn('21:30', Path(idx['messages'][0]['text_path']).read_text())
                else:
                    self.assertFalse(any('PEEK[1]' in f for f in fake.fetches))

    def test_malformed_bodystructure_fails_visibly(self):
        for structure in (b'()', b'(unknown)', b'(("TEXT" "PLAIN" NIL NIL NIL "7BIT" 24 1))', b'("TEXT" "PLAIN" NIL NIL NIL "7BIT" -1 1)', b'("TEXT"'):
            with self.subTest(structure=structure), tempfile.TemporaryDirectory() as td:
                fake = BodyIMAP(); fake.structure = structure
                cov, idx = m.collect(fake, td, START, END)
                self.assertFalse(cov['complete'])
                self.assertTrue(cov['folders'][0]['errors'])
                self.assertEqual(idx['messages'], [])

    def test_offline_reextract_to_new_output_leaves_historical_corpus_untouched(self):
        msg = EmailMessage()
        msg['Message-ID'] = '<offline@example.invalid>'
        msg.set_content('Meeting 21:30', subtype='enriched')
        msg.add_attachment(b'PDF_SENTINEL', maintype='application', subtype='pdf', filename='ticket.pdf')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)/'old'
            index = {'messages': []}
            m.store_message(msg.as_bytes(), {'folder': 'INBOX', 'uid': '1', 'uidvalidity': '42'}, root, index)
            m.save_json(root/'index.json', index)
            m.save_json(root/'coverage.json', {'complete': True, 'totals': {'collected_refs': 1}})
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            out = Path(td)/'new'
            cov, idx = m.reextract(root, out)
            self.assertEqual(before, {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()})
            self.assertFalse(cov['complete'])
            self.assertTrue(cov['transport_complete'])
            self.assertTrue(cov['body_coverage_gaps'])
            self.assertIn('21:30', Path(idx['messages'][0]['text_path']).read_text())
            self.assertFalse(list(out.rglob('*.pdf')))
            self.assertEqual(idx['messages'][0]['attachments'][0]['status'], 'skipped_by_user')
            with self.assertRaises(FileExistsError):
                m.reextract(root, out)
            with self.assertRaises(ValueError):
                m.reextract(root, root/'nested')

    def test_cli_collect_secure_environment_and_partial_exit_status(self):
        from unittest.mock import patch
        import contextlib
        import io
        import ssl
        for partial in (False, True):
            with self.subTest(partial=partial), tempfile.TemporaryDirectory() as td:
                fake = BodyIMAP()
                fake.login = lambda account, password: self.assertEqual((account, password), ('person@example.invalid', 'synthetic-${literal}'))
                fake.logout = lambda: ('BYE', [])
                if partial:
                    fake.structure = b'("TEXT" "ENRICHED" NIL NIL NIL "7BIT" 24 1)'
                    fake.mime = b'Content-Type: text/enriched\r\n\r\n'
                def factory(host, port, **kwargs):
                    self.assertEqual((host, port), ('imap.example.invalid', 993))
                    self.assertEqual(kwargs['ssl_context'].verify_mode, ssl.CERT_REQUIRED)
                    self.assertTrue(kwargs['ssl_context'].check_hostname)
                    return fake
                stdout = io.StringIO()
                with patch.dict('os.environ', {'MAIL_EVENTS_IMAP_PASSWORD': 'synthetic-${literal}'}, clear=True), contextlib.redirect_stdout(stdout):
                    result = m.main(['collect', '--host', 'imap.example.invalid', '--account', 'person@example.invalid', '--start', START.isoformat(), '--end', END.isoformat(), '--output', str(Path(td)/'run')], imap_factory=factory)
                self.assertEqual(result, 1 if partial else 0)
                report = json.loads(stdout.getvalue())
                self.assertEqual(report['complete'], not partial)
                self.assertEqual(report['status'], 'partial' if partial else 'complete')
                self.assertEqual(report['gap_counts']['body_coverage_gaps'], int(partial))
                self.assertNotIn('synthetic-${literal}', stdout.getvalue())

    def test_cli_protected_dotenv_no_interpolation_and_no_password_argument(self):
        from unittest.mock import patch
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as td:
            env = Path(td)/'secrets.env'
            env.write_text('MAIL_EVENTS_IMAP_PASSWORD=synthetic-${UNSET}\n')
            env.chmod(0o600)
            args = ['collect', '--host', 'imap.example.invalid', '--account', 'person@example.invalid', '--start', START.isoformat(), '--end', END.isoformat(), '--output', str(Path(td)/'run'), '--env-file', str(env)]
            fake = BodyIMAP()
            fake.login = lambda account, password: self.assertEqual(password, 'synthetic-${UNSET}')
            fake.logout = lambda: ('BYE', [])
            with patch.dict('os.environ', {}, clear=True), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(m.main(args, imap_factory=lambda *a, **k: fake), 0)
            env.chmod(0o644)
            output = io.StringIO()
            with patch.dict('os.environ', {}, clear=True), contextlib.redirect_stdout(output):
                self.assertEqual(m.main(args[:-4]+['--output', str(Path(td)/'unsafe'), '--env-file', str(env)], imap_factory=lambda *a, **k: self.fail('network before protected input check')), 2)
            self.assertNotIn('synthetic', output.getvalue())
            import subprocess
            result = subprocess.run([sys.executable, m.__file__, 'collect', '--help'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn('--password-env', result.stdout)
            self.assertNotIn('--password PASSWORD', result.stdout)

    def test_mime_fingerprint_frames_parts_and_flags_both_conflicts(self):
        first = EmailMessage()
        first['Message-ID'] = '<framing@example.invalid>'
        first.set_type('multipart/mixed')
        a = EmailMessage(); a.set_content('alpha')
        b = EmailMessage(); b.set_content('beta')
        first.attach(a); first.attach(b)
        second = EmailMessage()
        second['Message-ID'] = first['Message-ID']
        joined = a.get_payload(decode=True) + str(b['Content-Type']).encode() + b'\x00\x00' + b.get_payload(decode=True)
        second.set_content(joined.decode(), cte='base64')
        with tempfile.TemporaryDirectory() as td:
            index = {'messages': []}
            for uid, msg in (('1', first), ('2', first), ('3', second)):
                m.store_message(msg.as_bytes(), {'folder': 'INBOX', 'uid': uid, 'uidvalidity': '42'}, td, index)
            self.assertEqual(len(index['messages']), 2)
            self.assertNotEqual(*[r['content_sha256'] for r in index['messages']])
            self.assertEqual(len(index['messages'][0]['source_refs']), 2)
            self.assertTrue(all(r['message_id_collision'] for r in index['messages']))

    def test_offline_decode_fallback_is_not_complete(self):
        raw = b'Content-Type: text/plain; charset=x-unknown\r\nContent-Transfer-Encoding: x-unknown\r\n\r\nMeeting 21:30\r\n'
        with tempfile.TemporaryDirectory() as td:
            rec = m.extract_message(raw, Path(td)/'message')
            self.assertIn('21:30', Path(rec['text_path']).read_text())
            reasons = [g['reason'] for g in rec['body_coverage_gaps']]
            self.assertIn('charset_fallback', reasons)
            self.assertIn('unsupported_transfer_encoding', reasons)

    def test_unknown_text_preserved_but_extraction_is_partial(self):
        msg = EmailMessage()
        msg.set_content('Meeting 21 November at 21:30', subtype='enriched')
        with tempfile.TemporaryDirectory() as td:
            rec = m.extract_message(msg.as_bytes(), Path(td)/'message')
            self.assertIn('21:30', Path(rec['text_path']).read_text())
            self.assertEqual(rec['body_coverage_gaps'][0]['reason'], 'unsupported_text_format')

    def test_nonempty_snapshot_refused_before_network_preserves_all_bytes(self):
        for stage in ('LIST', 'SELECT', 'FETCH'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                m.save_json(root/'index.json', {'messages': [{'key': 'old'}]})
                m.save_json(root/'coverage.json', {'complete': True})
                m.save(root/'sources'/'old.eml', b'old source')
                before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
                fake = FailedIMAP(stage)
                with self.assertRaises(FileExistsError):
                    m.collect(fake, root, START, END)
                self.assertEqual(fake.calls, [])
                self.assertEqual(before, {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()})


if __name__ == '__main__':
    unittest.main()
