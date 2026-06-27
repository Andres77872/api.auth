"""Redis fixed-window rate limits for Stripe billing adapter operations.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 6.4.

Bucket keys contain only static prefixes plus SHA-256 digests. Raw Stripe IDs,
webhook signatures, secrets, and idempotency keys are never embedded in Redis
keys.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any, Mapping

from src.Util import auth_constants as constants


redis_client = None
_KEY_DIGEST_HEX_LENGTH = 32

_STRIPE_RATE_BUCKETS = (
    "s2s",
    "checkout",
    "portal",
    "resync",
    "webhook_signature_failure",
    "webhook_replay",
    "sync_retry",
)


class StripeRateLimitExceeded(RuntimeError):
    """Raised when a Stripe/billing bucket exceeds its configured limit."""

    def __init__(self, *, bucket: str, retry_after: int, limit: int, key: str | None = None) -> None:
        self.bucket = bucket
        self.retry_after = max(1, int(retry_after or 1))
        self.limit = int(limit)
        self.key = key
        super().__init__(f"Billing rate limit exceeded for {bucket}; retry after {self.retry_after}s")


RateLimitExceeded = StripeRateLimitExceeded


@dataclass(frozen=True)
class StripeRateLimitDecision:
    allowed: bool
    bucket: str
    retry_after: int = 0
    remaining: int | None = None
    degraded: bool = False


@dataclass(frozen=True)
class StripeRateLimitPolicy:
    s2s_limit: int = int(constants.BILLING_RATE_LIMIT_DEFAULTS["s2s"][0])
    s2s_window_seconds: int = int(constants.BILLING_RATE_LIMIT_DEFAULTS["s2s"][1])
    checkout_limit: int = int(constants.BILLING_RATE_LIMIT_DEFAULTS["checkout"][0])
    checkout_window_seconds: int = int(constants.BILLING_RATE_LIMIT_DEFAULTS["checkout"][1])
    portal_limit: int = int(constants.BILLING_RATE_LIMIT_DEFAULTS["portal"][0])
    portal_window_seconds: int = int(constants.BILLING_RATE_LIMIT_DEFAULTS["portal"][1])
    resync_limit: int = int(constants.BILLING_RATE_LIMIT_DEFAULTS["resync"][0])
    resync_window_seconds: int = int(constants.BILLING_RATE_LIMIT_DEFAULTS["resync"][1])
    webhook_signature_failure_limit: int = int(constants.BILLING_RATE_LIMIT_DEFAULTS["stripe_webhook_signature_failure"][0])
    webhook_signature_failure_window_seconds: int = int(constants.BILLING_RATE_LIMIT_DEFAULTS["stripe_webhook_signature_failure"][1])
    webhook_replay_limit: int = 120
    webhook_replay_window_seconds: int = 60
    sync_retry_limit: int = 30
    sync_retry_window_seconds: int = 300
    fail_closed_on_redis_error: bool = True

    def bucket_limit(self, bucket: str) -> int:
        return int(getattr(self, f"{bucket}_limit"))

    def bucket_window_seconds(self, bucket: str) -> int:
        return int(getattr(self, f"{bucket}_window_seconds"))


_BUCKET_ENV_NAMES = {
    "s2s": constants.BILLING_RATE_LIMIT_ENV_NAMES["s2s"],
    "checkout": constants.BILLING_RATE_LIMIT_ENV_NAMES["checkout"],
    "portal": constants.BILLING_RATE_LIMIT_ENV_NAMES["portal"],
    "resync": constants.BILLING_RATE_LIMIT_ENV_NAMES["resync"],
    "webhook_signature_failure": constants.BILLING_RATE_LIMIT_ENV_NAMES["stripe_webhook_signature_failure"],
}
_BUCKET_PREFIXES = {
    "s2s": constants.BILLING_S2S_RATE_PREFIX,
    "checkout": constants.BILLING_CHECKOUT_RATE_PREFIX,
    "portal": constants.BILLING_PORTAL_RATE_PREFIX,
    "resync": constants.BILLING_RESYNC_RATE_PREFIX,
    "webhook_signature_failure": constants.STRIPE_WEBHOOK_SIGNATURE_FAILURE_RATE_PREFIX,
    "webhook_replay": constants.STRIPE_WEBHOOK_REPLAY_RATE_PREFIX,
    "sync_retry": constants.STRIPE_SYNC_RATE_PREFIX,
}


def _default_redis_client():
    if redis_client is not None:
        return redis_client
    from src.Util.db_config import redis_client as configured_redis_client

    return configured_redis_client


def _env_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or str(raw).strip() == "":
        return max(1, int(default))
    try:
        return max(1, int(str(raw).strip()))
    except (TypeError, ValueError):
        return max(1, int(default))


def _configured_bucket(env: Mapping[str, str], bucket: str, default_limit: int, default_window: int) -> tuple[int, int]:
    names = _BUCKET_ENV_NAMES.get(bucket)
    if not names:
        return default_limit, default_window
    limit_env, window_env = names
    return _env_int(env, limit_env, default_limit), _env_int(env, window_env, default_window)


def load_stripe_rate_limit_policy(*, env: Mapping[str, str] | None = None) -> StripeRateLimitPolicy:
    values = env if env is not None else os.environ
    defaults = StripeRateLimitPolicy()
    s2s = _configured_bucket(values, "s2s", defaults.s2s_limit, defaults.s2s_window_seconds)
    checkout = _configured_bucket(values, "checkout", defaults.checkout_limit, defaults.checkout_window_seconds)
    portal = _configured_bucket(values, "portal", defaults.portal_limit, defaults.portal_window_seconds)
    resync = _configured_bucket(values, "resync", defaults.resync_limit, defaults.resync_window_seconds)
    signature = _configured_bucket(
        values,
        "webhook_signature_failure",
        defaults.webhook_signature_failure_limit,
        defaults.webhook_signature_failure_window_seconds,
    )
    return StripeRateLimitPolicy(
        s2s_limit=s2s[0],
        s2s_window_seconds=s2s[1],
        checkout_limit=checkout[0],
        checkout_window_seconds=checkout[1],
        portal_limit=portal[0],
        portal_window_seconds=portal[1],
        resync_limit=resync[0],
        resync_window_seconds=resync[1],
        webhook_signature_failure_limit=signature[0],
        webhook_signature_failure_window_seconds=signature[1],
    )


def hash_identifier(value: Any) -> str:
    material = str(value if value is not None else "").strip().lower()
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _bucket_key(prefix: str, bucket: str, *parts: Any) -> str:
    hashed_parts = [hash_identifier(part) for part in parts]
    material = "|".join([bucket, *hashed_parts])
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:_KEY_DIGEST_HEX_LENGTH]
    return f"{prefix}{digest}"


class StripeRateLimiter:
    """Fixed-window Redis limiter for billing S2S and Stripe adapter controls."""

    def __init__(self, *, redis=None, redis_client: Any | None = None, policy: StripeRateLimitPolicy | None = None) -> None:
        self.redis = redis_client if redis_client is not None else redis if redis is not None else _default_redis_client()
        self.policy = policy or load_stripe_rate_limit_policy()

    def _redis_unavailable(self, bucket: str) -> StripeRateLimitDecision:
        if self.policy.fail_closed_on_redis_error:
            raise StripeRateLimitExceeded(bucket=bucket, retry_after=1, limit=0)
        return StripeRateLimitDecision(allowed=True, bucket=bucket, degraded=True)

    def _ttl(self, key: str, fallback_seconds: int) -> int:
        try:
            ttl = int(self.redis.ttl(key))
        except Exception:
            return max(1, int(fallback_seconds))
        return max(1, ttl if ttl > 0 else int(fallback_seconds))

    def _consume_bucket(self, bucket: str, key: str) -> StripeRateLimitDecision:
        limit = self.policy.bucket_limit(bucket)
        window_seconds = self.policy.bucket_window_seconds(bucket)
        try:
            count = int(self.redis.incr(key))
            if count == 1 or int(self.redis.ttl(key)) < 0:
                self.redis.expire(key, max(1, int(window_seconds)))
        except Exception:
            return self._redis_unavailable(bucket)
        if count > limit:
            raise StripeRateLimitExceeded(bucket=bucket, retry_after=self._ttl(key, window_seconds), limit=limit, key=key)
        return StripeRateLimitDecision(allowed=True, bucket=bucket, remaining=max(0, limit - count))

    def _check(self, bucket: str, *parts: Any) -> StripeRateLimitDecision:
        if bucket not in _STRIPE_RATE_BUCKETS:
            raise ValueError(f"Unsupported Stripe rate-limit bucket: {bucket}")
        return self._consume_bucket(bucket, _bucket_key(_BUCKET_PREFIXES[bucket], bucket, *parts))

    def check_s2s(self, *, user_hash: str | None, project_hash: str | None = None, client_id: str | None = None, ip_address: str | None = None) -> StripeRateLimitDecision:
        return self._check("s2s", user_hash, project_hash, client_id, ip_address)

    check_s2s_read = check_s2s

    def check_checkout(self, *, user_hash: str | None, project_hash: str | None, client_intent_ref: str | None = None, ip_address: str | None = None) -> StripeRateLimitDecision:
        return self._check("checkout", user_hash, project_hash, client_intent_ref, ip_address)

    def check_portal(self, *, user_hash: str | None, project_hash: str | None, ip_address: str | None = None) -> StripeRateLimitDecision:
        return self._check("portal", user_hash, project_hash, ip_address)

    def check_resync(self, *, user_hash: str | None, project_hash: str | None, reason: str | None = None, ip_address: str | None = None) -> StripeRateLimitDecision:
        return self._check("resync", user_hash, project_hash, reason, ip_address)

    def check_webhook_signature_failure(self, *, ip_address: str | None, event_type: str | None = None, signature_digest: str | None = None) -> StripeRateLimitDecision:
        return self._check("webhook_signature_failure", ip_address, event_type, signature_digest)

    record_webhook_signature_failure = check_webhook_signature_failure

    def check_webhook_replay(self, *, event_fingerprint: str | None, ip_address: str | None = None) -> StripeRateLimitDecision:
        return self._check("webhook_replay", event_fingerprint, ip_address)

    def check_sync_retry(self, *, job_type: str | None, job_ref: str | None = None, reason: str | None = None) -> StripeRateLimitDecision:
        return self._check("sync_retry", job_type, job_ref, reason)


__all__ = [
    "RateLimitExceeded",
    "StripeRateLimitDecision",
    "StripeRateLimitExceeded",
    "StripeRateLimitPolicy",
    "StripeRateLimiter",
    "hash_identifier",
    "load_stripe_rate_limit_policy",
]
