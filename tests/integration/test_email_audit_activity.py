"""RED audit/activity contract tests for email activation.

Trace: `.dev/sdd/changes/email-activation/tasks.md` task 1.6.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_api_audit_redacts_email_links_bodies_provider_payloads_and_idempotency_keys():
    from src.Util.api_audit_logger import APIAuditLogger

    payload = {
        "email": "person@example.com",
        "recipient_email": "person@example.com",
        "activation_link": "https://client.example/verify?token=lookup.secret",
        "reset_link": "https://client.example/reset?token=lookup.secret",
        "subject": "Activate person@example.com",
        "html": "<a href='https://client.example/verify?token=lookup.secret'>verify</a>",
        "text": "lookup.secret",
        "template_variables": {"token": "lookup.secret", "email": "person@example.com"},
        "provider_response": {"raw": "person@example.com lookup.secret"},
        "idempotency_key": "public-idem-key",
        "lookup_id": "lookup",
        "secret": "secret",
    }

    filtered = APIAuditLogger.filter_sensitive_data(payload)

    serialized = str(filtered)
    assert "person@example.com" not in serialized
    assert "lookup.secret" not in serialized
    assert "public-idem-key" not in serialized
    assert "https://client.example" not in serialized


def test_api_audit_redacts_email_sensitive_headers():
    from src.Util.api_audit_logger import APIAuditLogger

    headers = {
        "Idempotency-Key": "raw-idem-key",
        "Svix-Signature": "v1,secret-signature",
        "Svix-Timestamp": "1710000000",
        "Authorization": "Bearer token",
        "Content-Type": "application/json",
    }

    filtered = APIAuditLogger.filter_headers(headers)

    assert filtered["Idempotency-Key"] == "***FILTERED***"
    assert filtered["Svix-Signature"] == "***FILTERED***"
    assert filtered["Svix-Timestamp"] == "***FILTERED***"
    assert filtered["Authorization"] == "***FILTERED***"
    assert filtered["Content-Type"] == "application/json"


def test_api_audit_auth_method_enum_allows_anonymous_email_link_and_webhook():
    sql = (ROOT / "schemas/tables/02_create_tables.sql").read_text()

    match = re.search(r"auth_method\s+ENUM\(([^)]+)\)", sql)
    assert match is not None
    values = {
        value.strip().strip("'\"")
        for value in match.group(1).split(",")
    }
    assert {
        "session",
        "api_key",
        "anonymous",
        "email_link",
        "webhook",
        "oauth",
    } <= values


def test_activity_type_enum_contains_email_reset_delivery_range():
    from src.Util.activity_logger import ActivityType

    expected_codes = {
        "user_email_added",
        "user_email_activation_requested",
        "user_email_activation_resent",
        "user_email_activated",
        "user_email_removed",
        "user_email_primary_changed",
        "auth_email_login",
        "password_reset_requested",
        "password_reset_consumed",
        "admin_password_reset_requested",
        "email_message_enqueued",
        "email_message_sent",
        "email_message_delivered",
        "email_message_bounced",
        "email_message_complained",
        "email_message_dead_lettered",
        "email_suppression_updated",
    }

    actual_codes = {item.value for item in ActivityType}
    assert expected_codes <= actual_codes


def test_activity_catalog_seeds_act_cat_046_through_062_in_order():
    sql = (ROOT / "schemas/tables/08_activity_logging_tables.sql").read_text()

    for number in range(46, 63):
        assert f"act-cat-{number:03d}" in sql

    for code in [
        "user_email_added",
        "user_email_activation_requested",
        "user_email_activation_resent",
        "user_email_activated",
        "user_email_removed",
        "user_email_primary_changed",
        "auth_email_login",
        "password_reset_requested",
        "password_reset_consumed",
        "admin_password_reset_requested",
        "email_message_enqueued",
        "email_message_sent",
        "email_message_delivered",
        "email_message_bounced",
        "email_message_complained",
        "email_message_dead_lettered",
        "email_suppression_updated",
    ]:
        assert code in sql


def test_webhook_paths_are_excluded_from_raw_body_audit_logging():
    from src.Util.api_audit_logger import APIAuditLogger

    assert APIAuditLogger.should_log_request("/webhooks/email/resend", "POST") is False
