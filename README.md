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

## Read-only REST/OpenAPI JSON observation

```python
from air.observer import ContractObserver, contract_changed

snapshot = ContractObserver().observe(
    authenticated_tenant_uuid, 'billing-contract',
    'https://api.example.com/openapi.json',
    headers={'Authorization': short_lived_read_only_credential},
)
with repo.transaction(authenticated_tenant_uuid) as tx:
    snapshot.persist(tx, observation_id)
```

Only explicitly configured read-only contract endpoints should be observed.
Provide an opaque `source_id` that your application binds to that endpoint and
reuse the **same snapshot and observation ID** when retrying persistence. A new
fetch is a new observation with its own timestamp and ID. `contract_changed(a,b)`
compares deterministic normalized hashes only within the same tenant/source/origin.

Security controls:

- HTTPS on port 443 only; verified certificates and original hostname/SNI.
- Rejects nonpublic IPs, metadata, loopback, private, reserved, multicast,
  mapped/transition IPv6 and mixed safe/unsafe DNS answers.
- Pins the socket to a validated numeric address; no second DNS lookup for connect.
- At most two same-origin redirects by default; validates URL and DNS on every hop.
  Never forwards credentials across origins; ignores proxy environment settings.
- Default 3-second DNS, 5-second connect/read and 15-second total deadlines. A
  watchdog interrupts stalled/dripping TLS/headers/chunk framing. DNS concurrency
  is capped at four; timed-out OS resolver calls retain their slot until completion.
- 512,000-byte body cap and 16,384-byte cumulative header/framing cap. Rejects
  compressed bodies, ambiguous framing, truncated bodies, unsupported media types,
  duplicate JSON keys, nonfinite numbers and excessive JSON depth/node counts.
- Only JSON media types are accepted. OpenAPI 3.0/3.1 gets basic structural checks;
  this is not full OpenAPI validation. YAML is deliberately unsupported. `$ref`
  targets are stored as sanitized references and **never fetched**.
- No raw URL path/query, request/response headers, or raw body is logged or saved.
  Persisted provenance contains an opaque source ID, origin, UTC observation time,
  validated destination IP, redirect count, normalization version and content hash.
- Sanitized contract snapshots remove examples/defaults, free-form descriptions,
  common credential fields, URL userinfo/query/fragment, bearer/basic values and
  known request credential/query values. Semantic arrays retain their order.
  Redacted-only changes intentionally do not alter the normalized hash.

Redaction is conservative, not a general sensitive-data detector. Only observe
approved contract documents; arbitrary response payloads may contain sensitive
material under unknown fields. Do not feed production payloads into this observer.
No data is sent to an LLM. Caller-managed source IDs and schema property names
must not contain credentials or personal data. Network egress restrictions should
also enforce the same public-HTTPS boundary in the deployment environment.

## Deterministic OpenAPI change intelligence

`air.change_intelligence.compare_openapi` classifies contract changes without an
LLM. `air.change_evidence.detect_and_persist` compares two authorized persisted
snapshot IDs and stores an immutable, idempotent change set with provenance and
atomic audit evidence. `load_change_evidence` verifies persisted results by
recomputation. Migration 002 enforces same-tenant snapshot links in PostgreSQL.
See [comparison policy and usage](docs/CHANGE_INTELLIGENCE.md) for supported
request/response rules, coverage warnings, limits and trust boundaries.

Explicit integration/adapter/workflow dependencies can be registered against an
immutable snapshot and matched deterministically to verified contract changes.
See [dependency impact](docs/DEPENDENCY_IMPACT.md) for APIs, conservative matching,
tenant isolation and the explicit registry completeness boundary.

[Automatic mapping extraction](docs/MAPPING_EXTRACTION.md) derives dependencies
from registered declarative adapter operation/field bindings and persists them
through the existing immutable registry, with separately auditable provenance.
