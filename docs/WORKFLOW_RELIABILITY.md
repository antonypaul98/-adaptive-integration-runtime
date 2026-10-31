# Workflow reliability — stabilization 2026-10-03

## Demo-first persisted impact candidate (2026-10-31)

Live reconciliation found no open PR and exact main
`2125fe57735990849945e338f8e7867229a901d5`. The prior offline demo source and
records chain is accepted through final-main run 41009164051 and explicit writer
release. Writer `AIR-DEMO-PERSISTED-20261031` is now claimed for the next bounded
demo gap.

The candidate adds one repository-native orchestration boundary over the existing
tenant-scoped change, registry, impact, projection and redacted-visualization
artifacts. It accepts only already authenticated immutable snapshot IDs plus an
explicit registry, persists all derived artifacts in one caller transaction,
reloads and recomputes all five, and returns a redacted receipt of identities,
hashes and bounded counts. It does not invent observation provenance. A rejected
registry or unauthorized snapshot rolls the complete new chain back.

Reuse review selected the existing verified AIR contracts; there is no
third-party source, translated logic, dependency, schema, model, account,
download or network operation. Python 3.12.14 passes 28 focused tests with three
PostgreSQL cases reserved and 515 portable tests with 355 PostgreSQL cases
deselected. Exact-head PostgreSQL 16/17 PR CI with zero product skips, guarded
merge, merged-main CI, independent records acceptance and writer release remain
mandatory.

This is local candidate evidence only. It grants no production observation,
dependency discovery, compatibility or safety conclusion, repair, approval,
deployment, external action or execution authority.

Initial exact-head run 41185987620 correctly failed both PostgreSQL lanes: each
reported 868 passed, two failed and zero skipped. The synthetic snapshot used an
IP rejected by the established provenance validator, and the rollback case used
a dependency whose operation conflicted during input parsing instead of reaching
the intended post-write validation failure. Both fixtures are corrected locally;
the failed run remains evidence and a new exact-head run is required.

## Demo-first offline impact candidate (2026-10-30)

Source PR #79 exact head `86da3e95a0cd015e3f1af8b5b4ffe9caa7de5b30`
and tree `419038cd20e68839dc7b46bc32797b7e8c7f5287` passed exact run
41008196526. Expected-head merge produced exact main
`39668bef31373217dd5f34ddb90d8eb01c3cb0e5`; main-push run 41008493283
passed. Python 3.12.15 on PostgreSQL 16 and 17 passed 866 product tests with
zero product skips in both gates. Each lane ran 16 infrastructure guards: 15
passed and one established Memory-only case skipped. Canonical records and
their own PR/final-main CI remain required before writer release.

Live GitHub reconciliation found no open PR and exact final main
`de0920370a882f03b458114e373fd20ab68770fb`; the prior AIR-25 writer is released.
Writer `AIR-DEMO-OFFLINE-IMPACT-20261030` is claimed at PR #78 comment
6515580522. The candidate is based on that exact main and contains no third-party
code, dependency, model, account, download, or network operation.

The checked-in CLI and fixtures exercise the existing pure change to impact to
projection to redacted-visualization pipeline. Local Python 3.12.14 validation
passes 6 focused and 515 portable tests, with 351 PostgreSQL cases reserved for
CI. Infrastructure runs 16 guards: 15 pass and one established Memory-only case
is skipped. Exact PostgreSQL 16/17 PR and merged-main CI with zero product skips,
independent canonical records, and explicit writer release remain mandatory.

This evidence is local candidate evidence only. It grants no network access,
production observation, dependency discovery, compatibility/safety conclusion,
repair, approval, deployment, external action, or execution authority.

## AIR-25 declared branch exclusive reach source receipt (2026-10-29)

Source PR #77 exact head `31f73365d068f736ea08968e39707dfa93fd884a`,
tree `ce54488773a8b6199ed6059bc7992dd65183d180`, passed exact run
40850076507. Expected-head merge produced main
`e056d2cda11c5d4cf3ff448449ecef39e7efcc51`, and main-push run 40850408809
passed. Python 3.12.15 on PostgreSQL 16 and 17 passed 860 product tests with
zero product skips in both gates. Each lane ran 16 infrastructure guards: 15
passed and one established Memory-only case skipped.

The evidence remains deterministic, compact, hash-only and read-only over one
validated explicit projection. It does not establish path or dependency
completeness, importance, risk, probability or safety and grants no repair,
approval, deployment, external-action or execution authority. Independent
records CI, final-main CI and explicit writer release remain required.

## AIR-25 declared branch exclusive reach candidate (2026-10-29)

