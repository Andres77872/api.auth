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
_RUNNER_SAFETY_ENV = {
    name: os.environ.get(name)
    for name in (
        "PYTEST_MEM_LIMIT_MB",
        "PYTEST_TIMEOUT_SECONDS",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
    )
}
if ENV_TEST_PATH.exists():
    try:
        from dotenv import load_dotenv

        # Host-side tests deliberately let the synthetic test file replace an
        # inherited developer shell environment.  The Docker E2E runner sets this
        # to false because Compose has already replaced loopback hosts with service
        # DNS names (mysql-test, redis-test, and mailpit-test).
        _dotenv_override = os.environ.get("PYTEST_DOTENV_OVERRIDE", "true").strip().lower()
        load_dotenv(
            ENV_TEST_PATH,
            override=_dotenv_override not in {"0", "false", "no", "off"},
        )
    except ImportError:
        # python-dotenv not installed — set env vars manually
        pass

# Host tests intentionally let .env.test replace application configuration, but
# the certified runner's process-safety controls are not application settings.
# Restore those exported values before installing the address-space/timer rails.
for _safety_name, _safety_value in _RUNNER_SAFETY_ENV.items():
    if _safety_value is not None:
        os.environ[_safety_name] = _safety_value

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

_PATREON_TEST_TIER_MAP_JSON = json.dumps(
    {
        "campaigns": [
            {
                "campaign_id": "campaign-mw-alpha",
                "tiers": [
                    {
                        "tier_id": "tier-mw-alpha-artisan",
                        "plan_code": "magic_worlds_plus",
                        "tier_code": "artisan",
                        "tier_name": "Artisan",
                        "priority": 10,
                    },
                ],
            },
            {
                "campaign_id": "campaign-mw-beta",
                "tiers": [
                    {
                        "tier_id": "tier-mw-beta-architect",
                        "plan_code": "magic_worlds_pro",
                        "tier_code": "architect",
                        "tier_name": "Architect",
                        "priority": 90,
                    }
                ],
            },
        ]
    },
    separators=(",", ":"),
    sort_keys=True,
)

