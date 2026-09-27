"""Read-only HTTPS JSON/OpenAPI observer; no credential discovery, AI or deployment.

DNS is validated once per hop and sockets connect ONLY to those numeric addresses.
TLS still verifies the original host. Proxies, cookies and remote $ref fetching are
never used. Request credentials may be supplied explicitly but are never persisted.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import http.client
import ipaddress
import json
import math
import re
import socket
import ssl
import threading
import time
from typing import Any
from urllib.parse import parse_qsl, unquote, urljoin, urlsplit, urlunsplit
from uuid import UUID

from air.postgres import EvidenceTransaction, canonical_json, tenant_uuid


class ObservationError(ValueError):
    """Messages are fixed codes and never include URLs, headers, bodies or credentials."""


@dataclass(frozen=True)
class ObservationLimits:
    connect_timeout: float = 5
    read_timeout: float = 5
    dns_timeout: float = 3
    total_timeout: float = 15
    max_bytes: int = 512_000
    max_redirects: int = 2

    def __post_init__(self):
        for name in ('connect_timeout', 'read_timeout', 'dns_timeout', 'total_timeout'):
            value = getattr(self, name)
            if type(value) not in (int, float) or not 0 < value <= 60:
                raise ValueError('invalid timeout')
        if type(self.max_bytes) is not int or not 1 <= self.max_bytes <= 512_000:
            raise ValueError('invalid response limit')
        if type(self.max_redirects) is not int or not 0 <= self.max_redirects <= 3:
            raise ValueError('invalid redirect limit')


@dataclass(frozen=True)
class Target:
    host: str
    path_and_query: str
    url: str


def validate_url(url: str) -> Target:
    if (not isinstance(url, str) or len(url) > 4096 or
            any(ord(c) <= 32 or ord(c) == 127 for c in url) or '\\' in url):
        raise ObservationError('invalid_url')
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if (parsed.scheme != 'https' or not host or parsed.port not in (None, 443)
                or parsed.username is not None or parsed.password is not None
                or parsed.fragment or '%' in host):
            raise ValueError()
        host = host.encode('idna').decode('ascii').lower()
        # Reject ambiguous numeric forms (octal/hex/short IPv4), trailing dots, and
        # single-label internal hostnames. Valid IP literals are checked below.
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            if (len(host) > 253 or not re.fullmatch(
                r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,62}', host)
                or host.endswith(('.localhost', '.local', '.internal', '.test', '.invalid'))):
                raise ValueError()
        else:
            validate_ip(str(ip))
        path = parsed.path or '/'
        # Prevent request-line injection after intermediary percent decoding.
        if any(ord(c) < 32 or ord(c) == 127 for c in unquote(path + parsed.query)):
            raise ValueError()
        (path + parsed.query).encode('ascii')
        authority = '[' + host + ']' if ':' in host else host
        normalized = urlunsplit(('https', authority, path, parsed.query, ''))
        return Target(host, path + ('?' + parsed.query if parsed.query else ''), normalized)
    except (ValueError, UnicodeError):
        raise ObservationError('invalid_url') from None


_SPECIAL_NETWORKS = tuple(map(ipaddress.ip_network, (
    '192.0.0.0/24', '192.88.99.0/24', '2001::/23', '3fff::/20',
)))


def validate_ip(address: str) -> str:
    try:
        ip = ipaddress.ip_address(address)
        if (any(ip in network for network in _SPECIAL_NETWORKS if network.version == ip.version)
                or not ip.is_global or ip.is_multicast or ip.is_unspecified or ip.is_reserved
                or ip.is_loopback or ip.is_link_local
                or (isinstance(ip, ipaddress.IPv6Address) and
                    (ip.ipv4_mapped is not None or ip.sixtofour is not None or ip.teredo is not None
                     or ip in ipaddress.ip_network('64:ff9b::/96')
                     or ip in ipaddress.ip_network('64:ff9b:1::/48')))):
            raise ValueError()
        return str(ip)
    except ValueError:
        raise ObservationError('blocked_address') from None


_DNS_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix='air-dns')
_DNS_SLOTS = threading.BoundedSemaphore(4)


def resolve_public(host: str, timeout: float) -> tuple[str, ...]:
    if not _DNS_SLOTS.acquire(blocking=False):
        raise ObservationError('dns_busy')
    try:
        future = _DNS_POOL.submit(socket.getaddrinfo, host, 443, 0, socket.SOCK_STREAM)
    except BaseException:
        _DNS_SLOTS.release()
        raise
    future.add_done_callback(lambda _: _DNS_SLOTS.release())
    try:
        records = future.result(timeout=timeout)
        addresses = tuple(sorted({validate_ip(record[4][0]) for record in records}))
        if not addresses:
            raise ObservationError('dns_empty')
        # Reject the entire response if ANY answer is unsafe; never choose only a
        # public answer from a mixed public/private set.
        return addresses
    except FutureTimeout:
        future.cancel()
        raise ObservationError('dns_timeout') from None
    except OSError:
        raise ObservationError('dns_failure') from None


class _HeaderLimitedReader:
    """Bound cumulative status/header/chunk-framing lines as well as body bytes."""
    def __init__(self, stream):
        self.stream = stream
        self.remaining = 16_384

    def readline(self, limit=-1):
        cap = self.remaining + 1
        if limit >= 0:
            cap = min(cap, limit)
        line = self.stream.readline(cap)
        self.remaining -= len(line)
        if self.remaining < 0:
            raise ObservationError('response_headers_too_large')
        return line

    def __getattr__(self, name):
        return getattr(self.stream, name)


class _BoundedHTTPResponse(http.client.HTTPResponse):
    def __init__(self, sock, *args, **kwargs):
        class SocketView:
            def makefile(self, *args, **kwargs):
                return _HeaderLimitedReader(sock.makefile(*args, **kwargs))
        super().__init__(SocketView(), *args, **kwargs)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    response_class = _BoundedHTTPResponse

    def __init__(self, host: str, address: str, timeout: float):
        super().__init__(host, port=443, timeout=timeout, context=ssl.create_default_context())
        self.address = validate_ip(address)
        self._abort_event = threading.Event()
        self._socket_lock = threading.Lock()
        self._interrupt_socket = None

    def abort(self):
        self._abort_event.set()
        with self._socket_lock:
            if self._interrupt_socket is not None:
                try:
                    self._interrupt_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self._interrupt_socket.close()
                self._interrupt_socket = None

    def connect(self):
        # Never call create_connection(host): that would resolve again after validation.
        family = socket.AF_INET6 if ':' in self.address else socket.AF_INET
        raw = socket.socket(family, socket.SOCK_STREAM)
        raw.settimeout(self.timeout)
        try:
            with self._socket_lock:
                if self._abort_event.is_set():
                    raise TimeoutError()
                self.sock = raw
                self._interrupt_socket = raw.dup()
            raw.connect((self.address, 443))
            # Publish the SSL socket before handshake so the total-deadline watchdog
            # can interrupt a peer that stalls or drips during TLS negotiation.
            secure = self._context.wrap_socket(raw, server_hostname=self.host,
                                               do_handshake_on_connect=False)
            with self._socket_lock:
                self.sock = secure
                if self._abort_event.is_set():
                    secure.close()
                    raise TimeoutError()
            secure.do_handshake()
        except BaseException:
            raw.close()
            self.close()
            raise


def _request_headers(headers: dict[str, str] | None) -> dict[str, str]:
    result = {'Accept': 'application/json, application/vnd.oai.openapi+json',
              'Accept-Encoding': 'identity', 'User-Agent': 'AIR-contract-observer/0.1',
              'Connection': 'close'}
    # Deliberate small allowlist: no caller-supplied Host, forwarding or framing headers.
    for key, value in (headers or {}).items():
        if (not isinstance(key, str) or key.lower() not in ('authorization', 'x-api-key')
                or not isinstance(value, str) or len(value) > 4096
                or any(ord(c) < 32 or ord(c) > 126 for c in value)):
            raise ObservationError('invalid_request_headers')
        if any(existing.lower() == key.lower() for existing in result):
            raise ObservationError('duplicate_request_headers')
        result[key] = value
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ObservationError('duplicate_json_key')
        result[key] = value
    return result


def parse_contract(body: bytes) -> dict[str, Any]:
    try:
        value = json.loads(body.decode('utf-8'), object_pairs_hook=_unique_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError):
        raise ObservationError('invalid_json') from None
    if not isinstance(value, dict):
        raise ObservationError('contract_must_be_object')
    # Bound tree complexity independently of wire bytes, and never dereference $ref.
    stack, nodes = [(value, 0)], 0
    while stack:
        node, depth = stack.pop()
        nodes += 1
        if depth > 64 or nodes > 50_000:
            raise ObservationError('contract_complexity_limit')
        if isinstance(node, float) and not math.isfinite(node):
            raise ObservationError('invalid_json_number')
        if isinstance(node, str) and '\x00' in node:
            raise ObservationError('invalid_json_string')
        if isinstance(node, dict):
            if any('\x00' in key for key in node):
                raise ObservationError('invalid_json_key')
            stack.extend((item, depth + 1) for item in node.values())
        elif isinstance(node, list):
            stack.extend((item, depth + 1) for item in node)
    if 'openapi' in value:
        if not isinstance(value['openapi'], str) or not re.fullmatch(r'3\.[01]\.\d+', value['openapi']):
            raise ObservationError('unsupported_openapi_version')
        if not isinstance(value.get('paths'), dict) or not isinstance(value.get('info'), dict):
            raise ObservationError('invalid_openapi_structure')
    return value


_SECRET_KEYS = re.compile(r'(?:password|passwd|secret|token|authorization|cookie|api[_-]?key|credential)', re.I)


def redact_contract(value: Any, key: str = '', *, secrets: tuple[str, ...] = (),
                    _pattern: re.Pattern | None = None) -> Any:
    # Strip example/default material conservatively: specs often embed real payloads.
    # Secret-bearing property names retain their schema shape when their value is an
    # object, but scalar credential values and example material are removed.
    if _pattern is None and any(secrets):
        _pattern = re.compile('|'.join(re.escape(secret) for secret in
            sorted(set(filter(None, secrets)), key=len, reverse=True)))
    if key.lower() in ('example', 'examples', 'default'):
        return '[REDACTED]'
    if _SECRET_KEYS.search(key) and not isinstance(value, (dict, list)):
        return '[REDACTED]'
    if isinstance(value, dict):
        return {k: redact_contract(v, k, _pattern=_pattern) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_contract(item, key, _pattern=_pattern) for item in value]
    if isinstance(value, str):
        if _pattern is not None:
            # One substitution pass: replacements must never be processed again.
            value = _pattern.sub('[REDACTED]', value)
        # Free-form descriptions and extension values can contain arbitrary secrets.
        if key.lower() in ('description', 'summary') or key.startswith('x-'):
            return '[REDACTED]'
        if value.startswith(('https://', 'http://')):
            try:
                parsed = urlsplit(value)
                host = parsed.hostname or ''
            except ValueError:
                return '[REDACTED]'
            # Drop userinfo and ALL query/fragment values in contract URLs and refs.
            host = parsed.hostname or ''
            if ':' in host:
                host = '[' + host + ']'
            return urlunsplit((parsed.scheme, host, parsed.path, '', ''))
        if re.match(r'(?i)^(bearer|basic)\s', value):
            return '[REDACTED]'
    return value


@dataclass(frozen=True)
class ContractSnapshot:
    tenant_id: UUID
    source_id: str
    origin: str
    observed_at: str
    resolved_ip: str
    redirects: int
    contract_json: str
    content_hash: str
    normalization: str = 'air-json-redacted-v1'

    def persist(self, transaction: EvidenceTransaction, observation_key: str) -> dict[str, Any]:
        if transaction.tenant_id != self.tenant_id:
            raise ObservationError('tenant_mismatch')
        return transaction.put('contract_observation', observation_key, {
            'source_id': self.source_id, 'origin': self.origin,
            'observed_at': self.observed_at, 'resolved_ip': self.resolved_ip,
            'redirects': self.redirects, 'content_hash': self.content_hash,
            'normalization': self.normalization, 'contract': json.loads(self.contract_json)})


def contract_changed(previous: ContractSnapshot, current: ContractSnapshot) -> bool:
    if (previous.tenant_id != current.tenant_id or previous.source_id != current.source_id
            or previous.origin != current.origin):
        raise ObservationError('incomparable_snapshots')
    if previous.normalization != current.normalization:
        raise ObservationError('incomparable_normalization')
    return previous.content_hash != current.content_hash


class ContractObserver:
    def __init__(self, limits: ObservationLimits | None = None):
        self.limits = limits or ObservationLimits()

    def observe(self, tenant: str | UUID, source_id: str, url: str, *,
                headers: dict[str, str] | None = None) -> ContractSnapshot:
        tenant_id = tenant_uuid(tenant)
        # Opaque caller-managed ID supplies provenance without persisting URL paths,
        # query tokens, request headers, response headers, or response bodies.
        if not isinstance(source_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', source_id):
            raise ObservationError('invalid_source_id')
        target = validate_url(url)
        original_host = target.host
        request_headers = _request_headers(headers)
        secrets = set(value for _, value in parse_qsl(urlsplit(target.url).query) if value)
        for key, value in (headers or {}).items():
            secrets.add(value)
            if key.lower() == 'authorization' and ' ' in value:
                secrets.add(value.split(' ', 1)[1])
        deadline = time.monotonic() + self.limits.total_timeout
        for hop in range(self.limits.max_redirects + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ObservationError('observation_timeout')
            addresses = resolve_public(target.host, min(self.limits.dns_timeout, remaining))
            address = addresses[0]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ObservationError('observation_timeout')
            connection = _PinnedHTTPSConnection(target.host, address,
                                                 min(self.limits.connect_timeout, remaining))
            watchdog = threading.Timer(remaining, connection.abort)
            watchdog.daemon = True
            watchdog.start()
            response = None
            try:
                connection.connect()
                connection.sock.settimeout(min(self.limits.read_timeout, max(0.001, deadline - time.monotonic())))
                connection.request('GET', target.path_and_query, headers=request_headers)
                response = connection.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    if hop >= self.limits.max_redirects:
                        raise ObservationError('redirect_limit')
                    location = response.getheader('Location')
                    if not location:
                        raise ObservationError('invalid_redirect')
                    redirected = validate_url(urljoin(target.url, location))
                    if redirected.host != original_host:
                        raise ObservationError('cross_origin_redirect')
                    secrets.update(value for _, value in parse_qsl(urlsplit(redirected.url).query) if value)
                    target = redirected
                    continue
                if response.status != 200:
                    raise ObservationError('http_status_rejected')
                content_type = response.getheader('Content-Type', '').split(';', 1)[0].strip().lower()
                if content_type != 'application/json' and not re.fullmatch(r'application/[a-z0-9.+-]+\+json', content_type):
                    raise ObservationError('unsupported_content_type')
                if response.getheader('Content-Encoding', 'identity').strip().lower() != 'identity':
                    raise ObservationError('compressed_response_rejected')
                lengths = response.headers.get_all('Content-Length') or []
                transfer = response.getheader('Transfer-Encoding')
                if len(lengths) > 1 or (lengths and transfer):
                    raise ObservationError('ambiguous_response_framing')
                if transfer and transfer.lower() != 'chunked':
                    raise ObservationError('unsupported_transfer_encoding')
                expected = None
                if lengths:
                    if not re.fullmatch(r'[0-9]{1,10}', lengths[0]):
                        raise ObservationError('invalid_content_length')
                    expected = int(lengths[0])
                    if expected > self.limits.max_bytes:
                        raise ObservationError('response_too_large')
                body = bytearray()
                while True:
                    if time.monotonic() >= deadline:
                        raise ObservationError('observation_timeout')
                    chunk = response.read1(min(16384, self.limits.max_bytes + 1 - len(body)))
                    if not chunk:
                        break
                    body.extend(chunk)
                    if len(body) > self.limits.max_bytes:
                        raise ObservationError('response_too_large')
                if expected is not None and len(body) != expected:
                    raise ObservationError('truncated_response')
                contract = redact_contract(parse_contract(bytes(body)),
                                           secrets=tuple(sorted(secrets, key=len, reverse=True)))
                normalized = canonical_json(contract)
                authority = '[' + original_host + ']' if ':' in original_host else original_host
                return ContractSnapshot(tenant_id, source_id, 'https://' + authority,
                    datetime.now(timezone.utc).isoformat(), address, hop, normalized,
                    sha256(normalized.encode('utf-8')).hexdigest())
            except (OSError, http.client.HTTPException, UnicodeError):
                raise ObservationError('transport_failure') from None
            finally:
                watchdog.cancel()
                connection.abort()
                if response is not None:
                    response.close()
                connection.close()
        raise ObservationError('redirect_limit')
