"""
High-Fidelity ASGI Integration Test Infrastructure

These tests run against the REAL FastAPI app with ALL middleware active.
They are labeled "e2e" for historical reasons but are more accurately described as
**high-fidelity ASGI integration tests** — they exercise the full application stack
(HTTP layer, middleware, routing, dependency injection, exception handlers, JWT/session
logic) while isolating infrastructure boundaries:

- DB: patched at module boundary (MySQL stored procedures not available in test env)
- Redis: fakeredis (API-compatible in-memory replacement, not a mock)
- Audit logger: mocked (writes to DB in production)

What is truly integration-tested:
- Full middleware stack (CORS, RequestValidation, APIAudit, AuthContext)
- Real FastAPI routing and dependency injection
- Real JWT/session logic and cookie handling
- Real exception handlers producing standardized error responses
- Real response serialization through Pydantic models

What uses test doubles (infrastructure boundaries only):
- DB calls patched at src.Util.db boundary (stored procedures require MySQL 8.0)
- Redis replaced with fakeredis (full API-compatible in-memory implementation)
- Audit logger methods mocked (writes to api_audit_log table in production)

Full MySQL+Redis end-to-end tests would require docker-compose with MySQL 8.0
and all stored procedures deployed. This is a future phase investment.
"""

import json
import os
import uuid
from typing import Any, Dict, Optional
from unittest.mock import patch, MagicMock

import fakeredis
import httpx
import pymysql
import pytest
import redis

from src.main import app as fastapi_app


# ─── Register real_db marker ─────────────────────────────────────────────────

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_db: marks tests that require a real MySQL 8.0 instance "
        "(deselect with '-m \"not real_db\"')"
    )


# ─── App Fixture (REAL app with all middleware) ──────────────────────────────

@pytest.fixture
def app():
    """Return the REAL FastAPI app with ALL middleware active."""
    return fastapi_app


