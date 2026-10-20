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

This source must pass exact PostgreSQL 16 and 17 PR-head CI on Python 3.12 with
zero product skips, a guarded merge, and exact merged-main CI. A separate
canonical records receipt and explicit writer release are required before
another AIR-25 source slice.
