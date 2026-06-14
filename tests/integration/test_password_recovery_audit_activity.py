"""RED audit redaction and activity-catalog tests for password recovery delta.

Trace: `.dev/sdd/changes/password-recovery-email-validation/tasks.md` task 1.7.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_api_audit_redacts_password_change_and_reset_sensitive_fields():
    from src.Util.api_audit_logger import APIAuditLogger

    payload = {
        "current_password": "current-audit-contract-2026",
        "new_password": "new audit contract passphrase",
        "password_hash": "$argon2id$audit-contract-hash",
        "reset_token": "lookup.secret-fragment",
        "reset_link": "link-token-fragment",
        "idempotency_key": "idem-audit-contract",
        "provider_payload": {"raw": "provider-payload-contract"},
    }

    filtered = APIAuditLogger.filter_sensitive_data(payload)
    serialized = str(filtered)

    for forbidden in [
        "current-audit-contract-2026",
        "new audit contract passphrase",
        "$argon2id$audit-contract-hash",
        "lookup.secret-fragment",
        "link-token-fragment",
        "idem-audit-contract",
        "provider-payload-contract",
    ]:
        assert forbidden not in serialized


def test_password_change_path_is_security_relevant_session_activity():
    from src.Util.api_audit_logger import APIAuditLogger

    assert APIAuditLogger.should_log_request("/auth/password/change", "POST") is True
    assert APIAuditLogger.is_security_event("/auth/password/change", "POST", 200, "consumer") is True


def test_password_changed_activity_enum_and_catalog_row_are_aligned_after_email_range():
    from src.Util.activity_logger import ActivityType

    sql = (ROOT / "schemas/tables/08_activity_logging_tables.sql").read_text()

    assert "password_changed" in {item.value for item in ActivityType}
    assert "act-cat-063" in sql
    assert "password_changed" in sql


def test_user_update_trigger_no_longer_labels_generic_hash_changes_as_password_resets():
    sql = (ROOT / "schemas/triggers/01_activity_logging_triggers.sql").read_text()
    trigger = sql.split("CREATE TRIGGER trg_after_user_update", 1)[1].split("END//", 1)[0]

    assert "NEW.password_hash != OLD.password_hash THEN 'user_password_reset'" not in trigger
    assert "password_changed" not in trigger.lower()
