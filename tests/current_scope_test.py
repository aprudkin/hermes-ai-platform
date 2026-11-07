"""Contracts for the current one-agent maintenance/recovery repository."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


def retired_assets(root):
    retired = ('terraform', 'ansible', 'installer', 'configs', 'infrastructure',
               'prompts', '.pi', 'docs/agents', 'docs/superpowers',
               'profiles/devops', 'profiles/coding', 'profiles/research',
               'CHATGPT_CONVERSATION.md', 'CODEX_SETUP_PROMPT.md',
               'CODEX_CLI_START.md', 'PROJECT_AUDIT.md',
               'INSTALLATION_GUIDE.md', 'QUICKSTART.md', 'scripts/telegram_env.py')
    tracked = subprocess.check_output(
        ['git', '-C', str(root), 'ls-files', '-z', '--', *retired], text=True)
    return [name for name in tracked.split('\0') if name]


class CurrentScopeTests(unittest.TestCase):
    def test_retired_platform_assets_are_absent(self):
        self.assertEqual(retired_assets(ROOT), [], 'Retired platform material remains tracked')

    def test_scope_ignores_local_cache_but_rejects_tracked_terraform(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '--quiet', str(root)], check=True)
            (root / '.gitignore').write_text((ROOT / '.gitignore').read_text())
            cache = root / 'terraform/.terraform/provider'
            cache.parent.mkdir(parents=True)
            cache.write_text('local provider fixture')
            subprocess.run(['git', '-C', str(root), 'check-ignore', '--quiet', str(cache)], check=True)
            self.assertEqual(retired_assets(root), [])
            source = root / 'terraform/main.tf'
            source.write_text('# retired source fixture\n')
            subprocess.run(['git', '-C', str(root), 'add', 'terraform/main.tf'], check=True)
            self.assertEqual(retired_assets(root), ['terraform/main.tf'])
            subprocess.run(['git', '-C', str(root), 'add', '--force', str(cache)], check=True)
            self.assertIn('terraform/.terraform/provider', retired_assets(root))
            self.assertEqual(cache.read_text(), 'local provider fixture')

    def test_current_identity_and_recovery_entrypoints_remain(self):
        required = ('profiles/manager/SOUL.md', 'docker/docker-compose.yml',
                    'scripts/hermes_backup.sh', 'scripts/hermes_backup_bundle.py',
                    'scripts/hermes_backup_progress.py', 'scripts/hermes_cloud_backup.py',
                    'scripts/hermes_server_backup.py', 'scripts/hermes_server_backup_entry.py',
                    'scripts/install_server_backup.py', 'scripts/hermes_upgrade.sh',
                    'systemd/hermes-backup.service', 'systemd/hermes-backup.timer',
                    'docs/backup-restore.md', 'docs/personal-backup.md',
                    'docs/cloud-backup.md', 'docs/server-backup.md')
        for name in required:
            with self.subTest(path=name):
                self.assertTrue((ROOT / name).is_file())
                self.assertGreater((ROOT / name).stat().st_size, 0)
        self.assertIn('Chebi', (ROOT / 'profiles/manager/SOUL.md').read_text())

    def test_task_exposes_standalone_local_validation(self):
        result = subprocess.run(['task', '--taskfile', str(ROOT / 'Taskfile.yml'), '--dry', 'validate'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('./scripts/validate.sh --all', result.stdout + result.stderr)

    def test_local_document_links_resolve(self):
        missing = []
        for path in ROOT.rglob('*.md'):
            if '.git' in path.parts or '.ai-archive' in path.parts:
                continue
            fenced = False
            for line in path.read_text().splitlines():
                if line.lstrip().startswith('```'):
                    fenced = not fenced
                if fenced:
                    continue
                for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', line):
                    target = target.split('#', 1)[0]
                    if not target or re.match(r'[a-zA-Z][a-zA-Z0-9+.-]*:', target):
                        continue
                    if not (path.parent / unquote(target)).exists():
                        missing.append((str(path.relative_to(ROOT)), target))
        self.assertEqual(missing, [], 'Active documentation links to removed files')


if __name__ == '__main__':
    unittest.main()
