"""RED contract tests for Redis-backed email rate limits and idempotency.

Trace: `.dev/sdd/changes/email-activation/tasks.md` task 1.3.
"""

from __future__ import annotations

import pytest


def _rate_limit_module():
    from src.Util.email import rate_limit

    return rate_limit


def _idempotency_module():
    from src.Util.email import idempotency

    return idempotency


def test_recipient_hourly_bucket_blocks_fourth_send(mock_redis):
    rate_limit = _rate_limit_module()
    limiter = rate_limit.EmailRateLimiter(redis=mock_redis)

    for _ in range(3):
        decision = limiter.check_send_request(
            purpose="email_activation",
            recipient_hash="rh-1",
            user_id="usr-1",
            ip_address="203.0.113.10",
        )
        assert decision.allowed is True

    with pytest.raises(rate_limit.RateLimitExceeded) as exc:
        limiter.check_send_request(
            purpose="email_activation",
            recipient_hash="rh-1",
            user_id="usr-1",
            ip_address="203.0.113.10",
        )

    assert exc.value.bucket == "recipient_hour"
    assert exc.value.retry_after > 0


def test_ip_bucket_blocks_cross_recipient_abuse(mock_redis):
    rate_limit = _rate_limit_module()
    limiter = rate_limit.EmailRateLimiter(redis=mock_redis)

    for idx in range(20):
        assert limiter.check_send_request(
            purpose="password_reset",
            recipient_hash=f"rh-{idx}",
            user_id=None,
            ip_address="198.51.100.7",
        ).allowed

    with pytest.raises(rate_limit.RateLimitExceeded) as exc:
        limiter.check_send_request(
            purpose="password_reset",
            recipient_hash="rh-21",
            user_id=None,
            ip_address="198.51.100.7",
        )

    assert exc.value.bucket == "ip_hour"


def test_lookup_consume_bucket_limits_token_guessing(mock_redis):
    rate_limit = _rate_limit_module()
    limiter = rate_limit.EmailRateLimiter(redis=mock_redis)

    for _ in range(5):
        assert limiter.check_consume_request(
            purpose="email_activation",
            lookup_id="lookupABC123",
            ip_address="203.0.113.20",
        ).allowed

    with pytest.raises(rate_limit.RateLimitExceeded) as exc:
        limiter.check_consume_request(
            purpose="email_activation",
            lookup_id="lookupABC123",
            ip_address="203.0.113.20",
        )

    assert exc.value.bucket == "lookup_hour"


def test_resend_cooldown_returns_retry_after(mock_redis):
    rate_limit = _rate_limit_module()
    limiter = rate_limit.EmailRateLimiter(redis=mock_redis)

    assert limiter.check_resend_cooldown("rh-1", "email_activation").allowed
    limiter.mark_resend_sent("rh-1", "email_activation")

    with pytest.raises(rate_limit.RateLimitExceeded) as exc:
        limiter.check_resend_cooldown("rh-1", "email_activation")

    assert exc.value.bucket == "resend_cooldown"
    assert 0 < exc.value.retry_after <= 60


def test_login_identifier_failure_bucket_blocks_after_ten(mock_redis):
    rate_limit = _rate_limit_module()
    limiter = rate_limit.EmailRateLimiter(redis=mock_redis)

    for _ in range(10):
        limiter.record_login_identifier_failure("203.0.113.30", "person@example.com")

    with pytest.raises(rate_limit.RateLimitExceeded) as exc:
        limiter.check_login_identifier_allowed("203.0.113.30", " person@example.com ")

    assert exc.value.bucket == "login_identifier_15m"


def test_idempotency_key_hash_scope_and_body_binding_are_stable():
    idempotency = _idempotency_module()

    key_hash_a = idempotency.hash_idempotency_key("public-key-1", pepper=b"idem-pepper")
    key_hash_b = idempotency.hash_idempotency_key("public-key-1", pepper=b"idem-pepper")
    request_a = idempotency.request_fingerprint(
        scope="POST /auth/password/forgot",
        user_id=None,
        recipient_hash="rh-1",
        body={"email_or_username": "person@example.com"},
        pepper=b"idem-pepper",
    )
    request_b = idempotency.request_fingerprint(
        scope="POST /auth/password/forgot",
        user_id=None,
        recipient_hash="rh-2",
        body={"email_or_username": "other@example.com"},
        pepper=b"idem-pepper",
    )

    assert isinstance(key_hash_a, bytes)
    assert len(key_hash_a) == 32
    assert key_hash_a == key_hash_b
    assert request_a != request_b
