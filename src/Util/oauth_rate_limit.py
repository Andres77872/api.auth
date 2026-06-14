"""Redis fixed-window rate limits for Google OAuth abuse controls.

Trace: `.dev/sdd/changes/google-oauth-login/tasks.md` task 6.2.

The implementation mirrors ``EmailRateLimiter``: non-PII bucket keys, Redis
``INCR`` + ``EXPIRE`` fixed windows, and fail-closed behavior by default. Config
is loaded lazily; this module does not import Redis/db_config at import time.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any, Mapping

from src.Util.auth_constants import (
    GOOGLE_OAUTH_CALLBACK_RATE_LIMIT_ENV,
    GOOGLE_OAUTH_CALLBACK_RATE_PREFIX,
    GOOGLE_OAUTH_CALLBACK_RATE_WINDOW_SECONDS_ENV,
    GOOGLE_OAUTH_JWKS_FETCH_RATE_LIMIT_ENV,
    GOOGLE_OAUTH_JWKS_FETCH_RATE_PREFIX,
    GOOGLE_OAUTH_JWKS_FETCH_RATE_WINDOW_SECONDS_ENV,
    GOOGLE_OAUTH_LINK_TOKEN_RATE_LIMIT_ENV,
    GOOGLE_OAUTH_LINK_TOKEN_RATE_PREFIX,
    GOOGLE_OAUTH_LINK_TOKEN_RATE_WINDOW_SECONDS_ENV,
    GOOGLE_OAUTH_PROVIDER_INIT_RATE_LIMIT_ENV,
    GOOGLE_OAUTH_PROVIDER_INIT_RATE_PREFIX,
    GOOGLE_OAUTH_PROVIDER_INIT_RATE_WINDOW_SECONDS_ENV,
    GOOGLE_OAUTH_START_RATE_LIMIT_ENV,
    GOOGLE_OAUTH_START_RATE_PREFIX,
    GOOGLE_OAUTH_START_RATE_WINDOW_SECONDS_ENV,
    GOOGLE_OAUTH_STATE_CONSUME_RATE_LIMIT_ENV,
    GOOGLE_OAUTH_STATE_CONSUME_RATE_PREFIX,
    GOOGLE_OAUTH_STATE_CONSUME_RATE_WINDOW_SECONDS_ENV,
    GOOGLE_OAUTH_SUB_COLLISION_RATE_LIMIT_ENV,
    GOOGLE_OAUTH_SUB_COLLISION_RATE_PREFIX,
    GOOGLE_OAUTH_SUB_COLLISION_RATE_WINDOW_SECONDS_ENV,
    GOOGLE_OAUTH_UNLINK_RATE_LIMIT_ENV,
    GOOGLE_OAUTH_UNLINK_RATE_PREFIX,
    GOOGLE_OAUTH_UNLINK_RATE_WINDOW_SECONDS_ENV,
)
from src.Util.google_oauth_config import load_google_oauth_config


redis_client = None


class OAuthRateLimitExceeded(RuntimeError):
    """Raised when an OAuth bucket exceeds its configured limit."""

    def __init__(self, *, bucket: str, retry_after: int, limit: int, key: str | None = None) -> None:
        self.bucket = bucket
        self.retry_after = max(1, int(retry_after or 1))
        self.limit = int(limit)
        self.key = key
        super().__init__(f"OAuth rate limit exceeded for {bucket}; retry after {self.retry_after}s")


RateLimitExceeded = OAuthRateLimitExceeded


@dataclass(frozen=True)
class OAuthRateLimitDecision:
    allowed: bool
    bucket: str
    retry_after: int = 0
    remaining: int | None = None
    degraded: bool = False


@dataclass(frozen=True)
class OAuthRateLimitPolicy:
    start_limit: int = 20
    start_window_seconds: int = 60
    callback_limit: int = 30
    callback_window_seconds: int = 60
    provider_init_limit: int = 20
    provider_init_window_seconds: int = 60
    state_consume_limit: int = 60
    state_consume_window_seconds: int = 60
    sub_collision_limit: int = 10
    sub_collision_window_seconds: int = 300
    link_token_limit: int = 10
    link_token_window_seconds: int = 300
    jwks_fetch_limit: int = 5
    jwks_fetch_window_seconds: int = 60
    unlink_limit: int = 10
    unlink_window_seconds: int = 300
    fail_closed_on_redis_error: bool = True


def _default_redis_client():
    global redis_client
    if redis_client is not None:
        return redis_client
    from src.Util.db_config import redis_client as configured_redis_client

    redis_client = configured_redis_client
    return configured_redis_client


def _env_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return max(1, int(str(raw).strip()))
    except ValueError:
        return default


def load_oauth_rate_limit_policy(*, env: Mapping[str, str] | None = None) -> OAuthRateLimitPolicy:
    """Load OAuth rate policy from documented env names and feature config."""

    values = env if env is not None else os.environ
    oauth_config = load_google_oauth_config(env=values)
    return OAuthRateLimitPolicy(
        start_limit=_env_int(values, GOOGLE_OAUTH_START_RATE_LIMIT_ENV, 20),
        start_window_seconds=_env_int(values, GOOGLE_OAUTH_START_RATE_WINDOW_SECONDS_ENV, 60),
        callback_limit=_env_int(values, GOOGLE_OAUTH_CALLBACK_RATE_LIMIT_ENV, 30),
        callback_window_seconds=_env_int(values, GOOGLE_OAUTH_CALLBACK_RATE_WINDOW_SECONDS_ENV, 60),
        provider_init_limit=_env_int(values, GOOGLE_OAUTH_PROVIDER_INIT_RATE_LIMIT_ENV, 20),
        provider_init_window_seconds=_env_int(values, GOOGLE_OAUTH_PROVIDER_INIT_RATE_WINDOW_SECONDS_ENV, 60),
        state_consume_limit=_env_int(values, GOOGLE_OAUTH_STATE_CONSUME_RATE_LIMIT_ENV, 60),
        state_consume_window_seconds=_env_int(values, GOOGLE_OAUTH_STATE_CONSUME_RATE_WINDOW_SECONDS_ENV, 60),
        sub_collision_limit=_env_int(values, GOOGLE_OAUTH_SUB_COLLISION_RATE_LIMIT_ENV, 10),
        sub_collision_window_seconds=_env_int(values, GOOGLE_OAUTH_SUB_COLLISION_RATE_WINDOW_SECONDS_ENV, 300),
        link_token_limit=_env_int(values, GOOGLE_OAUTH_LINK_TOKEN_RATE_LIMIT_ENV, 10),
        link_token_window_seconds=_env_int(values, GOOGLE_OAUTH_LINK_TOKEN_RATE_WINDOW_SECONDS_ENV, 300),
        jwks_fetch_limit=_env_int(values, GOOGLE_OAUTH_JWKS_FETCH_RATE_LIMIT_ENV, 5),
        jwks_fetch_window_seconds=_env_int(values, GOOGLE_OAUTH_JWKS_FETCH_RATE_WINDOW_SECONDS_ENV, 60),
        unlink_limit=_env_int(values, GOOGLE_OAUTH_UNLINK_RATE_LIMIT_ENV, 10),
        unlink_window_seconds=_env_int(values, GOOGLE_OAUTH_UNLINK_RATE_WINDOW_SECONDS_ENV, 300),
        fail_closed_on_redis_error=oauth_config.fail_closed_on_redis_error,
    )


def _digest(value: Any) -> str:
    material = str(value if value is not None else "").strip().lower()
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _bucket_key(prefix: str, bucket: str, *parts: Any) -> str:
    material = "|".join([bucket, *[str(part if part is not None else "") for part in parts]])
    return f"{prefix}{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


class OAuthRateLimiter:
    """Fixed-window Redis limiter for OAuth start/callback/provider controls."""

    def __init__(self, *, redis=None, redis_client: Any | None = None, policy: OAuthRateLimitPolicy | None = None) -> None:
        self.redis = redis_client if redis_client is not None else redis if redis is not None else _default_redis_client()
        self.policy = policy or load_oauth_rate_limit_policy()

    def _redis_unavailable(self, bucket: str) -> OAuthRateLimitDecision:
        if self.policy.fail_closed_on_redis_error:
            raise OAuthRateLimitExceeded(bucket=bucket, retry_after=1, limit=0)
        return OAuthRateLimitDecision(allowed=True, bucket=bucket, degraded=True)

    def _ttl(self, key: str, fallback_seconds: int) -> int:
        try:
            ttl = int(self.redis.ttl(key))
        except Exception:
            return max(1, int(fallback_seconds))
        return max(1, ttl if ttl > 0 else int(fallback_seconds))

    def _consume_bucket(self, bucket: str, key: str, *, limit: int, window_seconds: int) -> OAuthRateLimitDecision:
        try:
            count = int(self.redis.incr(key))
            if count == 1 or int(self.redis.ttl(key)) < 0:
                self.redis.expire(key, max(1, int(window_seconds)))
        except Exception:
            return self._redis_unavailable(bucket)
        if count > limit:
            raise OAuthRateLimitExceeded(bucket=bucket, retry_after=self._ttl(key, window_seconds), limit=limit, key=key)
        return OAuthRateLimitDecision(allowed=True, bucket=bucket, remaining=max(0, limit - count))

    def check_start(self, *, ip_address: str, provider_init_fingerprint: str | None = None) -> OAuthRateLimitDecision:
        return self._consume_bucket(
            "start",
            _bucket_key(GOOGLE_OAUTH_START_RATE_PREFIX, "start", _digest(ip_address), provider_init_fingerprint),
            limit=self.policy.start_limit,
            window_seconds=self.policy.start_window_seconds,
        )

    def check_callback(self, *, ip_address: str, state_fingerprint: str | None = None) -> OAuthRateLimitDecision:
        return self._consume_bucket(
            "callback",
            _bucket_key(GOOGLE_OAUTH_CALLBACK_RATE_PREFIX, "callback", _digest(ip_address), state_fingerprint),
            limit=self.policy.callback_limit,
            window_seconds=self.policy.callback_window_seconds,
        )

    def check_provider_init_redeem(self, *, ip_address: str, provider_init_fingerprint: str | None = None) -> OAuthRateLimitDecision:
        return self._consume_bucket(
            "provider_init",
            _bucket_key(GOOGLE_OAUTH_PROVIDER_INIT_RATE_PREFIX, "provider_init", _digest(ip_address), provider_init_fingerprint),
            limit=self.policy.provider_init_limit,
            window_seconds=self.policy.provider_init_window_seconds,
        )

    check_provider_init = check_provider_init_redeem

    def check_state_consumption(self, *, ip_address: str, state_fingerprint: str | None = None) -> OAuthRateLimitDecision:
        return self._consume_bucket(
            "state_consume",
            _bucket_key(GOOGLE_OAUTH_STATE_CONSUME_RATE_PREFIX, "state_consume", _digest(ip_address), state_fingerprint),
            limit=self.policy.state_consume_limit,
            window_seconds=self.policy.state_consume_window_seconds,
        )

    check_state_consume = check_state_consumption

    def check_provider_sub_collision(self, *, provider_sub_fingerprint: str, ip_address: str | None = None) -> OAuthRateLimitDecision:
        return self._consume_bucket(
            "sub_collision",
            _bucket_key(GOOGLE_OAUTH_SUB_COLLISION_RATE_PREFIX, "sub_collision", provider_sub_fingerprint, _digest(ip_address)),
            limit=self.policy.sub_collision_limit,
            window_seconds=self.policy.sub_collision_window_seconds,
        )

    def check_link_token_consumption(self, *, ip_address: str, link_token_fingerprint: str | None = None) -> OAuthRateLimitDecision:
        return self._consume_bucket(
            "link_token",
            _bucket_key(GOOGLE_OAUTH_LINK_TOKEN_RATE_PREFIX, "link_token", _digest(ip_address), link_token_fingerprint),
            limit=self.policy.link_token_limit,
            window_seconds=self.policy.link_token_window_seconds,
        )

    check_link_token_consume = check_link_token_consumption

    def check_jwks_fetch(self, *, issuer: str = "google") -> OAuthRateLimitDecision:
        return self._consume_bucket(
            "jwks_fetch",
            _bucket_key(GOOGLE_OAUTH_JWKS_FETCH_RATE_PREFIX, "jwks_fetch", issuer),
            limit=self.policy.jwks_fetch_limit,
            window_seconds=self.policy.jwks_fetch_window_seconds,
        )

    def check_unlink_attempt(self, *, user_id: str, ip_address: str | None = None) -> OAuthRateLimitDecision:
        return self._consume_bucket(
            "unlink",
            _bucket_key(GOOGLE_OAUTH_UNLINK_RATE_PREFIX, "unlink", _digest(user_id), _digest(ip_address)),
            limit=self.policy.unlink_limit,
            window_seconds=self.policy.unlink_window_seconds,
        )

    check_unlink = check_unlink_attempt


__all__ = [
    "OAuthRateLimitDecision",
    "OAuthRateLimitExceeded",
    "OAuthRateLimitPolicy",
    "OAuthRateLimiter",
    "RateLimitExceeded",
    "load_oauth_rate_limit_policy",
]
