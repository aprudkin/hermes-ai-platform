#!/usr/bin/env python3
"""Single-owner encrypted daily upload with metadata-only readback and scoped retention.

Fixed production paths. No installation, scheduling, restoration or cloud discovery.
Run only after authorizing this workflow; see docs/server-backup.md.
"""
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid

from hermes_cloud_backup import CloudError, digest, read_config, require

PACKAGE = Path('/usr/local/lib/hermes-backup')
STATE = Path('/var/lib/hermes-backup')
KEYS = Path('/etc/hermes-backup')
LOGS = Path('/var/log/hermes-backup')
RUNTIME = Path('/opt/hermes')
REMOTE = 'hermes-backup:'
LEGACY_REMOTE = 'hermes-backup:scheduled-v1/'
CRYPT_ROOT = 'mailru-hermes:Backup/Hermes'
RCLONE_SHA = 'ed7ab1f17876bb006c3df3949a3044959671afd9112362dacaa5dd1647735bc1'
RUN_RE = re.compile(r'(\d{8}T\d{6}Z)-[0-9a-f]{32}')
RETENTION_DAYS = 3
LOG_AGE = 30 * 86400
LOG_TOTAL = 100 * 1024 * 1024
LOG_FILE = 1024 * 1024
STAGES = {
    'Checking runtime, capture lock and available space',
    'Saving Docker image on source (container not paused by this capture)',
    'Pausing source for the state snapshot',
    'Snapshotting state on source (pause confirmed)',
    'Unpausing source after snapshot',
    'Source unpause confirmed; hashing snapshot and image payloads',
    'Compressing and transmitting archive; source is no longer paused by this capture',
    'Archive stream sent; controller integrity verification still required',
}


def private(path, directory=False):
    info = path.lstat()
    require(info.st_uid == os.getuid() and not info.st_mode & 0o077
            and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)),
            'unsafe private workflow path')
    return info


def trusted_tree(path):
    """Reject symlink ancestors and untrusted writable parents, including /tmp."""
    require(path.is_absolute(), 'absolute workflow path required')
    for part in (path, *path.parents):
        info = part.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and not info.st_mode & 0o022, 'unsafe workflow directory ancestry')


def stamp(run):
    require(isinstance(run, str) and RUN_RE.fullmatch(run), 'invalid run identity')
    return int(dt.datetime.strptime(run[:16], '%Y%m%dT%H%M%SZ').replace(tzinfo=dt.timezone.utc).timestamp())