# Phase 3 Patreon RED harness defaults. These are synthetic-only values and all
# feature flags remain disabled until individual tests opt in with monkeypatch.
_PATREON_TEST_ENV_DEFAULTS = {
    "PATREON_LINKING_ENABLED": "false",
    "PATREON_WEBHOOKS_ENABLED": "false",
    "PATREON_SYNC_ENABLED": "false",
    "PATREON_S2S_ENTITLEMENT_ENABLED": "false",
    "PATREON_CREATOR_TOKEN_REFRESH_ENABLED": "false",
    "PATREON_RAW_PAYLOAD_CAPTURE_ENABLED": "false",
    "PATREON_API_BASE_URL": "http://patreon.test/api/oauth2/v2",
    "PATREON_OAUTH_TOKEN_URL": "http://patreon.test/api/oauth2/token",
    "PATREON_CREATOR_ACCESS_TOKEN": "test-patreon-creator-access-token-not-real",
    "PATREON_CREATOR_REFRESH_TOKEN": "test-patreon-creator-refresh-token-not-real",
    "PATREON_CLIENT_ID": "test-patreon-client-id-not-real",
    "PATREON_CLIENT_SECRET": "test-patreon-client-secret-not-real",
    "PATREON_WEBHOOK_SECRET": "test-patreon-webhook-secret-not-real",
    "PATREON_WEBHOOK_ID": "test-patreon-webhook-id-not-real",
    "PATREON_S2S_BEARER_TOKEN": "test-patreon-s2s-bearer-token-not-real",
    "PATREON_USER_AGENT": "api.auth Patreon tests (no real provider calls)",
    "PATREON_PROVIDER_SUB_PEPPER": "test-patreon-provider-sub-pepper-not-real-min-32-bytes!!",
    "PATREON_EMAIL_HASH_PEPPER": "test-patreon-email-hash-pepper-not-real-min-32-bytes!!",
    "PATREON_PROOF_TOKEN_PEPPER": "test-patreon-proof-token-pepper-not-real-min-32-bytes!!",
    "PATREON_ID_HMAC_SECRET": "test-patreon-id-hmac-secret-not-real-min-32-bytes!!",
    "PATREON_HMAC_SECRET": "test-patreon-hmac-secret-not-real-min-32-bytes!!",
    "PATREON_WEBHOOK_DELIVERY_HASH_PEPPER": "test-patreon-delivery-hash-pepper-not-real-min-32-bytes!!",
    "PATREON_PROVIDER_TOKEN_ENCRYPTION_KEY": "test-patreon-provider-token-encryption-key-not-real",
    "PATREON_PROVIDER_TOKEN_ENCRYPTION_KEY_ID": "test-key-id-not-real",
    "PATREON_CAMPAIGN_IDS": "campaign-mw-alpha,campaign-mw-beta",
    "PATREON_CAMPAIGN_TIER_MAP": _PATREON_TEST_TIER_MAP_JSON,
    "PATREON_TIER_MAP_JSON": _PATREON_TEST_TIER_MAP_JSON,
    "PATREON_TIER_MAP_FILE": "",
    "PATREON_ALLOWED_WEBHOOK_EVENTS": (
        "members:create,members:update,members:delete,"
        "members:pledge:create,members:pledge:update,members:pledge:delete"
    ),
    "PATREON_PROOF_TOKEN_TTL_SECONDS": "900",
    "PATREON_PROOF_RETENTION_AFTER_EXPIRY_HOURS": "24",
    "PATREON_WEBHOOK_DELIVERY_RETENTION_DAYS": "90",
    "PATREON_RAW_PAYLOAD_RETENTION_DAYS": "30",
    "PATREON_API_TIMEOUT_SECONDS": "15",
    "PATREON_API_CONNECT_TIMEOUT_SECONDS": "5",
    "PATREON_API_PAGE_SIZE": "1000",
    "PATREON_API_MAX_PAGES_PER_SYNC": "0",
    "PATREON_API_RETRY_MAX_ATTEMPTS": "3",
    "PATREON_API_RETRY_BACKOFF_SECONDS": "1,5,15",
    "PATREON_API_RETRY_JITTER_SECONDS": "5",
    "PATREON_CREATOR_TOKEN_REFRESH_MARGIN_SECONDS": "604800",
    "PATREON_SYNC_INTERVAL_SECONDS": "21600",
    "PATREON_SYNC_JITTER_SECONDS": "900",
    "PATREON_SYNC_STALE_AFTER_SECONDS": "86400",
    "PATREON_SYNC_WORKER_POLL_SECONDS": "30",
    "PATREON_SYNC_WORKER_BATCH_SIZE": "25",
    "PATREON_SYNC_JOB_LEASE_SECONDS": "300",
    "PATREON_SYNC_MAX_ATTEMPTS": "8",
    "PATREON_SYNC_BACKOFF_SECONDS": "60,300,900,3600,10800,21600",
    "PATREON_WEBHOOK_SIGNATURE_FAILURE_ALERT_LIMIT": "1",
    "PATREON_WEBHOOK_SIGNATURE_FAILURE_ALERT_WINDOW_SECONDS": "60",
    "PATREON_LINK_REQUEST_RATE_LIMIT": "5",
    "PATREON_LINK_REQUEST_RATE_WINDOW_SECONDS": "3600",
    "PATREON_PROOF_REQUEST_RATE_LIMIT": "3",
    "PATREON_PROOF_REQUEST_RATE_WINDOW_SECONDS": "3600",
    "PATREON_PROOF_CONSUME_RATE_LIMIT": "5",
    "PATREON_PROOF_CONSUME_RATE_WINDOW_SECONDS": "900",
    "PATREON_UNLINK_RATE_LIMIT": "5",
    "PATREON_UNLINK_RATE_WINDOW_SECONDS": "300",
    "PATREON_STATUS_RATE_LIMIT": "60",
    "PATREON_STATUS_RATE_WINDOW_SECONDS": "60",
    "PATREON_S2S_RATE_LIMIT": "120",
    "PATREON_S2S_RATE_WINDOW_SECONDS": "60",
    "PATREON_WEBHOOK_SIGNATURE_FAILURE_RATE_LIMIT": "30",
    "PATREON_WEBHOOK_SIGNATURE_FAILURE_RATE_WINDOW_SECONDS": "60",
    "PATREON_SYNC_ENQUEUE_RATE_LIMIT": "30",
    "PATREON_SYNC_ENQUEUE_RATE_WINDOW_SECONDS": "300",
    "PATREON_API_CLIENT_RATE_LIMIT": "100",
    "PATREON_API_CLIENT_RATE_WINDOW_SECONDS": "2",
    "PATREON_API_ACCESS_TOKEN_RATE_LIMIT": "100",
    "PATREON_API_ACCESS_TOKEN_RATE_WINDOW_SECONDS": "60",
    "PATREON_API_EDGE_4XX_RATE_LIMIT": "2000",
    "PATREON_API_EDGE_4XX_RATE_WINDOW_SECONDS": "600",
    "RUN_PATREON_LOCAL_E2E": "false",
    "RUN_PATREON_E2E": "false",
    "PATREON_LIVE_TEST_USER_HASH": "",
    "PATREON_TEST_CAMPAIGN_ID": "",
    "PATREON_TEST_MEMBER_EMAIL": "",
    "PATREON_E2E_CREATOR_TOKEN": "",
}

