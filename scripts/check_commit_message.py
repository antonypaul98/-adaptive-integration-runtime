#!/usr/bin/env python3
"""Reject accidental CI skips. Usable by local hook or before GitHub API writes."""
import argparse
from pathlib import Path
import re
import subprocess

MARKERS = re.compile(r'\[(?:skip ci|ci skip|no ci|skip actions|actions skip)\]|skip-checks\s*:\s*true', re.I)


def infrastructure_path(path):
    return path in {'AGENTS.md', 'CHECKPOINT_STATE.json', '.python-version', 'CONTRIBUTING.md'} or path.startswith((
        '.github/workflows/', '.githooks/', 'docs/WORKFLOW_', 'docs/BRANCH_AUDIT',
        'scripts/session_preflight.py', 'scripts/ci_diagnostics.py',
        'scripts/check_commit_message.py', 'scripts/tests/'))


def validate(message, paths):
    if not MARKERS.search(message):
        return
    if 'Infrastructure-Only: true' not in message.splitlines():
        raise ValueError('CI skip rejected: normal feature commits must run CI. Do not copy stabilization messages.')
    if not paths or not all(infrastructure_path(p) for p in paths):
        raise ValueError('CI skip rejected: explicit infrastructure exception requires a nonempty infrastructure-only file list.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('message_file')
    parser.add_argument('--paths', nargs='+', help='Exact changed paths for an API commit; otherwise use Git staged paths')
    args = parser.parse_args()
    paths = args.paths
    if paths is None:
        paths = subprocess.check_output(['git', 'diff', '--cached', '--name-only', '-z'], text=True).split('\0')
        paths = [p for p in paths if p]
    try:
        validate(Path(args.message_file).read_text(), paths)
    except ValueError as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
