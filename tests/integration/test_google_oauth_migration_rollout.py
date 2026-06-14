"""Schema/fresh-bootstrap regression contracts for Google OAuth.

The one-off ``migrate_google_oauth.py`` script has been retired now that the
canonical schema files in ``schemas/`` are the single source of truth (applied
via ``scripts/recreate_database.py`` / ``scripts/create_database.py``). These
tests guard the lasting invariants: the external-accounts schema stores no raw
Google token/state material, and the fresh bootstrap accepts the ``oauth``
auth method, the OAuth activity-catalog range, and wires the OAuth schema files.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXTERNAL_ACCOUNTS_SQL = ROOT / "schemas" / "tables" / "10_external_accounts.sql"
CREATE_TABLES_SQL = ROOT / "schemas" / "tables" / "02_create_tables.sql"
ACTIVITY_SQL = ROOT / "schemas" / "tables" / "08_activity_logging_tables.sql"
SESSION_ANALYTICS_SQL = ROOT / "schemas" / "stored_procedures" / "07_sessions_analytics.sql"
CREATE_DATABASE_SCRIPT = ROOT / "scripts" / "create_database.py"
RECREATE_DATABASE_SCRIPT = ROOT / "scripts" / "recreate_database.py"

FORBIDDEN_TOKEN_COLUMNS = {
    "access_token",
    "refresh_token",
    "id_token",
    "authorization_code",
    "code",
    "state",
    "nonce",
    "code_verifier",
}


def test_external_accounts_schema_has_no_forbidden_google_token_or_state_columns():
    assert EXTERNAL_ACCOUNTS_SQL.exists(), "missing user_external_accounts table SQL"
    source = EXTERNAL_ACCOUNTS_SQL.read_text(encoding="utf-8", errors="ignore").lower()

    assert "user_external_accounts" in source
    assert "provider_sub_hash" in source
    assert "provider='google'" in source or "provider enum('google')" in source
    assert not any(f"`{column}`" in source or f" {column} " in source for column in FORBIDDEN_TOKEN_COLUMNS)


def test_schema_and_fresh_bootstrap_accept_oauth_auth_method_and_activity_range():
    sources = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore").lower()
        for path in (CREATE_TABLES_SQL, SESSION_ANALYTICS_SQL, ACTIVITY_SQL)
    )

    assert "'oauth'" in sources or '"oauth"' in sources
    for number in range(64, 75):
        assert f"act-cat-{number:03d}" in sources
    bootstrap_sources = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore").lower()
        for path in (CREATE_DATABASE_SCRIPT, RECREATE_DATABASE_SCRIPT)
    )
    assert "10_external_accounts.sql" in bootstrap_sources
    assert "15_external_accounts.sql" in bootstrap_sources
    assert "05_external_accounts_triggers.sql" in bootstrap_sources
