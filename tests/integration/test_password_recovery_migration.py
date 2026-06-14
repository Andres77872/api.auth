"""Schema/code regression tests for legacy reset-table cleanup.

The one-off password-recovery migration script has been retired now that the
canonical schema files in ``schemas/`` are the single source of truth (applied
via ``scripts/recreate_database.py`` / ``scripts/create_database.py``). These
tests guard the lasting invariants: the fresh schema never recreates the legacy
plaintext reset table, and no live code writes to it.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LEGACY_TABLE = "user_password_resets"


def test_fresh_schema_no_longer_creates_legacy_plaintext_reset_table_indexes_or_triggers():
    table_sql = (ROOT / "schemas/tables/02_create_tables.sql").read_text()
    index_sql = (ROOT / "schemas/tables/03_create_indexes.sql").read_text()
    constraint_sql = (ROOT / "schemas/tables/04_add_constraints.sql").read_text()
    trigger_sql = (ROOT / "schemas/triggers/01_activity_logging_triggers.sql").read_text()

    assert f"CREATE TABLE IF NOT EXISTS {LEGACY_TABLE}" not in table_sql
    assert "reset_token VARCHAR" not in table_sql
    assert f"idx_{LEGACY_TABLE}" not in index_sql
    assert f"fk_{LEGACY_TABLE}" not in constraint_sql
    assert "tr_validate_password_reset_expiry" not in constraint_sql
    assert LEGACY_TABLE not in trigger_sql


def test_live_application_code_does_not_insert_or_consume_legacy_plaintext_reset_storage():
    live_sources = [
        *ROOT.glob("src/**/*.py"),
        *ROOT.glob("scripts/**/*.py"),
        *ROOT.glob("schemas/stored_procedures/**/*.sql"),
    ]
    offenders = []
    for path in live_sources:
        content = path.read_text(errors="ignore").lower()
        if f"insert into {LEGACY_TABLE}" in content or f"update {LEGACY_TABLE}" in content:
            offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []
