# AIR implementation state

Updated 2026-09-28. GitHub is the source of truth.

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

## Observer checkpoint evidence

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

## Observer checkpoint boundaries and then-next step

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

## Deterministic change intelligence — validated implementation

Continuation starting main: `30b1733876fd1fa2b67be7e7a4a2f7ba1a9b5841`.
Validated code head: `224fb618c97a33b94e84c1345ce49013fe5a1a55` on PR #3.

Implemented deterministic OpenAPI 3.0/3.1 comparison with stable ordering,
structured immutable change sets, bounded local reference expansion and coverage
warnings. Request/response variance, paths, operations, parameters, bodies,
responses, properties, requiredness, types, enums, nullability and security drift
have explicit deterministic classifications. Unsupported semantics require review.

Tenant-bound evidence verifies snapshot content and provenance, stores both snapshot
IDs/hashes with detector version and normalized comparison hash, and supports
idempotent persistence and verified reload. Migration 002 enforces same-tenant
snapshot links in PostgreSQL; existing RLS, immutable rows and atomic audit remain
in force. Classification integrity on reload is checked by recomputation. See
[CHANGE_INTELLIGENCE.md](docs/CHANGE_INTELLIGENCE.md) for policy and trust limits.

Executed evidence:

- Targeted classifier suite: **70 passed**.
- Complete local non-PostgreSQL suite: **185 passed**, 57 database tests deselected
  (not claimed as local database passes).
- Exact-code-head PR CI run **36365861829**: **242 passed, zero skipped** on each
  of PostgreSQL **16 and 17**, including **57 actual PostgreSQL integration tests**.
  https://github.com/antonypaul98/-adaptive-integration-runtime/actions/runs/36365861829
- Database cases cover immutable evidence, cross-tenant input/read/link attacks,
  provenance/hash tampering, concurrent idempotency, rollback, migration re-run and
  failed-upgrade behavior. CI verifies installed modules and migration resources.
- Local PostgreSQL service installation was unavailable; integration execution
  occurred in GitHub service containers. No production data or endpoints were used.

Final PR #3 head `e2ff3aaf251139e31a1eb13e82664aa5be5b30a0` passed the full
242-test PostgreSQL 16/17 matrix (run 36366080073). Merged main
`e5385fd745b84fad279c8b16f6b06147e978233a` passed the same matrix
(run 36366147860). The change-intelligence checkpoint is merged and verified.

## Dependency impact foundation — validated implementation

Change intelligence was merged by PR #3 into
`e5385fd745b84fad279c8b16f6b06147e978233a`. Exact final PR head
`e2ff3aaf251139e31a1eb13e82664aa5be5b30a0` passed 242 tests on both PostgreSQL
versions (run 36366080073), and merged main passed the same 242-test matrix
(run 36366147860). Only then did dependency impact implementation start.

Implemented immutable snapshot-bound dependency registrations, deterministic
location/operation/security impact links, verified reload, idempotent persistence
and migration 003 for database-enforced tenant/link integrity. This is an explicit
registry foundation; automatic extraction and transitive workflow propagation are
not implemented. See docs/DEPENDENCY_IMPACT.md for exact matching/coverage limits.

Validated code head: `a66b8e2f9a5249b91cf264801adb8e8484b44ab9` on PR #4.

- Targeted impact suite: **26 passed**.
- Complete local non-PostgreSQL suite: **211 passed**, 81 database cases deselected.
- Exact-code-head PR CI run **36366772178**: **292 passed, zero skipped** on each
  of PostgreSQL **16 and 17**, including **81 actual database integration tests**.
  https://github.com/antonypaul98/-adaptive-integration-runtime/actions/runs/36366772178
- New database cases verify persisted reload, cross-tenant reads and inputs,
  forged links/tenants, snapshot binding, immutable registry/impact rows, rollback,
  concurrent idempotency and recomputation rejecting forged impact results.
- Compilation and whitespace checks passed. PostgreSQL execution occurred in
  disposable GitHub service containers, not a local or production database.

The documentation revision and merged main must pass the same matrix as the final
acceptance gate. PR #4 and Actions record that final merge/post-merge result.

