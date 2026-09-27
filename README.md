# AIR — Adaptive Integration Runtime

Evidence-first integration runtime. Current implementation: PostgreSQL evidence
storage with database-enforced tenant isolation. See [PROJECT_STATE.md](PROJECT_STATE.md)
for executed validation and remaining work.

Lifecycle: observe → detect → propose → sandbox → replay → verify → approve → deploy.
Human approval is mandatory for consequential changes. There is no deployment
executor and no LLM call in this implementation.

## Install and test

```sh
python -m pip install '.[test]'
python -m pytest -m 'not postgres'
```

The full suite requires a **disposable**, fresh loopback PostgreSQL database named
`air_test`, accessible through `AIR_TEST_DATABASE_URL`. Tests create roles and
schemas and inject temporary database constraints. Never point them at production.
CI runs the full suite against PostgreSQL 16 and 17 and fails if the database is
missing. Without that variable, local database tests are explicitly skipped.

## PostgreSQL provisioning

1. Provision a dedicated migration administrator. Use its connection to call
   `air.postgres.apply_migrations(connection)` on an idle psycopg connection.
   It needs database schema/role creation privileges. Applied SQL is checksummed;
   never edit an applied migration. Add the next numbered migration instead.
2. Provision separate unprivileged LOGIN credentials for each tenant outside AIR.
   Call `bind_tenant_login(admin_connection, login_name, tenant_uuid)` to bind each
   login. Do not grant membership in other tenant, owner, or privileged roles.
3. Give the process the appropriate tenant's DSN through `AIR_DATABASE_URL`, with
   `sslmode=verify-full` and a trusted certificate root. Never use administrator
   credentials at runtime. Configuration objects hide DSNs from their repr.
4. Use explicit tenant transactions:

```python
from air.postgres import PostgresConfig, PostgresRepository

repo = PostgresRepository(PostgresConfig.from_env())
with repo.transaction(authenticated_tenant_uuid) as tx:
    evidence = tx.put('contract', observation_id, {'schema': sanitized_schema})
    same_evidence = tx.get('contract', observation_id)
```

`AIR_ALLOW_INSECURE_LOCAL=1` is only for explicit loopback development connections.
The default requires certificate-verified TLS. A deployment should bound request
concurrency/database connections and rotate credentials externally. Connections
are closed on every transaction; tenant state is never kept in a shared pool.

A repeated key and identical canonical payload returns the existing evidence.
Different content under the same tenant/kind/key raises `IdempotencyConflict`.
Exceptions must escape the transaction context to roll back the whole unit of
work. A database error always leaves the transaction aborted until rollback.

## Isolation and trust boundary

RLS verifies both transaction-local tenant context and the authenticated database
`session_user`. Setting a different tenant variable cannot change the login's
binding. Artifact and audit tables force RLS; runtime receives only SELECT and
restricted INSERT permissions. Triggers reject update/delete/truncate and append
an audit event atomically with every insert. Hashes and timestamps are generated
in PostgreSQL. Application serialization is deterministic UTF-8 JSON.

Database superusers, migration administrators and credential provisioning are
trusted: an administrator can change DDL or grant bypass privileges. This is not
protection against a malicious database administrator. Never allow end users to
choose DSNs or reuse one tenant login for another tenant. Disable a binding with
an administrator update to `air_private.tenant_logins.enabled`; new statements
then fail closed. Existing statement snapshots follow PostgreSQL MVCC semantics.

Migrations are forward-only. A failed upgrade rolls back atomically. Operational
rollback uses a reviewed forward fix or backup restoration, never automatic
artifact deletion. Database backups, retention, role rotation, encrypted disks,
and external tamper-evident archives remain operator responsibilities.
