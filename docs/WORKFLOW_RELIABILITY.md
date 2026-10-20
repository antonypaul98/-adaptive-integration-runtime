# Workflow reliability — stabilization 2026-10-03

No product checkpoint advanced. No feature source/test changed.

## Environment

Metadata minimum remains Python >=3.11 where present; this repository's
reproducible development/CI interpreter is **3.12** (`.python-version`).
Other interpreters are not validated by this stabilization. Existing dependency
ranges are retained; version ranges do not guarantee byte-for-byte dependency
reproducibility. No dependencies upgraded or new lockfile guessed.

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python scripts/session_preflight.py
python -m pip install '.[test]'
python -m pip check
python scripts/ci_diagnostics.py
```

Preflight failing on a new clean checkout on main is intentional: switch to the
existing recorded branch. Missing gh is a tooling blocker, not proof that the
connected GitHub integration is unavailable. Follow AGENTS.md's fallback.
A dry-run is preliminary; branch protections/token scopes can still reject a
real write. Verify the first actual coherent commit remotely before larger work.

## CI event contract

Push all branches and all PRs; PostgreSQL matrix 16 and 17, Python 3.12.
CI uses scoped concurrency, contents:read, bounded jobs and early environment
checks. Package import/pip check/connectivity success is not product acceptance.
Never print environment variables, tokens, DSNs or credential helper output.

This infrastructure commit uses `[skip ci]` deliberately to preserve execution
capacity and avoid running feature-checkpoint suites in this repair-only run.
No PR is opened for a skipped commit (required checks could remain pending).
Future normal commits must not copy that marker; expected push/PR events will
run the documented workflows. CI execution after these edits is not claimed.

## Historical first-pass audit evidence (superseded by current state)

Existing exact-head run 37072179798 failed: 16 missing reviewer fixture setup errors; PostgreSQL containers/install passed. Feature-test repair intentionally deferred.

Observed main: `1a724a8f453a83090f7f0235198d0c5b29daa760`. Active feature head: `9bd920aa808076fb1e4ceb849ee102859ebd1c37`.
All current remote feature work was ahead of main, not behind it. Local worktrees
from September 30 had stale refs; some contained uncommitted/untracked work.
Shell access initially failed through an unavailable sandbox proxy; a permitted
network execution context restored read/fetch. Shell GitHub CLI was absent;
connector repository metadata reported push permission. Actual connector
publication must be verified before claiming a durable fix.

`docs/recovery/2026-10-03/` preserves source patches without applying them.
Original worktrees remain untouched. AgentFlight also had a local-only commit
63fcc3d; its patch is archived, not activated or merged. These archives cover the
identified September 30 worktrees, not inaccessible devices or unknown sessions.

## Branch discipline

Use `git fetch --all --prune`, `git merge-base origin/main HEAD`,
`git rev-list --left-right --count origin/main...HEAD` and
`git rev-list --left-right --count HEAD...origin/<active-branch>`.
Inspect dirty status before switching and check `git worktree list`.
No deletions are needed. Historical classifications are in `docs/BRANCH_AUDIT.md`.
Only merge stale main into a feature branch or rebase after reviewing conflicts
and scope; this stabilization does neither. Preserve divergent local variants
for comparison, not automatic integration.

## PostgreSQL boundary

Local non-PostgreSQL: `python -m pytest -m 'not postgres'`. Report the exact
command and deselected tests; **integration tests pending CI** when PostgreSQL
is absent. Real integration: provision a fresh disposable loopback `air_test`
database, set AIR_TEST_DATABASE_URL privately, then `python -m pytest -m postgres`.
Full CI on PostgreSQL 16/17 remains the full-validation boundary. Existing
conftest already fails CI when the database variable is absent. Missing reviewer
fixture errors were recorded in the first audit; consult current CHECKPOINT_STATE for subsequent resolution.
Never remove/skip failing feature tests to make this infrastructure run green.

## Follow-up live audit and current operating contract

Observed push 37100280869 and PR 37100373417 succeeded at 12515b8. PR #9 remains open/unmerged. Previous missing reviewer fixture failure is historical, already repaired before this run.

Current observations, CI SHA/event/URL, PR, and last-session blocker are in
CHECKPOINT_STATE.json. observed_feature_sha identifies the last source/test
commit; observed_branch_sha identifies the fetched branch head. The current
repository SHA is resolved with git rev-parse HEAD, never a self-reference.
Local tests not run this session are not failures. Historical CI successes are
not evidence for a later skipped head. Prior local receipts are attributed,
not re-executed.

Core CI uses workflow+ref concurrency: a newer push cancels the previous push
on that ref; PR and push refs are separate and may both run. Cancellation is
not a pass. Existing timeouts, interpreter pins, dependency ranges, PostgreSQL
services and workflow permissions are retained. No dependency migration.

The commit-message validator rejects standard Actions skip directives on
ordinary commits. An explicit infrastructure exception requires an audited
file list; install/integrate the local hook as described in AGENTS.md, and call
the same validator before API writes. Hooks cannot enforce remote API behavior
or control the external scheduler.

Bounded infrastructure validation: python -m unittest discover -s scripts/tests
-p 'test_*.py'. No product suites, database matrices or camera access needed.
The Memory direct-script import regression uses real isolated Python import
resolution and a source-only fixture, with only pip-check mocked.

This follow-up intentionally skips feature-suite CI. For AIR's existing PR #9,
the prior successful SHA remains recorded; the new infrastructure head is
not claimed validated. No PR is merged, marked complete or handed to replay.

On every stop, persist the five-field blocker receipt into CHECKPOINT_STATE,
commit/synchronize it, and verify remote SHA. .git/session-preflight.json alone
is ephemeral. Missing API/shell credentials, Actions service outages, quotas,
runner availability, the external hourly scheduler and a physical Mac cannot
be repaired solely by repository code. Report that exact external layer.

## AIR-24 first risk-baseline receipt (2026-10-16)

PR #34 source `93e8e0fed2715aee0a2b3121c844ce0a5eae5c66`, tree
`1e8430fa7f3344d0598004efd459a346055fab85`, passed exact-head PR CI
38849674422 on Python 3.12.15 with 785 tests, zero failures and zero skips on
PostgreSQL 16 and 17. Guarded merge produced main
`a6aac4f0ad942f4911d18a7541ebc0faa521c13d`; exact push CI 38849847090
passed the same 785/0/0 result per matrix.

The slice is offline and deterministic, using caller-supplied redacted metadata
with exact change/impact evidence binding and explicit coverage/uncertainty. It
performs no production monitoring, external call, repair, deployment, approval
bypass, credential/payload handling, or executor action. This records change
must pass its own exact PostgreSQL 16/17 PR and merged-main CI before release.

## AIR-24 bounded risk-window trend receipt (2026-10-16)

PR #36 source `8af03a75010730a86b1d0ef8a0971bd44ed029ce`, tree
`6e0db6c98f3fd4ccc11b54d15265ceca800ef278`, passed exact-head PR CI
38915749154 on Python 3.12.15 with 788 tests, zero failures and zero skips on
PostgreSQL 16 and 17. Guarded merge produced main
`9a23efb5feefd6e0e6e3974982c2a35e2a7c9109`; exact push CI 38916048257
passed the same 788/0/0 result per matrix.

The comparison accepts only separately validated bounded radar windows and
requires strict ordering without overlap. Reports bind exact canonical radar
and evidence hashes, expose coverage and uncertainty, and state that score
deltas are heuristic points rather than probabilities. Missing candidate
signals are not evidence of safety. No monitoring, network action, repair,
deployment, approval bypass, credential handling, or production execution was
added. This records change requires its own exact PR and merged-main CI.

## AIR-24 bounded outcome-calibration receipt (2026-10-17)

PR #38 source `c364c20d66aaf5398383aa781c85fec257794f07`, tree
`1049af808bcf03bb2128bf7b4331cba6abe6d992`, passed exact-head PR CI
39070558604 on Python 3.12.15 with 792 tests, zero failures and zero skips on
PostgreSQL 16 and 17. Guarded merge produced main
`0c1e555f437ad17c3321dd7c43abd93352af1120`; exact push CI 39070668492
passed the same 792/0/0 result per matrix.

The calibration accepts fixed caller-declared labels only after the radar
window and binds them to exact radar and signal hashes. It exposes coverage and
withholds a descriptive no-impact rate below five resolved labels. Labels are
not independently verified; no-impact is not a safety claim. No production
observation, network access, credentials, repair, deployment, approval bypass,
or external execution was added. This records change requires its own exact PR
and merged-main CI.

## AIR-24 per-signal calibration receipt (2026-10-18)

PR #40 source `9b955918f060e78aff8bc71ae5ba43aeef03761f`, tree
`10196c19d621842bbf98b7a5a2cc2d6a44437d31`, passed exact-head PR CI
39114728167 on Python 3.12.15 with 793 tests, zero failures and zero skips on
PostgreSQL 16 and 17. Guarded merge produced main
`1131281ee213f4fd943f3ca17226d5dc95e3a45e`; exact push CI 39114895773
passed the same 793/0/0 result per matrix.

Each radar signal independently requires the fixed minimum resolved-label
sample before exposing a descriptive no-impact rate. Sparse signal coverage
remains explicit instead of inheriting a global calibration claim. Caller
labels remain unverified offline metadata; rates are descriptive integer
summaries, not probabilities, forecasts, causal estimates, safety claims, or
repair, deployment, approval or execution authority. No production
observation, network access, credentials, external action or approval bypass
was added. This records change requires its own exact PR and merged-main CI
before writer release. AIR-24 remains in progress at 1/12 accepted checkpoints.

## AIR-24 bounded-scope acceptance closure (2026-10-20)

AIR-24 is accepted only for deterministic offline diagnostic metadata. Source
PRs #34, #36, #38, #40, and #42 and records PRs #35, #37, #39, #41, and
#43 provide independently verified baselines, historical-window comparisons,
coverage and unsupported-case uncertainty, caller-declared outcome visibility,
per-signal descriptive calibration, and exact time/source/evidence identities.

Records head `78122618600f0b608b4fc0338631f1358aeba827` passed exact PR CI
39422447207, and merged main `5d520c80a2ff83b215f9d06ad7e4ddb040248330`
passed exact push CI 39422771453. PostgreSQL 16 and 17 each executed 794 tests
with zero failures and zero skips in both runs. Writer ownership was explicitly
released in PR #43.

No accepted path performs production observation, monitoring, network access,
repair, approval, deployment, credential use, external action, or execution.
Scores and descriptive rates are not probabilities, forecasts, causal estimates,
or safety claims. This closure must pass its own exact PR-head and merged-main
CI before the 2/12 acceptance record is canonical and AIR-25 work begins.

## AIR-24 outcome-evidence identity receipt (2026-10-20)

PR #42 source `80b27fc375f04848439fb423d7f29ebf9dba9dda`, tree
`7f16acec94cd80701093d67eec76e2d3c157c739`, passed exact-head PR CI
39184925190 on Python 3.12.15 with 794 tests, zero failures and zero skips on
PostgreSQL 16 and 17. Guarded merge produced main
`ecbbd1b784c3d1ee44d1f328494ef910d9875d10`; exact push CI 39185082984
passed the same 794/0/0 result per matrix.

Every caller-declared outcome label now requires a bounded SHA-256 evidence
identity. That identity is included in the content-addressed label receipt, and
reuse of one evidence identity under another timestamp fails closed. Evidence
identities and outcome labels remain unverified offline caller metadata; this
does not establish probability, forecasting accuracy, causality or safety and
adds no repair, approval, deployment, credential or execution authority. No
production observation, network access, external action or approval bypass was
added. This records change requires its own exact PR and merged-main CI before
writer release. AIR-24 remains in progress at 1/12 accepted checkpoints.
