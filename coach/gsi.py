"""Bounded loopback-only receiver. No outbound networking, CORS or browser API."""
import hmac
import json
import logging
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from .state import normalize


class LocalServer(HTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def start_receiver(port, token, on_state, on_rejected=lambda reason: None,
                   *, on_request_result=None):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(2)

        def log_message(self, *args):
            pass

        def reply(self, status, data):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Connection', 'close')
            self.end_headers()
            try:
                self.wfile.write(body)
            except OSError:
                pass

        def do_GET(self):
            if self.path == '/health':
                self.reply(200, {'service':'Dota AI Coach', 'status':'listening'})
            else:
                self.reply(404, {})

        def outcome(self, classification, status, payload=None, state=None):
            if on_request_result is not None:
                now = time.monotonic_ns()
                on_request_result(dict(classification=classification, http_status=status,
                                       payload=payload, state=state,
                                       read_ns=self.read_ns, parse_ns=self.parse_ns, normalize_ns=self.normalize_ns,
                                       parse_normalize_ns=now - self.after_body_ns if self.after_body_ns is not None else 0,
                                       after_body_start_ns=self.after_body_ns if self.after_body_ns is not None else now))

        def do_POST(self):
            self.after_body_ns = None
            self.read_ns = self.parse_ns = self.normalize_ns = 0
            classification = 'transport'
            if self.path != '/gsi':
                self.reply(404, {})
                self.outcome('path', 404)
                return
            try:
                if self.headers.get('Origin') or self.headers.get('Transfer-Encoding'):
                    raise ValueError('Requisição de navegador/chunked rejeitada.')
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 262144:
                    self.reply(413, {'error':'payload size'})
                    on_rejected('Tamanho inválido')
                    self.outcome('size', 413)
                    return
                read_started_ns = time.monotonic_ns() if on_request_result is not None else None
                body = self.rfile.read(size)
                if len(body) != size:
                    raise ValueError('Pacote incompleto')
                if on_request_result is not None:
                    self.after_body_ns = time.monotonic_ns()
                classification = 'json'
                data = json.loads(body)
                classification = 'shape'
                if not isinstance(data, dict):
                    raise ValueError('JSON inválido')
                auth = data.get('auth')
                received = auth.get('token') if isinstance(auth, dict) else None
                if not isinstance(received, str) or not hmac.compare_digest(received.encode(), token.encode()):
                    self.reply(403, {'error':'auth'})
                    on_rejected('Token diferente: reinstale o GSI pelo painel.')
                    self.outcome('auth', 403)
                    return
                normalize_started_ns = time.monotonic_ns() if on_request_result is not None else None
                state = normalize(data)
                self.normalize_ns = time.monotonic_ns() - normalize_started_ns if on_request_result is not None else 0
                self.read_ns = self.after_body_ns - read_started_ns if on_request_result is not None else 0
            except (ValueError, TypeError, UnicodeError, OSError, RecursionError):
                self.reply(400, {'error':'invalid payload'})
                on_rejected('Pacote GSI inválido')
                self.outcome(classification, 400)
                return
            try:
                on_state(state)
                self.outcome('accepted', 200, data, state)
            except Exception:
                logging.exception('Falha ao processar GSI')
                on_rejected('Erro interno; consulte app.log')
                self.reply(500, {'error':'processing'})
                return
            self.reply(200, {'ok':True})

    server = LocalServer(('127.0.0.1', port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name='gsi-receiver')
    thread.start()
    return server, thread
