# Session startup and preservation

Canonical repository: `antonypaul98/-adaptive-integration-runtime`; canonical main: `origin/main`.
Read `CHECKPOINT_STATE.json` and `docs/WORKFLOW_RELIABILITY.md` before edits.
The JSON is the current resumability record; older project/spec histories remain
historical evidence, not instructions to repeat completed work. Refresh live refs
and evidence before trusting recorded SHAs, test counts, PRs or CI conclusions.

1. Inspect origin fetch AND push URLs, status including untracked files, branches
   and worktrees. Fetch all remotes with pruning; pruning is not branch deletion.
2. Run `python scripts/session_preflight.py` with the pinned interpreter. It
   checks canonical URLs, main/branch merge-base, ahead/behind, GitHub API write
   permission and a non-mutating Git push dry-run. Never create dummy commits.
3. Resume `work/post-verification-review` for the recorded checkpoint. Do not create another
   checkpoint branch to avoid drift or failed authentication. Inventory and
   preserve local work first; reconcile stale refs before significant edits.
   Never reset, discard, force-push or automatically rebase legitimate work.
4. Auth/network failure: report the exact failing layer early. Do not accumulate
   substantial local-only implementation. A GitHub connector session and shell
   Git credentials are separate capabilities; public clone success proves no write access.
5. Connected-integration fallback: read live repository permissions and branch
   SHA, inspect the diff for credentials, then preserve a small coherent change
   using blobs/tree based on the existing tree and a commit parented to the
   observed head. Re-read the ref; stop on concurrent movement. Update the same
   ref with force=false and verify remote SHA AND changed-file list. Do not
   copy tokens into shell URLs. If write fails, preserve a bundle plus tracked
   binary diff and untracked files in durable storage with a manifest.
   Never rebuild missing work merely because Git push failed.
6. Make small coherent commits and synchronize early. Update checkpoint state
   after meaningful progress and before limits: command, tested SHA, result,
   PR, CI URL/head/event, merge status, external acceptance and next action.
   `unknown`, `not run`, `pending` and `failed` must remain distinct. A state
   file records observed code SHAs; Git history supplies its containing commit.
7. Missing CI is not automatically a failure. Check event/branch/path filters,
   skip directives, Actions permissions and exact head before retries. Inspect
   failed steps and summaries; retry only a transient infrastructure failure.
8. Infrastructure-only sessions must not implement features, fix checkpoint
   tests, advance ledgers, merge feature branches or claim hardware acceptance.
   Stop after bounded infrastructure verification; no optional full-suite loops.

The 2026-10-03 stabilization preserves unapplied historical recovery patches in
`docs/recovery/`. Do not apply them blindly or treat archived acceptance claims
as verified. Future feature work needs its own scope and validation.

## Resume and exit guardrails (2026-10-03 follow-up)

- On main, preflight prints the exact existing branch and safe switch command.
  It checks remote branch existence first and never switches over dirty files.
  If a branch is checked out elsewhere, resume the reported worktree.
- API authorization and actual Git push dry-run are independent; test both,
  including when gh is absent. Do not call a successful public fetch a write test.
  Connector recovery is preservation, not proof of shell authentication.
- Before low capacity: STOP new implementation, preserve coherent work, commit,
  synchronize, update CHECKPOINT_STATE with the remote SHA/tested SHA/PR/event,
  synchronize that state commit, record one executable next action, then exit.
  Do not start a slice unless there is time to preserve it.
- On failure preflight emits BLOCKED_LAYER, BLOCKER, SAFE_WORK_COMPLETED,
  REMOTE_SHA and NEXT_ACTION and writes a local Git-metadata receipt. Transfer
  the receipt into CHECKPOINT_STATE.last_session_exit and preserve it remotely
  through the connector if needed. A .git receipt alone is NOT durable storage.
- Normal commit messages must not contain CI skip directives. Use
  `python scripts/check_commit_message.py MESSAGE_FILE --paths <changed-files>`
  before API writes. For local commits, inspect `git config --get core.hooksPath`;
  if unset, enable `git config --local core.hooksPath .githooks`. If another hook
  system exists, integrate this validator into it; never overwrite it blindly.
  Hooks are opt-in, can be bypassed, and do not govern connector writes.
- Explicit infrastructure-only skip exceptions need the message trailer
  `Infrastructure-Only: true` AND only allowed infrastructure paths. No feature
  skip exception. Do not amend old skip commits or reuse their messages.
- When feature work is separately authorized and ready for handoff, find/reuse
  the canonical PR before creating one; record its number and exact-head CI.
  No PR for the active branch means PR-event CI is absent, not failed. This
  stabilization does not create feature PRs or authorize checkpoint completion.
- A skipped infrastructure update to an existing PR makes the NEW head
  unvalidated. Retain old success only at its exact SHA; require a later normal
  CI event before any separately authorized merge. Never relabel it green.
