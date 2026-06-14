"""RED migration/rollout tests for email activation schema.

Trace: `.dev/sdd/changes/email-activation/tasks.md` task 1.8.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_additive_email_schema_files_exist_and_define_canonical_tables():
    sql = (ROOT / "schemas/tables/09_email_activation_tables.sql").read_text()

    for table in [
        "user_emails",
        "user_email_link_tokens",
        "email_messages",
        "email_delivery_attempts",
        "email_suppressions",
        "email_idempotency_keys",
        "email_templates",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql

    assert "GENERATED ALWAYS" in sql
    assert "uk_user_emails_active_activated_email" in sql
    assert "uk_user_emails_one_primary" in sql


def test_legacy_users_email_backfill_is_pending_not_activated():
    sql = (ROOT / "schemas/stored_procedures/14_email_activation.sql").read_text()

    assert "sp_backfill_legacy_user_emails" in sql
    assert "users.email" in sql
    assert "status" in sql
    assert "pending" in sql
    assert "legacy" in sql
    assert "activated_at" not in sql.split("sp_backfill_legacy_user_emails", 1)[1].split("END", 1)[0]


def test_users_email_shadow_syncs_only_from_primary_activation_change_or_removal():
    sql = (ROOT / "schemas/stored_procedures/14_email_activation.sql").read_text()

    assert "sp_consume_email_activation_token" in sql
    assert "sp_user_email_set_primary" in sql
    assert "sp_user_email_remove" in sql
    assert "UPDATE users" in sql
    assert "is_primary" in sql
    assert "email_normalized" in sql


def test_gdpr_retention_and_anonymization_routines_are_present():
    sql = (ROOT / "schemas/stored_procedures/14_email_activation.sql").read_text()

    assert "sp_email_retention_purge" in sql
    assert "sp_anonymize_user_email_data" in sql
    assert "render_payload_ciphertext = NULL" in sql
    assert "recipient_email = NULL" in sql
    assert "365" in sql
    assert "30" in sql


def test_bootstrap_registers_email_table_trigger_and_sp_files():
    create_py = (ROOT / "scripts/create_database.py").read_text()
    recreate_py = (ROOT / "scripts/recreate_database.py").read_text()

    for content in (create_py, recreate_py):
        assert "schemas/tables/09_email_activation_tables.sql" in content
        assert "schemas/triggers/04_email_activation_triggers.sql" in content
        assert "schemas/stored_procedures/14_email_activation.sql" in content


def test_disabled_delivery_rollout_env_is_documented_without_dropping_tables():
    env_example = (ROOT / ".env.example").read_text()
    compose_test = (ROOT / "docker-compose.test.yml").read_text()

    assert "EMAIL_DELIVERY_ENABLED=false" in env_example
    assert "EMAIL_PROVIDER=fake" in env_example
    assert "mailpit" in compose_test.lower()
    assert "axllent/mailpit" in compose_test.lower()
