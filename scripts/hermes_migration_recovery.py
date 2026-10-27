#!/usr/bin/env python3
"""Non-starting recovery staging primitive; NOT a migration-site-v2 adapter.

Trusted operator supplies capture identity and digest. No SSH, Docker, Telegram,
application execution, source recovery or admission-ready operation exists.
"""
import os
from pathlib import Path
import re
import shutil
import stat

import hermes_backup_bundle as bundle
from hermes_migration_controller import atomic_json, require
from hermes_migration_host import locked, private_directory, read_private

CONTRACT = 'processed-state-v1'


class RecoveryStage:
    def __init__(self, directory):
        self.directory = Path(directory)
        private_directory(self.directory)

    def stage(self, *, run_id, archive, archive_digest, container_id, image_id,
              continuity_contract):
        require(continuity_contract == CONTRACT, 'explicit processed-state continuity contract required')
        for value, pattern in ((run_id, '[0-9a-f]{32}'), (archive_digest, '[0-9a-f]{64}'),
                               (container_id, '[0-9a-f]{64}'), (image_id, 'sha256:[0-9a-f]{64}')):
            require(isinstance(value, str) and re.fullmatch(pattern, value), 'invalid recovery identity')
        binding = dict(version=1, run_id=run_id, operation_id=run_id + ':stage-recovery',
                       archive_digest=archive_digest, container_id=container_id,
                       image_id=image_id, continuity_contract=continuity_contract)
        directory = self.directory
        copied = directory / 'full.tar.gz'
        receipt_path = directory / 'receipt.json'
        expected = dict(binding, phase='STAGED', archive_verified=True, state_compared=True,
                        independent_copy_verified=False, runtime_started=False, ready=False)
        with locked(directory / 'operation.lock'):
            if receipt_path.exists():
                receipt = read_private(receipt_path)
                require(receipt == expected, 'different or invalid recovery receipt')
                require(read_private(directory / 'intent.json') == binding, 'recovery intent changed')
                self.compare(binding)
                return receipt
            require(set(p.name for p in directory.iterdir()) == {'operation.lock'},
                    'existing or interrupted recovery state requires review')
            atomic_json(directory / 'intent.json', binding)
            with Path(archive).open('rb') as source, copied.open('xb') as target:
                os.chmod(copied, 0o600)
                shutil.copyfileobj(source, target)
                target.flush()
                os.fsync(target.fileno())
            self.check(copied, binding)
            bundle.restore_state(copied, directory / 'restored')
            self.compare(binding)
            atomic_json(receipt_path, expected)
            return expected

    def check(self, archive, binding):
        info = archive.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and not info.st_mode & 0o077 and info.st_nlink == 1, 'unsafe custody archive')
        require(bundle.digest_file(archive)['sha256'] == binding['archive_digest'], 'archive digest mismatch')
        manifest = bundle.verify(archive, 'full')
        require(manifest.get('capture', {}).get('mode') == 'cold-stopped-v1', 'cold capture required')
        require(manifest['source']['container_id'] == binding['container_id']
                and manifest['image']['id'] == binding['image_id'], 'capture identity mismatch')
        return manifest

    def compare(self, binding):
        manifest = self.check(self.directory / 'full.tar.gz', binding)
        restored = self.directory / 'restored'
        private_directory(restored)
        private_directory(restored / '.recovery')
        state = restored / '.recovery/state.tar'
        require(bundle.digest_file(state) == manifest['payloads']['state.tar'], 'restored comparison payload changed')
        bundle.run(['tar', '--compare', '--file', str(state), '--directory', str(restored),
                    '--numeric-owner'], timeout=5400, reject_diagnostics=True)
