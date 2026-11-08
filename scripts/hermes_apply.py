#!/usr/bin/env python3
"""Explicit external-controller update of the existing, Compose-managed Hermes."""
import copy
import fcntl
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

from hermes_backup_bundle import (
    BundleError,
    inspect,
    layer_diff,
    require,
    run,
    validate_container,
)

ROOT = Path('/opt/hermes')
IMAGE = re.compile(r'nousresearch/hermes-agent:([A-Za-z0-9._-]+)@sha256:[0-9a-f]{64}')
PIN = re.compile(r'(?m)^(\s*image:\s*)(nousresearch/hermes-agent:[A-Za-z0-9._:@-]+)([ \t]*(?:#.*)?)$')


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compose_command(root, container):
    labels = container['Config'].get('Labels') or {}
    project = labels.get('com.docker.compose.project', '')
    require(re.fullmatch(r'[a-z0-9][a-z0-9_-]*', project), 'missing Compose project')
    require(labels.get('com.docker.compose.service') == 'hermes'
            and labels.get('com.docker.compose.project.config_files') == str(root / 'app/docker-compose.yml'),
            'only the existing single-file app/docker-compose.yml layout is supported')
    return ['docker', 'compose', '--project-directory', str(root / 'app'),
            '--env-file', str(root / 'app/gateway.env'), '-p', project,
            '-f', str(root / 'app/docker-compose.yml')]


def probe(root):
    container = inspect('container', 'hermes')
    require(validate_container(container, root, 'hermes') == 'manager', 'expected manager profile')
    layer_diff(container['Id'])
    command = compose_command(root, container)
    config_hash = run(command + ['config', '--hash', 'hermes']).decode().strip().split()
    require(config_hash == ['hermes', container['Config']['Labels'].get('com.docker.compose.config-hash')],
            'deployed Compose inputs differ from the running container; reconcile first')
    config = json.loads(run(command + ['config', '--format', 'json']))
    require(set(config.get('services', {})) == {'hermes'}, 'expected one Compose service')
    service = config['services']['hermes']
    require(service.get('container_name') == 'hermes' and service.get('scale', 1) == 1
            and (service.get('deploy') or {}).get('replicas', 1) == 1,
            'expected one replica with the fixed hermes container name')
    require(service.get('image') == container['Config']['Image'],
            'Compose image differs from the running container')
    owners = run(['docker', 'ps', '--no-trunc', '--quiet', '--filter',
                  'label=com.docker.compose.project=' + config['name'], '--filter',
                  'label=com.docker.compose.service=hermes']).decode().split()
    require(owners == [container['Id']], 'expected exactly one running Compose owner')
    identity = root / 'data/profiles/manager/SOUL.md'
    require(identity.is_file() and not identity.is_symlink() and identity.stat().st_size > 0,
            'live manager identity is missing')
    source = {'container_id': container['Id'], 'image_id': container['Image'],
              'compose_sha256': file_hash(root / 'app/docker-compose.yml'),
              'gateway_sha256': file_hash(root / 'app/gateway.env'),
              'identity_sha256': file_hash(identity)}
    return source, container, command, config