Next implementation step: extract explicit operation/field dependencies from a
registered adapter mapping into this immutable registry, and validate extraction
against known mappings before adding transitive workflow impact propagation.
Registry revision selection remains explicit; there is no claim of automatic
runtime dependency discovery or completeness. No repair generation, LLM calls or
production deployment were added. Human approval remains mandatory.

## Automatic dependency extraction — validated implementation

Started from verified main `9188aab3a658a7f9ae252a21cb7b6bff5ed053db`.
PRs #3 and #4 were merged, and main CI run 36366956866 passed 292 tests on each
of PostgreSQL 16 and 17 with zero skips. Baseline local run: 211 passed.

Repository inspection found no existing adapter-mapping representation. Added a
bounded versioned declarative mapping registration format and deterministic
operation/parameter/body-field extraction into the existing immutable registry.
Separate immutable extraction evidence explains each dependency using registered
mapping artifact/hash, mapping ID and canonical source pointer. Optional explicit
registrations are unioned without overwriting records. Migration 004 enforces
same-tenant ownership and snapshot/registry/mapping/provenance links. Verified
reload, content-addressed retries and savepoint-protected writes are implemented.

Validated code head: `d7d8938de74bde7deefb097951b63f56c58d7d7d` on PR #5.

- Focused extractor suite: **38 passed**.
- Complete local non-PostgreSQL suite: **249 passed**, 120 database tests deselected
  (not claimed as local database passes).
- Exact-code-head PR CI run **36458560289**: **369 passed, zero skipped** on each
  of PostgreSQL **16 and 17**, including **120 actual database integration tests**.
  https://github.com/antonypaul98/-adaptive-integration-runtime/actions/runs/36458560289
- Added **77 tests**: 38 pure extraction and 39 PostgreSQL cases. Coverage includes
  deterministic normalization/deduplication, multiple operations/mappings/adapters,
  provenance pointers/hashes, explicit registry reuse/union, persisted reload,
  malformed/unsupported/ambiguous ownership, cross-tenant inputs/reads/forged links,
  immutable rows, concurrent idempotency, savepoint rollback and existing impact
  analysis consuming extracted dependencies.
- Whitespace and compilation checks passed. Database tests ran in disposable
  GitHub service containers; no production data or endpoints were used.

The documentation revision and merged main must pass the same exact-head matrix.
PR #5 and Actions record the final merge and post-merge acceptance evidence.
See docs/MAPPING_EXTRACTION.md for the supported declarative format and trust limits.
No arbitrary adapter-code discovery, transitive workflow analysis, repair
generation or sandbox/replay was started. Human approval remains mandatory.

Exact next checkpoint: deterministic transitive workflow impact from explicitly
registered workflow dependency edges, with immutable tenant-bound evidence.

## Transitive workflow impact — implementation awaiting database validation

Starting main: `da63a8956a796dc7aba672173abbd73b7895162b`. PR #5 was merged;
merged-main run 36459040057 passed 369 tests on each PostgreSQL version with zero
skips. Baseline local suite: 249 passed, 120 database cases deselected.

Existing registrations contained direct contract-to-mapping dependencies but no
downstream edges. Added optional explicit WorkflowEdge relationships to the same
registry and transitive results to the same impact API/artifact kind. Sorted
multi-source BFS emits one canonical shortest path per original change and
registered dependency, handles cycles/self-edges, and fails completely on bounds.
Each hop retains endpoint values and edge hash, linked to the immutable registry
and original change evidence. Legacy v1 payloads remain unchanged. PR #5 extraction
preserves workflow edges when unioning an explicit registry. Migration 005 enforces
same-registry endpoint membership and rejects tenant/registry override fields.

Executed locally: 27 focused workflow tests passed; complete non-PostgreSQL suite:
276 passed, 148 database cases deselected. PostgreSQL 16/17 validation is pending;
no unexecuted database pass is claimed. See docs/WORKFLOW_IMPACT.md for exact scope,
traversal limits, path selection, versioning and trust boundaries. No repair,
sandbox/replay or unrelated functionality was started.
