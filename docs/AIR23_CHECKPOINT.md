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

## First source slice verified — 2026-10-13

Source head `249245f95e3078c3115520101384c98d37c9200e` passed exact
PR-event run `38351555551`; PostgreSQL 16 and 17 each reported 730 passed,
zero failed and zero skipped. Guarded PR #24 merge
`750b88bd80a98617b19c46dd967a17e5c3f83ad6` passed exact merged-main
run `38351716887` with the same 730/0/0 result on both versions.

Pinned local Python 3.12.14 validation: 34 focused tests passed; the complete
non-PostgreSQL suite passed 433 tests with 297 database tests explicitly
deselected for CI. Infrastructure passed 15 tests with one established
Memory-only skip. Dependency, diagnostics, compilation, JSON and whitespace
checks passed. This receipt verifies one source slice, not AIR-23 completion.
