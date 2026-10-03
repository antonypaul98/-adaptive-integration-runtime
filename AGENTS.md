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
3. Resume `work/sandbox-evaluation-foundation` for the recorded checkpoint. Do not create another
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
