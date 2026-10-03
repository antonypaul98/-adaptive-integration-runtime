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

## Audit evidence and recovery

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
fixture errors belong to the sandbox checkpoint and are intentionally unresolved.
Never remove/skip failing feature tests to make this infrastructure run green.
