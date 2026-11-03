"""One-time receive-only signup; durable secret receipt, no blind retries."""
import argparse
import json
import os
from pathlib import Path
import urllib.request
import urllib.error
import urllib.parse

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
opener = urllib.request.build_opener(NoRedirect)

def request(method, path, payload=None, key=None):
    headers = {'Accept': 'application/json'}
    if payload is not None:
        headers['Content-Type'] = 'application/json'
    if key:
        headers['Authorization'] = 'Bearer ' + key
    req = urllib.request.Request('https://api.agentmail.to/v0/' + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers, method=method)
    try:
        response = opener.open(req, timeout=45)
    except urllib.error.HTTPError as exc:
        response = exc
    return {'status': response.code, 'content_type': response.headers.get('Content-Type'),
            'body': response.read().decode()}

def save(path, obj):
    with path.open('x') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())


def main(argv=None):
    parser=argparse.ArgumentParser(description='Explicit one-time AgentMail signup; no automatic activation')
    parser.add_argument('--home',required=True,type=Path)
    parser.add_argument('--username')
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args(argv)
    if not args.execute:
        parser.error('Signup requires explicit --execute; import and help never register accounts')
    if not args.username:
        parser.error('--username is required for explicit signup')
    HOME=args.home.expanduser().resolve()
    HOME.mkdir(parents=True,mode=0o700,exist_ok=True)
    ROOT=HOME/'agent-mail'
    os.umask(0o077)
    ROOT.mkdir(mode=0o700,exist_ok=True)
    receipt = ROOT / 'signup-response.private.json'
    if not receipt.exists():
        intent = ROOT / 'signup-intent.json'
        if intent.exists():
            raise SystemExit('Previous attempt unresolved; refusing duplicate signup.')
        payload = {'username': args.username, 'source': 'hermes-agent'}
        save(intent, {'state': 'sending', 'payload': payload, 'authorization': 'User requested own free agent mailbox; no human email or billing supplied.'})
        result = request('POST', 'agent/sign-up', payload)
        save(receipt, result)
    else:
        result = json.loads(receipt.read_text())
    if result['status'] != 200:
        # Signup errors have no expected secrets, but print only selected fields.
        try:
            err = json.loads(result['body'])
            print(json.dumps({'status': result['status'], 'name': err.get('name'), 'code': err.get('code'), 'message': err.get('message')}, ensure_ascii=False))
        except ValueError:
            print('Signup failed; response saved privately. HTTP', result['status'])
        raise SystemExit(1)
    data = json.loads(result['body'])
    key = data['api_key']
    env = HOME / '.env'
    # Preserve existing environment entries. Never overwrite another credential.
    text = env.read_text() if env.exists() else ''
    if not any(line.startswith('AGENTMAIL_API_KEY=') for line in text.splitlines()):
        with env.open('a') as f:
            f.write(('' if text.endswith('\n') else '\n') + 'AGENTMAIL_API_KEY=' + key + '\n')
            f.flush()
            os.fsync(f.fileno())
        env.chmod(0o600)
    readback = request('GET', 'inboxes/' + urllib.parse.quote(data['inbox_id'], safe=''), key=key)
    (ROOT / 'inbox-readback.private.json').write_text(json.dumps(readback, indent=2))
    if readback['status'] != 200:
        print('Signup succeeded, exact inbox readback failed. HTTP', readback['status'])
        raise SystemExit(2)
    inbox = json.loads(readback['body'])
    assert inbox['inbox_id'] == data['inbox_id']
    metadata = {'provider': 'AgentMail', 'inbox_id': inbox['inbox_id'], 'email': inbox.get('email', inbox['inbox_id']),
        'organization_id': data['organization_id'], 'mode': 'receive-only-unverified',
        'credential_env': 'AGENTMAIL_API_KEY', 'automatic_monitoring': False,
        'verified_by': 'Authenticated exact inbox GET', 'created_at': inbox.get('created_at')}
    (ROOT / 'account.json').write_text(json.dumps(metadata, indent=2))
    print(json.dumps(metadata, ensure_ascii=False))

if __name__=='__main__':
    main()
