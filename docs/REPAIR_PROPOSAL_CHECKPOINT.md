# Repair Proposal Checkpoint

Working checkpoint for immutable repair-proposal records and explicit human approval gates.

## Safety invariants

- Proposal creation never executes a repair.
- Approval is explicitly bound to an exact immutable proposal/version.
- Approval never bypasses sandbox, replay, verification, or deployment controls.
- Evidence and decisions remain tenant isolated and auditable.
- Missing, malformed, stale, or cross-tenant references fail closed.
