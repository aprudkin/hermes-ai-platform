"""Update fixtures: no Docker daemon, SSH, accounts or production state."""
import contextlib
import copy
import hashlib
import importlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
apply = importlib.import_module('hermes_apply')
IMAGE = 'nousresearch/hermes-agent:v2@sha256:' + '2' * 64
REAL_RUN = apply.run


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'app').mkdir()
        (self.root / 'data/profiles/manager').mkdir(parents=True)
        self.compose = self.root / 'app/docker-compose.yml'
        self.compose.write_text('services:\n  hermes:\n    image: nousresearch/hermes-agent:v1\n')
        (self.root / 'app/gateway.env').write_text('SYNTHETIC=private-fixture\n')
        (self.root / 'data/config.yaml').write_text('fixture: true\n')
        (self.root / 'data/profiles/manager/SOUL.md').write_text('Fixture identity\n')
        self.container = {
            'Id': 'a' * 64, 'Image': 'sha256:' + '1' * 64, 'Name': '/hermes',
            'State': {'Running': True, 'Paused': False, 'Health': {'Status': 'healthy'}},
            'HostConfig': {'NetworkMode': 'host'},
            'Mounts': [{'Type': 'bind', 'Source': str(self.root / 'data'),
                        'Destination': '/opt/data', 'RW': True}],
            'Config': {'Image': 'nousresearch/hermes-agent:v1',
                       'Cmd': ['hermes', '-p', 'manager', 'gateway', 'run'],
                       'Labels': {'com.docker.compose.project': 'fixture',
                                  'com.docker.compose.service': 'hermes',
                                  'com.docker.compose.project.config_files': str(self.compose),
                                  'com.docker.compose.config-hash': 'good-hash'}},
        }
        self.commands = []
        self.fail_up = False
        self.bad_health = False
        self.drift = False
        self.target = {'Id': 'sha256:' + '3' * 64, 'Os': 'linux', 'Architecture': 'amd64'}
        self.baseline = {'name': 'fixture', 'services': {'hermes': {
            'image': 'nousresearch/hermes-agent:v1', 'container_name': 'hermes',
            'environment': {'SYNTHETIC': 'private-fixture'}}}}
        self.addCleanup(patch.stopall)
        patch.object(apply, 'run', side_effect=self.run_command).start()
        patch.object(apply, 'inspect', side_effect=self.inspect).start()
        patch.object(apply, 'layer_diff', return_value=[]).start()

    def inspect(self, kind, name):
        if kind == 'container':
            return copy.deepcopy(self.container)
        return copy.deepcopy(self.target)

    def run_command(self, args, **kwargs):
        self.commands.append(args)
        if 'config' in args:
            if '--hash' in args:
                return b'hermes good-hash\n'
            value = copy.deepcopy(self.baseline)
            if IMAGE in self.compose.read_text():
                value['services']['hermes']['image'] = IMAGE
                if self.drift:
                    value['services']['hermes']['environment'] = {}
            return json.dumps(value).encode()
        if args[:2] == ['docker', 'ps']:
            return (self.container['Id'] + '\n').encode()
        if 'up' in args:
            if self.fail_up:
                raise apply.BundleError('synthetic recreation failure')
            self.container['Id'] = 'b' * 64
            self.container['Image'] = self.target['Id']
            self.container['Config']['Image'] = IMAGE
            if self.bad_health:
                self.container['State']['Health']['Status'] = 'unhealthy'
        return b''

    def snapshot(self):
        return apply.probe(self.root)[0]

    def deploy(self, source=None):
        return apply.deploy(self.root, IMAGE, source or self.snapshot())

    def test_image_only_apply_preserves_files_and_requires_pending_acceptance(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = self.deploy()
        self.assertEqual(result['deployment'], 'applied')
        self.assertEqual(result['functional_acceptance'], 'pending')
        for p, data in before.items():
            self.assertEqual(p.read_bytes(), data.replace(b'nousresearch/hermes-agent:v1', IMAGE.encode())
                             if p == self.compose else data)
        up = next(c for c in self.commands if 'up' in c)
        self.assertIn('--no-deps', up)
        self.assertIn('--no-build', up)
        self.assertEqual(up[-1], 'hermes')
        saved = list((self.root / 'app').glob('update-*/docker-compose.yml'))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].read_bytes(), before[self.compose])
        self.assertEqual(saved[0].stat().st_mode & 0o777, 0o600)

    def test_source_drift_rejected_before_pull_or_write(self):
        source = self.snapshot()
        (self.root / 'app/gateway.env').write_text('CHANGED=1\n')
        with self.assertRaises(apply.BundleError):
            self.deploy(source)
        self.assertFalse(any('pull' in c or 'up' in c for c in self.commands))

    def test_replica_and_container_name_changes_cannot_start_another_owner(self):
        service = self.baseline['services']['hermes']
        for change in ({'scale': 2}, {'deploy': {'replicas': 2}}, {'container_name': 'another'}):
            original = copy.deepcopy(service)
            service.update(change)
            with self.subTest(change=change), self.assertRaises(apply.BundleError):
                self.deploy()
            service.clear()
            service.update(original)
        self.assertFalse(any('pull' in c or 'up' in c for c in self.commands))

    def test_unmanaged_compose_and_hash_drift_fail_closed(self):
        for key, value in [('com.docker.compose.project.config_files', '/elsewhere.yml'),
                           ('com.docker.compose.config-hash', 'stale')]:
            with self.subTest(key=key):
                original = self.container['Config']['Labels'][key]
                self.container['Config']['Labels'][key] = value
                with self.assertRaises(apply.BundleError):
                    self.deploy()
                self.container['Config']['Labels'][key] = original
        self.assertFalse(any('up' in c for c in self.commands))

    def test_recreation_failure_preserves_candidate_and_intent_without_rollback(self):
        self.fail_up = True
        with self.assertRaises(apply.BundleError):
            self.deploy()
        self.assertIn(IMAGE, self.compose.read_text())
        self.assertEqual(sum('up' in c for c in self.commands), 1)
        self.assertEqual(len(list((self.root / 'app').glob('update-*/intent.json'))), 1)
        self.assertFalse(list((self.root / 'app').glob('update-*/result.json')))

    def test_health_failure_is_not_success(self):
        self.bad_health = True
        with self.assertRaises(apply.BundleError):
            self.deploy()
        self.assertEqual(sum('up' in c for c in self.commands), 1)

    def test_candidate_config_drift_never_recreates(self):
        self.drift = True
        with self.assertRaises(apply.BundleError):
            self.deploy()
        self.assertFalse(any('up' in c for c in self.commands))

    def test_busy_backup_lock_prevents_update(self):
        import fcntl
        with (self.root / '.hermes-backup.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(apply.BundleError):
                self.deploy()
        self.assertFalse(any('pull' in c or 'up' in c for c in self.commands))

    def test_missing_confirmation_has_no_remote_or_backup_side_effects(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(apply, 'remote') as remote:
            with self.assertRaises(apply.BundleError):
                apply.controller()
            remote.assert_not_called()

    def test_backup_failure_never_calls_remote_apply(self):
        review = {'image': IMAGE, 'source': {'container_id': 'a' * 64}}
        with patch.dict(os.environ, {'HERMES_CONFIRM_UPDATE': '1'}), \
             patch.object(apply, 'load_review', return_value=review), \
             patch.object(apply, 'remote', return_value=review['source']) as remote, \
             patch.object(apply, 'fresh_backup', side_effect=apply.BundleError('backup failed')), \
             patch.object(apply, 'local_check'):
            with self.assertRaises(apply.BundleError):
                apply.controller()
            self.assertEqual(remote.call_args_list, [call({'action': 'inspect'})])

    def test_controller_orders_gates_and_does_not_claim_functional_success(self):
        review = {'image': IMAGE, 'source': self.snapshot()}
        events = []

        def remote(request):
            events.append(request['action'])
            return review['source'] if request['action'] == 'inspect' else {
                'deployment': 'applied', 'functional_acceptance': 'pending'}

        def backup(source):
            self.assertEqual(source, review['source'])
            events.append('backup')
            return self.root / 'verified-full.tar.gz'

        output = io.StringIO()
        with patch.dict(os.environ, {'HERMES_CONFIRM_UPDATE': '1'}), \
             patch.object(apply, 'load_review', return_value=review), \
             patch.object(apply, 'remote', side_effect=remote), \
             patch.object(apply, 'fresh_backup', side_effect=backup), \
             patch.object(apply, 'local_check', side_effect=lambda args: events.append('validate')), \
             contextlib.redirect_stdout(output):
            apply.controller()
        self.assertEqual(events, ['validate', 'inspect', 'backup', 'apply'])
        self.assertIn('Functional acceptance PENDING', output.getvalue())
        self.assertIn('No Git commit/push was performed', output.getvalue())

    def test_validation_failure_and_stale_backup_never_apply(self):
        review = {'image': IMAGE, 'source': self.snapshot()}
        with patch.dict(os.environ, {'HERMES_CONFIRM_UPDATE': '1'}), \
             patch.object(apply, 'load_review', return_value=review), \
             patch.object(apply, 'remote', return_value=review['source']) as remote, \
             patch.object(apply, 'local_check', side_effect=apply.BundleError('validation failed')):
            with self.assertRaises(apply.BundleError):
                apply.controller()
            remote.assert_not_called()
        with patch.dict(os.environ, {'HERMES_CONFIRM_UPDATE': '1'}), \
             patch.object(apply, 'load_review', return_value=review), \
             patch.object(apply, 'remote', return_value=review['source']) as remote, \
             patch.object(apply, 'local_check'), patch.object(apply, 'fresh_backup'), \
             patch.object(apply.time, 'monotonic', side_effect=[0, 1801]):
            with self.assertRaises(apply.BundleError):
                apply.controller()
            self.assertEqual(remote.call_args_list, [call({'action': 'inspect'})])

    def test_remote_failure_reports_observation_not_success_or_private_values(self):
        output = io.StringIO()
        with patch.object(apply.sys, 'argv', ['script', '--remote', '{"action":"apply"}']), \
             contextlib.redirect_stdout(output):
            self.assertEqual(apply.main(), 1)
        value = json.loads(output.getvalue())
        self.assertEqual(value['deployment'], 'unknown')
        self.assertEqual(value['observed']['image_id'], self.container['Image'])
        self.assertNotIn('private-fixture', output.getvalue())

    def test_incomplete_attempt_blocks_new_apply_but_allows_inspection(self):
        self.fail_up = True
        with self.assertRaises(apply.BundleError):
            self.deploy()
        self.compose.write_text('services:\n  hermes:\n    image: nousresearch/hermes-agent:v1\n')
        source = self.snapshot()
        self.fail_up = False
        with self.assertRaisesRegex(apply.BundleError, 'incomplete update'):
            self.deploy(source)
        self.assertEqual(sum('up' in c for c in self.commands), 1)
        saved = next((self.root / 'app').glob('update-*/intent.json')).parent
        (saved / 'result.json').write_text('{}')
        with self.assertRaises(apply.BundleError):
            self.deploy(source)
        (saved / 'result.json').write_text('{')
        with self.assertRaises(ValueError):
            self.deploy(source)
        self.assertEqual(sum('up' in c for c in self.commands), 1)

    def test_changed_profile_mount_and_missing_identity_fail_before_apply(self):
        self.container['Config']['Cmd'][2] = 'other'
        with self.assertRaises(apply.BundleError):
            self.deploy()
        self.container['Config']['Cmd'][2] = 'manager'
        self.container['Mounts'][0]['Source'] = '/not-the-data'
        with self.assertRaises(apply.BundleError):
            self.deploy()
        self.container['Mounts'][0]['Source'] = str(self.root / 'data')
        (self.root / 'data/profiles/manager/SOUL.md').unlink()
        with self.assertRaises(apply.BundleError):
            self.deploy()
        self.assertFalse(any('up' in c for c in self.commands))

    def test_local_review_gate_is_real_and_does_not_run_preparation(self):
        repo = self.root / 'repo'
        for directory in ('scripts', 'docker', 'docs'):
            (repo / directory).mkdir(parents=True)
        shutil.copyfile(ROOT / 'scripts/hermes_upgrade.sh', repo / 'scripts/hermes_upgrade.sh')
        for path in ('README.md', 'docs/operations.md'):
            (repo / path).write_text('Synthetic contract\n')
        (repo / 'docker/docker-compose.yml').write_text('image: nousresearch/hermes-agent:v2\n')
        review = {'tag': 'v2', 'image': IMAGE, 'source': self.snapshot(),
                  'release_notes_url': 'https://github.com/NousResearch/hermes-agent/releases/tag/v2',
                  'compatibility': 'compatible', 'summary': 'Synthetic compatibility review',
                  'maintenance_window': 'Fixture window', 'rollback_plan': 'Isolated recovery only',
                  'contracts': {p: hashlib.sha256((repo / p).read_bytes()).hexdigest()
                                for p in ('README.md', 'docs/operations.md', 'docker/docker-compose.yml')},
                  'checks': [{'command': './scripts/validate.sh --all', 'result': 'passed'}]}
        path = self.root / 'review.json'
        path.write_text(json.dumps(review))
        with patch.object(apply, 'repository', return_value=repo), \
             patch.object(apply, 'run', side_effect=REAL_RUN), \
             patch.dict(os.environ, {'HERMES_UPGRADE_REVIEW_FILE': str(path)}):
            self.assertEqual(apply.load_review(), review)
            for key, value in [('image', 'nousresearch/hermes-agent:latest'),
                               ('rollback_plan', ''), ('tag', 'wrong')]:
                changed = dict(review, **{key: value})
                path.write_text(json.dumps(changed))
                with self.subTest(key=key), self.assertRaises(apply.BundleError):
                    apply.load_review()
            path.write_text(json.dumps(review))
            (repo / 'README.md').write_text('Changed contract')
            with self.assertRaises(apply.BundleError):
                apply.load_review()

    def test_remote_program_and_failure_do_not_leak_diagnostics(self):
        with patch.object(apply.subprocess, 'run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, json.dumps(self.snapshot()), '')
            apply.remote({'action': 'inspect'})
            command = run.call_args.args[0]
            self.assertIn('-T', command)
            compile(run.call_args.kwargs['input'], '<shipped-program>', 'exec')
            run.side_effect = subprocess.CalledProcessError(1, [], stderr='private-fixture')
            with self.assertRaisesRegex(apply.BundleError, 'runtime state UNKNOWN') as error:
                apply.remote({'action': 'apply', 'image': IMAGE, 'source': self.snapshot()})
            self.assertNotIn('private-fixture', str(error.exception))

    def test_shared_test_runner_does_not_inherit_update_authorization_or_live_profile(self):
        runner = self.root / 'isolated-tests'
        runner.mkdir()
        shutil.copyfile(ROOT / 'tests/run.sh', runner / 'run.sh')
        (runner / 'environment_test.sh').write_text(
            '#!/usr/bin/env bash\nset -euo pipefail\n'
            '[[ -z "${HERMES_UPGRADE_REVIEW_FILE+x}" && -z "${HERMES_DEPLOY_HOST+x}" ]]\n'
            '[[ -z "${HERMES_CONFIRM_UPDATE+x}" && -z "${CONFIRM_DEPLOY+x}" ]]\n'
            '[[ -d "$HERMES_HOME" && "$HERMES_HOME" != /synthetic/live-profile ]]\n'
            '[[ "$HERMES_SRC" == /synthetic/test-source ]]\n')
        env = dict(os.environ, HERMES_UPGRADE_REVIEW_FILE='/synthetic/private-review.json',
                   HERMES_DEPLOY_HOST='never.example.invalid', HERMES_CONFIRM_UPDATE='1',
                   CONFIRM_DEPLOY='yes', HERMES_HOME='/synthetic/live-profile',
                   HERMES_SRC='/synthetic/test-source')
        result = subprocess.run(['bash', str(runner / 'run.sh')], env=env,
                                capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_task_aliases_and_separate_apply(self):
        for task, script in [('update:hermes', 'hermes_upgrade.sh'),
                             ('hermes:update', 'hermes_upgrade.sh'),
                             ('update:hermes:prepare', 'hermes_upgrade.sh'),
                             ('update:hermes:apply', 'hermes_apply.py'),
                             ('update:hermes:inspect', 'hermes_apply.py --inspect')]:
            result = subprocess.run(['task', '--taskfile', str(ROOT / 'Taskfile.yml'), '--dry', task],
                                    capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(script, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
