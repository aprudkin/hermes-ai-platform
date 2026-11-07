"""Private, offline MIME extraction and read-only IMAP event-source corpus.
Mail/attachments are untrusted data, never instructions. No network parsing.
"""
import hashlib
import json
import os
from pathlib import Path
import re
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser


def private_dir(path):
    path = Path(path)
    if not path.parent.exists():
        private_dir(path.parent)
    path.mkdir(exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def save(path, value):
    path = Path(path)
    private_dir(path.parent)
    payload = value if isinstance(value, bytes) else value.encode('utf-8')
    tmp = path.with_name(path.name + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(payload)
    tmp.chmod(0o600)
    tmp.replace(path)
    return str(path.resolve())


def save_json(path, value):
    return save(path, json.dumps(value, ensure_ascii=False, indent=2))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_name(name):
    name = str(name or 'unnamed').replace('\\', '/')
    name = name.rsplit('/', 1)[-1]
    return re.sub(r'[^\w.() +@-]', '_', name, flags=re.UNICODE)[:140].strip('. ') or 'unnamed'


class HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.out = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'head'):
            self.hidden += 1
        elif not self.hidden:
            if tag in ('p', 'div', 'br', 'tr', 'li', 'h1', 'h2', 'table'):
                self.out.append('\n')
            if tag == 'a':
                for key, value in attrs:
                    if key == 'href' and value:
                        self.out.append(' [link: ' + value + '] ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'head') and self.hidden:
            self.hidden -= 1
        elif not self.hidden and tag in ('p', 'div', 'tr', 'li'):
            self.out.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.out.append(data)


def decode_bytes(data, charset=None):
    for encoding in (charset, 'utf-8', 'cp1251', 'latin-1'):
        if not encoding:
            continue
        try:
            return data.decode(encoding)
        except (UnicodeError, LookupError):
            pass
    return data.decode('utf-8', errors='replace')


def decode_text_part(part, data):
    gaps = []
    try:
        data.decode(part.get_content_charset() or 'utf-8')
    except (UnicodeError, LookupError):
        gaps.append('charset_fallback')
    if str(part.get('Content-Transfer-Encoding', '7bit')).lower() not in ('7bit', '8bit', 'binary', 'base64', 'quoted-printable'):
        gaps.append('unsupported_transfer_encoding')
    return decode_bytes(data, part.get_content_charset()), gaps


def html_text(text):
    p = HTMLText()
    p.feed(text)
    return ''.join(p.out)


def extract_attachment(att):
    """Only local parsers; never unzip to disk, execute macros or load URLs."""
    import zipfile
    import xml.etree.ElementTree as ET
    path = Path(att['path'])
    suffix = path.suffix.lower()
    ctype = att['type']
    try:
        if suffix in ('.html', '.htm', '.txt', '.csv', '.json', '.xml', '.rtf'):
            text = decode_bytes(path.read_bytes())
            if suffix in ('.html', '.htm'):
                text = html_text(text)
            att['text_path'] = save(path.with_name(path.name+'.txt'), text)
            att['status'] = 'text_extracted' if suffix != '.rtf' else 'rtf_source_preserved'
        elif ctype == 'application/pdf' or suffix == '.pdf':
            # Owner explicitly removed PDF checking. Do not import a PDF parser,
            # open the PDF, inspect its text, render it, or follow download links.
            att['status'] = 'skipped_by_user'
            previous = path.with_name(path.name+'.txt')
            if previous.exists():
                att['previous_extraction_artifact_path'] = str(previous.resolve())
                att['previous_extraction_note'] = 'Produced before scope change; not part of current body-first review'
        elif suffix == '.docx' or ctype == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document':
            with zipfile.ZipFile(path) as z:
                names = [i for i in z.infolist() if i.filename.startswith('word/') and
                         re.match(r'word/(document|header\d+|footer\d+|footnotes|endnotes|comments)\.xml$', i.filename)]
                if sum(i.file_size for i in names) > 32*1024*1024:
                    att['status'] = 'oversize_zip_xml'
                    return
                texts = []
                for info in names:
                    if info.flag_bits & 1:
                        att['status'] = 'encrypted_archive'
                        return
                    root = ET.fromstring(z.read(info))
                    lines = []
                    for node in root.iter():
                        tag = node.tag.rsplit('}', 1)[-1]
                        if tag == 't' and node.text:
                            lines.append(node.text)
                        elif tag in ('p', 'br', 'tab'):
                            lines.append('\n' if tag != 'tab' else '\t')
                    texts.append(f'--- {info.filename} ---\n'+''.join(lines))
                att['text_path'] = save(path.with_name(path.name+'.txt'), '\n'.join(texts))
                att['status'] = 'text_extracted'
                att['embedded_media'] = [i.filename for i in z.infolist() if i.filename.startswith('word/media/')]
                if att['embedded_media']:
                    att['status'] = 'text_extracted_embedded_media_unreviewed'
        elif ctype.startswith('image/') or suffix in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.tif', '.tiff'):
            att['status'] = 'needs_visual_review'
        elif suffix in ('.zip', '.7z', '.rar', '.gz', '.tar', '.docm', '.xlsm') or 'zip' in ctype or 'archive' in ctype:
            att['status'] = 'unsupported_archive'
        else:
            att['status'] = 'unsupported'
    except Exception as exc:
        # No untrusted content/exception strings in logs or control output.
        att['status'] = 'extraction_error'
        att['error_type'] = type(exc).__name__


def store_message(raw, source, root, index):
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    mid = str(msg.get('Message-ID', '')).strip()
    # Canonical structure frames every part; payload concatenation is ambiguous.
    fingerprint = {
        'headers': [[field, msg.get_all(field, [])] for field in ('Subject', 'From', 'To', 'Cc', 'Date')],
        'parts': [{'headers': list(part.raw_items()), 'multipart': part.is_multipart(),
                   'payload_sha256': digest(part.get_payload(decode=True) or b'')}
                  for part in msg.walk()]}
    content_hash = digest(json.dumps(fingerprint, sort_keys=True, ensure_ascii=True).encode())
    key = digest((mid+'\x00'+content_hash).encode())[:32] if mid else digest(raw)[:32]
    root = Path(root)
    source = dict(source)
    source['raw_sha256'] = digest(raw)
    source['raw_path'] = save(root/'sources'/f'{digest(json.dumps(source, sort_keys=True).encode())[:24]}.eml', raw)
    existing = next((r for r in index['messages'] if r['key'] == key), None)
    if existing:
        if source not in existing['source_refs']:
            existing['source_refs'].append(source)
        save_json(existing['metadata_path'], existing)
        return existing
    rec = extract_message(raw, root/'messages'/key)
    rec.update(key=key, content_sha256=content_hash, source_refs=[source],
               message_id_collision=bool(mid and any(r['message_id'] == mid for r in index['messages'])))
    index['messages'].append(rec)
    if rec['message_id_collision']:
        for other in index['messages']:
            if other['message_id'] == mid:
                other['message_id_collision'] = True
                save_json(other['metadata_path'], other)
    save_json(rec['metadata_path'], rec)
    return rec


def extract_message(raw, directory, *, check_pdf=False):
    directory = private_dir(directory)
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    rec: dict = {key.replace('-', '_').lower(): str(msg.get(key, '')) for key in
           ('Subject', 'From', 'To', 'Cc', 'Date', 'Message-ID')}
    rec.update(raw_sha256=digest(raw), raw_path=save(directory/'source.eml', raw),
               attachments=[], defects=[str(d) for d in msg.defects], body_parts=[], body_coverage_gaps=[])
    sections = []
    for idx, part in enumerate(msg.walk()):
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        filename = part.get_filename()
        if ctype == 'application/pdf' or str(filename or '').lower().endswith('.pdf'):
            rec['attachments'].append({'part': idx, 'name': filename, 'type': ctype, 'status': 'skipped_by_user', 'text_path': None})
            continue
        data = part.get_payload(decode=True) or b''
        disposition = part.get_content_disposition()
        is_calendar = ctype in ('text/calendar', 'application/ics', 'application/icalendar') or str(filename or '').lower().endswith('.ics')
        is_attachment = bool(filename or disposition == 'attachment' or is_calendar or not ctype.startswith('text/'))
        decoded = None
        if ctype.startswith('text/') or is_calendar:
            decoded, gaps = decode_text_part(part, data)
            rec['body_coverage_gaps'].extend({'part': idx, 'reason': gap} for gap in gaps)
        rec['defects'].extend(type(d).__name__ for d in part.defects)
        if ctype.startswith('text/') and disposition != 'attachment' and not filename:
            text = html_text(decoded) if ctype == 'text/html' else decoded
            sections.append(f'--- MIME part {idx}: {ctype} ---\n{text}')
            rec['body_parts'].append({'part': idx, 'type': ctype, 'characters': len(text)})
            if ctype not in ('text/plain', 'text/html', 'text/calendar'):
                rec['body_coverage_gaps'].append({'part': idx, 'type': ctype, 'reason': 'unsupported_text_format'})
        if is_attachment:
            name = safe_name(filename or ('calendar.ics' if is_calendar else 'part-' + str(idx)))
            path = directory/'attachments'/f'{idx:03d}-{name}'
            att = {'part': idx, 'name': filename or name, 'safe_name': name, 'type': ctype,
                   'disposition': disposition, 'content_id': str(part.get('Content-ID', '')),
                   'size': len(data), 'sha256': digest(data), 'path': save(path, data),
                   'text_path': None, 'status': 'unsupported'}
            if is_calendar:
                att['text_path'] = save(path.with_name(path.name+'.txt'), decoded)
                att['status'] = 'calendar_preserved_unexpanded'
                sections.append(f'--- Calendar part {idx} (full source; recurrence/timezones NOT expanded) ---\n{decoded}')
            elif ctype.startswith('text/'):
                att['text_path'] = save(path.with_name(path.name+'.txt'), html_text(decoded) if ctype == 'text/html' else decoded)
                att['status'] = 'text_extracted'
            else:
                extract_attachment(att)
            rec['attachments'].append(att)
            sections.append(f"--- Attachment part {idx}: {name} ({att['status']}) ---\nLocal source: {att['path']}")
            if att['text_path'] and not is_calendar:
                sections.append(Path(att['text_path']).read_text(encoding='utf-8'))
    if not rec['body_parts'] and not any(a['status'] == 'calendar_preserved_unexpanded' for a in rec['attachments']):
        rec['body_coverage_gaps'].append({'reason': 'no_readable_body'})
    header = '\n'.join(f'{k}: {rec[k]}' for k in ('subject', 'from', 'to', 'cc', 'date', 'message_id'))
    rec['text_path'] = save(directory/'readable.txt', header+'\n\n'+'\n\n'.join(sections))
    rec['metadata_path'] = str((directory/'metadata.json').resolve())
    save_json(rec['metadata_path'], rec)
    return rec


def reextract(root, output):
    """Historical full-MIME corpus is read-only; rebuild into a fresh directory."""
    root, output = Path(root).resolve(), Path(output).resolve()
    if output == root or output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError('input and output must be disjoint')
    if output.exists() and any(output.iterdir()):
        raise FileExistsError('snapshot must be new or empty')
    index = json.loads((root/'index.json').read_text(encoding='utf-8'))
    coverage = json.loads((root/'coverage.json').read_text(encoding='utf-8'))
    coverage['transport_complete'] = coverage.get('transport_complete', coverage['complete'])
    for i, old in enumerate(index['messages']):
        fresh = extract_message(Path(old['raw_path']).read_bytes(), output/'messages'/old['key'])
        for key in ('key', 'content_sha256', 'source_refs', 'message_id_collision'):
            fresh[key] = old[key]
        fresh['hash_scope'] = 'historical_full_mime'
        index['messages'][i] = fresh
        save_json(fresh['metadata_path'], fresh)
    atts = [a for msg in index['messages'] for a in msg['attachments']]
    counts = {}
    for a in atts:
        counts[a['status']] = counts.get(a['status'], 0)+1
    coverage['totals'].update(attachments=len(atts), attachment_status_counts=counts)
    coverage['extraction_gaps'] = [dict(message_key=msg['key'], **a) for msg in index['messages'] for a in msg['attachments'] if a['status'] not in ('text_extracted', 'skipped_by_user', 'calendar_preserved_unexpanded')]
    coverage['body_mime_defects'] = [{'message_key': msg['key'], 'defects': msg['defects']} for msg in index['messages'] if msg['defects']]
    coverage['body_coverage_gaps'] = [dict(message_key=msg['key'], **g) for msg in index['messages'] for g in msg['body_coverage_gaps']]
    coverage['extraction_complete'] = not any(coverage[k] for k in ('extraction_gaps', 'body_mime_defects', 'body_coverage_gaps'))
    coverage['complete'] = coverage['transport_complete'] and coverage['extraction_complete']
    coverage['scope'] = {'mode': 'historical_full_mime_offline', 'pdf_checking': 'skipped_by_user', 'historical_note': 'Full MIME bytes were downloaded historically; preserved raw copies include those bytes. No new transport, PDF decoding or PDF artifacts.', 'remote_links_followed': False}
    save_json(output/'index.json', index)
    save_json(output/'coverage.json', coverage)
    return coverage, index


def collect(imap, root, start, end):
    from collector import collect as run
    return run(imap, root, start, end)


def main(argv=None, *, imap_factory=None):
    import argparse
    from datetime import datetime
    import imaplib
    import ssl
    import stat
    parser = argparse.ArgumentParser(description='Read-only body-only mail collection; no PDF or binary downloads')
    commands = parser.add_subparsers(dest='command', required=True)
    fresh = commands.add_parser('collect', help='Fresh TLS IMAP snapshot of all selectable folders')
    fresh.add_argument('--host', required=True)
    fresh.add_argument('--port', type=int, default=993)
    fresh.add_argument('--account', required=True)
    fresh.add_argument('--start', required=True, type=datetime.fromisoformat)
    fresh.add_argument('--end', required=True, type=datetime.fromisoformat)
    fresh.add_argument('--password-env', default='MAIL_EVENTS_IMAP_PASSWORD', help='Protected environment key NAME, never the password')
    fresh.add_argument('--env-file', type=Path, help='Optional owner-only dotenv file; interpolation disabled')
    offline = commands.add_parser('reextract', help='Historical full-MIME input, untouched; new output required')
    offline.add_argument('--input', required=True, type=Path)
    for sub in (fresh, offline):
        sub.add_argument('--output', required=True, type=Path, help='New or empty private snapshot directory')
    args = parser.parse_args(argv)
    try:
        if args.output.exists() and any(args.output.iterdir()):
            raise FileExistsError('snapshot must be new or empty')
        if args.command == 'reextract':
            cov, _ = reextract(args.input, args.output)
        else:
            if args.start.utcoffset() is None or args.end.utcoffset() is None or args.start >= args.end:
                raise ValueError('ordered timezone-aware window required')
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', args.password_env):
                raise ValueError('invalid environment key name')
            values = {}
            if args.env_file:
                st = args.env_file.stat()
                if args.env_file.is_symlink() or not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o077:
                    raise PermissionError('credential file must be owner-only')
                from dotenv import dotenv_values
                values = dotenv_values(args.env_file, interpolate=False)
            password = os.environ.get(args.password_env) or values.get(args.password_env)
            if not password:
                raise ValueError('protected credential missing')
            imap = (imap_factory or imaplib.IMAP4_SSL)(args.host, args.port, ssl_context=ssl.create_default_context(), timeout=30)
            try:
                imap.login(args.account, password)
                cov, _ = collect(imap, args.output, args.start, args.end)
            finally:
                try:
                    imap.logout()
                except Exception:
                    pass
        print(json.dumps({'status': 'complete' if cov['complete'] else 'partial',
                          'complete': cov['complete'], 'transport_complete': cov['transport_complete'],
                          'extraction_complete': cov['extraction_complete'], 'totals': cov['totals'],
                          'gap_counts': {k: len(cov[k]) for k in ('body_coverage_gaps', 'body_mime_defects', 'extraction_gaps')}}, ensure_ascii=False))
        return 0 if cov['complete'] else 1
    except Exception as exc:
        # Server/decoder exception strings may contain private mail or credentials.
        print(json.dumps({'status': 'failed', 'complete': False, 'error_type': type(exc).__name__}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
