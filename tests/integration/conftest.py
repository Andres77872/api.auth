"""
Integration test infrastructure — Slice 0

Fixtures for httpx.AsyncClient against the real FastAPI app, fakeredis injection,
DB boundary patching, and test user factories.

CRITICAL: We patch at the USAGE location (where the name is looked up in the
importing module's namespace), not the source definition.
"""

import copy
import hashlib
import importlib
import json
import uuid
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional
from unittest.mock import patch, MagicMock
from urllib.parse import urlsplit, urlunsplit

import fakeredis
import httpx
import pytest

from src.main import app as fastapi_app


# ─── App & Client Fixtures ───────────────────────────────────────────────────

@pytest.fixture
def app():
    return fastapi_app


@pytest.fixture
def app_with_request_validation():
    """App with RequestValidationMiddleware but no auth/audit middleware."""
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse
    from src.middleware.error_handler import register_exception_handlers
    from src.middleware.request_validation import RequestValidationMiddleware
    from src.routes import (
        auth, users, user_types_auth, projects,
        admin_user_groups, admin_project_groups, admin_dashboard, system, bulk_operations, global_roles, permission_assignments
    )

    test_app = FastAPI(
        title='Test App',
        description='Test',
        version='1.0.0',
    )
    register_exception_handlers(test_app)

    @test_app.get("/ping")
    async def ping():
        return PlainTextResponse("", status_code=204)

    test_app.include_router(auth.router, tags=['Authentication'])
    test_app.include_router(users.router, tags=['User Management'])
    test_app.include_router(user_types_auth.router, tags=['User Type Management'])
    test_app.include_router(projects.router, tags=['Project Management'])
    test_app.include_router(admin_user_groups.router, tags=['Admin - User Groups'])
    test_app.include_router(admin_project_groups.router, tags=['Admin - Project Groups'])
    test_app.include_router(admin_dashboard.router, tags=['Admin Dashboard'])
    test_app.include_router(system.router, tags=['System Information'])
    test_app.include_router(bulk_operations.router, tags=['Bulk Operations'])
    test_app.include_router(global_roles.router, tags=['Global Role System'])
    test_app.include_router(permission_assignments.router, tags=['Permission Assignments'])
    test_app.add_middleware(RequestValidationMiddleware)
    return test_app


@pytest.fixture
async def client_with_request_validation(app_with_request_validation):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_with_request_validation),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# ─── Fakeredis ───────────────────────────────────────────────────────────────

_OAUTH_REDIS_PATCH_LOCATIONS = (
    "src.Util.oauth_state.redis_client",
    "src.Util.oauth_rate_limit.redis_client",
    "src.Util.provider_init.redis_client",
    "src.routes.auth_google.redis_client",
)


@contextmanager
def _optional_patch_targets(targets: Iterable[str], value: Any):
    """Patch forward-referenced OAuth modules only once they exist."""
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

@pytest.fixture
def fake_redis():
    """Provide a fakeredis instance patched at ALL usage locations."""
    fake = fakeredis.FakeStrictRedis()
    # Create a valid session data mock for the decorators' validate_session
    # AND for AuthContextMiddleware which does lazy import from src.Util.db
    session_mock = MagicMock()
    session_mock.user_id = "1"
    session_mock.user_hash = "usr-test-001"
    session_mock.user_type = "consumer"
    session_mock.project_hash = "prj-test-001"
    session_mock.project_name = "Test Project"
    session_mock.project_id = "1"
    session_mock.permissions = []
    session_mock.groups = []
    session_mock.session_token = "test-token"
    session_mock.session_length = 259200
    session_mock.username = "testuser"

    user_mock = MagicMock()
    user_mock.id = "1"
    user_mock.user_hash = "usr-test-001"
    user_mock.username = "testuser"
    user_mock.email = "test@example.com"
    user_mock.user_type = "consumer"

    # Patch the singleton instance's redis attribute (created at import time)
    from src.Util.cache_manager import cache_manager
    original_redis = cache_manager.redis

    with patch("src.Util.db_config.redis_client", fake), \
         patch("src.Util.cache_manager.redis_client", fake), \
         patch("src.Util.auth_lifecycle.redis_client", fake), \
         patch("src.Util.email.route_support.redis_client", fake), \
         patch("src.Util.db.db_enhanced.client", fake), \
         patch("src.Util.db.db_users.client", fake), \
         patch("src.Util.db.db_session_analytics.redis_client", fake), \
         patch("src.Util.system_metrics.redis_client", fake), \
         patch("src.routes.auth.redis_client", fake), \
         patch("src.Util.decorators.validate_session", return_value=session_mock), \
         patch("src.Util.decorators.get_user_by_hash", return_value=user_mock), \
         patch("src.Util.db.validate_session", return_value=session_mock), \
         _optional_patch_targets(_OAUTH_REDIS_PATCH_LOCATIONS, fake):
        # Directly set the singleton's redis attribute (cannot be patched after import)
        cache_manager.redis = fake
        yield fake
        cache_manager.redis = original_redis
    fake.flushall()