for _oauth_env_key, _oauth_env_value in _GOOGLE_OAUTH_TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(_oauth_env_key, _oauth_env_value)

for _patreon_env_key, _patreon_env_value in _PATREON_TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(_patreon_env_key, _patreon_env_value)

# ─── Step 3: Now import test dependencies ────────────────────────────────────
import pytest

from tests.support import make_db_connection_mock

# ─── Step 3b: Safety rails ───────────────────────────────────────────────────
# These tests drive real `src.Util.db` code against mock cursors.  That code drains
# result sets with `while cur.nextset():`, which never terminates against a cursor
# double that has not stubbed `nextset` — and MagicMock records every call it gets,
# so the loop allocates until the box swaps itself to death.  tests/support.py stops
# that at the source; these two rails make sure the *next* such bug fails a test
# instead of taking the machine down with it.
#
#   PYTEST_MEM_LIMIT_MB=0     leaves any inherited address-space cap unchanged
#   PYTEST_TIMEOUT_SECONDS=0  disables the per-test wall-clock limit
_MEM_LIMIT_MB = int(os.environ.get("PYTEST_MEM_LIMIT_MB", "1536"))
_TIMEOUT_SECONDS = int(os.environ.get("PYTEST_TIMEOUT_SECONDS", "60"))


def _install_address_space_cap(limit_mb: int) -> int | None:
    """Install a non-weakening process cap and return its byte value.

    A parent shell or container may already impose a stricter limit.  Never raise
    that soft limit: doing so would turn a safety rail into a safety regression.
    """
    if limit_mb <= 0:
        return None
    try:
        import resource
    except ImportError:  # non-POSIX
        return None

    requested = limit_mb * 1024 * 1024
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)

    candidates = [requested]
    if soft != resource.RLIM_INFINITY:
        candidates.append(soft)
    if hard != resource.RLIM_INFINITY:
        candidates.append(hard)
    limit = min(candidates)

    if soft == limit:
        return limit

    try:
        resource.setrlimit(resource.RLIMIT_AS, (limit, hard))
    except (ValueError, OSError) as exc:
        raise RuntimeError(
            f"could not install pytest address-space cap of {limit_mb} MiB"
        ) from exc

    installed_soft, _ = resource.getrlimit(resource.RLIMIT_AS)
    if installed_soft == resource.RLIM_INFINITY or installed_soft > limit:
        raise RuntimeError(
            f"pytest address-space cap was not enforced (requested {limit_mb} MiB)"
        )
    return installed_soft


