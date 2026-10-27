#!/usr/bin/env python3
"""Fixed-DM outbound Telegram sender. No polling, webhook or confirmation receiver.

Not installed/enabled by this repository. A sender does not make a stopped
receiver safe: prove input drain/replay and owner confirmation independently.
"""
import argparse
import datetime
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time

from hermes_migration_controller import Refused, atomic_json, require
from hermes_migration_host import locked, private_directory, read_private


def token_bytes(path):
    require(path.is_absolute() and path == path.resolve(), 'unsafe credential path')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and not info.st_mode & 0o077 and info.st_size <= 256, 'unsafe credential file')
        value = stream.read().strip()
    require(re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]{20,100}', value), 'invalid credential format')
    return value


class Sender:
    def __init__(self, config, directory, connection=http.client.HTTPSConnection):
        self.directory = Path(directory)
        private_directory(self.directory)
        self.config = read_private(Path(config))
        require(set(self.config) == {'owner_id', 'chat_id', 'token_file'}, 'unsupported sender configuration')
        require(isinstance(self.config['owner_id'], str)
                and re.fullmatch('[1-9][0-9]{0,19}', self.config['owner_id'])
                and self.config['chat_id'] == self.config['owner_id'], 'fixed private owner DM required')
        self.connection = connection  # In-process offline test seam; never CLI/config URL.

    def send(self, state, kind='ready'):
        require(kind in ('ready', 'blocked'), 'unsupported notice')
        require(state.get('phase') == ('NOTIFYING_READY' if kind == 'ready' else 'BLOCKED'),
                'wrong notification phase')
        require(all(state.get(key) == self.config[key] for key in ('owner_id', 'chat_id')),
                'notice identity mismatch')
        run = state.get('run_id')
        require(isinstance(run, str) and re.fullmatch('[0-9a-f]{32}', run), 'invalid run')
        if kind == 'ready':
            require(isinstance(state.get('nonce'), str) and re.fullmatch('[0-9a-f]{48}', state['nonce'])
                    and isinstance(state.get('archive_digest'), str)
                    and re.fullmatch('[0-9a-f]{64}', state['archive_digest']), 'invalid readiness identity')
            expiry = state.get('prepare_deadline')
            require(type(expiry) in (int, float) and math.isfinite(expiry)
                    and time.time() < expiry < time.time() + 86400, 'readiness notice expired')
            deadline = datetime.datetime.fromtimestamp(expiry, datetime.timezone.utc).isoformat()
            text = (f'Подготовлен перенос, run {run}.\nАрхив SHA256: {state["archive_digest"]}'
                    f'\nNonce: {state["nonce"]}\nПодтверждение действительно до {deadline}.'
                    '\nCutover не начат. Нужно новое подтверждение владельца в исходном чате'
                    ' через заранее проверенный единственный receiver.'
                    '\nPlan B: с независимого компьютера запросить rollback этого run через'
                    ' hermes_migration_plan_b.py; неизвестное состояние target — запрет старта source.'
                    '\nДоставка этого уведомления не является подтверждением.')
        else:
            text = (f'Перенос BLOCKED, run {run}. Заморозка не разрешена: admission не доказан.'
                    ' Не запускайте второй экземпляр. Проверить исходный host и журнал;'
                    ' недоступный target не считается остановленным.')
        payload = {'chat_id': int(self.config['chat_id']), 'text': text,
                   'disable_notification': False, 'protect_content': True,
                   'link_preview_options': {'is_disabled': True}}
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        fingerprint = hashlib.sha256(encoded).hexdigest()
        path = self.directory / (run + '.' + kind + '.notice.json')
        with locked(self.directory / 'sender.lock'):
            if path.exists():
                previous = read_private(path)
                require(previous['request_sha256'] == fingerprint, 'notice intent changed')
                require(previous['status'] == 'delivered', 'uncertain notice; reconcile without resending')
                return previous['receipt']
            token = token_bytes(Path(self.config['token_file']))
            # Any interruption after this fsync is uncertain, even before connect.
            # Bot API sendMessage has no idempotency key or message readback API.
            intent = {'run_id': run, 'status': 'uncertain', 'request_sha256': fingerprint}
            atomic_json(path, intent)
            connection = self.connection('api.telegram.org', timeout=15)
            try:
                connection.request('POST', '/bot' + token + '/sendMessage', body=encoded,
                                   headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
                response = connection.getresponse()
                raw = response.read(65537)
                require(response.status == 200 and len(raw) <= 65536, 'notice response rejected')
                data = json.loads(raw)
                result = data.get('result', {})
                require(data.get('ok') is True and result.get('chat', {}).get('type') == 'private'
                        and type(result.get('chat', {}).get('id')) is int
                        and result['chat']['id'] == int(self.config['chat_id'])
                        and result.get('from', {}).get('is_bot') is True
                        and result['from'].get('id') == int(token.split(':', 1)[0])
                        and type(result.get('message_id')) is int and result['message_id'] > 0
                        and result.get('text') == text, 'notice receipt mismatch')
                receipt = {'run_id': run, 'owner_id': self.config['owner_id'], 'chat_id': self.config['chat_id'],
                           'delivered': True, 'notice_id': str(result['message_id'])}
                if kind == 'ready':
                    receipt.update(nonce=state['nonce'], archive_digest=state['archive_digest'])
                intent.update(status='delivered', receipt=receipt)
                atomic_json(path, intent)
                return receipt
            except (OSError, ValueError, TypeError, KeyError, AttributeError, http.client.HTTPException, Refused):
                raise Refused('notice uncertain or rejected; do not automatically resend') from None
            finally:
                connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--state-dir', required=True, type=Path)
    parser.add_argument('--controller-state', required=True, type=Path)
    parser.add_argument('--kind', choices=('ready', 'blocked'), required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    try:
        require(args.execute, 'explicit --execute required; no test messages')
        receipt = Sender(args.config, args.state_dir).send(read_private(args.controller_state), args.kind)
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except (Refused, OSError, ValueError, TypeError, KeyError):
        print('notice not confirmed; inspect private intent without automatic retry', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
