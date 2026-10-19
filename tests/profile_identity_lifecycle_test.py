"""Exercise production Ansible identity tasks on isolated local fixtures."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class IdentityLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.play_dir = self.root / 'ansible'
        self.play_dir.mkdir()
        (self.root / 'profiles').symlink_to(ROOT / 'profiles', target_is_directory=True)
        self.data = self.root / 'data'
        self.identity = self.data / 'profiles/manager/SOUL.md'
        self.identity.parent.mkdir(parents=True)
        self.personal = b'# Personal identity\n\nLocally chosen words.\n'
        self.identity.write_bytes(self.personal)

    def production_install(self, *, created=False, replace=False):
        tasks = yaml.safe_load((ROOT / 'ansible/roles/hermes/tasks/main.yml').read_text())
        installation = next(t for t in tasks if t.get('name') == 'Install profile identities')
        variables = {
            'hermes_data_dir': str(self.data),
            'hermes_runtime_owner': str(os.getuid()),
            'hermes_runtime_group': str(os.getgid()),
            'hermes_profiles': [{'name': 'manager'}],
            'hermes_profile_queries': {'results': [
                {'item': {'name': 'manager'}, 'rc': 1 if created else 0}]},
        }
        if replace:
            variables['hermes_replace_profile_identities'] = True
        play = [{'name': 'Isolated identity lifecycle', 'hosts': 'localhost',
                 'connection': 'local', 'gather_facts': False, 'become': False,
                 'vars': variables, 'tasks': [installation],
                 'handlers': [{'name': 'Restart Hermes', 'ansible.builtin.debug':
                               {'msg': 'Fixture only; no runtime restart'}}]}]
        path = self.play_dir / 'identity.yml'
        path.write_text(json.dumps(play))
        result = subprocess.run(['ansible-playbook', '-i', 'localhost,', str(path)],
                                capture_output=True, text=True, timeout=45,
                                env={**os.environ, 'ANSIBLE_NOCOLOR': '1',
                                     'ANSIBLE_LOCAL_TEMP': str(self.root / 'ansible-tmp')})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def production_verify(self, *, replace=False):
        variables = {'hermes_data_dir': str(self.data),
                     'hermes_profile_source_dir': str(ROOT / 'profiles'),
                     'hermes_profile_names': ['manager'],
                     'hermes_replace_profile_identities': replace}
        play = [{'name': 'Isolated identity verification', 'hosts': 'localhost',
                 'connection': 'local', 'gather_facts': False, 'become': False,
                 'vars': variables, 'tasks': [{'ansible.builtin.include_tasks':
                     str(ROOT / 'ansible/tasks/verify_profile_identities.yml')}]}]
        path = self.play_dir / 'verify.yml'
        path.write_text(json.dumps(play))
        return subprocess.run(['ansible-playbook', '-i', 'localhost,', str(path)],
                              capture_output=True, text=True, timeout=45,
                              env={**os.environ, 'ANSIBLE_NOCOLOR': '1',
                                   'ANSIBLE_LOCAL_TEMP': str(self.root / 'ansible-tmp')})

    def test_verifier_accepts_preserved_identity(self):
        result = self.production_verify()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.identity.read_bytes(), self.personal)

    def test_newly_created_profile_replaces_the_cloned_seed(self):
        self.identity.write_bytes(b'# Cloned default seed\n')
        self.production_install(created=True)
        self.assertEqual(self.identity.read_bytes(),
                         (ROOT / 'profiles/manager/SOUL.md').read_bytes())

    def test_missing_identity_is_initialized_for_an_existing_profile(self):
        self.identity.unlink()
        self.production_install()
        self.assertEqual(self.identity.read_bytes(),
                         (ROOT / 'profiles/manager/SOUL.md').read_bytes())

    def test_explicit_replacement_keeps_a_byte_exact_backup(self):
        self.production_install(replace=True)
        self.assertEqual(self.identity.read_bytes(),
                         (ROOT / 'profiles/manager/SOUL.md').read_bytes())
        backups = list(self.identity.parent.glob('SOUL.md.*~'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.personal)

    def test_verifier_rejects_empty_identity(self):
        self.identity.write_bytes(b'')
        self.assertNotEqual(self.production_verify().returncode, 0)

    def test_verifier_rejects_missing_identity(self):
        self.identity.unlink()
        self.assertNotEqual(self.production_verify().returncode, 0)

    def test_verifier_rejects_symlink_identity(self):
        original = self.root / 'other.md'
        original.write_bytes(self.personal)
        self.identity.unlink()
        self.identity.symlink_to(original)
        self.assertNotEqual(self.production_verify().returncode, 0)

    def test_explicit_replacement_verification_rejects_source_drift(self):
        self.assertNotEqual(self.production_verify(replace=True).returncode, 0)

    def test_explicit_replacement_verification_accepts_exact_source(self):
        self.identity.write_bytes((ROOT / 'profiles/manager/SOUL.md').read_bytes())
        result = self.production_verify(replace=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_new_profile_then_later_edit_survives_redeploy(self):
        self.production_install(created=True)
        self.identity.write_bytes(self.personal)
        self.production_install()
        self.assertEqual(self.identity.read_bytes(), self.personal)
        self.assertEqual(self.production_verify().returncode, 0)

    def test_redeploy_preserves_locally_edited_identity(self):
        self.production_install()
        self.assertEqual(self.identity.read_bytes(), self.personal)


if __name__ == '__main__':
    unittest.main()
