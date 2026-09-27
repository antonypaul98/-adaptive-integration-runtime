from dataclasses import FrozenInstanceError, replace
from email.message import Message
from io import BytesIO
import json
import socket
from uuid import uuid4

import pytest

from air import observer as obs


@pytest.mark.parametrize('url', [
    'http://example.com/spec', 'file:///etc/passwd', 'https://user:pass@example.com',
    'https://localhost/x', 'https://127.0.0.1', 'https://10.0.0.1',
    'https://169.254.169.254/latest/meta-data/', 'https://[::1]', 'https://[::ffff:8.8.8.8]',
    'https://example.com:8443', 'https://example.com/#x', 'https://example.com\\@127.0.0.1',
    'https://2130706433', 'https://0177.0.0.1', 'https://0x7f000001',
    'https://example.com\r\nX:bad', 'https://example.com/%0d%0aX:bad',
    'https://example.com.', 'https://[fe80::1%25eth0]', 'https://foo.internal',
])
def test_invalid_targets(url):
    with pytest.raises(obs.ObservationError):
        obs.validate_url(url)


@pytest.mark.parametrize('address', ['0.0.0.0', '127.0.0.1', '10.10.1.1', '172.16.0.1',
    '192.168.0.1', '169.254.169.254', '100.64.0.1', '192.0.0.9', '192.0.2.1',
    '192.88.99.1', '198.18.0.1', '198.51.100.1', '203.0.113.1', '224.0.0.1',
    '255.255.255.255', '::', '::1', 'fc00::1', 'fe80::1', 'ff02::1', '2001:db8::1',
    '2002:0808:0808::1', '64:ff9b::808:808', '2001::1', '3fff::1'])
def test_reserved_addresses_blocked(address):
    with pytest.raises(obs.ObservationError, match='blocked_address'):
        obs.validate_ip(address)


def test_public_addresses_and_url():
    assert obs.validate_ip('8.8.8.8') == '8.8.8.8'
    assert obs.validate_ip('2606:4700:4700::1111') == '2606:4700:4700::1111'
    assert obs.validate_url('https://EXAMPLE.com:443/spec?v=1').url == 'https://example.com/spec?v=1'


def test_mixed_dns_is_rejected(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a: [
        (2, 1, 6, '', ('8.8.8.8', 443)), (2, 1, 6, '', ('127.0.0.1', 443))])
    with pytest.raises(obs.ObservationError, match='blocked_address'):
        obs.resolve_public('example.com', 1)


def test_dns_failure_and_empty(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a: [])
    with pytest.raises(obs.ObservationError, match='dns_empty'):
        obs.resolve_public('example.com', 1)
    def fail(*_):
        raise socket.gaierror('SECRET HOST')
    monkeypatch.setattr(socket, 'getaddrinfo', fail)
    with pytest.raises(obs.ObservationError, match='dns_failure') as exc:
        obs.resolve_public('example.com', 1)
    assert 'SECRET' not in str(exc.value)


def test_pinned_connection_uses_numeric_address_and_tls_hostname(monkeypatch):
    events = []
    class FakeSocket:
        def settimeout(self, timeout):
            pass
        def dup(self):
            return self
        def connect(self, endpoint):
            events.append(endpoint)
        def do_handshake(self):
            events.append('handshake')
        def close(self):
            pass
        def shutdown(self, _):
            pass
    class Context:
        def wrap_socket(self, raw, **kwargs):
            events.append(kwargs)
            return raw
    monkeypatch.setattr(socket, 'socket', lambda *a: FakeSocket())
    monkeypatch.setattr(obs.ssl, 'create_default_context', lambda: Context())
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a: pytest.fail('unexpected second DNS lookup'))
    conn = obs._PinnedHTTPSConnection('example.com', '8.8.8.8', 1)
    conn.connect()
    assert events == [('8.8.8.8', 443), {'server_hostname': 'example.com',
                       'do_handshake_on_connect': False}, 'handshake']
    conn.abort()
    conn.close()


class FakeResponse:
    def __init__(self, body=b'{"type":"object"}', *, status=200, headers=None):
        self.status, self.body = status, BytesIO(body)
        self.headers = Message()
        for key, value in (headers or {'Content-Type': 'application/json'}).items():
            self.headers[key] = value
        self.closed = False
    def getheader(self, key, default=None):
        return self.headers.get(key, default)
    def read1(self, size):
        return self.body.read(size)
    def close(self):
        self.closed = True


@pytest.fixture
def network(monkeypatch):
    responses, calls = [], []
    class Connection:
        def __init__(self, host, address, timeout):
            calls.append((host, address))
            self.sock = self
        def connect(self):
            pass
        def settimeout(self, timeout):
            pass
        def request(self, method, path, headers):
            calls.append((method, path, headers))
        def getresponse(self):
            return responses.pop(0)
        def abort(self):
            pass
        def close(self):
            pass
    monkeypatch.setattr(obs, 'resolve_public', lambda *a: ('8.8.8.8',))
    monkeypatch.setattr(obs, '_PinnedHTTPSConnection', Connection)
    return responses, calls


def observe(**kwargs):
    return obs.ContractObserver().observe(uuid4(), 'source_1', 'https://example.com/spec', **kwargs)