_install_address_space_cap(_MEM_LIMIT_MB)


def pytest_collection_modifyitems(items):
    """Attach layer markers by directory so resource-safe selection is reliable."""
    root = Path(__file__).resolve().parent.parent
    for item in items:
        try:
            relative = item.path.resolve().relative_to(root)
        except (AttributeError, ValueError):
            continue

        parts = relative.parts
        if len(parts) < 2 or parts[0] != "tests":
            continue

        layer = parts[1]
        if layer in {"unit", "integration", "e2e", "static"}:
            item.add_marker(getattr(pytest.mark, layer))

        if item.path.name in {
            "test_patreon_live_opt_in.py",
            "test_stripe_live_opt_in.py",
        }:
            item.add_marker(pytest.mark.live_provider)

        if (
            item.path.name == "test_slice11_request_validation.py"
            and item.name == "test_oversized_post_rejected"
        ):
            item.add_marker(pytest.mark.large_payload)


@pytest.fixture(autouse=True)
def _per_test_timeout():
    """Turn a hung test into a failing test.

    SIGALRM only interrupts Python bytecode, which is exactly what a runaway
    `while cur.nextset():` loop is made of.
    """
    import signal

    if _TIMEOUT_SECONDS <= 0 or not hasattr(signal, "SIGALRM"):
        yield
        return

    def _timed_out(_signum, _frame):
        raise TimeoutError(
            f"test exceeded {_TIMEOUT_SECONDS}s — suspect a non-terminating loop "
            f"(a cursor double that does not stub nextset() will do this)"
        )

    previous = signal.signal(signal.SIGALRM, _timed_out)
    signal.setitimer(signal.ITIMER_REAL, _TIMEOUT_SECONDS)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


@pytest.fixture(scope="session", autouse=True)
def _cheap_argon2_for_tests():
    """Run Argon2id at a throwaway cost for the whole session.

    Production is tuned to 64 MiB per hash.  The suite hashes and verifies on every
    login, register, and API-key path — including the dummy-hash verification that
    equalizes timing on *failed* logins — so at production cost the suite burns a
    64 MiB spike and ~100 ms of CPU per request.  The code path under test is
    identical; only the work factor changes.
    """
    from argon2 import PasswordHasher

    import src.Util.db.db_users as db_users
    import src.Util.password_security as password_security

    cheap = PasswordHasher(
        time_cost=1, memory_cost=64, parallelism=1, hash_len=32, salt_len=16
    )
    original_hasher = password_security.password_manager.hasher
    original_dummy = db_users._DUMMY_LOGIN_PASSWORD_HASH

    password_security.password_manager.hasher = cheap
    db_users._DUMMY_LOGIN_PASSWORD_HASH = cheap.hash("dummy-login-password-not-real")
    try:
        yield
    finally:
        password_security.password_manager.hasher = original_hasher
        db_users._DUMMY_LOGIN_PASSWORD_HASH = original_dummy


# ─── Constants ───────────────────────────────────────────────────────────────
TEST_JWT_SECRET = os.environ["JWT_SECRET_KEY"]
PATREON_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "patreon"
PATREON_MANIFEST_PATH = PATREON_FIXTURE_ROOT / "manifest.json"
PATREON_REDACTED_VALUE = "[REDACTED]"

