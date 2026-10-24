# Workflow reliability — stabilization 2026-10-03

## AIR-25 deterministic visualization candidate (2026-10-23)

The source candidate is based on exact main
`530fc80ea64dc480fc20e350bd3f3d7ea4368513` and derives only redacted,
read-only presentation data from an already canonical dependency projection.
It revalidates node and edge identities, source hashes, summary counts,
coverage limits and authority before assigning stable opaque aliases and review
lanes. It copies no dependency names, mappings, locations, operations or free
form warning text into the output. It explicitly does not authenticate an
in-memory projection's origin; persisted origin remains the responsibility of
the existing tenant-scoped recomputation path.

Local Python 3.12.14 validation passed 21 focused tests, 483 portable product
tests with 343 PostgreSQL tests deselected, and 15 of 16 infrastructure guards;
the sole skip is the documented Memory-only diagnostic. At local candidate
validation, PostgreSQL 16/17 PR CI and merged-main CI were pending; their exact
receipt follows. Canonical acceptance records remain pending.
No discovery, production observation, credential/payload access, external
action, repair, approval, deployment, execution or safety claim was added.

Source PR #52 head `cd5b51cd44030808c98b09f921b93e4935feaae4`
passed exact run 39969307864, and merged main
`007e09a6c75a5918050f8f3ba672a3d2ec25568c` passed exact push run
39969589955. Python 3.12.15 with PostgreSQL 16 and 17 passed 826 product tests
with zero product skips in every matrix. Canonical records CI and writer release
remain pending.

No product checkpoint advanced by the 2026-10-03 stabilization below. No
feature source/test changed in that stabilization.

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


## AIR-25 impact completeness-warning source receipt (2026-10-24)

Impact-path source and records PRs #58/#59 are verified through exact main
`f6f072f00e71c97f8ac00cd351ffb526eead5815` and PostgreSQL 16/17 final-main
run 40082210089 with 843 product tests and zero product skips per matrix. The
writer is explicitly released in PR #59.

The new candidate reports the exact hash identities of registered nodes not
reachable from the selected seeds and emits only fixed coverage-warning codes.
It reconciles registered, reachable and unreachable counts and does not copy
caller warning text. This remains bounded to one validated explicit projection;
it infers no undeclared dependency and grants no completeness, safety, repair,
approval, deployment, external-action or execution authority. Local Python
3.12.14 validation passed 32 focused tests and 494 portable product tests with
351 PostgreSQL cases deselected. Source PR #60 exact head
`7960898a1da1b515f51c42011c669f490201da86`, tree
`d3d68a10b27fcfe87b0bfaf39b25d5e1c5f3b341`, passed run 40129737781 on
Python 3.12.15; PostgreSQL 16 and 17 each passed 845 product tests with zero
product skips. Guarded merge produced exact main
`f276519803d5d85a9eaedc00ea4b40a4c7d3db75`, and run 40129867893 passed the
same matrix. This records change requires its own exact PR and merged-main CI
before explicit writer release. AIR-25 remains in progress at 2/12.

## AIR-25 deterministic dependency projection source (2026-10-20)

The first bounded source slice projects only caller-supplied explicit dependency
registrations, declared workflow edges and verified impact metadata into stable
content-addressed nodes and edges. It preserves registry-only coverage warnings
and labels an unannotated node as `no_recorded_impact`, never as safe.

No dependency discovery, production observation, payload/credential access,
external call, repair, approval, deployment or execution is added. Exact
PostgreSQL 16/17 PR and merged-main CI with zero product skips is required
before a canonical records receipt or further AIR-25 source work.

## AIR-25 dependency projection source receipt (2026-10-20)

PR #45 source `fcd0902b00ddd9a55668d45935ccc09fb31b86c0`, tree
`1ea5f0c99412cf6cc9bddfe9eb58d2cf8c470336`, passed exact-head PR CI
39474623923 on Python 3.12.15. PostgreSQL 16 and 17 each reported 802 tests
passed with zero failures and zero product skips. Guarded merge produced main
`dfb7acd43c9f6786a4bf09d93084e8cc325c6ecc`; exact push CI 39474887370
passed the same 802/0/0 result per matrix.

The projection consumes only caller-supplied explicit dependency registrations,
declared workflow edges and verified content-addressed impact metadata. It emits
stable review nodes and edges, registry-only coverage and an explicit statement
that missing impact evidence is not proof of safety. It adds no discovery,
production observation, tenant-crossing query, payload or credential access,
external call, repair, approval, deployment or execution authority. This
records-only change requires its own exact PostgreSQL 16/17 PR and merged-main
CI before the writer is released or another source slice begins.

## AIR-25 recorded-impact summary source receipt (2026-10-21)

PR #48 head `c78c8c6e6510ebe31275232311f9c2b007c1e3b8`, tree
`8b341bf750348e0de396f52f8432508127de970f`, passed exact PR run
39576942933 on Python 3.12.15; PostgreSQL 16 and 17 each passed 804 tests
with zero product skips. Guarded merge produced main
`ab355e398bc99cdbd5e5da4227fb97145712ecc9`; exact main push run
39577293315 passed the same 804-test matrix with zero product skips.

The summary counts only caller-supplied recorded dependency nodes, workflow
edges and verified impact annotations. Counts are not probabilities,
completeness claims, safety claims or authority. No discovery, production
observation, payload/credential access, external action, repair, approval,
deployment or execution was added. AIR-25 remains in progress at 2/12.

