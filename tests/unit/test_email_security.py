"""RED contract tests for email identity, link-token, and payload security.

Trace:
- `.dev/sdd/changes/email-activation/spec.md` requirements for authoritative
  normalized emails, hash-only link tokens, purpose separation, expiry, dummy
  not-found timing, and encrypted transient render payloads.
- `.dev/sdd/changes/email-activation/tasks.md` task 1.1.

These tests intentionally target modules that do not exist yet. They are the
RED proof for Phase 1 before production implementation starts.
"""

from __future__ import annotations

import base64
import hmac
import os
from datetime import datetime, timedelta, timezone

import pytest


TOKEN_PEPPER = b"unit-email-token-pepper"
EMAIL_PEPPER = b"unit-email-hash-pepper"
PAYLOAD_KEY = base64.urlsafe_b64encode(b"1" * 32).decode("ascii")


def _security_module():
    from src.Util.email import security

    return security


def test_email_normalization_uses_lower_trim_only():
    security = _security_module()

    assert security.normalize_email("  A.User+Tag@Example.COM  ") == "a.user+tag@example.com"


def test_mask_email_never_returns_plaintext_full_address():
    security = _security_module()

    masked = security.mask_email("person@example.com")

    assert masked != "person@example.com"
    assert "person" not in masked
    assert masked.endswith("@example.com")


def test_email_hash_is_hmac_sha256_over_normalized_email():
    security = _security_module()

    first = security.hash_email(" Person@Example.COM ", pepper=EMAIL_PEPPER)
    second = security.hash_email("person@example.com", pepper=EMAIL_PEPPER)
    different = security.hash_email("other@example.com", pepper=EMAIL_PEPPER)

    assert isinstance(first, bytes)
    assert len(first) == 32
    assert first == second
    assert first != different


def test_split_link_token_generation_is_hash_only_and_url_safe():
    security = _security_module()

    generated = security.generate_link_token(
        purpose="email_activation",
        ttl_seconds=24 * 60 * 60,
        pepper=TOKEN_PEPPER,
        now=datetime(2026, 6, 13, tzinfo=timezone.utc),
    )

    assert generated.token == f"{generated.lookup_id}.{generated.secret}"
    assert 12 <= len(generated.lookup_id) <= 16
    assert len(generated.secret) >= 43
    assert isinstance(generated.token_hash, bytes)
    assert len(generated.token_hash) == 32
    assert generated.secret.encode("utf-8") not in generated.token_hash
    assert len(generated.token_fingerprint) == 12
    assert generated.expires_at == datetime(2026, 6, 14, tzinfo=timezone.utc)


def test_link_token_hash_material_includes_purpose_lookup_and_secret():
    security = _security_module()
    lookup_id = "lookupABC123"
    secret = "s" * 43

    expected = hmac.digest(
        TOKEN_PEPPER,
        f"v1:email_activation:{lookup_id}:{secret}".encode("utf-8"),
        "sha256",
    )

    assert (
        security.hash_link_token(
            purpose="email_activation",
            lookup_id=lookup_id,
            secret=secret,
            pepper=TOKEN_PEPPER,
        )
        == expected
    )


def test_link_token_verification_enforces_purpose_and_expiry():
    security = _security_module()
    generated = security.generate_link_token(
        purpose="email_activation",
        ttl_seconds=3600,
        pepper=TOKEN_PEPPER,
        now=datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc),
    )

    assert security.verify_link_token(
        token=generated.token,
        purpose="email_activation",
        expected_hash=generated.token_hash,
        expires_at=generated.expires_at,
        pepper=TOKEN_PEPPER,
        now=datetime(2026, 6, 13, 12, 30, tzinfo=timezone.utc),
    ) is True

    assert security.verify_link_token(
        token=generated.token,
        purpose="password_reset",
        expected_hash=generated.token_hash,
        expires_at=generated.expires_at,
        pepper=TOKEN_PEPPER,
        now=datetime(2026, 6, 13, 12, 30, tzinfo=timezone.utc),
    ) is False

    assert security.verify_link_token(
        token=generated.token,
        purpose="email_activation",
        expected_hash=generated.token_hash,
        expires_at=generated.expires_at,
        pepper=TOKEN_PEPPER,
        now=generated.expires_at + timedelta(seconds=1),
    ) is False


def test_dummy_verification_path_still_uses_constant_time_compare(monkeypatch):
    security = _security_module()
    calls = []

    def fake_compare(left, right):
        calls.append((left, right))
        return False

    monkeypatch.setattr(hmac, "compare_digest", fake_compare)

    assert security.verify_link_token(
        token="malformed",
        purpose="email_activation",
        expected_hash=b"\x00" * 32,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        pepper=TOKEN_PEPPER,
        now=datetime.now(timezone.utc),
    ) is False
    assert calls, "malformed/not-found paths must still call hmac.compare_digest"


def test_render_payload_encrypts_round_trips_and_purges_terminal_payload():
    security = _security_module()
    payload = {
        "activation_link": "https://client.example/auth/email/verify?token=lookup.secret",
        "recipient_email": "person@example.com",
    }

    ciphertext = security.encrypt_render_payload(payload, key=PAYLOAD_KEY)
    assert isinstance(ciphertext, bytes)
    assert b"lookup.secret" not in ciphertext
    assert b"person@example.com" not in ciphertext

    assert security.decrypt_render_payload(ciphertext, key=PAYLOAD_KEY) == payload

    purged = security.purge_render_payload_if_due(
        {
            "status": "sent",
            "render_payload_ciphertext": ciphertext,
            "payload_purge_at": datetime(2026, 6, 13, tzinfo=timezone.utc),
        },
        now=datetime(2026, 6, 14, tzinfo=timezone.utc),
    )
    assert purged["render_payload_ciphertext"] is None


@pytest.mark.parametrize(
    "value",
    ["token=lookup.secret", "person@example.com", "Idempotency-Key: abc", "reset_link=https://x"],
)
def test_sanitize_email_log_value_redacts_links_tokens_email_and_idempotency(value):
    security = _security_module()

    redacted = security.sanitize_email_log_value(value)

    assert "lookup.secret" not in redacted
    assert "person@example.com" not in redacted
    assert "abc" not in redacted
    assert "https://x" not in redacted
