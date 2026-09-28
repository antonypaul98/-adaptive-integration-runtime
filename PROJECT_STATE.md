# AIR implementation state

Updated 2026-09-27. GitHub is the source of truth.

## Source reconciliation

The accessible repository is `antonypaul98/-adaptive-integration-runtime` (leading
hyphen). The supplied non-hyphen name returned 404. This run started from main
`8ccd2db0e1f6ea31b0db021abab871d7b534ca05` (README only) and continued the newest real
implementation at recovery/postgres-tenant-isolation `b80ca97` (migration-loader
stub and packaging; no migrations or tests). No historical Git reconstruction.
The old 39-test claim is not acceptance evidence for this repository.

## Completed implementation

### PostgreSQL persistence and tenant isolation

- Versioned, checksum-verified, advisory-locked transactional migrations.
- Tenant-scoped artifacts and atomic database-triggered audit events.
- ENABLE + FORCE RLS with a protected authenticated-login/tenant binding.
- Missing, malformed, disabled and forged tenant contexts fail closed.
- Runtime cannot modify bindings, bypass RLS, mutate evidence or forge timestamps.
- Database SHA-256 hashes; deterministic JSON; idempotent inserts and conflict errors.
- Rollback boundaries, explicit READ COMMITTED semantics, closed short-lived
  connections, statement/lock/idle timeouts and certificate-verified TLS defaults.
- Guards reject privileged runtime/session identities, including SET ROLE masking.

PR #1 merged as `6aa33a827dc2eef9c7cbac6e180b2c06c4458482`. Its merged-main run
36344593469 passed PostgreSQL 16 and 17, 54 tests per job. The initial migration
CI failure was fixed (hashing uses an insert trigger rather than a non-immutable
PostgreSQL generated-column expression).

### Read-only REST/OpenAPI JSON observer

- HTTPS/443 only; strict URL, DNS and public-IP validation; pinned numeric sockets
  with original-host TLS verification; revalidation on same-origin redirects.
- Bounded DNS concurrency, connect/read/total deadlines; watchdog stops slow TLS,
  headers and chunk framing; strict body/header/JSON-complexity limits.
- No proxy inheritance, remote reference fetches, compression or write methods.
- Sanitized provenance and contract snapshots; one-pass secret replacement;
  immutable tenant-scoped persistence; deterministic normalized hashes and changes.
- Explicit adversarial tests and actual TLS transport tests, not only mocks.

## Latest executed evidence

Validated code head: `c46091fdbfeb69653267893bf15e41ff08d86391` on PR #2.

- Local Python 3.12: **115 passed**, 35 PostgreSQL cases deselected (not claimed as
  local passes). Includes actual TLS tests for trusted/untrusted certificates,
  hostname mismatch, chunked/truncated/oversized responses and drip deadlines.
- Exact-head PR CI run **36345148788**: **150 passed, zero skipped** on both
  PostgreSQL **16 and 17**. Includes 35 actual database integration cases.
  https://github.com/antonypaul98/-adaptive-integration-runtime/actions/runs/36345148788
- Local wheel built and inspected: PostgreSQL/observer code and migration SQL
  resources are packaged. CI also verifies installed imports/resources outside
  the source checkout.
- Compilation and whitespace checks passed. No benchmarks were claimed.

Local database installation was unavailable. PostgreSQL integration tests actually
ran in GitHub service containers. No production database or customer endpoint was
contacted. Subsequent documentation/package-verification revisions and merged main
must pass the same full matrix before acceptance.

## Boundaries and exact next implementation step

Observer supports JSON and basic OpenAPI 3.0/3.1 structural checks, not full OpenAPI
validation or YAML. Redaction is conservative; only approved contract documents
are appropriate input. `$ref` URLs are never fetched. Source IDs must be bound to
stable endpoints by the calling application. See README for trust/provisioning,
normalization, sensitive-data, resolver, retention and operational limitations.

Next: implement deterministic OpenAPI operation/parameter/response/schema change
classification, persist tenant-scoped change evidence linked to the two immutable
snapshot artifact IDs, and test breaking/nonbreaking/security drift. Proposal,
sandbox, replay and approval enforcement follow that evidence boundary.

Lifecycle: observe → detect → propose → sandbox → replay → verify → approve → deploy.
No automatic deployment, production writes or LLM calls are implemented. Human
approval remains mandatory for externally consequential changes. This checkpoint
does not claim the rest of AIR's lifecycle is implemented.

## Change intelligence implementation — validation in progress

Continuation starting main: `30b1733876fd1fa2b67be7e7a4a2f7ba1a9b5841`.
Implemented deterministic OpenAPI comparison, structured immutable change sets,
reference/coverage evidence, directional request/response compatibility rules,
security drift classification, persisted snapshot verification, idempotent
change evidence and database-enforced tenant-scoped snapshot links (migration 002).

Executed locally in this continuation: 67 classifier tests passed; complete
non-PostgreSQL suite: 182 passed. Database acceptance awaits PostgreSQL 16/17 CI.
Prior main's 150-test PostgreSQL matrix remains the verified baseline, not evidence
for the new migration. No dependency-impact implementation has started.

Next acceptance action: push the feature branch, execute the full PostgreSQL
matrix, fix failures, merge only on a passing exact head, then verify merged main.
