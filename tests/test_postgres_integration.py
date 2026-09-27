from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from air.postgres import (ConfigurationError, IdempotencyConflict, MIGRATION_PATH,
                          PostgresConfig, PostgresRepository, apply_migrations,
                          bind_tenant_login)

pytestmark = pytest.mark.postgres


def test_persistence_idempotency_and_audit(database, repos):
    tenant = database['tenants'][0]
    key = uuid4().hex
    with repos[0].transaction(tenant) as tx:
        first = tx.put('contract', key, {'b': 2, 'a': 1})
        repeated = tx.put('contract', key, {'a': 1, 'b': 2})
        assert first == repeated
        assert first['content_hash'] == sha256(first['payload'].encode()).hexdigest()
        assert len([x for x in tx.audit() if x['artifact_id'] == first['artifact_id']]) == 1
    with repos[0].transaction(tenant) as tx:
        assert tx.get('contract', key) == first
    with repos[1].transaction(database['tenants'][1]) as tx:
        assert tx.get('contract', key) is None
        other = tx.put('contract', key, {'a': 3})
        assert other['artifact_id'] != first['artifact_id']


def test_conflicting_key_rolls_back_entire_transaction(database, repos):
    tenant, key, transient = database['tenants'][0], uuid4().hex, uuid4().hex
    with repos[0].transaction(tenant) as tx:
        tx.put('contract', key, {'v': 1})
    with pytest.raises(IdempotencyConflict):
        with repos[0].transaction(tenant) as tx:
            tx.put('contract', transient, {})
            tx.put('contract', key, {'v': 2})
    with repos[0].transaction(tenant) as tx:
        assert tx.get('contract', transient) is None


def test_application_error_rolls_back_artifact_and_audit(database, repos):
    tenant, key = database['tenants'][0], uuid4().hex
    with pytest.raises(RuntimeError):
        with repos[0].transaction(tenant) as tx:
            artifact = tx.put('contract', key, {})
            raise RuntimeError('abort')
    with repos[0].transaction(tenant) as tx:
        assert tx.get('contract', key) is None
        assert all(x['artifact_id'] != artifact['artifact_id'] for x in tx.audit())


def test_cross_tenant_unfiltered_sql(database, repos):
    for i in range(2):
        with repos[i].transaction(database['tenants'][i]) as tx:
            tx.put('contract', uuid4().hex, {'tenant': i})
    with repos[0].transaction(database['tenants'][0]) as tx:
        for table in ('artifacts', 'audit_events'):
            rows = tx._connection.execute(f'SELECT tenant_id FROM air.{table}').fetchall()
            assert rows and all(x['tenant_id'] == database['tenants'][0] for x in rows)


