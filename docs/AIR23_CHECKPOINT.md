# AIR-23 — Explainable failure investigation

Status: **IN_PROGRESS**.

The first source slice explains exact failures from the accepted bounded replay
verifier. `air.failure_investigation.investigate_replay` emits deterministic
findings bound to the normalized fixture and observed/expected hashes. Reports
exclude state values, fixture paths, expected values, and exception details.

This slice proves only that a recorded projection mismatched. It explicitly
states that root-cause coverage is not established and that passing recorded
cases say nothing about unrecorded behavior. The output is diagnostic only and
grants no repair, approval, deployment, or execution authority.

Before AIR-23 can be accepted, later bounded slices must add evidence-backed
candidate-cause correlation across existing change, impact, sandbox, and replay
artifacts; preserve tenant isolation for persisted investigations; expose
unsupported evidence and ambiguity; and pass exact PostgreSQL 16/17 CI. No
candidate may be presented as causal proof without direct evidence.
