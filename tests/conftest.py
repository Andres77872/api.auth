"""
Shared test fixtures and bootstrap configuration.

CRITICAL: This file loads .env.test BEFORE any src.* import to prevent
db_config.py from creating a live Redis connection at import time.
"""

import base64
import importlib
import json
import os
import sys
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional
from unittest.mock import patch, MagicMock

# ─── Step 1: Load .env.test BEFORE any src.* import ─────────────────────────
ENV_TEST_PATH = Path(__file__).parent.parent / ".env.test"
if ENV_TEST_PATH.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_TEST_PATH, override=True)
    except ImportError:
        # python-dotenv not installed — set env vars manually
        pass

# ─── Step 2: Ensure critical env vars are set ────────────────────────────────
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test_jwt_secret_key_for_testing_only_32chars!!"
)
os.environ.setdefault("DEBUG_MODE", "true")
os.environ.setdefault("LOG_TOKEN_USER", "test_log_token_user")
os.environ.setdefault("LOG_TOKEN_REALM", "test_log_token_realm")

# Phase 1 Google OAuth RED harness defaults.
# These intentionally live in-process until task 4.3 owns .env.test edits.
_GOOGLE_OAUTH_TEST_ENV_DEFAULTS = {
    "GOOGLE_OAUTH_ENABLED": "false",
    "GOOGLE_OAUTH_CLIENT_ID": "test-google-client-id.apps.googleusercontent.com",
    "GOOGLE_OAUTH_CLIENT_SECRET": "test-google-client-secret-not-real",
    "GOOGLE_OAUTH_DISCOVERY_URL": "https://accounts.google.com/.well-known/openid-configuration",
    "GOOGLE_OAUTH_AUTHORIZE_ENDPOINT": "https://accounts.google.com/o/oauth2/v2/auth",
    "GOOGLE_OAUTH_TOKEN_ENDPOINT": "https://oauth2.googleapis.com/token",
    "GOOGLE_OAUTH_JWKS_URI": "https://www.googleapis.com/oauth2/v3/certs",
    "GOOGLE_OAUTH_ISSUERS": "https://accounts.google.com,accounts.google.com",
    "GOOGLE_OAUTH_SCOPES": "openid email",
    "GOOGLE_OAUTH_REDIRECT_URIS": "http://localhost:8000/auth/google/callback,http://127.0.0.1:8000/auth/google/callback",
    "GOOGLE_OAUTH_RETURN_ORIGINS": "http://localhost:3000,http://localhost:5173",
    "GOOGLE_OAUTH_PROVISIONING_MODE": "disabled",
    "GOOGLE_OAUTH_DEFAULT_USER_GROUP_HASH": "",
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

for _oauth_env_key, _oauth_env_value in _GOOGLE_OAUTH_TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(_oauth_env_key, _oauth_env_value)

# ─── Step 3: Now import test dependencies ────────────────────────────────────
import pytest

# ─── Constants ───────────────────────────────────────────────────────────────
TEST_JWT_SECRET = os.environ["JWT_SECRET_KEY"]

_OAUTH_REDIS_PATCH_LOCATIONS = (
    "src.Util.oauth_state.redis_client",
    "src.Util.oauth_rate_limit.redis_client",
    "src.Util.provider_init.redis_client",
    "src.routes.auth_google.redis_client",
)


def _base64url_json(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def build_fake_google_jwk(kid: str = "test-google-key-1") -> dict:
    """Return a JWKS-shaped RSA key fixture with non-production key material."""
    return {
        "kty": "RSA",
        "use": "sig",
        "kid": kid,
        "alg": "RS256",
        "n": "vR7testModulusForContractTestsOnlyNotARealKey",
        "e": "AQAB",
    }


def build_fake_google_claims(
    *,
    sub: str = "google-sub-test-001",
    email: str = "oauth-user@example.test",
    email_verified: bool = True,
    nonce: str = "test-oauth-nonce",
    audience: Optional[str] = None,
    issuer: str = "https://accounts.google.com",
    issued_at: Optional[int] = None,
    expires_in: int = 300,
    extra_claims: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Build sanitized Google ID-token claims for tests; never stores real tokens."""
    now = issued_at or int(time.time())
    claims = {
        "iss": issuer,
        "aud": audience or os.environ["GOOGLE_OAUTH_CLIENT_ID"],
        "sub": sub,
        "email": email,
        "email_verified": email_verified,
        "nonce": nonce,
        "iat": now,
        "exp": now + expires_in,
    }
    if extra_claims:
        claims.update(extra_claims)
    return claims


def build_fake_google_id_token(
    claims: Optional[Mapping[str, Any]] = None,
    *,
    kid: str = "test-google-key-1",
    alg: str = "RS256",
) -> str:
    """Create a structurally valid fake JWT for RED tests; it is not signed."""
    header = {"alg": alg, "kid": kid, "typ": "JWT"}
    body = dict(claims or build_fake_google_claims())
    return f"{_base64url_json(header)}.{_base64url_json(body)}.fake-signature"


@contextmanager
def _optional_patch_targets(targets: Iterable[str], value: Any):
    """Patch future module usage locations when present, skip while still RED."""
    with ExitStack() as stack:
        for target in targets:
            module_name, _, _ = target.rpartition(".")
            if not module_name:
                continue
            try:
                importlib.import_module(module_name)
            except ImportError:
                continue
            stack.enter_context(patch(target, value, create=True))
        yield


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_redis():
    """Provide a fakeredis instance that replaces the global redis_client.

    Usage:
        def test_something(mock_redis):
            # src.Util.db_config.redis_client is now a FakeStrictRedis
            ...
    """
    try:
        import fakeredis
    except ImportError:
        pytest.skip("fakeredis not installed")

    fake = fakeredis.FakeStrictRedis()
    with patch("src.Util.db_config.redis_client", fake), \
         patch("src.Util.cache_manager.redis_client", fake), \
         patch("src.Util.auth_lifecycle.redis_client", fake), \
         patch("src.Util.email.route_support.redis_client", fake), \
         patch("src.Util.db.db_enhanced.client", fake), \
         patch("src.Util.db.db_users.client", fake), \
         patch("src.Util.db.db_session_analytics.redis_client", fake), \
         patch("src.Util.system_metrics.redis_client", fake), \
         patch("src.routes.auth.redis_client", fake), \
         _optional_patch_targets(_OAUTH_REDIS_PATCH_LOCATIONS, fake):
        yield fake
    fake.flushall()


@pytest.fixture
def fake_google_jwk():
    return build_fake_google_jwk()


@pytest.fixture
def fake_google_jwks(fake_google_jwk):
    return {"keys": [fake_google_jwk]}


@pytest.fixture
def fake_google_claims():
    return build_fake_google_claims()


@pytest.fixture
def fake_google_id_token(fake_google_claims):
    return build_fake_google_id_token(fake_google_claims)


@pytest.fixture
def fake_google_token_response(fake_google_id_token):
    return {
        "token_type": "Bearer",
        "expires_in": 300,
        "scope": "openid email",
        "id_token": fake_google_id_token,
        "access_token": "fake-google-access-token-not-real",
    }


@pytest.fixture
def mock_db_connection():
    """Mock get_connection to return a fake MySQL connection."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = None
    mock_cursor.fetchone.return_value = None
    mock_cursor.fetchall.return_value = []
    mock_cursor.nextset.return_value = None
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.close = MagicMock()
    with patch("src.Util.db_config.get_connection", return_value=mock_conn):
        yield mock_conn


@pytest.fixture
def jwt_secret():
    """Return the test JWT secret key."""
    return TEST_JWT_SECRET


@pytest.fixture
def frozen_time():
    """Freeze time for deterministic JWT tests."""
    try:
        from freezegun import freeze_time
    except ImportError:
        pytest.skip("freezegun not installed")

    with freeze_time("2026-04-15 12:00:00") as frozen:
        yield frozen


@pytest.fixture
def debug_mode_on():
    """Ensure DEBUG_MODE is True for the duration of the test."""
    import src.Util.error_handler as eh
    original = eh.DEBUG_MODE
    eh.DEBUG_MODE = True
    yield
    eh.DEBUG_MODE = original


@pytest.fixture
def debug_mode_off():
    """Ensure DEBUG_MODE is False for the duration of the test."""
    import src.Util.error_handler as eh
    original = eh.DEBUG_MODE
    eh.DEBUG_MODE = False
    yield
    eh.DEBUG_MODE = original
