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
