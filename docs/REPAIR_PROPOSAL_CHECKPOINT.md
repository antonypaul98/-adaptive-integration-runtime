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

## Implemented slice

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

## Implementation increment (recovered and database-validated 2026-09-30)

`air.repair_proposal` now supplies `create_proposal`, `load_proposal`, `decide`,
`authorization`, and `proposal_status`. Descriptions are bounded declarative JSON,
with a supported change type, proposed state, rationale, risk and human/deterministic
provenance. The exact direct or transitive impact item supplies the target and
current-state registry reference; its immutable impact links preserve change and
observation provenance. There is no execution or LLM capability.

The canonical artifact content hash is the deterministic proposal identity and
idempotency key. Artifact UUIDs remain the existing storage identity. Revisions
reference the exact prior artifact/hash, retain the target integration/mapping and
increment revision, bounded at 100. Database-created timestamps and append-only
audit entries provide creation/decision time. No timestamp is included in the
idempotent semantic payload.

Migration 006 reuses artifacts, audit and RLS. It validates proposal/impact/parent
and decision links, binds exact revision/hash, prevents multiple successors or
conflicting decisions with unique indexes, and serializes revision/decision writes
with transaction advisory locks. Lifecycle is derived from immutable evidence:
PROPOSED, APPROVED, REJECTED, SUPERSEDED. A revision invalidates the prior proposal's
authorization even if it had been approved.

Human identities must be provisioned by an administrator using `bind_reviewer`
with a dedicated authenticated database login. Service credentials cannot approve,
self-provision or impersonate reviewers via a caller-supplied name/GUC. An identity
provider/UI integration is not provided. Reviewers must explicitly choose APPROVED
or REJECTED and confirm the exact proposal hash/revision. The stored reviewer comes
from authenticated `session_user`, not request data. Repeated identical decisions
are idempotent; changes of decision or reviewer conflict.

`authorization` requires the exact proposal hash/revision and caller's current
impact identity. AIR has no global mutable current-contract pointer; this API does
not invent one or infer that historical evidence is globally current. Later stage
controllers must supply their authoritative current impact and recheck the gate.
The returned decision is evidence, not a transferable execution/deployment token.
Sandbox, replay, verification and deployment approval remain future, separate gates.

### Validation and recovery evidence

- Starting main: `8e57f6000b94525cfc82526e251c6ba5e1f9a34a`.
- Recovered actual local commit `60c44934504ac64c5f43376580dfc9993ba82fcd`
  from the existing Work checkout, branch and reflog. No source was rebuilt.
- Normal HTTPS Git push lacked credentials. The connected GitHub API transplanted
  the source as `113bdc7f6cbc60ffe765e33d77278179027da5c7`; its exact tree
  `4ceed30608615e3f7052f73e4f884b33cadb862d` equals the recovered commit's tree.
  The historical local SHA is not claimed to exist on GitHub.
- Local proposal suite: 36 passed. Full non-PostgreSQL suite: 313 passed,
  188 database cases deselected.
- Exact implementation-head PR CI run **36668960578**: **501 passed, no skips**
  on each of PostgreSQL **16 and 17**, including all 188 database cases.
- Canonical integration: PR **#7**, `work/repair-proposal-foundation`.
  The final implementation/documentation head passed both PostgreSQL jobs before merge (receipt below).
- The empty local `work/repair-proposal-approval` branch is superseded by this
  canonical workstream; recovered historical commits remain preserved.
- No physical database deployment, repair execution, identity-provider integration,
  sandbox/replay stage or infrastructure deployment is claimed by this checkpoint.

## Verified integration — 2026-09-30

Checkpoint **AIR accepted on main** through PR #7.

- Exact PR head: `99299c1698d3c4a9542bb207f4b104b33bec9853`; CI run `36669301907` succeeded.
- Merge: `bd98462682b1e9775ac565b47dc6dc60a4c4e55d`, fetched and verified locally.
- Merged-main CI run `36669480007` succeeded.
- Local reviewed/tested source tree equals the merged implementation tree.
- This follow-up records the completed integration; it changes documentation only.