The candidate is rooted at exact verified main
`48c544e117fb5c2f340d4aa463ab83e7a526f4b8`, after declared branch reach
overlap source/records verification and explicit writer release. Reuse-first
review selected AIR's existing validated projection, cycle-safe queue traversal,
canonical hashing and compact report contracts. No third-party code, dependency,
model, download, external account or network activity is introduced.

For each reachable declared branch, the candidate commits to the count and
canonical hash of nodes reachable from exactly one immediate branch target.
Nodes reachable from two or more targets are excluded, including fully shared
cyclic target cones. The summary retains the existing branch identity and does
not enumerate paths, target membership, dependency names or raw metadata.

Python 3.12.14 local validation passed 26 focused and 509 portable product
tests; 351 PostgreSQL cases remain reserved for exact CI. Infrastructure ran 16
guards: 15 passed and one documented Memory-only case skipped. Dependency,
diagnostic, import, compilation, JSON and whitespace checks passed. Exact-head
PostgreSQL 16/17 PR and merged-main CI with zero product skips remain required.
This is read-only evidence over one explicit projection; it does not establish
path or dependency completeness, importance, risk, probability or safety and
grants no repair, approval, deployment, external-action or execution authority.

## AIR-25 declared branch reach overlap source receipt (2026-10-28)

Source PR #75 exact head `5aff77872ccf8892b1e200b2ad69e2689db40daa`,
tree `5a0234f28a5d41f8fc1e9658adccecf44143ed06`, passed exact run
40687735433. Expected-head merge produced main
`5d4d479ffa0b7b2e7df2ce4040e5303c5a459ca6`, and main-push run 40688022997
passed. Python 3.12.15 on PostgreSQL 16 and 17 passed 858 product tests with
zero product skips in both gates. Each lane ran 16 infrastructure guards: 15
passed and one established Memory-only case skipped.

The evidence remains synthetic, deterministic, hash-only and read-only. It
does not establish path or dependency completeness, importance, risk,
probability or safety, and grants no repair, approval, deployment,
external-action or execution authority. Independent records CI and explicit
writer release remain required.

## AIR-25 declared branch reach overlap candidate (2026-10-28)

The candidate is rooted at exact verified main
`ffb3554b361864d250ba4853d4727f0d870f8174`, after declared-branch-target
writer release. Reuse-first review selected the existing in-repository
validated projection, cycle-safe queue traversal and canonical hash contracts;
no third-party code, dependency, model, network access or external account is
used.

Each compact summary is bound to one existing branch identity and commits to
the count and sorted hash-only identities of nodes reachable from at least two
distinct immediate branch targets. The output does not enumerate paths, expose
raw dependency metadata or infer undeclared dependencies. Python 3.12.14 local
validation passed 24 focused and 507 portable product tests, with 351
PostgreSQL cases reserved for exact CI. Infrastructure ran 16 guards: 15 passed
and one documented Memory-only case skipped. Exact PostgreSQL 16/17 PR and
merged-main CI with zero product skips remain required. This evidence grants no
repair, approval, deployment, external-action or execution authority.

## AIR-25 declared branch target candidate (2026-10-27)

Prior declared-branch PRs #70/#71 are fully verified and writer
`AIR25-DECLARED-BRANCH-SUMMARY-20261026` is released through exact main
`685f3fb5e2f47565d2d74897c6139230c0e9b8a8` and final-main run 40479256326.
Python 3.12.15 on PostgreSQL 16 and 17 passed 855 product tests with zero
product skips per lane.

This source candidate adds deterministic compact commitments from each existing
declared branch to its distinct target-node set: one count and one canonical
hash over sorted opaque target identities. The values derive only from already
traversed declared edges and expose no raw dependency metadata. Python 3.12.14
validation passes 22 focused and 505 portable product tests, with 351
PostgreSQL cases reserved for exact CI. Infrastructure passes 15 guards with
one documented Memory-only skip; dependency, import, compile, JSON and
whitespace checks pass. Exact PostgreSQL 16/17 PR and merged-main CI remain
required. The commitment is not alternative-path or dependency
completeness, discovery, importance, risk, probability or safety, and grants no
repair, approval, deployment, external-action or execution authority.

## AIR-25 declared branch source candidate (2026-10-26)

The candidate is based on exact verified main
`234800f5b4f7d20568d3917604dfabd4bf4b74d3`. It records only hash identities,
counts and content hashes for reachable nodes with multiple outgoing traversed
declared edges. Unreachable edges are excluded. Declared branching is not
alternative-path completeness and no undeclared dependency is inferred.

Local Python 3.12.14 validation passed 21 focused and 504 portable product
tests, with 351 PostgreSQL cases reserved for exact CI. Infrastructure passed
15 guards with one documented Memory-only skip; dependency, import,
diagnostics, compile, JSON and diff checks passed. Exact PostgreSQL 16/17 PR
and merged-main CI with zero product skips remain required.

