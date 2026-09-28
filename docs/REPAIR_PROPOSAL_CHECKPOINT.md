# Repair Proposal Checkpoint

Working checkpoint for immutable repair-proposal records and explicit human approval gates.

## Safety invariants

- Proposal creation never executes a repair.
- Approval is explicitly bound to an exact immutable proposal/version.
- Approval never bypasses sandbox, replay, verification, or deployment controls.
- Evidence and decisions remain tenant isolated and auditable.
- Missing, malformed, stale, or cross-tenant references fail closed.

## Repository integration verified

The existing persistence boundary is `EvidenceTransaction` in `air/postgres.py`.
Repair evidence must reuse `air.artifacts`, RLS, append-only audit triggers,
canonical JSON, immutable idempotency semantics, and tenant-scoped `get_by_id`.
It must not introduce a second evidence store.

The triggering source is an immutable `contract_dependency_impact` loaded through
`load_impact`. A proposal binds the exact impact artifact id/hash and carries the
already-bound change-evidence and dependency-registry references. A revision is a
new immutable proposal that names the superseded proposal; it never mutates it.

An explicit decision is separate immutable evidence. It binds the proposal artifact
id, content hash, deterministic proposal hash, and revision. The only authorization
decision is an explicit APPROVED record. REJECTED is terminal evidence but not
authorization. Conflicting retries must fail closed rather than replace a decision.
Neither proposal creation nor approval executes a repair.

## Next implementation slice

1. Add `air/repair_proposal.py` with deterministic proposal identity, immutable
   revisions, exact impact binding, explicit APPROVED/REJECTED decision evidence,
   and a read-only authorization query.
2. Add unit tests for deterministic identity, revisions, rejection, exact binding,
   malformed/missing references, and no-execution semantics.
3. Add migration 006 validating same-tenant proposal/impact/supersedes/decision
   links and exact hashes at INSERT time.
4. Add PostgreSQL adversarial tests for RLS, forged/cross-tenant links,
   immutability, idempotency, conflicting/concurrent decisions and reload.
5. Run the full PostgreSQL 16/17 matrix on the exact branch head before merge.