@pytest.mark.parametrize('context', [None, '', 'invalid', 'other'])
def test_missing_malformed_or_forged_context(database, context):
    with psycopg.connect(database['logins'][0], autocommit=True) as conn:
        if context is not None:
            value = str(database['tenants'][1]) if context == 'other' else context
            conn.execute("SELECT set_config('air.tenant_id', %s, false)", (value,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('SELECT air.current_tenant()')
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("""INSERT INTO air.artifacts (tenant_id, artifact_id, kind,
                idempotency_key, payload) VALUES (%s, %s, 'contract', %s, '{}')""",
                (database['tenants'][0], uuid4(), uuid4().hex))


def test_repository_cannot_select_another_tenant(database, repos):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with repos[0].transaction(database['tenants'][1]):
            pytest.fail('forged tenant accepted')


def test_direct_cross_tenant_insert(database, repos):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with repos[0].transaction(database['tenants'][0]) as tx:
            tx._connection.execute("""INSERT INTO air.artifacts
                (tenant_id, artifact_id, kind, idempotency_key, payload)
                VALUES (%s, %s, 'contract', %s, '{}')""",
                (database['tenants'][1], uuid4(), uuid4().hex))


@pytest.mark.parametrize('statement', [
    "UPDATE air.artifacts SET payload = '{}'", 'DELETE FROM air.artifacts',
    'TRUNCATE air.artifacts CASCADE', 'DELETE FROM air.audit_events',
    'UPDATE air.audit_events SET action = action', 'TRUNCATE air.audit_events',
    'ALTER TABLE air.artifacts DISABLE ROW LEVEL SECURITY',
    'ALTER TABLE air.artifacts DISABLE TRIGGER ALL',
    'SELECT * FROM air_private.tenant_logins',
    "INSERT INTO air_private.tenant_logins VALUES ('intruder', gen_random_uuid(), true)",
    'SET ROLE postgres',
    "INSERT INTO air.audit_events VALUES (gen_random_uuid(), gen_random_uuid(), gen_random_uuid(), 'x', 'artifact.created', DEFAULT)",
])
def test_runtime_cannot_mutate_or_bypass(database, repos, statement):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with repos[0].transaction(database['tenants'][0]) as tx:
            tx._connection.execute(statement)


def test_row_security_off_does_not_bypass(database, repos):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with repos[0].transaction(database['tenants'][0]) as tx:
            tx._connection.execute('SET LOCAL row_security = off')
            tx._connection.execute('SELECT * FROM air.artifacts').fetchall()


def test_tenant_context_does_not_survive_commit(database):
    with psycopg.connect(database['logins'][0], autocommit=True) as conn:
        with conn.transaction():
            conn.execute("SELECT set_config('air.tenant_id', %s, true)",
                         (str(database['tenants'][0]),))
            assert conn.execute('SELECT air.current_tenant()').fetchone()[0] == database['tenants'][0]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('SELECT air.current_tenant()')


def test_concurrent_idempotency(database, repos):
    key = uuid4().hex
    def write(_):
        with repos[0].transaction(database['tenants'][0]) as tx:
            return tx.put('contract', key, {'same': True})['artifact_id']
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(write, range(8)))
    assert len(set(ids)) == 1
    with repos[0].transaction(database['tenants'][0]) as tx:
        assert len([e for e in tx.audit() if e['artifact_id'] == ids[0]]) == 1


def test_migration_rerun_checksum_and_rollback(database, tmp_path):
    with psycopg.connect(database['dsn'], autocommit=True) as conn:
        apply_migrations(conn)
        original = conn.execute('SELECT version, checksum FROM air.schema_migrations').fetchall()
        (tmp_path / MIGRATION_PATH.name).write_text(MIGRATION_PATH.read_text() + '\n-- altered')
        with pytest.raises(ConfigurationError, match='checksum'):
            apply_migrations(conn, directory=tmp_path)
        (tmp_path / MIGRATION_PATH.name).write_text(MIGRATION_PATH.read_text())
        (tmp_path / '002_failure.sql').write_text('CREATE TABLE air.rollback_probe (id INT); SELECT 1/0;')
        with pytest.raises(psycopg.errors.DivisionByZero):
            apply_migrations(conn, directory=tmp_path)
        assert conn.execute("SELECT to_regclass('air.rollback_probe')").fetchone()[0] is None
        assert conn.execute('SELECT version, checksum FROM air.schema_migrations').fetchall() == original
        # Real successful upgrade and re-run, then transactional cleanup for isolation.
        (tmp_path / '002_failure.sql').write_text('CREATE TABLE air.upgrade_probe (id INT);')
        apply_migrations(conn, directory=tmp_path)
        apply_migrations(conn, directory=tmp_path)
        assert conn.execute("SELECT to_regclass('air.upgrade_probe')").fetchone()[0]
        with conn.transaction():
            conn.execute('DROP TABLE air.upgrade_probe')
            conn.execute('DELETE FROM air.schema_migrations WHERE version = 2')


def test_runtime_cannot_migrate(database):
    with psycopg.connect(database['logins'][0], autocommit=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            apply_migrations(conn)


def test_admin_cannot_be_runtime(database):
    repo = PostgresRepository(PostgresConfig(database['dsn'], allow_insecure_local=True))
    with pytest.raises(ConfigurationError, match='unprivileged'):
        with repo.transaction(database['tenants'][0]):
            pytest.fail('admin accepted')


def test_rebind_and_disabled_login(database, repos):
    login = psycopg.conninfo.conninfo_to_dict(database['logins'][0])['user']
    with psycopg.connect(database['dsn'], autocommit=True) as admin:
        with pytest.raises(ConfigurationError, match='rebound'):
            bind_tenant_login(admin, login, database['tenants'][1])
        admin.execute('UPDATE air_private.tenant_logins SET enabled=false WHERE login=%s', (login,))
        try:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with repos[0].transaction(database['tenants'][0]):
                    pytest.fail('disabled binding accepted')
        finally:
            admin.execute('UPDATE air_private.tenant_logins SET enabled=true WHERE login=%s', (login,))


def test_database_hash_and_timestamp_cannot_be_forged(database, repos):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with repos[0].transaction(database['tenants'][0]) as tx:
            tx._connection.execute("""INSERT INTO air.artifacts
                (tenant_id, artifact_id, kind, idempotency_key, payload, created_at)
                VALUES (%s, %s, 'contract', %s, '{}', '2000-01-01')""",
                (database['tenants'][0], uuid4(), uuid4().hex))


def test_audit_failure_rolls_back_artifact(database, repos):
    tenant, key = database['tenants'][0], uuid4().hex
    # Temporary administrator constraint injects an audit failure, not an application mock.
    with psycopg.connect(database['dsn'], autocommit=True) as admin:
        admin.execute('ALTER TABLE air.audit_events ADD CONSTRAINT fail_audit CHECK (false) NOT VALID')
        try:
            with pytest.raises(psycopg.errors.CheckViolation):
                with repos[0].transaction(tenant) as tx:
                    tx.put('contract', key, {})
        finally:
            admin.execute('ALTER TABLE air.audit_events DROP CONSTRAINT fail_audit')
    with repos[0].transaction(tenant) as tx:
        assert tx.get('contract', key) is None
