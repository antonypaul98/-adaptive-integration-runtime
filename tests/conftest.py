import os
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from air.postgres import PostgresConfig, PostgresRepository, apply_migrations, bind_tenant_login


@pytest.fixture(scope='session')
def database():
    dsn = os.environ.get('AIR_TEST_DATABASE_URL')
    if not dsn:
        if os.environ.get('CI'):
            pytest.fail('CI must configure PostgreSQL; integration tests cannot silently skip')
        pytest.skip('set AIR_TEST_DATABASE_URL for disposable PostgreSQL integration tests')
    params = psycopg.conninfo.conninfo_to_dict(dsn)
    if params.get('host') not in ('localhost', '127.0.0.1', '::1') or params.get('dbname') != 'air_test':
        pytest.fail('integration suite only accepts a loopback database named air_test')
    # CI creates a fresh database service. No DROP DATABASE/SCHEMA is used.
    with psycopg.connect(dsn, autocommit=True) as admin:
        apply_migrations(admin)
        tenants = [uuid4(), uuid4()]
        logins = []
        for tenant in tenants:
            login, password = 'air_test_' + uuid4().hex, uuid4().hex
            admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(
                sql.Identifier(login), sql.Literal(password)))
            bind_tenant_login(admin, login, tenant)
            login_dsn = psycopg.conninfo.make_conninfo(dsn, user=login, password=password)
            logins.append(login_dsn)
    return {'dsn': dsn, 'tenants': tenants, 'logins': logins}


@pytest.fixture
def repos(database):
    return [PostgresRepository(PostgresConfig(dsn, allow_insecure_local=True))
            for dsn in database['logins']]
