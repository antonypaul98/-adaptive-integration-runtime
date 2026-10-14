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

## Tenant-scoped investigation evidence

`persist_investigation` derives a redacted report only from an exact immutable
`replay_verification` artifact and stores it through the existing tenant RLS,
append-only artifact, content-hash, and audit boundaries. The record binds the
replay artifact identity and hash to canonical report bytes; `load_investigation`
recomputes the report from replay evidence before returning it.

Migration 011 independently checks the same-tenant replay link, report hash,
fixed schema, exact replay status and case hashes, finding identities, coverage,
uncertainty, and diagnostic-only authority even for direct SQL inserts. Raw
fixture values and paths are not copied into investigation evidence. Cross-tenant
reads and forged links fail closed, and byte-identical retries remain idempotent.

This persistence slice performs no replay, repair, external call, approval,
deployment, or production action. Candidate-correlation persistence and wider
sandbox/replay lifecycle correlation remain future AIR-23 work.

## Candidate correlation source slice

`air.failure_investigation.correlate_candidates` accepts only explicit,
caller-declared links between a failing replay case and an exact dependency
impact. It validates the canonical investigation, exact change-set binding,
impact identity, supported evidence versions, and bounded link count before
emitting any candidate. It never correlates by names, payload values, paths,
timing, or model inference.

The output contains only stable case, finding, impact, and change identifiers;
contract locations, dependency names, raw values, and explanations remain
excluded. Every candidate is labeled
`SUPPORTED_CORRELATION_NOT_CAUSAL_PROOF`. Unmatched failures, limited coverage,
and diagnostic-only authority remain explicit. This is still an offline,
read-only source slice: persistence, tenant-scoped retrieval, sandbox/replay
cross-evidence correlation, and AIR-23 acceptance remain future work.

## Candidate correlation source slice verified — 2026-10-13

Source head `8f75c1dda0e8bc55dcb4f30b305d598e3ec1b448` passed exact
PR-event run `38383623654`; PostgreSQL 16 and 17 each reported 740 passed,
zero failed and zero skipped. Guarded PR #26 merge
`34bf72d59c9a6203efe41028f916dfc1c93b1f90` passed exact merged-main
run `38383837836` with the same 740/0/0 result on both versions.

Pinned local Python 3.12.14 validation: 70 focused tests passed; the complete
non-PostgreSQL suite passed 443 tests with 297 database tests explicitly
deselected for CI. Infrastructure passed 15 tests with one established
Memory-only skip. Dependency, diagnostics, compilation, JSON and whitespace
checks passed. This receipt verifies the second source slice, not AIR-23
completion.

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
