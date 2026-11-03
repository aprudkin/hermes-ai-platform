#!/usr/bin/env python3
"""Source-host Docker primitives, NOT a production migration-site-v2 adapter.

No preflight-ready or target start action exists. Source recovery is in-process
only, gated by a trusted current safety guard. Docker fencing is not an input
drain or a fence against systemd/Compose/admin recreation.
Run only from outside Hermes after independent authority and admission checks.
"""
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys

import hermes_backup_bundle as bundle
from hermes_migration_controller import Refused, atomic_json, require


def private_directory(path):
    require(path.is_absolute() and path == path.resolve(), 'unsafe directory path')
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and not info.st_mode & 0o077, 'unsafe private directory')


def read_private(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and not info.st_mode & 0o077 and info.st_size < 16 * 1024 * 1024,
                'unsafe operation record')
        return json.load(stream)


@contextlib.contextmanager
def locked(path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and not info.st_mode & 0o077, 'unsafe operation lock')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refused('host operation busy') from None
        yield fd
    finally:
        os.close(fd)


class HostOperations:
    def __init__(self, root, directory):
        self.root, self.directory = Path(root), Path(directory)
        private_directory(self.directory)
        require(self.root.is_absolute() and self.root == self.root.resolve()
                and self.root.is_dir(), 'invalid runtime root')
        require(not self.directory.is_relative_to(self.root), 'operation store must be outside runtime')
        self.path = self.directory / 'operation.json'
        self.anchor = self.root / '.hermes-migration-owner.json'
        self.lock_path = self.root / '.hermes-migration.lock'

    def record(self, run):
        require(isinstance(run, str) and re.fullmatch('[0-9a-f]{32}', run), 'invalid run')
        anchor = read_private(self.anchor)
        require(anchor == {'run_id': run, 'directory': str(self.directory)}, 'different host operation owner')
        value = read_private(self.path)
        require(value['run_id'] == run and value['root'] == str(self.root), 'different operation identity')
        return value

    def observe(self, record):
        current = bundle.inspect('container', 'hermes')
        original = read_private(self.directory / 'original.json')
        require(bundle.digest_file(self.directory / 'original.json')['sha256'] == record['original_sha256'],
                'original runtime receipt changed')
        require(current.get('Id') == original['Id'] and current.get('Image') == original['Image']
                and current.get('Config') == original['Config'] and current.get('Mounts') == original['Mounts'],
                'source identity or configuration changed')
        # Only RestartPolicy and State are changed by these primitives.
        host = dict(original['HostConfig'], RestartPolicy={'Name': 'no', 'MaximumRetryCount': 0})
        require(current['HostConfig'] in (original['HostConfig'], host), 'host configuration changed')
        if record['phase'] in ('FENCED', 'CAPTURED'):
            frozen = self.directory / 'frozen.json'
            require(bundle.digest_file(frozen)['sha256'] == record['frozen_sha256']
                    and current == read_private(frozen), 'source changed since original fence')
        return current

    def fence(self, run, before_effect=None):
        require(isinstance(run, str) and re.fullmatch('[0-9a-f]{32}', run), 'invalid run')
        with locked(self.lock_path), locked(self.root / '.hermes-backup.lock'):
            if not self.anchor.exists():
                require(not self.path.exists() and not (self.directory / 'original.json').exists(),
                        'unbound operation records require review')
                original = bundle.inspect('container', 'hermes')
                # This operation preserves the original container, not a
                # portable restore. capture-cold separately applies the strict
                # archive validator; never rewrite the saved inspection.
                bundle.validate_container(original, self.root, 'hermes', in_place=True)
                atomic_json(self.directory / 'original.json', original)
                record = {'version': 1, 'run_id': run, 'root': str(self.root), 'phase': 'FENCING',
                          'revoked': False,
                          'original_sha256': bundle.digest_file(self.directory / 'original.json')['sha256']}
                atomic_json(self.path, record)
                atomic_json(self.anchor, {'run_id': run, 'directory': str(self.directory)})
            record = self.record(run)
            require(not record['revoked'], 'operation revoked')
            current = self.observe(record)
            require(not current['State'].get('Paused'), 'paused source requires independent recovery')
            if current['HostConfig']['RestartPolicy'] != {'Name': 'no', 'MaximumRetryCount': 0}:
                if before_effect is not None:
                    before_effect()
                bundle.run(['docker', 'update', '--restart=no', current['Id']])
            current = self.observe(record)
            if current['State'].get('Running'):
                if before_effect is not None:
                    before_effect()
                bundle.run(['docker', 'stop', '--time', '60', current['Id']], timeout=90)
            current = self.observe(record)
            bundle.validate_cold_state(current)
            if record['phase'] == 'FENCING':
                atomic_json(self.directory / 'frozen.json', current)
                record['frozen_sha256'] = bundle.digest_file(self.directory / 'frozen.json')['sha256']
                record['phase'] = 'FENCED'
                atomic_json(self.path, record)
            return {'run_id': run, 'docker_fenced': True, 'all_writers_fenced': False,
                    'saved_states_digest': record['original_sha256']}

    def capture(self, run, before_effect=None):
        with locked(self.lock_path) as lease:
            record = self.record(run)
            require(not record['revoked'] and record['phase'] in ('FENCED', 'CAPTURED'),
                    'capture not admitted')
            bundle.validate_cold_state(self.observe(record))
            final = self.directory / 'full.tar.gz'
            receipt_path = self.directory / 'capture.json'
            if receipt_path.exists():
                receipt = read_private(receipt_path)
                require(bundle.digest_file(final)['sha256'] == receipt['archive_digest'], 'archive changed')
                bundle.verify(final, 'full')
                return receipt
            require(not final.exists(), 'unreceipted archive requires review')
            pending = self.directory / 'full.tar.gz.pending'
            helper = Path(bundle.__file__).resolve()
            guide = helper.parent.parent / 'docs/backup-restore.md'
            source = helper.read_text()
            program = ('RESTORE_GUIDE = ' + repr(guide.read_text()) + '\nBUNDLE_SOURCE = '
                       + repr(source) + '\n' + source).encode()
            # O_EXCL: interrupted output is retained and cannot become a success.
            if before_effect is not None:
                before_effect()
            fd = os.open(pending, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as output:
                child = subprocess.Popen([sys.executable, '-', 'capture-cold', str(self.root), 'hermes'],
                                         stdin=subprocess.PIPE, stdout=output, stderr=subprocess.PIPE,
                                         start_new_session=True, pass_fds=(lease,))
                try:
                    child.communicate(program, timeout=5500)
                    require(child.returncode == 0, 'cold capture failed; pending bytes retained')
                finally:
                    if child.poll() is None:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait()
                output.flush()
                os.fsync(output.fileno())
            manifest = bundle.verify(pending, 'full')
            require(manifest.get('capture', {}).get('mode') == 'cold-stopped-v1', 'not a cold bundle')
            current = self.observe(record)
            bundle.validate_cold_state(current)
            require(manifest['source']['root'] == str(self.root)
                    and manifest['source']['container_id'] == current['Id']
                    and manifest['image']['id'] == current['Image'], 'capture differs from fenced source')
            receipt = {'run_id': run, 'verified': True, 'independent_copy_verified': False,
                       'archive_format': 'tar.gz', 'archive_digest': bundle.digest_file(pending)['sha256'],
                       'image_id': manifest['image']['id'], 'container_id': manifest['source']['container_id']}
            os.link(pending, final)  # exclusive publication, never replace an accepted archive
            pending.unlink()
            atomic_json(receipt_path, receipt)  # also fsyncs directory containing final
            record['phase'] = 'CAPTURED'
            atomic_json(self.path, record)
            return receipt

    def recover(self, run, guard):
        """Restore this container only under a trusted, continuously held site fence.

        The caller holds the site-wide recovery lease across this entire method.
        guard() must freshly verify persistent target fencing, remote revocation,
        no target activity and CURRENT cancellations/effect reconciliation. It is
        trusted adapter code, never user JSON or a stored proof substituted for a
        probe. This primitive cannot supply those production proofs itself.
        """
        with locked(self.lock_path), locked(self.root / '.hermes-backup.lock'):
            record = self.record(run)
            current = self.observe(record)
            original = read_private(self.directory / 'original.json')

            def check():
                proof = guard()
                require(isinstance(proof, dict) and proof.get('run_id') == run
                        and all(proof.get(k) is True for k in (
                            'target_fenced', 'persistent_fence', 'outstanding_operations_revoked',
                            'no_target_activity_verified', 'safe_to_resume',
                            'cancelled_jobs_preserved', 'replay_reviewed'))
                        and isinstance(proof.get('reconciliation_digest'), str)
                        and re.fullmatch('[0-9a-f]{64}', proof['reconciliation_digest']),
                        'current recovery safety evidence missing')
                return proof

            check()
            require(record['phase'] in ('FENCING', 'FENCED', 'CAPTURED', 'RECOVERING', 'RECOVERED'),
                    'unsupported source recovery phase')
            record['revoked'] = True
            if record['phase'] not in ('RECOVERING', 'RECOVERED'):
                record.update(phase='RECOVERING', recovery_step='ADMITTED',
                              recovery_operation_id=run + ':source_recover')
                atomic_json(self.path, record)
            require(record.get('recovery_operation_id') == run + ':source_recover',
                    'source recovery identity changed')
            if record['phase'] == 'RECOVERED':
                require(current['State'].get('Running') is True
                        and current['HostConfig'] == original['HostConfig'], 'recovered source changed')
                expected = dict(run_id=run, running=True, safe_to_resume=True,
                                cancelled_jobs_preserved=True, replay_reviewed=True,
                                saved_states_digest=record['original_sha256'],
                                reconciliation_digest=record['recovery_evidence']['reconciliation_digest'])
                require(read_private(self.directory / 'recovery.json') == expected,
                        'source recovery receipt changed')
            require(not current['State'].get('Paused') and not current['State'].get('Restarting')
                    and not current['State'].get('Dead'), 'source state requires manual review')
            if not current['State'].get('Running'):
                require(record['recovery_step'] == 'ADMITTED',
                        'uncertain source start; reconcile without replay')
                proof = check()
                record.update(recovery_step='START_INTENT', recovery_evidence=proof)
                atomic_json(self.path, record)
                bundle.run(['docker', 'start', current['Id']])
                current = self.observe(record)
            require(current['State'].get('Running') is True, 'source start not observed')
            if current['HostConfig']['RestartPolicy'] != original['HostConfig']['RestartPolicy']:
                proof = check()
                policy = original['HostConfig']['RestartPolicy']
                name, count = policy['Name'], policy['MaximumRetryCount']
                require(name in ('no', 'always', 'unless-stopped', 'on-failure')
                        and type(count) is int and count >= 0, 'unsupported original restart policy')
                setting = name + (':' + str(count) if name == 'on-failure' and count else '')
                record.update(recovery_step='POLICY_INTENT', recovery_evidence=proof)
                atomic_json(self.path, record)
                bundle.run(['docker', 'update', '--restart=' + setting, current['Id']])
            current = self.observe(record)
            proof = check()
            require(current['State'].get('Running') is True
                    and current['HostConfig'] == original['HostConfig'], 'source recovery readback failed')
            receipt = dict(run_id=run, running=True, safe_to_resume=True,
                           cancelled_jobs_preserved=True, replay_reviewed=True,
                           saved_states_digest=record['original_sha256'],
                           reconciliation_digest=proof['reconciliation_digest'])
            atomic_json(self.directory / 'recovery.json', receipt)
            record.update(phase='RECOVERED', recovery_step='DONE', recovery_evidence=proof)
            atomic_json(self.path, record)
            return receipt

    def revoke(self, run):
        # The inherited host lock keeps revoke from racing an orphan capture.
        with locked(self.lock_path):
            record = self.record(run)
            record['revoked'] = True
            atomic_json(self.path, record)
            bundle.validate_cold_state(self.observe(record))
            return {'run_id': run, 'revoked': True, 'docker_fenced': True,
                    'source_resumed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('fence', 'capture', 'revoke'))
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--state-dir', required=True, type=Path)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    try:
        require(args.execute, 'explicit --execute required; this is not a preflight')
        value = getattr(HostOperations(args.root, args.state_dir), args.action)(args.run_id)
        print(json.dumps(value, sort_keys=True))
        return 0
    except (Refused, bundle.BundleError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('host operation refused or incomplete; inspect private receipts; source NOT resumed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
