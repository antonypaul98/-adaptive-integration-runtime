# Deterministic OpenAPI change intelligence

`air.change_intelligence.compare_openapi(previous, current)` compares OpenAPI
3.0/3.1 JSON documents without network access or an LLM. It returns frozen change
objects, stable ordering/IDs, normalized comparison hashes, reference provenance
and explicit coverage warnings. This is a conservative client-compatibility
policy for a documented subset, not a complete JSON Schema subsumption solver or
full OpenAPI conformance validator.

## Persisted detection

```python
from air.change_evidence import detect_and_persist, load_change_evidence

with repo.transaction(authenticated_tenant_uuid) as tx:
    evidence = detect_and_persist(tx, previous_snapshot_artifact_id,
                                 new_snapshot_artifact_id)
    verified = load_change_evidence(tx, evidence['artifact_id'])
```

This API reads actual `contract_observation` artifacts through tenant predicates
and PostgreSQL RLS. It validates artifact/content hashes, supported normalization,
source identity, origin, observation time and network provenance before comparison.
Snapshots must belong to the same tenant/source/origin/normalization. Missing and
cross-tenant IDs have the same fixed-code error. Pure dictionary comparison does
not grant database access; use persisted detection for authoritative evidence.

The `contract_change_set` artifact contains tenant identity, both immutable
snapshot IDs and hashes, observed provenance, detector version, normalized change
hash, coverage warnings and every change's location, operation, old/new values,
presence flags, classification and deterministic reason. Locations are escaped
JSON pointers into the effective contract. Effective parameters use
`/parameters/{in}/{name}`; reference provenance maps expanded usage locations to
original local `$ref` targets.

The artifact's database `created_at` is its detection timestamp. It is excluded
from deterministic comparison content. The ordered snapshot pair and detector
version identify an idempotent detection. Repeated/concurrent detection returns
the same artifact and audit event. Reload recomputes the evidence and rejects
forged classifications or hashes. Any exception escaping the transaction rolls
back all writes in that transaction.

Migration `002_change_evidence_links.sql` adds a database trigger requiring both
snapshot references and hashes to resolve within the inserting tenant and to a
matching source/origin/normalization. Existing evidence remains append-only under
migration 001. Database administrators and trusted runtime code remain inside the
trust boundary: the trigger verifies links, not the Python classification
algorithm. Use `load_change_evidence` to verify evidence from untrusted writers.

## Compatibility policy

| Change | Classification |
|---|---|
| Path/operation addition | NON_BREAKING |
| Path/operation removal | BREAKING |
| Optional parameter addition | NON_BREAKING |
| Required parameter addition / optional becoming required | BREAKING |
| Parameter removal / serialization change | BREAKING (conservative) |
| Request type/enum/bound narrowing | BREAKING |
| Request type/enum/bound widening | NON_BREAKING |
| Response type/enum/bound widening | BREAKING |
| Response type/enum/bound narrowing | NON_BREAKING |
| Required request property introduced | BREAKING |
| Required response property removed | BREAKING |
| Response property removed | BREAKING (conservative documented-field policy) |
| Response property added | NON_BREAKING, except an old closed object is BREAKING |
| Optional request property added | NON_BREAKING for an old closed object; otherwise REVIEW_REQUIRED |
| Required request body introduced | BREAKING |
| Documented response status removed | BREAKING |
| Response status added | REVIEW_REQUIRED |
| Authentication requirement/scheme change | SECURITY_RELEVANT |
| Unsupported field/schema semantics | REVIEW_REQUIRED, plus coverage warnings |

Operation security inherits root security unless explicitly overridden; empty
security arrays disable inherited requirements. Path parameters inherit into
operations, with operation-local overrides by location/name. Header parameter
identity is case insensitive. Parameter serialization defaults are compared
explicitly. Integer/number widening, enum set changes, nullable forms, property
requirements, array items, additional-properties flags and basic numeric/size
bounds have directional rules. Components are also compared with a neutral
context because consumers may exist outside observed operations.

JSON object ordering is irrelevant. Required/type/enum lists use set semantics;
security alternatives and scopes are order insensitive. Literal array order
inside enum objects is preserved. Output ordering and reason strings are stable.
Local references expand with bounded depth/work. External references are never
fetched. Recursive refs, unsupported siblings/compositions/dialects and redacted
authentication details require review; no complete compatibility claim is made
for those areas. Documentation-only annotations are ignored by supported rules.

## Limits and safety

Inputs use existing observer parsing bounds. Expansion is limited to 100,000
nodes, comparison to 2,000 changes, and persisted evidence to the repository's
1 MiB payload limit. Exceeding a limit fails explicitly before persistence; no
partial/truncated change set is reported as complete. OpenAPI 2 and unsupported
versions, unresolved local references and malformed supported structures fail.

Only approved sanitized contract snapshots are appropriate inputs. The observer
already removes examples/defaults and some credentials, so changes to removed
material cannot be recovered by this detector. Security changes and any coverage
warning require review. Classification does not authorize production actions.

Lifecycle remains observe → detect → propose → sandbox → replay → verify →
approve → deploy. No repair generation, deployment or LLM call is introduced.