def private_json(path, value):
    with path.open('x', encoding='utf-8') as stream:
        os.chmod(path, 0o600)
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(path.parent)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def replace_compose(path, content):
    previous = path.stat()
    fd, name = tempfile.mkstemp(prefix='.update-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), stat.S_IMODE(previous.st_mode))
            os.fchown(stream.fileno(), previous.st_uid, previous.st_gid)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def deploy(root, image, expected):
    require(IMAGE.fullmatch(image), 'expected an explicit official tag and sha256 digest')
    os.umask(0o077)
    # Share the capture lock: no backup may pause a container being replaced.
    fd = os.open(root / '.hermes-backup.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+b') as lock:
        require(stat.S_ISREG(os.fstat(lock.fileno()).st_mode), 'invalid capture lock')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BundleError('capture or update is already active') from None
        for intent in (root / 'app').glob('update-*/intent.json'):
            receipt = intent.parent / 'result.json'
            require(receipt.is_file(),
                    'an incomplete update exists; reconcile its private intent before retrying')
            result = json.loads(receipt.read_text())
            require(isinstance(result, dict) and result.get('deployment') == 'applied'
                    and result.get('image') == json.loads(intent.read_text())['target'],
                    'invalid update receipt; reconcile before retrying')
        source, container, command, config = probe(root)
        require(source == expected, 'reviewed source changed; inspect and review again')
        require(container['Config']['Image'] != image, 'image reference already applied; not an update')
        compose = root / 'app/docker-compose.yml'
        original = compose.read_bytes()
        text = original.decode('utf-8')
        matches = list(PIN.finditer(text))
        require(len(matches) == 1 and matches[0][2] == container['Config']['Image'],
                'deployed image must be one literal official pin, not an interpolation')
        candidate = PIN.sub(lambda match: match[1] + image + match[3], text).encode('utf-8')
        old_image = inspect('image', container['Image'])
        run(['docker', 'image', 'pull', image], timeout=900)
        target = inspect('image', image)
        require(all(target.get(key) == old_image.get(key) and target.get(key)
                    for key in ('Os', 'Architecture')), 'target platform differs from source')
        require(target['Id'] != container['Image'], 'target is already running; not an update')
        require(probe(root)[0] == expected, 'source changed while pulling image')
        saved = Path(tempfile.mkdtemp(prefix='update-', dir=root / 'app'))
        for name in ('docker-compose.yml', 'gateway.env'):
            destination = saved / name
            destination.write_bytes((root / 'app' / name).read_bytes())
            destination.chmod(0o600)
        private_json(saved / 'intent.json', {'source': source, 'target': image,
                                           'target_image_id': target['Id'],
                                           'status': 'apply may be incomplete; do not blindly retry or roll back'})
        replace_compose(compose, candidate)
        effective = json.loads(run(command + ['config', '--format', 'json']))
        wanted = copy.deepcopy(config)
        wanted['services']['hermes']['image'] = image
        require(effective == wanted, 'candidate changes more than the image; not recreating')
        # Never build, start dependencies, remove volumes or run a second project.
        run(command + ['up', '-d', '--no-deps', '--no-build', '--pull', 'never',
                       '--wait', '--wait-timeout', '180', 'hermes'], timeout=240)
        current_source, current, _, _ = probe(root)
        require(current['Image'] == target['Id'] and current['Config']['Image'] == image,
                'applied image not confirmed')
        require(current_source['compose_sha256'] == hashlib.sha256(candidate).hexdigest(),
                'deployed Compose changed during apply')
        require(current['State'].get('Health', {}).get('Status') == 'healthy', 'health not confirmed')
        require(file_hash(root / 'data/profiles/manager/SOUL.md') == source['identity_sha256'],
                'live identity changed; functional acceptance failed')
        require(file_hash(root / 'app/gateway.env') == source['gateway_sha256'],
                'protected gateway inputs changed')
        result = {'deployment': 'applied', 'image': image, 'image_id': target['Id'],
                  'profile': 'manager', 'health': 'healthy', 'functional_acceptance': 'pending',
                  'rollback_config': str(saved)}
        private_json(saved / 'result.json', result)
        return result


def repository():
    return Path(__file__).resolve().parents[1]


def local_check(args, env=None):
    try:
        subprocess.run(args, env=env, check=True)
    except (OSError, subprocess.SubprocessError):
        raise BundleError('local validation or backup failed; apply not authorized') from None


def load_review():
    path = Path(os.environ.get('HERMES_UPGRADE_REVIEW_FILE', ''))
    require(path.is_file(), 'set HERMES_UPGRADE_REVIEW_FILE to a private review JSON')
    require(not path.resolve().is_relative_to(repository()), 'keep the private apply review outside Git')
    review = json.loads(path.read_text())
    require(isinstance(review, dict), 'invalid review')
    match = IMAGE.fullmatch(review.get('image', ''))
    if match is None:
        raise BundleError('review.image must contain an official tag and sha256 digest')
    tag = match[1]
    root = repository()
    pins = list(PIN.finditer((root / 'docker/docker-compose.yml').read_text()))
    require(len(pins) == 1 and pins[0][2] == 'nousresearch/hermes-agent:' + tag,
            'prepare/review the local target pin first')
    # Reuse the preparation gate, without invoking its backup or pin mutation.
    run(['bash', '-c', 'source "$1"; verify_compatibility_review "$2"', '_',
         str(root / 'scripts/hermes_upgrade.sh'), tag])
    require(isinstance(review.get('source'), dict) and review['source'], 'review.source is required')
    for key in ('maintenance_window', 'rollback_plan'):
        require(isinstance(review.get(key), str) and review[key].strip(), 'review.' + key + ' is required')
    return review


def remote(request):
    root = repository()
    host = os.environ.get('HERMES_DEPLOY_HOST') or 'hermes-minimal'
    user = os.environ.get('HERMES_DEPLOY_SSH_USER')
    destination = user + '@' + host if user else host
    require(not destination.startswith('-') and not any(c.isspace() for c in destination),
            'invalid SSH destination')
    command = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new']
    key = os.environ.get('HERMES_DEPLOY_SSH_PRIVATE_KEY')
    if key:
        require(Path(key).is_file(), 'explicit SSH key is missing')
        command += ['-i', key]
    command += [destination, 'python3 - --remote ' + shlex.quote(json.dumps(request))]
    # Ship the existing runtime validator as well; no remote installation is needed.
    program = ('import sys, types\n'
               'bundle = types.ModuleType("hermes_backup_bundle")\n'
               'sys.modules[bundle.__name__] = bundle\n'
               f'exec({(root / "scripts/hermes_backup_bundle.py").read_text()!r}, bundle.__dict__)\n'
               + (root / 'scripts/hermes_apply.py').read_text())
    try:
        result = subprocess.run(command, input=program, text=True, capture_output=True,
                                check=False, timeout=1500)
        response = json.loads(result.stdout)
        if result.returncode:
            require(isinstance(response, dict) and response.get('deployment') == 'unknown',
                    'unexpected remote failure response; runtime state UNKNOWN')
            print(json.dumps(response, indent=2), file=sys.stderr)
            raise BundleError('remote operation failed; reconcile observed state and private intent before retrying')
        return response
    except (OSError, ValueError, subprocess.SubprocessError):
        raise BundleError('remote operation failed/disconnected; runtime state UNKNOWN. '
                          'Inspect app/update-*/intent.json on the host before any retry; '
                          'no automatic retry or rollback was performed (diagnostics withheld)') from None


def fresh_backup(source):
    base = Path(os.environ.get('HERMES_BACKUP_DIR') or Path.home() / 'backup/hermer').expanduser()
    base.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='update-', dir=base))
    env = dict(os.environ, HERMES_BACKUP_DIR=str(directory))
    local_check(['bash', str(repository() / 'scripts/hermes_backup.sh'), '--full'], env=env)
    archives = list(directory.glob('hermes-recovery-*.tar.gz'))
    require(len(archives) == 1, 'expected one verified full recovery archive')
    # The existing wrapper has verified all payloads before publishing this file.
    with tarfile.open(archives[0], 'r:gz') as archive:
        stream = archive.extractfile('manifest.json')
        if stream is None:
            raise BundleError('missing full backup manifest')
        with stream:
            manifest = json.load(stream)
    require(manifest['source']['container_id'] == source['container_id']
            and manifest['image']['id'] == source['image_id']
            and manifest['source']['profile'] == 'manager', 'backup does not match reviewed source')
    return archives[0]


