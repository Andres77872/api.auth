"""RED unit contracts for Patreon audit/privacy redaction.

Trace: `.dev/sdd/changes/patreon-account-link/tasks.md` task 1.7 and
spec/design requirements that Patreon signatures, raw IDs, email, payloads,
proof tokens, creator credentials, webhook bodies, and S2S credentials remain
server-only and out of audit/log/browser-visible surfaces.
"""

from __future__ import annotations

import json

from src.Util.api_audit_logger import APIAuditLogger
from src.middleware.api_audit import APIAuditMiddleware


REDACTED = APIAuditLogger.REDACTED_VALUE

SENSITIVE_PATREON_FIELDS = {
    "patreon_email": "patron-linked@example.test",
    "patreon_user_id": "user-fixture-linked-001",
    "patreon_member_id": "member-active-alpha-001",
    "patreon_campaign_id": "campaign-mw-alpha",
    "patreon_tier_id": "tier-mw-alpha-artisan",
    "patron_status": "active_patron",
    "currently_entitled_tiers": ["tier-mw-alpha-artisan"],
    "patreon_signature": "36c5cc386f79205a87d2d351072ab53a",
    "webhook_secret": "patreon_webhook_secret_fixture_do_not_use",
    "creator_access_token": "creator_access_token_fixture_do_not_log",
    "creator_refresh_token": "creator_refresh_token_fixture_do_not_log",
    "patreon_payload": {"data": {"id": "member-active-alpha-001"}},
    "proof_token": "lookup.fixture.secret.fixture",
    "s2s_token": "s2s_bearer_fixture_do_not_log",
}


def _flatten(value) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _audit_middleware() -> APIAuditMiddleware:
    async def app(scope, receive, send):  # pragma: no cover - never called by these unit tests
        raise AssertionError("dummy ASGI app should not be invoked")

    return APIAuditMiddleware(app)


def test_filter_headers_redacts_patreon_signature_and_internal_s2s_headers():
    headers = {
        "X-Patreon-Signature": "36c5cc386f79205a87d2d351072ab53a",
        "x-patreon-event": "members:update",
        "Authorization": "Bearer s2s_bearer_fixture_do_not_log",
        "Content-Type": "application/json",
    }

    filtered = APIAuditLogger.filter_headers(headers)

    assert filtered["X-Patreon-Signature"] == REDACTED
    assert filtered["Authorization"] == REDACTED
    assert filtered["x-patreon-event"] == "members:update"
    assert filtered["Content-Type"] == "application/json"


def test_filter_sensitive_data_redacts_patreon_fields_recursively():
    payload = {
        **SENSITIVE_PATREON_FIELDS,
        "safe_reason": "tier_map_miss",
        "nested": dict(SENSITIVE_PATREON_FIELDS),
        "events": [dict(SENSITIVE_PATREON_FIELDS)],
    }

    filtered = APIAuditLogger.filter_sensitive_data(payload)
    serialized = _flatten(filtered)

    for field, raw_value in SENSITIVE_PATREON_FIELDS.items():
        assert filtered[field] == REDACTED, f"field {field} must be redacted"
        assert str(raw_value) not in serialized, f"raw Patreon value for {field} leaked"
    assert filtered["safe_reason"] == "tier_map_miss"


def test_sanitize_sensitive_text_removes_patreon_credentials_and_provider_internals():
    raw_message = (
        "patreon_user_id=user-fixture-linked-001 "
        "patreon_member_id=member-active-alpha-001 "
        "patreon_campaign_id=campaign-mw-alpha "
        "patreon_tier_id=tier-mw-alpha-artisan "
        "patreon_email=patron-linked@example.test "
        "creator_access_token=creator_access_token_fixture_do_not_log "
        "proof_token=lookup.fixture.secret.fixture "
        "x-patreon-signature=36c5cc386f79205a87d2d351072ab53a"
    )

    sanitized = APIAuditLogger.sanitize_sensitive_text(raw_message)

    for raw_value in (
        "user-fixture-linked-001",
        "member-active-alpha-001",
        "campaign-mw-alpha",
        "tier-mw-alpha-artisan",
        "patron-linked@example.test",
        "creator_access_token_fixture_do_not_log",
        "lookup.fixture.secret.fixture",
        "36c5cc386f79205a87d2d351072ab53a",
    ):
        assert raw_value not in sanitized


def test_patreon_webhook_raw_body_is_excluded_from_api_audit_capture():
    middleware = _audit_middleware()

    assert middleware._is_raw_body_audit_excluded("/webhooks/patreon") is True
    assert middleware._is_raw_body_audit_excluded("/webhooks/patreon?debug=true") is True
    assert middleware._is_raw_body_audit_excluded("/auth/patreon/link/status") is False


def test_patreon_webhook_and_internal_entitlement_auth_methods_are_classified():
    middleware = _audit_middleware()

    assert middleware._infer_auth_method("/webhooks/patreon", user_id=None, session_id=None) == "webhook"
    assert (
        middleware._infer_auth_method(
            "/internal/users/usr_contract_linked_001/entitlements",
            user_id=None,
            session_id=None,
        )
        == "api_key"
    )
    assert (
        middleware._infer_auth_method(
            "/internal/users/usr_contract_linked_001/entitlements/patreon/resync",
            user_id=None,
            session_id=None,
        )
        == "api_key"
    )


def test_patreon_route_tags_are_specific_and_security_relevant():
    webhook_tags = APIAuditLogger.generate_tags("/webhooks/patreon", "POST", 401, user_type=None)
    s2s_tags = APIAuditLogger.generate_tags(
        "/internal/users/usr_contract_linked_001/entitlements",
        "GET",
        403,
        user_type=None,
    )

    assert "webhook" in webhook_tags
    assert "patreon" in webhook_tags
    assert "security_event" in webhook_tags
    assert "patreon" in s2s_tags
    assert "s2s" in s2s_tags or "internal" in s2s_tags
    assert "security_event" in s2s_tags


def test_patreon_webhook_metadata_remains_auditable_without_raw_body_capture():
    # `/webhooks/patreon` should still be metadata-auditable for security and
    # operations, but the middleware must not persist the raw provider payload.
    assert APIAuditLogger.should_log_request("/webhooks/patreon", "POST") is True