# ─── DB Connection — patch at usage locations ────────────────────────────────

def _mock_db_connection():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = None
    mock_cursor.fetchone.return_value = None
    mock_cursor.fetchall.return_value = []
    mock_cursor.nextset.return_value = None
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    return mock_conn


# Modules confirmed to import `from src.Util.db_config import get_connection`:
_DB_CONN_PATCH_LOCATIONS = [
    "src.Util.api_audit_logger.get_connection",
    "src.Util.activity_logger.get_connection",
    "src.Util.db.db_error_logger.get_connection",
    "src.Util.db.db_users.get_connection",
    "src.Util.db.db_projects.get_connection",
    "src.Util.db.db_user_groups.get_connection",
    "src.Util.db.db_project_groups.get_connection",
    "src.Util.db.db_global_roles.get_connection",
    "src.Util.db.db_permission_assignments.get_connection",
    "src.Util.db.db_session_analytics.get_connection",
    "src.Util.db.db_audit_analytics.get_connection",
    "src.Util.db.db_api_keys.get_connection",
    "src.Util.db.db_email.get_connection",
    "src.Util.system_metrics.get_connection",
    "src.Util.bulk_operations.get_connection",
]


@contextmanager
def _patch_all_db_connections(mock_conn):
    """Patch get_connection at source AND all usage locations."""
    patches = []
    # Source
    patches.append(patch("src.Util.db_config.get_connection", return_value=mock_conn))
    # Usage locations
    for loc in _DB_CONN_PATCH_LOCATIONS:
        patches.append(patch(loc, return_value=mock_conn))
    for p in patches:
        p.start()
    try:
        yield mock_conn
    finally:
        for p in patches:
            p.stop()


@pytest.fixture
def patched_db_connection():
    mock_conn = _mock_db_connection()
    with _patch_all_db_connections(mock_conn) as conn:
        yield conn


# ─── Audit Logger — patch at middleware usage location ───────────────────────

@pytest.fixture
def patched_audit_logger():
    mock_cls = MagicMock()
    excluded_paths = (
        "/ping",
        "/health",
        "/metrics",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/auth/validate",
    )

    def should_log_request(path, method):
        if method == "OPTIONS":
            return False
        path_without_query = path.split("?")[0]
        return not any(
            path_without_query == excluded or path_without_query.startswith(excluded + "/")
            for excluded in excluded_paths
        )

    mock_cls.should_log_request.side_effect = should_log_request
    mock_cls.log_request = MagicMock()
    mock_cls.log_response = MagicMock()
    mock_cls.extract_resource_info.return_value = (None, None)
    mock_cls.is_security_event.return_value = False
    mock_cls.generate_tags.return_value = []
    mock_cls.filter_sensitive_data = lambda d: d
    with patch("src.Util.api_audit_logger.APIAuditLogger", mock_cls), \
         patch("src.middleware.api_audit.APIAuditLogger", mock_cls):
        yield mock_cls


@pytest.fixture
def patched_audit_ids():
    with patch("src.middleware.api_audit.generate_audit_id", return_value="audit-test-id"), \
         patch("src.middleware.api_audit.generate_request_id", return_value="req-test-id"):
        yield


# ─── DB Error Logger — patch at error handler usage location ─────────────────

@pytest.fixture
def patched_db_error_logger():
    with patch("src.middleware.error_handler.log_app_exception_to_db", MagicMock()), \
         patch("src.middleware.error_handler.log_generic_exception_to_db", MagicMock()), \
         patch("src.middleware.error_handler.log_http_exception_to_db", MagicMock()), \
         patch("src.middleware.error_handler.log_validation_exception_to_db", MagicMock()):
        yield


# ─── Cache Manager ───────────────────────────────────────────────────────────

