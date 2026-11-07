"""Read-only IMAP collector. No flags, sends, expunges or remote resources."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from mail_events import private_dir, save_json
from body_only import store_selected


def collect(imap, root, start, end):
    root = Path(root)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError('snapshot must be new or empty')
    root = private_dir(root)
    if not start.tzinfo or not end.tzinfo or start >= end:
        raise ValueError('window must be ordered and timezone aware')
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    since = (start-timedelta(days=1)).strftime('%d-%b-%Y')
    index = {'schema': 2, 'window': {'start': start.isoformat(), 'end': end.isoformat(), 'interval': '[start,end)', 'date_basis': 'IMAP INTERNALDATE'}, 'messages': []}
    coverage = {'schema': 2, 'window': index['window'], 'search': {'criterion': 'SINCE', 'value': since, 'sender_filter': None},
                'access': {'readonly_select': True, 'body_fetch': 'BODYSTRUCTURE + bounded BODY.PEEK[section]', 'remote_resources_loaded': False},
                'scope': {'mode': 'body_only', 'pdf_payloads': 'never_requested', 'binary_payloads': 'excluded'},
                'folders': [], 'errors': [], 'complete': False, 'transport_complete': False,
                'calendar_policy': 'Selected original ICS preserved, not expanded/interpreted'}

    def checkpoint():
        folders = coverage['folders']
        atts = [a for msg in index['messages'] for a in msg['attachments']]
        counts = {}
        for a in atts:
            counts[a['status']] = counts.get(a['status'], 0)+1
        coverage['totals'] = {
            'listed_folders': len(folders), 'selected_folders': sum(f.get('selected', False) for f in folders),
            'candidate_refs': sum(len(f['candidate_uids']) for f in folders),
            'in_window_refs': sum(len(f['in_window_uids']) for f in folders),
            'excluded_refs': sum(len(f['excluded_uids']) for f in folders),
            'collected_refs': sum(len(f['collected_uids']) for f in folders),
            'failed_refs': sum('error_type' in ref for f in folders for ref in f['refs']),
            'unique_messages': len(index['messages']), 'attachments': len(atts), 'attachment_status_counts': counts,
            'folder_errors': sum(len(f['errors']) for f in folders), 'global_errors': len(coverage['errors'])}
        coverage['extraction_gaps'] = [dict(message_key=msg['key'], **a) for msg in index['messages'] for a in msg['attachments'] if a['status'] not in ('text_extracted', 'skipped_by_user')]
        coverage['body_mime_defects'] = [{'message_key': msg['key'], 'defects': msg['defects']} for msg in index['messages'] if msg['defects']]
        coverage['body_coverage_gaps'] = [dict(message_key=msg['key'], **gap) for msg in index['messages'] for gap in msg['body_coverage_gaps']]
        coverage['extraction_complete'] = not any(coverage[k] for k in ('extraction_gaps', 'body_mime_defects', 'body_coverage_gaps'))
        coverage['complete'] = coverage['transport_complete'] and coverage['extraction_complete']
        save_json(root/'index.json', index)
        save_json(root/'coverage.json', coverage)

    def ok(result):
        typ, data = result
        if typ != 'OK':
            raise RuntimeError('IMAP command failed')
        return data

    checkpoint()
    try:
        listed = ok(imap.list())
    except Exception as exc:
        coverage['errors'].append({'stage': 'LIST', 'error_type': type(exc).__name__})
        checkpoint()
        return coverage, index
    for line in listed:
        match = re.fullmatch(rb'\(([^)]*)\)\s+(NIL|"(?:[^"\\]|\\.)*")\s+(.+)', line) if isinstance(line, bytes) else None
        if not match:
            coverage['errors'].append({'stage': 'LIST_PARSE', 'error_type': 'UnsupportedListEntry'})
            continue
        token = match.group(3)
        if token.startswith(b'"') and token.endswith(b'"'):
            token = re.sub(rb'\\(.)', rb'\1', token[1:-1])
        try:
            flags = match.group(1).decode('ascii').split()
            wire_name = token.decode('ascii')
            list_line = line.decode('ascii')
        except UnicodeError:
            coverage['errors'].append({'stage': 'LIST_PARSE', 'error_type': 'UnsupportedListEncoding'})
            continue
        coverage['folders'].append({'name': wire_name, 'wire_name': wire_name, 'list_line': list_line, 'flags': flags,
             'selected': False, 'uidvalidity': None, 'candidate_uids': [], 'in_window_uids': [],
             'excluded_uids': [], 'collected_uids': [], 'refs': [], 'errors': []})
    checkpoint()
    for f in coverage['folders']:
        if any(flag.lower() == '\\noselect' for flag in f['flags']):
            f['not_selectable'] = True
            checkpoint()
            continue
        try:
            quoted = '"'+f['wire_name'].replace('\\', '\\\\').replace('"', '\\"')+'"'
            selected = ok(imap.select(quoted, readonly=True))
            f['selected'] = True
            f['selected_message_count'] = int(selected[0])
            validity = imap.response('UIDVALIDITY')[1]
            if not validity or not validity[0] or not validity[0].isdigit():
                raise RuntimeError('missing UIDVALIDITY')
            f['uidvalidity'] = validity[0].decode('ascii')
            data = ok(imap.uid('SEARCH', None, 'SINCE', since))
            candidates = b' '.join(x for x in data if isinstance(x, bytes)).split()
            if not all(x.isdigit() for x in candidates):
                raise RuntimeError('invalid SEARCH UIDs')
            f['candidate_uids'] = [str(n) for n in sorted(set(map(int, candidates)))]
        except Exception as exc:
            f['errors'].append({'stage': 'SELECT_OR_SEARCH', 'error_type': type(exc).__name__})
            checkpoint()
            continue
        checkpoint()
        for uid in f['candidate_uids']:
            ref = {'folder': f['name'], 'uidvalidity': f['uidvalidity'], 'uid': uid}
            f['refs'].append(ref)
            try:
                data = ok(imap.uid('FETCH', uid, '(UID INTERNALDATE FLAGS)'))
                meta = b' '.join(x for x in data if isinstance(x, bytes))
                found_uid = re.search(rb'\bUID (\d+)\b', meta)
                dt = re.search(rb'INTERNALDATE "([^"]+)"', meta)
                if not found_uid or found_uid.group(1).decode() != uid or not dt:
                    raise RuntimeError('missing or mismatched FETCH metadata')
                stamp = datetime.strptime(dt.group(1).decode('ascii').strip(), '%d-%b-%Y %H:%M:%S %z').astimezone(timezone.utc)
                ref['internaldate'] = stamp.isoformat()
                ref['in_window'] = start <= stamp < end
                old_flags = re.search(rb'FLAGS \(([^)]*)\)', meta)
                ref['flags_before'] = old_flags.group(1).decode('ascii').split() if old_flags else None
                if not ref['in_window']:
                    f['excluded_uids'].append(uid)
                    continue
                f['in_window_uids'].append(uid)
                rec = store_selected(imap, uid, ref, root, index)
                ref['message_key'] = rec['key']
                f['collected_uids'].append(uid)
            except Exception as exc:
                ref['error_type'] = type(exc).__name__
                f['errors'].append({'uid': uid, 'stage': 'FETCH_OR_EXTRACT', 'error_type': type(exc).__name__})
            finally:
                checkpoint()
        f['complete'] = not f['errors'] and len(f['refs']) == len(f['candidate_uids']) and len(f['collected_uids']) == len(f['in_window_uids'])
        checkpoint()
    coverage['transport_complete'] = not coverage['errors'] and all(f.get('not_selectable') or f.get('complete') for f in coverage['folders'])
    checkpoint()
    return coverage, index
