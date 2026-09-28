# Automatic dependency extraction from registered adapter mappings

AIR had an explicit dependency registry but no executable adapter or mapping model
at the start of this checkpoint. This adds a small, versioned **declarative mapping
format**, not an adapter execution engine or arbitrary code analyzer. Dependencies
are derived from its HTTP operation and parameter/body field bindings; callers do
not supply dependency records or inferred ownership.

```python
from air.mapping_extraction import register_adapter_mapping, extract_registered_dependencies

with repo.transaction(authenticated_tenant_uuid) as tx:
    mapping = register_adapter_mapping(tx, {
        'mapping_version': 'air-adapter-mapping-v1',
        'tenant_id': str(authenticated_tenant_uuid),
        'snapshot_id': str(previous_snapshot_id),
        'adapter_id': 'billing',
        'mappings': [{
            'mapping_id': 'fetch-items', 'method': 'GET', 'path': '/items',
            'bindings': [{
                'binding_id': 'invoice-id',
                'contract': {'kind': 'response_body', 'status': '200',
                             'media_type': 'application/json', 'field': '/id'},
                'adapter_field': '/invoice/id', 'transform': 'identity',
            }],
        }],
    })
    result = extract_registered_dependencies(tx, [mapping['artifact_id']])
    # Existing API; no parallel dependency or impact model.
    impact = analyze_and_persist(tx, change_evidence_id, result['registry']['artifact_id'])
```

Import `analyze_and_persist` from `air.dependency_impact`. The observed snapshot
must contain the operation and field. Registration validates locations with the
existing bounded contract expansion, inherited parameter and header-name rules.
No network call or adapter execution takes place.

Supported binding `contract` objects:

| Kind | Required fields | Derived contract location |
|---|---|---|
| `parameter` | `in`, `name` | Effective operation parameter by location/name |
| `request_body` | `media_type`, `field` | Request schema and object-property path |
| `response_body` | `status`, `media_type`, `field` | Response schema and object-property path |

`field` and `adapter_field` are RFC 6901 JSON pointers. Body `field` traverses
object properties only; an empty pointer selects the entire body schema. Array
traversal, wildcard inference, executable transformations and dynamic expressions
are unsupported and must not be guessed. Only the declared `identity` transform
is accepted. Every mapping also establishes an operation dependency; an empty
binding list declares operation-only use. Distinct operations require distinct
mapping IDs. Adapter field paths describe binding metadata, never actual payloads.
Do not register credentials, production payloads or sensitive customer values.

Ownership is required at the manifest root and must match the authenticated tenant.
Missing/unknown/nested ownership fields, unsupported versions/keys/transforms,
conflicting duplicate IDs and multiple revisions of one adapter in the same
extraction fail closed. Identical duplicate mappings/bindings and artifact inputs
are deduplicated. Ordering, header-name casing, HTTP method casing and UUID spelling
are normalized. IDs remain case-sensitive. Mapping lists are declarative sets,
not ordered executable steps. Choose one immutable revision per adapter explicitly.

`register_adapter_mapping` persists the normalized manifest as an immutable
`registered_adapter_mapping` artifact with its authorized snapshot reference.
`extract_registered_dependencies` loads those registered artifacts through tenant
predicates/RLS, derives ordinary `Dependency` values, and calls the existing
`register_dependencies`. Its `registry` result is directly compatible with
`load_registry` and existing impact analysis. Identical manual and extracted
dependency sets reuse the same registry artifact. An optional
`explicit_registry_id` unions a verified registry for the **same exact snapshot**;
existing registrations are never overwritten.

Its second result, `extraction`, is immutable `adapter_dependency_extraction`
evidence. Every derived dependency has its deterministic hash, mapping artifact
ID/hash, mapping ID, canonical manifest pointer and reason. The pointer resolves
to the operation or binding (including binding ID, adapter field and transform)
in the **stored normalized manifest**, not the original list order. An optional
explicit registry is linked separately with its immutable ID/hash. These are
provenance links, not a second registry model. `load_adapter_mapping` and
`load_extraction` revalidate/recompute their evidence on reload.

Migration 004 enforces tenant ownership, snapshot binding, registry/mapping hashes
and provenance artifact links in PostgreSQL. Existing immutable rows, audit and
RLS apply unchanged. Runtime/admin writers remain trusted for declaration truth;
verified loaders reject unsupported manifests and forged extraction calculations.
Registry and extraction writes use one savepoint: catching an extraction failure
inside the caller's transaction cannot leave a newly created orphan registry.
Repeated/concurrent extraction is content-addressed and idempotent.

Work is bounded to 32 manifest inputs, 200 mapping entries per manifest, 500 binding
entries per manifest, the existing 1,000 dependency limit and 1 MiB evidence limit.
Limits count supplied entries before deduplication. Oversized or unsupported work
fails explicitly rather than recording partial evidence. Same-snapshot matching
is mandatory; cross-tenant IDs never become authoritative links.

No transitive workflow analysis, repair generation, sandbox/replay, AI calls or
production deployment is added. This extracts what registered mappings explicitly
represent; it does not discover undeclared external dependencies or prove safety.
