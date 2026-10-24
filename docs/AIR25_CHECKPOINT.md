# AIR-25 — dependency visualization and impact reports

Status: **IN PROGRESS**. The first bounded slice defines a deterministic,
read-only dependency projection suitable for later visualization and review.

`project_dependency_graph` accepts only explicit `Dependency` registrations,
declared `WorkflowEdge` values and an optional content-addressed
`ImpactReport`. It emits stable node and edge identities, review annotations,
source hashes, explicit registry-only coverage warnings and authority limits.
`no_recorded_impact` is never represented as proof that a dependency is safe.
The second bounded slice adds aggregate counts over only those recorded nodes,
edges and annotations. The summary labels its basis explicitly and states that
its counts are neither probabilities nor completeness claims.
The third bounded slice persists that projection as immutable, tenant-scoped
evidence bound to the exact registry and optional impact artifacts. Reload
recomputes the projection and fails closed on mismatched or forged evidence.
The fourth bounded slice derives a deterministic presentation model only after
revalidating every projection identity, source hash, summary, coverage boundary
and read-only authority. It replaces dependency names, mappings, locations and
operations with stable opaque aliases, groups nodes into explicit review lanes,
and retains only recorded counts and `consumes_output` edges.
The fifth bounded slice persists that redacted presentation as immutable,
tenant-scoped evidence bound to one exact persisted projection. Reload first
revalidates and recomputes the projection, then recomputes the visualization;
cross-tenant, forged, substituted and noncanonical evidence fails closed.

The projection performs no dependency discovery, production observation,
payload or credential access, external call, repair, approval, deployment,
agent/tool execution or tenant-crossing query. This presentation model renders
no UI and grants no interactive or external-action authority; interactive
visualization remains a later bounded slice.

## Acceptance gate

Source PR #45 and merged main passed exact PostgreSQL 16 and 17 CI on Python
3.12.15 with 802 tests and zero product skips per matrix. Canonical records PR
#46 passed exact-head CI; recovery PR #47 and exact-current-main-SHA recovery
run 39543021758 passed the same 802 tests with zero product skips per matrix.
The prior writer was explicitly released before this second source slice.

## CI recovery receipt

Canonical records PR #46 merged as `1193ad5d509e913bd8f0f8135ea7e987943d3f82`
after exact-head CI passed, but GitHub Actions did not create a run for that
merge SHA despite the unfiltered `push` trigger in
`.github/workflows/tests.yml`. This metadata-only receipt intentionally
re-exercises the normal PR and merged-main gates; it does not change product
behavior or relax acceptance.

Recovery PR #47 merged as current main
`999f58abc9e3aeec0db971149c5a3615ac69dbd5`. Recovery push run 39543021758
tested that exact SHA on a recovery ref (not a `main` event) and passed Python
3.12.15 with 802 tests on each PostgreSQL version and zero product skips. The
event/ref distinction is retained; writer release is recorded on PR #47.

## Recorded-impact summary source receipt

PR #48 head `c78c8c6e6510ebe31275232311f9c2b007c1e3b8`, tree
`8b341bf750348e0de396f52f8432508127de970f`, passed exact-head run
39576942933 on Python 3.12.15. PostgreSQL 16 and 17 each reported 804
tests passed with zero product skips. Guarded merge produced main
`ab355e398bc99cdbd5e5da4227fb97145712ecc9`; exact main push run
39577293315 passed the same 804-test matrix with zero product skips.

The new aggregate is bounded to recorded annotations. Its node, edge and impact
counts are explicitly neither probabilities nor completeness claims. AIR-25
remains in progress at 2/12 pending later visualization/report slices and
eventual checkpoint acceptance.

## Projection persistence source receipt

PR #50 head `c5161360dc12e2a658a4636020f583c3133a5727`, tree
`996cd451fdb438fa4df34d356493d8bd86969dab`, passed exact-head run
39871385727 on Python 3.12.15. PostgreSQL 16 and 17 each reported 815
product tests passed with zero product skips. Guarded merge produced main
`44331ae748f3995018000b29b755a4ba81c4f730`; exact main push run
39877439471 passed the same 815-test matrix with zero product skips.

The slice stores immutable, tenant-scoped dependency projections bound to the
exact registry and optional impact artifacts. Reload recomputes the projection
and fails closed on mismatched or forged evidence. It performs no dependency
discovery, production observation, payload or credential access, repair,
approval, deployment, external action, agent/tool execution, probability,
completeness or safety claim. AIR-25 remains in progress at 2/12 pending later
visualization/report slices and eventual checkpoint acceptance.

## Deterministic visualization source scope

The candidate source accepts only an existing canonical `DependencyProjection`
and fails closed if node or edge identities, source hashes, recorded-impact
summary, coverage claims, ordering, or read-only authority have been forged.
Its output uses stable opaque aliases and fixed review lanes without copying raw
dependency metadata or source warning text. `no_recorded_impact` remains an
explicit unknown state, not a safety result. The in-memory presentation model
does not authenticate the projection's origin; persisted evidence must still be
loaded through the existing tenant-scoped recomputation path.

Local Python 3.12.14 validation passed 21 focused projection/visualization tests,
483 portable product tests with 343 PostgreSQL cases deselected, and 15 of 16
infrastructure guards with the documented Memory-only skip. At candidate
creation, PostgreSQL 16/17 CI, PR merge and merged-main CI were still pending;
the verified source receipt follows. Canonical records and writer release remain
pending.

