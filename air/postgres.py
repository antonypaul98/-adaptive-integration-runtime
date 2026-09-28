"""PostgreSQL evidence persistence. A database login is bound to exactly one tenant.

The migration administrator and tenant runtime DSNs MUST be separate credentials.
No production deployment operation is provided by this module.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any, Iterator
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

MIGRATION_PATH = Path(__file__).with_name("migrations") / "001_tenant_isolation.sql"
MAX_PAYLOAD_BYTES = 1_048_576


class ConfigurationError(ValueError):
    pass


class IdempotencyConflict(ValueError):
    pass


def tenant_uuid(value: str | UUID) -> UUID:
    if not isinstance(value, (str, UUID)):
        raise ValueError("tenant must be a UUID")
    parsed = UUID(str(value))
    if parsed.int == 0:
        raise ValueError("nil tenant is not allowed")
    return parsed


def canonical_json(value: dict[str, Any]) -> str:
    if not isinstance(value, dict):
        raise ValueError("evidence payload must be an object")
    result = json.dumps(value, sort_keys=True, separators=(",", ":"),
                        ensure_ascii=False, allow_nan=False)
    if len(result.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ValueError("evidence exceeds size limit")
    return result


def migration_sql() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def apply_migrations(connection: psycopg.Connection, *, directory: Path | None = None) -> None:
    """Atomically upgrade with a transaction lock and immutable migration checksums.

    Connection must be idle: never commit a caller's unrelated transaction.
    Reruns verify checksums, and failures roll back schema, ledger and data together.
    """
    if connection.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        raise ConfigurationError("migrations require an idle connection")
    paths = sorted((directory or MIGRATION_PATH.parent).glob("[0-9][0-9][0-9]_*.sql"))
    if not paths:
        raise ConfigurationError("no migrations found")
    versions = [int(path.name.split("_", 1)[0]) for path in paths]
    if versions != list(range(1, len(paths) + 1)):
        raise ConfigurationError("migration sequence must be contiguous")
    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(714208315, 1)")
        connection.execute("CREATE SCHEMA IF NOT EXISTS air")
        connection.execute("REVOKE CREATE ON SCHEMA air FROM PUBLIC")
        connection.execute("""CREATE TABLE IF NOT EXISTS air.schema_migrations (
            version INTEGER PRIMARY KEY, checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp())""")
        connection.execute("REVOKE ALL ON air.schema_migrations FROM PUBLIC")
        applied = dict(connection.execute(
            "SELECT version, checksum FROM air.schema_migrations ORDER BY version").fetchall())
        if sorted(applied) != versions[:len(applied)]:
            raise ConfigurationError("database has unknown or noncontiguous migrations")
        for version, path in zip(versions, paths):
            source = path.read_text(encoding="utf-8")
            checksum = sha256(source.encode("utf-8")).hexdigest()
            if version in applied:
                if applied[version] != checksum:
                    raise ConfigurationError("applied migration checksum differs")
                continue
            connection.execute(source)
            connection.execute("INSERT INTO air.schema_migrations VALUES (%s, %s, DEFAULT)",
                               (version, checksum))


def bind_tenant_login(connection: psycopg.Connection, login: str, tenant: str | UUID) -> None:
    """Administrator-only binding of an EXISTING unprivileged login; never rebinds.

    Credentials are provisioned outside AIR. This function does not handle passwords.
    Do not grant tenant roles membership in other login roles or object-owner roles.
    """
    tenant_id = tenant_uuid(tenant)
    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 714208315))", (login,))
        role = connection.execute("""SELECT rolcanlogin AND NOT (rolsuper OR rolbypassrls
            OR rolcreaterole OR rolcreatedb OR rolreplication) FROM pg_roles
            WHERE rolname = %s""", (login,)).fetchone()
        if not role or not role[0]:
            raise ConfigurationError("tenant login must be an unprivileged LOGIN role")
        if connection.execute("""SELECT 1 FROM pg_auth_members m
            JOIN pg_roles r ON r.oid = m.member JOIN pg_roles parent ON parent.oid = m.roleid
            WHERE r.rolname = %s AND parent.rolname <> 'air_runtime'""", (login,)).fetchone():
            raise ConfigurationError("tenant login has other role memberships")
        existing = connection.execute(
            "SELECT tenant_id FROM air_private.tenant_logins WHERE login = %s", (login,)
        ).fetchone()
        if existing and existing[0] != tenant_id:
            raise ConfigurationError("tenant login cannot be rebound")
        connection.execute("""INSERT INTO air_private.tenant_logins(login, tenant_id)
            VALUES (%s, %s) ON CONFLICT (login) DO NOTHING""", (login, tenant_id))
        connection.execute(sql.SQL("GRANT air_runtime TO {}").format(sql.Identifier(login)))


@dataclass(frozen=True)
class PostgresConfig:
    dsn: str = field(repr=False)
    connect_timeout: int = 5
    statement_timeout_ms: int = 10_000
    lock_timeout_ms: int = 3_000
    allow_insecure_local: bool = False

    def __post_init__(self) -> None:
        for name in ("connect_timeout", "statement_timeout_ms", "lock_timeout_ms"):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= 300_000:
                raise ConfigurationError("timeouts must be positive bounded integers")
        if not self.dsn:
            raise ConfigurationError("AIR_DATABASE_URL is required")
        try:
            params = psycopg.conninfo.conninfo_to_dict(self.dsn)
        except psycopg.Error:
            raise ConfigurationError("invalid database configuration") from None
        if self.allow_insecure_local:
            if params.get("host") not in ("127.0.0.1", "::1", "localhost"):
                raise ConfigurationError("insecure mode requires a loopback database")
            if params.get("hostaddr") not in (None, "127.0.0.1", "::1"):
                raise ConfigurationError("insecure mode rejects non-loopback hostaddr")
        elif params.get("sslmode") != "verify-full":
            raise ConfigurationError("production connections require sslmode=verify-full")

    @classmethod
    def from_env(cls) -> PostgresConfig:
        return cls(dsn=os.environ.get("AIR_DATABASE_URL", ""),
                   allow_insecure_local=os.environ.get("AIR_ALLOW_INSECURE_LOCAL") == "1")


class PostgresRepository:
    """Short-lived connections bound to one login; commit/rollback and close on every use.

    This avoids ambient/shared tenant session state and unbounded idle connections.
    Authentication middleware must select an authorized tenant's credential, never a
    client-provided DSN. Database RLS also verifies the login binding independently.
    """
    def __init__(self, config: PostgresConfig):
        self.config = config

    @contextmanager
    def transaction(self, tenant: str | UUID) -> Iterator[EvidenceTransaction]:
        tenant_id = tenant_uuid(tenant)
        with psycopg.connect(self.config.dsn, autocommit=True, row_factory=dict_row,
                             connect_timeout=self.config.connect_timeout,
                             application_name="air-evidence") as connection:
            with connection.transaction():
                connection.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                connection.execute("SET LOCAL search_path = pg_catalog, air")
                connection.execute("SET LOCAL row_security = on")
                for key, value in (("statement_timeout", self.config.statement_timeout_ms),
                                   ("lock_timeout", self.config.lock_timeout_ms),
                                   ("idle_in_transaction_session_timeout", 30_000),
                                   ("air.tenant_id", str(tenant_id))):
                    connection.execute("SELECT set_config(%s, %s, true)", (key, str(value)))
                roles = connection.execute("""SELECT rolsuper, rolbypassrls, rolcreaterole,
                    rolcreatedb, rolreplication FROM pg_roles WHERE rolname IN (current_user, session_user)""").fetchall()
                if not roles or any(any(role.values()) for role in roles):
                    raise ConfigurationError("runtime credentials must be unprivileged")
                owner = connection.execute("""SELECT 1 FROM pg_class c JOIN pg_namespace n
                    ON c.relnamespace = n.oid WHERE n.nspname IN ('air', 'air_private')
                    AND pg_has_role(current_user, c.relowner, 'MEMBER') LIMIT 1""").fetchone()
                if owner:
                    raise ConfigurationError("runtime credentials must not own database objects")
                connection.execute("SELECT air.current_tenant()")
                yield EvidenceTransaction(connection, tenant_id)


class EvidenceTransaction:
    def __init__(self, connection: psycopg.Connection, tenant_id: UUID):
        self._connection = connection
        self.tenant_id = tenant_id

    def put(self, kind: str, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(kind, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", kind):
            raise ValueError("invalid artifact kind")
        if not isinstance(key, str) or not 1 <= len(key) <= 256 or "\x00" in key:
            raise ValueError("invalid idempotency key")
        serialized = canonical_json(payload)
        # DO NOTHING avoids issuing UPDATE against immutable evidence. Under READ
        # COMMITTED the following SELECT sees a concurrent winner after INSERT waits.
        self._connection.execute("""INSERT INTO air.artifacts
            (tenant_id, artifact_id, kind, idempotency_key, payload)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, kind, idempotency_key) DO NOTHING""",
            (self.tenant_id, uuid4(), kind, key, serialized))
        artifact = self.get(kind, key)
        if artifact is None or artifact["payload"] != serialized:
            raise IdempotencyConflict("key already identifies different immutable evidence")
        return artifact

    def get(self, kind: str, key: str) -> dict[str, Any] | None:
        return self._connection.execute("""SELECT * FROM air.artifacts
            WHERE tenant_id = %s AND kind = %s AND idempotency_key = %s""",
            (self.tenant_id, kind, key)).fetchone()

    def get_by_id(self, artifact_id: str | UUID, *, kind: str) -> dict[str, Any] | None:
        """Resolve immutable evidence by identity through both tenant predicate and RLS."""
        return self._connection.execute("""SELECT * FROM air.artifacts
            WHERE tenant_id = %s AND artifact_id = %s AND kind = %s""",
            (self.tenant_id, UUID(str(artifact_id)), kind)).fetchone()

    def audit(self) -> list[dict[str, Any]]:
        return self._connection.execute("""SELECT * FROM air.audit_events
            WHERE tenant_id = %s ORDER BY created_at, event_id""", (self.tenant_id,)).fetchall()