_PATREON_SECRET_ENV_NAMES = (
    "PATREON_CREATOR_ACCESS_TOKEN",
    "PATREON_CREATOR_REFRESH_TOKEN",
    "PATREON_CLIENT_SECRET",
    "PATREON_WEBHOOK_SECRET",
    "PATREON_S2S_BEARER_TOKEN",
    "PATREON_PROVIDER_SUB_PEPPER",
    "PATREON_EMAIL_HASH_PEPPER",
    "PATREON_PROOF_TOKEN_PEPPER",
    "PATREON_ID_HMAC_SECRET",
    "PATREON_HMAC_SECRET",
    "PATREON_WEBHOOK_DELIVERY_HASH_PEPPER",
    "PATREON_PROVIDER_TOKEN_ENCRYPTION_KEY",
    "PATREON_E2E_CREATOR_TOKEN",
)
_PATREON_SENSITIVE_KEY_FRAGMENTS = (
    "authorization",
    "bearer",
    "token",
    "secret",
    "pepper",
    "signature",
    "payload",
    "raw_body",
    "patreon_email",
    "raw_patreon_email",
    "masked_patreon_email",
    "patreon_user_id",
    "patreon_member_id",
    "patreon_campaign_id",
    "patreon_tier_id",
    "provider_sub_hash",
    "provider_sub_fingerprint",
    "hash_prefix",
    "audit_rows",
)
_PATREON_FIXTURE_ONLY_SECRET_VALUES = (
    "patreon_webhook_secret_fixture_do_not_use",
    "s2s_bearer_fixture_do_not_log",
    "creator_access_token_fixture_do_not_log",
    "creator_refresh_token_fixture_do_not_log",
)

_OAUTH_REDIS_PATCH_LOCATIONS = (
    "src.Util.oauth_state.redis_client",
    "src.Util.oauth_rate_limit.redis_client",
    "src.Util.provider_init.redis_client",
    "src.routes.auth_google.redis_client",
)


