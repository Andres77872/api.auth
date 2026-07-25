"""Focused unit coverage for Redis-backed Google OAuth rate limits."""

from __future__ import annotations

import re

import pytest

from src.Util.auth_constants import (
    GOOGLE_OAUTH_CALLBACK_RATE_PREFIX,
    GOOGLE_OAUTH_JWKS_FETCH_RATE_PREFIX,
    GOOGLE_OAUTH_LINK_TOKEN_RATE_PREFIX,
    GOOGLE_OAUTH_PROVIDER_INIT_RATE_PREFIX,
    GOOGLE_OAUTH_START_RATE_PREFIX,
    GOOGLE_OAUTH_STATE_CONSUME_RATE_PREFIX,
    GOOGLE_OAUTH_SUB_COLLISION_RATE_PREFIX,
    GOOGLE_OAUTH_UNLINK_RATE_PREFIX,
)
from src.Util.oauth_rate_limit import (
    OAuthRateLimitExceeded,
    OAuthRateLimitPolicy,
    OAuthRateLimiter,
    load_oauth_rate_limit_policy,
)


RAW_IP = "203.0.113.45"
RAW_PROVIDER_INIT = "provider-init-fingerprint-sensitive"
RAW_STATE = "state-fingerprint-sensitive"
RAW_PROVIDER_SUB = "provider-sub-fingerprint-sensitive"
RAW_LINK_TOKEN = "link-token-fingerprint-sensitive"
RAW_USER_ID = "user-id-sensitive"
RAW_ISSUER = "https://accounts.example.test/issuer-sensitive"


class RecordingRedis:
    def __init__(self, *, fail_operation: str | None = None) -> None:
        self.fail_operation = fail_operation
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.incr_keys: list[str] = []
        self.expire_calls: list[tuple[str, int]] = []

    def _fail_if(self, operation: str) -> None:
        if self.fail_operation == operation:
            raise RuntimeError(f"redis {operation} unavailable")

    def incr(self, key: str) -> int:
        self._fail_if("incr")
        self.incr_keys.append(key)
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def ttl(self, key: str) -> int:
        self._fail_if("ttl")
        return self.ttls.get(key, -1)

    def expire(self, key: str, seconds: int) -> bool:
        self._fail_if("expire")
        self.ttls[key] = int(seconds)
        self.expire_calls.append((key, int(seconds)))
        return True


