"""sp_delete_user must report the users row, not the memberships update.

``delete_user`` treats ``rows_affected == 0`` as "not deleted". The procedure used to
return ``ROW_COUNT()`` of its second UPDATE (group memberships), so soft-deleting a
user without active memberships deactivated the account but answered 500, and bulk
delete reported it as "Delete failed".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.static

ROOT = Path(__file__).resolve().parents[2]
USER_PROCEDURES = ROOT / "schemas" / "stored_procedures" / "01_user_management.sql"


def _procedure_body(name: str) -> str:
    sql = USER_PROCEDURES.read_text(encoding="utf-8")
    match = re.search(rf"CREATE PROCEDURE {name}\(.*?\)\s*BEGIN(.*?)END\$\$", sql, re.S | re.I)
    assert match, f"{name} not found in {USER_PROCEDURES.name}"
    # Drop comments so they cannot satisfy or break the checks below.
    return re.sub(r"--[^\n]*", "", match.group(1))


def test_sp_delete_user_reports_the_users_update_row_count():
    statements = [s.strip() for s in _procedure_body("sp_delete_user").split(";") if s.strip()]

    users_update = next(i for i, s in enumerate(statements) if re.match(r"UPDATE\s+users\b", s, re.I))
    captured = statements[users_update + 1]
    assignment = re.fullmatch(r"SET\s+(\w+)\s*=\s*ROW_COUNT\(\)", captured, re.I)
    assert assignment, f"ROW_COUNT() must be captured right after the users UPDATE, found: {captured!r}"

    final = statements[-1]
    assert re.fullmatch(rf"SELECT\s+{assignment.group(1)}\s+as\s+rows_affected", final, re.I), final
    assert "ROW_COUNT()" not in final.upper()


def test_schema_sync_reapplies_the_user_procedures():
    """Existing databases get the fixed procedure through scripts/schema_sync.py."""
    source = (ROOT / "scripts" / "schema_sync.py").read_text(encoding="utf-8")
    patch_files = re.search(r"PATCH_FILES = \((.*?)\n\)", source, re.S).group(1)

    assert '"stored_procedures/01_user_management.sql"' in patch_files
