from __future__ import annotations

from pathlib import Path
from typing import Any

MIGRATION_PATH = Path(__file__).with_name("migrations") / "001_tenant_isolation.sql"

def migration_sql() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")

def apply_migrations(connection: Any) -> None:
    with connection.transaction():
        connection.execute(migration_sql())