@pytest.mark.parametrize(
    ("method_name", "kwargs", "bucket", "prefix", "raw_values"),
    [
        (
            "check_start",
            {"ip_address": RAW_IP, "provider_init_fingerprint": RAW_PROVIDER_INIT},
            "start",
            GOOGLE_OAUTH_START_RATE_PREFIX,
            (RAW_IP, RAW_PROVIDER_INIT),
        ),
        (
            "check_callback",
            {"ip_address": RAW_IP, "state_fingerprint": RAW_STATE},
            "callback",
            GOOGLE_OAUTH_CALLBACK_RATE_PREFIX,
            (RAW_IP, RAW_STATE),
        ),
        (
            "check_provider_init_redeem",
            {"ip_address": RAW_IP, "provider_init_fingerprint": RAW_PROVIDER_INIT},
            "provider_init",
            GOOGLE_OAUTH_PROVIDER_INIT_RATE_PREFIX,
            (RAW_IP, RAW_PROVIDER_INIT),
        ),
        (
            "check_state_consumption",
            {"ip_address": RAW_IP, "state_fingerprint": RAW_STATE},
            "state_consume",
            GOOGLE_OAUTH_STATE_CONSUME_RATE_PREFIX,
            (RAW_IP, RAW_STATE),
        ),
        (
            "check_provider_sub_collision",
            {"provider_sub_fingerprint": RAW_PROVIDER_SUB, "ip_address": RAW_IP},
            "sub_collision",
            GOOGLE_OAUTH_SUB_COLLISION_RATE_PREFIX,
            (RAW_PROVIDER_SUB, RAW_IP),
        ),
        (
            "check_link_token_consumption",
            {"ip_address": RAW_IP, "link_token_fingerprint": RAW_LINK_TOKEN},
            "link_token",
            GOOGLE_OAUTH_LINK_TOKEN_RATE_PREFIX,
            (RAW_IP, RAW_LINK_TOKEN),
        ),
        (
            "check_jwks_fetch",
            {"issuer": RAW_ISSUER},
            "jwks_fetch",
            GOOGLE_OAUTH_JWKS_FETCH_RATE_PREFIX,
            (RAW_ISSUER,),
        ),
        (
            "check_unlink_attempt",
            {"user_id": RAW_USER_ID, "ip_address": RAW_IP},
            "unlink",
            GOOGLE_OAUTH_UNLINK_RATE_PREFIX,
            (RAW_USER_ID, RAW_IP),
        ),
    ],
)
def test_each_oauth_bucket_uses_only_prefixed_hash_keys(
    method_name,
    kwargs,
    bucket,
    prefix,
    raw_values,
):
    redis = RecordingRedis()
    limiter = OAuthRateLimiter(redis=redis, policy=OAuthRateLimitPolicy())

    decision = getattr(limiter, method_name)(**kwargs)

    assert decision.allowed is True
    assert decision.bucket == bucket
    assert decision.degraded is False
    assert len(redis.incr_keys) == 1
    key = redis.incr_keys[0]
    assert re.fullmatch(rf"{re.escape(prefix)}[0-9a-f]{{24}}", key)
    for raw_value in raw_values:
        assert raw_value not in key


def test_bucket_exhaustion_reports_live_ttl_and_hashed_key():
    redis = RecordingRedis()
    limiter = OAuthRateLimiter(
        redis=redis,
        policy=OAuthRateLimitPolicy(start_limit=2, start_window_seconds=37),
    )

    first = limiter.check_start(ip_address=RAW_IP, provider_init_fingerprint=RAW_PROVIDER_INIT)
    second = limiter.check_start(ip_address=RAW_IP, provider_init_fingerprint=RAW_PROVIDER_INIT)

    assert first.remaining == 1
    assert second.remaining == 0
    key = redis.incr_keys[-1]
    assert redis.expire_calls == [(key, 37)]
    redis.ttls[key] = 19

    with pytest.raises(OAuthRateLimitExceeded) as exc:
        limiter.check_start(ip_address=RAW_IP, provider_init_fingerprint=RAW_PROVIDER_INIT)

    assert exc.value.bucket == "start"
    assert exc.value.limit == 2
    assert exc.value.retry_after == 19
    assert exc.value.key == key
    assert re.fullmatch(rf"{re.escape(GOOGLE_OAUTH_START_RATE_PREFIX)}[0-9a-f]{{24}}", exc.value.key)
    for secret in (RAW_IP, RAW_PROVIDER_INIT):
        assert secret not in exc.value.key
        assert secret not in str(exc.value)


def test_existing_bucket_without_ttl_gets_window_repaired():
    redis = RecordingRedis()
    limiter = OAuthRateLimiter(
        redis=redis,
        policy=OAuthRateLimitPolicy(callback_limit=5, callback_window_seconds=41),
    )

    limiter.check_callback(ip_address=RAW_IP, state_fingerprint=RAW_STATE)
    key = redis.incr_keys[-1]
    redis.ttls[key] = -1
    limiter.check_callback(ip_address=RAW_IP, state_fingerprint=RAW_STATE)

    assert redis.expire_calls == [(key, 41), (key, 41)]


