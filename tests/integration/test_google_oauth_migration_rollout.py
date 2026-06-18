"""Schema/fresh-bootstrap regression contracts for Google OAuth.

The one-off ``migrate_google_oauth.py`` script has been retired now that the
canonical schema files in ``schemas/`` are the single source of truth (applied
via ``scripts/recreate_database.py`` / ``scripts/create_database.py``). These
tests guard the lasting invariants: the external-accounts schema stores no raw
Google token/state material, and the fresh bootstrap accepts the ``oauth``
auth method, the OAuth activity-catalog range, and wires the OAuth schema files.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXTERNAL_ACCOUNTS_SQL = ROOT / "schemas" / "tables" / "10_external_accounts.sql"
EXTERNAL_ACCOUNTS_SP_SQL = ROOT / "schemas" / "stored_procedures" / "15_external_accounts.sql"
EXTERNAL_ACCOUNTS_TRIGGERS_SQL = ROOT / "schemas" / "triggers" / "05_external_accounts_triggers.sql"
CREATE_TABLES_SQL = ROOT / "schemas" / "tables" / "02_create_tables.sql"
ACTIVITY_SQL = ROOT / "schemas" / "tables" / "08_activity_logging_tables.sql"
SESSION_ANALYTICS_SQL = ROOT / "schemas" / "stored_procedures" / "07_sessions_analytics.sql"
PATREON_MIGRATION_SQL = ROOT / "scripts" / "migrations" / "patreon_account_link.sql"
CREATE_DATABASE_SCRIPT = ROOT / "scripts" / "create_database.py"
RECREATE_DATABASE_SCRIPT = ROOT / "scripts" / "recreate_database.py"

FORBIDDEN_TOKEN_COLUMNS = {
    "access_token",
    "refresh_token",
    "id_token",
    "authorization_code",
    "oauth_code",
    "code",
    "state",
    "nonce",
    "code_verifier",
    "provider_token",
    "creator_access_token",
    "creator_refresh_token",
    "webhook_secret",
    "client_secret",
}


def _read(path: Path) -> str:
    assert path.exists(), f"missing Google OAuth rollout artifact: {path.relative_to(ROOT)}"
    return path.read_text(encoding="utf-8", errors="ignore")


def _compact(source: str) -> str:
    return re.sub(r"\s+", "", source.lower().replace("`", ""))


def _table_block(source: str, table_name: str) -> str:
    pattern = rf"create\s+table\s+if\s+not\s+exists\s+`?{re.escape(table_name)}`?\s*\((.*?)\)\s*engine"
    match = re.search(pattern, source, flags=re.IGNORECASE | re.DOTALL)
    assert match, f"missing CREATE TABLE block for {table_name}"
    return match.group(1).lower()


def _procedure_block(source: str, procedure_name: str) -> str:
    pattern = rf"create\s+procedure\s+`?{re.escape(procedure_name)}`?\s*\(.*?\nend\$\$"
    match = re.search(pattern, source, flags=re.IGNORECASE | re.DOTALL)
    assert match, f"missing stored procedure block for {procedure_name}"
    return match.group(0).lower()


def _has_forbidden_column(source: str, column_name: str) -> bool:
    column_pattern = rf"(?:^|[,()]\s*)`?{re.escape(column_name)}`?\s+(?:var)?char|(?:^|[,()]\s*)`?{re.escape(column_name)}`?\s+(?:long)?blob|(?:^|[,()]\s*)`?{re.escape(column_name)}`?\s+text|(?:^|[,()]\s*)`?{re.escape(column_name)}`?\s+json|(?:^|[,()]\s*)`?{re.escape(column_name)}`?\s+binary"
    return re.search(column_pattern, source, flags=re.IGNORECASE | re.MULTILINE) is not None


def test_external_accounts_schema_has_no_forbidden_google_token_or_state_columns():
    source = _read(EXTERNAL_ACCOUNTS_SQL)
    table = _table_block(source, "user_external_accounts")
    compact = _compact(table)

    assert "user_external_accounts" in source
    assert "provider_sub_hash" in source
    assert "provider_sub_hashbinary(32)" in compact
    assert "provider_sub_fingerprint" in source
    assert "provider_sub_fingerprintchar(12)" in compact
    assert (
        "providerenum('google','patreon')" in compact
        or "providerenum('patreon','google')" in compact
        or "providerin('google','patreon')" in compact
        or "providerin('patreon','google')" in compact
    ), "provider widening must keep google while adding patreon"
    assert "unique key uk_external_accounts_active_sub (provider, active_provider_sub_hash)" in table
    assert "unique key uk_external_accounts_user_provider (active_user_provider)" in table
    assert not any(_has_forbidden_column(table, column) for column in FORBIDDEN_TOKEN_COLUMNS)


def test_external_account_link_unlink_and_triggers_preserve_google_invariants_after_provider_widening():
    sp_source = _read(EXTERNAL_ACCOUNTS_SP_SQL)
    trigger_source = _read(EXTERNAL_ACCOUNTS_TRIGGERS_SQL).lower()

    for procedure in (
        "sp_get_user_by_external_account",
        "sp_link_external_account",
        "sp_unlink_external_account",
        "sp_touch_external_account_last_seen",
    ):
        block = _procedure_block(sp_source, procedure)
        assert "'google'" in block, f"{procedure} must still accept Google"
        assert "'patreon'" in block, f"{procedure} must only widen provider support additively"
        if procedure != "sp_unlink_external_account":
            assert "provider_sub_hash" in block, f"{procedure} must keep HMAC subject authority"
        assert not any(_has_forbidden_column(block, column) for column in FORBIDDEN_TOKEN_COLUMNS)

    link_block = _procedure_block(sp_source, "sp_link_external_account")
    assert "provider_sub_fingerprint" in link_block
    assert "external account subject is already linked" in link_block
    assert "user already has an active external account for this provider" in link_block

    unlink_block = _procedure_block(sp_source, "sp_unlink_external_account")
    assert "status = 'unlinked'" in unlink_block
    assert "where user_id = p_user_id" in unlink_block
    assert "and provider = p_provider" in unlink_block
    assert "and status = 'linked'" in unlink_block

    auto_create = _procedure_block(sp_source, "sp_create_consumer_user_from_external_account")
    assert "p_provider <> 'google'" in auto_create
    assert "patreon" not in auto_create, "Google login auto-create must not become Patreon-capable"

    assert "new.provider not in ('google','patreon')" in trigger_source
    assert "new.provider <> old.provider" in trigger_source
    assert "new.provider_sub_hash <> old.provider_sub_hash" in trigger_source
    assert "terminal external account status is immutable" in trigger_source
    assert "terminal external account transition requires unlink time" in trigger_source


def test_patreon_migration_is_additive_and_preserves_existing_google_external_account_rows():
    source = _read(PATREON_MIGRATION_SQL).lower()
    compact = _compact(source)

    assert "alter table user_external_accounts" in source
    assert "modifyproviderenum('google','patreon')notnull" in compact
    assert "preserve google rows" in source or "preserves google rows" in source
    assert "drop table user_external_accounts" not in source
    assert "truncate table user_external_accounts" not in source
    assert not re.search(r"delete\s+from\s+user_external_accounts\b", source)


def test_schema_and_fresh_bootstrap_accept_oauth_auth_method_and_activity_range():
    sources = "\n".join(
        _read(path).lower()
        for path in (CREATE_TABLES_SQL, SESSION_ANALYTICS_SQL, ACTIVITY_SQL)
    )

    assert "'oauth'" in sources or '"oauth"' in sources
    for number in range(64, 75):
        assert f"act-cat-{number:03d}" in sources
    bootstrap_sources = "\n".join(
        _read(path).lower()
        for path in (CREATE_DATABASE_SCRIPT, RECREATE_DATABASE_SCRIPT)
    )
    assert "10_external_accounts.sql" in bootstrap_sources
    assert "15_external_accounts.sql" in bootstrap_sources
    assert "05_external_accounts_triggers.sql" in bootstrap_sources

    for script_path in (CREATE_DATABASE_SCRIPT, RECREATE_DATABASE_SCRIPT):
        source = _read(script_path)
        assert source.find("tables/10_external_accounts.sql") < source.find("tables/11_patreon_entitlements.sql")
        assert source.find("stored_procedures/15_external_accounts.sql") < source.find(
            "stored_procedures/16_patreon_entitlements.sql"
        )
        assert source.find("triggers/05_external_accounts_triggers.sql") < source.find(
            "triggers/06_patreon_entitlements_triggers.sql"
        )
