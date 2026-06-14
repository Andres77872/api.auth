"""RED unit contracts for Google OAuth configuration.

Trace: `.dev/sdd/changes/google-oauth-login/tasks.md` task 2.1 and
spec requirements for env-driven allowlists, safe provisioning defaults,
TTL/leeway caps, required secrets, and no hard-coded production domains.

These tests intentionally import the future implementation inside test bodies
so pytest collection stays green while Phase 4.5 is still missing.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_NAME = "src.Util.google_oauth_config"


def _future_config_module() -> ModuleType:
    try:
        return importlib.import_module(MODULE_NAME)
    except ModuleNotFoundError as exc:
        if exc.name == MODULE_NAME or str(exc).endswith(MODULE_NAME):
            pytest.fail(
                f"missing implementation module: {MODULE_NAME}; "
                "Phase 4.5 must provide the Google OAuth config loader",
                pytrace=False,
            )
        pytest.fail(
            f"{MODULE_NAME} import failed due to missing dependency: {exc.name}",
            pytrace=False,
        )


_MISSING = object()


def _field(value: Any, name: str, default: Any = _MISSING) -> Any:
    if isinstance(value, Mapping):
        if name in value:
            return value[name]
    elif hasattr(value, name):
        return getattr(value, name)
    if default is not _MISSING:
        return default
    pytest.fail(f"Google OAuth config object missing field `{name}`")


def _loader(module: ModuleType):
    loader = getattr(module, "load_google_oauth_config", None)
    assert callable(loader), "expected load_google_oauth_config(env=...) contract"
    return loader


def _readiness_validator(module: ModuleType):
    validator = getattr(module, "validate_google_oauth_readiness", None)
    assert callable(validator), "expected validate_google_oauth_readiness(config) contract"
    return validator


def _config_error(module: ModuleType) -> type[BaseException]:
    error_type = getattr(module, "GoogleOAuthConfigError", None)
    assert isinstance(error_type, type), "expected GoogleOAuthConfigError exception type"
    return error_type


def _base_env(**overrides: str) -> dict[str, str]:
    env = {
        "APP_ENV": "test",
        "GOOGLE_OAUTH_ENABLED": "true",
        "GOOGLE_OAUTH_CLIENT_ID": "test-google-client-id.apps.googleusercontent.com",
        "GOOGLE_OAUTH_CLIENT_SECRET": "test-google-client-secret-not-real",
        "GOOGLE_OAUTH_DISCOVERY_URL": "https://accounts.google.com/.well-known/openid-configuration",
        "GOOGLE_OAUTH_AUTHORIZE_ENDPOINT": "https://accounts.google.com/o/oauth2/v2/auth",
        "GOOGLE_OAUTH_TOKEN_ENDPOINT": "https://oauth2.googleapis.com/token",
        "GOOGLE_OAUTH_JWKS_URI": "https://www.googleapis.com/oauth2/v3/certs",
        "GOOGLE_OAUTH_ISSUERS": "https://accounts.google.com,accounts.google.com",
        "GOOGLE_OAUTH_SCOPES": "openid email",
        "GOOGLE_OAUTH_REDIRECT_URIS": (
            "http://localhost:8000/auth/google/callback,"
            "http://127.0.0.1:8000/auth/google/callback"
        ),
        "GOOGLE_OAUTH_RETURN_ORIGINS": "http://localhost:3000,http://localhost:5173",
        "GOOGLE_OAUTH_PROVISIONING_MODE": "link_only",
        "GOOGLE_OAUTH_STATE_TTL_SECONDS": "600",
        "GOOGLE_OAUTH_LINK_TOKEN_TTL_SECONDS": "600",
        "GOOGLE_OAUTH_RECENT_REAUTH_SECONDS": "300",
        "GOOGLE_OAUTH_JWKS_CACHE_TTL_SECONDS": "3600",
        "GOOGLE_OAUTH_LEEWAY_SECONDS": "30",
        "GOOGLE_OAUTH_STATE_PEPPER": "test-oauth-state-pepper-not-real-min-32-bytes!!",
        "GOOGLE_OAUTH_PROVIDER_SUB_PEPPER": "test-oauth-provider-sub-pepper-not-real-min-32-bytes!!",
        "GOOGLE_OAUTH_EMAIL_HASH_PEPPER": "test-oauth-email-hash-pepper-not-real-min-32-bytes!!",
        "GOOGLE_OAUTH_PASSWORDLESS_HASH_SECRET": "test-oauth-passwordless-secret-not-real-min-32-bytes!!",
        "GOOGLE_OAUTH_FAIL_CLOSED_ON_REDIS_ERROR": "true",
        "PROVIDER_INIT_REDEEM_URL": "http://provider-init.test/internal/auth/provider-init/redeem",
        "PROVIDER_INIT_REDEEM_TOKEN": "test-provider-init-redeem-token-not-real",
        "PROVIDER_INIT_RETURN_ORIGINS": "http://localhost:3000,http://localhost:5173",
    }
    env.update(overrides)
    return env


def _is_allowed(config: Any, module: ModuleType, kind: str, value: str) -> bool:
    candidates = {
        "redirect": (
            "is_redirect_uri_allowed",
            "redirect_uri_allowed",
            "validate_redirect_uri",
        ),
        "return_origin": (
            "is_return_origin_allowed",
            "return_origin_allowed",
            "validate_return_origin",
        ),
    }[kind]
    for name in candidates:
        target = getattr(config, name, None) or getattr(module, name, None)
        if callable(target):
            try:
                return bool(target(value))
            except TypeError:
                return bool(target(config, value))
    pytest.fail(f"missing exact-match allowlist helper for {kind}")


def test_disabled_config_is_not_ready_and_does_not_require_google_provider_secrets():
    module = _future_config_module()
    config = _loader(module)(
        env=_base_env(
            GOOGLE_OAUTH_ENABLED="false",
            GOOGLE_OAUTH_CLIENT_ID="",
            GOOGLE_OAUTH_CLIENT_SECRET="",
            PROVIDER_INIT_REDEEM_TOKEN="",
        )
    )
    readiness = _readiness_validator(module)(config)

    assert _field(config, "enabled") is False
    assert _field(readiness, "ready") is False
    assert _field(readiness, "status") == "disabled"
    assert "GOOGLE_OAUTH_CLIENT_SECRET" not in _field(readiness, "missing", [])


def test_production_default_provisioning_mode_is_disabled_or_link_only():
    module = _future_config_module()
    env = _base_env(APP_ENV="production")
    env.pop("GOOGLE_OAUTH_PROVISIONING_MODE")

    config = _loader(module)(env=env)

    assert _field(config, "provisioning_mode") in {"disabled", "link_only"}
    assert _field(config, "provisioning_mode") != "auto_create"


def test_redirect_and_return_origin_allowlists_are_environment_driven_exact_matches():
    module = _future_config_module()
    config = _loader(module)(env=_base_env())

    assert _is_allowed(config, module, "redirect", "http://localhost:8000/auth/google/callback")
    assert _is_allowed(config, module, "redirect", "http://127.0.0.1:8000/auth/google/callback")
    assert not _is_allowed(config, module, "redirect", "http://localhost:8000/auth/google/callback/")
    assert not _is_allowed(config, module, "redirect", "http://localhost:8000/auth/google/callback?next=/")
    assert not _is_allowed(config, module, "redirect", "http://evil.localhost:8000/auth/google/callback")

    assert _is_allowed(config, module, "return_origin", "http://localhost:3000")
    assert _is_allowed(config, module, "return_origin", "http://localhost:5173")
    assert not _is_allowed(config, module, "return_origin", "http://localhost:3000/")
    assert not _is_allowed(config, module, "return_origin", "http://evil.localhost:3000")


def test_ttl_jwks_cache_and_leeway_caps_are_enforced():
    module = _future_config_module()
    loader = _loader(module)
    error_type = _config_error(module)

    config = loader(env=_base_env())
    assert _field(config, "state_ttl_seconds") <= 600
    assert _field(config, "link_token_ttl_seconds") <= 600
    assert _field(config, "jwks_cache_ttl_seconds") <= 3600
    assert _field(config, "leeway_seconds") == 30

    with pytest.raises(error_type, match="GOOGLE_OAUTH_STATE_TTL_SECONDS"):
        loader(env=_base_env(GOOGLE_OAUTH_STATE_TTL_SECONDS="601"))
    with pytest.raises(error_type, match="GOOGLE_OAUTH_LINK_TOKEN_TTL_SECONDS"):
        loader(env=_base_env(GOOGLE_OAUTH_LINK_TOKEN_TTL_SECONDS="601"))
    with pytest.raises(error_type, match="GOOGLE_OAUTH_JWKS_CACHE_TTL_SECONDS"):
        loader(env=_base_env(GOOGLE_OAUTH_JWKS_CACHE_TTL_SECONDS="3601"))
    with pytest.raises(error_type, match="GOOGLE_OAUTH_LEEWAY_SECONDS"):
        loader(env=_base_env(GOOGLE_OAUTH_LEEWAY_SECONDS="31"))


def test_enabled_readiness_requires_google_provider_init_and_hashing_secrets():
    module = _future_config_module()
    config = _loader(module)(
        env=_base_env(
            GOOGLE_OAUTH_CLIENT_SECRET="",
            GOOGLE_OAUTH_STATE_PEPPER="",
            GOOGLE_OAUTH_PROVIDER_SUB_PEPPER="",
            GOOGLE_OAUTH_EMAIL_HASH_PEPPER="",
            GOOGLE_OAUTH_PASSWORDLESS_HASH_SECRET="",
            PROVIDER_INIT_REDEEM_URL="",
            PROVIDER_INIT_REDEEM_TOKEN="",
        )
    )
    readiness = _readiness_validator(module)(config)

    assert _field(readiness, "ready") is False
    assert set(_field(readiness, "missing")) >= {
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GOOGLE_OAUTH_STATE_PEPPER",
        "GOOGLE_OAUTH_PROVIDER_SUB_PEPPER",
        "GOOGLE_OAUTH_EMAIL_HASH_PEPPER",
        "GOOGLE_OAUTH_PASSWORDLESS_HASH_SECRET",
        "PROVIDER_INIT_REDEEM_URL",
        "PROVIDER_INIT_REDEEM_TOKEN",
    }


def test_config_source_does_not_hard_code_application_production_domains():
    module = _future_config_module()
    source_path = Path(module.__file__ or "")
    assert source_path.exists(), "config module must be inspectable for static safety checks"
    source = source_path.read_text(encoding="utf-8", errors="ignore").lower()

    forbidden_application_domain_fragments = (
        "magic-worlds.com",
        "api.magic-worlds",
        "auth.magic-worlds",
        "app.magic-worlds",
    )
    offenders = [fragment for fragment in forbidden_application_domain_fragments if fragment in source]

    assert offenders == []
