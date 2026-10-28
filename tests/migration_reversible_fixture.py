"""TEST ONLY: filesystem model of two hosts, never production readiness proof.

The second custody directory is byte-independent, NOT a different real failure
 domain. Its failure-domain flag is a modeled premise, explicitly scoped synthetic.
Docker is the test's subprocess fixture; HTTP is loopback, not Telegram.
"""
import contextlib
import os
import shutil
import sqlite3
import time
from hermes_migration_controller import atomic_json, require
from hermes_migration_host import locked, read_private
import hermes_backup_bundle as bundle


class SyntheticAuthority:
    def __init__(self, test):
        self.test = test
        self.directory = test.base / 'synthetic-authority'
        self.directory.mkdir(mode=0o700)
        self.path = self.directory / 'state.json'
        self.profile = test.root / 'data/profiles/manager'
        (self.profile / 'jobs.json').write_text('{"cancelled-job":{"enabled":false}}\n')
        (self.profile / 'effects.json').write_text('{"effect":"uncertain","replay":false}\n')
        (self.profile / 'result.txt').write_text('completed synthetic result\n')
        (self.profile / 'MEMORY.md').write_text('retained synthetic memory\n')
        (self.profile / 'config.yaml').write_text('synthetic_setting: retained\n')
        (self.profile / 'SOUL.md').write_text('synthetic manager identity\n')
        with contextlib.closing(sqlite3.connect(self.profile / 'state.db')) as db, db:
            db.execute('create table messages(id integer primary key, content text)')
            db.execute('insert into messages values(1, ?)', ('processed synthetic conversation',))
        self.processed = {name: (self.profile / name).read_bytes() for name in
                          ('state.db', 'MEMORY.md', 'SOUL.md', 'config.yaml', 'result.txt',
                           'jobs.json', 'effects.json')}
        self.policy = {name: bundle.digest_file(self.profile / name)['sha256']
                       for name in ('jobs.json', 'effects.json')}

    def bind(self, run):
        atomic_json(self.path, dict(run_id=run, target_running=False, target_fenced=False,
                                   target_activity=False, revoked=False, source_fenced=False,
                                   operations={}, policy=self.policy, scope='synthetic-only'))

    def current(self):
        return read_private(self.path)

    def save(self, **changes):
        value = self.current()
        value.update(changes)
        atomic_json(self.path, value)

    @contextlib.contextmanager
    def hold(self, request):
        with locked(self.directory / 'site.lock'):
            state = self.current()
            require(state['run_id'] == request['run_id'], 'wrong fixture run')
            if 'effect_expires_at' in request:
                require(not state['revoked'] and time.time() < request['effect_expires_at'], 'fixture lease expired/revoked')
                operation = request['operation_id']
                expiry = state['operations'].setdefault(operation, request['effect_expires_at'])
                require(expiry == request['effect_expires_at'], 'fixture deadline renewed')
                atomic_json(self.path, state)
            yield

    def preflight(self, request):
        # Only simulated admission. No production host/auth/clock/custody claim.
        return dict(run_id=request['run_id'], ready=True, contract='migration-site-v2', evidence_scope='synthetic-only')

    def forward_guard(self, request):
        state = self.current()
        require(not state['revoked'] and not state.get('expired')
                and time.time() < request['effect_expires_at']
                and state['operations'][request['operation_id']] == request['effect_expires_at'],
                'fixture effect lease expired/revoked')

    def source_quiesce(self, request):
        self.save(source_fenced=True)

    def source_probe(self, request):
        fenced = self.current()['source_fenced']
        return dict(run_id=request['run_id'], fenced=fenced, writers_stopped=fenced)

    def independent_copy(self, request, archive, staged):
        destination = self.directory / 'modeled-other-host.tar.gz'
        if not destination.exists():
            with archive.open('rb') as source, destination.open('xb') as target:
                os.chmod(destination, 0o600)
                shutil.copyfileobj(source, target)
                target.flush()
                os.fsync(target.fileno())
        digest = bundle.digest_file(destination)['sha256']
        require(digest == staged['archive_digest'], 'fixture custody changed')
        bundle.verify(destination, 'full')
        return dict(run_id=request['run_id'], archive_digest=digest, verified=True,
                    independent_copy_verified=True, evidence_scope='synthetic-only')

    def target_fence(self, request):
        # The persistent fixture fence disallows every modeled target start;
        # no_target_activity comes from the durable lifetime ledger, not stop.
        self.save(target_running=False, target_fenced=True, revoked=True)
        return self.target_probe(request)

    def target_probe(self, request):
        value = self.current()
        require(not value.get('unreachable'), 'fixture target unreachable')
        return dict(run_id=request['run_id'], running=value['target_running'],
                    fenced=value['target_fenced'], writers_stopped=value['target_fenced'],
                    no_target_activity_verified=not value['target_activity'])

    def recovery_guard(self, request):
        value = self.current()
        probe = self.target_probe(request)
        policy = {name: bundle.digest_file(self.profile / name)['sha256']
                  for name in ('jobs.json', 'effects.json')}
        require(policy == value['policy'], 'current cancellation/effect reconciliation required')
        return dict(run_id=request['run_id'], target_fenced=probe['fenced'] and not probe['running'],
                    persistent_fence=value['target_fenced'], outstanding_operations_revoked=value['revoked'],
                    no_target_activity_verified=not value['target_activity'],
                    safe_to_resume=True, cancelled_jobs_preserved=True, replay_reviewed=True,
                    reconciliation_digest=bundle.digest_file(self.path)['sha256'])