## Deterministic visualization source receipt

PR #52 head `cd5b51cd44030808c98b09f921b93e4935feaae4`, tree
`8990c0b1c2b128e682b35270a3aaccef05a3fa4d`, passed exact PR run
39969307864 on Python 3.12.15. PostgreSQL 16 and 17 each passed 826 product
tests with zero skips. Guarded merge produced main
`007e09a6c75a5918050f8f3ba672a3d2ec25568c`; exact push run 39969589955
passed the same 826-test matrix with zero product skips.

The output contains stable opaque aliases, review lanes, recorded counts and
registered edge relations only. It includes no raw dependency metadata, and it
explicitly withholds origin authentication, completeness, probability, safety,
repair, approval, deployment, external-action or execution authority. This
records change requires its own exact PR and merged-main CI before release.

## Visualization persistence source scope

The candidate stores only the existing redacted presentation payload plus its
content hash and exact tenant-scoped projection artifact identity/hash. Database
validation enforces the tenant, immutable reference, payload hash, explicit
unknown/safety boundary and read-only authority. Verified reload recomputes both
the projection and visualization rather than trusting the stored presentation.

Local Python 3.12.14 validation passed 21 focused projection/visualization tests,
483 portable product tests with 351 PostgreSQL cases deselected, and 15 of 16
infrastructure guards with the documented Memory-only skip. PostgreSQL 16/17
source CI is pending. This slice adds no raw dependency metadata, discovery,
production observation, credentials, payload access, external action, repair,
approval, deployment, agent/tool execution, probability, completeness or safety
authority. AIR-25 remains in progress at 2/12.

## Visualization persistence source receipt

PR #54 head `aa77d6284bf3afbfc37590dd5726c9c689d6b9ee`, tree
`c88316f20b12056a678f4234d16a4295aabf6c0e`, passed exact PR run
40002653145 on Python 3.12.15. PostgreSQL 16 and 17 each passed 834 product
tests with zero product skips. The expected-head guarded merge produced exact
main `fbd6cf37fd7f6f471169e4eab749636051a03e9c`; exact merged-main run
40039245945 passed the same 834-test matrix with zero product skips.

This receipt does not expand authority or mark AIR-25 complete. Canonical
records CI and the explicit writer release remain pending; roadmap progress is
still 2/12 accepted.

## Cycle-safe impact-report source scope

The candidate consumes one already validated dependency projection and a bounded
set of registered hash identities. It traverses declared downstream edges once,
computes deterministic minimum-hop distances, and reports deterministic strongly
connected components for cycles. The output retains only hashes, fixed impact
states, recorded impact identities, counts and explicit coverage/authority flags;
it copies no raw dependency metadata.

Local Python 3.12.14 validation passed 28 focused tests and 490 portable product
tests with 351 PostgreSQL cases deselected. Infrastructure validation passed 15
guards with one documented Memory-only skip. PostgreSQL 16/17 source CI is
pending. No discovery, production observation, credential/payload access,
external action, repair, approval, deployment, agent/tool execution,
completeness inference or safety claim is added.

## Cycle-safe impact-report source receipt

PR #56 head `08f4be44d631b7b584caed9f977114c10eb33ea3`, tree
`570130da6975a9bd018f1c48dd87d64c8f201132`, passed exact PR run
40066183394. PostgreSQL 16 and 17 each passed 841 product tests with zero
product skips. The expected-head guarded merge produced exact main
`9e2a8a387ef5573f1969f6ae76a09fbd8e567dc9`; exact merged-main run
40066344089 passed the same matrix.

This receipt adds no authority and does not mark AIR-25 complete. Canonical
records CI and explicit writer release remain pending; progress stays 2/12.

## Impact-path witness evidence source scope

Starting from exact verified main
`aa87735e78e0173840662731a7593753baa937a2`, this bounded candidate adds one
canonical shortest-path predecessor witness per reachable recorded node. Seed
and declared-edge hashes resolve equal-length choices deterministically. The
evidence is linear in the bounded node count and can be reconstructed without
copying dependency names, mappings, locations or operations.

This is one witness through recorded edges, not a discovery or alternative-path
completeness claim. It adds no production observation, credential or payload
access, repair, approval, deployment, external action, execution or safety
authority. Local Python 3.12.14 validation passed 30 focused tests, 492
portable product tests with 351 PostgreSQL cases deselected, and 15 of 16
infrastructure guards; the sole skip is the documented Memory-only diagnostic.
Exact PostgreSQL 16/17 PR and merged-main CI remain required.

## Impact completeness-warning source candidate

Starting from exact verified main
`f6f072f00e71c97f8ac00cd351ffb526eead5815`, this bounded candidate makes
the traversal gap explicit. It reports every registered node not reachable
from the selected seeds as a sorted hash-only manifest, reconciles registered,
reachable and unreachable counts, and emits fixed warning codes when coverage
is partial or the source projection already carries warnings. Caller warning
text is never copied into the report.

The manifest covers only the validated explicit projection. It does not infer
undeclared dependencies or claim that seed reachability is registry or system
completeness. It adds no raw dependency metadata, production observation,
credential or payload access, repair, approval, deployment, external action,
execution or safety authority. Local Python 3.12.14 validation passed 32
focused tests and 494 portable product tests with 351 PostgreSQL cases
deselected. Exact PostgreSQL 16/17 PR and merged-main CI with zero product
skips remain required before canonical records.
