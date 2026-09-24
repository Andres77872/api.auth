"""Rollout contracts for the billing-group re-key, catalog, and seed script.

Pure file/structure checks (no live DB): verifies the new billing_groups / catalog tables,
the project->group access view, the group/catalog procedures, DB-script registration, the
re-key of fact tables to billing_group_id, and that the seed script is redacted + dry-run-safe.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TABLES_SQL = ROOT / "schemas" / "tables" / "12_billing_provider_facts.sql"
GROUP_SP_SQL = ROOT / "schemas" / "stored_procedures" / "18_billing_groups.sql"
FACT_SP_SQL = ROOT / "schemas" / "stored_procedures" / "17_billing_provider_facts.sql"
TRIGGERS_SQL = ROOT / "schemas" / "triggers" / "07_billing_provider_facts_triggers.sql"
CREATE_DB = ROOT / "scripts" / "create_database.py"
RECREATE_DB = ROOT / "scripts" / "recreate_database.py"
GROUP_BOOTSTRAP = ROOT / "scripts" / "migrations" / "billing_group_bootstrap.py"

NEW_TABLES = {"billing_groups", "billing_group_projects", "billing_catalog_items"}
GROUP_PROCEDURES = {
    "sp_billing_resolve_user_billing_group",
    "sp_billing_group_create",
    "sp_billing_group_set_credentials",
    "sp_billing_group_get_operational_credentials",
    "sp_billing_group_attach_project",
    "sp_billing_catalog_item_create",
    "sp_billing_catalog_item_set_provisioned",
    "sp_billing_catalog_list_for_project",
}


def _read(path: Path) -> str:
    assert path.exists(), f"missing rollout artifact: {path.relative_to(ROOT)}"
    return path.read_text(encoding="utf-8", errors="ignore")


def _compact(source: str) -> str:
    return re.sub(r"\s+", "", source.lower().replace("`", ""))


def test_group_and_catalog_tables_and_view_exist():
    table_sql = _read(TABLES_SQL).lower()
    for table in NEW_TABLES:
        assert f"create table" in table_sql and table in table_sql, f"missing table {table}"
    # per-account encrypted Stripe credential columns on the group
    assert "stripe_secret_key_ciphertext" in table_sql
    assert "stripe_webhook_secret_ciphertext" in table_sql
    assert "credential_status" in table_sql
    # opaque, agnostic catalog features
    assert "features json" in table_sql and "billing_catalog_items" in table_sql
    # project -> billing group resolver view
    assert "v_user_billing_group_access" in table_sql


def test_group_and_catalog_procedures_exist():
    sp_sql = _read(GROUP_SP_SQL).lower()
    for proc in GROUP_PROCEDURES:
        assert proc in sp_sql, f"missing group/catalog procedure {proc}"
    # hot-path session plan projection lives in the fact-procedure file
    assert "sp_billing_get_session_plan" in _read(FACT_SP_SQL).lower()


def test_fact_tables_are_rekeyed_to_billing_group():
    compact = _compact(_read(TABLES_SQL))
    # subscriptions/entitlements/customers now scope on billing_group_id
    assert "active_user_group_provider" in compact
    assert "uk_billing_current_scope(user_id,billing_group_id,provider)" in compact
    # webhook dedupe uniqueness includes billing_group_id (no cross-account collision)
    assert "uk_billing_webhook_provider_event(provider,billing_group_id,provider_event_id_hmac)" in compact
    # credit purchases keep BOTH project_id and billing_group_id
    purchase_block = _read(TABLES_SQL).lower().split("billing_purchase_events")[1].split(") engine")[0]
    assert "project_id" in purchase_block and "billing_group_id" in purchase_block


def test_db_scripts_register_group_procedures_after_fact_procedures():
    for script in (CREATE_DB, RECREATE_DB):
        source = _read(script)
        pos_17 = source.find("stored_procedures/17_billing_provider_facts.sql")
        pos_18 = source.find("stored_procedures/18_billing_groups.sql")
        assert pos_17 >= 0 and pos_18 >= 0, f"{script.name} must register both billing proc files"
        assert pos_17 < pos_18, f"{script.name} must load 17 before 18"


def test_group_bootstrap_is_redacted_and_dry_run_safe():
    source = _read(GROUP_BOOTSTRAP).lower()
    assert "dry" in source and "apply" in source and "check-db" in source
    assert "billing_groups" in source and "billing_catalog_items" in source
    assert "billing_providers" in source and "provider_code = %s" in source
    assert "billing_provider_bootstrap.py --apply first" in source
    # never prints raw secret material
    assert "print(creds" not in source
    assert "sk_live" not in source and "whsec_" not in source and "cus_" not in source
    assert "output=redacted" in source


def _procedure_select(sql: str, name: str) -> str:
    """Return the lower-cased body of ``CREATE PROCEDURE <name>`` up to its ``END$$``."""

    lowered = sql.lower()
    start = lowered.find(f"create procedure {name.lower()}(")
    assert start >= 0, f"missing procedure {name}"
    end = lowered.find("end$$", start)
    assert end > start, f"procedure {name} is not terminated"
    return lowered[start:end]


def test_group_reads_return_the_catalog_sync_fields():
    sql = _read(GROUP_SP_SQL)
    for proc in ("sp_billing_group_get_by_hash", "sp_billing_group_list"):
        body = _procedure_select(sql, proc)
        for column in ("catalog_sync_status", "last_catalog_synced_at"):
            assert column in body, f"{proc} must select {column}"


def test_group_list_returns_capability_flags_and_webhook_secret_presence():
    body = _procedure_select(_read(GROUP_SP_SQL), "sp_billing_group_list")
    for column in ("checkout_enabled", "portal_enabled", "provisioning_enabled", "webhooks_enabled", "has_webhook_secret"):
        assert column in body, f"sp_billing_group_list must select {column}"
    # presence only: the list must never return credential material
    assert "ciphertext as" not in body and "_hmac," not in body


def test_purchase_status_lookup_is_scoped_to_user_and_project_and_returns_safe_columns_only():
    body = _procedure_select(_read(FACT_SP_SQL), "sp_billing_get_purchase_status_by_ref")
    compact = _compact(body)
    for param in ("p_user_hash", "p_project_hash", "p_purchase_ref", "p_provider"):
        assert param in body, f"lookup must take {param}"
    assert "u.user_hash=p_user_hash" in compact
    assert "p.project_hash=p_project_hash" in compact
    assert "bpe.user_id=u.id" in compact and "bpe.project_id=p.id" in compact
    assert "bpe.purchase_ref=p_purchase_ref" in compact
    for forbidden in ("ciphertext", "_hmac", "_fingerprint", "safe_metadata", "customer_id", "checkout_ref"):
        assert forbidden not in body, f"purchase lookup must not select {forbidden}"
