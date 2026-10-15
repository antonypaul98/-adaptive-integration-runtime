# AIR competitive roadmap — AIR-23 through AIR-34

Status: **AUTHORIZED, 1/12 checkpoints accepted**. AIR-23 is accepted; the earlier evidence and
control-plane roadmap remains accepted and is not reimplemented.

The estimated 10–16 week sequence is planning guidance, not a delivery promise.
Every checkpoint requires a bounded source slice, synthetic regressions, exact
PR-head PostgreSQL 16/17 CI with zero product skips, guarded merge, exact
merged-main CI, canonical acceptance records, and explicit writer release.

## Phase 1 — investigation and impact understanding

- **AIR-23 — Explainable failure investigation.** Deterministically derive
  privacy-conscious findings from exact evidence; bind every finding to its
  inputs; expose coverage and uncertainty; reject unsupported or unbounded
  inputs. Acceptance requires useful root-cause candidates without presenting
  correlation as proof, leaking payloads, or granting repair authority.
- **AIR-24 — Predictive breaking-change radar.** Rank evidence-backed future
  compatibility risks with calibrated uncertainty and time/source provenance.
  Acceptance requires deterministic baselines, false-positive visibility,
  conservative unsupported-case handling, and no claim of future certainty.
- **AIR-25 — Dependency visualization and impact reports.** Produce bounded,
  tenant-scoped graph/report projections over the explicit registry. Acceptance
  requires cycle-safe traversal, completeness warnings, deterministic layouts or
  exports, exact evidence links, and no inference of undeclared dependencies.

## Phase 2 — governed repair design and simulation

- **AIR-26 — Safe repair recommendations.** Generate declarative, review-only
  repair candidates bound to findings and revisions. Acceptance requires
  alternatives, trade-offs, uncertainty, provenance, and no automatic action.
- **AIR-27 — Integration digital twin.** Simulate supported declarative changes
  using synthetic fixtures only. Acceptance requires resource bounds,
  deterministic state, declared fidelity gaps, cleanup, and no production I/O.
- **AIR-28 — Repair verification and approval.** Verify a selected candidate
  against exact simulation evidence and explicit human approval. Acceptance
  requires stale-evidence rejection, exact target/revision binding, append-only
  decisions, and separation between approval and execution.

## Phase 3 — operations, evidence, and economics

- **AIR-29 — Connector health and drift monitoring.** Evaluate authorized,
  read-only connector observations. Acceptance requires bounded polling inputs,
  freshness/drift evidence, redaction, tenant isolation, and no credential or
  endpoint discovery.
- **AIR-30 — Evidence timeline.** Build deterministic append-only lifecycle views.
  Acceptance requires exact provenance, stable ordering, missing-evidence gaps,
  tenant isolation, and no rewriting of historical evidence.
- **AIR-31 — Reliability and cost simulation.** Model bounded synthetic failure,
  latency, retry, and cost scenarios. Acceptance requires explicit assumptions,
  reproducibility, sensitivity ranges, budgets, and no production forecast claim.

## Phase 4 — product surface and release proof

- **AIR-32 — Visual studio.** Provide a tenant-scoped, read-only investigation
  and simulation interface. Acceptance requires evidence drill-down, uncertainty
  display, accessibility, safe exports, and no hidden consequential actions.
- **AIR-33 — Governed AI-agent tool gateway.** Design and test mocks for a
  capability-minimal, approval-aware gateway. Acceptance in this roadmap is
  **design/mock-only**: schemas, policy checks, adversarial fixtures, audit, and
  denial behavior. Real external tool execution needs separate authorization.
- **AIR-34 — Benchmarking, security, and release acceptance.** Run reproducible
  synthetic benchmarks and adversarial/security acceptance. Acceptance requires
  published methodology, limitations, regression thresholds, privacy review,
  exact CI evidence, and explicit beta release criteria.

## Permanent boundary

This roadmap authorizes offline and read-only design and implementation only.
It does not authorize production execution, deployment, credentials, private
payloads, external tool actions, or bypass of human approval. Tenant isolation,
RLS, append-only evidence, deterministic bounds, provenance, exact target and
revision binding, and explicit consequential-action approval remain invariant.
