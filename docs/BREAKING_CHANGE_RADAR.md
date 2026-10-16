# AIR-24 breaking-change radar

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