@pytest.fixture
async def client(app):
    """Async httpx test client against the REAL app."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# ─── Real-DB Fixtures (for tests that need real MySQL) ───────────────────────

_REAL_DB_CONFIG = {
    "host": os.environ.get("REAL_DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("REAL_DB_PORT", "3307")),
    "user": os.environ.get("REAL_DB_USER", "test_user"),
    "password": os.environ.get("REAL_DB_PASSWORD", "test_mysql_password"),
    "database": os.environ.get("REAL_DB_NAME", "magic_auth"),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}


def _check_mysql_available():
    """Check if real MySQL is available."""
    try:
        conn = pymysql.connect(**_REAL_DB_CONFIG)
        conn.close()
        return True
    except Exception:
        return False


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    """Skip real_db tests if MySQL is not available."""
    if item.get_closest_marker("real_db"):
        if not _check_mysql_available():
            pytest.skip("Real MySQL not available (docker compose -f docker-compose.test.yml up -d)")


@pytest.fixture
def real_db_conn():
    """Provide a real MySQL connection that auto-closes after each test."""
    conn = pymysql.connect(**_REAL_DB_CONFIG)
    try:
        yield conn
    finally:
        conn.close()


# ─── Live Redis Fixtures ────────────────────────────────────────────────────

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


# ─── Fakeredis ───────────────────────────────────────────────────────────────

@pytest.fixture
def fake_redis():
    """fakeredis patched at ALL Redis usage locations."""
    fake = fakeredis.FakeStrictRedis()

    session_mock = MagicMock()
    session_mock.user_id = "1"
    session_mock.user_hash = "usr-e2e-001"
    session_mock.user_type = "consumer"
    session_mock.project_hash = "prj-e2e-001"
    session_mock.project_name = "E2E Test Project"
    session_mock.project_id = "1"
    session_mock.permissions = []
    session_mock.groups = []
    session_mock.session_token = "e2e-token"
    session_mock.session_length = 259200
    session_mock.username = "e2euser"

    user_mock = MagicMock()
    user_mock.id = "1"
    user_mock.user_hash = "usr-e2e-001"
    user_mock.username = "e2euser"
    user_mock.email = "e2e@test.com"
    user_mock.user_type = "consumer"

    with patch("src.Util.db_config.redis_client", fake), \
         patch("src.Util.cache_manager.redis_client", fake), \
         patch("src.Util.auth_lifecycle.redis_client", fake), \
         patch("src.Util.db.db_enhanced.client", fake), \
         patch("src.Util.db.db_users.client", fake), \
         patch("src.Util.db.db_session_analytics.redis_client", fake), \
         patch("src.Util.system_metrics.redis_client", fake), \
         patch("src.routes.auth.redis_client", fake), \
         patch("src.Util.decorators.validate_session", return_value=session_mock), \
         patch("src.Util.decorators.get_user_by_hash", return_value=user_mock), \
         patch("src.Util.db.validate_session", return_value=session_mock):
        yield fake
    fake.flushall()


# ─── DB Connection Patching ──────────────────────────────────────────────────

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
    "src.Util.system_metrics.get_connection",
    "src.Util.bulk_operations.get_connection",
]


def _mock_db_connection():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    return mock_conn


@pytest.fixture
def patched_db_connection():
    """Patch all DB connections."""
    mock_conn = _mock_db_connection()
    patches = [patch("src.Util.db_config.get_connection", return_value=mock_conn)]
    for loc in _DB_CONN_PATCH_LOCATIONS:
        patches.append(patch(loc, return_value=mock_conn))
    for p in patches:
        p.start()
    try:
        yield mock_conn
    finally:
        for p in patches:
            p.stop()


# ─── Audit Logger ────────────────────────────────────────────────────────────

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
    with patch("src.middleware.api_audit.generate_audit_id", return_value="audit-e2e-id"), \
         patch("src.middleware.api_audit.generate_request_id", return_value="req-e2e-id"):
        yield


# ─── Other Infrastructure ────────────────────────────────────────────────────

async def _noop_access_logger(*args, **kwargs):
    return None


@pytest.fixture(autouse=True)
def patched_request_access_logger():
    with patch("src.middleware.request_validation.logger", _noop_access_logger):
        yield


@pytest.fixture
def patched_cache_manager():
    mock = MagicMock()
    mock.get_cache_stats.return_value = {"hit_rate": 0.0, "miss_rate": 0.0, "total_keys": 0, "memory_used": "0 KB"}
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


@pytest.fixture
def patched_activity_logger():
    with patch("src.Util.activity_logger.ActivityLogger") as mock:
        yield mock


@pytest.fixture
def patched_db_error_logger():
    with patch("src.middleware.error_handler.log_app_exception_to_db", MagicMock()), \
         patch("src.middleware.error_handler.log_generic_exception_to_db", MagicMock()), \
         patch("src.middleware.error_handler.log_http_exception_to_db", MagicMock()), \
         patch("src.middleware.error_handler.log_validation_exception_to_db", MagicMock()):
        yield


# ─── Combined E2E Environment ────────────────────────────────────────────────

@pytest.fixture
def e2e_env(fake_redis, patched_cache_manager, patched_activity_logger,
            patched_audit_logger, patched_audit_ids, patched_db_connection,
            patched_db_error_logger):
    """Complete E2E environment with all patches applied."""
    yield {
        "redis": fake_redis,
        "cache": patched_cache_manager,
        "activity": patched_activity_logger,
        "audit": patched_audit_logger,
        "db_conn": patched_db_connection,
    }


# ─── Factories ───────────────────────────────────────────────────────────────

def make_e2e_session(user_type="consumer", user_id="1", user_hash="usr-e2e-001",
                     project_hash="prj-e2e-001", project_id="1", permissions=None,
                     session_token=None):
    if session_token is None:
        session_token = f"e2e-token-{uuid.uuid4().hex[:16]}"
    s = MagicMock()
    s.user_id = user_id
    s.user_hash = user_hash
    s.user_type = user_type
    s.project_hash = project_hash
    s.project_name = "E2E Test Project"
    s.project_id = project_id
    s.permissions = permissions or []
    s.groups = []
    s.session_token = session_token
    s.session_length = 259200
    s.username = "e2euser"
    return s


def make_e2e_user(user_type="consumer", user_id="1", user_hash="usr-e2e-001",
                  username="e2euser", email="e2e@test.com"):
    u = MagicMock()
    u.id = user_id
    u.user_hash = user_hash
    u.username = username
    u.email = email
    u.user_type = user_type
    u.is_active = True
    u.assigned_project_id = None
    return u


def create_e2e_session(fake_redis, token: str, user_type="consumer",
                       permissions=None, project_hash="prj-e2e-001",
                       user_id="1", user_hash=None, family_id=None):
    """Create a session in fakeredis for E2E tests."""
    user_hash = user_hash or f"usr-e2e-{user_type}"
    family_id = family_id or f"family-{token}"
    payload = {
        "session_id": 99999,
        "access_jti": token,
        "jti": token,
        "family_id": family_id,
        "user_hash": user_hash,
        "user_id": user_id,
        "user_type": user_type,
        "scope": "project",
        "collection": project_hash,
        "project_hash": project_hash,
        "project_name": "E2E Test Project",
        "project_id": "1",
        "permissions": permissions or [],
        "groups": [],
        "session_token": token,
        "session_length": 259200,
    }
    fake_redis.set(f"session:{token}", json.dumps(payload), ex=259200)
    fake_redis.sadd(f"user_sessions:{user_id}", token)
    fake_redis.expire(f"user_sessions:{user_id}", 259200)
    fake_redis.sadd(f"user_refresh_families:{user_id}", family_id)
    fake_redis.expire(f"user_refresh_families:{user_id}", 259200)
    fake_redis.set(
        f"refresh_family:{family_id}",
        json.dumps({
            "family_id": family_id,
            "user_id": user_id,
            "user_hash": user_hash,
            "status": "active",
            "current_access_jti": token,
            "refresh_ttl_seconds": 259200,
        }),
        ex=259200,
    )
    return token
