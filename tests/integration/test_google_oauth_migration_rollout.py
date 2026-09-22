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
SCHEMA_SYNC_SCRIPT = ROOT / "scripts" / "schema_sync.py"
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
    # The provider ENUM is only ever widened by APPENDING: 'google','patreon' keep their
    # positions so stored ordinal values never change meaning.
    assert "providerenum('google','patreon'," in compact or "providerenum('google','patreon')" in compact, (
        "provider widening must append after google and patreon"
    )
    # Identity is keyed on (namespace, subject HMAC); the namespace is a column, never
    # part of the HMAC input, so pre-existing hashes keep resolving.
    assert "identity_namespacevarchar(191)notnull" in compact
    assert "unique key uk_external_accounts_active_namespace_sub (identity_namespace, active_provider_sub_hash)" in table
    assert "unique key uk_external_accounts_user_namespace (active_user_namespace)" in table
    assert "uk_external_accounts_active_sub (provider" not in table, "the provider-keyed unique key was replaced"
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

    # Which provider types exist is data (oauth_provider_catalog), not a literal list.
    assert "new.provider not in (" not in trigger_source
    assert "from oauth_provider_catalog where provider_type = new.provider" in trigger_source
    assert "set new.identity_namespace = new.provider" in trigger_source, (
        "rows from provider-keyed procedures must default their namespace to the provider"
    )
    assert "new.identity_namespace <> old.identity_namespace" in trigger_source, "identity namespace is immutable"
    assert "new.provider <> old.provider" in trigger_source
    assert "new.provider_sub_hash <> old.provider_sub_hash" in trigger_source
    assert "terminal external account status is immutable" in trigger_source
    assert "terminal external account transition requires unlink time" in trigger_source


def test_schema_sync_provider_widening_is_additive_and_preserves_existing_google_external_account_rows():
    external_accounts = _read(EXTERNAL_ACCOUNTS_SQL).lower()
    sync_source = _read(SCHEMA_SYNC_SCRIPT).lower()
    compact_schema = _compact(external_accounts)
    compact_sync = _compact(sync_source)

    assert "providerenum('google','patreon'," in compact_schema
    assert "altertableuser_external_accounts" in compact_sync
    assert "modifyproviderenum('google','patreon'," in compact_sync, "ENUM patch must append, never reorder"
    # The namespace migration is additive plus an index swap. It backfills; it never
    # rewrites a subject hash and never deletes a row.
    assert "setidentity_namespace=providerwhereidentity_namespace=''" in compact_sync
    assert "provider_sub_hash=" not in compact_sync, "schema sync must never rewrite a subject hash"
    assert "drop table user_external_accounts" not in sync_source
    assert "truncate table user_external_accounts" not in sync_source
    assert not re.search(r"delete\s+from\s+user_external_accounts\b", sync_source)


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


OAUTH_TABLES_SQL = ROOT / "schemas/tables/13_oauth_connections.sql"
OAUTH_SP_SQL = ROOT / "schemas/stored_procedures/19_oauth_connections.sql"
OAUTH_TRIGGERS_SQL = ROOT / "schemas/triggers/08_oauth_connections_triggers.sql"
PLAINTEXT_SECRET_COLUMNS = (
    "client_secret",
    "signing_key",
    "legacy_redeem_token",
    "legacy_redeem_url",
    "private_key",
)


def test_oauth_connection_tables_store_secrets_as_ciphertext_only():
    source = _read(OAUTH_TABLES_SQL)
    for table_name in ("oauth_connections", "project_oauth_bindings"):
        table = _table_block(source, table_name)
        for column in PLAINTEXT_SECRET_COLUMNS:
            assert not _has_forbidden_column(table, column), (
                f"{table_name} must never hold a plaintext {column} column"
            )
    connections = _compact(_table_block(source, "oauth_connections"))
    assert "client_secret_ciphertextlongblob" in connections
    assert "client_secret_hmacbinary(32)" in connections
    assert "credential_key_idvarchar(128)" in connections
    assert not any(_has_forbidden_column(_table_block(source, "oauth_connections"), c) for c in FORBIDDEN_TOKEN_COLUMNS)


