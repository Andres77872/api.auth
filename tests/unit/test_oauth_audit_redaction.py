"""RED unit contracts for OAuth audit/error/log redaction.

Trace: `.dev/sdd/changes/google-oauth-login/tasks.md` task 2.4 and
spec requirements that OAuth callback remains audited while code/state/nonce,
PKCE, ID/access/refresh tokens, provider identifiers, Google email/domain,
provider-init token, and link token are redacted from audit/error/log surfaces.
"""

from __future__ import annotations

import json

from src.Util.api_audit_logger import APIAuditLogger
from src.Util.error_handler import sanitize_error_message


REDACTED = APIAuditLogger.REDACTED_VALUE

SENSITIVE_OAUTH_FIELDS = {
    "code": "fake-google-code-for-redaction",
    "authorization_code": "fake-authorization-code-for-redaction",
    "state": "fake-oauth-state-for-redaction",
    "nonce": "fake-oauth-nonce-for-redaction",
    "code_verifier": "fake-pkce-verifier-for-redaction",
    "pkce_verifier": "fake-pkce-verifier-alias-for-redaction",
    "id_token": "header.payload.fake-signature",
    "google_id_token": "google.header.payload.fake-signature",
    "access_token": "fake-google-access-token-for-redaction",
    "google_access_token": "fake-google-access-token-alias-for-redaction",
    "refresh_token": "fake-google-refresh-token-for-redaction",
    "google_refresh_token": "fake-google-refresh-token-alias-for-redaction",
    "google_sub": "fake-google-sub-for-redaction",
    "provider_sub": "fake-provider-sub-for-redaction",
    "google_email": "oauth-user@example.test",
    "google_hd": "workspace.example.test",
    "provider_init_token": "fake-provider-init-token-for-redaction",
    "oauth_link_token": "fake-oauth-link-token-for-redaction",
}


def _flatten(value):
    return json.dumps(value, sort_keys=True)


def test_filter_sensitive_data_redacts_all_oauth_top_level_and_nested_fields():
    payload = {
        **SENSITIVE_OAUTH_FIELDS,
        "safe_reason": "state_rejected",
        "nested": {**SENSITIVE_OAUTH_FIELDS},
        "events": [{**SENSITIVE_OAUTH_FIELDS}],
    }

    filtered = APIAuditLogger.filter_sensitive_data(payload)
    serialized = _flatten(filtered)

    for field, raw_value in SENSITIVE_OAUTH_FIELDS.items():
        assert filtered[field] == REDACTED, f"field {field} must be redacted"
        assert raw_value not in serialized, f"raw value for {field} leaked from filtered audit data"
    assert filtered["safe_reason"] == "state_rejected"


def test_error_message_sanitizer_redacts_oauth_query_and_claim_material():
    raw_message = " ".join(f"{field}={value}" for field, value in SENSITIVE_OAUTH_FIELDS.items())

    sanitized = sanitize_error_message(raw_message)

    for field, raw_value in SENSITIVE_OAUTH_FIELDS.items():
        assert raw_value not in sanitized, f"raw OAuth value for {field} leaked in error text"
    assert "oauth" in sanitized.lower() or "[REDACTED]" in sanitized


def test_google_oauth_callback_remains_audited_instead_of_excluded():
    assert APIAuditLogger.should_log_request(
        "/auth/google/callback?code=fake-code-for-redaction&state=fake-state-for-redaction",
        "GET",
    ) is True


def test_google_oauth_callback_tags_identify_authentication_google_oauth_and_external_idp():
    tags = APIAuditLogger.generate_tags("/auth/google/callback", "GET", 400, user_type=None)

    assert "authentication" in tags
    assert "google_oauth" in tags
    assert "external_idp" in tags
    assert "security_event" in tags


def test_google_oauth_callback_client_and_server_failures_are_security_events():
    assert APIAuditLogger.is_security_event("/auth/google/callback", "GET", 400) is True
    assert APIAuditLogger.is_security_event("/auth/google/callback", "GET", 502) is True


def test_filter_headers_redacts_cookie_and_provider_init_authorization_boundaries():
    headers = {
        "Authorization": "Bearer fake-provider-init-bearer-token",
        "Cookie": "oauth_state=fake-oauth-state-for-redaction",
        "X-Provider-Init-Token": "fake-provider-init-token-for-redaction",
        "Content-Type": "application/json",
    }

    filtered = APIAuditLogger.filter_headers(headers)

    assert filtered["Authorization"] == REDACTED
    assert filtered["Cookie"] == REDACTED
    assert filtered["X-Provider-Init-Token"] == REDACTED
    assert filtered["Content-Type"] == "application/json"
