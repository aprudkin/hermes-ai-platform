#!/usr/bin/env python3
"""Pre-cutover composition, not an installable production migration-site-v2 site.

There is NO bundled production authority, admission, independent transport,
approval receiver or target-start path. The trusted authority must implement the
site-wide lease, all-writer fences, nonrenewable remote expiry/revocation, fresh
proofs and current policy reconciliation. Never use tests' synthetic authority
on real hosts. See docs/migration-reversible.md for this deliberately narrow port.
"""
from hermes_migration_controller import Refused, require
from hermes_migration_recovery import CONTRACT
import hermes_backup_bundle as bundle


class PreparationSite:
    def __init__(self, host, stage, sender, authority=None):
        self.host, self.stage, self.sender, self.authority = host, stage, sender, authority

    def call(self, action, request):
        try:
            return self.dispatch(action, request)
        except (bundle.BundleError, OSError, ValueError, KeyError, TypeError):
            # Preserve controller/primitive intent; expose no private diagnostics.
            raise Refused('preparation operation incomplete; retained for recovery') from None

    def dispatch(self, action, request):
        run = request['run_id']
        require(request.get('operation_id') == run + ':' + action, 'operation identity mismatch')
        if self.authority is None:
            if action == 'preflight':
                return dict(run_id=run, ready=False, contract='migration-site-v2')
            raise Refused('production safety authority is not implemented')
        # The authority owns a site-wide lease across every primitive, not just
        # a stale JSON proof. It must enforce expiry AT effects on remote hosts.
        with self.authority.hold(request):
            if action == 'preflight':
                return self.authority.preflight(request)
            if action == 'source_fence':
                self.authority.source_quiesce(request)
                receipt = self.host.fence(run, lambda: self.authority.forward_guard(request))
                self.source_probe(request)
                return dict(receipt, fenced=True, writers_stopped=True)
            if action == 'source_probe':
                return self.source_probe(request)
            if action == 'capture':
                self.source_probe(request)
                receipt = self.host.capture(run, lambda: self.authority.forward_guard(request))
                staged = self.stage.stage(
                    run_id=run, archive=self.host.directory / 'full.tar.gz',
                    archive_digest=receipt['archive_digest'], container_id=receipt['container_id'],
                    image_id=receipt['image_id'], continuity_contract=CONTRACT)
                # Local stage always remains ready=false, independent=false.
                # Only a SEPARATE custody backend may establish off-host custody.
                copy = self.authority.independent_copy(request, self.stage.directory / 'full.tar.gz', staged)
                require(copy.get('run_id') == run and copy.get('archive_digest') == receipt['archive_digest']
                        and copy.get('verified') is True and copy.get('independent_copy_verified') is True,
                        'independent custody not verified')
                self.source_probe(request)
                return dict(receipt, independent_copy_verified=True)
            if action == 'notify_ready':
                self.source_probe(request)
                self.authority.forward_guard(request)
                return self.sender.send(request)
            if action == 'notify_blocked':
                return self.sender.send(request, 'blocked')
            if action == 'target_fence':
                # Includes outstanding remote operation revocation. Local host
                # revocation is serialized with orphan capture in recover().
                return self.authority.target_fence(request)
            if action == 'target_probe':
                return self.authority.target_probe(request)
            if action == 'source_recover':
                saved = request.get('saved_states_digest')
                require(saved is None or saved == self.host.record(run)['original_sha256'],
                        'controller original-settings binding mismatch')
                return self.host.recover(run, lambda: self.authority.recovery_guard(request))
            # Target activity needs independent delta preservation/reconciliation;
            # never misroute source_resume to the no-target-activity fast path.
            raise Refused('operation outside reversible pre-cutover preparation')

    def source_probe(self, request):
        current = self.host.observe(self.host.record(request['run_id']))
        proof = self.authority.source_probe(request)
        require(proof.get('run_id') == request['run_id'], 'source authority mismatch')
        if current['State'].get('Running') is True:
            return dict(run_id=request['run_id'], running=True, fenced=False, writers_stopped=False)
        bundle.validate_cold_state(current)
        require(proof.get('fenced') is True and proof.get('writers_stopped') is True,
                'all-writer source fence missing')
        return dict(run_id=request['run_id'], running=False, fenced=True, writers_stopped=True)