def controller():
    require(os.environ.get('HERMES_CONFIRM_UPDATE') == '1',
            'set HERMES_CONFIRM_UPDATE=1 only on an independent off-server controller, '
            'in the reviewed maintenance window; this authorizes container replacement')
    review = load_review()
    print('Validating local source; Git publication is NOT checked or performed.', flush=True)
    local_check(['bash', str(repository() / 'scripts/validate.sh'), '--all'])
    print('Inspecting deployed inputs against the private review.', flush=True)
    source = remote({'action': 'inspect'})
    require(source == review['source'], 'reviewed source changed; inspect and review again')
    started = time.monotonic()
    print('Capturing and verifying a fresh full off-server backup.', flush=True)
    archive = fresh_backup(source)
    require(time.monotonic() - started <= 1800, 'backup took over 30 minutes; maintenance review required')
    print('Backup verified. Applying the exact reviewed image; no automatic rollback.', flush=True)
    result = remote({'action': 'apply', 'image': review['image'], 'source': source})
    require(result.get('deployment') == 'applied' and result.get('functional_acceptance') == 'pending',
            'unexpected apply result; acceptance UNKNOWN')
    print(json.dumps(result, indent=2))
    print(f'Full backup retained: {archive}')
    print('Image/profile/mount/identity/health checked. Functional acceptance PENDING: '
          'verify memory/history, custom applications, approved/cancelled jobs, inference and Telegram. '
          'Health is not proof of those behaviors. No Git commit/push was performed.')


def main():
    try:
        if sys.argv[1:] == ['--inspect']:
            print(json.dumps(remote({'action': 'inspect'}), indent=2))
        elif len(sys.argv) == 3 and sys.argv[1] == '--remote':
            request = json.loads(sys.argv[2])
            if request['action'] == 'inspect':
                result = probe(ROOT)[0]
            else:
                require(request['action'] == 'apply', 'invalid action')
                result = deploy(ROOT, request['image'], request['source'])
            print(json.dumps(result))
        else:
            require(len(sys.argv) == 1, 'usage: hermes_apply.py [--inspect]')
            controller()
    except (BundleError, OSError, ValueError, KeyError, TypeError) as exc:
        message = str(exc) if isinstance(exc, BundleError) else 'invalid inputs or operation failed (details withheld)'
        if len(sys.argv) == 3 and sys.argv[1] == '--remote':
            observed = None
            try:
                current = inspect('container', 'hermes')
                observed = {'container_id': current['Id'], 'image_id': current['Image'],
                            'running': current['State'].get('Running'),
                            'paused': current['State'].get('Paused'),
                            'health': current['State'].get('Health', {}).get('Status', 'unknown')}
            except (BundleError, OSError, ValueError, KeyError, TypeError):
                pass
            print(json.dumps({'deployment': 'unknown', 'error': message, 'observed': observed,
                              'functional_acceptance': 'pending', 'retry': 'manual reconciliation required'}))
        else:
            print('ERROR: ' + message, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
