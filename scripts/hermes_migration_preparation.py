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
    def __init__(self, host, stage, sender, authority=None, *, inventory=None):
        self.host, self.stage, self.sender, self.authority = host, stage, sender, authority
        # Supplying observations explicitly selects a non-acting diagnostic site.
        # No JSON key or ready authority can turn this mode into an effects path.
        self.inventory = inventory

    def diagnose(self):
        """Read-only obligations, NOT an authority or a production proof verifier."""
        obligations = (
            ('identity', 'preflight', 'independent source/target identity and boot binding'),
            ('writers', 'source_quiesce/source_probe', 'processed-state quiescence of every writer'),
            ('recreation', 'source_quiesce/target_fence/target_probe',
             'persistent Docker/systemd/Compose/job/delegate/browser fences across reboot'),
            ('remote_operations', 'hold/forward_guard/target_fence',
             'remote nonrenewable expiry, durable operation identities and positive revoke'),
            ('policy', 'recovery_guard', 'CURRENT cancellations/withdrawals/effects reconciled; no replay'),
            ('custody', 'independent_copy', 'verified independent failure-domain custody'),
            ('rescue', 'preflight', 'owner recovery keys, rescue access and runnable Plan B'),
            ('approval', 'preflight', 'authenticated original-DM fresh approval after readiness'),
            ('watchdog', 'hold/recovery_guard', 'external watchdog and boot/partial-fence recovery'),
            ('target_runtime', 'preflight', 'target startup/delta/dialogue implementation and rehearsal'),
        )
        inventory = self.inventory if isinstance(self.inventory, dict) else {}
        observations = {key: value for key, value in inventory.items() if isinstance(value, dict)}
        hazards = []
        if observations.get('recreation', {}).get('reboot_recreation_possible') is True:
            hazards.append('reboot-recreation-possible')
        pending = observations.get('remote_operations', {}).get('pending')
        if not isinstance(pending, list):
            hazards.append('remote-effects-unknown')
        elif pending:
            hazards.append('pending-remote-effects')
        policy = observations.get('policy', {})
        current, reconciled = policy.get('current'), policy.get('reconciled')
        for revision in ('cancellations', 'withdrawals', 'effects'):
            values = [value.get(revision) if isinstance(value, dict) else None
                      for value in (current, reconciled)]
            if not all(isinstance(value, str) and value for value in values):
                hazards.append('unreconciled-' + revision)
            elif values[0] != values[1]:
                hazards.append('changed-' + revision)
        # Hazards are a convenience, not exhaustive verification. An empty list
        # means no reported hazard, NOT safe/empty queues or a reconciled policy.
        return dict(ready=False, status='BLOCKED', contract='migration-site-v2',
                    evidence_scope='observations-only', hazards=hazards,
                    gates=[dict(gate=gate, authority_method=method, required=required,
                                status='BLOCKED', reason='production-proof-unavailable',
                                observation=('present-unverified' if isinstance(inventory.get(gate), dict)
                                             and inventory[gate] else 'missing-or-invalid'))
                           for gate, method, required in obligations])

    def call(self, action, request):
        try:
            return self.dispatch(action, request)
        except (bundle.BundleError, OSError, ValueError, KeyError, TypeError):
            # Preserve controller/primitive intent; expose no private diagnostics.
            raise Refused('preparation operation incomplete; retained for recovery') from None

    def dispatch(self, action, request):
        run = request['run_id']
        require(request.get('operation_id') == run + ':' + action, 'operation identity mismatch')
        if self.authority is None or self.inventory is not None:
            if action == 'preflight':
                return dict(self.diagnose(), run_id=run)
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


def main():
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description='Read-only production admission diagnostic; never authorizes effects')
    parser.add_argument('--inventory', type=Path, help='optional observations JSON, never executable policy or proof')
    args = parser.parse_args()
    inventory = {}
    if args.inventory is not None:
        try:
            inventory = json.loads(args.inventory.read_text())
            if not isinstance(inventory, dict):
                raise ValueError('expected object')
        except (OSError, ValueError):
            parser.error('inventory unreadable or invalid')
    print(json.dumps(PreparationSite(None, None, None, inventory=inventory).diagnose(), sort_keys=True, indent=2))
    return 2  # Deliberately BLOCKED, including a complete/optimistic inventory.


if __name__ == '__main__':
    raise SystemExit(main())