## AIR-25 declared-branch source receipt (2026-10-26)

Source PR #70 exact head `d9e420c00ed1e939d4ed92f4b70968f3fd4997ef`,
tree `85d1e989927a3f54e8e4967cfe17938d593afa42`, passed exact-head run
40368414126 on Python 3.12.15. PostgreSQL 16 and 17 each passed 855 product
tests with zero product skips. Its expected-head guarded merge produced exact
main `490a2a2628b6f69c549778de52f17f816e58e75a`; push run 40368709577
passed the same matrix. Each lane executed 16 infrastructure guards: 15 passed
and one established Memory-only case skipped. Diagnostics passed.

The slice remains a bounded deterministic hash-only summary of reachable nodes
with multiple outgoing traversed declared edges. It discovers no undeclared
dependency, reads no production payload or secret, and grants no repair,
approval, deployment, external-action or execution authority. Independent
canonical records and exact PR/final-main CI remain required before writer
release. AIR-25 remains in progress at 2/12.

## AIR-25 declared branch target source receipt (2026-10-28)

Source PR #72 exact head `137cfe077d18f541dac3e98d3f71ab4368b62f93`,
tree `6ee7b6720d04035f3798f173850a95cf020f37ef`, passed Python 3.12.15
exact-head run 40512164020. PostgreSQL 16 and 17 each passed 856 product
tests with zero failures and zero product skips. Expected-head guarded merge
`2fb8abf905835cf9cba86be17b88b5a38cadc5a3` passed exact main-push run
40648809391 with the same result. Each lane executed 16 infrastructure guards:
15 passed and one established Memory-only case skipped. Diagnostics passed.

The verifier derives each branch's distinct target-node count and canonical
target-set hash solely from the report's already traversed declared edges.
Ordering, duplicate targets, unreachable edges, tampered commitments and
payload-size boundaries have deterministic synthetic regression coverage.

This remains a bounded compact hash-only review aid over one explicit
projection. It discovers no dependency, reads no production payload or secret,
and grants no importance, risk, probability, safety, repair, approval,
deployment, external-action or execution authority. Independent canonical
records and exact PostgreSQL 16/17 PR/final-main CI remain required before
writer release. AIR-25 remains in progress at 2/12.

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

## AIR-25 deterministic impact-layer source receipt (2026-10-25)

Completeness-warning source/records PRs #60/#61 are fully verified through
exact main `a281b1fc9ea65ed18964122b572257405058d75d` and final-main run
40130405432; PostgreSQL 16 and 17 each passed 845 product tests with zero
product skips. The prior writer is explicitly released in PR #61.

The new candidate groups reachable hash-only node identities by minimum
declared hops from the selected seeds, with deterministic content-derived layer
identities and exact reconciliation to the reachable report body. Layer number
is not importance, risk, probability, completeness or safety. The slice infers
no undeclared dependency and adds no production observation, raw metadata,
repair, approval, deployment, external action or execution authority. Local
Python 3.12.14 validation passed 34 focused tests and 496 portable product tests
with 351 PostgreSQL cases deselected; infrastructure passed 15 guards with one
documented Memory-only skip. Source PR #62 exact head
`14b76274f4a6a63942e2fa5188a93eb59b445e08`, tree
`d3042f92a9e8a7d32d9f714bb87845a5a24652b1`, passed exact run
40133889617 on Python 3.12.15. PostgreSQL 16 and 17 each passed 847 product
tests with zero product skips. Guarded merge produced exact main
`2724254d91ea3a019eadcacd61470917bddcdfc2`; merged-main run 40168781130
passed the same matrix. Canonical records CI and explicit writer release remain
required. AIR-25 remains in progress at 2/12.

## AIR-25 deterministic seed-partition source candidate (2026-10-25)

Impact-layer records PR #63 head
`c2272142c47700eed00dd95ed1b9941d6c7505ed` passed exact run 40172502509;
guarded merge produced main `7cf039a5ffe6660212244037eccc92b8bfb3c183`,
and run 40172624044 passed. Python 3.12.15 on PostgreSQL 16 and 17 passed
847 product tests with zero product skips per matrix. The prior writer is
explicitly released in PR #63.

The new candidate groups reachable recorded nodes by the seed stored in each
node's deterministic shortest-path witness. Each seed summary carries only its
hash identity, member count and a content hash over sorted member node IDs, so
the maximum-size report remains bounded. These partitions describe one selected
witness forest only; they do not enumerate alternative paths, discover
undeclared dependencies or claim completeness, importance, risk, probability
or safety. No production observation, repair, approval, deployment, external
action or execution authority is added. Local Python 3.12.14 validation passed
15 focused and 498 portable tests; 351 PostgreSQL cases remain delegated to
exact PR CI. Infrastructure passed 15 guards with one documented Memory-only
skip.

