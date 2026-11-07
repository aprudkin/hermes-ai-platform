"""Bounded IMAP section retrieval; never fetch a full message or a PDF part."""
import json
from pathlib import Path
import re
from email import policy
from email.parser import BytesHeaderParser, BytesParser
from email.message import Message
from mail_events import digest, save, save_json, decode_text_part, html_text

MAX_TEXT = 2 * 1024 * 1024
MAX_HEADER = 64 * 1024


def ok(result):
    typ, data = result
    if typ != 'OK':
        raise RuntimeError('IMAP command failed')
    return data


def wire(data):
    return b' '.join(x[0] + b'\r\n' + x[1] if isinstance(x, tuple) else x
                     for x in data if isinstance(x, (tuple, bytes)))


def parse_structure(data):
    """Parse RFC 3501 lists/quoted strings/literals, not Python expressions."""
    raw = wire(data)
    if len(raw) > 1024 * 1024:
        raise ValueError('oversize BODYSTRUCTURE')
    match = re.search(rb'\bBODYSTRUCTURE\s+', raw, re.I)
    if not match:
        raise ValueError('missing BODYSTRUCTURE')
    pos = match.end()

    def value(depth=0):
        nonlocal pos
        if depth > 40:
            raise ValueError('BODYSTRUCTURE nesting limit')
        while pos < len(raw) and raw[pos:pos+1].isspace():
            pos += 1
        if pos >= len(raw):
            raise ValueError('truncated BODYSTRUCTURE')
        token = raw[pos:pos+1]
        pos += 1
        if token == b'(':
            out = []
            while True:
                while pos < len(raw) and raw[pos:pos+1].isspace():
                    pos += 1
                if raw[pos:pos+1] == b')':
                    pos += 1
                    return out
                out.append(value(depth+1))
        if token == b'"':
            out = bytearray()
            while pos < len(raw):
                c = raw[pos:pos+1]; pos += 1
                if c == b'"':
                    return out.decode('ascii')
                if c == b'\\':
                    c = raw[pos:pos+1]; pos += 1
                out.extend(c)
            raise ValueError('unterminated quoted string')
        if token == b'{':
            literal = re.match(rb'(\d+)\}\r\n', raw[pos:])
            if not literal:
                raise ValueError('invalid literal')
            pos += literal.end()
            size = int(literal.group(1))
            out = raw[pos:pos+size]; pos += size
            if len(out) != size:
                raise ValueError('truncated literal')
            return out.decode('ascii')
        atom = re.match(rb'[^\s()]+', raw[pos-1:])
        if not atom:
            raise ValueError('invalid atom')
        pos = pos-1+atom.end()
        text = atom.group().decode('ascii')
        return None if text.upper() == 'NIL' else int(text) if text.isdigit() else text

    result = value()
    if not isinstance(result, list):
        raise ValueError('BODYSTRUCTURE must be a list')
    return result, raw


def filenames(params):
    if params is None:
        return []
    if not isinstance(params, list) or len(params) % 2:
        raise ValueError('invalid MIME parameters')
    fields = []
    for key, val in zip(params[::2], params[1::2]):
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_*.-]+', key) or not isinstance(val, str):
            raise ValueError('unsupported MIME parameters')
        fields.append(key+'="'+val.replace('\\', '\\\\').replace('"', '\\"')+'"')
    msg = Message(policy=policy.default)
    msg['Content-Type'] = 'application/octet-stream; '+'; '.join(fields)
    # stdlib handles RFC 2231 continuations/percent encoding.
    name = msg.get_filename()
    if name is None:
        msg['Content-Disposition'] = 'attachment; '+'; '.join(fields)
        name = msg.get_filename()
    return [str(name)] if name else []


def parts(tree, prefix=''):
    if not tree:
        raise ValueError('empty BODYSTRUCTURE')
    if isinstance(tree[0], list):
        count = 0
        for child in tree:
            if not isinstance(child, list):
                break
            count += 1
            yield from parts(child, f'{prefix}.{count}' if prefix else str(count))
        if count >= len(tree) or not isinstance(tree[count], str):
            raise ValueError('missing multipart subtype')
        return
    if len(tree) < 7 or not all(isinstance(tree[i], str) for i in (0, 1, 5)) or not isinstance(tree[6], int) or tree[6] < 0:
        raise ValueError('unsupported leaf BODYSTRUCTURE')
    ctype = f'{tree[0]}/{tree[1]}'.lower()
    names = filenames(tree[2])
    if tree[0].upper() == 'TEXT' and (len(tree) < 8 or not isinstance(tree[7], int) or tree[7] < 0):
        raise ValueError('missing text line count')
    # body-ext-1part: MD5, disposition; text has a mandatory line count first.
    ext = 8 if tree[0].upper() == 'TEXT' else 7
    if len(tree) > ext+1 and tree[ext+1] is not None:
        disp = tree[ext+1]
        if not isinstance(disp, list) or len(disp) != 2:
            raise ValueError('invalid MIME disposition')
        names.extend(filenames(disp[1]))
    pdf = ctype == 'application/pdf' or any(n.lower().endswith('.pdf') for n in names)
    textual = ctype.startswith('text/') or ctype in ('application/ics', 'application/icalendar') or (
        ctype == 'application/octet-stream' and any(n.lower().endswith(('.html', '.htm', '.txt', '.ics', '.csv', '.json', '.xml')) for n in names))
    yield {'section': prefix or '1', 'type': ctype, 'size': tree[6], 'names': names,
           'selected': textual and not pdf, 'reason': 'pdf_excluded' if pdf else 'binary_excluded'}


