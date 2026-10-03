"""Bounded stdlib tests; no product suite, services, network or camera access."""
import contextlib
import io
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]

def module(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + '.py'))
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


class PreflightTests(unittest.TestCase):
    def exercise(self, overrides=None, gh=True):
        m = module('session_preflight')
        self.calls = []
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'CHECKPOINT_STATE.json').write_text(json.dumps({'repository': 'owner/repo', 'active_branch': 'work/current'}))
            (root / '.python-version').write_text(f'{sys.version_info.major}.{sys.version_info.minor}')
            def run(args):
                self.calls.append(args)
                key = ' '.join(args)
                for needle, value in (overrides or {}).items():
                    if needle in key:
                        return value
                if 'get-url' in args:
                    return 'https://github.com/owner/repo.git'
                if args[:2] == ['git', 'for-each-ref']:
                    return args[-1]
                if args[:3] == ['git', 'branch', '--show-current']:
                    return 'work/current'
                if args[:2] == ['git', 'rev-list']:
                    return '0 0'
                if args[:2] == ['git', 'status']:
                    return ''
                if args[:2] == ['gh', 'api']:
                    return 'true'
                if '--git-path' in args:
                    return str(root / 'receipt.json')
                return 'a' * 40
            with patch.object(m, 'ROOT', root), patch.object(m, 'run', run), patch.object(m.shutil, 'which', return_value='/bin/gh' if gh else None), contextlib.redirect_stdout(io.StringIO()):
                try:
                    m.main()
                except m.PreflightFailure as exc:
                    return exc.receipt
        return None

    def test_clean_checks_both_channels(self):
        self.assertIsNone(self.exercise())
        self.assertTrue(any(a[:2] == ['gh', 'api'] for a in self.calls))
        self.assertTrue(any(a[:3] == ['git', 'push', '--dry-run'] for a in self.calls))

    def test_main_gives_existing_branch_command(self):
        r = self.exercise({'branch --show-current': 'main'})
        self.assertIn('git switch work/current', r['NEXT_ACTION'])
        self.assertIn('DO NOT CREATE', r['BLOCKER'])

    def test_remote_only_branch_gives_track_command(self):
        r = self.exercise({'branch --show-current': 'main', 'for-each-ref --format=%(refname) refs/heads/': ''})
        self.assertIn('git switch --track origin/work/current', r['NEXT_ACTION'])

    def test_dirty_main_never_suggests_switch(self):
        r = self.exercise({'branch --show-current': 'main', 'status --porcelain': ' M source.py'})
        self.assertIn('Preserve', r['NEXT_ACTION'])
        self.assertNotIn('git switch', r['NEXT_ACTION'])

    def test_missing_remote_is_explicit(self):
        r = self.exercise({'for-each-ref --format=%(refname) refs/remotes': ''})
        self.assertIn('absent remotely', r['BLOCKER'])

    def test_missing_gh_still_checks_git_push(self):
        self.assertIsNotNone(self.exercise(gh=False))
        self.assertTrue(any(a[:3] == ['git', 'push', '--dry-run'] for a in self.calls))

    def test_no_api_write_fails(self):
        self.assertEqual(self.exercise({'gh api': 'false'})['BLOCKED_LAYER'], 'auth')

    def test_local_only_work_fails(self):
        self.assertIn('local-only=1', self.exercise({'HEAD...refs/remotes': '1 0'})['BLOCKER'])

    def test_behind_main_fails(self):
        self.assertIn('behind-main=2', self.exercise({'origin/main...HEAD': '2 0'})['BLOCKER'])

    def test_wrong_origin_fails(self):
        self.assertIn('not canonical', self.exercise({'get-url': 'https://github.com/other/repo.git'})['BLOCKER'])

    def test_network_error_is_redacted(self):
        m = module('session_preflight')
        result = subprocess.CompletedProcess([], 128, '', 'proxy unavailable secret-token-value')
        with patch.object(m.subprocess, 'run', return_value=result), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(m.PreflightFailure) as ctx:
                m.run(['git', 'fetch'])
        self.assertEqual(ctx.exception.receipt['BLOCKED_LAYER'], 'environment')
        self.assertNotIn('secret-token-value', json.dumps(ctx.exception.receipt))


class CommitMessageTests(unittest.TestCase):
    def test_normal_feature_allowed(self):
        module('check_commit_message').validate('feat: meaningful work', ['src/product.py'])

    def test_all_skip_forms_rejected(self):
        guard = module('check_commit_message')
        for marker in ['[skip ci]', '[ci skip]', '[no ci]', '[skip actions]', '[actions skip]', 'skip-checks: true']:
            with self.subTest(marker=marker), self.assertRaises(ValueError):
                guard.validate('feat: work ' + marker, ['src/product.py'])

    def test_explicit_infrastructure_exception(self):
        module('check_commit_message').validate('chore: infra [skip ci]\n\nInfrastructure-Only: true', ['scripts/session_preflight.py'])

    def test_marker_cannot_hide_product_path(self):
        with self.assertRaises(ValueError):
            module('check_commit_message').validate('chore: infra [skip ci]\n\nInfrastructure-Only: true', ['src/product.py'])


class DiagnosticsTests(unittest.TestCase):
    @unittest.skipUnless((SCRIPTS.parent / 'app').is_dir(), 'source-layout Memory diagnostic regression only')
    def test_direct_script_can_import_checkout_outside_cwd(self):
        # Use the actual diagnostic source in a source-only miniature checkout.
        # Only pip check is mocked; Python import resolution is real and isolated.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'scripts').mkdir()
            (root / 'app').mkdir()
            (root / 'app/__init__.py').write_text('')
            shutil.copyfile(SCRIPTS / 'ci_diagnostics.py', root / 'scripts/ci_diagnostics.py')
            (root / '.python-version').write_text(f'{sys.version_info.major}.{sys.version_info.minor}')
            (root / 'CHECKPOINT_STATE.json').write_text(json.dumps({'repository': 'owner/fixture', 'diagnostic_import': 'app', 'diagnostic_postgres_variables': []}))
            code = "import runpy,sys;from unittest.mock import patch;\nwith patch('subprocess.run'):\n runpy.run_path(sys.argv[1],run_name='__main__')"
            r = subprocess.run([sys.executable, '-I', '-c', code, str(root / 'scripts/ci_diagnostics.py')], cwd='/', capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('Import OK: app', r.stdout)


if __name__ == '__main__':
    unittest.main()
