#!/usr/bin/env python3
"""Offline, private accounting export/import. Never starts Hermes or a sender."""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

import yaml
from dotenv import dotenv_values

DATABASES = ('ledger.db', 'reply-deliveries.db', 'review-cases.db', 'native-inputs.db')
RUNTIME_FILES = tuple('scripts/' + name + '.py' for name in (
    'cash_ledger_monitor', 'cash_ledger_reply_monitor', 'cash_compact_formats',
    'cash_message_context', 'cash_period_closure', 'cash_native_input',
    'cash_reply_sender', 'cash_review_sender', 'cash_calculation_correction',
)) + ('plugins/accounting-native-input/__init__.py', 'plugins/accounting-native-input/plugin.yaml')
POLICIES = ('monitor-state.json', 'format-guidance.json', 'correction-cleanup.json',
            'pending-confirmation-policy.json')
TELEGRAM_KEYS = ('allowed_chats', 'group_allowed_chats', 'free_response_chats',
                 'require_mention', 'observe_unmentioned_group_messages', 'home_channel')
ENV_KEYS = ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_ALLOWED_USERS', 'TELEGRAM_GROUP_ALLOWED_USERS',
            'TELEGRAM_ALLOWED_CHATS', 'TELEGRAM_GROUP_ALLOWED_CHATS',
            'TELEGRAM_FREE_RESPONSE_CHATS', 'TELEGRAM_REQUIRE_MENTION',
            'TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES', 'TELEGRAM_EXCLUSIVE_BOT_MENTIONS',
            'TELEGRAM_HOME_CHANNEL', 'TELEGRAM_HOME_CHANNEL_THREAD_ID',
            'BABLOMAT_CHAT_ID', 'BABLOMAT_REVIEW_CHAT_ID', 'BABLOMAT_OWNER_ID',
            'BABLOMAT_ELENA_ID', 'BABLOMAT_PERIOD_AUTHORIZED_IDS')
ROW_COLUMNS = {'source_row_id', 'command_source_row_id', 'previous_cutoff_source_row_id',
               'confirmation_source_row_id', 'report_source_row_id', 'resolution_row_id'}
SESSION_COLUMNS = ('id', 'source', 'chat_id', 'chat_type', 'thread_id', 'started_at',
                   'ended_at', 'archived')
MESSAGE_COLUMNS = ('id', 'session_id', 'role', 'content', 'timestamp',
                   'platform_message_id', 'active', 'observed')
FORMAT = 'bablomat-portable-v1'


class PortableError(ValueError):
    """A safe, actionable error without private database/configuration contents."""


def require(condition, message):
    if not condition:
        raise PortableError(message)


def quoted(name):
    return '"' + name.replace('"', '""') + '"'


def read_db(path):
    require(path.is_file() and not path.is_symlink(), 'Database must be a regular file')
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    return db


def tables(db):
    return [row['name'] for row in db.execute('PRAGMA table_list')
            if row['schema'] == 'main' and row['type'] in ('table', 'virtual')
            and not row['name'].startswith('sqlite_')]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def dump_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    path.chmod(0o600)


def database_inventory(path):
    """Compare every row, not merely a total that could hide changed recipients."""
    with closing(read_db(path)) as db:
        require(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'SQLite integrity failure')
        require(not db.execute('PRAGMA foreign_key_check').fetchall(), 'SQLite foreign-key failure')
        result = {}
        for table in sorted(tables(db)):
            rows = []
            for row in db.execute('SELECT * FROM ' + quoted(table)):
                values = [{'blob': value.hex()} if isinstance(value, bytes) else value for value in row]
                rows.append(json.dumps(values, ensure_ascii=False, separators=(',', ':')))
            result[table] = {'count': len(rows), 'sha256': hashlib.sha256(
                json.dumps(sorted(rows), ensure_ascii=False).encode()).hexdigest()}
        return result


def regular_files(root):
    require(root.is_dir() and not root.is_symlink(), 'Expected a regular directory')
    result = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            require(not path.is_symlink(), 'Refusing symlink in input')
            require(path.is_dir() or path.is_file(), 'Refusing special file in input')
        result.extend(Path(directory) / name for name in files)
    return sorted(result)


