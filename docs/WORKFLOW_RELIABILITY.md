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
