"""Transactional auth email configuration and no-real-send guardrails."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Mapping

from src.Util.auth_constants import (
    APP_ENV_ENV,
    EMAIL_ACTIVATION_TOKEN_TTL_SECONDS_ENV,
    EMAIL_ALLOW_REAL_SEND_IN_TESTS_ENV,
    EMAIL_DELIVERY_ATTEMPT_RETENTION_DAYS_ENV,
    EMAIL_DELIVERY_ENABLED_ENV,
    EMAIL_FROM_ADDRESS_ENV,
    EMAIL_HASH_PEPPER_ENV,
    EMAIL_IDEMPOTENCY_PEPPER_ENV,
    EMAIL_IDEMPOTENCY_TTL_SECONDS_ENV,
    EMAIL_PAYLOAD_KEY_ENV,
    EMAIL_PASSWORD_RESET_TOKEN_TTL_SECONDS_ENV,
    EMAIL_PROVIDER_ENV,
    EMAIL_REPLY_TO_ADDRESS_ENV,
    EMAIL_SENDER_DOMAIN_VERIFIED_ENV,
    EMAIL_TERMINAL_RETENTION_DAYS_ENV,
    EMAIL_TOKEN_PEPPER_ENV,
    EMAIL_WORKER_BACKOFF_SECONDS_ENV,
    EMAIL_WORKER_BATCH_SIZE_ENV,
    EMAIL_RETENTION_PURGE_INTERVAL_SECONDS_ENV,
    EMAIL_WORKER_LEASE_SECONDS_ENV,
    EMAIL_WORKER_MAX_ATTEMPTS_ENV,
    EMAIL_WORKER_POLL_SECONDS_ENV,
    MAILPIT_API_BASE_URL_ENV,
    MAILPIT_SMTP_HOST_ENV,
    MAILPIT_SMTP_PORT_ENV,
    NON_TEST_ENV_NAMES,
    PYTEST_CURRENT_TEST_ENV,
    RESEND_API_KEY_ENV,
    RESEND_WEBHOOK_SECRET_ENV,
    RESEND_WEBHOOK_TOLERANCE_SECONDS_ENV,
    TEST_ENV_NAMES,
)
from src.Util.email.security import validate_payload_key


SAFE_TEST_PROVIDERS = {"fake", "mailpit"}
REAL_SEND_PROVIDERS = {"resend"}


class EmailConfigError(RuntimeError):
    """Raised when email config is invalid or would permit unsafe real sends."""


@dataclass(frozen=True)
class EmailConfig:
    delivery_enabled: bool
    provider: str
    real_send_allowed: bool
    from_address: str
    reply_to_address: str | None
    sender_domain_verified: bool
    resend_api_key: str | None
    resend_webhook_secret: str | None
    resend_webhook_tolerance_seconds: int
    mailpit_smtp_host: str | None
    mailpit_smtp_port: int | None
    mailpit_api_base_url: str | None
    token_pepper: str
    hash_pepper: str
    idempotency_pepper: str
    payload_key: str
    activation_token_ttl_seconds: int
    password_reset_token_ttl_seconds: int
    idempotency_ttl_seconds: int
    terminal_retention_days: int
    delivery_attempt_retention_days: int
    worker_poll_seconds: int
    worker_batch_size: int
    worker_lease_seconds: int
    worker_max_attempts: int
    worker_backoff_seconds: tuple[int, ...]
    app_env: str
    explicit_test_runtime: bool
    retention_purge_interval_seconds: int = 3600

    @property
    def token_pepper_bytes(self) -> bytes:
        return self.token_pepper.encode("utf-8")

    @property
    def hash_pepper_bytes(self) -> bytes:
        return self.hash_pepper.encode("utf-8")

    @property
    def idempotency_pepper_bytes(self) -> bytes:
        return self.idempotency_pepper.encode("utf-8")

    @property
    def is_real_provider(self) -> bool:
        return self.provider in REAL_SEND_PROVIDERS


@dataclass(frozen=True)
class EmailReadiness:
    ready: bool
    status: str
    missing: list[str] = field(default_factory=list)
    provider: str | None = None


def _env(env: Mapping[str, str] | None = None) -> Mapping[str, str]:
    return env if env is not None else os.environ


def _get(env: Mapping[str, str], key: str, default: str = "") -> str:
    value = env.get(key, default)
    return "" if value is None else str(value).strip()


def _bool(value: str | bool | None, *, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = _get(env, key, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise EmailConfigError(f"{key} must be an integer") from exc


def _int_tuple(env: Mapping[str, str], key: str, default: tuple[int, ...]) -> tuple[int, ...]:
    raw = _get(env, key, ",".join(str(item) for item in default))
    if not raw:
        return default
    try:
        return tuple(int(part.strip()) for part in raw.split(",") if part.strip())
    except ValueError as exc:
        raise EmailConfigError(f"{key} must be a comma-separated integer list") from exc


def is_explicit_test_runtime(env: Mapping[str, str] | None = None) -> bool:
    values = _env(env)
    runtime = _get(values, APP_ENV_ENV).lower()
    if runtime in TEST_ENV_NAMES:
        return True
    if runtime in NON_TEST_ENV_NAMES:
        return False
    return bool(_get(values, PYTEST_CURRENT_TEST_ENV)) or "pytest" in sys.modules


def _validate_required_secret(name: str, value: str) -> None:
    if not value:
        raise EmailConfigError(f"{name} is required for transactional auth email")


def _validate_payload_key(key: str) -> None:
    try:
        validate_payload_key(key)
    except Exception as exc:
        raise EmailConfigError(f"{EMAIL_PAYLOAD_KEY_ENV} must be a Fernet URL-safe base64 32-byte key") from exc


def _enforce_no_real_send_guard(config: EmailConfig) -> None:
    if not config.delivery_enabled:
        return
    if not config.explicit_test_runtime:
        return
    if config.provider not in REAL_SEND_PROVIDERS:
        return
    if config.real_send_allowed:
        return
    has_real_credentials = bool(config.resend_api_key)
    if has_real_credentials:
        raise EmailConfigError(
            "real email sends are blocked in test runtime; set "
            f"{EMAIL_ALLOW_REAL_SEND_IN_TESTS_ENV}=true only for deliberate provider smoke tests"
        )


def load_email_config(
    *,
    env: Mapping[str, str] | None = None,
    validate_real_send_guard: bool = True,
) -> EmailConfig:
    """Parse email-related environment variables without sending anything."""

    values = _env(env)
    provider = _get(values, EMAIL_PROVIDER_ENV, "fake").lower() or "fake"
    token_pepper = _get(values, EMAIL_TOKEN_PEPPER_ENV)
    hash_pepper = _get(values, EMAIL_HASH_PEPPER_ENV)
    idempotency_pepper = _get(values, EMAIL_IDEMPOTENCY_PEPPER_ENV)
    payload_key = _get(values, EMAIL_PAYLOAD_KEY_ENV)

    for name, value in (
        (EMAIL_TOKEN_PEPPER_ENV, token_pepper),
        (EMAIL_HASH_PEPPER_ENV, hash_pepper),
        (EMAIL_IDEMPOTENCY_PEPPER_ENV, idempotency_pepper),
        (EMAIL_PAYLOAD_KEY_ENV, payload_key),
    ):
        _validate_required_secret(name, value)
    _validate_payload_key(payload_key)

    mailpit_port_raw = _get(values, MAILPIT_SMTP_PORT_ENV)
    mailpit_port = int(mailpit_port_raw) if mailpit_port_raw else None
    config = EmailConfig(
        delivery_enabled=_bool(_get(values, EMAIL_DELIVERY_ENABLED_ENV), default=False),
        provider=provider,
        real_send_allowed=_bool(_get(values, EMAIL_ALLOW_REAL_SEND_IN_TESTS_ENV), default=False),
        from_address=_get(values, EMAIL_FROM_ADDRESS_ENV),
        reply_to_address=_get(values, EMAIL_REPLY_TO_ADDRESS_ENV) or None,
        sender_domain_verified=_bool(_get(values, EMAIL_SENDER_DOMAIN_VERIFIED_ENV), default=False),
        resend_api_key=_get(values, RESEND_API_KEY_ENV) or None,
        resend_webhook_secret=_get(values, RESEND_WEBHOOK_SECRET_ENV) or None,
        resend_webhook_tolerance_seconds=_int(values, RESEND_WEBHOOK_TOLERANCE_SECONDS_ENV, 300),
        mailpit_smtp_host=_get(values, MAILPIT_SMTP_HOST_ENV) or None,
        mailpit_smtp_port=mailpit_port,
        mailpit_api_base_url=_get(values, MAILPIT_API_BASE_URL_ENV) or None,
        token_pepper=token_pepper,
        hash_pepper=hash_pepper,
        idempotency_pepper=idempotency_pepper,
        payload_key=payload_key,
        activation_token_ttl_seconds=_int(values, EMAIL_ACTIVATION_TOKEN_TTL_SECONDS_ENV, 86_400),
        password_reset_token_ttl_seconds=_int(values, EMAIL_PASSWORD_RESET_TOKEN_TTL_SECONDS_ENV, 3_600),
        idempotency_ttl_seconds=_int(values, EMAIL_IDEMPOTENCY_TTL_SECONDS_ENV, 86_400),
        terminal_retention_days=_int(values, EMAIL_TERMINAL_RETENTION_DAYS_ENV, 30),
        delivery_attempt_retention_days=_int(values, EMAIL_DELIVERY_ATTEMPT_RETENTION_DAYS_ENV, 365),
        worker_poll_seconds=_int(values, EMAIL_WORKER_POLL_SECONDS_ENV, 5),
        worker_batch_size=_int(values, EMAIL_WORKER_BATCH_SIZE_ENV, 25),
        worker_lease_seconds=_int(values, EMAIL_WORKER_LEASE_SECONDS_ENV, 300),
        worker_max_attempts=_int(values, EMAIL_WORKER_MAX_ATTEMPTS_ENV, 8),
        worker_backoff_seconds=_int_tuple(values, EMAIL_WORKER_BACKOFF_SECONDS_ENV, (10, 30, 120, 600, 1800, 3600, 7200, 14400)),
        app_env=_get(values, APP_ENV_ENV),
        explicit_test_runtime=is_explicit_test_runtime(values),
        retention_purge_interval_seconds=_int(values, EMAIL_RETENTION_PURGE_INTERVAL_SECONDS_ENV, 3600),
    )
    if validate_real_send_guard:
        _enforce_no_real_send_guard(config)
    return config


def validate_email_readiness(config: EmailConfig) -> EmailReadiness:
    """Return provider readiness without contacting an external provider."""

    if not config.delivery_enabled:
        return EmailReadiness(ready=False, status="disabled", provider=config.provider)

    missing: list[str] = []
    if not config.from_address:
        missing.append(EMAIL_FROM_ADDRESS_ENV)

    if config.provider == "resend":
        if not config.resend_api_key:
            missing.append(RESEND_API_KEY_ENV)
        if not config.resend_webhook_secret:
            missing.append(RESEND_WEBHOOK_SECRET_ENV)
        if config.app_env.lower() in {"prod", "production"} and not config.sender_domain_verified:
            missing.append(EMAIL_SENDER_DOMAIN_VERIFIED_ENV)
    elif config.provider == "mailpit":
        if not config.mailpit_smtp_host:
            missing.append(MAILPIT_SMTP_HOST_ENV)
        if not config.mailpit_smtp_port:
            missing.append(MAILPIT_SMTP_PORT_ENV)
    elif config.provider != "fake":
        missing.append(EMAIL_PROVIDER_ENV)

    if missing:
        return EmailReadiness(ready=False, status="not_ready", missing=missing, provider=config.provider)
    return EmailReadiness(ready=True, status="ready", provider=config.provider)
