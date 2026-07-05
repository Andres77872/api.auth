"""Redis-backed rate limits for transactional auth email flows.

Trace:
- SDD `email-activation` task 4.8.
- Spec default limits: recipient/user/IP send buckets, lookup/IP consume
  buckets, resend cooldown, and login identifier failure buckets.

Redis is support infrastructure only. It is never the canonical delivery ledger.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from src.Util.auth_constants import (
    AUTH_CHANGE_PASSWORD_FAILURE_LIMIT,
    AUTH_CHANGE_PASSWORD_FAILURE_WINDOW_SECONDS,
    AUTH_CHANGE_PASSWORD_IP_HOURLY_LIMIT,
    AUTH_CHANGE_PASSWORD_RATE_PREFIX,
    AUTH_CHANGE_PASSWORD_SESSION_HOURLY_LIMIT,
    AUTH_CHANGE_PASSWORD_USER_HOURLY_LIMIT,
    EMAIL_CONSUME_IP_HOURLY_LIMIT,
    EMAIL_CONSUME_LOOKUP_HOURLY_LIMIT,
    EMAIL_COOLDOWN_PREFIX,
    EMAIL_LOGIN_ACCOUNT_FAILURE_LIMIT,
    EMAIL_LOGIN_ACCOUNT_FAILURE_WINDOW_SECONDS,
    EMAIL_LOGIN_IDENTIFIER_FAILURE_LIMIT,
    EMAIL_LOGIN_IDENTIFIER_FAILURE_WINDOW_SECONDS,
    EMAIL_RATE_PREFIX,
    EMAIL_RESEND_COOLDOWN_SECONDS,
    EMAIL_SEND_IP_HOURLY_LIMIT,
    EMAIL_SEND_RECIPIENT_DAILY_LIMIT,
    EMAIL_SEND_RECIPIENT_HOURLY_LIMIT,
    EMAIL_SEND_USER_HOURLY_LIMIT,
)


ONE_HOUR_SECONDS = 60 * 60
ONE_DAY_SECONDS = 24 * ONE_HOUR_SECONDS


class RateLimitExceeded(RuntimeError):
    """Raised when an email-flow bucket exceeds its configured limit."""

    def __init__(self, *, bucket: str, retry_after: int, limit: int, key: str | None = None):
        self.bucket = bucket
        self.retry_after = max(1, int(retry_after or 1))
        self.limit = int(limit)
        self.key = key
        super().__init__(f"rate limit exceeded for {bucket}; retry after {self.retry_after}s")


@dataclass(frozen=True)
class RateLimitPolicy:
    send_recipient_hourly_limit: int = EMAIL_SEND_RECIPIENT_HOURLY_LIMIT
    send_recipient_daily_limit: int = EMAIL_SEND_RECIPIENT_DAILY_LIMIT
    send_user_hourly_limit: int = EMAIL_SEND_USER_HOURLY_LIMIT
    send_ip_hourly_limit: int = EMAIL_SEND_IP_HOURLY_LIMIT
    consume_lookup_hourly_limit: int = EMAIL_CONSUME_LOOKUP_HOURLY_LIMIT
    consume_ip_hourly_limit: int = EMAIL_CONSUME_IP_HOURLY_LIMIT
    resend_cooldown_seconds: int = EMAIL_RESEND_COOLDOWN_SECONDS
    login_identifier_failure_limit: int = EMAIL_LOGIN_IDENTIFIER_FAILURE_LIMIT
    login_identifier_failure_window_seconds: int = EMAIL_LOGIN_IDENTIFIER_FAILURE_WINDOW_SECONDS
    login_account_failure_limit: int = EMAIL_LOGIN_ACCOUNT_FAILURE_LIMIT
    login_account_failure_window_seconds: int = EMAIL_LOGIN_ACCOUNT_FAILURE_WINDOW_SECONDS
    change_password_failure_limit: int = AUTH_CHANGE_PASSWORD_FAILURE_LIMIT
    change_password_failure_window_seconds: int = AUTH_CHANGE_PASSWORD_FAILURE_WINDOW_SECONDS
    change_password_user_hourly_limit: int = AUTH_CHANGE_PASSWORD_USER_HOURLY_LIMIT
    change_password_session_hourly_limit: int = AUTH_CHANGE_PASSWORD_SESSION_HOURLY_LIMIT
    change_password_ip_hourly_limit: int = AUTH_CHANGE_PASSWORD_IP_HOURLY_LIMIT
    fail_closed_on_redis_error: bool = True


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    bucket: str
    retry_after: int = 0
    remaining: int | None = None
    degraded: bool = False


def _default_redis_client():
    from src.Util.db_config import redis_client

    return redis_client


def _digest_part(value: Any) -> str:
    material = str(value if value is not None else "").strip().lower()
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _rate_key(bucket: str, *parts: Any) -> str:
    material = "|".join([bucket, *[str(part if part is not None else "") for part in parts]])
    return f"{EMAIL_RATE_PREFIX}{bucket}:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def _change_password_rate_key(bucket: str, *parts: Any) -> str:
    material = "|".join([bucket, *[str(part if part is not None else "") for part in parts]])
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"{AUTH_CHANGE_PASSWORD_RATE_PREFIX}{bucket}:{digest}"


def _cooldown_key(recipient_hash: str, purpose: str) -> str:
    material = f"{purpose}|{recipient_hash}"
    return f"{EMAIL_COOLDOWN_PREFIX}{purpose}:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


class EmailRateLimiter:
    """Fixed-window Redis rate limiter for email endpoints.

    The implementation uses only non-PII key material. Raw email addresses,
    idempotency keys, token secrets, and full links are never embedded in Redis
    keys.
    """

    def __init__(self, *, redis=None, policy: RateLimitPolicy | None = None) -> None:
        self.redis = redis if redis is not None else _default_redis_client()
        self.policy = policy or RateLimitPolicy()

    def _redis_unavailable(self, bucket: str) -> RateLimitDecision:
        if self.policy.fail_closed_on_redis_error:
            raise RateLimitExceeded(bucket=bucket, retry_after=1, limit=0)
        return RateLimitDecision(allowed=True, bucket=bucket, degraded=True)

    def _ttl(self, key: str, fallback_seconds: int) -> int:
        try:
            ttl = int(self.redis.ttl(key))
        except Exception:
            return max(1, int(fallback_seconds))
        return max(1, ttl if ttl > 0 else int(fallback_seconds))

    def _value_as_int(self, value: Any) -> int:
        if value is None:
            return 0
        if isinstance(value, bytes):
            value = value.decode("ascii", errors="ignore")
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _consume_bucket(self, bucket: str, key: str, *, limit: int, window_seconds: int) -> RateLimitDecision:
        try:
            count = int(self.redis.incr(key))
            if count == 1 or int(self.redis.ttl(key)) < 0:
                self.redis.expire(key, max(1, int(window_seconds)))
        except Exception:
            return self._redis_unavailable(bucket)

        if count > limit:
            raise RateLimitExceeded(
                bucket=bucket,
                retry_after=self._ttl(key, window_seconds),
                limit=limit,
                key=key,
            )
        return RateLimitDecision(allowed=True, bucket=bucket, remaining=max(0, limit - count))

    def check_send_request(
        self,
        *,
        purpose: str,
        recipient_hash: str,
        user_id: str | None,
        ip_address: str,
    ) -> RateLimitDecision:
        """Consume send/resend/forgot/admin-reset buckets."""

        checks = [
            (
                "recipient_hour",
                _rate_key("send:recipient_hour", purpose, recipient_hash),
                self.policy.send_recipient_hourly_limit,
                ONE_HOUR_SECONDS,
            ),
            (
                "recipient_day",
                _rate_key("send:recipient_day", purpose, recipient_hash),
                self.policy.send_recipient_daily_limit,
                ONE_DAY_SECONDS,
            ),
        ]
        if user_id:
            checks.append(
                (
                    "user_hour",
                    _rate_key("send:user_hour", purpose, user_id),
                    self.policy.send_user_hourly_limit,
                    ONE_HOUR_SECONDS,
                )
            )
        checks.append(
            (
                "ip_hour",
                _rate_key("send:ip_hour", purpose, _digest_part(ip_address)),
                self.policy.send_ip_hourly_limit,
                ONE_HOUR_SECONDS,
            )
        )

        remaining: list[int] = []
        degraded = False
        for bucket, key, limit, window in checks:
            decision = self._consume_bucket(bucket, key, limit=limit, window_seconds=window)
            degraded = degraded or decision.degraded
            if decision.remaining is not None:
                remaining.append(decision.remaining)
        return RateLimitDecision(
            allowed=True,
            bucket="send",
            remaining=min(remaining) if remaining else None,
            degraded=degraded,
        )

    def check_consume_request(self, *, purpose: str, lookup_id: str, ip_address: str) -> RateLimitDecision:
        """Consume activation/reset token verification buckets."""

        lookup_decision = self._consume_bucket(
            "lookup_hour",
            _rate_key("consume:lookup_hour", purpose, _digest_part(lookup_id)),
            limit=self.policy.consume_lookup_hourly_limit,
            window_seconds=ONE_HOUR_SECONDS,
        )
        ip_decision = self._consume_bucket(
            "consume_ip_hour",
            _rate_key("consume:ip_hour", purpose, _digest_part(ip_address)),
            limit=self.policy.consume_ip_hourly_limit,
            window_seconds=ONE_HOUR_SECONDS,
        )
        remaining = [value for value in (lookup_decision.remaining, ip_decision.remaining) if value is not None]
        return RateLimitDecision(
            allowed=True,
            bucket="consume",
            remaining=min(remaining) if remaining else None,
            degraded=lookup_decision.degraded or ip_decision.degraded,
        )

    def check_resend_cooldown(self, recipient_hash: str, purpose: str) -> RateLimitDecision:
        key = _cooldown_key(recipient_hash, purpose)
        try:
            ttl = int(self.redis.ttl(key))
            exists = bool(self.redis.get(key))
        except Exception:
            return self._redis_unavailable("resend_cooldown")

        if exists and ttl != -2:
            raise RateLimitExceeded(
                bucket="resend_cooldown",
                retry_after=ttl if ttl > 0 else self.policy.resend_cooldown_seconds,
                limit=1,
                key=key,
            )
        return RateLimitDecision(allowed=True, bucket="resend_cooldown")

    def mark_resend_sent(self, recipient_hash: str, purpose: str) -> bool:
        key = _cooldown_key(recipient_hash, purpose)
        try:
            return bool(self.redis.set(key, "1", ex=max(1, self.policy.resend_cooldown_seconds)))
        except Exception:
            if self.policy.fail_closed_on_redis_error:
                raise RateLimitExceeded(bucket="resend_cooldown", retry_after=1, limit=1)
            return False

    def _login_identifier_key(self, ip_address: str, identifier: str) -> str:
        identifier_digest = _digest_part(str(identifier or "").strip().lower())
        return _rate_key("login_identifier_15m", _digest_part(ip_address), identifier_digest)

    def _login_account_key(self, identifier: str) -> str:
        # Per-account bucket: digests only the identifier (no IP), so rotating
        # source IPs cannot buy a fresh allowance against a single account.
        identifier_digest = _digest_part(str(identifier or "").strip().lower())
        return _rate_key("login_account_15m", identifier_digest)

    def record_login_identifier_failure(self, ip_address: str, identifier: str) -> RateLimitDecision:
        key = self._login_identifier_key(ip_address, identifier)
        decision = self._consume_bucket(
            "login_identifier_15m",
            key,
            limit=max(self.policy.login_identifier_failure_limit, 10**9),
            window_seconds=self.policy.login_identifier_failure_window_seconds,
        )
        # Also advance the per-account bucket. Use a huge limit so incrementing
        # never raises here; enforcement happens in check_login_identifier_allowed.
        self._consume_bucket(
            "login_account_15m",
            self._login_account_key(identifier),
            limit=max(self.policy.login_account_failure_limit, 10**9),
            window_seconds=self.policy.login_account_failure_window_seconds,
        )
        return decision

    def check_login_identifier_allowed(self, ip_address: str, identifier: str) -> RateLimitDecision:
        key = self._login_identifier_key(ip_address, identifier)
        account_key = self._login_account_key(identifier)
        try:
            count = self._value_as_int(self.redis.get(key))
            account_count = self._value_as_int(self.redis.get(account_key))
        except Exception:
            return self._redis_unavailable("login_identifier_15m")
        if count >= self.policy.login_identifier_failure_limit:
            raise RateLimitExceeded(
                bucket="login_identifier_15m",
                retry_after=self._ttl(key, self.policy.login_identifier_failure_window_seconds),
                limit=self.policy.login_identifier_failure_limit,
                key=key,
            )
        if account_count >= self.policy.login_account_failure_limit:
            raise RateLimitExceeded(
                bucket="login_account_15m",
                retry_after=self._ttl(account_key, self.policy.login_account_failure_window_seconds),
                limit=self.policy.login_account_failure_limit,
                key=account_key,
            )
        return RateLimitDecision(
            allowed=True,
            bucket="login_identifier_15m",
            remaining=max(
                0,
                min(
                    self.policy.login_identifier_failure_limit - count,
                    self.policy.login_account_failure_limit - account_count,
                ),
            ),
        )

    def check_change_password_attempt(
        self,
        *,
        user_id: str,
        session_id: str | None,
        ip_address: str,
    ) -> RateLimitDecision:
        """Consume non-PII user/session/IP buckets for change-password attempts."""

        checks = [
            (
                "change_password_user_hour",
                _change_password_rate_key("user_hour", _digest_part(user_id)),
                self.policy.change_password_user_hourly_limit,
                ONE_HOUR_SECONDS,
            ),
            (
                "change_password_ip_hour",
                _change_password_rate_key("ip_hour", _digest_part(ip_address)),
                self.policy.change_password_ip_hourly_limit,
                ONE_HOUR_SECONDS,
            ),
        ]
        if session_id:
            checks.append(
                (
                    "change_password_session_hour",
                    _change_password_rate_key("session_hour", _digest_part(session_id)),
                    self.policy.change_password_session_hourly_limit,
                    ONE_HOUR_SECONDS,
                )
            )

        remaining: list[int] = []
        degraded = False
        for bucket, key, limit, window in checks:
            decision = self._consume_bucket(bucket, key, limit=limit, window_seconds=window)
            degraded = degraded or decision.degraded
            if decision.remaining is not None:
                remaining.append(decision.remaining)
        return RateLimitDecision(
            allowed=True,
            bucket="change_password_attempt",
            remaining=min(remaining) if remaining else None,
            degraded=degraded,
        )

    def record_change_password_failure(self, *, user_id: str, ip_address: str) -> RateLimitDecision:
        """Consume a short failed-current-password bucket without PII in keys."""

        return self._consume_bucket(
            "change_password_failure_15m",
            _change_password_rate_key("failure_15m", _digest_part(user_id), _digest_part(ip_address)),
            limit=self.policy.change_password_failure_limit,
            window_seconds=self.policy.change_password_failure_window_seconds,
        )


__all__ = [
    "EmailRateLimiter",
    "ONE_DAY_SECONDS",
    "ONE_HOUR_SECONDS",
    "RateLimitDecision",
    "RateLimitExceeded",
    "RateLimitPolicy",
]
