#!/usr/bin/env python3
"""Single-owner server capture/crypt round trip with receipt-scoped retention.

Fixed production paths. No installation, scheduling, restoration or cloud discovery.
Run only after authorizing this workflow; see docs/server-backup.md.
"""
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
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
REMOTE = 'hermes-backup:scheduled-v1/'
RCLONE_SHA = 'ed7ab1f17876bb006c3df3949a3044959671afd9112362dacaa5dd1647735bc1'
RUN_RE = re.compile(r'(\d{8}T\d{6}Z)-[0-9a-f]{32}')
RETENTION = 168 * 3600
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
        require(set(record) == {'run', 'created', 'bytes', 'sha256', 'cloud_deleted',
                                'bundle_integrity_verified', 'state_restored', 'restored_runtime_verified'}
                and record['run'] == run and type(record['created']) is int and record['created'] == created
                and type(record['bytes']) is int and record['bytes'] > 0
                and isinstance(record['sha256'], str) and re.fullmatch('[0-9a-f]{64}', record['sha256'])
                and type(record['cloud_deleted']) is bool
                and record['bundle_integrity_verified'] is True
                and record['state_restored'] is False and record['restored_runtime_verified'] is False,
                'invalid receipt; rotation refused')
        records.append(record)
    return records


def archive_name(run):
    stamp(run)
    return 'hermes-scheduled-' + run + '.tar.gz'


def rotation_candidates(records, current):
    """Only locally receipted successful copies; never infer ownership from a listing."""
    now = stamp(current)
    require(any(r['run'] == current and not r['cloud_deleted'] for r in records),
            'current verified receipt missing')
    require(all(r['created'] <= now for r in records), 'clock moved backwards; rotation refused')
    return [r for r in records if not r['cloud_deleted'] and r['created'] < now - RETENTION]


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

    def rclone(self, action, source, destination=None, recovery=False):
        command = [str(PACKAGE / 'rclone'), action, str(source)]
        if destination is not None:
            command.append(str(destination))
        command += ['--config', str(KEYS / ('recovery.conf' if recovery else 'upload.conf')),
                    '--retries', '1', '--low-level-retries', '3', '--contimeout', '30s',
                    '--timeout', '5m', '--stats', '5s', '--stats-log-level', 'NOTICE', '--use-json-log']
        if action in ('copy', 'copyto'):
            command += ['--immutable', '--size-only']
        phase(command, self.env, self.journal, action)

    def verify(self, path):
        phase([sys.executable, str(PACKAGE / 'hermes_backup_bundle.py'), 'verify', str(path), 'full'],
              self.env, self.journal, 'verify')

    def space(self):
        # Reuse the capture estimator, adding compressed original + readback and
        # verification scratch. All workflow files and capture staging must share a FS.
        import hermes_backup_bundle as bundle
        require(STATE.stat().st_dev == RUNTIME.stat().st_dev, 'state and runtime must share a filesystem')
        def inspect(args):
            result = subprocess.run(['docker', *args], env=self.env, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, timeout=60, check=True)
            return json.loads(result.stdout)[0]
        image = inspect(['image', 'inspect', inspect(['inspect', 'hermes'])['Image']])
        budget = bundle.require_space(RUNTIME, image)
        require(shutil.disk_usage(STATE).free >= 4 * budget + 1024**3,
                'insufficient space for server round trip')
        self.journal.emit('space_checked', required_bytes=4 * budget + 1024**3)

    def rotate(self, current):
        records = load_receipts(STATE)
        candidates = rotation_candidates(records, current)
        for record in candidates:
            # No remote enumeration, sync, purge, recursive delete, or unreceipted paths.
            self.rclone('deletefile', REMOTE + archive_name(record['run']))
            record['cloud_deleted'] = True
            atomic_json(STATE / 'receipts' / (record['run'] + '.json'), record)
            self.journal.emit('cloud_copy_expired')
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
        self.rclone('copy', upload, REMOTE)
        downloaded = directory / 'readback.tar.gz'
        self.rclone('copyto', REMOTE + source.name, downloaded, recovery=True)
        require(private(downloaded).st_size == source.stat().st_size and digest(downloaded) == checksum,
                'readback size or hash mismatch')
        self.verify(downloaded)
        self.source_ok()
        receipt = {'run': run, 'created': stamp(run), 'bytes': source.stat().st_size, 'sha256': checksum,
                   'cloud_deleted': False, 'bundle_integrity_verified': True,
                   'state_restored': False, 'restored_runtime_verified': False}
        atomic_json(STATE / 'receipts' / (run + '.json'), receipt)
        self.journal.emit('cloud_roundtrip_verified', bytes=receipt['bytes'])
        downloaded.unlink()  # Only this successful run's readback, never failed/unknown leftovers.
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
            for name in ('upload.conf', 'recovery.conf'):
                require(private(KEYS / name).st_size <= 65536, 'oversized config')
            require(read_config(KEYS / 'upload.conf') == read_config(KEYS / 'recovery.conf'),
                    'working and recovery configurations differ')
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