def safe_relative(value):
    require(isinstance(value, str) and value and '\\' not in value, 'Invalid relative path')
    path = Path(value)
    require(not path.is_absolute() and all(p not in ('', '.', '..') for p in value.split('/')),
            'Invalid relative path')
    return path


def source_file(home, relative):
    path = home / safe_relative(relative)
    require(path.is_relative_to(home), 'Path outside snapshot')
    for parent in (path, *path.parents):
        if parent == home:
            break
        require(not parent.is_symlink(), 'Refusing symlink in input')
    require(path.is_file(), 'Required input file missing: ' + relative)
    return path


def copy_file(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.copyfile(source, destination)
    destination.chmod(0o600)


def copy_db(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with closing(read_db(source)) as incoming, closing(sqlite3.connect(destination)) as outgoing:
        incoming.backup(outgoing)
        outgoing.execute('PRAGMA journal_mode=DELETE')
        outgoing.execute('VACUUM')
    destination.chmod(0o600)
    require(database_inventory(source) == database_inventory(destination), 'Database copy mismatch')


def referenced_rows(cash):
    result = set()
    for name in DATABASES:
        with closing(read_db(cash / name)) as db:
            for table in tables(db):
                columns = {row['name'] for row in db.execute('PRAGMA table_info(' + quoted(table) + ')')}
                for column in ROW_COLUMNS & columns:
                    for row in db.execute('SELECT DISTINCT ' + quoted(column) + ' FROM ' + quoted(table)):
                        if row[0] is not None and row[0] != 0:
                            require(type(row[0]) is int and row[0] > 0, 'Invalid source row reference')
                            result.add(row[0])
    return result


def add_policy_rows(value, rows):
    if isinstance(value, dict):
        for key, item in value.items():
            if (key in ROW_COLUMNS or key == 'policy_source_row_id') and type(item) is int and item > 0:
                rows.add(item)
            else:
                add_policy_rows(item, rows)
    elif isinstance(value, list):
        for item in value:
            add_policy_rows(item, rows)


def filtered_state(source, destination, rows, chat_id, cursor):
    """Keep exact source IDs but no session prompts, tools, credentials or routing."""
    with closing(read_db(source)) as old, closing(sqlite3.connect(destination)) as new:
        high_water = max(old.execute('SELECT COALESCE(MAX(id),0) FROM messages').fetchone()[0],
                         old.execute("SELECT COALESCE(MAX(seq),0) FROM sqlite_sequence WHERE name='messages'").fetchone()[0])
        require(0 <= cursor <= high_water, 'Cursor is outside source history')
        pending = old.execute('''SELECT COUNT(*) FROM messages m JOIN sessions s ON s.id=m.session_id
            WHERE s.chat_id=? AND m.role='user' AND m.active=1 AND m.id>?''', (chat_id, cursor)).fetchone()[0]
        require(not pending, 'Snapshot has unprocessed bookkeeping messages; drain before final capture')
        selected = []
        for row_id in sorted(rows):
            row = old.execute('SELECT * FROM messages WHERE id=?', (row_id,)).fetchone()
            require(row is not None, 'Referenced source rows are missing; reconcile evidence before export')
            require(row['role'] == 'user', 'Referenced source is not participant input')
            selected.append(row)
        # Rebuild schema, not a deleted copy: no unrelated content in pages or FTS shadows.
        schema = list(old.execute("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"))
        table_names = set(tables(old))
        for kind in ('table', 'view', 'index'):
            for item in schema:
                if item['type'] == kind and (kind != 'table' or item['name'] in table_names):
                    new.execute(item['sql'])
        for row in old.execute('SELECT * FROM schema_version'):
            new.execute('INSERT INTO schema_version VALUES(' + ','.join('?' for _ in row) + ')', tuple(row))
        session_columns = {r[1] for r in new.execute('PRAGMA table_info(sessions)')}
        message_columns = {r[1] for r in new.execute('PRAGMA table_info(messages)')}
        seen = set()
        for row in selected:
            session = old.execute('SELECT * FROM sessions WHERE id=?', (row['session_id'],)).fetchone()
            if session is None or session['source'] != 'telegram':
                raise PortableError('Expected Telegram source session')
            session_id = 'accounting-import-' + hashlib.sha256(session['id'].encode()).hexdigest()
            if session_id not in seen:
                values = {key: session[key] for key in SESSION_COLUMNS if key in session_columns}
                values.update(id=session_id, ended_at=float(row['timestamp']))
                if 'archived' in session_columns:
                    values['archived'] = 1
                insert_row(new, 'sessions', values)
                seen.add(session_id)
            values = {key: row[key] for key in MESSAGE_COLUMNS if key in message_columns}
            values['session_id'] = session_id
            insert_row(new, 'messages', values)
        new.execute("DELETE FROM sqlite_sequence WHERE name='messages'")
        new.execute("INSERT INTO sqlite_sequence(name,seq) VALUES('messages',?)", (high_water,))
        for item in schema:
            if item['type'] == 'trigger':
                new.execute(item['sql'])
        for table in table_names:
            definition = next(item['sql'] for item in schema if item['type'] == 'table' and item['name'] == table)
            if 'USING fts5' in definition or 'USING FTS5' in definition:
                # Hermes uses external-content indexes. Contentless FTS is not portable here.
                require('content=' in definition.lower().replace(' ', ''), 'Unsupported contentless FTS schema')
                new.execute('INSERT INTO ' + quoted(table) + '(' + quoted(table) + ") VALUES('rebuild')")
        new.commit()
    destination.chmod(0o600)
    database_inventory(destination)
    return high_water


def insert_row(db, table, values):
    db.execute('INSERT INTO ' + quoted(table) + '(' + ','.join(map(quoted, values)) + ') VALUES('
               + ','.join('?' for _ in values) + ')', tuple(values.values()))


def export_bundle(home, destination, selection_path):
    """Input must be an immutable offline profile snapshot, never a running home."""
    home, destination = Path(home).absolute(), Path(destination).absolute()
    require(not home.is_symlink(), 'Refusing symlink snapshot')
    require(not destination.is_relative_to(home), 'Destination must be outside the snapshot')
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    selection = json.loads(Path(selection_path).read_text())
    require(set(selection) <= {'chat_id', 'artifacts', 'source_rows'}, 'Unknown selection field')
    chat_id = selection['chat_id']
    require(isinstance(chat_id, str) and chat_id.startswith('-') and chat_id[1:].isdigit(), 'Explicit source group ID required')
    extras = selection.get('source_rows', [])
    require(isinstance(extras, list) and all(type(n) is int and n > 0 for n in extras), 'Invalid additional source rows')
    relatives = ['state.db', 'config.yaml', '.env'] + ['cash-ledger/' + n for n in DATABASES] + list(RUNTIME_FILES)
    relatives += [str(p.relative_to(home)) for p in (home / 'cash-ledger').iterdir()
                  if p.suffix in ('.json', '.txt')]
    artifacts = selection.get('artifacts', [])
    require(isinstance(artifacts, list), 'Artifacts must be an explicitly reviewed list')
    for relative in artifacts:
        path = safe_relative(relative)
        require(path.parts[0] in ('cash-ledger', 'reports', 'workspace', 'assets', 'image_cache') and len(path.parts) > 1,
                'Select exact accounting artifacts, not an entire shared directory')
        item = home / path
        require(not item.is_symlink(), 'Refusing symlink artifact')
        relatives += [str(f.relative_to(home)) for f in regular_files(item)] if item.is_dir() else [relative]
    sources = {rel: source_file(home, rel) for rel in sorted(set(relatives))}
    for rel in list(sources):
        if rel.endswith('.db'):
            # The offline copy may contain a valid SQLite WAL; preserve its snapshot boundary.
            for suffix in ('-wal',):
                if (home / (rel + suffix)).exists():
                    sources[rel + suffix] = source_file(home, rel + suffix)
    fingerprints = {rel: digest(path) for rel, path in sources.items()}
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix='.bablomat-export-', dir=destination.parent) as temporary:
        stage = Path(temporary)
        payload = stage / 'payload'
        payload.mkdir(mode=0o700)
        for name in DATABASES:
            copy_db(home / 'cash-ledger' / name, payload / 'cash-ledger' / name)
        rows = referenced_rows(payload / 'cash-ledger') | set(extras)
        for rel in relatives:
            if Path(rel).parent == Path('cash-ledger') and Path(rel).suffix in ('.json', '.txt'):
                path = home / rel
                if path.suffix == '.json' and path.name in POLICIES:
                    add_policy_rows(json.loads(path.read_text()), rows)
                copy_file(path, payload / rel)
        state = json.loads((home / 'cash-ledger/monitor-state.json').read_text())
        require(str(state['chat_id']) == chat_id, 'Source chat and accounting cursor disagree')
        with closing(read_db(home / 'state.db')) as db, closing(read_db(payload / 'cash-ledger/reply-deliveries.db')) as receipts:
            # Some older clarification/report sources appear only in reply receipts.
            for receipt in receipts.execute('SELECT DISTINCT source_message_id FROM receipts'):
                rows.update(r[0] for r in db.execute('''SELECT m.id FROM messages m JOIN sessions s ON s.id=m.session_id
                    WHERE s.chat_id=? AND m.platform_message_id=? AND m.role='user' ''', (chat_id, str(receipt[0]))))
        high_water = filtered_state(home / 'state.db', payload / 'state.db', rows, chat_id, state['last_seen_message_rowid'])
        with closing(sqlite3.connect(payload / 'cash-ledger/native-inputs.db')) as native, closing(read_db(payload / 'state.db')) as evidence:
            keep = {str(r[0]) for r in evidence.execute('''SELECT m.platform_message_id FROM messages m
                JOIN sessions s ON s.id=m.session_id WHERE s.chat_id=?''', (chat_id,))}
            for rowid, source_chat, message_id in native.execute('SELECT rowid,chat_id,message_id FROM native_inputs').fetchall():
                if str(source_chat) != chat_id or str(message_id) not in keep:
                    native.execute('DELETE FROM native_inputs WHERE rowid=?', (rowid,))
            native.commit()
            native.execute('VACUUM')
        state['last_seen_message_rowid'] = high_water
        dump_json(payload / 'cash-ledger/monitor-state.json', state)
        config = yaml.safe_load((home / 'config.yaml').read_text())
        telegram = config['platforms']['telegram']
        require(set(telegram) <= set(TELEGRAM_KEYS) | {'enabled', 'channel_prompts'},
                'Unrecognized Telegram setting; review before export')
        dump_json(payload / 'telegram-settings.json', {key: telegram[key] for key in TELEGRAM_KEYS if key in telegram})
        dump_json(payload / 'accounting-settings.json', {
            'chat_id': chat_id, 'activation_required': True,
            'native_input': config.get('plugins', {}).get('entries', {}).get('accounting-native-input', {})})
        # A missing enabled list can grandfather installed plugins during Hermes config migration.
        dump_json(payload / 'config.yaml', {'platforms': {'telegram': {'enabled': False}},
                  'plugins': {'enabled': [], 'disabled': ['accounting-native-input']}})
        env = dotenv_values(home / '.env', interpolate=False)
        dump_json(payload / 'telegram-secrets.json', {key: env[key] for key in ENV_KEYS if key in env})
        for rel in relatives:
            if rel in RUNTIME_FILES or any(Path(rel).is_relative_to(safe_relative(a)) for a in artifacts):
                if (payload / rel).exists():
                    continue  # Core databases/policies were already filtered and reconciled.
                require(not rel.endswith(('-wal', '-shm')), 'Select a database, not its WAL or SHM')
                if rel.endswith('.db'):
                    copy_db(home / rel, payload / rel)
                else:
                    copy_file(home / rel, payload / rel)
        package = Path(__file__).resolve().parents[1]
        copy_file(Path(__file__).resolve(), payload / 'scripts/bablomat_portable.py')
        copy_file(package / 'PORTABILITY.md', payload / 'PORTABILITY.md')
        copy_file(package / 'skills/bablomat-accounting/SKILL.md', payload / 'skills/bablomat-accounting/SKILL.md')
        require(all(digest(path) == fingerprints[rel] for rel, path in sources.items())
                and all((home / (rel + '-wal')).exists() == (rel + '-wal' in sources)
                        for rel in sources if rel.endswith('.db')),
                'Offline snapshot changed during export')
        inventories = {str(f.relative_to(payload)): database_inventory(f) for f in payload.rglob('*.db')}
        manifest = {'format': FORMAT, 'chat_id': chat_id, 'source_high_water': high_water,
                    'original_cursor': json.loads((home / 'cash-ledger/monitor-state.json').read_text())['last_seen_message_rowid'],
                    'selected_source_rows': sorted(rows), 'artifacts': artifacts, 'databases': inventories,
                    'files': {str(f.relative_to(payload)): digest(f) for f in regular_files(payload)}}
        dump_json(stage / 'manifest.json', manifest)
        for directory in stage.rglob('*'):
            if directory.is_dir():
                directory.chmod(0o700)
        verify_bundle(stage)
        stage.rename(destination)
    return manifest


def verify_bundle(bundle):
    bundle = Path(bundle)
    files = regular_files(bundle)
    require({str(f.relative_to(bundle)).split('/')[0] for f in files} <= {'manifest.json', 'payload'}, 'Unexpected bundle file')
    manifest = json.loads((bundle / 'manifest.json').read_text())
    require(manifest['format'] == FORMAT, 'Unsupported bundle format')
    expected = manifest['files']
    for name in expected:
        safe_relative(name)
    payload = bundle / 'payload'
    require(set(expected) == {str(f.relative_to(payload)) for f in regular_files(payload)}, 'Bundle file inventory mismatch')
    require(all(digest(payload / name) == value for name, value in expected.items()), 'Bundle checksum mismatch')
    require(set(manifest['databases']) == {name for name in expected if name.endswith('.db')}, 'Database inventory mismatch')
    for name, inventory in manifest['databases'].items():
        require(database_inventory(payload / name) == inventory, 'Accounting row inventory mismatch')
    state = json.loads((payload / 'cash-ledger/monitor-state.json').read_text())
    require(state['last_seen_message_rowid'] == manifest['source_high_water'], 'Unsafe accounting cursor')
    with closing(read_db(payload / 'state.db')) as db:
        require(db.execute("SELECT seq FROM sqlite_sequence WHERE name='messages'").fetchone()[0] == manifest['source_high_water'],
                'Unsafe source ID allocation')
        require([r[0] for r in db.execute('SELECT id FROM messages ORDER BY id')] == manifest['selected_source_rows'], 'Source row inventory mismatch')
    return manifest


def import_bundle(bundle, destination):
    """Create a NEW offline profile; no merge, execution, transport or activation."""
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix='.bablomat-import-', dir=destination.parent) as temporary:
        stage = Path(temporary)
        # Verify the private copy that is actually installed, not mutable originals.
        for path in regular_files(Path(bundle)):
            copy_file(path, stage / path.relative_to(bundle))
        manifest = verify_bundle(stage)
        dump_json(stage / 'payload/IMPORT-RECEIPT.json', {
            'format': FORMAT, 'activated': False, 'source_high_water': manifest['source_high_water'],
            'databases': manifest['databases']})
        for directory in stage.rglob('*'):
            if directory.is_dir():
                directory.chmod(0o700)
        (stage / 'payload').rename(destination)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    export = commands.add_parser('export', help='Use a trusted, immutable offline profile snapshot only')
    export.add_argument('--home', required=True, type=Path)
    export.add_argument('--selection', required=True, type=Path)
    export.add_argument('--destination', required=True, type=Path)
    export.add_argument('--offline-snapshot', required=True, action='store_true', help='Acknowledge source is not a live profile')
    verify = commands.add_parser('verify')
    verify.add_argument('bundle', type=Path)
    restore = commands.add_parser('import', help='Prepare a new offline profile, never activate it')
    restore.add_argument('bundle', type=Path)
    restore.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.command == 'export':
            result = export_bundle(args.home, args.destination, args.selection)
        elif args.command == 'verify':
            result = verify_bundle(args.bundle)
        else:
            result = import_bundle(args.bundle, args.destination)
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError, yaml.YAMLError) as exc:
        detail = str(exc) if isinstance(exc, PortableError) else type(exc).__name__
        parser.exit(1, f'FAILED {args.command}: {detail}; no activation performed. Inspect inputs privately.\n')
    print(f"PASS {args.command}: {len(result['files'])} files; {len(result['selected_source_rows'])} source records; no activation")


if __name__ == '__main__':
    main()