def atomic_json(path, value):
    # A crash may leave the staging file behind. Never reuse or overwrite it.
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.new')
    with temporary.open('x') as stream:
        json.dump(value, stream, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def load_receipts(state):
    records = []
    for path in sorted((state / 'receipts').iterdir()):
        if re.fullmatch(RUN_RE.pattern + r'\.json(?:\.[0-9a-f]{32})?\.new', path.name):
            # Only a completed atomic rename makes a receipt authoritative. Keep
            # interrupted private staging files as evidence, never rotate from them.
            stamp(path.name.split('.', 1)[0])
            require(private(path).st_size < 8192, 'oversized pending receipt')
            continue
        require(path.suffix == '.json', 'unexpected receipt entry; inspect before retry')
        run = path.stem
        created = stamp(run)
        require(private(path).st_size < 8192, 'oversized receipt')
        record = json.loads(path.read_text())
        extra = {'cloud_layout', 'cloud_metadata_checked', 'cloud_roundtrip_verified'} if 'cloud_layout' in record else set()
        if record.get('cloud_layout') == 'dated-v2':
            extra.add('cloud_directory')
        if 'cloud_removed_externally' in record:
            extra.add('cloud_removed_externally')
        require(('cloud_layout' not in record or (record['cloud_layout'] in ('dated-v1', 'dated-v2')
                and record.get('cloud_metadata_checked') is True and record.get('cloud_roundtrip_verified') is False))
                and ('cloud_removed_externally' not in record or record['cloud_removed_externally'] is True)
                and set(record) == {'run', 'created', 'bytes', 'sha256', 'cloud_deleted',
                                'bundle_integrity_verified', 'state_restored', 'restored_runtime_verified'} | extra
                and record['run'] == run and type(record['created']) is int and record['created'] == created
                and type(record['bytes']) is int and record['bytes'] > 0
                and isinstance(record['sha256'], str) and re.fullmatch('[0-9a-f]{64}', record['sha256'])
                and type(record['cloud_deleted']) is bool
                and record['bundle_integrity_verified'] is True
                and record['state_restored'] is False and record['restored_runtime_verified'] is False,
                'invalid receipt; rotation refused')
        if record.get('cloud_layout') == 'dated-v2':
            record_directory(record)
        records.append(record)
    return records


def archive_name(run):
    stamp(run)
    return 'hermes-scheduled-' + run + '.tar.gz'


def date_directory(run):
    date = dt.datetime.fromtimestamp(stamp(run), ZoneInfo('Europe/Moscow'))
    return f'{date.year % 100:02d}-{date.month}-{date.day}'


def record_directory(record):
    base = date_directory(record['run'])
    if record.get('cloud_layout') == 'dated-v1':
        return base
    directory = record.get('cloud_directory')
    require(record.get('cloud_layout') == 'dated-v2' and isinstance(directory, str)
            and re.fullmatch(re.escape(base) + r'(?:-(?:[2-9]|[1-9][0-9]+))?', directory),
            'invalid receipt cloud directory')
    return directory


def record_remote(record):
    prefix = REMOTE + record_directory(record) + '/' if record.get('cloud_layout') in ('dated-v1', 'dated-v2') else LEGACY_REMOTE
    return prefix + archive_name(record['run'])


def rotation_candidates(records, current):
    """Only locally receipted successful copies; never infer ownership from a listing."""
    now = stamp(current)
    timezone = ZoneInfo('Europe/Moscow')
    cutoff = dt.datetime.fromtimestamp(now, timezone).date() - dt.timedelta(days=RETENTION_DAYS - 1)
    require(any(r['run'] == current and not r['cloud_deleted'] for r in records),
            'current verified receipt missing')
    require(all(r['created'] <= now for r in records), 'clock moved backwards; rotation refused')
    return [r for r in records if not r['cloud_deleted'] and not r.get('cloud_removed_externally')
            and dt.datetime.fromtimestamp(r['created'], timezone).date() < cutoff]


class Journal:
    def __init__(self, root, run, now):
        self.root, self.run = root, run
        self.started = time.monotonic()
        candidates = []
        for path in root.iterdir():
            if path.suffix != '.jsonl' or not RUN_RE.fullmatch(path.stem):
                continue  # Never remove unknown/operator files.
            info = private(path)
            created = stamp(path.stem)
            require(created <= now, 'future journal; check clock before starting')
            if created < now - LOG_AGE:
                path.unlink()
            else:
                candidates.append((created, path, info.st_size))
        total = sum(item[2] for item in candidates)
        for _, path, size in sorted(candidates):
            if total <= LOG_TOTAL - LOG_FILE:
                break
            path.unlink()
            total -= size
        self.path = root / (run + '.jsonl')
        self.stream = self.path.open('x')
        self.stream.close()

    def emit(self, event, **numbers):
        # Callers supply fixed event names and numeric fields only. No raw diagnostics.
        require(all(type(v) in (int, float, bool) for v in numbers.values()), 'unsafe log field')
        line = json.dumps({'event': event, 'utc': int(time.time()),
                           'elapsed_seconds': round(time.monotonic() - self.started, 3), **numbers}) + '\n'
        if self.path.stat().st_size + len(line.encode()) > LOG_FILE:
            # Keep the newest safe events, including the terminal result, within a strict cap.
            data = self.path.read_bytes()[-LOG_FILE // 2:]
            data = data.split(b'\n', 1)[-1]
            with self.path.open('wb') as stream:
                stream.write(data)
        with self.path.open('a') as stream:
            stream.write(line)
            stream.flush()


def safe_progress(line, journal):
    """Only allowlisted capture stages or numeric rclone statistics leave the pipe."""
    match = re.fullmatch(r'\[source elapsed \d+:\d{2}:\d{2} \| previous stage \d+:\d{2}:\d{2}\] (.+)', line)
    if match and match[1] in STAGES:
        journal.emit(match[1])
        return
    try:
        value = json.loads(line).get('stats', {})
        count, speed = value.get('bytes'), value.get('speed')
        if all(type(x) in (int, float) and 0 <= x < 10**18 for x in (count, speed)):
            journal.emit('transfer_progress', bytes=count, bytes_per_second=speed)
    except (ValueError, TypeError, AttributeError):
        pass


def phase(command, env, journal, label, output=None, monitored=None, timeout=5400):
    journal.emit(label + '_start')
    started = time.monotonic()
    child = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                             stdout=output if output is not None else subprocess.DEVNULL,
                             stderr=subprocess.PIPE, start_new_session=True)
    pending = b''
    selector = selectors.DefaultSelector()
    selector.register(child.stderr, selectors.EVENT_READ)
    next_report = started + 5
    try:
        while child.poll() is None or selector.get_map():
            require(time.monotonic() - started < timeout, 'phase timed out')
            for key, _ in selector.select(timeout=0.2):
                chunk = os.read(key.fd, 8192)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                pending += chunk
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    if len(line) <= 16384:
                        safe_progress(line.decode('utf-8', errors='replace'), journal)
                if len(pending) > 16384:
                    pending = b''
            if monitored is not None and time.monotonic() >= next_report:
                journal.emit(label + '_progress', bytes=monitored.stat().st_size)
                next_report = time.monotonic() + 5
        code = child.wait()
        journal.emit(label + '_exit', code=code, seconds=round(time.monotonic() - started, 3))
        require(code == 0, 'phase failed; raw diagnostics suppressed')
    finally:
        if child.poll() is None:
            handlers = {sig: signal.signal(sig, signal.SIG_IGN)
                        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
            try:
                child.terminate()  # Capture gets its bounded owned-unpause cleanup first.
                try:
                    child.wait(timeout=180)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
                    journal.emit('forced_stop_source_state_requires_inspection')
            finally:
                for sig, handler in handlers.items():
                    signal.signal(sig, handler)
        selector.close()
        child.stderr.close()


class Workflow:
    def __init__(self, journal, env):
        self.journal, self.env = journal, env

    def source_ok(self):
        result = subprocess.run(['docker', 'inspect', '--format', '{{.State.Running}} {{.State.Paused}}', 'hermes'],
                                env=self.env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30)
        require(result.returncode == 0 and result.stdout.strip() == b'true false',
                'source not confirmed running and unpaused')
        self.journal.emit('source_running_unpaused')

    def rclone(self, action, source, destination=None, legacy=False):
        command = [str(PACKAGE / 'rclone'), action, str(source)]
        if destination is not None:
            command.append(str(destination))
        command += ['--config', str(KEYS / ('upload.conf' if legacy else 'daily-upload.conf')),
                    '--retries', '1', '--low-level-retries', '3', '--contimeout', '30s',
                    '--timeout', '5m', '--stats', '5s', '--stats-log-level', 'NOTICE', '--use-json-log']
        if action in ('copy', 'copyto'):
            command += ['--immutable', '--size-only']
        phase(command, self.env, self.journal, action)

    def metadata(self, remote, expected_bytes, absent=False):
        result = subprocess.run([str(PACKAGE / 'rclone'), 'lsjson', remote, '--stat',
                                 '--config', str(KEYS / 'daily-recovery.conf'), '--retries', '1',
                                 '--low-level-retries', '3', '--contimeout', '30s', '--timeout', '5m'],
                                env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=360)
        if absent:
            require(result.returncode in (3, 4), 'remote archive already exists or absence unconfirmed')
            return
        require(result.returncode == 0 and len(result.stdout) < 8192, 'cloud metadata unavailable')
        value = json.loads(result.stdout)
        require(value.get('IsDir') is False and value.get('Name') == remote.rsplit('/', 1)[-1]
                and type(value.get('Size')) is int and value['Size'] == expected_bytes,
                'cloud metadata size or name mismatch')
        self.journal.emit('cloud_metadata_checked', bytes=expected_bytes)

    def verify(self, path):
        phase([sys.executable, str(PACKAGE / 'hermes_backup_bundle.py'), 'verify', str(path), 'full'],
              self.env, self.journal, 'verify')

    def allocate_directory(self, run):
        # main holds the stable workflow flock throughout allocation and upload.
        # Existence is occupancy even for empty/unknown/failed-upload directories.
        base = date_directory(run)
        number = 1
        while True:
            directory = base if number == 1 else base + '-' + str(number)
            result = subprocess.run([str(PACKAGE / 'rclone'), 'lsjson', REMOTE + directory, '--stat',
                                     '--config', str(KEYS / 'daily-recovery.conf'), '--retries', '1',
                                     '--low-level-retries', '3', '--contimeout', '30s', '--timeout', '5m'],
                                    env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, timeout=360)
            if result.returncode in (3, 4):
                return directory
            require(result.returncode == 0 and len(result.stdout) < 8192, 'directory absence unconfirmed')
            value = json.loads(result.stdout)
            # A directory stat is rooted at the exact requested directory;
            # rclone crypt reports Name/Path as empty strings for that root.
            require(isinstance(value, dict) and type(value.get('IsDir')) is bool
                    and (value.get('Name') == directory or
                         (value['IsDir'] and value.get('Name') == '' and value.get('Path') == '')),
                    'invalid directory metadata')
            number += 1

    def remove_empty_date(self, record):
        remote = REMOTE + record_directory(record)
        result = subprocess.run([str(PACKAGE / 'rclone'), 'lsjson', remote,
                                 '--config', str(KEYS / 'daily-recovery.conf'), '--retries', '1',
                                 '--low-level-retries', '3', '--contimeout', '30s', '--timeout', '5m'],
                                env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=360)
        if result.returncode in (3, 4):
            return
        require(result.returncode == 0 and len(result.stdout) < 1024 * 1024, 'date metadata unavailable')
        entries = json.loads(result.stdout)
        require(isinstance(entries, list), 'invalid date metadata')
        if not entries:
            self.rclone('rmdir', remote)  # Nonrecursive; refuses a concurrent/unknown object.
            self.journal.emit('empty_date_removed')

    def space(self):
        # Capture, original and local verifier scratch; no downloaded archive.
        import hermes_backup_bundle as bundle
        require(STATE.stat().st_dev == RUNTIME.stat().st_dev, 'state and runtime must share a filesystem')
        def inspect(args):
            result = subprocess.run(['docker', *args], env=self.env, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, timeout=60, check=True)
            return json.loads(result.stdout)[0]
        image = inspect(['image', 'inspect', inspect(['inspect', 'hermes'])['Image']])
        budget = bundle.require_space(RUNTIME, image)
        require(shutil.disk_usage(STATE).free >= 3 * budget + 1024**3,
                'insufficient space for server backup')
        self.journal.emit('space_checked', required_bytes=3 * budget + 1024**3)

    def rotate(self, current):
        records = load_receipts(STATE)
        candidates = rotation_candidates(records, current)
        for record in candidates:
            # No remote enumeration, sync, purge, recursive delete, or unreceipted paths.
            self.rclone('deletefile', record_remote(record), legacy=record.get('cloud_layout') not in ('dated-v1', 'dated-v2'))
            record['cloud_deleted'] = True
            atomic_json(STATE / 'receipts' / (record['run'] + '.json'), record)
            self.journal.emit('cloud_copy_expired')
        expired_dates = {record_directory(r): r for r in records
                         if r.get('cloud_layout') in ('dated-v1', 'dated-v2') and r['cloud_deleted']}
        for day, record in expired_dates.items():
            if not any(r.get('cloud_layout') in ('dated-v1', 'dated-v2') and record_directory(r) == day
                       and not r['cloud_deleted'] for r in records):
                self.remove_empty_date(record)
        for record in records:
            if record['run'] == current:
                continue
            directory = STATE / 'runs' / record['run']
            path = directory / 'upload' / archive_name(record['run'])
            if not directory.exists():
                continue
            private(directory, True)
            private(directory / 'upload', True)
            if not path.exists() and not path.is_symlink():
                continue
            require(private(path).st_size == record['bytes'] and digest(path) == record['sha256'],
                    'previous original changed; cleanup refused')
            path.unlink()
            self.journal.emit('previous_local_original_removed')

    def execute(self, run):
        records = load_receipts(STATE)
        require(all(r['created'] <= stamp(run) for r in records), 'clock moved backwards')
        self.source_ok()
        self.space()
        directory = STATE / 'runs' / run
        directory.mkdir(mode=0o700)  # Never reuse an interrupted run.
        upload = directory / 'upload'
        upload.mkdir(mode=0o700)
        scratch = directory / 'scratch'
        scratch.mkdir(mode=0o700)
        self.env['TMPDIR'] = str(scratch)
        partial = upload / (archive_name(run) + '.part')
        with partial.open('xb') as stream:
            phase([sys.executable, str(PACKAGE / 'capture.py'), 'capture', str(RUNTIME), 'hermes'],
                  self.env, self.journal, 'capture', output=stream, monitored=partial, timeout=7200)
            stream.flush()
            os.fsync(stream.fileno())
        self.source_ok()
        self.verify(partial)
        checksum = digest(partial)
        source = upload / archive_name(run)
        partial.rename(source)
        require(list(upload.iterdir()) == [source], 'upload directory must contain only the archive')
        cloud_directory = self.allocate_directory(run)
        destination = REMOTE + cloud_directory + '/'
        atomic_json(directory / 'cloud-target.json', {'run': run, 'cloud_directory': cloud_directory})
        self.metadata(destination + source.name, source.stat().st_size, absent=True)
        self.rclone('copy', upload, destination)
        self.metadata(destination + source.name, source.stat().st_size)
        self.source_ok()
        receipt = {'run': run, 'created': stamp(run), 'bytes': source.stat().st_size, 'sha256': checksum,
                   'cloud_deleted': False, 'bundle_integrity_verified': True,
                   'cloud_layout': 'dated-v2', 'cloud_directory': cloud_directory,
                   'cloud_metadata_checked': True, 'cloud_roundtrip_verified': False,
                   'state_restored': False, 'restored_runtime_verified': False}
        atomic_json(STATE / 'receipts' / (run + '.json'), receipt)
        self.journal.emit('encrypted_upload_metadata_checked', bytes=receipt['bytes'])
        self.rotate(run)
        self.source_ok()
        self.journal.emit('success')


def stop(_signal, _frame):
    raise CloudError('interrupted')


def main():
    if sys.argv[1:] == ['--help']:
        print('Server full capture, Mail.ru crypt verification and scoped retention.\n'
              'Requires root and --confirm-external-mutation. See docs/server-backup.md.')
        return 0
    journal = None
    os.umask(0o077)
    try:
        require(sys.argv[1:] == ['--confirm-external-mutation'] and os.getuid() == 0,
                'root and explicit external-mutation confirmation required')
        for path in (PACKAGE, STATE, KEYS, LOGS, STATE / 'runs', STATE / 'receipts'):
            trusted_tree(path)
            private(path, True)
        lock_fd = os.open(STATE / 'workflow.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(lock_fd, 'r+b') as lock:
            private(STATE / 'workflow.lock')
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Root controls package/config updates; do not replace either while running.
            require(digest(PACKAGE / 'rclone') == RCLONE_SHA, 'unexpected rclone binary')
            for name in ('upload.conf', 'recovery.conf', 'daily-upload.conf', 'daily-recovery.conf'):
                require(private(KEYS / name).st_size <= 65536, 'oversized config')
            require(read_config(KEYS / 'upload.conf') == read_config(KEYS / 'recovery.conf'),
                    'working and recovery configurations differ')
            daily = read_config(KEYS / 'daily-upload.conf', CRYPT_ROOT, 'false')
            require(daily == read_config(KEYS / 'daily-recovery.conf', CRYPT_ROOT, 'false'),
                    'daily working and recovery configurations differ')
            old = read_config(KEYS / 'upload.conf')
            require(daily[1] == old[1] and all(daily[0][k] == old[0][k]
                    for k in ('type', 'filename_encryption', 'password', 'password2')),
                    'daily encryption or transport changed')
            now = int(time.time())
            run = dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex
            journal = Journal(LOGS, run, now)
            for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                signal.signal(sig, stop)
            # Whitelisted environment: no inherited rclone/TLS/Python/credential overrides.
            env = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                   'HOME': '/root', 'LANG': 'C.UTF-8'}
            Workflow(journal, env).execute(run)
        return 0
    except (Exception, KeyboardInterrupt):
        if journal is not None:
            try:
                journal.emit('failure_inspect_retained_state_before_retry')
            except OSError:
                pass
        print('Server backup failed; inspect safe journal and actual source state. '
              'No retry/restore or deletion of unknown leftovers performed.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
