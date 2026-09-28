# Deterministic transitive workflow impact

Downstream relationships are an optional extension to the **existing immutable
contract dependency registry**. There is no separate graph store, traversal
service, impact artifact kind or execution engine. Existing v1 registries and
impact records retain their payloads, hashes and loaders unchanged. Registries
with explicit workflow edges and their impact reports use `air-dependency-impact-v2`.

```python
from air.dependency_impact import (
    Dependency, WorkflowEdge, register_dependencies, analyze_and_persist, load_impact,
)

source = Dependency('inventory-adapter', 'read', '/paths/~1inventory/get',
                    'GET /inventory', 'adapter')
consumer = Dependency('checkout-workflow', 'reserve', '/paths/~1reservations/post',
                      'POST /reservations', 'workflow')
with repo.transaction(authenticated_tenant_uuid) as tx:
    registry = register_dependencies(tx, previous_snapshot_id, [source, consumer],
        workflow_edges=[WorkflowEdge(source, consumer)])
    evidence = analyze_and_persist(tx, change_evidence_id, registry['artifact_id'])
    verified = load_impact(tx, evidence['artifact_id'])
```

Each `WorkflowEdge(upstream, downstream)` explicitly declares that downstream
consumes upstream output. Only `consumes_output` is supported. The ordering is the
direction of potential impact propagation. Both endpoints must exactly match
registered `Dependency` values in the same registry, and their contract locations
must exist in its authorized snapshot. A node is the complete existing dependency
value (integration kind/ID, mapping ID, location and operation). Distinct locations
on one mapping remain distinct evidence nodes. Similar names never create edges.
Missing or malformed endpoints, unknown relations and external registry/tenant
references fail closed. Cycles and self-edges are valid declarations and terminate.

The previous repository represented only contract-to-mapping dependencies; it had
no downstream relationships to discover automatically. Integrators must register
those relationships explicitly. This implementation never invents connections
from method names, mapping names, deployment topology or shared field names.
Cross-snapshot or cross-contract registry linking is outside this scoped format.

`analyze_changes(change_set, dependencies, workflow_edges=...)` is the pure API.
The existing direct matcher produces roots; a sorted multi-source breadth-first
search propagates each original change over registered edges. Node and edge IDs
are hashes of canonical existing dependency/edge values. Input order and identical
duplicate declarations do not change results. A node is visited once per original
change, including direct roots. Thus cycles and converging paths cannot cause
unbounded path enumeration or duplicate downstream results.

`analysis.impacts` retains direct evidence. `analysis.downstream_impacts` adds
one canonical shortest explanation for each newly reached dependency and original
change. Equal-length paths are selected by sorted root dependency/impact IDs,
then sorted outgoing edge IDs. Every result records:

- Original contract change ID, location, type and classification.
- The affected registered dependency, its stable ID and a deterministic reason.
- The direct root impact/dependency IDs and hop count.
- The ordered node path and every full edge with its deterministic edge ID.

The outer artifact already links the exact registry and change evidence by
immutable artifact IDs and hashes, so each hop resolves to the registered edge
in that tenant's selected revision. Source classification is retained; downstream
matches are `TRANSITIVE_REVIEW`, indicating potential impact, not proof of a
runtime failure. One path explains a result; the immutable registry retains all
alternative registered paths. Separate original changes remain separate evidence.

Explicit registrations and automatically extracted PR #5 dependencies both feed
traversal. Register edges using the extracted dependency values. When extraction
unions an `explicit_registry_id`, its workflow edges are preserved and verified on
reload; extraction must never silently discard them. Existing extraction evidence
continues to link its explicit base and mapping source artifacts. Selecting registry
revisions remains explicit, and no unregistered dependencies are discovered.

Limits: 1,000 dependency entries, 2,000 supplied edge entries before deduplication,
32 downstream hops, 100,000 examined edges across all original changes, 5,000 direct
plus downstream results, and the existing 1 MiB evidence payload limit. Limits are
versioned code policy. Exceeding any bound raises an error before persisting impact;
there is no partial successful result. Back/cycle edges to seen nodes do not consume
new depth. Unreachable nodes are never reported as safe: existing coverage warnings
and `review_required` are preserved, including when no path is registered.

Migration 005 enforces same-registry endpoint membership and rejects external
ownership/link fields in PostgreSQL. The existing RLS, authenticated tenant
context, snapshot linkage, append-only rows and audit triggers remain in force.
An endpoint's identity is scoped to its containing tenant/registry; equal names in
another tenant do not identify or expose that tenant's records. Runtime integrators
and administrators remain trusted for truthful declarations. Database checks verify
membership, not real-world execution semantics. Verified reload recomputes paths,
reasons, hashes and classifications and rejects forged impact records. Repeated and
concurrent identical analysis returns one immutable artifact and audit event.

No repair generation, sandbox/replay, AI call or deployment behavior is included.
Human approval remains mandatory for consequential actions.
