#!/usr/bin/env python3
"""Small environment checks; no application startup or migrations are executed."""
import importlib
import importlib.resources
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
state = json.loads((root / 'CHECKPOINT_STATE.json').read_text())
expected = (root / '.python-version').read_text().strip()
actual = f'{sys.version_info.major}.{sys.version_info.minor}'
print(f'Python {sys.version.split()[0]}; executable={sys.executable}; cwd={Path.cwd()}', flush=True)
if actual != expected:
    raise SystemExit(f'Use Python {expected}; this checkout uses {actual}')
subprocess.run([sys.executable, '-m', 'pip', 'check'], check=True)
module = state['diagnostic_import']
importlib.import_module(module)
print(f'Import OK: {module}', flush=True)
if state['repository'].endswith('/-adaptive-integration-runtime'):
    migration_files = [p for p in importlib.resources.files('air').joinpath('migrations').iterdir()
                       if p.name.endswith('.sql')]
    if not migration_files:
        raise SystemExit('No packaged SQL migrations found; check package-data installation')
    print(f'Migration resources available: {len(migration_files)}')
for variable in state['diagnostic_postgres_variables']:
    dsn = os.environ.get(variable)
    if not dsn:
        if os.environ.get('CI'):
            raise SystemExit(f'{variable} missing: CI must provision a disposable PostgreSQL service')
        print(f'{variable} unset: integration tests pending CI')
        continue
    import psycopg
    try:
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            conn.execute('SELECT 1').fetchone()
    except Exception as exc:
        raise SystemExit(f'{variable}: PostgreSQL connectivity failed ({type(exc).__name__}); inspect service readiness and credentials privately') from None
    print(f'{variable}: PostgreSQL connectivity OK')
if state['repository'].endswith('/ai-memory-search-agent'):
    url = os.environ.get('MEMORY_AGENT_TEST_REDIS_URL')
    if url:
        import redis
        try:
            redis.Redis.from_url(url, socket_connect_timeout=5, socket_timeout=5).ping()
        except Exception as exc:
            raise SystemExit(f'Redis connectivity failed ({type(exc).__name__})') from None
        print('Redis connectivity OK')
    elif os.environ.get('CI'):
        raise SystemExit('MEMORY_AGENT_TEST_REDIS_URL missing')
print('Environment diagnostics passed; no product tests or hardware acceptance performed.')