def _base64url_json(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _patreon_sensitive_values() -> tuple[str, ...]:
    values = [os.environ.get(name, "") for name in _PATREON_SECRET_ENV_NAMES]
    values.extend(_PATREON_FIXTURE_ONLY_SECRET_VALUES)
    return tuple(value for value in values if value)


def load_patreon_manifest() -> dict[str, Any]:
    """Load the sanitized Patreon fixture manifest."""
    return json.loads(PATREON_MANIFEST_PATH.read_text(encoding="utf-8"))


def load_patreon_fixture(relative_path: str, *, as_bytes: bool = False) -> Any:
    """Load a sanitized Patreon fixture under tests/fixtures/patreon."""
    path = (PATREON_FIXTURE_ROOT / relative_path).resolve()
    if PATREON_FIXTURE_ROOT.resolve() not in path.parents and path != PATREON_FIXTURE_ROOT.resolve():
        raise ValueError("Patreon fixture path must stay under tests/fixtures/patreon")
    if as_bytes:
        return path.read_bytes()
    return json.loads(path.read_text(encoding="utf-8"))


def load_patreon_member_fixture(name: str = "active_mapped") -> dict[str, Any]:
    manifest = load_patreon_manifest()
    return load_patreon_fixture(manifest["member_fixtures"][name])


def load_patreon_webhook_fixture(name: str = "member_update_active") -> bytes:
    manifest = load_patreon_manifest()
    return load_patreon_fixture(manifest["webhook_fixtures"][name], as_bytes=True)


def load_patreon_s2s_contract_fixture(name: str = "linked") -> dict[str, Any]:
    manifest = load_patreon_manifest()
    return load_patreon_fixture(manifest["s2s_contract_fixtures"][name])


def redact_patreon_test_value(value: Any, *, replacement: str = PATREON_REDACTED_VALUE) -> Any:
    """Return a copy with Patreon server-only values redacted for test assertions."""
    if isinstance(value, Mapping):
        redacted: dict[Any, Any] = {}
        for key, child in value.items():
            lowered_key = str(key).lower()
            if any(fragment in lowered_key for fragment in _PATREON_SENSITIVE_KEY_FRAGMENTS):
                redacted[key] = replacement
            else:
                redacted[key] = redact_patreon_test_value(child, replacement=replacement)
        return redacted
    if isinstance(value, list):
        return [redact_patreon_test_value(item, replacement=replacement) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_patreon_test_value(item, replacement=replacement) for item in value)
    if isinstance(value, str):
        sanitized = value
        for secret_value in _patreon_sensitive_values():
            sanitized = sanitized.replace(secret_value, replacement)
        return sanitized
    return value


def assert_no_patreon_secret_leak(value: Any, *, context: str = "Patreon test output") -> None:
    """Fail if fake/live Patreon secret material appears in captured test output."""
    serialized = json.dumps(value, sort_keys=True, default=str)
    for secret_value in _patreon_sensitive_values():
        assert secret_value not in serialized, f"{context} leaked Patreon secret-like test material"


class FakePatreonAPI:
    """Small in-memory fake for Patreon API seams; never performs network I/O."""

    def __init__(self, members: Optional[Mapping[str, Any]] = None) -> None:
        default_members = {
            name: load_patreon_member_fixture(name)
            for name in load_patreon_manifest()["member_fixtures"]
        }
        self.members = _json_clone(dict(members or default_members))
        self.calls: list[dict[str, Any]] = []

    def list_campaign_members(self, campaign_key: str = "active_mapped", **metadata: Any) -> dict[str, Any]:
        self.calls.append(redact_patreon_test_value({"operation": "list_campaign_members", **metadata}))
        return _json_clone(self.members[campaign_key])

    async def async_list_campaign_members(self, campaign_key: str = "active_mapped", **metadata: Any) -> dict[str, Any]:
        return self.list_campaign_members(campaign_key, **metadata)

    def get_member(self, name: str = "active_mapped") -> dict[str, Any]:
        self.calls.append({"operation": "get_member", "fixture": name})
        return _json_clone(self.members[name])


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
def patreon_test_env(monkeypatch):
    """Apply safe disabled Patreon env defaults for one test."""
    for key, value in _PATREON_TEST_ENV_DEFAULTS.items():
        monkeypatch.setenv(key, value)
    return dict(_PATREON_TEST_ENV_DEFAULTS)


@pytest.fixture
def patreon_fixture_root() -> Path:
    return PATREON_FIXTURE_ROOT


@pytest.fixture
def patreon_manifest() -> dict[str, Any]:
    return load_patreon_manifest()


@pytest.fixture
def fake_patreon_member_fixture():
    return load_patreon_member_fixture


@pytest.fixture
def fake_patreon_webhook_fixture():
    return load_patreon_webhook_fixture


@pytest.fixture
def fake_patreon_s2s_contract_fixture():
    return load_patreon_s2s_contract_fixture


@pytest.fixture
def fake_patreon_api() -> FakePatreonAPI:
    return FakePatreonAPI()


@pytest.fixture
def fake_patreon_s2s_token(monkeypatch) -> str:
    token = _PATREON_TEST_ENV_DEFAULTS["PATREON_S2S_BEARER_TOKEN"]
    monkeypatch.setenv("PATREON_S2S_BEARER_TOKEN", token)
    return token


@pytest.fixture
def fake_patreon_s2s_headers(fake_patreon_s2s_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {fake_patreon_s2s_token}",
        "User-Agent": "patreon-s2s-test-fixture",
    }


@pytest.fixture
def patreon_redaction_helper():
    return redact_patreon_test_value


@pytest.fixture
def patreon_no_secret_log_guard(caplog):
    """Opt-in guard: fail if captured logs contain Patreon secret-like values."""
    yield
    assert_no_patreon_secret_leak(
        "\n".join(record.getMessage() for record in caplog.records),
        context="captured pytest logs",
    )


@pytest.fixture
def mock_db_connection():
    """Mock get_connection to return a fake MySQL connection."""
    mock_conn = make_db_connection_mock()
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
