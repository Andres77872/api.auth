"""Deployment-level OAuth settings.

Only values that are genuinely deployment-wide live here: kill switch, HMAC
peppers, fail-closed posture, clock leeway, cache tuning, ceilings and the
encryption keys for connection secrets. Everything a project or a provider could
legitimately want to differ lives on the connection or the project binding.

Every ``OAUTH_*`` name falls back to its historical ``GOOGLE_OAUTH_*`` name. The
peppers MUST keep their values across the rename -- the provider-subject HMAC is
the durable identity key, and a different pepper orphans every existing link. If
both names are set with different values the loader fails loudly instead of
silently picking one.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Mapping

from src.Util.auth_constants import (
    GOOGLE_OAUTH_EMAIL_HASH_PEPPER_ENV,
    GOOGLE_OAUTH_ENABLED_ENV,
    GOOGLE_OAUTH_FAIL_CLOSED_ON_REDIS_ERROR_ENV,
    GOOGLE_OAUTH_JWKS_CACHE_TTL_SECONDS_ENV,
    GOOGLE_OAUTH_LEEWAY_SECONDS_ENV,
    GOOGLE_OAUTH_PROVIDER_SUB_PEPPER_ENV,
    GOOGLE_OAUTH_RECENT_REAUTH_SECONDS_ENV,
    GOOGLE_OAUTH_STATE_PEPPER_ENV,
    GOOGLE_OAUTH_STATE_TTL_SECONDS_ENV,
    OAUTH_ALLOW_PRIVATE_IDP_HOSTS_ENV,
    OAUTH_CONFIG_SOURCE_DB,
    OAUTH_CONFIG_SOURCE_ENV,
    OAUTH_CONFIG_SOURCE_ENV_NAME,
    OAUTH_EMAIL_HASH_PEPPER_ENV,
    OAUTH_ENABLED_ENV,
    OAUTH_FAIL_CLOSED_ON_REDIS_ERROR_ENV,
    OAUTH_JWKS_CACHE_TTL_SECONDS_ENV,
    OAUTH_LEEWAY_SECONDS_ENV,
    OAUTH_MAX_STATE_TTL_SECONDS_ENV,
    OAUTH_PROVIDER_SUB_PEPPER_ENV,
    OAUTH_RECENT_REAUTH_SECONDS_ENV,
    OAUTH_SECRET_DECRYPTION_KEYS_JSON_ENV,
    OAUTH_SECRET_ENCRYPTION_KEY_ENV,
    OAUTH_SECRET_ENCRYPTION_KEY_ID_ENV,
    OAUTH_SECRET_HMAC_KEY_ENV,
    OAUTH_STATE_PEPPER_ENV,
    OAUTH_TRUSTED_PROXY_CIDRS_ENV,
)


HARD_MAX_STATE_TTL_SECONDS = 600
HARD_MAX_JWKS_CACHE_TTL_SECONDS = 3600
HARD_MAX_LEEWAY_SECONDS = 30
DEFAULT_RECENT_REAUTH_SECONDS = 300


class OAuthSettingsError(RuntimeError):
    """Raised when deployment-level OAuth settings are malformed or conflicting."""


def _env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return env if env is not None else os.environ


def _text(env: Mapping[str, str], name: str) -> str:
    value = env.get(name)
    return "" if value is None else str(value).strip()


def env_with_fallback(env: Mapping[str, str], name: str, legacy_name: str, *, default: str = "", strict: bool = False) -> str:
    """Read ``name``, falling back to ``legacy_name``.

    ``strict`` is for identity-bearing secrets (the peppers): two different values would
    mean two different identity keys, so that fails loudly instead of silently picking
    one. For ordinary settings the new name simply takes precedence.
    """

    current = _text(env, name)
    legacy = _text(env, legacy_name)
    if strict and current and legacy and current != legacy:
        raise OAuthSettingsError(
            f"{name} and {legacy_name} are both set with different values; "
            "they must be identical (or set only one)"
        )
    return current or legacy or default


def _bool(raw: str, *, default: bool) -> bool:
    if raw == "":
        return default
    return raw.lower() in {"1", "true", "yes", "y", "on"}


def _bounded_int(raw: str, *, name: str, default: int, minimum: int, maximum: int) -> int:
    if raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise OAuthSettingsError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise OAuthSettingsError(f"{name} must be between {minimum} and {maximum}")
    return value


def _csv(raw: str) -> tuple[str, ...]:
    seen: list[str] = []
    for item in raw.split(","):
        value = item.strip()
        if value and value not in seen:
            seen.append(value)
    return tuple(seen)


@dataclass(frozen=True)
class OAuthDeploymentSettings:
    enabled: bool
    config_source: str
    state_pepper: str = field(repr=False)
    provider_sub_pepper: str = field(repr=False)
    email_hash_pepper: str = field(repr=False)
    fail_closed_on_redis_error: bool
    leeway_seconds: int
    jwks_cache_ttl_seconds: int
    recent_reauth_seconds: int
    max_state_ttl_seconds: int
    trusted_proxy_cidrs: tuple[str, ...]
    allow_private_idp_hosts: bool
    secret_encryption_key: str | None = field(default=None, repr=False)
    secret_encryption_key_id: str | None = None
    secret_decryption_keys: Mapping[str, str] = field(default_factory=dict, repr=False)
    secret_hmac_key: str | None = field(default=None, repr=False)

    @property
    def uses_database(self) -> bool:
        return self.config_source == OAUTH_CONFIG_SOURCE_DB

    @property
    def secrets_ready(self) -> bool:
        return bool(self.secret_encryption_key and self.secret_encryption_key_id and self.secret_hmac_key)

    @property
    def decryption_keys_by_id(self) -> dict[str, str]:
        keys = dict(self.secret_decryption_keys)
        if self.secret_encryption_key and self.secret_encryption_key_id:
            keys[self.secret_encryption_key_id] = self.secret_encryption_key
        return keys


def _decryption_keys(raw: str) -> dict[str, str]:
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OAuthSettingsError(f"{OAUTH_SECRET_DECRYPTION_KEYS_JSON_ENV} must be a JSON object") from exc
    if not isinstance(decoded, dict):
        raise OAuthSettingsError(f"{OAUTH_SECRET_DECRYPTION_KEYS_JSON_ENV} must be a JSON object")
    return {str(key): str(value) for key, value in decoded.items() if str(key).strip() and str(value).strip()}


def load_oauth_settings(*, env: Mapping[str, str] | None = None) -> OAuthDeploymentSettings:
    """Parse deployment-level OAuth settings without touching providers, Redis or the database."""

    values = _env(env)
    source = (_text(values, OAUTH_CONFIG_SOURCE_ENV_NAME) or OAUTH_CONFIG_SOURCE_ENV).lower()
    if source not in {OAUTH_CONFIG_SOURCE_ENV, OAUTH_CONFIG_SOURCE_DB}:
        raise OAuthSettingsError(
            f"{OAUTH_CONFIG_SOURCE_ENV_NAME} must be '{OAUTH_CONFIG_SOURCE_ENV}' or '{OAUTH_CONFIG_SOURCE_DB}'"
        )

    max_state_ttl = _bounded_int(
        env_with_fallback(values, OAUTH_MAX_STATE_TTL_SECONDS_ENV, GOOGLE_OAUTH_STATE_TTL_SECONDS_ENV),
        name=OAUTH_MAX_STATE_TTL_SECONDS_ENV,
        default=HARD_MAX_STATE_TTL_SECONDS,
        minimum=1,
        maximum=HARD_MAX_STATE_TTL_SECONDS,
    )
    recent_reauth_raw = env_with_fallback(values, OAUTH_RECENT_REAUTH_SECONDS_ENV, GOOGLE_OAUTH_RECENT_REAUTH_SECONDS_ENV)
    try:
        recent_reauth = int(recent_reauth_raw) if recent_reauth_raw else DEFAULT_RECENT_REAUTH_SECONDS
    except ValueError as exc:
        raise OAuthSettingsError(f"{OAUTH_RECENT_REAUTH_SECONDS_ENV} must be an integer") from exc

    return OAuthDeploymentSettings(
        enabled=_bool(env_with_fallback(values, OAUTH_ENABLED_ENV, GOOGLE_OAUTH_ENABLED_ENV), default=False),
        config_source=source,
        state_pepper=env_with_fallback(values, OAUTH_STATE_PEPPER_ENV, GOOGLE_OAUTH_STATE_PEPPER_ENV, strict=True),
        provider_sub_pepper=env_with_fallback(values, OAUTH_PROVIDER_SUB_PEPPER_ENV, GOOGLE_OAUTH_PROVIDER_SUB_PEPPER_ENV, strict=True),
        email_hash_pepper=env_with_fallback(values, OAUTH_EMAIL_HASH_PEPPER_ENV, GOOGLE_OAUTH_EMAIL_HASH_PEPPER_ENV, strict=True),
        fail_closed_on_redis_error=_bool(
            env_with_fallback(values, OAUTH_FAIL_CLOSED_ON_REDIS_ERROR_ENV, GOOGLE_OAUTH_FAIL_CLOSED_ON_REDIS_ERROR_ENV),
            default=True,
        ),
        leeway_seconds=_bounded_int(
            env_with_fallback(values, OAUTH_LEEWAY_SECONDS_ENV, GOOGLE_OAUTH_LEEWAY_SECONDS_ENV),
            name=OAUTH_LEEWAY_SECONDS_ENV,
            default=HARD_MAX_LEEWAY_SECONDS,
            minimum=0,
            maximum=HARD_MAX_LEEWAY_SECONDS,
        ),
        jwks_cache_ttl_seconds=_bounded_int(
            env_with_fallback(values, OAUTH_JWKS_CACHE_TTL_SECONDS_ENV, GOOGLE_OAUTH_JWKS_CACHE_TTL_SECONDS_ENV),
            name=OAUTH_JWKS_CACHE_TTL_SECONDS_ENV,
            default=HARD_MAX_JWKS_CACHE_TTL_SECONDS,
            minimum=1,
            maximum=HARD_MAX_JWKS_CACHE_TTL_SECONDS,
        ),
        recent_reauth_seconds=max(1, recent_reauth),
        max_state_ttl_seconds=max_state_ttl,
        trusted_proxy_cidrs=_csv(_text(values, OAUTH_TRUSTED_PROXY_CIDRS_ENV)),
        allow_private_idp_hosts=_bool(_text(values, OAUTH_ALLOW_PRIVATE_IDP_HOSTS_ENV), default=False),
        secret_encryption_key=_text(values, OAUTH_SECRET_ENCRYPTION_KEY_ENV) or None,
        secret_encryption_key_id=_text(values, OAUTH_SECRET_ENCRYPTION_KEY_ID_ENV) or None,
        secret_decryption_keys=_decryption_keys(_text(values, OAUTH_SECRET_DECRYPTION_KEYS_JSON_ENV)),
        secret_hmac_key=_text(values, OAUTH_SECRET_HMAC_KEY_ENV) or None,
    )


__all__ = [
    "HARD_MAX_STATE_TTL_SECONDS",
    "OAuthDeploymentSettings",
    "OAuthSettingsError",
    "env_with_fallback",
    "load_oauth_settings",
]
