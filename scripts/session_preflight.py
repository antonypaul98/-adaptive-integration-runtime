#!/usr/bin/env python3
"""Inspect readiness; never switch branches, reset files or create commits."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REMOTE_SHA = None


class PreflightFailure(SystemExit):
    def __init__(self, receipt):
        super().__init__(1)
        self.receipt = receipt


def fail(layer, blocker, action):
    receipt = dict(BLOCKED_LAYER=layer, BLOCKER=blocker,
                   SAFE_WORK_COMPLETED='No implementation changed by preflight; existing files preserved. Remote backup not inferred.',
                   REMOTE_SHA=REMOTE_SHA, NEXT_ACTION=action)
    # Local receipt is evidence, NOT a durable remote backup. The session must
    # transfer it to CHECKPOINT_STATE and synchronize using the documented path.
    try:
        p = subprocess.run(['git', 'rev-parse', '--git-path', 'session-preflight.json'],
                           cwd=ROOT, text=True, capture_output=True, timeout=5)
        if p.returncode == 0:
            path = Path(p.stdout.strip())
            if not path.is_absolute():
                path = ROOT / path
            path.write_text(json.dumps(receipt, indent=2) + '\n')
    except (OSError, subprocess.TimeoutExpired):
        pass
    print(json.dumps(receipt, indent=2))
    raise PreflightFailure(receipt)


def run(args):
    try:
        p = subprocess.run(args, cwd=ROOT, text=True, capture_output=True,
                           timeout=45, env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
    except (OSError, subprocess.TimeoutExpired):
        fail('environment', f'{args[0]} unavailable or timed out',
             'Restore this tool/network, then run python scripts/session_preflight.py')
    if p.returncode:
        # Never echo helper output, credentials, URLs containing tokens or DSNs.
        hint = p.stderr.lower()
        if any(x in hint for x in ('proxy', 'resolve host', 'connect to', 'timed out')):
            layer, reason = 'environment', 'network/proxy/DNS unavailable'
        elif any(x in hint for x in ('authentication', 'username', 'permission denied', '403', '401', 'login')):
            layer, reason = 'auth', 'authentication/authorization unavailable'
        else:
            layer, reason = 'Git' if args[0] == 'git' else 'environment', 'command failed; inspect privately'
        fail(layer, f'{args[0]} {args[1]}: {reason}',
             'Use AGENTS.md connected-GitHub preservation procedure; rerun preflight after restoring shell access')
    return p.stdout.strip()


def main():
    global REMOTE_SHA
    state = json.loads((ROOT / 'CHECKPOINT_STATE.json').read_text())
    repo, active = state['repository'], state['active_branch']
    allowed = {f'https://github.com/{repo}.git', f'https://github.com/{repo}',
               f'git@github.com:{repo}.git', f'ssh://git@github.com/{repo}.git'}
    for direction in ([], ['--push']):
        urls = run(['git', 'remote', 'get-url', *direction, '--all', 'origin']).splitlines()
        if not urls or any(u not in allowed for u in urls):
            fail('Git', 'origin fetch/push URL is not canonical',
                 f'Inspect git remote -v and restore origin for {repo}; do not create another repository')
    run(['git', 'fetch', '--all', '--prune'])
    remote = 'refs/remotes/origin/' + active
    refs = run(['git', 'for-each-ref', '--format=%(refname)', remote]).splitlines()
    if remote not in refs:
        fail('Git', f'ACTIVE CHECKPOINT BRANCH {active} is absent remotely',
             'Inspect GitHub PRs and CHECKPOINT_STATE; reconcile the canonical branch without recreating it')
    REMOTE_SHA = run(['git', 'rev-parse', remote])
    branch = run(['git', 'branch', '--show-current'])
    dirty = bool(run(['git', 'status', '--porcelain', '--untracked-files=all']))
    if branch != active:
        if dirty:
            action = 'Preserve tracked/untracked work using AGENTS.md before switching; DO NOT force checkout'
        else:
            local_ref = 'refs/heads/' + active
            exists = local_ref in run(['git', 'for-each-ref', '--format=%(refname)', local_ref]).splitlines()
            action = ('git switch ' + shlex.quote(active) if exists else
                      'git switch --track ' + shlex.quote('origin/' + active))
            action += ' && python scripts/session_preflight.py; if occupied, use git worktree list and resume that worktree'
        fail('Git', f'ACTIVE CHECKPOINT BRANCH IS {active}. CHECK IT OUT AND RERUN PREFLIGHT. DO NOT CREATE A REPLACEMENT BRANCH.', action)
    head = run(['git', 'rev-parse', 'HEAD'])
    main_sha = run(['git', 'rev-parse', 'origin/main'])
    base = run(['git', 'merge-base', 'origin/main', 'HEAD'])
    behind, ahead = map(int, run(['git', 'rev-list', '--left-right', '--count', 'origin/main...HEAD']).split())
    local_only, remote_only = map(int, run(['git', 'rev-list', '--left-right', '--count', 'HEAD...' + remote]).split())
    print(json.dumps(dict(repository=repo, current_repository_sha=head,
                          observed_feature_sha=state.get('observed_feature_sha'),
                          remote_sha=REMOTE_SHA, main_sha=main_sha, merge_base=base,
                          behind_main=behind, ahead_of_main=ahead,
                          local_only=local_only, remote_only=remote_only, dirty=dirty), indent=2))
    if dirty or local_only or remote_only or behind:
        fail('Git', f'Reconciliation needed: dirty={dirty}, local-only={local_only}, remote-only={remote_only}, behind-main={behind}',
             'Inspect git status and git log --left-right HEAD...origin/' + active + '; preserve first, then reconcile without force/reset')
    # Both channels are checked independently. Failure in API tooling must not
    # conceal the separate transport/authentication result of git push.
    errors = []
    if not shutil.which('gh'):
        errors.append(('environment', 'GitHub API: gh unavailable; connector authorization must be checked separately'))
    else:
        try:
            if run(['gh', 'api', f'repos/{repo}', '--jq', '.permissions.push']) != 'true':
                errors.append(('auth', 'GitHub API: repository write permission absent'))
        except PreflightFailure as exc:
            errors.append((exc.receipt['BLOCKED_LAYER'], exc.receipt['BLOCKER']))
    try:
        run(['git', 'push', '--dry-run', 'origin', f'HEAD:refs/heads/{active}'])
    except PreflightFailure as exc:
        errors.append((exc.receipt['BLOCKED_LAYER'], exc.receipt['BLOCKER']))
    if errors:
        fail(errors[0][0] if len({e[0] for e in errors}) == 1 else 'external', '; '.join(e[1] for e in errors),
             'Use the connected-GitHub fallback in AGENTS.md to preserve current work; restore shell credentials before substantial implementation')
    expected = (ROOT / '.python-version').read_text().strip()
    actual = f'{sys.version_info.major}.{sys.version_info.minor}'
    if actual != expected:
        fail('environment', f'Python {actual} differs from pinned {expected}',
             f'python{expected} -m venv .venv; activate it and rerun preflight')
    receipt_path = Path(run(['git', 'rev-parse', '--git-path', 'session-preflight.json']))
    if not receipt_path.is_absolute():
        receipt_path = ROOT / receipt_path
    receipt_path.unlink(missing_ok=True)
    print('PASS: startup only. No product acceptance. Dry-run is preliminary; verify first real coherent commit remotely. Refresh PR/CI and record state before coding.')


if __name__ == '__main__':
    main()
