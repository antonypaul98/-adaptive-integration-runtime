# Unapplied recovery evidence

Source worktree: `/workspace/scratch/31409c41d9c1/air`
Base/observed HEAD: `1a724a8f453a83090f7f0235198d0c5b29daa760`

Preserved only; not applied, accepted, tested or merged as feature work.
Existing source worktree remains unchanged. Patches may conflict with newer remote
work. Compare with the active branch before applying in a separate recovery worktree.
Do not run `git apply` blindly, overwrite current files or treat any acceptance
claims inside an archived patch as current validation.
Tracked changes are relative to the base HEAD; other patches preserve untracked files.
AgentFlight's local-only-commit.patch (if present) preserves the existing commit
contents and author metadata, without activating that feature implementation.