Source PR #64 exact head `571478f1ad3287060dba2cf39582a24ee25f5f20`,
tree `b5508d3f2f039676a46cdd4b277fefcfc7c566be`, passed exact run
40192674817. Python 3.12.15 on PostgreSQL 16 and 17 passed 849 product tests
with zero product skips per matrix. Guarded merge produced exact main
`32f26d7cb4aa322832b5ab85b068ba8402e6a315`; merged-main run 40192856747
passed the same matrix. Canonical records CI and explicit writer release remain
required. AIR-25 remains in progress at 2/12.

## AIR-25 declared convergence source receipt (2026-10-25)

Seed-partition records PR #65 head
`1d213832d34b72fb7310b8cd18e6a486245c67ed` and exact main
`99af6847a3e4d08dbde0811c684aaf78ff7fe689` passed final run 40193307096.
Python 3.12.15 on PostgreSQL 16 and 17 passed 849 product tests with zero
product skips, and the prior writer is explicitly released.

The new bounded candidate summarizes reachable nodes with multiple incoming
traversed declared edges. It records only hash identities and counts, excludes
incoming edges whose sources were not reachable from the selected seeds, and
states a fixed warning that declared convergence is not path completeness.
Local Python 3.12.14 validation passed 17 focused tests, 500 portable product
tests with 351 PostgreSQL cases deselected, and 15 infrastructure guards with
one documented Memory-only skip. Dependency, compilation, JSON and whitespace
checks passed. Source PR #66 exact head
`eca262eafbfd6ec32bd41fec7a728b0658bdc294`, tree
`628720232a652cfdd6b80469414dc01f7da3ff7f`, passed exact-head run
40244575096 on Python 3.12.15. PostgreSQL 16 and 17 each passed 851 product
tests with zero product skips. Guarded merge produced exact main
`a972727054957248f6758c91fa7326fb98daf97a`; merged-main run 40244766661
passed the same matrix. Canonical records CI and explicit writer release remain
required. The slice adds no discovery, production observation, raw metadata,
importance, risk, probability, completeness, safety, repair, approval,
deployment, external action or execution authority. AIR-25 remains in progress
at 2/12.

## AIR-25 declared frontier source candidate (2026-10-26)

Declared-convergence records PR #67 head
`01441699de053776ab8b96a275d5bcd90d75b0f6` passed exact run 40244992819;
guarded merge produced exact main
`4d73997fe895b21b17c31fcc356f5978e56049fb`, and final-main run 40245135755
passed. Python 3.12.15 on PostgreSQL 16 and 17 passed 851 product tests with
zero product skips per matrix, and the prior writer is explicitly released.

The new bounded candidate summarizes reachable nodes without outgoing
traversed declared edges. It retains only the terminal count, a content hash
over sorted hash-only node identities and a content-derived frontier identity.
Cycles are not treated as terminals, and a fixed warning states that this
declared frontier is not downstream completeness. Python 3.12.14 validation
passed 19 focused and 502 portable product tests, with 351 PostgreSQL cases
deselected for exact CI. Infrastructure passed 15 guards with one documented
Memory-only skip; diagnostics, dependencies, compilation, JSON and whitespace
checks passed. Exact PR-head and merged-main PostgreSQL 16/17 CI remain
required. The slice adds no
dependency discovery, production observation, raw metadata, importance, risk,
probability, completeness, safety, repair, approval, deployment, external
action or execution authority. AIR-25 remains in progress at 2/12.

## AIR-25 declared-frontier source receipt (2026-10-26)

Source PR #68 exact head `e3e775355a2b63ba2270d87cae944165b14091f7`,
tree `660fbc13ff3a42ea51de2f2f5e33740fdcf38539`, passed exact-head run
40279147493 on Python 3.12.15. PostgreSQL 16 and 17 each passed 853 product
tests with zero product skips. Its expected-head guarded merge produced exact
main `f62e630d8f95f729e975ef5669aaf4621e30a563`; push run 40279349524
passed the same matrix. Each lane executed 16 infrastructure guards: 15 passed
and one established Memory-only case skipped. Diagnostics passed.

The slice remains a bounded deterministic hash-only summary of reachable nodes
without outgoing traversed declared edges. It discovers no undeclared
dependency, reads no production payload or secret, and grants no repair,
approval, deployment, external-action or execution authority. Independent
canonical records and exact PR/final-main CI remain required before writer
release. AIR-25 remains in progress at 2/12.