def test_only_the_two_server_only_procedures_select_ciphertext():
    source = _read(OAUTH_SP_SQL)
    blocks = re.findall(r"create\s+procedure\s+`?(\w+)`?\s*\(.*?\nend\$\$", source, flags=re.IGNORECASE | re.DOTALL)
    assert blocks, "expected OAuth stored procedures"
    allowed = {
        "sp_oauth_connection_get_operational_credentials",
        "sp_oauth_binding_get_legacy_redeem",
        # writers take ciphertext as INPUT and never select it back
        "sp_oauth_connection_set_credentials",
        "sp_oauth_binding_set_legacy_redeem",
        "sp_oauth_connection_delete",
    }
    for name in blocks:
        block = _procedure_block(source, name)
        selects = re.findall(r"select\b(.*?)\bfrom\b", block, flags=re.DOTALL)
        leaks = [s_ for s_ in selects if "_ciphertext," in s_ or re.search(r"_ciphertext\s*$", s_.strip()) or "_hmac" in s_]
        # ``x_ciphertext IS NOT NULL AS has_x`` is a presence flag, not a leak.
        leaks = [s_ for s_ in leaks if re.search(r"(?<!\()\b\w+_(?:ciphertext|hmac)\s*(?:,|$)", s_.strip(), flags=re.MULTILINE)]
        if name not in allowed:
            assert not leaks, f"{name} must not select ciphertext or HMAC columns"


def test_provisioning_policy_and_group_come_from_the_binding_not_the_caller():
    source = _read(OAUTH_SP_SQL)
    create = _procedure_block(source, "sp_create_consumer_user_from_external_identity")
    assert "from project_oauth_bindings" in create
    assert "provisioning_mode, default_user_group_id into v_mode, v_group_id" in create
    assert "binding does not permit auto-provisioning" in create
    assert "login_enabled = true" in create, "auto-create requires a login-capable provider type"

    upsert = _procedure_block(source, "sp_oauth_binding_upsert")
    assert "default user group does not reach this project" in upsert
    assert "auto-create requires a default user group" in upsert


def test_patreon_stays_link_only_at_the_database_boundary():
    tables = _read(OAUTH_TABLES_SQL).lower()
    assert re.search(r"\('oapc-patreon',\s*'patreon',\s*'patreon',\s*'custom',\s*'enabled',\s*false,", tables), (
        "patreon must be seeded with login_enabled = FALSE"
    )
    assert "status = values(status)" not in tables, "re-running the seed must not undo an operator kill switch"
    assert "login_enabled = values(login_enabled)" not in tables
    catalog = _procedure_block(_read(OAUTH_SP_SQL), "sp_oauth_catalog_set_status")
    assert "patreon cannot be enabled for login" in catalog


def test_oauth_connection_triggers_are_fail_closed():
    triggers = _read(OAUTH_TRIGGERS_SQL).lower()
    assert "an active oauth connection requires active credentials" in triggers
    assert "active oauth credentials require ciphertext and a key id" in triggers
    assert "provider type does not accept tenant-supplied endpoints" in triggers
    assert "identity namespace is immutable once identities are linked" in triggers
    assert "oauth connection provider type is immutable" in triggers


def test_oauth_schema_files_are_registered_in_every_ordered_list():
    for script_path in (CREATE_DATABASE_SCRIPT, RECREATE_DATABASE_SCRIPT):
        source = _read(script_path)
        for name in ("tables/13_oauth_connections.sql", "stored_procedures/19_oauth_connections.sql", "triggers/08_oauth_connections_triggers.sql"):
            assert name in source, f"{name} missing from {script_path.name}"
    sync_source = _read(SCHEMA_SYNC_SCRIPT)
    # The catalog table must be created before the external-account trigger file that reads it.
    assert sync_source.find('"tables/13_oauth_connections.sql"') < sync_source.find('"triggers/05_external_accounts_triggers.sql"')
    compose = _read(ROOT / "docker-compose.test.yml")
    for name in ("13_oauth_connections.sql", "19_oauth_connections.sql", "08_oauth_connections_triggers.sql"):
        assert name in compose


