"""Generic billing configuration and readiness helpers.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 4.3.

This module parses configuration only when explicitly called. Importing it has no
environment reads with side effects and never contacts providers, Redis, or the
database.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


BILLING_ENABLED_ENV = "BILLING_ENABLED"
BILLING_S2S_ENABLED_ENV = "BILLING_S2S_ENABLED"
BILLING_CHECKOUT_ENABLED_ENV = "BILLING_CHECKOUT_ENABLED"
BILLING_PORTAL_ENABLED_ENV = "BILLING_PORTAL_ENABLED"
BILLING_SYNC_ENABLED_ENV = "BILLING_SYNC_ENABLED"
BILLING_RAW_PAYLOAD_CAPTURE_ENABLED_ENV = "BILLING_RAW_PAYLOAD_CAPTURE_ENABLED"
BILLING_S2S_BEARER_TOKEN_ENV = "BILLING_S2S_BEARER_TOKEN"
BILLING_ID_HMAC_SECRET_ENV = "BILLING_ID_HMAC_SECRET"
BILLING_PROVIDER_REF_ENCRYPTION_KEY_ENV = "BILLING_PROVIDER_REF_ENCRYPTION_KEY"
BILLING_PROVIDER_REF_ENCRYPTION_KEY_ID_ENV = "BILLING_PROVIDER_REF_ENCRYPTION_KEY_ID"
BILLING_PROVIDER_REF_DECRYPTION_KEYS_JSON_ENV = "BILLING_PROVIDER_REF_DECRYPTION_KEYS_JSON"
BILLING_RAW_PAYLOAD_ENCRYPTION_KEY_ENV = "BILLING_RAW_PAYLOAD_ENCRYPTION_KEY"
BILLING_RAW_PAYLOAD_ENCRYPTION_KEY_ID_ENV = "BILLING_RAW_PAYLOAD_ENCRYPTION_KEY_ID"
BILLING_WEBHOOK_DELIVERY_RETENTION_DAYS_ENV = "BILLING_WEBHOOK_DELIVERY_RETENTION_DAYS"
BILLING_RAW_PAYLOAD_RETENTION_DAYS_ENV = "BILLING_RAW_PAYLOAD_RETENTION_DAYS"
BILLING_SYNC_STALE_AFTER_SECONDS_ENV = "BILLING_SYNC_STALE_AFTER_SECONDS"
BILLING_S2S_RATE_LIMIT_ENV = "BILLING_S2S_RATE_LIMIT"
BILLING_S2S_RATE_WINDOW_SECONDS_ENV = "BILLING_S2S_RATE_WINDOW_SECONDS"
BILLING_RETURN_URL_ALLOWLIST_ENV = "BILLING_RETURN_URL_ALLOWLIST"
BILLING_ALLOWED_RETURN_ORIGINS_ENV = "BILLING_ALLOWED_RETURN_ORIGINS"

DEFAULT_BILLING_WEBHOOK_DELIVERY_RETENTION_DAYS = 90
MAX_BILLING_WEBHOOK_DELIVERY_RETENTION_DAYS = 90
DEFAULT_BILLING_RAW_PAYLOAD_RETENTION_DAYS = 30
MAX_BILLING_RAW_PAYLOAD_RETENTION_DAYS = 30
DEFAULT_BILLING_SYNC_STALE_AFTER_SECONDS = 24 * 60 * 60
DEFAULT_BILLING_S2S_RATE_LIMIT = 120
DEFAULT_BILLING_S2S_RATE_WINDOW_SECONDS = 60


class BillingConfigError(RuntimeError):
    """Raised for malformed generic billing configuration."""


@dataclass(frozen=True)
class BillingConfig:
    billing_enabled: bool = False
    s2s_enabled: bool = False
    checkout_enabled: bool = False
    portal_enabled: bool = False
    sync_enabled: bool = False
    raw_payload_capture_enabled: bool = False
    s2s_bearer_token: str | None = field(default=None, repr=False)
    id_hmac_secret: str | None = field(default=None, repr=False)
    provider_ref_encryption_key: str | None = field(default=None, repr=False)
    provider_ref_encryption_key_id: str | None = None
    provider_ref_decryption_keys_json: str = field(default="{}", repr=False)
    raw_payload_encryption_key: str | None = field(default=None, repr=False)
    raw_payload_encryption_key_id: str | None = None
    webhook_delivery_retention_days: int = DEFAULT_BILLING_WEBHOOK_DELIVERY_RETENTION_DAYS
    raw_payload_retention_days: int = DEFAULT_BILLING_RAW_PAYLOAD_RETENTION_DAYS
    sync_stale_after_seconds: int = DEFAULT_BILLING_SYNC_STALE_AFTER_SECONDS
    s2s_rate_limit: int = DEFAULT_BILLING_S2S_RATE_LIMIT
    s2s_rate_window_seconds: int = DEFAULT_BILLING_S2S_RATE_WINDOW_SECONDS
    return_url_allowlist: tuple[str, ...] = ()

    @property
    def primary_feature_flags(self) -> dict[str, bool]:
        return {
            "billing": self.billing_enabled,
            "s2s": self.s2s_enabled,
            "checkout": self.checkout_enabled,
            "portal": self.portal_enabled,
            "sync": self.sync_enabled,
        }

    @property
    def disabled(self) -> bool:
        return not any(self.primary_feature_flags.values()) and not self.raw_payload_capture_enabled

    @property
    def decryption_keys_by_id(self) -> dict[str, str]:
        raw = self.provider_ref_decryption_keys_json or "{}"
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BillingConfigError(f"{BILLING_PROVIDER_REF_DECRYPTION_KEYS_JSON_ENV} must be valid JSON") from exc
        if not isinstance(parsed, Mapping):
            raise BillingConfigError(f"{BILLING_PROVIDER_REF_DECRYPTION_KEYS_JSON_ENV} must be a JSON object")
        result = {str(key): str(value) for key, value in parsed.items() if str(key).strip() and str(value).strip()}
        if self.provider_ref_encryption_key and self.provider_ref_encryption_key_id:
            result.setdefault(self.provider_ref_encryption_key_id, self.provider_ref_encryption_key)
        return result

    def is_feature_enabled(self, feature: str) -> bool:
        normalized = str(feature or "").strip().lower()
        mapping = {
            "billing": self.billing_enabled,
            "s2s": self.s2s_enabled,
            "checkout": self.checkout_enabled,
            "portal": self.portal_enabled,
            "sync": self.sync_enabled,
            "raw_payload_capture": self.raw_payload_capture_enabled,
        }
        if normalized not in mapping:
            raise BillingConfigError(f"unknown billing feature flag: {normalized or '<empty>'}")
        return mapping[normalized]


@dataclass(frozen=True)
class BillingReadiness:
    ready: bool
    status: str
    enabled: bool = False
    missing: list[str] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)
    s2s_ready: bool = False
    checkout_ready: bool = False
    portal_ready: bool = False
    sync_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "status": self.status,
            "enabled": self.enabled,
            "missing": list(self.missing),
            "degraded": list(self.degraded),
            "s2s_ready": self.s2s_ready,
            "checkout_ready": self.checkout_ready,
            "portal_ready": self.portal_ready,
            "sync_ready": self.sync_ready,
        }


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
        raise BillingConfigError(f"{key} must be an integer") from exc


def _bounded_int(env: Mapping[str, str], key: str, default: int, *, minimum: int = 0, maximum: int) -> int:
    value = _int(env, key, default)
    if value < minimum or value > maximum:
        raise BillingConfigError(f"{key} must be between {minimum} and {maximum}")
    return value


def _csv_tuple(raw: str) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    for item in str(raw or "").split(","):
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        values.append(normalized)
        seen.add(normalized)
    return tuple(values)


def _origin(value: str) -> str | None:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        return None
    port = f":{parsed.port}" if parsed.port else ""
    hostname = (parsed.hostname or "").lower()
    return f"{parsed.scheme.lower()}://{hostname}{port}"


def parse_return_url_allowlist(raw: str | Sequence[str] | None) -> tuple[str, ...]:
    if raw is None:
        items: Sequence[str] = ()
    elif isinstance(raw, str):
        items = raw.split(",")
    else:
        items = raw
    origins: list[str] = []
    seen: set[str] = set()
    for item in items:
        origin = _origin(str(item))
        if origin and origin not in seen:
            origins.append(origin)
            seen.add(origin)
    return tuple(origins)


def is_return_url_allowed(url: str, allowlist: Sequence[str]) -> bool:
    candidate = _origin(url)
    allowed = {_origin(item) for item in allowlist}
    return bool(candidate and candidate in allowed)


def load_billing_config(*, env: Mapping[str, str] | None = None) -> BillingConfig:
    values = _env(env)
    return_urls = _get(values, BILLING_RETURN_URL_ALLOWLIST_ENV) or _get(values, BILLING_ALLOWED_RETURN_ORIGINS_ENV)
    return BillingConfig(
        billing_enabled=_bool(_get(values, BILLING_ENABLED_ENV), default=False),
        s2s_enabled=_bool(_get(values, BILLING_S2S_ENABLED_ENV), default=False),
        checkout_enabled=_bool(_get(values, BILLING_CHECKOUT_ENABLED_ENV), default=False),
        portal_enabled=_bool(_get(values, BILLING_PORTAL_ENABLED_ENV), default=False),
        sync_enabled=_bool(_get(values, BILLING_SYNC_ENABLED_ENV), default=False),
        raw_payload_capture_enabled=_bool(_get(values, BILLING_RAW_PAYLOAD_CAPTURE_ENABLED_ENV), default=False),
        s2s_bearer_token=_get(values, BILLING_S2S_BEARER_TOKEN_ENV) or None,
        id_hmac_secret=_get(values, BILLING_ID_HMAC_SECRET_ENV) or None,
        provider_ref_encryption_key=_get(values, BILLING_PROVIDER_REF_ENCRYPTION_KEY_ENV) or None,
        provider_ref_encryption_key_id=_get(values, BILLING_PROVIDER_REF_ENCRYPTION_KEY_ID_ENV) or None,
        provider_ref_decryption_keys_json=_get(values, BILLING_PROVIDER_REF_DECRYPTION_KEYS_JSON_ENV, "{}") or "{}",
        raw_payload_encryption_key=_get(values, BILLING_RAW_PAYLOAD_ENCRYPTION_KEY_ENV) or None,
        raw_payload_encryption_key_id=_get(values, BILLING_RAW_PAYLOAD_ENCRYPTION_KEY_ID_ENV) or None,
        webhook_delivery_retention_days=_bounded_int(
            values,
            BILLING_WEBHOOK_DELIVERY_RETENTION_DAYS_ENV,
            DEFAULT_BILLING_WEBHOOK_DELIVERY_RETENTION_DAYS,
            maximum=MAX_BILLING_WEBHOOK_DELIVERY_RETENTION_DAYS,
        ),
        raw_payload_retention_days=_bounded_int(
            values,
            BILLING_RAW_PAYLOAD_RETENTION_DAYS_ENV,
            DEFAULT_BILLING_RAW_PAYLOAD_RETENTION_DAYS,
            maximum=MAX_BILLING_RAW_PAYLOAD_RETENTION_DAYS,
        ),
        sync_stale_after_seconds=_int(values, BILLING_SYNC_STALE_AFTER_SECONDS_ENV, DEFAULT_BILLING_SYNC_STALE_AFTER_SECONDS),
        s2s_rate_limit=_int(values, BILLING_S2S_RATE_LIMIT_ENV, DEFAULT_BILLING_S2S_RATE_LIMIT),
        s2s_rate_window_seconds=_int(values, BILLING_S2S_RATE_WINDOW_SECONDS_ENV, DEFAULT_BILLING_S2S_RATE_WINDOW_SECONDS),
        return_url_allowlist=parse_return_url_allowlist(return_urls),
    )


def validate_billing_readiness(
    config: BillingConfig,
    *,
    provider_readinesses: Sequence[Any] | None = None,
) -> BillingReadiness:
    """Return fail-closed readiness without disclosing secret values."""

    if config.disabled:
        return BillingReadiness(ready=False, status="disabled", enabled=False)

    missing: list[str] = []
    degraded: list[str] = []
    required: list[tuple[str, Any]] = []

    if any(config.primary_feature_flags.values()):
        required.append((BILLING_ID_HMAC_SECRET_ENV, config.id_hmac_secret))
    if config.s2s_enabled:
        required.append((BILLING_S2S_BEARER_TOKEN_ENV, config.s2s_bearer_token))
    if config.checkout_enabled or config.portal_enabled or config.sync_enabled:
        required.extend(
            [
                (BILLING_PROVIDER_REF_ENCRYPTION_KEY_ENV, config.provider_ref_encryption_key),
                (BILLING_PROVIDER_REF_ENCRYPTION_KEY_ID_ENV, config.provider_ref_encryption_key_id),
            ]
        )
    if config.checkout_enabled and not config.return_url_allowlist:
        missing.append(BILLING_RETURN_URL_ALLOWLIST_ENV)
    if config.portal_enabled and not config.return_url_allowlist:
        missing.append(BILLING_RETURN_URL_ALLOWLIST_ENV)
    if config.raw_payload_capture_enabled:
        required.extend(
            [
                (BILLING_RAW_PAYLOAD_ENCRYPTION_KEY_ENV, config.raw_payload_encryption_key),
                (BILLING_RAW_PAYLOAD_ENCRYPTION_KEY_ID_ENV, config.raw_payload_encryption_key_id),
            ]
        )

    for name, value in required:
        if not value and name not in missing:
            missing.append(name)

    for readiness in provider_readinesses or ():
        provider_status = getattr(readiness, "status", None) or (readiness.get("status") if isinstance(readiness, Mapping) else None)
        provider_ready = getattr(readiness, "ready", None)
        if provider_ready is None and isinstance(readiness, Mapping):
            provider_ready = readiness.get("ready")
        if provider_status and provider_status not in {"ready", "healthy", "disabled"}:
            degraded.append(str(provider_status))
        if provider_ready is False and provider_status != "disabled":
            degraded.append("provider_not_ready")

    if missing:
        return BillingReadiness(
            ready=False,
            status="not_ready",
            enabled=config.billing_enabled,
            missing=missing,
            degraded=degraded,
            s2s_ready=False,
            checkout_ready=False,
            portal_ready=False,
            sync_ready=False,
        )

    if degraded:
        return BillingReadiness(
            ready=False,
            status="degraded",
            enabled=config.billing_enabled,
            degraded=sorted(set(degraded)),
            s2s_ready=config.s2s_enabled,
            checkout_ready=False if config.checkout_enabled else False,
            portal_ready=False if config.portal_enabled else False,
            sync_ready=False if config.sync_enabled else False,
        )

    return BillingReadiness(
        ready=True,
        status="ready",
        enabled=config.billing_enabled,
        s2s_ready=config.s2s_enabled,
        checkout_ready=config.checkout_enabled,
        portal_ready=config.portal_enabled,
        sync_ready=config.sync_enabled,
    )


def billing_disabled_or_not_ready_status(config: BillingConfig) -> str:
    return validate_billing_readiness(config).status


def is_billing_feature_enabled(config: BillingConfig, feature: str) -> bool:
    return config.is_feature_enabled(feature)


__all__ = [
    "BILLING_ALLOWED_RETURN_ORIGINS_ENV",
    "BILLING_CHECKOUT_ENABLED_ENV",
    "BILLING_ENABLED_ENV",
    "BILLING_ID_HMAC_SECRET_ENV",
    "BILLING_PORTAL_ENABLED_ENV",
    "BILLING_PROVIDER_REF_DECRYPTION_KEYS_JSON_ENV",
    "BILLING_PROVIDER_REF_ENCRYPTION_KEY_ENV",
    "BILLING_PROVIDER_REF_ENCRYPTION_KEY_ID_ENV",
    "BILLING_RAW_PAYLOAD_CAPTURE_ENABLED_ENV",
    "BILLING_RAW_PAYLOAD_ENCRYPTION_KEY_ENV",
    "BILLING_RAW_PAYLOAD_ENCRYPTION_KEY_ID_ENV",
    "BILLING_RAW_PAYLOAD_RETENTION_DAYS_ENV",
    "BILLING_RETURN_URL_ALLOWLIST_ENV",
    "BILLING_S2S_BEARER_TOKEN_ENV",
    "BILLING_S2S_ENABLED_ENV",
    "BILLING_S2S_RATE_LIMIT_ENV",
    "BILLING_S2S_RATE_WINDOW_SECONDS_ENV",
    "BILLING_SYNC_ENABLED_ENV",
    "BILLING_SYNC_STALE_AFTER_SECONDS_ENV",
    "BILLING_WEBHOOK_DELIVERY_RETENTION_DAYS_ENV",
    "BillingConfig",
    "BillingConfigError",
    "BillingReadiness",
    "billing_disabled_or_not_ready_status",
    "is_billing_feature_enabled",
    "is_return_url_allowed",
    "load_billing_config",
    "parse_return_url_allowlist",
    "validate_billing_readiness",
]