def section(imap, uid, name, limit, source, directory):
    data = ok(imap.uid('FETCH', uid, f'(UID BODY.PEEK[{name}]<0.{limit+1}> FLAGS)'))
    literals = [x for x in data if isinstance(x, tuple)]
    if len(literals) != 1:
        raise ValueError('missing or ambiguous section literal')
    meta, payload = literals[0]
    metadata = b' '.join(x[0] if isinstance(x, tuple) else x for x in data if isinstance(x, (tuple, bytes)))
    found_uid = re.search(rb'\bUID (\d+)\b', metadata)
    label = re.search(rb'BODY\[([^]]+)\](?:<0>)?\s+\{(\d+)\}', meta, re.I)
    if not found_uid or found_uid.group(1).decode() != uid or not label or label.group(1).decode().upper() != name.upper() or int(label.group(2)) != len(payload):
        raise ValueError('mismatched section response')
    if len(payload) > limit:
        raise ValueError('section size limit exceeded')
    flags = re.search(rb'FLAGS \(([^)]*)\)', metadata)
    source['flags_after'] = flags.group(1).decode('ascii').split() if flags else None
    source.setdefault('sections', {})[name] = {
        'path': save(directory/(name+'.section'), payload), 'sha256': digest(payload), 'size': len(payload)}
    return payload


def store_selected(imap, uid, source, root, index):
    identity = {k: source[k] for k in ('folder', 'uidvalidity', 'uid')}
    key = digest(json.dumps(identity, sort_keys=True).encode())[:32]
    directory = Path(root)/'sources'/key
    structure_data = ok(imap.uid('FETCH', uid, '(UID BODYSTRUCTURE)'))
    found_uid = re.search(rb'\bUID (\d+)\b', wire(structure_data))
    if not found_uid or found_uid.group(1).decode() != uid:
        raise ValueError('mismatched BODYSTRUCTURE UID')
    tree, raw_structure = parse_structure(structure_data)
    source['bodystructure_path'] = save(directory/'bodystructure.response', raw_structure)
    source['bodystructure_sha256'] = digest(raw_structure)
    plan = list(parts(tree))
    headers = section(imap, uid, 'HEADER', MAX_HEADER, source, directory)
    msg = BytesHeaderParser(policy=policy.default).parsebytes(headers)
    rec: dict = {k.replace('-', '_').lower(): str(msg.get(k, '')) for k in ('Subject', 'From', 'To', 'Cc', 'Date', 'Message-ID')}
    rec.update(key=key, hash_scope='selected_sections_only', source_refs=[source], body_parts=[],
               attachments=[], excluded_parts=[p for p in plan if not p['selected']],
               body_coverage_gaps=[], defects=[type(d).__name__ for d in msg.defects],
               metadata_path=str((directory/'metadata.json').resolve()))
    readable = []
    for part in plan:
        name = part['section']
        if not part['selected']:
            if part['type'].startswith('message/'):
                rec['body_coverage_gaps'].append({'section': name, 'reason': 'unsupported_nested_message'})
            continue
        if part['size'] > MAX_TEXT:
            rec['body_coverage_gaps'].append({'section': name, 'reason': 'text_size_limit'})
            continue
        mime = section(imap, uid, name+'.MIME', MAX_HEADER, source, directory)
        payload = section(imap, uid, name, MAX_TEXT, source, directory)
        # Parse an individual MIME part in memory, never fabricate a complete .eml.
        leaf = BytesParser(policy=policy.default).parsebytes(mime+payload)
        if not leaf.get('Content-Type') or leaf.get_content_type() != part['type']:
            rec['body_coverage_gaps'].append({'section': name, 'reason': 'mime_header_mismatch'})
        data = leaf.get_payload(decode=True) or b''
        text, gaps = decode_text_part(leaf, data)
        rec['body_coverage_gaps'].extend({'section': name, 'reason': gap} for gap in gaps)
        ctype = part['type']
        is_html = ctype == 'text/html' or any(n.lower().endswith(('.html', '.htm')) for n in part['names'])
        text = html_text(text) if is_html else text
        readable.append(f'--- Section {name}: {ctype} ---\n{text}')
        rec['body_parts'].append(dict(part, characters=len(text)))
        rec['defects'].extend(type(d).__name__ for d in leaf.defects)
        if ctype.startswith('text/') and ctype not in ('text/plain', 'text/html', 'text/calendar'):
            rec['body_coverage_gaps'].append({'section': name, 'reason': 'unsupported_text_format'})
    if not rec['body_parts']:
        rec['body_coverage_gaps'].append({'reason': 'no_readable_body'})
    rec['selected_sections_sha256'] = digest(json.dumps({k: v['sha256'] for k, v in source['sections'].items()}, sort_keys=True).encode())
    rec['deduplication'] = 'source_identity_only; unfetched attachments are not compared'
    rec['message_id_collision'] = False
    for other in index['messages']:
        if rec['message_id'] and other['message_id'] == rec['message_id']:
            rec['message_id_collision'] = other['message_id_collision'] = True
            save_json(other['metadata_path'], other)
    rec['text_path'] = save(directory/'readable.txt', '\n'.join(f'{k}: {rec[k]}' for k in ('subject', 'from', 'date', 'message_id'))+'\n\n'+'\n\n'.join(readable))
    index['messages'].append(rec)
    save_json(rec['metadata_path'], rec)
    return rec