@pytest.fixture
def patched_cache_manager():
    """Patch cache_manager at source AND all usage locations."""
    mock = MagicMock()
    mock.get_cache_stats.return_value = {
        "hit_rate": 0.0, "miss_rate": 0.0,
        "total_keys": 0, "memory_used": "0 KB",
    }
    mock.clear_all_cache.return_value = True
    mock.invalidate_user_cache.return_value = True
    mock.invalidate_project_cache.return_value = True
    mock.get_session.return_value = None
    mock.get_session_full.return_value = None
    mock.set_session = MagicMock()
    mock.set_session_full = MagicMock(return_value=True)
    mock.delete_session = MagicMock()
    with patch("src.Util.cache_manager.cache_manager", mock), \
         patch("src.Util.db.db_enhanced.cache_manager", mock), \
         patch("src.routes.system.cache_manager", mock):
        yield mock


# ─── Activity Logger ─────────────────────────────────────────────────────────

async def _noop_access_logger(*args, **kwargs):
    return None


@pytest.fixture(autouse=True)
def patched_request_access_logger():
    with patch("src.middleware.request_validation.logger", _noop_access_logger):
        yield


@pytest.fixture
def patched_activity_logger():
    with patch("src.Util.activity_logger.ActivityLogger") as mock:
        yield mock


# ─── Combined Infrastructure ─────────────────────────────────────────────────

@pytest.fixture
def integration_env(
    fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids,
    patched_db_connection, patched_db_error_logger,
):
    yield {
        "redis": fake_redis,
        "cache": patched_cache_manager,
        "activity": patched_activity_logger,
        "audit": patched_audit_logger,
        "db_conn": patched_db_connection,
    }


@pytest.fixture
def e2e_env(integration_env):
    """Compatibility alias for ASGI lifecycle tests mirrored from tests/e2e."""
    return integration_env


# ─── Factories ───────────────────────────────────────────────────────────────

def _make_mock_user(
    user_id: str = "1", user_hash: str = "usr-test-hash-001",
    username: str = "testuser", email: str = "test@example.com",
    user_type: str = "consumer", is_active: bool = True,
    assigned_project_id: Optional[str] = None,
    password_hash: str = "$argon2id$fake",
    created_at: Optional[datetime] = None,
):
    user = MagicMock()
    user.id = user_id
    user.user_hash = user_hash
    user.username = username
    user.email = email
    user.user_type = user_type
    user.is_active = is_active
    user.assigned_project_id = assigned_project_id
    user.password_hash = password_hash
    user.created_at = created_at or datetime.now(timezone.utc)
    user.updated_at = None
    user.last_login = None
    user.assigned_at = None
    return user


def _make_mock_project(
    project_id: str = "1", project_hash: str = "prj-test-hash-001",
    project_name: str = "Test Project", project_description: str = "A test project",
    owner_id: str = "1", is_active: bool = True,
    project_created: Optional[datetime] = None,
):
    project = MagicMock()
    project.id = project_id
    project.project_hash = project_hash
    project.project_name = project_name
    project.project_description = project_description
    project.owner_id = owner_id
    project.is_active = is_active
    project.project_created = project_created or datetime.now(timezone.utc)
    project.updated_at = None
    return project


def _make_mock_user_group(group_id: str = "1", group_hash: str = "grp-test-hash-001", group_name: str = "Test Group"):
    group = MagicMock()
    group.id = group_id
    group.group_hash = group_hash
    group.group_name = group_name
    return group


@pytest.fixture
def user_factory():
    return _make_mock_user


@pytest.fixture
def project_factory():
    return _make_mock_project


@pytest.fixture
def user_group_factory():
    return _make_mock_user_group


# ─── Session Helpers ─────────────────────────────────────────────────────────

def make_session_payload(
    user_hash: str = "usr-test-hash-001", user_id: str = "1",
    user_type: str = "consumer", project_hash: str = "prj-test-hash-001",
    project_name: str = "Test Project", project_id: str = "1",
    permissions: list = None, groups: list = None, session_token: str = None,
):
    if session_token is None:
        session_token = f"test-token-{uuid.uuid4().hex[:16]}"
    return {
        "session_id": 12345, "user_hash": user_hash, "user_id": user_id,
        "user_type": user_type, "project_hash": project_hash,
        "project_name": project_name, "project_id": project_id,
        "permissions": permissions or [], "groups": groups or [],
        "session_token": session_token, "session_length": 259200,
    }


def create_test_session(fake_redis, token: str, payload: dict) -> str:
    fake_redis.set(f"session:{token}", json.dumps(payload, default=str), ex=259200)
    return token


# ─── DBPatcher ───────────────────────────────────────────────────────────────

