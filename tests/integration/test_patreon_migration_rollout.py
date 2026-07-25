"""RED migration/bootstrap contracts for Patreon account linking.

Trace: `.dev/sdd/changes/patreon-account-link/tasks.md` tasks `1.8` and `11.3`.

These tests are intentionally source/static integration checks.  Phase 1 is the
proof scaffold, not the schema implementation, so failures should point at
missing Patreon SQL/bootstrap/rollback work rather than import-time breakage.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

EXTERNAL_ACCOUNTS_SQL = ROOT / "schemas" / "tables" / "10_external_accounts.sql"
EXTERNAL_ACCOUNTS_SP_SQL = ROOT / "schemas" / "stored_procedures" / "15_external_accounts.sql"
EMAIL_TABLES_SQL = ROOT / "schemas" / "tables" / "09_email_activation_tables.sql"
EMAIL_SP_SQL = ROOT / "schemas" / "stored_procedures" / "14_email_activation.sql"
ACTIVITY_SQL = ROOT / "schemas" / "tables" / "08_activity_logging_tables.sql"
PATREON_TABLES_SQL = ROOT / "schemas" / "tables" / "11_patreon_entitlements.sql"
PATREON_SP_SQL = ROOT / "schemas" / "stored_procedures" / "16_patreon_entitlements.sql"
PATREON_TRIGGERS_SQL = ROOT / "schemas" / "triggers" / "06_patreon_entitlements_triggers.sql"
PATREON_ROLLBACK_RUNBOOK = ROOT / "docs" / "RUNBOOKS" / "patreon-link.md"
SCHEMA_SYNC_SCRIPT = ROOT / "scripts" / "schema_sync.py"
CREATE_DATABASE_SCRIPT = ROOT / "scripts" / "create_database.py"
RECREATE_DATABASE_SCRIPT = ROOT / "scripts" / "recreate_database.py"
COMPOSE_TEST = ROOT / "docker-compose.test.yml"

FORBIDDEN_PER_USER_TOKEN_COLUMNS = {
    "access_token",
    "refresh_token",
    "id_token",
    "oauth_code",
    "authorization_code",
    "creator_access_token",
    "creator_refresh_token",
    "webhook_secret",
    "client_secret",
    "provider_token",
}

PATREON_TABLES = {
    "patreon_link_proofs",
    "patreon_campaigns",
    "patreon_tier_map",
    "patreon_memberships",
    "patreon_member_snapshots",
    "patreon_entitlements_current",
    "patreon_entitlement_history",
    "patreon_webhook_deliveries",
    "patreon_sync_jobs",
    "patreon_raw_payload_quarantine",
}

PATREON_ACTIVITY_CODES = {
    "patreon_link_proof_requested",
    "patreon_link_proof_consumed",
    "patreon_linked",
    "patreon_link_rejected",
    "patreon_unlinked",
    "patreon_webhook_received",
    "patreon_webhook_rejected",
    "patreon_webhook_replay_ignored",
    "patreon_sync_started",
    "patreon_sync_completed",
    "patreon_sync_failed",
    "patreon_entitlement_changed",
    "patreon_tier_map_miss",
    "patreon_token_refreshed",
    "patreon_token_revoked",
    "patreon_retention_purged",
}

LIVE_LIKE_ROLLBACK_SCENARIOS = (
    (
        "Patreon link authority exists",
        {"user_external_accounts": [{"provider": "patreon", "status": "linked"}]},
    ),
    (
        "Patreon proof row exists",
        {"patreon_link_proofs": [{"status": "pending"}]},
    ),
    (
        "Patreon membership row exists",
        {"patreon_memberships": [{"status": "active"}]},
    ),
    (
        "Patreon snapshot row exists",
        {"patreon_member_snapshots": [{"sync_source": "webhook"}]},
    ),
    (
        "Patreon snapshot history row exists",
        {"patreon_member_snapshot_history": [{"event_type": "snapshot_observed"}]},
    ),
    (
        "Patreon current entitlement row exists",
        {"patreon_entitlements_current": [{"link_status": "linked"}]},
    ),
    (
        "Patreon unlink history row exists",
        {"patreon_entitlement_history": [{"sync_source": "unlink", "link_status": "unlinked"}]},
    ),
    (
        "Patreon webhook delivery row exists",
        {"patreon_webhook_deliveries": [{"status": "processed"}]},
    ),
    (
        "Patreon activity/audit evidence exists",
        {"activity_logs": [{"activity_type": "patreon_unlinked"}]},
    ),
)


def _read(path: Path) -> str:
    assert path.exists(), f"missing expected Patreon rollout artifact: {path.relative_to(ROOT)}"
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


def _rollback_count_terms(preflight_block: str) -> tuple[tuple[str, str], ...]:
    pattern = r"select\s+count\(\*\)\s+from\s+`?(?P<table>[a-z0-9_]+)`?(?:\s+where\s+(?P<where>[^)]+?))?\s*\)"
    return tuple(
        (
            match.group("table").lower(),
            re.sub(r"\s+", " ", (match.group("where") or "").replace("`", "").lower()).strip(),
        )
        for match in re.finditer(pattern, preflight_block, flags=re.IGNORECASE | re.DOTALL)
    )


def _sql_like_matches(value: str, pattern: str) -> bool:
    regex = "^" + "".join(
        ".*" if char == "%" else "." if char == "_" else re.escape(char)
        for char in pattern
    ) + "$"
    return re.match(regex, value) is not None


def _row_matches_where(row: dict[str, str], where_clause: str) -> bool:
    if not where_clause:
        return True

    equality_checks = re.findall(r"([a-z0-9_]+)\s*=\s*'([^']+)'", where_clause)
    like_checks = re.findall(r"([a-z0-9_]+)\s+like\s+'([^']+)'", where_clause)
    if not equality_checks and not like_checks:
        raise AssertionError(f"unsupported rollback preflight WHERE clause in test helper: {where_clause}")

    for column, expected in equality_checks:
        if str(row.get(column, "")).lower() != expected:
            return False
    for column, like_pattern in like_checks:
        if not _sql_like_matches(str(row.get(column, "")).lower(), like_pattern):
            return False
    return True


def _preflight_count_for_rows(
    terms: tuple[tuple[str, str], ...],
    rows_by_table: dict[str, list[dict[str, str]]],
) -> int:
    live_rows = 0
    for table_name, where_clause in terms:
        for row in rows_by_table.get(table_name, []):
            if _row_matches_where(row, where_clause):
                live_rows += 1
    return live_rows


def _has_forbidden_column(source: str, column_name: str) -> bool:
    column_pattern = rf"(?:^|[,(]\s*)`?{re.escape(column_name)}`?\s+(?:var)?char|(?:^|[,(]\s*)`?{re.escape(column_name)}`?\s+(?:long)?blob|(?:^|[,(]\s*)`?{re.escape(column_name)}`?\s+text|(?:^|[,(]\s*)`?{re.escape(column_name)}`?\s+json|(?:^|[,(]\s*)`?{re.escape(column_name)}`?\s+binary"
    return re.search(column_pattern, source, flags=re.IGNORECASE | re.MULTILINE) is not None


def test_external_account_provider_model_is_widened_for_patreon_without_token_columns():
    source = _read(EXTERNAL_ACCOUNTS_SQL)
    compact = _compact(source)

    assert "user_external_accounts" in source
    assert "provider_sub_hash" in source
    assert "provider_sub_fingerprint" in source
    assert (
        "providerenum('google','patreon')" in compact
        or "providerenum('patreon','google')" in compact
        or "providerin('google','patreon')" in compact
        or "providerin('patreon','google')" in compact
    ), "user_external_accounts.provider must support both google and patreon"

    for column in FORBIDDEN_PER_USER_TOKEN_COLUMNS:
        assert not _has_forbidden_column(source, column), f"per-user provider token column is forbidden: {column}"


def test_external_account_stored_procedures_accept_patreon_where_generic_but_keep_auto_create_google_only():
    source = _read(EXTERNAL_ACCOUNTS_SP_SQL)
    compact = _compact(source)

    for procedure in (
        "sp_get_user_by_external_account",
        "sp_link_external_account",
        "sp_unlink_external_account",
        "sp_touch_external_account_last_seen",
    ):
        block = _procedure_block(source, procedure)
        assert "patreon" in block, f"{procedure} must accept patreon for no-login link authority"
        assert "google" in block, f"{procedure} must preserve google compatibility"

    assert "p_provider<>'google'" in compact or "p_provider!='google'" in compact
    auto_create = _procedure_block(source, "sp_create_consumer_user_from_external_account")
    assert "patreon" not in auto_create, "auto-create/login-specific external-account procedure must stay Google-only"


def test_patreon_schema_sp_trigger_and_rollout_docs_exist_with_required_contracts():
    table_sql = _read(PATREON_TABLES_SQL).lower()
    sp_sql = _read(PATREON_SP_SQL).lower()
    trigger_sql = _read(PATREON_TRIGGERS_SQL).lower()
    runbook = _read(PATREON_ROLLBACK_RUNBOOK).lower()
    schema_sync = _read(SCHEMA_SYNC_SCRIPT).lower()

    for table in PATREON_TABLES:
        assert f"create table if not exists {table}" in table_sql, f"missing Patreon table {table}"

    for procedure in (
        "sp_patreon_proof_create",
        "sp_patreon_proof_consume",
        "sp_patreon_link_account",
        "sp_patreon_unlink_account",
        "sp_patreon_entitlement_snapshot_upsert",
        "sp_patreon_webhook_delivery_record",
        "sp_patreon_sync_job_enqueue",
        "sp_patreon_get_entitlement_by_user_hash",
        "sp_patreon_retention_purge",
    ):
        assert procedure in sp_sql, f"missing Patreon stored procedure {procedure}"

    assert "patreon" in trigger_sql
    assert "immutable" in trigger_sql or "signal sqlstate" in trigger_sql
    assert "disabled by default" in runbook
    assert "non-destructive" in runbook
    assert "11_patreon_entitlements.sql" in schema_sync
    assert "16_patreon_entitlements.sql" in schema_sync


def test_patreon_terminal_entitlement_triggers_reject_paid_grants_even_if_status_is_active():
    trigger_sql = _compact(_read(PATREON_TRIGGERS_SQL))

    assert "new.link_statusin('unlinked','revoked')" in trigger_sql
    assert "new.entitlement_status='active'" in trigger_sql
    assert "new.plan_code<>'free'" in trigger_sql
    assert "new.tier_codeisnotnull" in trigger_sql
    assert "new.tier_nameisnotnull" in trigger_sql
    assert "new.entitlement_status<>'active'andnew.plan_code<>'free'andnew.link_statusin('unlinked','revoked')" not in trigger_sql


def test_fresh_bootstrap_scripts_and_compose_mount_patreon_sql_in_dependency_order():
    required_files = (
        "tables/11_patreon_entitlements.sql",
        "stored_procedures/16_patreon_entitlements.sql",
        "triggers/06_patreon_entitlements_triggers.sql",
    )

    for script_path in (CREATE_DATABASE_SCRIPT, RECREATE_DATABASE_SCRIPT):
        source = _read(script_path)
        positions = [source.find(file_name) for file_name in required_files]
        assert all(pos >= 0 for pos in positions), f"{script_path.name} must register all Patreon SQL files"
        assert positions == sorted(positions), f"{script_path.name} must load Patreon table -> SP -> trigger in order"

    compose = _read(COMPOSE_TEST)
    for mounted_path in (
        "./schemas/tables/11_patreon_entitlements.sql",
        "./schemas/stored_procedures/16_patreon_entitlements.sql",
        "./schemas/triggers/06_patreon_entitlements_triggers.sql",
    ):
        assert mounted_path in compose, f"docker-compose.test.yml must mount {mounted_path}"
    for env_name in (
        "PATREON_LINKING_ENABLED",
        "PATREON_WEBHOOKS_ENABLED",
        "PATREON_SYNC_ENABLED",
        "PATREON_S2S_ENTITLEMENT_ENABLED",
    ):
        assert env_name in compose, f"compose test env must define disabled fake {env_name}"


def test_no_per_user_patreon_token_columns_in_link_membership_or_entitlement_tables():
    external_accounts = _read(EXTERNAL_ACCOUNTS_SQL)
    patreon_schema = _read(PATREON_TABLES_SQL)

    scanned_blocks = [
        _table_block(external_accounts, "user_external_accounts"),
        _table_block(patreon_schema, "patreon_link_proofs"),
        _table_block(patreon_schema, "patreon_memberships"),
        _table_block(patreon_schema, "patreon_entitlements_current"),
    ]

    for block in scanned_blocks:
        for column in FORBIDDEN_PER_USER_TOKEN_COLUMNS:
            assert not _has_forbidden_column(block, column), f"Patreon per-user rows must not store raw token column {column}"


def test_patreon_activity_catalog_range_is_seeded_after_google_oauth():
    source = _read(ACTIVITY_SQL).lower()

    assert "act-cat-074" in source, "Google OAuth activity range must remain present"
    for number in range(75, 75 + len(PATREON_ACTIVITY_CODES)):
        assert f"act-cat-{number:03d}" in source, f"missing Patreon activity catalog id act-cat-{number:03d}"
    for code in PATREON_ACTIVITY_CODES:
        assert code in source, f"missing Patreon activity code {code}"


def test_patreon_link_proof_email_outbox_purpose_is_supported_without_reusing_local_email_tokens():
    email_tables = _read(EMAIL_TABLES_SQL)
    email_sp = _read(EMAIL_SP_SQL).lower()
    patreon_sp = _read(PATREON_SP_SQL).lower()

    email_messages = _table_block(email_tables, "email_messages")
    local_email_tokens = _table_block(email_tables, "user_email_link_tokens")

    assert "patreon_link_proof" in email_messages, "email outbox must support patreon_link_proof purpose"
    assert "patreon_link_proof" not in local_email_tokens, "Patreon proof tokens must not overload local email activation tokens"
    assert "patreon_link_proof" in email_sp, "email outbox procedures must permit the Patreon proof purpose"
    assert "patreon_link_proof" in patreon_sp, "Patreon proof procedure must enqueue the Patreon proof email"
    assert "email_messages" in patreon_sp, "Patreon proof creation must use durable email outbox"


def test_destructive_rollback_is_refused_when_live_patreon_rows_exist():
    source = _read(PATREON_ROLLBACK_RUNBOOK).lower()

    assert "rollback" in source
    assert "destructive" in source
    for table in (
        "user_external_accounts",
        "patreon_link_proofs",
        "patreon_entitlements_current",
        "patreon_entitlement_history",
        "patreon_webhook_deliveries",
        "patreon_memberships",
    ):
        assert table in source, f"rollback preflight must inspect live data in {table}"
    assert "refuse" in source, (
        "rollback path must fail closed when live Patreon history exists"
    )


def test_destructive_rollback_runbook_refuses_each_live_like_patreon_evidence_scenario():
    source = _read(PATREON_ROLLBACK_RUNBOOK).lower()
    for scenario_name, rows_by_table in LIVE_LIKE_ROLLBACK_SCENARIOS:
        for table in rows_by_table:
            assert table in source, f"rollback runbook would not refuse when {scenario_name}"
    assert "if any row exists, refuse" in source
    assert "non-destructive disable/archive rollback" in source


def test_destructive_rollback_preflight_keeps_live_history_tables_in_refusal_scope():
    compact = _compact(_read(PATREON_ROLLBACK_RUNBOOK))

    required_live_history_fragments = (
        "user_external_accountswhereproviderispatreon",
        "patreon_link_proofs",
        "patreon_memberships",
        "patreon_member_snapshots",
        "patreon_member_snapshot_history",
        "patreon_entitlements_current",
        "patreon_entitlement_history",
        "patreon_webhook_deliveries",
        "activity_logswhereactivitytypestartswithpatreon_",
    )
    for fragment in required_live_history_fragments:
        assert fragment in compact, f"rollback preflight must include live/history evidence selector: {fragment}"

    assert "droptable" not in compact
    assert "deletefrom" not in compact