## AIR-25 projection persistence source scope (2026-10-21)

This bounded slice stores the existing deterministic projection as immutable,
tenant-scoped evidence bound to one exact registry and optional exact impact
artifact. Reload recomputes the projection from those authenticated inputs and
fails closed on tampering, mismatched registry/impact evidence or cross-tenant
access. Database validation retains append-only audit, RLS, strict references,
explicit registry-only coverage and read-only authority.

It adds no dependency discovery, production observation, payload/credential
access, external action, repair, approval, deployment, agent/tool execution,
probability, completeness or safety claim. Exact PostgreSQL 16/17 source PR
and merged-main CI are required before canonical records or writer release.

## AIR-25 projection persistence source receipt (2026-10-23)

- Source PR #50: head `c5161360dc12e2a658a4636020f583c3133a5727`, tree `996cd451fdb438fa4df34d356493d8bd86969dab`.
- Exact-head run 39871385727: Python 3.12.15; PostgreSQL 16 and 17 each passed
  815 product tests with zero product skips.
- Guarded merge: exact main `44331ae748f3995018000b29b755a4ba81c4f730`.
- Exact merged-main run 39877439471: the same 815-test PostgreSQL 16/17 matrix
  passed with zero product skips.
- Authority remains read-only evidence persistence: no discovery, production
  observation, credential/payload access, repair, approval, deployment,
  external action, agent/tool execution, probability, completeness or safety
  claim. AIR-25 remains in progress at 2/12.

## AIR-25 visualization persistence source scope (2026-10-23)

This bounded slice persists only the existing redacted dependency presentation,
bound to one exact immutable tenant-scoped projection. Reload authenticates and
recomputes the projection, then deterministically recomputes the presentation;
it fails closed on cross-tenant access, substitution or tampering. Database
validation enforces the exact projection reference, content hashes, explicit
unknown/safety boundary and read-only authority.

Local Python 3.12.14 validation passed 21 focused tests, 483 portable product
tests with 351 PostgreSQL cases deselected, and 15 infrastructure guards with
one documented Memory-only skip. Source head
`aa77d6284bf3afbfc37590dd5726c9c689d6b9ee` passed exact PR run
`40002653145`; PostgreSQL 16 and 17 each passed 834 product tests on Python
3.12.15 with zero product skips. Guarded merge produced exact main
`fbd6cf37fd7f6f471169e4eab749636051a03e9c`, and exact merged-main run
`40039245945` passed the same matrix. Canonical records CI and writer release
remain pending. No raw
dependency metadata, discovery, production observation, credentials, payload
access, repair, approval, deployment, external action, agent/tool execution,
probability, completeness or safety authority is added.

## AIR-25 cycle-safe impact-report candidate (2026-10-24)

The candidate is based on exact main
`532cb5fca2a69c241faa9ec3afbdf87eb204626f`. It validates the complete explicit
projection before bounded downstream traversal, terminates cycles through visited
state, and records deterministic strongly connected components with exact
content-addressed node and edge identities. It exposes no raw dependency names,
mappings, locations or operations and never infers undeclared dependencies.

Local Python 3.12.14 validation passed 28 focused tests, 490 portable product
tests with 351 PostgreSQL cases deselected, and 15 of 16 infrastructure guards;
the sole skip is the documented Memory-only diagnostic. PostgreSQL 16/17 PR and
merged-main CI are pending. This slice adds no production access, repair,
approval, deployment, external action, execution, completeness or safety
authority.

Source PR #56 head `08f4be44d631b7b584caed9f977114c10eb33ea3`, tree
`570130da6975a9bd018f1c48dd87d64c8f201132`, passed exact run
40066183394; PostgreSQL 16 and 17 each passed 841 product tests with zero
product skips. Guarded merge `9e2a8a387ef5573f1969f6ae76a09fbd8e567dc9`
passed exact merged-main run 40066344089 with the same result. Canonical records
CI and writer release remain pending.

Records PR #57 head `a17b8bd4bbd6c40ced5be2848da30a9b3fe8e846`
passed run 40066597342; guarded merge
`aa87735e78e0173840662731a7593753baa937a2` passed exact-main run
40066726558. PostgreSQL 16 and 17 each passed 841 product tests with zero
product skips, and the writer was explicitly released.

The next source candidate adds a deterministic hash-only shortest-path witness
predecessor forest over the already validated explicit traversal. It is bounded
to one entry per reachable node, does not enumerate all paths, and grants no
discovery, completeness, repair, approval, deployment, action or execution
authority. Local Python 3.12.14 validation passed 30 focused tests, 492
portable product tests with 351 PostgreSQL cases deselected, and 15
infrastructure guards with one documented Memory-only skip. Exact PR-head and
merged-main PostgreSQL 16/17 CI are required.

Source PR #58 exact head `086099da7af047dac6b73c12d8dcfa6d61f3243e`,
tree `8f63a6718d32af4e6c08f0584fb8f5d64272d078`, passed run
40069743139. Python 3.12.15 on PostgreSQL 16 and 17 passed 843 product tests
with zero product skips per matrix. Guarded merge produced exact main
`86ffa37cd1f7f89d73bf9567cdfe14f54535a35a`; exact merged-main run
40081774837 passed the same matrix. Canonical records CI and writer release
remain pending. AIR-25 remains in progress at 2/12.