class DBPatcher:
    OAUTH_EXTERNAL_ACCOUNT_PATCHES = [
        "get_user_by_external_account",
        "link_external_account",
        "unlink_external_account",
        "touch_external_account_last_seen",
        "create_consumer_user_from_external_account",
    ]

    DEFAULT_PATCHES = [
        "get_user_by_credentials", "get_user_by_hash",
        "get_user_groups_for_user", "get_user_accessible_projects",
        "get_project_by_hash", "validate_session",
        "is_root_user", "is_admin_user",
        "check_username_email_available", "get_user_group_by_hash",
        "get_projects_for_user_group", "enhanced_register",
        "count_users", "count_projects", "count_user_groups",
        "count_project_permission_groups", "list_all_projects",
        "search_projects", "get_user_project_permissions",
        "get_user_type_info", "get_user_group_membership",
        "get_user_effective_permissions", "update_user", "delete_user",
        "list_users_with_access", "get_user_type",
        "invalidate_user_sessions", "create_project",
        "update_project", "delete_project", "get_project_members_page",
        "get_project_stats",
        "get_user_groups_for_project", "get_permission_groups_for_project",
        "get_user_groups_in_project", "get_user_groups_in_project_by_hash",
        "check_user_has_permission_extended", "get_user_all_permissions",
        "get_user_permission_sources",
        # Audit analytics
        "get_audit_logs", "count_audit_logs", "get_audit_statistics",
        "get_security_events", "get_failed_requests", "get_user_api_activity_summary",
        "get_user_by_id",
    ] + OAUTH_EXTERNAL_ACCOUNT_PATCHES

    def __init__(self, extra_patches: list = None, exclude_patches: list = None):
        self.extra = extra_patches or []
        self.exclude = set(exclude_patches or [])
        self._patches = []
        self.patches = {}

    def __enter__(self):
        import src.Util.db as db_module
        all_names = [n for n in set(self.DEFAULT_PATCHES + self.extra) if n not in self.exclude]
        for name in all_names:
            mock = MagicMock()
            patcher = patch.object(
                db_module,
                name,
                mock,
                create=name in self.OAUTH_EXTERNAL_ACCOUNT_PATCHES,
            )
            patcher.start()
            self._patches.append(patcher)
            self.patches[name] = mock
        return self.patches

    def __exit__(self, *args):
        for p in self._patches:
            p.stop()


@pytest.fixture
def db_patcher():
    return DBPatcher


# ─── Google OAuth RED Harness Helpers ────────────────────────────────────────

_DEFAULT_PROVIDER_INIT_TOKEN = "fake-provider-init-token-not-real"
_DEFAULT_PROJECT_HASH = "test-project-hash-server-side-only"
_DEFAULT_USER_GROUP_HASH = "test-user-group-hash-server-side-only"

_OAUTH_REDACTED_KEYS = {
    "access_token",
    "authorization_code",
    "code",
    "code_verifier",
    "google_email",
    "google_hd",
    "google_sub",
    "id_token",
    "nonce",
    "oauth_link_token",
    "project_hash",
    "provider_init_token",
    "provider_sub",
    "refresh_token",
    "state",
    "user_group_hash",
}

_DEFAULT_FORBIDDEN_OAUTH_SENTINELS = {
    "provider_init_token": _DEFAULT_PROVIDER_INIT_TOKEN,
    "project_hash": _DEFAULT_PROJECT_HASH,
    "user_group_hash": _DEFAULT_USER_GROUP_HASH,
    "authorization_code": "fake-google-auth-code-not-real",
    "google_access_token": "fake-google-access-token-not-real",
    "google_refresh_token": "fake-google-refresh-token-not-real",
}


class RedactedOAuthMapping(dict):
    """Dict payload whose repr does not leak strict hashes or OAuth tokens."""

    def __repr__(self):
        return repr(_redact_oauth_value(dict(self)))

    __str__ = __repr__


class FakeProviderInitRedeemError(RuntimeError):
    pass


def _oauth_test_fingerprint(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]


def _redact_oauth_value(value: Any) -> Any:
    if hasattr(value, "url") and hasattr(value, "method") and hasattr(value, "scope"):
        # Starlette/FastAPI Request is Mapping-like and exposes ``scope``,
        # including raw callback query strings.  Captures are asserting what the
        # app records, not the inbound Google URL, so keep only safe metadata.
        return {
            "method": getattr(value, "method", None),
            "path": getattr(getattr(value, "url", None), "path", None),
        }
    if isinstance(value, Mapping):
        return {
            key: "<redacted>" if str(key).lower() in _OAUTH_REDACTED_KEYS else _redact_oauth_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_redact_oauth_value(item) for item in value]
    return value


