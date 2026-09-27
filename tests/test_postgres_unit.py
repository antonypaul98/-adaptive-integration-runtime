from hashlib import sha256
from uuid import UUID

import pytest

from air.postgres import ConfigurationError, PostgresConfig, canonical_json, tenant_uuid


@pytest.mark.parametrize('value', [None, '', ' ', 'not-a-uuid', 123, '00000000-0000-0000-0000-000000000000'])
def test_invalid_tenant(value):
    with pytest.raises(ValueError):
        tenant_uuid(value)


def test_uuid_and_canonical_content():
    value = UUID('12345678-1234-1234-1234-123456789abc')
    assert tenant_uuid(value) == value
    a = canonical_json({'z': [1, 2], 'a': 'é'})
    b = canonical_json({'a': 'é', 'z': [1, 2]})
    assert a == b
    assert sha256(a.encode()).hexdigest() == sha256(b.encode()).hexdigest()


@pytest.mark.parametrize('payload', [[], {'x': float('nan')}, {'x': float('inf')}, {'x': 'a' * 1048576}])
def test_reject_invalid_payload(payload):
    with pytest.raises(ValueError):
        canonical_json(payload)


@pytest.mark.parametrize('dsn,local', [('', False), ('host=db sslmode=require', False),
    ('host=example.com', True), ('host=localhost hostaddr=8.8.8.8', True),
    ('host=localhost,example.com', True)])
def test_unsafe_connection_config(dsn, local):
    with pytest.raises(ConfigurationError):
        PostgresConfig(dsn, allow_insecure_local=local)


def test_secrets_not_in_config_repr():
    config = PostgresConfig('host=db password=secret sslmode=verify-full')
    assert 'secret' not in repr(config)
    assert 'password' not in repr(config)


@pytest.mark.parametrize('timeout', [0, -1, True, 300001, 1.5])
def test_bad_timeout(timeout):
    with pytest.raises(ConfigurationError):
        PostgresConfig('sslmode=verify-full', connect_timeout=timeout)


def test_config_environment(monkeypatch):
    monkeypatch.setenv('AIR_DATABASE_URL', 'host=localhost dbname=air_test')
    monkeypatch.setenv('AIR_ALLOW_INSECURE_LOCAL', '1')
    assert PostgresConfig.from_env().allow_insecure_local