def test_redaction_provenance_hash_and_immutability(network):
    responses, calls = network
    responses.append(FakeResponse(json.dumps({'type': 'object', 'example': {'person': 'Alice'},
        'authorization': 'secret', 'description': 'customer data', 'enum': ['one', 'two'],
        'url': 'https://user:password@example.com/path?secret=abc#fragment',
        'echo': 'key-123'}).encode()))
    result = obs.ContractObserver().observe(uuid4(), 'source_1',
        'https://example.com/secret-path?api_key=key-123', headers={'Authorization': 'Bearer secret'})
    assert result.origin == 'https://example.com'
    for secret in ('Alice', 'customer data', 'key-123', 'secret-path', 'password', 'fragment'):
        assert secret not in repr(result)
    assert json.loads(result.contract_json)['enum'] == ['one', 'two']
    assert calls[1][0] == 'GET'
    assert calls[1][2]['Accept-Encoding'] == 'identity'
    with pytest.raises(FrozenInstanceError):
        result.content_hash = 'changed'


def test_deterministic_hash_and_change_scope(network):
    responses, _ = network
    responses.extend([FakeResponse(b'{"b":2,"a":1}'), FakeResponse(b'{"a":1,"b":2}')])
    tenant = uuid4()
    a = obs.ContractObserver().observe(tenant, 'source', 'https://example.com/a')
    b = obs.ContractObserver().observe(tenant, 'source', 'https://example.com/a')
    assert not obs.contract_changed(a, b)
    assert obs.contract_changed(a, replace(b, content_hash='changed'))
    with pytest.raises(obs.ObservationError, match='incomparable_snapshots'):
        obs.contract_changed(a, replace(b, tenant_id=uuid4()))
    with pytest.raises(obs.ObservationError, match='incomparable_snapshots'):
        obs.contract_changed(a, replace(b, source_id='other'))


@pytest.mark.parametrize('headers,body,error', [
    ({'Content-Type': 'text/html'}, b'<html>', 'content_type'),
    ({'Content-Type': 'application/yaml'}, b'openapi: 3', 'content_type'),
    ({'Content-Type': 'application/json', 'Content-Encoding': 'gzip'}, b'{}', 'compressed'),
    ({'Content-Type': 'application/json', 'Content-Length': '9999999'}, b'{}', 'too_large'),
    ({'Content-Type': 'application/json', 'Content-Length': '-1'}, b'{}', 'invalid_content_length'),
    ({'Content-Type': 'application/json', 'Content-Length': '10'}, b'{}', 'truncated'),
    ({'Content-Type': 'application/json', 'Content-Length': '2', 'Transfer-Encoding': 'chunked'}, b'{}', 'ambiguous'),
    ({'Content-Type': 'application/json'}, b'x'*512001, 'too_large'),
])
def test_bad_responses(network, headers, body, error):
    responses, _ = network
    response = FakeResponse(body, headers=headers)
    responses.append(response)
    with pytest.raises(obs.ObservationError, match=error):
        observe()
    assert response.closed


@pytest.mark.parametrize('body', [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}',
    b'{"a":"\\u0000"}', b'[]', b'\xff', b'{',
    b'{"openapi":"2.0","info":{},"paths":{}}', b'{"openapi":"3.1.0"}'])
def test_invalid_json_contracts(body):
    with pytest.raises(obs.ObservationError):
        obs.parse_contract(body)


def test_complexity_bound():
    body = ('{"a":'*70 + '{}' + '}'*70).encode()
    with pytest.raises(obs.ObservationError, match='complexity'):
        obs.parse_contract(body)


def test_openapi_normalization_does_not_fetch_refs():
    contract = {'openapi': '3.1.0', 'info': {'title': 'test'}, 'paths': {},
                '$ref': 'http://169.254.169.254/metadata?secret=token'}
    parsed = obs.parse_contract(json.dumps(contract).encode())
    assert obs.redact_contract(parsed)['$ref'] == 'http://169.254.169.254/metadata'


@pytest.mark.parametrize('location', ['http://example.com/x', 'https://127.0.0.1/',
    'https://other.example.org/spec', '//169.254.169.254/'])
def test_unsafe_redirect(network, location):
    responses, _ = network
    responses.append(FakeResponse(status=302, headers={'Location': location}))
    with pytest.raises(obs.ObservationError):
        observe()


def test_redirect_revalidates_dns_and_blocks_rebinding(network, monkeypatch):
    responses, calls = network
    responses.append(FakeResponse(status=302, headers={'Location': '/next'}))
    lookup = []
    def resolve(*_):
        lookup.append(1)
        if len(lookup) > 1:
            raise obs.ObservationError('blocked_address')
        return ('8.8.8.8',)
    monkeypatch.setattr(obs, 'resolve_public', resolve)
    with pytest.raises(obs.ObservationError, match='blocked_address'):
        observe()
    assert len(lookup) == 2
    assert len(calls) == 2


def test_same_origin_redirect_and_limit(network):
    responses, _ = network
    responses.extend([FakeResponse(status=302, headers={'Location': '/next'}), FakeResponse()])
    assert observe().redirects == 1
    responses.extend([FakeResponse(status=302, headers={'Location': '/next'}) for _ in range(3)])
    with pytest.raises(obs.ObservationError, match='redirect_limit'):
        observe()


@pytest.mark.parametrize('headers', [{'Host': '127.0.0.1'}, {'Cookie': 'session=secret'},
    {'Authorization': 'Bearer x\r\nX: y'}, {'X-Forwarded-Host': 'internal'},
    {'authorization': 'a', 'Authorization': 'b'}])
def test_unsafe_request_headers(headers):
    with pytest.raises(obs.ObservationError):
        obs._request_headers(headers)


def test_transport_error_has_no_sensitive_details(network, monkeypatch):
    class FailedConnection:
        def __init__(self, *a):
            pass
        def connect(self):
            raise OSError('password=SECRET')
        def abort(self):
            pass
        def close(self):
            pass
    monkeypatch.setattr(obs, '_PinnedHTTPSConnection', FailedConnection)
    with pytest.raises(obs.ObservationError) as exc:
        observe()
    assert str(exc.value) == 'transport_failure'
    assert exc.value.__suppress_context__