def make_fake_provider_init_payload(
    *,
    provider: str = "google",
    purpose: str = "login",
    project_hash: str = _DEFAULT_PROJECT_HASH,
    user_group_hash: Optional[str] = _DEFAULT_USER_GROUP_HASH,
    return_origin: str = "http://localhost:3000",
    expires_in: int = 600,
) -> RedactedOAuthMapping:
    payload = RedactedOAuthMapping({
        "provider": provider,
        "purpose": purpose,
        "project_hash": project_hash,
        "return_origin": return_origin,
        "issuer": "magic-worlds-api",
        "audience": "api.auth",
        "expires_in": expires_in,
        "scope_fingerprint": "test-scope-fingerprint",
        "provider_init_fingerprint": "test-provider-init-fingerprint",
    })
    if user_group_hash is not None:
        payload["user_group_hash"] = user_group_hash
    return payload


class FakeProviderInitRedeemer:
    """Server-side provider-init redemption fake; call records are redacted."""

    def __init__(self, default_payload: Optional[Mapping[str, Any]] = None):
        self.default_payload = RedactedOAuthMapping(default_payload or make_fake_provider_init_payload())
        self.tokens = {_DEFAULT_PROVIDER_INIT_TOKEN: self.default_payload}
        self.failures = {}
        self.redeemed = set()
        self.calls = []

    def add_token(self, token: str, payload: Optional[Mapping[str, Any]] = None):
        self.tokens[token] = RedactedOAuthMapping(payload or self.default_payload)
        return token

    def reject_token(self, token: str, reason: str = "invalid_provider_init"):
        self.failures[token] = reason
        return token

    async def redeem_provider_init_token(self, provider_init_token: str, **kwargs):
        self.calls.append({
            "token_fingerprint": _oauth_test_fingerprint(provider_init_token),
            "kwargs": _redact_oauth_value(kwargs),
        })
        if provider_init_token in self.failures:
            raise FakeProviderInitRedeemError(self.failures[provider_init_token])
        if provider_init_token in self.redeemed:
            raise FakeProviderInitRedeemError("provider_init_replay")
        payload = self.tokens.get(provider_init_token)
        if payload is None:
            raise FakeProviderInitRedeemError("provider_init_not_found")
        self.redeemed.add(provider_init_token)
        return copy.deepcopy(payload)

    async def __call__(self, provider_init_token: str, **kwargs):
        return await self.redeem_provider_init_token(provider_init_token, **kwargs)


class FakeGoogleTokenExchange:
    """Authlib/Google token-exchange fake with no network calls."""

    def __init__(self, token_response: Optional[Mapping[str, Any]] = None):
        self.token_response = RedactedOAuthMapping(token_response or {})
        self.calls = []

    async def authorize_access_token(self, *args, **kwargs):
        self.calls.append({"method": "authorize_access_token", "args_count": len(args), "kwargs": _redact_oauth_value(kwargs)})
        return copy.deepcopy(self.token_response)

    async def exchange_authorization_code(self, *args, **kwargs):
        self.calls.append({"method": "exchange_authorization_code", "args_count": len(args), "kwargs": _redact_oauth_value(kwargs)})
        return copy.deepcopy(self.token_response)


class FakeGoogleIDTokenVerifier:
    """Verifier fake that returns sanitized claims and records only fingerprints."""

    def __init__(self, claims: Optional[Mapping[str, Any]] = None):
        self.claims = RedactedOAuthMapping(claims or {})
        self.calls = []

    def verify(self, id_token: str, **kwargs):
        self.calls.append({
            "id_token_fingerprint": _oauth_test_fingerprint(id_token),
            "kwargs": _redact_oauth_value(kwargs),
        })
        return copy.deepcopy(self.claims)

    async def verify_async(self, id_token: str, **kwargs):
        return self.verify(id_token, **kwargs)

    def __call__(self, id_token: str, **kwargs):
        return self.verify(id_token, **kwargs)


class OAuthCapture:
    """Audit/activity capture sink with redacted repr and leak assertions."""

    def __init__(self, name: str):
        self.name = name
        self.records = []

    def capture(self, *args, **kwargs):
        self.records.append({"args": _redact_oauth_value(args), "kwargs": _redact_oauth_value(kwargs)})
        return None

    async def capture_async(self, *args, **kwargs):
        return self.capture(*args, **kwargs)

    def assert_no_leaks(self, forbidden_values: Optional[Mapping[str, Any]] = None):
        assert_no_oauth_sensitive_leaks(self.records, forbidden_values=forbidden_values, context=self.name)

    def __len__(self):
        return len(self.records)

    def __iter__(self):
        return iter(self.records)

    def __repr__(self):
        return f"OAuthCapture(name={self.name!r}, records={len(self.records)})"


