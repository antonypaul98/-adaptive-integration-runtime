"""Actual HTTPS sockets and certificates; only socket routing and DNS are substituted.

The transport always receives a public pinned IP. Test routing maps that socket to
an ephemeral loopback TLS server so no Internet service or credential is needed.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import ssl
import subprocess
import threading
import time
from uuid import uuid4

import pytest

from air import observer as obs


@pytest.fixture
def tls_server(tmp_path, monkeypatch):
    cert, key = tmp_path / 'cert.pem', tmp_path / 'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                    '-keyout', str(key), '-out', str(cert), '-days', '1',
                    '-subj', '/CN=observer.example.com', '-addext',
                    'subjectAltName=DNS:observer.example.com'], check=True, capture_output=True)
    requests = []
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *args):
            pass
        def do_GET(self):
            requests.append((self.command, self.path, self.headers.get('Host')))
            try:
                if self.path == '/slow-headers':
                    self.connection.sendall(b'HTTP/1.1 200 OK\r\nX-Drip: ')
                    for _ in range(40):
                        self.connection.sendall(b'x')
                        time.sleep(.02)
                    return
                self.send_response(200)
                if self.path == '/headers':
                    self.send_header('X-Large', 'x' * 20_000)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Connection', 'close')
                if self.path in ('/chunked', '/slow-chunk'):
                    self.send_header('Transfer-Encoding', 'chunked')
                    self.end_headers()
                    if self.path == '/slow-chunk':
                        # A chunk header can drip without read1 returning. The
                        # watchdog must still interrupt after http.client closes
                        # its owning connection and retains only a response file.
                        for _ in range(40):
                            self.wfile.write(b'0')
                            self.wfile.flush()
                            time.sleep(.02)
                    else:
                        self.wfile.write(b'2\r\n{}\r\n0\r\n\r\n')
                elif self.path == '/truncated':
                    self.send_header('Content-Length', '10')
                    self.end_headers()
                    self.wfile.write(b'{}')
                elif self.path == '/oversize':
                    self.end_headers()
                    self.wfile.write(b'x' * 1000)
                else:
                    body = b'{"openapi":"3.1.0","info":{"title":"Demo"},"paths":{}}'
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
            except OSError:
                pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
    thread.start()
    public = '8.8.8.8'
    real_socket = socket.socket
    class RoutedSocket(real_socket):
        def connect(self, address):
            if address == (public, 443):
                address = server.server_address
            return super().connect(address)
    trusted = ssl.create_default_context(cafile=str(cert))
    real_context = ssl.create_default_context
    monkeypatch.setattr(socket, 'socket', RoutedSocket)
    monkeypatch.setattr(obs, 'resolve_public', lambda *a: (public,))
    monkeypatch.setattr(ssl, 'create_default_context', lambda: trusted)
    yield requests, real_context
    server.shutdown()
    server.server_close()
    thread.join(timeout=1)


def observe(path, limits=None):
    return obs.ContractObserver(limits).observe(uuid4(), 'demo', 'https://observer.example.com' + path)


def test_actual_tls_and_http(tls_server):
    requests, _ = tls_server
    result = observe('/spec')
    assert '3.1.0' in result.contract_json
    assert result.resolved_ip == '8.8.8.8'
    assert requests == [('GET', '/spec', 'observer.example.com')]
    assert observe('/chunked').contract_json == '{}'


def test_untrusted_certificate_rejected(tls_server, monkeypatch):
    requests, real_context = tls_server
    monkeypatch.setattr(ssl, 'create_default_context', real_context)
    with pytest.raises(obs.ObservationError, match='transport_failure'):
        observe('/spec')
    assert requests == []


def test_certificate_hostname_is_verified(tls_server):
    requests, _ = tls_server
    with pytest.raises(obs.ObservationError, match='transport_failure'):
        obs.ContractObserver().observe(uuid4(), 'demo', 'https://wrong.example.com/spec')
    assert requests == []


@pytest.mark.parametrize('path,error', [('/truncated', 'truncated_response'), ('/oversize', 'response_too_large'),
                                        ('/headers', 'response_headers_too_large')])
def test_real_body_bounds(tls_server, path, error):
    with pytest.raises(obs.ObservationError, match=error):
        observe(path, obs.ObservationLimits(max_bytes=100))


@pytest.mark.parametrize('path', ['/slow-headers', '/slow-chunk'])
def test_total_deadline_interrupts_drip_feed(tls_server, path):
    start = time.monotonic()
    with pytest.raises(obs.ObservationError):
        observe(path, obs.ObservationLimits(total_timeout=.15, read_timeout=1))
    assert time.monotonic() - start < .65


def test_dns_deadline_and_bounded_slots(monkeypatch):
    release = threading.Event()
    def stuck(*_):
        release.wait(timeout=2)
        return [(2, 1, 6, '', ('8.8.8.8', 443))]
    monkeypatch.setattr(socket, 'getaddrinfo', stuck)
    try:
        for _ in range(4):
            with pytest.raises(obs.ObservationError, match='dns_timeout'):
                obs.resolve_public('example.com', .01)
        with pytest.raises(obs.ObservationError, match='dns_busy'):
            obs.resolve_public('example.com', .01)
    finally:
        release.set()
