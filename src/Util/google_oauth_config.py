"""Google OAuth/OIDC feature configuration.

This module is intentionally configuration-only. It does not import or call
Authlib, google-auth, Google network APIs, Redis, or database code. Runtime
protocol modules consume this parsed config in later phases.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Mapping

from src.Util.auth_constants import (
    APP_ENV_ENV,
    GOOGLE_OAUTH_ALLOWED_PROVISIONING_MODES,
    GOOGLE_OAUTH_AUTHORIZE_ENDPOINT_ENV,
    GOOGLE_OAUTH_CLIENT_ID_ENV,
    GOOGLE_OAUTH_CLIENT_SECRET_ENV,
    GOOGLE_OAUTH_DEFAULT_SCOPES,
    GOOGLE_OAUTH_DEFAULT_USER_GROUP_HASH_ENV,
    GOOGLE_OAUTH_DISCOVERY_URL_ENV,
    GOOGLE_OAUTH_EMAIL_HASH_PEPPER_ENV,
    GOOGLE_OAUTH_ENABLED_ENV,
    GOOGLE_OAUTH_FAIL_CLOSED_ON_REDIS_ERROR_ENV,
    GOOGLE_OAUTH_ISSUERS_ENV,
    GOOGLE_OAUTH_JWKS_CACHE_TTL_SECONDS_ENV,
    GOOGLE_OAUTH_JWKS_URI_ENV,
    GOOGLE_OAUTH_LEEWAY_SECONDS_ENV,
    GOOGLE_OAUTH_LINK_TOKEN_TTL_SECONDS_ENV,
    GOOGLE_OAUTH_PASSWORDLESS_HASH_SECRET_ENV,
    GOOGLE_OAUTH_PROVIDER_SUB_PEPPER_ENV,
    GOOGLE_OAUTH_PROVISIONING_DISABLED,
    GOOGLE_OAUTH_PROVISIONING_LINK_ONLY,
    GOOGLE_OAUTH_PROVISIONING_MODE_ENV,
    GOOGLE_OAUTH_RECENT_REAUTH_SECONDS_ENV,
    GOOGLE_OAUTH_REDIRECT_URIS_ENV,
    GOOGLE_OAUTH_RETURN_ORIGINS_ENV,
    GOOGLE_OAUTH_SCOPES_ENV,
    GOOGLE_OAUTH_STATE_PEPPER_ENV,
    GOOGLE_OAUTH_STATE_TTL_SECONDS_ENV,
    GOOGLE_OAUTH_TOKEN_ENDPOINT_ENV,
    NON_TEST_ENV_NAMES,
    PROVIDER_INIT_REDEEM_TOKEN_ENV,
    PROVIDER_INIT_REDEEM_URL_ENV,
    PROVIDER_INIT_RETURN_ORIGINS_ENV,
    PYTEST_CURRENT_TEST_ENV,
    TEST_ENV_NAMES,
)


DEFAULT_GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
DEFAULT_GOOGLE_AUTHORIZE_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
DEFAULT_GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
DEFAULT_GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
DEFAULT_GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")

MAX_GOOGLE_OAUTH_STATE_TTL_SECONDS = 600
MAX_GOOGLE_OAUTH_LINK_TOKEN_TTL_SECONDS = 600
MAX_GOOGLE_OAUTH_JWKS_CACHE_TTL_SECONDS = 3600
MAX_GOOGLE_OAUTH_LEEWAY_SECONDS = 30
DEFAULT_GOOGLE_OAUTH_RECENT_REAUTH_SECONDS = 300


class GoogleOAuthConfigError(RuntimeError):
    """Raised when Google OAuth configuration is malformed."""


@dataclass(frozen=True)
class GoogleOAuthConfig:
    enabled: bool
    client_id: str
    client_secret: str | None
    discovery_url: str
    authorize_endpoint: str
    token_endpoint: str
    jwks_uri: str
    issuers: tuple[str, ...]
    scopes: str
    redirect_uris: tuple[str, ...]
    return_origins: tuple[str, ...]
    provisioning_mode: str
    default_user_group_hash: str | None
    state_ttl_seconds: int
    link_token_ttl_seconds: int
    recent_reauth_seconds: int
    jwks_cache_ttl_seconds: int
    leeway_seconds: int
    state_pepper: str
    provider_sub_pepper: str
    email_hash_pepper: str
    passwordless_hash_secret: str
    fail_closed_on_redis_error: bool
    provider_init_redeem_url: str | None
    provider_init_redeem_token: str | None
    provider_init_return_origins: tuple[str, ...]
    app_env: str
    explicit_test_runtime: bool

    @property
    def scope_set(self) -> frozenset[str]:
        return frozenset(self.scopes.split())

    @property
    def production_like(self) -> bool:
        return self.app_env.lower() in {"prod", "production"}

    @property
    def disabled(self) -> bool:
        return not self.enabled

    def is_redirect_uri_allowed(self, redirect_uri: str) -> bool:
        """Return True only for exact configured redirect URI matches."""
        return str(redirect_uri or "") in self.redirect_uris

    def is_return_origin_allowed(self, return_origin: str) -> bool:
        """Return True only for exact configured return-origin matches."""
        return str(return_origin or "") in self.return_origins

    def is_provider_init_return_origin_allowed(self, return_origin: str) -> bool:
        """Return True only for exact provider-init return-origin matches."""
        return str(return_origin or "") in self.provider_init_return_origins


@dataclass(frozen=True)
class GoogleOAuthReadiness:
    ready: bool
    status: str
    missing: list[str] = field(default_factory=list)
    provider: str = "google"


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
        raise GoogleOAuthConfigError(f"{key} must be an integer") from exc


def _bounded_int(
    env: Mapping[str, str],
    key: str,
    default: int,
    *,
    minimum: int = 1,
    maximum: int,
) -> int:
    value = _int(env, key, default)
    if value < minimum or value > maximum:
        raise GoogleOAuthConfigError(f"{key} must be between {minimum} and {maximum}")
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


def is_explicit_test_runtime(env: Mapping[str, str] | None = None) -> bool:
    values = _env(env)
    runtime = _get(values, APP_ENV_ENV).lower()
    if runtime in TEST_ENV_NAMES:
        return True
    if runtime in NON_TEST_ENV_NAMES:
        return False
    return bool(_get(values, PYTEST_CURRENT_TEST_ENV)) or "pytest" in sys.modules


def _default_provisioning_mode(env: Mapping[str, str]) -> str:
    # Default safe in every environment. In production this satisfies the spec's
    # disabled-or-link-only default; auto_create/both must be explicit.
    return GOOGLE_OAUTH_PROVISIONING_DISABLED


def _parse_provisioning_mode(env: Mapping[str, str]) -> str:
    raw = _get(env, GOOGLE_OAUTH_PROVISIONING_MODE_ENV)
    mode = (raw or _default_provisioning_mode(env)).lower()
    if mode not in GOOGLE_OAUTH_ALLOWED_PROVISIONING_MODES:
        allowed = "|".join(sorted(GOOGLE_OAUTH_ALLOWED_PROVISIONING_MODES))
        raise GoogleOAuthConfigError(f"{GOOGLE_OAUTH_PROVISIONING_MODE_ENV} must be one of {allowed}")
    return mode


def _validate_scopes(scopes: str) -> str:
    scope_set = set(scopes.split())
    if scope_set != {"openid", "email"}:
        raise GoogleOAuthConfigError(f"{GOOGLE_OAUTH_SCOPES_ENV} must be exactly 'openid email'")
    return GOOGLE_OAUTH_DEFAULT_SCOPES


def load_google_oauth_config(*, env: Mapping[str, str] | None = None) -> GoogleOAuthConfig:
    """Parse Google OAuth environment variables without contacting providers."""

    values = _env(env)
    app_env = _get(values, APP_ENV_ENV)
    return_origins = _csv_tuple(_get(values, GOOGLE_OAUTH_RETURN_ORIGINS_ENV))
    provider_init_return_origins = _csv_tuple(_get(values, PROVIDER_INIT_RETURN_ORIGINS_ENV)) or return_origins

    return GoogleOAuthConfig(
        enabled=_bool(_get(values, GOOGLE_OAUTH_ENABLED_ENV), default=False),
        client_id=_get(values, GOOGLE_OAUTH_CLIENT_ID_ENV),
        client_secret=_get(values, GOOGLE_OAUTH_CLIENT_SECRET_ENV) or None,
        discovery_url=_get(values, GOOGLE_OAUTH_DISCOVERY_URL_ENV, DEFAULT_GOOGLE_DISCOVERY_URL),
        authorize_endpoint=_get(values, GOOGLE_OAUTH_AUTHORIZE_ENDPOINT_ENV, DEFAULT_GOOGLE_AUTHORIZE_ENDPOINT),
        token_endpoint=_get(values, GOOGLE_OAUTH_TOKEN_ENDPOINT_ENV, DEFAULT_GOOGLE_TOKEN_ENDPOINT),
        jwks_uri=_get(values, GOOGLE_OAUTH_JWKS_URI_ENV, DEFAULT_GOOGLE_JWKS_URI),
        issuers=_csv_tuple(_get(values, GOOGLE_OAUTH_ISSUERS_ENV, ",".join(DEFAULT_GOOGLE_ISSUERS))),
        scopes=_validate_scopes(_get(values, GOOGLE_OAUTH_SCOPES_ENV, GOOGLE_OAUTH_DEFAULT_SCOPES)),
        redirect_uris=_csv_tuple(_get(values, GOOGLE_OAUTH_REDIRECT_URIS_ENV)),
        return_origins=return_origins,
        provisioning_mode=_parse_provisioning_mode(values),
        default_user_group_hash=_get(values, GOOGLE_OAUTH_DEFAULT_USER_GROUP_HASH_ENV) or None,
        state_ttl_seconds=_bounded_int(
            values,
            GOOGLE_OAUTH_STATE_TTL_SECONDS_ENV,
            MAX_GOOGLE_OAUTH_STATE_TTL_SECONDS,
            maximum=MAX_GOOGLE_OAUTH_STATE_TTL_SECONDS,
        ),
        link_token_ttl_seconds=_bounded_int(
            values,
            GOOGLE_OAUTH_LINK_TOKEN_TTL_SECONDS_ENV,
            MAX_GOOGLE_OAUTH_LINK_TOKEN_TTL_SECONDS,
            maximum=MAX_GOOGLE_OAUTH_LINK_TOKEN_TTL_SECONDS,
        ),
        recent_reauth_seconds=_int(values, GOOGLE_OAUTH_RECENT_REAUTH_SECONDS_ENV, DEFAULT_GOOGLE_OAUTH_RECENT_REAUTH_SECONDS),
        jwks_cache_ttl_seconds=_bounded_int(
            values,
            GOOGLE_OAUTH_JWKS_CACHE_TTL_SECONDS_ENV,
            MAX_GOOGLE_OAUTH_JWKS_CACHE_TTL_SECONDS,
            maximum=MAX_GOOGLE_OAUTH_JWKS_CACHE_TTL_SECONDS,
        ),
        leeway_seconds=_bounded_int(
            values,
            GOOGLE_OAUTH_LEEWAY_SECONDS_ENV,
            MAX_GOOGLE_OAUTH_LEEWAY_SECONDS,
            minimum=0,
            maximum=MAX_GOOGLE_OAUTH_LEEWAY_SECONDS,
        ),
        state_pepper=_get(values, GOOGLE_OAUTH_STATE_PEPPER_ENV),
        provider_sub_pepper=_get(values, GOOGLE_OAUTH_PROVIDER_SUB_PEPPER_ENV),
        email_hash_pepper=_get(values, GOOGLE_OAUTH_EMAIL_HASH_PEPPER_ENV),
        passwordless_hash_secret=_get(values, GOOGLE_OAUTH_PASSWORDLESS_HASH_SECRET_ENV),
        fail_closed_on_redis_error=_bool(_get(values, GOOGLE_OAUTH_FAIL_CLOSED_ON_REDIS_ERROR_ENV), default=True),
        provider_init_redeem_url=_get(values, PROVIDER_INIT_REDEEM_URL_ENV) or None,
        provider_init_redeem_token=_get(values, PROVIDER_INIT_REDEEM_TOKEN_ENV) or None,
        provider_init_return_origins=provider_init_return_origins,
        app_env=app_env,
        explicit_test_runtime=is_explicit_test_runtime(values),
    )


def validate_google_oauth_readiness(config: GoogleOAuthConfig) -> GoogleOAuthReadiness:
    """Return readiness state without leaking secret values."""

    if not config.enabled:
        return GoogleOAuthReadiness(ready=False, status="disabled")

    missing: list[str] = []
    required_values = (
        (GOOGLE_OAUTH_CLIENT_ID_ENV, config.client_id),
        (GOOGLE_OAUTH_CLIENT_SECRET_ENV, config.client_secret),
        (GOOGLE_OAUTH_JWKS_URI_ENV, config.jwks_uri),
        (GOOGLE_OAUTH_REDIRECT_URIS_ENV, config.redirect_uris),
        (GOOGLE_OAUTH_RETURN_ORIGINS_ENV, config.return_origins),
        (GOOGLE_OAUTH_STATE_PEPPER_ENV, config.state_pepper),
        (GOOGLE_OAUTH_PROVIDER_SUB_PEPPER_ENV, config.provider_sub_pepper),
        (GOOGLE_OAUTH_EMAIL_HASH_PEPPER_ENV, config.email_hash_pepper),
        (GOOGLE_OAUTH_PASSWORDLESS_HASH_SECRET_ENV, config.passwordless_hash_secret),
        (PROVIDER_INIT_REDEEM_URL_ENV, config.provider_init_redeem_url),
        (PROVIDER_INIT_REDEEM_TOKEN_ENV, config.provider_init_redeem_token),
    )
    for name, value in required_values:
        if not value:
            missing.append(name)

    if missing:
        return GoogleOAuthReadiness(ready=False, status="not_ready", missing=missing)
    return GoogleOAuthReadiness(ready=True, status="ready")


def is_redirect_uri_allowed(config: GoogleOAuthConfig, redirect_uri: str) -> bool:
    return config.is_redirect_uri_allowed(redirect_uri)


def is_return_origin_allowed(config: GoogleOAuthConfig, return_origin: str) -> bool:
    return config.is_return_origin_allowed(return_origin)


def google_oauth_disabled_or_not_ready_status(config: GoogleOAuthConfig) -> str:
    """Return a neutral posture label for disabled/not-ready route handling."""
    readiness = validate_google_oauth_readiness(config)
    if readiness.status == "ready":
        return "ready"
    if config.provisioning_mode == GOOGLE_OAUTH_PROVISIONING_LINK_ONLY and not config.enabled:
        return "disabled"
    return readiness.status