def _iter_text_surfaces(value: Any, path: str = "$"):
    if hasattr(value, "headers") and hasattr(value, "text"):
        yield from _iter_text_surfaces(oauth_response_surface(value), path)
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from _iter_text_surfaces(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple, set)):
        for index, item in enumerate(value):
            yield from _iter_text_surfaces(item, f"{path}[{index}]")
    elif isinstance(value, bytes):
        yield path, value.decode("utf-8", errors="replace")
    elif value is not None:
        yield path, str(value)


def oauth_response_surface(response) -> dict:
    # ``httpx.Response.url`` is the inbound request URL, not an api.auth
    # browser-visible response surface.  OAuth callbacks legitimately arrive
    # with ``code``/``state`` query parameters from Google, so leak assertions
    # must inspect only the response path plus outbound headers/body/cookies.
    parsed_url = urlsplit(str(getattr(response, "url", "")))
    safe_response_url = urlunsplit((parsed_url.scheme, parsed_url.netloc, parsed_url.path, "", parsed_url.fragment))
    return {
        "url": safe_response_url,
        "headers": dict(getattr(response, "headers", {})),
        "cookies": dict(getattr(response, "cookies", {})),
        "body": getattr(response, "text", ""),
    }


def assert_no_oauth_sensitive_leaks(
    surface: Any,
    *,
    forbidden_values: Optional[Mapping[str, Any]] = None,
    context: str = "oauth surface",
):
    sentinels = dict(_DEFAULT_FORBIDDEN_OAUTH_SENTINELS)
    if forbidden_values:
        sentinels.update(forbidden_values)

    leaks = []
    for path, text in _iter_text_surfaces(surface):
        for label, raw_value in sentinels.items():
            if raw_value and str(raw_value) in text:
                leaks.append((label, path))

    if leaks:
        safe_locations = ", ".join(f"{label}@{path}" for label, path in leaks[:10])
        pytest.fail(f"OAuth sensitive leak detected in {context}: {safe_locations}")


@pytest.fixture
def fake_provider_init_redeemer():
    return FakeProviderInitRedeemer()


@pytest.fixture
def fake_google_token_exchange(fake_google_token_response):
    return FakeGoogleTokenExchange(fake_google_token_response)


@pytest.fixture
def fake_google_verifier(fake_google_claims):
    sanitized_claims = {
        "provider": "google",
        "sub": fake_google_claims["sub"],
        "email": fake_google_claims["email"],
        "email_verified": fake_google_claims["email_verified"],
        "iss": fake_google_claims["iss"],
        "aud": fake_google_claims["aud"],
        "nonce": fake_google_claims["nonce"],
    }
    return FakeGoogleIDTokenVerifier(sanitized_claims)


@pytest.fixture
def oauth_audit_capture():
    return OAuthCapture("audit")


@pytest.fixture
def oauth_activity_capture():
    return OAuthCapture("activity")


@pytest.fixture
def oauth_assert_no_leaks():
    return assert_no_oauth_sensitive_leaks
"""
Real-DB conftest — registers real_db marker and provides fixtures.

This file is loaded alongside the main integration conftest.py.
It provides fixtures for tests that require a real MySQL 8.0 instance.
"""

import os
import secrets
import uuid
from typing import Optional

import pymysql
import pytest
import redis

# ─── Register the real_db marker ─────────────────────────────────────────────

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_db: marks tests that require a real MySQL 8.0 instance "
        "(deselect with '-m \"not real_db\"')"
    )


# ─── Real MySQL Connection ───────────────────────────────────────────────────

