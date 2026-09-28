# Deterministic dependency impact foundation

```python
from air.dependency_impact import (
    Dependency, register_dependencies, analyze_and_persist, load_impact,
)

with repo.transaction(authenticated_tenant_uuid) as tx:
    registry = register_dependencies(tx, previous_snapshot_id, [
        Dependency('billing', 'invoice-id',
            '/paths/~1invoices/get/responses/200/content/application~1json/schema/properties/id',
            'GET /invoices', 'workflow'),
    ])
    impact = analyze_and_persist(tx, verified_change_evidence_id, registry['artifact_id'])
    checked = load_impact(tx, impact['artifact_id'])
```

A registry is an immutable revision of explicitly declared integration, adapter or
workflow dependencies on one observed contract snapshot. Each declaration names an
integration, mapping, optional operation, and an escaped JSON pointer. Registration
validates that the operation and location exist in the detector's bounded effective
contract: local references are expanded and operation parameters use
`/parameters/{in}/{name}`, including inherited parameters and lower-case header
names. External references are never fetched. Select a schema or property object
rather than an index in an order-insensitive array. Root pointer `''` deliberately
registers a dependency on the whole contract.

Analysis requires a registry for the change evidence's exact previous snapshot.
It verifies snapshots, change evidence and registry before producing these links:

contract change ID → integration/kind → mapping/operation → match/reason → evidence.

- Consequential changes with overlapping pointer tokens produce `LOCATION_OVERLAP`.
  Both ancestor removal and changes below a registered schema/operation are covered.
- Enclosing schema/parameter constraints produce `SCHEMA_REVIEW`, including
  required-property changes whose effective location differs from the property.
- Other changes to the declared operation (or operation inferred from its pointer) produce `OPERATION_REVIEW`, a conservative
  potential impact. This includes indirect constraints and sibling field effects.
- Global authentication changes produce `GLOBAL_SECURITY_REVIEW` for registered
  consumers. This may over-report consumers of an unused authentication scheme.
- Nonbreaking changes do not produce impact links. Coverage warnings propagate,
  and unmatched consequential changes still leave `review_required` true.

`analyze_changes(change_set, dependencies)` is the deterministic pure API. Input
ordering and duplicate declarations do not change the result. IDs, ordering,
registry hashes, comparison hashes and output hashes are deterministic. Persistence
adds tenant identity, immutable change/registry artifact IDs and hashes; detection
time is the database artifact timestamp. Repeating or concurrently submitting an
identical registration/analysis returns the same artifact and audit event.

Migration 003 enforces same-tenant snapshot/registry/change links and the registry's
previous-snapshot binding in PostgreSQL. Existing RLS, immutable artifacts and audit
triggers apply. Verified reload recomputes impact to detect forged results. Trusted
integrators/admins remain responsible for truthful declarations; the database
checks linkage, not the Python matching algorithm. Any failed transaction rolls
back as with other evidence. Inputs are limited to 1,000 declarations, 200,000
comparison pairs and 5,000 impact links, plus the existing 1 MiB evidence limit.
Excess work fails explicitly without storing a partial report.

This foundation does not discover dependencies from executable code, maintain a
mutable latest registry, or prove registry completeness. Callers explicitly choose
the intended immutable registry revision. Empty impact results never prove safety
or authorize deployment. Registration lifecycle/selection, automatic adapter
extraction and transitive workflow propagation are subsequent implementation work.
There are no LLM calls, repair generation or production deployment operations.
