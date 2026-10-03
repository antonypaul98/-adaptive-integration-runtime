#!/usr/bin/env python3
"""Read-only readiness checks (except fetching remote-tracking refs). No commits."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(args):
    try:
        p = subprocess.run(args, cwd=ROOT, text=True, capture_output=True,
                           timeout=60, env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
    except (OSError, subprocess.TimeoutExpired):
        raise SystemExit(f"FAIL: {args[0]} unavailable or timed out; preserve work before retrying.")
    if p.returncode:
        # Do not echo credential-bearing remote URLs or helper output.
        hint = p.stderr.lower()
        reason = ('network/proxy/DNS unavailable' if any(x in hint for x in
                  ('proxy', 'resolve host', 'connect to', 'timed out')) else
                  'authentication/authorization unavailable' if any(x in hint for x in
                  ('authentication', 'username', 'permission denied', '403', '401')) else
                  'command failed; inspect locally without sharing credentials')
        raise SystemExit(f"FAIL: {args[0]} {args[1]}: {reason}. No readiness approval.")
    return p.stdout.strip()


def main():
    state = json.loads((ROOT / 'CHECKPOINT_STATE.json').read_text())
    repo = state['repository']
    allowed = {f'https://github.com/{repo}.git', f'https://github.com/{repo}',
               f'git@github.com:{repo}.git', f'ssh://git@github.com/{repo}.git'}
    for direction in ([], ['--push']):
        urls = run(['git', 'remote', 'get-url', *direction, '--all', 'origin']).splitlines()
        if not urls or any(u not in allowed for u in urls):
            raise SystemExit('FAIL: origin fetch/push URL is not the canonical repository.')
    run(['git', 'fetch', '--all', '--prune'])
    head = run(['git', 'rev-parse', 'HEAD'])
    branch = run(['git', 'branch', '--show-current'])
    main_sha = run(['git', 'rev-parse', 'origin/main'])
    base = run(['git', 'merge-base', 'origin/main', 'HEAD'])
    behind, ahead = map(int, run(['git', 'rev-list', '--left-right', '--count',
                                 'origin/main...HEAD']).split())
    dirty = bool(run(['git', 'status', '--porcelain', '--untracked-files=all']))
    print(json.dumps(dict(repository=repo, branch=branch, head=head, main=main_sha,
                          merge_base=base, ahead_of_main=ahead, behind_main=behind,
                          uncommitted_or_untracked=dirty), indent=2))
    if branch != state['active_branch']:
        raise SystemExit('FAIL: resume the recorded active branch; do not create a duplicate.')
    remote = 'refs/remotes/origin/' + branch
    run(['git', 'rev-parse', '--verify', remote])
    local_only, remote_only = map(int, run(['git', 'rev-list', '--left-right', '--count',
                                          'HEAD...' + remote]).split())
    print(f'Branch synchronization: local-only={local_only}; remote-only={remote_only}')
    if not shutil.which('gh'):
        raise SystemExit('FAIL: gh unavailable. Use the connected GitHub recovery procedure in AGENTS.md; Git read access alone does not prove write access.')
    permission = run(['gh', 'api', f'repos/{repo}', '--jq', '.permissions.push'])
    if permission != 'true':
        raise SystemExit('FAIL: GitHub API does not report repository write permission.')
    run(['git', 'push', '--dry-run', 'origin', f'HEAD:refs/heads/{branch}'])
    expected = (ROOT / '.python-version').read_text().strip()
    actual = f'{sys.version_info.major}.{sys.version_info.minor}'
    if actual != expected:
        raise SystemExit(f'FAIL: use Python {expected}; current interpreter is {actual}.')
    if dirty or local_only or remote_only or behind:
        raise SystemExit('FAIL: preserve/reconcile the reported work before new implementation. No reset, forced push, automatic rebase or deletion.')
    print('PASS: startup checks only, not product acceptance. Permission/dry-run is preliminary; verify the first real coherent commit remotely. Read current checkpoint and blockers before coding.')


if __name__ == '__main__':
    main()
