"""Redis fixed-window rate limits for Patreon account-link primitives.

Trace: `.dev/sdd/changes/patreon-account-link/tasks.md` task 3.5.

Patreon Redis keys are intentionally privacy-minimized: bucket keys contain only
static namespace prefixes plus SHA-256 digests. Raw IPs, user IDs, emails,
campaign IDs, tier IDs, member IDs, proof lookup IDs, tokens, signatures, and
fingerprints must never be embedded in Redis key names.

The module loads Redis lazily so importing Patreon utilities does not create a
Redis connection or read provider secrets at import time.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any, Mapping

from src.Util.auth_constants import (
    PATREON_RATE_LIMIT_DEFAULTS,
    PATREON_RATE_LIMIT_ENV_NAMES,
    PATREON_REDIS_RATE_PREFIXES,
)


redis_client = None

_PATREON_RATE_BUCKETS = (
    "link_request",
    "proof_request",
    "proof_consume",
    "unlink",
    "status",
    "s2s",
    "webhook_signature_failure",
    "sync_enqueue",
)
_KEY_DIGEST_HEX_LENGTH = 32


class PatreonRateLimitExceeded(RuntimeError):
    """Raised when a Patreon bucket exceeds its configured limit."""

    def __init__(self, *, bucket: str, retry_after: int, limit: int, key: str | None = None) -> None:
        self.bucket = bucket
        self.retry_after = max(1, int(retry_after or 1))
        self.limit = int(limit)
        # ``key`` is safe to retain for internal diagnostics because it is a
        # hashed Redis key, never raw identifier material.
        self.key = key
        super().__init__(f"Patreon rate limit exceeded for {bucket}; retry after {self.retry_after}s")


RateLimitExceeded = PatreonRateLimitExceeded


@dataclass(frozen=True)
class PatreonRateLimitDecision:
    allowed: bool
    bucket: str
    retry_after: int = 0
    remaining: int | None = None
    degraded: bool = False


@dataclass(frozen=True)
class PatreonRateLimitPolicy:
    link_request_limit: int = int(PATREON_RATE_LIMIT_DEFAULTS["link_request"][0])
    link_request_window_seconds: int = int(PATREON_RATE_LIMIT_DEFAULTS["link_request"][1])
    proof_request_limit: int = int(PATREON_RATE_LIMIT_DEFAULTS["proof_request"][0])
    proof_request_window_seconds: int = int(PATREON_RATE_LIMIT_DEFAULTS["proof_request"][1])
    proof_consume_limit: int = int(PATREON_RATE_LIMIT_DEFAULTS["proof_consume"][0])
    proof_consume_window_seconds: int = int(PATREON_RATE_LIMIT_DEFAULTS["proof_consume"][1])
    unlink_limit: int = int(PATREON_RATE_LIMIT_DEFAULTS["unlink"][0])
    unlink_window_seconds: int = int(PATREON_RATE_LIMIT_DEFAULTS["unlink"][1])
    status_limit: int = int(PATREON_RATE_LIMIT_DEFAULTS["status"][0])
    status_window_seconds: int = int(PATREON_RATE_LIMIT_DEFAULTS["status"][1])
    s2s_limit: int = int(PATREON_RATE_LIMIT_DEFAULTS["s2s"][0])
    s2s_window_seconds: int = int(PATREON_RATE_LIMIT_DEFAULTS["s2s"][1])
    webhook_signature_failure_limit: int = int(PATREON_RATE_LIMIT_DEFAULTS["webhook_signature_failure"][0])
    webhook_signature_failure_window_seconds: int = int(PATREON_RATE_LIMIT_DEFAULTS["webhook_signature_failure"][1])
    sync_enqueue_limit: int = int(PATREON_RATE_LIMIT_DEFAULTS["sync_enqueue"][0])
    sync_enqueue_window_seconds: int = int(PATREON_RATE_LIMIT_DEFAULTS["sync_enqueue"][1])
    fail_closed_on_redis_error: bool = True

    def bucket_limit(self, bucket: str) -> int:
        return int(getattr(self, f"{bucket}_limit"))

    def bucket_window_seconds(self, bucket: str) -> int:
        return int(getattr(self, f"{bucket}_window_seconds"))


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


def _configured_bucket(env: Mapping[str, str], bucket: str) -> tuple[int, int]:
    limit_env, window_env = PATREON_RATE_LIMIT_ENV_NAMES[bucket]
    default_limit, default_window = PATREON_RATE_LIMIT_DEFAULTS[bucket]
    return (
        _env_int(env, limit_env, int(default_limit)),
        _env_int(env, window_env, int(default_window)),
    )


def load_patreon_rate_limit_policy(*, env: Mapping[str, str] | None = None) -> PatreonRateLimitPolicy:
    """Load Patreon rate-limit policy from the documented env names."""

    values = env if env is not None else os.environ
    link_request = _configured_bucket(values, "link_request")
    proof_request = _configured_bucket(values, "proof_request")
    proof_consume = _configured_bucket(values, "proof_consume")
    unlink = _configured_bucket(values, "unlink")
    status = _configured_bucket(values, "status")
    s2s = _configured_bucket(values, "s2s")
    webhook_signature_failure = _configured_bucket(values, "webhook_signature_failure")
    sync_enqueue = _configured_bucket(values, "sync_enqueue")

    return PatreonRateLimitPolicy(
        link_request_limit=link_request[0],
        link_request_window_seconds=link_request[1],
        proof_request_limit=proof_request[0],
        proof_request_window_seconds=proof_request[1],
        proof_consume_limit=proof_consume[0],
        proof_consume_window_seconds=proof_consume[1],
        unlink_limit=unlink[0],
        unlink_window_seconds=unlink[1],
        status_limit=status[0],
        status_window_seconds=status[1],
        s2s_limit=s2s[0],
        s2s_window_seconds=s2s[1],
        webhook_signature_failure_limit=webhook_signature_failure[0],
        webhook_signature_failure_window_seconds=webhook_signature_failure[1],
        sync_enqueue_limit=sync_enqueue[0],
        sync_enqueue_window_seconds=sync_enqueue[1],
    )


def hash_identifier(value: Any) -> str:
    """Return a normalized SHA-256 hex digest for Redis bucket material."""

    material = str(value if value is not None else "").strip().lower()
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _bucket_key(prefix: str, bucket: str, *parts: Any) -> str:
    """Build a Redis key from static prefix plus digest-only identifier material."""

    hashed_parts = [hash_identifier(part) for part in parts]
    material = "|".join([bucket, *hashed_parts])
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:_KEY_DIGEST_HEX_LENGTH]
    return f"{prefix}{digest}"


class PatreonRateLimiter:
    """Fixed-window Redis limiter for Patreon link/proof/S2S/webhook controls."""

    def __init__(self, *, redis=None, redis_client: Any | None = None, policy: PatreonRateLimitPolicy | None = None) -> None:
        self.redis = redis_client if redis_client is not None else redis if redis is not None else _default_redis_client()
        self.policy = policy or load_patreon_rate_limit_policy()

    def _redis_unavailable(self, bucket: str) -> PatreonRateLimitDecision:
        if self.policy.fail_closed_on_redis_error:
            raise PatreonRateLimitExceeded(bucket=bucket, retry_after=1, limit=0)
        return PatreonRateLimitDecision(allowed=True, bucket=bucket, degraded=True)

    def _ttl(self, key: str, fallback_seconds: int) -> int:
        try:
            ttl = int(self.redis.ttl(key))
        except Exception:
            return max(1, int(fallback_seconds))
        return max(1, ttl if ttl > 0 else int(fallback_seconds))

    def _consume_bucket(self, bucket: str, key: str) -> PatreonRateLimitDecision:
        limit = self.policy.bucket_limit(bucket)
        window_seconds = self.policy.bucket_window_seconds(bucket)
        try:
            count = int(self.redis.incr(key))
            if count == 1 or int(self.redis.ttl(key)) < 0:
                self.redis.expire(key, max(1, int(window_seconds)))
        except Exception:
            return self._redis_unavailable(bucket)

        if count > limit:
            raise PatreonRateLimitExceeded(
                bucket=bucket,
                retry_after=self._ttl(key, window_seconds),
                limit=limit,
                key=key,
            )
        return PatreonRateLimitDecision(allowed=True, bucket=bucket, remaining=max(0, limit - count))

    def _check(self, bucket: str, *parts: Any) -> PatreonRateLimitDecision:
        if bucket not in _PATREON_RATE_BUCKETS:
            raise ValueError(f"Unsupported Patreon rate-limit bucket: {bucket}")
        key = _bucket_key(PATREON_REDIS_RATE_PREFIXES[bucket], bucket, *parts)
        return self._consume_bucket(bucket, key)

    def check_link_request(
        self,
        *,
        user_id: str | None,
        ip_address: str | None,
        email_hint: str | None = None,
        request_scope: str | None = None,
    ) -> PatreonRateLimitDecision:
        """Consume the authenticated Patreon link-request bucket."""

        return self._check("link_request", user_id, ip_address, email_hint, request_scope)

    check_link = check_link_request

    def check_proof_request(
        self,
        *,
        user_id: str | None,
        ip_address: str | None,
        proof_email_hash: str | None = None,
        pending_link_id: str | None = None,
    ) -> PatreonRateLimitDecision:
        """Consume proof-send/request abuse controls."""

        return self._check("proof_request", user_id, ip_address, proof_email_hash, pending_link_id)

    check_proof_send = check_proof_request
    check_proof = check_proof_request

    def check_proof_consume(
        self,
        *,
        ip_address: str | None,
        lookup_id: str | None = None,
        proof_token_fingerprint: str | None = None,
        pending_link_id: str | None = None,
    ) -> PatreonRateLimitDecision:
        """Consume invalid/valid proof-token submission controls."""

        return self._check("proof_consume", ip_address, lookup_id, proof_token_fingerprint, pending_link_id)

    check_proof_confirmation = check_proof_consume
    check_proof_confirm = check_proof_consume

    def check_unlink(
        self,
        *,
        user_id: str | None,
        ip_address: str | None,
    ) -> PatreonRateLimitDecision:
        """Consume Patreon unlink/relink lifecycle controls."""

        return self._check("unlink", user_id, ip_address)

    check_unlink_attempt = check_unlink

    def check_status(
        self,
        *,
        user_id: str | None,
        ip_address: str | None = None,
    ) -> PatreonRateLimitDecision:
        """Consume browser-owned safe link-status read controls."""

        return self._check("status", user_id, ip_address)

    check_status_read = check_status

    def check_s2s(
        self,
        *,
        user_hash: str | None,
        client_id: str | None = None,
        ip_address: str | None = None,
    ) -> PatreonRateLimitDecision:
        """Consume dedicated internal S2S entitlement read controls."""

        return self._check("s2s", user_hash, client_id, ip_address)

    check_s2s_read = check_s2s
    check_s2s_entitlement_read = check_s2s

    def check_webhook_signature_failure(
        self,
        *,
        ip_address: str | None,
        event_type: str | None = None,
        signature_digest: str | None = None,
    ) -> PatreonRateLimitDecision:
        """Consume invalid webhook-signature failure controls."""

        return self._check("webhook_signature_failure", ip_address, event_type, signature_digest)

    record_webhook_signature_failure = check_webhook_signature_failure

    def check_sync_enqueue(
        self,
        *,
        kind: str,
        campaign_hash: str | None = None,
        member_hash: str | None = None,
        user_id: str | None = None,
        source: str | None = None,
    ) -> PatreonRateLimitDecision:
        """Consume manual/webhook-triggered sync enqueue controls."""

        return self._check("sync_enqueue", kind, campaign_hash, member_hash, user_id, source)

    check_sync_job_enqueue = check_sync_enqueue


__all__ = [
    "PatreonRateLimitDecision",
    "PatreonRateLimitExceeded",
    "PatreonRateLimitPolicy",
    "PatreonRateLimiter",
    "RateLimitExceeded",
    "hash_identifier",
    "load_patreon_rate_limit_policy",
]
