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

The projection performs no dependency discovery, production observation,
payload or credential access, external call, repair, approval, deployment,
agent/tool execution or tenant-crossing query. Persistence and interactive
visualization remain future bounded slices.

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
