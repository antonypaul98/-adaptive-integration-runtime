# AIR-24 breaking-change radar

Status: **MERGED AND VERIFIED** for the bounded offline, diagnostic-only scope.

AIR-24 is an offline, deterministic triage aid over already accepted OpenAPI
change evidence. It ranks recurring non-safe detector signals and can compare
two strictly ordered, non-overlapping historical windows. Every radar and trend
report is canonical JSON with a content hash and exact source-evidence hashes.

Scores and score deltas are transparent heuristic points, not probabilities or
forecasts. A rising score means only that a detector signal has more weight in
the bounded candidate window. A missing signal is not evidence of safety.
Coverage gaps, unsupported semantics, differing observation counts, unlabeled
outcomes, and the unmeasurable false-positive rate remain explicit.

Inputs are limited to validated, caller-supplied `ChangeSet` metadata and UTC
timestamps. Raw contracts, locations, values, URLs, credentials, payloads, and
arbitrary error text are not copied into reports. Bounds limit each window to
2–64 observations and each radar to 128 signals.

The module performs no monitoring, network access, sleeping, external action,
repair, deployment, credential use, or production execution. Its outputs grant
diagnostic authority only and always require human review before consequential
action.

## Verified bounded-window slice

PR #36 source `8af03a75010730a86b1d0ef8a0971bd44ed029ce`, tree
`6e0db6c98f3fd4ccc11b54d15265ceca800ef278`, passed exact-head CI run
38915749154 on Python 3.12.15 with 788 tests and zero product skips on each of
PostgreSQL 16 and 17. Guarded merge
`9a23efb5feefd6e0e6e3974982c2a35e2a7c9109` passed exact merged-main run
38916048257 with the same result. This verifies only the bounded comparison
slice; AIR-24 remains in progress.

## Bounded offline outcome calibration

Outcome calibration accepts only fixed caller-declared labels bound to the
exact content hash of a radar and one of its exact signal IDs. Labels must be
strictly later than the radar window, use a fixed outcome vocabulary, and stay
within a 256-label bound. Duplicate labels, unknown signals, stale timestamps,
and mismatched radar hashes fail closed.

The report exposes labeled, unlabeled, resolved, and inconclusive coverage. A
descriptive observed-no-impact rate is withheld until at least five resolved
labels exist. The same minimum is applied independently to each signal, so a
well-labeled signal cannot make a sparsely labeled signal appear calibrated.
Per-signal sample counts and withheld-rate status remain visible in calibration
schema v2. Even when
available, an integer rate is not a probability,
forecast, causal estimate, or safety claim. Labels are not independently
verified, and no-impact does not prove that a change was harmless.

Calibration is offline and performs no observation, network access, production
data collection, repair, deployment, credential use, or external action. It
does not change the diagnostic-only authority of the radar.

## Verified outcome-calibration slice

PR #38 source `c364c20d66aaf5398383aa781c85fec257794f07`, tree
`1049af808bcf03bb2128bf7b4331cba6abe6d992`, passed exact-head CI run
39070558604 on Python 3.12.15 with 792 tests and zero product skips on each of
PostgreSQL 16 and 17. Guarded merge
`0c1e555f437ad17c3321dd7c43abd93352af1120` passed exact merged-main run
39070668492 with the same result. This verifies only bounded offline outcome
calibration; AIR-24 remains in progress.

## Final scoped acceptance review — 2026-10-20

AIR-24's five independently verified source slices and matching records PRs
satisfy the authorized acceptance contract. The implementation provides
deterministic evidence-bound baselines; strictly ordered, non-overlapping window
comparisons; conservative unsupported-case, coverage, and uncertainty output;
caller-declared false-positive visibility; independently gated descriptive
rates per signal; and exact time, radar, signal, source-evidence, and outcome-
evidence identities.

Source PRs #34, #36, #38, #40, and #42 and records PRs #35, #37, #39,
#41, and #43 passed exact-head and merged-main PostgreSQL 16/17 CI. The latest
records head `78122618600f0b608b4fc0338631f1358aeba827` and accepted main
`5d520c80a2ff83b215f9d06ad7e4ddb040248330` each passed 794 product tests
with zero failures or skips per matrix.

Acceptance remains limited to offline caller-supplied redacted metadata. Scores
and descriptive rates are not probabilities, forecasts, causal estimates, or
safety claims. AIR-24 performs no production observation, monitoring, repair,
approval, deployment, credential use, external action, or execution. AIR-25
dependency visualization and impact reports is next.
