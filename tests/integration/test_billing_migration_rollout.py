"""RED migration/rollout contracts for additive provider-agnostic billing SQL.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 2.8.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BILLING_TABLES_SQL = ROOT / "schemas" / "tables" / "12_billing_provider_facts.sql"
BILLING_SP_SQL = ROOT / "schemas" / "stored_procedures" / "17_billing_provider_facts.sql"
BILLING_TRIGGERS_SQL = ROOT / "schemas" / "triggers" / "07_billing_provider_facts_triggers.sql"
PATREON_TABLES_SQL = ROOT / "schemas" / "tables" / "11_patreon_entitlements.sql"
PATREON_SP_SQL = ROOT / "schemas" / "stored_procedures" / "16_patreon_entitlements.sql"
PATREON_TRIGGERS_SQL = ROOT / "schemas" / "triggers" / "06_patreon_entitlements_triggers.sql"
CREATE_DATABASE_SCRIPT = ROOT / "scripts" / "create_database.py"
RECREATE_DATABASE_SCRIPT = ROOT / "scripts" / "recreate_database.py"
BOOTSTRAP_SCRIPT = ROOT / "scripts" / "migrations" / "billing_provider_bootstrap.py"

BILLING_TABLES = {
    "billing_providers",
    "billing_customers",
    "billing_checkout_intents",
    "billing_subscriptions",
    "billing_subscription_snapshots",
    "billing_entitlements_current",
    "billing_entitlement_history",
    "billing_purchase_events",
    "billing_purchase_history",
    "billing_webhook_deliveries",
    "billing_sync_jobs",
    "billing_raw_payload_quarantine",
}

BILLING_PROCEDURES = {
    "sp_billing_resolve_user_project",
    "sp_billing_get_current_by_user_project",
    "sp_billing_checkout_intent_begin",
    "sp_billing_checkout_intent_complete",
    "sp_billing_customer_upsert",
    "sp_billing_get_customer_operational_ref",
    "sp_billing_webhook_delivery_record",
    "sp_billing_subscription_observe",
    "sp_billing_purchase_event_record",
    "sp_billing_sync_job_enqueue",
    "sp_billing_sync_job_claim",
    "sp_billing_sync_job_complete",
    "sp_billing_retention_purge",
}


def _read(path: Path) -> str:
    assert path.exists(), f"missing expected billing rollout artifact: {path.relative_to(ROOT)}"
    return path.read_text(encoding="utf-8", errors="ignore")


def _compact(source: str) -> str:
    return re.sub(r"\s+", "", source.lower().replace("`", ""))


def test_billing_schema_procedure_and_trigger_files_exist_with_required_table_family():
    table_sql = _read(BILLING_TABLES_SQL).lower()
    sp_sql = _read(BILLING_SP_SQL).lower()
    trigger_sql = _read(BILLING_TRIGGERS_SQL).lower()

    for table in BILLING_TABLES:
        assert f"create table" in table_sql and table in table_sql, f"missing billing table {table}"
    for procedure in BILLING_PROCEDURES:
        assert procedure in sp_sql, f"missing billing stored procedure {procedure}"

    assert "provider_customer_id_ciphertext" in table_sql
    assert "provider_customer_id_hmac" in table_sql
    assert "provider_customer_id_fingerprint" in table_sql
    assert "provider_ref_key_id" in table_sql
    assert "signal sqlstate" in trigger_sql or "raise" in trigger_sql


def test_billing_schema_enforces_project_scoped_customer_uniqueness_and_terminal_no_paid_plan():
    table_compact = _compact(_read(BILLING_TABLES_SQL))
    trigger_compact = _compact(_read(BILLING_TRIGGERS_SQL))

    assert "user_id" in table_compact and "project_id" in table_compact and "provider" in table_compact
    assert "active_user_project_provider" in table_compact or "uk_billing_customer_scope" in table_compact
    assert "provider_customer_id_fingerprintchar(12)" in table_compact or "provider_customer_id_fingerprintvarchar(12)" in table_compact
    assert "terminal" in trigger_compact or "canceled" in trigger_compact or "former" in trigger_compact
    assert "plan_code='free'" in trigger_compact or "plan_code<>\'free\'" in trigger_compact or "plan_code!='free'" in trigger_compact


def test_billing_retention_policy_is_encoded_without_purging_normalized_history():
    combined = (_read(BILLING_TABLES_SQL) + "\n" + _read(BILLING_SP_SQL) + "\n" + _read(BILLING_TRIGGERS_SQL)).lower()
    assert "90" in combined and "webhook" in combined and "retention" in combined
    assert "30" in combined and "raw_payload" in combined
    assert "billing_entitlement_history" in combined
    assert "billing_purchase_history" in combined
    assert "delete from billing_entitlement_history" not in combined
    assert "delete from billing_purchase_history" not in combined


def test_database_bootstrap_registers_billing_sql_after_existing_patreon_artifacts():
    required_order = (
        "tables/11_patreon_entitlements.sql",
        "stored_procedures/16_patreon_entitlements.sql",
        "triggers/06_patreon_entitlements_triggers.sql",
        "tables/12_billing_provider_facts.sql",
        "stored_procedures/17_billing_provider_facts.sql",
        "triggers/07_billing_provider_facts_triggers.sql",
    )
    for script_path in (CREATE_DATABASE_SCRIPT, RECREATE_DATABASE_SCRIPT):
        source = _read(script_path)
        positions = [source.find(fragment) for fragment in required_order]
        assert all(position >= 0 for position in positions), f"{script_path.name} must register Patreon and billing SQL files"
        assert positions == sorted(positions), f"{script_path.name} must load Patreon before additive billing artifacts"


def test_bootstrap_seed_and_rollback_are_redacted_dry_run_safe():
    source = _read(BOOTSTRAP_SCRIPT).lower()
    assert "dry" in source and "apply" in source
    assert "billing_providers" in source
    assert "stripe" in source
    assert "table_name as table_name" in source
    assert "routine_name as routine_name" in source
    assert "sk_" not in source
    assert "whsec_" not in source
    assert "cus_" not in source


def test_existing_patreon_artifacts_remain_present_and_not_destructively_generalized():
    patreon_sources = {
        PATREON_TABLES_SQL: _read(PATREON_TABLES_SQL).lower(),
        PATREON_SP_SQL: _read(PATREON_SP_SQL).lower(),
        PATREON_TRIGGERS_SQL: _read(PATREON_TRIGGERS_SQL).lower(),
    }
    for path, source in patreon_sources.items():
        assert "patreon" in source, f"{path.relative_to(ROOT)} must remain Patreon-specific"
        assert "drop table" not in source
        assert "rename table" not in source