class _MarkerCursor:
    """Answers schema_sync's marker queries from a declared database state."""

    def __init__(self, *, indexes, columns, empty_namespaces=0, uncovered_providers=0, catalog=("google", "patreon"), oauth_codes=999):
        self.indexes, self.columns, self.catalog = set(indexes), set(columns), set(catalog)
        self.empty_namespaces, self.uncovered_providers, self.oauth_codes = empty_namespaces, uncovered_providers, oauth_codes
        self._row = None

    def execute(self, sql, params=()):
        text = " ".join(sql.split()).lower()
        if "information_schema.statistics" in text:
            self._row = {"count": int(params[1] in self.indexes)}
        elif "information_schema.columns" in text:
            self._row = {"COLUMN_TYPE": "varchar(191)"} if params[1] in self.columns else None
        elif "information_schema.tables" in text:
            self._row = {"count": 1}
        elif "identity_namespace = ''" in text:
            self._row = {"count": self.empty_namespaces}
        elif "left join oauth_provider_catalog" in text:
            self._row = {"count": self.uncovered_providers}
        elif "from oauth_provider_catalog where provider_type" in text:
            self._row = {"count": int(params[0] in self.catalog)}
        elif "activity_code like 'oauth" in text:
            self._row = {"count": self.oauth_codes}
        else:  # pragma: no cover - a new marker query must be modelled here
            raise AssertionError(f"unmodelled marker query: {text[:80]}")

    def fetchone(self):
        return self._row


def test_schema_sync_verify_checks_outcomes_not_only_object_names():
    """--verify must fail on a half-applied namespace migration (names alone cannot show it)."""
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("schema_sync_under_test", SCHEMA_SYNC_SCRIPT)
    schema_sync = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = schema_sync  # dataclasses resolve annotations through sys.modules
    try:
        spec.loader.exec_module(schema_sync)
    finally:
        sys.modules.pop(spec.name, None)

    new_keys = {"uk_external_accounts_active_namespace_sub", "uk_external_accounts_user_namespace"}
    old_keys = {"uk_external_accounts_active_sub", "uk_external_accounts_user_provider"}
    migrated = {"identity_namespace", "connection_id", "active_user_namespace"}

    assert schema_sync._verify_oauth_markers(_MarkerCursor(indexes=new_keys, columns=migrated)) == []

    half_applied = schema_sync._verify_oauth_markers(
        _MarkerCursor(
            indexes={"uk_external_accounts_active_namespace_sub"} | old_keys,
            columns=migrated | {"active_user_provider"},
            empty_namespaces=2,
            uncovered_providers=1,
            catalog=("google",),
            oauth_codes=0,
        )
    )
    joined = "\n".join(half_applied)
    for expected in (
        "missing unique key uk_external_accounts_user_namespace",
        "provider-keyed unique key still present: uk_external_accounts_active_sub",
        "provider-keyed unique key still present: uk_external_accounts_user_provider",
        "stale generated column still present: user_external_accounts.active_user_provider",
        "identity_namespace backfill incomplete: 2 row(s)",
        "provider value(s) in use have no oauth_provider_catalog row",
        "oauth_provider_catalog is missing the patreon row",
        "OAuth activity catalog range is incomplete",
    ):
        assert expected in joined, expected

    source = SCHEMA_SYNC_SCRIPT.read_text(encoding="utf-8")
    assert "failures.extend(_verify_oauth_markers(cursor))" in source
    assert "SET SESSION lock_wait_timeout" in source, "a blocked ALTER must fail fast, not queue logins behind it"
