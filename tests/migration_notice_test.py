#!/usr/bin/env python3
"""Offline HTTP fixture: real request/response bytes, no Telegram connection."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from hermes_migration_controller import atomic_json


class NoticeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.token = '12345:' + 'x' * 30
        tokenfile = self.base / 'token'
        tokenfile.write_text(self.token)
        tokenfile.chmod(0o600)
        self.config = self.base / 'sender.json'
        atomic_json(self.config, {'owner_id': '42', 'chat_id': '42', 'token_file': str(tokenfile)})
        self.state = {'phase': 'NOTIFYING_READY', 'run_id': 'a' * 32, 'nonce': 'b' * 48,
                      'owner_id': '42', 'chat_id': '42', 'archive_digest': 'c' * 64,
                      'prepare_deadline': time.time() + 300}
        self.requests = []
        self.mode = 'ok'
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                outer.requests.append((self.path, body))
                if outer.mode == 'lost':
                    self.connection.close()
                    return
                data = {'ok': True, 'result': {'message_id': 88, 'date': int(time.time()),
                        'chat': {'id': 42, 'type': 'private'}, 'from': {'id': 12345, 'is_bot': True},
                        'text': body['text']}}
                if outer.mode == 'wrong-chat': data['result']['chat']['id'] = 43
                if outer.mode == 'reject': data = {'ok': False, 'description': outer.token}
                if outer.mode == 'malformed': data = {'ok': True, 'result': []}
                if outer.mode == 'oversize': data['unused'] = 'z' * 70000
                encoded = json.dumps(data).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()

    def connection(self, host, timeout):
        self.assertEqual(host, 'api.telegram.org')
        self.assertEqual(timeout, 15)
        return http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=timeout)

    def sender(self):
        self.assertTrue((Path(__file__).resolve().parents[1] / 'scripts/hermes_migration_notice.py').exists(),
                        'fixed-destination executable sender missing')
        self.module = importlib.import_module('hermes_migration_notice')
        return self.module.Sender(self.config, self.base, connection=self.connection)

    def test_fixed_destination_send_receipt_and_idempotent_retry(self):
        sender = self.sender()
        receipt = sender.send(self.state)
        self.assertTrue(receipt['delivered'])
        self.assertEqual(receipt['notice_id'], '88')
        self.assertEqual(sender.send(self.state), receipt)
        self.assertEqual(len(self.requests), 1)
        path, request = self.requests[0]
        self.assertEqual(path, '/bot' + self.token + '/sendMessage')
        self.assertEqual(request['chat_id'], 42)
        self.assertIn(self.state['archive_digest'], request['text'])
        self.assertIn(self.state['nonce'], request['text'])
        self.assertIn(self.state['run_id'], request['text'])
        for file in self.base.glob('*.notice.json'):
            self.assertNotIn(self.token, file.read_text())

    def test_unknown_outcome_and_wrong_receipt_never_resend(self):
        sender = self.sender()
        for index, mode in enumerate(('lost', 'wrong-chat', 'reject')):
            with self.subTest(mode=mode):
                self.mode = mode
                state = dict(self.state, run_id=str(index + 1) * 32)
                with self.assertRaises(self.module.Refused) as error:
                    sender.send(state)
                self.assertNotIn(self.token, str(error.exception))
                self.mode = 'ok'
                with self.assertRaises(self.module.Refused):
                    sender.send(state)
        self.assertEqual(len(self.requests), 3)
        for file in self.base.glob('*.notice.json'):
            self.assertEqual(json.loads(file.read_text())['status'], 'uncertain')
            self.assertNotIn(self.token, file.read_text())

    def test_malformed_and_oversize_response_is_sanitized_and_never_retried(self):
        sender = self.sender()
        for index, mode in enumerate(('malformed', 'oversize')):
            with self.subTest(mode=mode):
                self.mode = mode
                state = dict(self.state, run_id=str(index + 1) * 32)
                with self.assertRaises(self.module.Refused):
                    sender.send(state)
                with self.assertRaises(self.module.Refused):
                    sender.send(state)
        self.assertEqual(len(self.requests), 2)

    def test_wrong_owner_chat_expired_or_unadmitted_state_never_contacts_server(self):
        sender = self.sender()
        for change in ({'owner_id': '43'}, {'chat_id': '-1'}, {'prepare_deadline': 0},
                       {'phase': 'PREPARED'}, {'nonce': 'bad'}, {'archive_digest': 'bad'},
                       {'prepare_deadline': float('nan')}):
            with self.subTest(change=change):
                with self.assertRaises(self.module.Refused):
                    sender.send(dict(self.state, **change))
        self.assertEqual(self.requests, [])

    def test_pending_intent_and_payload_change_refuse_duplicate_delivery(self):
        sender = self.sender()
        sender.send(self.state)
        with self.assertRaises(self.module.Refused):
            sender.send(dict(self.state, archive_digest='d' * 64))
        path = next(self.base.glob('*.notice.json'))
        data = json.loads(path.read_text())
        data['status'] = 'uncertain'
        atomic_json(path, data)
        with self.assertRaises(self.module.Refused):
            sender.send(self.state)
        self.assertEqual(len(self.requests), 1)

    def test_no_endpoint_override_and_no_insecure_token(self):
        sender = self.sender()
        token = self.base / 'token'
        token.chmod(0o644)
        with self.assertRaises(self.module.Refused):
            sender.send(self.state)
        token.chmod(0o600)
        config = json.loads(self.config.read_text())
        config['url'] = 'http://127.0.0.1'
        atomic_json(self.config, config)
        with self.assertRaises(self.module.Refused):
            self.module.Sender(self.config, self.base, connection=self.connection)
        self.assertEqual(self.requests, [])

    def test_blocked_notice_is_fixed_outbound_only(self):
        sender = self.sender()
        receipt = sender.send(dict(self.state, phase='BLOCKED'), 'blocked')
        self.assertTrue(receipt['delivered'])
        self.assertIn('BLOCKED', self.requests[0][1]['text'])
        self.assertNotIn('getUpdates', self.requests[0][0])

    def test_cli_does_not_send_without_execute(self):
        import subprocess
        sender = self.sender()
        state_file = self.base / 'controller.json'
        atomic_json(state_file, self.state)
        result = subprocess.run([sys.executable, self.module.__file__, '--config', str(self.config),
                                 '--state-dir', str(self.base), '--controller-state', str(state_file),
                                 '--kind', 'ready'], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.requests, [])
        self.assertFalse(list(self.base.glob('*.notice.json')))


if __name__ == '__main__':
    unittest.main()