@pytest.mark.parametrize("fail_operation", ["incr", "expire", "ttl"])
def test_redis_failures_fail_closed_by_default(fail_operation):
    redis = RecordingRedis(fail_operation=fail_operation)
    limiter = OAuthRateLimiter(
        redis=redis,
        policy=OAuthRateLimitPolicy(fail_closed_on_redis_error=True),
    )

    if fail_operation == "ttl":
        redis.counts["unused"] = 1

    with pytest.raises(OAuthRateLimitExceeded) as exc:
        if fail_operation == "ttl":
            limiter.check_start(ip_address=RAW_IP)
            limiter.check_start(ip_address=RAW_IP)
        else:
            limiter.check_start(ip_address=RAW_IP)

    assert exc.value.bucket == "start"
    assert exc.value.retry_after == 1
    assert exc.value.limit == 0
    assert exc.value.key is None


@pytest.mark.parametrize("fail_operation", ["incr", "expire"])
def test_configured_fail_open_returns_explicit_degraded_decision(fail_operation):
    limiter = OAuthRateLimiter(
        redis=RecordingRedis(fail_operation=fail_operation),
        policy=OAuthRateLimitPolicy(fail_closed_on_redis_error=False),
    )

    decision = limiter.check_provider_init_redeem(
        ip_address=RAW_IP,
        provider_init_fingerprint=RAW_PROVIDER_INIT,
    )

    assert decision.allowed is True
    assert decision.bucket == "provider_init"
    assert decision.degraded is True
    assert decision.remaining is None


def test_policy_loader_applies_bucket_values_and_redis_failure_policy():
    policy = load_oauth_rate_limit_policy(
        env={
            "APP_ENV": "test",
            "GOOGLE_OAUTH_SCOPES": "openid email",
            "GOOGLE_OAUTH_FAIL_CLOSED_ON_REDIS_ERROR": "false",
            "GOOGLE_OAUTH_START_RATE_LIMIT": "3",
            "GOOGLE_OAUTH_START_RATE_WINDOW_SECONDS": "17",
            "GOOGLE_OAUTH_CALLBACK_RATE_LIMIT": "4",
            "GOOGLE_OAUTH_CALLBACK_RATE_WINDOW_SECONDS": "19",
            "GOOGLE_OAUTH_PROVIDER_INIT_RATE_LIMIT": "5",
            "GOOGLE_OAUTH_PROVIDER_INIT_RATE_WINDOW_SECONDS": "23",
            "GOOGLE_OAUTH_STATE_CONSUME_RATE_LIMIT": "6",
            "GOOGLE_OAUTH_STATE_CONSUME_RATE_WINDOW_SECONDS": "29",
            "GOOGLE_OAUTH_SUB_COLLISION_RATE_LIMIT": "7",
            "GOOGLE_OAUTH_SUB_COLLISION_RATE_WINDOW_SECONDS": "31",
            "GOOGLE_OAUTH_LINK_TOKEN_RATE_LIMIT": "8",
            "GOOGLE_OAUTH_LINK_TOKEN_RATE_WINDOW_SECONDS": "37",
            "GOOGLE_OAUTH_JWKS_FETCH_RATE_LIMIT": "9",
            "GOOGLE_OAUTH_JWKS_FETCH_RATE_WINDOW_SECONDS": "41",
            "GOOGLE_OAUTH_UNLINK_RATE_LIMIT": "10",
            "GOOGLE_OAUTH_UNLINK_RATE_WINDOW_SECONDS": "43",
        }
    )

    assert policy == OAuthRateLimitPolicy(
        start_limit=3,
        start_window_seconds=17,
        callback_limit=4,
        callback_window_seconds=19,
        provider_init_limit=5,
        provider_init_window_seconds=23,
        state_consume_limit=6,
        state_consume_window_seconds=29,
        sub_collision_limit=7,
        sub_collision_window_seconds=31,
        link_token_limit=8,
        link_token_window_seconds=37,
        jwks_fetch_limit=9,
        jwks_fetch_window_seconds=41,
        unlink_limit=10,
        unlink_window_seconds=43,
        fail_closed_on_redis_error=False,
    )
