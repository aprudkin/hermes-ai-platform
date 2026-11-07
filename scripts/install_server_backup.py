#!/usr/bin/env python3
"""Initial host-local installation only; never contact cloud or enable/start units."""
import argparse
import configparser
import os
from pathlib import Path
import shutil
import subprocess
import sys

from hermes_cloud_backup import digest, private_copy, read_config, require
from hermes_server_backup import CRYPT_ROOT, RCLONE_SHA, trusted_tree

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = Path('/usr/local/lib/hermes-backup')
KEYS = Path('/etc/hermes-backup')
STATE = Path('/var/lib/hermes-backup')
LOGS = Path('/var/log/hermes-backup')
UNITS = Path('/etc/systemd/system')
SCRIPTS = ('hermes_server_backup.py', 'hermes_server_backup_entry.py',
           'hermes_cloud_backup.py', 'hermes_backup_bundle.py')


def preflight(args):
    require(os.getuid() == 0 and args.confirm_external_mutation, 'root and explicit confirmation required')
    require(sys.platform == 'linux', 'Linux host required')
    trusted_tree(ROOT)
    targets = [PACKAGE, KEYS, STATE, LOGS, UNITS / 'hermes-backup.service', UNITS / 'hermes-backup.timer']
    for path in targets:
        trusted_tree(path.parent)
        require(not path.exists() and not path.is_symlink(), 'existing installation or partial state; inspect manually')
    require(shutil.which('systemctl') and shutil.which('systemd-analyze'), 'systemd tools required')
    for unit in ('hermes-backup.service', 'hermes-backup.timer'):
        result = subprocess.run(['systemctl', 'show', '--property=LoadState', '--value', unit],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30, check=True)
        require(result.stdout.strip() == b'not-found', 'existing systemd unit; initial install only')
    require(digest(Path(args.rclone_binary)) == RCLONE_SHA, 'approved Linux amd64 rclone v1.75.2 required')
    # All inputs must be protected regular files; configs never enter the package.
    for value in (args.upload_config, args.recovery_config, args.rclone_binary):
        path = Path(value)
        trusted_tree(path.parent)
        info = path.lstat()
        require(path.is_absolute() and not path.is_symlink() and path.is_file()
                and info.st_uid == 0 and not info.st_mode & 0o077, 'unsafe staged input')
    require(Path(args.upload_config).resolve() != Path(args.recovery_config).resolve(),
            'separately staged recovery config required')
    require(read_config(Path(args.upload_config)) == read_config(Path(args.recovery_config)),
            'working and saved recovery configs differ')


def install(args):
    preflight(args)
    for directory in (PACKAGE, KEYS, STATE, LOGS, STATE / 'runs', STATE / 'receipts'):
        directory.mkdir(mode=0o700)
    for name in SCRIPTS:
        source = ROOT / 'scripts' / name
        require(source.is_file() and not source.is_symlink(), 'missing package source')
        (PACKAGE / name).write_bytes(source.read_bytes())
    source = (PACKAGE / 'hermes_backup_bundle.py').read_text()
    guide = (ROOT / 'docs/backup-restore.md').read_text()
    require(bool(guide), 'missing recovery guide')
    (PACKAGE / 'capture.py').write_text('RESTORE_GUIDE = ' + repr(guide) + '\nBUNDLE_SOURCE = ' + repr(source) + '\n' + source)
    private_copy(Path(args.rclone_binary), PACKAGE / 'rclone', 'rclone')
    (PACKAGE / 'rclone').chmod(0o700)
    require(digest(PACKAGE / 'rclone') == RCLONE_SHA, 'installed binary checksum mismatch')
    private_copy(Path(args.upload_config), KEYS / 'upload.conf', 'working config', 65536)
    private_copy(Path(args.recovery_config), KEYS / 'recovery.conf', 'recovery config', 65536)
    require(read_config(KEYS / 'upload.conf') == read_config(KEYS / 'recovery.conf'), 'installed configs differ')
    for source, target in (('upload.conf', 'daily-upload.conf'), ('recovery.conf', 'daily-recovery.conf')):
        config = configparser.ConfigParser(interpolation=None)
        config.read(KEYS / source)
        config['hermes-backup']['remote'] = CRYPT_ROOT
        config['hermes-backup']['directory_name_encryption'] = 'false'
        with (KEYS / target).open('x') as stream:
            config.write(stream)
    require(read_config(KEYS / 'daily-upload.conf', CRYPT_ROOT, 'false') ==
            read_config(KEYS / 'daily-recovery.conf', CRYPT_ROOT, 'false'), 'installed daily configs differ')
    for name in ('hermes-backup.service', 'hermes-backup.timer'):
        (UNITS / name).write_bytes((ROOT / 'systemd' / name).read_bytes())
        (UNITS / name).chmod(0o644)
    subprocess.run(['systemd-analyze', 'verify', str(UNITS / 'hermes-backup.service'),
                    str(UNITS / 'hermes-backup.timer')], check=True, timeout=30,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=30,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print('Installed only. Timer/service NOT enabled or started. Staged inputs retained; protect them.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-external-mutation', action='store_true')
    parser.add_argument('--upload-config', required=True)
    parser.add_argument('--recovery-config', required=True)
    parser.add_argument('--rclone-binary', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        install(args)
    except Exception:
        print('Installation failed; partial files may remain. Nothing was started by this installer. '
              'Inspect before retry; no automatic overwrite or rollback.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
