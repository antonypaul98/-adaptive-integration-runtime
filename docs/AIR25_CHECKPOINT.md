# AIR-25 — dependency visualization and impact reports

Status: **IN PROGRESS**. The first bounded slice defines a deterministic,
read-only dependency projection suitable for later visualization and review.

`project_dependency_graph` accepts only explicit `Dependency` registrations,
declared `WorkflowEdge` values and an optional content-addressed
`ImpactReport`. It emits stable node and edge identities, review annotations,
source hashes, explicit registry-only coverage warnings and authority limits.
`no_recorded_impact` is never represented as proof that a dependency is safe.

The projection performs no dependency discovery, production observation,
payload or credential access, external call, repair, approval, deployment,
agent/tool execution or tenant-crossing query. Persistence and interactive
visualization remain future bounded slices.

## Acceptance gate

Source PR #45 and merged main passed exact PostgreSQL 16 and 17 CI on Python
3.12.15 with 802 tests and zero product skips per matrix. A separate canonical
records receipt must pass the same exact PR-head and merged-main gate, followed
by explicit writer release, before another AIR-25 source slice.

## CI recovery receipt

Canonical records PR #46 merged as `1193ad5d509e913bd8f0f8135ea7e987943d3f82`
after exact-head CI passed, but GitHub Actions did not create a run for that
merge SHA despite the unfiltered `push` trigger in
`.github/workflows/tests.yml`. This metadata-only receipt intentionally
re-exercises the normal PR and merged-main gates; it does not change product
behavior or relax acceptance.