_REAL_DB_CONFIG = {
    "host": os.environ.get("REAL_DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("REAL_DB_PORT", "3307")),
    "user": os.environ.get("REAL_DB_USER", "test_user"),
    "password": os.environ.get("REAL_DB_PASSWORD", "test_mysql_password"),
    "database": os.environ.get("REAL_DB_NAME", "magic_auth"),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}


def _get_real_connection():
    """Get a real MySQL connection for tests."""
    return pymysql.connect(**_REAL_DB_CONFIG)


def _check_mysql_available():
    """Check if real MySQL is available."""
    try:
        conn = _get_real_connection()
        conn.close()
        return True
    except Exception:
        return False


# ─── Skip hook for real_db tests when MySQL is not available ─────────────────

@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    """Skip real_db tests if MySQL is not available."""
    if item.get_closest_marker("real_db"):
        if not _check_mysql_available():
            pytest.skip("Real MySQL not available (docker compose -f docker-compose.test.yml up -d)")


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def real_db_available():
    """Session-scoped check for MySQL availability."""
    return _check_mysql_available()


@pytest.fixture
def real_db_conn():
    """Provide a real MySQL connection that auto-closes after each test."""
    conn = _get_real_connection()
    try:
        yield conn
    finally:
        conn.close()


# ─── Live Redis Connection ──────────────────────────────────────────────────

_REAL_REDIS_CONFIG = {
    "host": os.environ.get("REAL_REDIS_HOST", "127.0.0.1"),
    "port": int(os.environ.get("REAL_REDIS_PORT", "6380")),
    "db": 0,
    "decode_responses": True,
}


def _get_live_redis():
    """Get a live Redis client for tests."""
    return redis.StrictRedis(**_REAL_REDIS_CONFIG)


def _check_redis_available():
    """Check if live Redis is available."""
    try:
        r = _get_live_redis()
        r.ping()
        return True
    except Exception:
        return False


@pytest.fixture
def live_redis():
    """Provide a live Redis client that auto-flushes after each test."""
    r = _get_live_redis()
    r.flushdb()
    try:
        yield r
    finally:
        r.flushdb()


def _check_full_infra_available():
    """Check if both MySQL and Redis are available."""
    return _check_mysql_available() and _check_redis_available()


# ─── Entity Factories for Real-DB Tests ──────────────────────────────────────

def _gen_id(prefix: str) -> str:
    """Generate a UUID-based ID with prefix."""
    return f"{prefix}-{uuid.uuid4()}"


def _gen_hash(prefix: str) -> str:
    """Generate a hex hash."""
    return f"{prefix}-{secrets.token_hex(16).upper()}"


class RealDBFactory:
    """Factory for creating real entities in MySQL test database."""

    def __init__(self, conn: pymysql.Connection):
        self.conn = conn
        self._created_users = []
        self._created_user_groups = []
        self._created_projects = []
        self._created_project_groups = []
        self._created_memberships = []

    def create_user(self, username: str = None, email: str = None,
                    user_type: str = "consumer", password_hash: str = None) -> dict:
        """Create a user and return its data."""
        user_id = _gen_id("usr")
        user_hash = _gen_hash("uh")
        # Always append UUID suffix to avoid UNIQUE constraint conflicts on username
        # (soft-delete doesn't release the UNIQUE key)
        username = f"{username or 'testuser'}_{uuid.uuid4().hex[:8]}"
        email = email or f"{username}@test.com"
        password_hash = password_hash or f"$argon2id$fake_hash_{secrets.token_hex(8)}"

        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO users (id, user_hash, username, email, password_hash,
                   user_type, created_at, is_active)
                   VALUES (%s, %s, %s, %s, %s, %s, NOW(), 1)""",
                (user_id, user_hash, username, email, password_hash, user_type),
            )
        self.conn.commit()
        self._created_users.append(user_id)
        return {
            "id": user_id, "user_hash": user_hash, "username": username,
            "email": email, "user_type": user_type,
        }

    def create_user_group(self, group_name: str = None,
                          group_description: str = None) -> dict:
        """Create a user group and return its data."""
        group_id = _gen_id("ug")
        group_hash = _gen_hash("ugh")
        # Always append UUID suffix to avoid UNIQUE constraint conflicts
        group_name = f"{group_name or 'test_group'}_{uuid.uuid4().hex[:8]}"
        group_description = group_description or "Test user group"

        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO user_groups (id, group_hash, group_name, group_description,
                   created_at, is_active)
                   VALUES (%s, %s, %s, %s, NOW(), 1)""",
                (group_id, group_hash, group_name, group_description),
            )
        self.conn.commit()
        self._created_user_groups.append(group_id)
        return {
            "id": group_id, "group_hash": group_hash,
            "group_name": group_name, "group_description": group_description,
        }

    def create_project(self, project_name: str = None,
                       project_description: str = None) -> dict:
        """Create a project and return its data."""
        project_id = _gen_id("proj")
        project_hash = _gen_hash("ph")
        project_name = project_name or f"Test Project {uuid.uuid4().hex[:8]}"
        project_description = project_description or "Test project"

        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO projects (id, project_hash, project_name, project_description,
                   project_created, is_active)
                   VALUES (%s, %s, %s, %s, NOW(), 1)""",
                (project_id, project_hash, project_name, project_description),
            )
        self.conn.commit()
        self._created_projects.append(project_id)
        return {
            "id": project_id, "project_hash": project_hash,
            "project_name": project_name, "project_description": project_description,
        }

    def create_project_group(self, group_name: str = None,
                             group_description: str = None) -> dict:
        """Create a project group and return its data."""
        pg_id = _gen_id("pg")
        pg_hash = _gen_hash("pgh")
        # Always append UUID suffix to avoid UNIQUE constraint conflicts
        group_name = f"{group_name or 'test_pg'}_{uuid.uuid4().hex[:8]}"
        group_description = group_description or "Test project group"

        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO project_groups (id, group_hash, group_name, group_description,
                   created_at, is_active)
                   VALUES (%s, %s, %s, %s, NOW(), 1)""",
                (pg_id, pg_hash, group_name, group_description),
            )
        self.conn.commit()
        self._created_project_groups.append(pg_id)
        return {
            "id": pg_id, "group_hash": pg_hash,
            "group_name": group_name, "group_description": group_description,
        }

    def link_user_to_group(self, user_id: str, user_group_id: str) -> str:
        """Link a user to a user group."""
        member_id = _gen_id("ugm")
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO user_group_members (id, user_id, user_group_id,
                   assigned_at, is_active)
                   VALUES (%s, %s, %s, NOW(), 1)""",
                (member_id, user_id, user_group_id),
            )
        self.conn.commit()
        self._created_memberships.append(member_id)
        return member_id

    def link_project_to_group(self, project_id: str, project_group_id: str) -> str:
        """Link a project to a project group."""
        pgm_id = _gen_id("pgm")
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO project_group_members (id, project_id, project_group_id,
                   assigned_at, is_active)
                   VALUES (%s, %s, %s, NOW(), 1)""",
                (pgm_id, project_id, project_group_id),
            )
        self.conn.commit()
        self._created_memberships.append(pgm_id)
        return pgm_id

    def link_user_group_to_project_group(self, user_group_id: str,
                                          project_group_id: str) -> str:
        """Link a user group to a project group (the bridge)."""
        ugpg_id = _gen_id("ugpg")
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO user_group_project_groups (id, user_group_id, project_group_id,
                   granted_at, is_active)
                   VALUES (%s, %s, %s, NOW(), 1)""",
                (ugpg_id, user_group_id, project_group_id),
            )
        self.conn.commit()
        self._created_memberships.append(ugpg_id)
        return ugpg_id

    def create_full_chain(self, username: str = None, group_name: str = None,
                          pg_name: str = None, project_name: str = None) -> dict:
        """Create the full USER → USER_GROUP → PROJECT_GROUP → PROJECT chain."""
        user = self.create_user(username=username)
        ug = self.create_user_group(group_name=group_name)
        pg = self.create_project_group(group_name=pg_name)
        proj = self.create_project(project_name=project_name)

        self.link_user_to_group(user["id"], ug["id"])
        self.link_project_to_group(proj["id"], pg["id"])
        self.link_user_group_to_project_group(ug["id"], pg["id"])

        return {"user": user, "user_group": ug, "project_group": pg, "project": proj}

    def cleanup(self):
        """Soft-delete all created entities to clean up."""
        with self.conn.cursor() as cur:
            # Soft-delete memberships first
            for mid in self._created_memberships:
                cur.execute("UPDATE user_group_members SET is_active = 0 WHERE id = %s", (mid,))
                cur.execute("UPDATE project_group_members SET is_active = 0 WHERE id = %s", (mid,))
                cur.execute("UPDATE user_group_project_groups SET is_active = 0 WHERE id = %s", (mid,))
            # Soft-delete entities
            for uid in self._created_users:
                cur.execute("UPDATE users SET is_active = 0 WHERE id = %s", (uid,))
            for gid in self._created_user_groups:
                cur.execute("UPDATE user_groups SET is_active = 0 WHERE id = %s", (gid,))
            for pid in self._created_projects:
                cur.execute("UPDATE projects SET is_active = 0 WHERE id = %s", (pid,))
            for pgid in self._created_project_groups:
                cur.execute("UPDATE project_groups SET is_active = 0 WHERE id = %s", (pgid,))
        self.conn.commit()


@pytest.fixture
def real_factory(real_db_conn):
    """Provide a RealDBFactory that auto-cleans up after each test."""
    factory = RealDBFactory(real_db_conn)
    try:
        yield factory
    finally:
        factory.cleanup()
