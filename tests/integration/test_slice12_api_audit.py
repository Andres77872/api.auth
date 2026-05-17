"""
Slice 12 — Middleware: API Audit

Tests: Verify audit logging at TWO levels:
1. Unit-level: APIAuditLogger utility logic (path filtering, sensitive data filtering, etc.)
2. Request-level: APIAuditMiddleware calls log_request during real HTTP requests through
   the full middleware stack.

The request-level tests verify that the middleware actually invokes the audit logger
with correct parameters during real ASGI request processing. Response logging runs
in background tasks and is not awaited in tests (to avoid hangs), but the synchronous
request logging path is fully proven.

Note: Excluded-path filtering (e.g., /ping, /docs not logged) is proven at the unit
level via test_should_log_request_excludes_health_paths. The request-level proof focuses
on verifying log_request IS called for non-excluded paths.
"""

import pytest
from unittest.mock import patch, MagicMock, call

from src.Util.api_audit_logger import APIAuditLogger


# ─── Unit-Level: APIAuditLogger Utility Tests ────────────────────────────────

def test_should_log_request_excludes_health_paths():
    """APIAuditLogger.should_log_request excludes /ping, /health, /docs."""
    assert APIAuditLogger.should_log_request("/ping", "GET") is False
    # Note: /system/health is NOT in excluded paths, only /health is
    assert APIAuditLogger.should_log_request("/docs", "GET") is False
    assert APIAuditLogger.should_log_request("/docs/openapi.json", "GET") is False
    assert APIAuditLogger.should_log_request("/redoc", "GET") is False


def test_should_log_request_excludes_options():
    """APIAuditLogger.should_log_request excludes OPTIONS (CORS preflight)."""
    assert APIAuditLogger.should_log_request("/auth/login", "OPTIONS") is False


def test_should_log_request_includes_protected_endpoints():
    """APIAuditLogger.should_log_request includes protected endpoints."""
    assert APIAuditLogger.should_log_request("/auth/login", "POST") is True
    assert APIAuditLogger.should_log_request("/users/profile", "GET") is True
    assert APIAuditLogger.should_log_request("/projects", "GET") is True
    assert APIAuditLogger.should_log_request("/users/list", "GET") is True


def test_filter_sensitive_data_removes_passwords():
    """APIAuditLogger.filter_sensitive_data masks password fields."""
    data = {
        "username": "testuser",
        "password": "secret123",
        "password_hash": "$argon2id$fake",
        "email": "test@example.com",
    }
    filtered = APIAuditLogger.filter_sensitive_data(data)
    # Sensitive fields are masked, not removed
    assert filtered["password"] == "***FILTERED***"
    assert filtered["password_hash"] == "***FILTERED***"
    assert filtered["username"] == "testuser"
    assert filtered["email"] == "test@example.com"


def test_filter_sensitive_data_removes_tokens():
    """APIAuditLogger.filter_sensitive_data masks token fields."""
    data = {
        "session_token": "abc123",
        "access_token": "jwt.here",
        "refresh_token": "refresh.here",
        "authorization": "Bearer token",
        "user_id": "1",
    }
    filtered = APIAuditLogger.filter_sensitive_data(data)
    # Token fields are masked, not removed
    assert filtered["session_token"] == "***FILTERED***"
    assert filtered["access_token"] == "***FILTERED***"
    assert filtered["refresh_token"] == "***FILTERED***"
    assert filtered["authorization"] == "***FILTERED***"
    assert filtered["user_id"] == "1"


def test_filter_sensitive_data_handles_none():
    """APIAuditLogger.filter_sensitive_data handles None input."""
    assert APIAuditLogger.filter_sensitive_data(None) is None


def test_filter_sensitive_data_nested():
    """APIAuditLogger.filter_sensitive_data handles nested dicts."""
    data = {
        "user": {"username": "test", "password": "secret"},
        "token": "abc",
    }
    filtered = APIAuditLogger.filter_sensitive_data(data)
    # Sensitive fields are masked
    assert filtered["user"]["password"] == "***FILTERED***"
    assert filtered["token"] == "***FILTERED***"
    assert filtered["user"]["username"] == "test"


def test_generate_tags_for_auth_endpoint():
    """APIAuditLogger.generate_tags returns appropriate tags for auth endpoints."""
    tags = APIAuditLogger.generate_tags("/auth/login", "POST", 200, None)
    assert isinstance(tags, list)
    assert len(tags) > 0


def test_is_security_event_for_auth_failures():
    """APIAuditLogger.is_security_event flags auth failures."""
    assert APIAuditLogger.is_security_event("/auth/login", "POST", 401, None) is True
    assert APIAuditLogger.is_security_event("/auth/login", "POST", 200, None) is False


def test_extract_resource_info_for_user_endpoints():
    """APIAuditLogger.extract_resource_info extracts resource type and ID."""
    resource_type, resource_id = APIAuditLogger.extract_resource_info("/users/usr-123", "GET")
    assert resource_type == "user"
    assert resource_id == "usr-123"


def test_extract_resource_info_for_project_endpoints():
    """APIAuditLogger.extract_resource_info extracts project resource."""
    resource_type, resource_id = APIAuditLogger.extract_resource_info("/projects/prj-456", "GET")
    assert resource_type == "project"
    assert resource_id == "prj-456"


def test_excluded_paths_constant():
    """Verify excluded paths list contains expected entries."""
    assert "/ping" in APIAuditLogger.EXCLUDED_PATHS
    assert "/docs" in APIAuditLogger.EXCLUDED_PATHS
    assert "/redoc" in APIAuditLogger.EXCLUDED_PATHS
    assert "/openapi.json" in APIAuditLogger.EXCLUDED_PATHS
    assert "/auth/validate" in APIAuditLogger.EXCLUDED_PATHS  # Phase 1.3: high-frequency validation


# ─── Request-Level: APIAuditMiddleware Runtime Proof ─────────────────────────

@pytest.mark.asyncio
async def test_audit_middleware_logs_login_request(
    client, fake_redis, patched_db_connection, patched_db_error_logger,
    patched_cache_manager, patched_activity_logger, patched_audit_ids,
):
    """APIAuditMiddleware calls log_request for /auth/login with correct parameters during real HTTP request."""
    mock_logger = MagicMock()
    mock_logger.should_log_request.return_value = True  # Force logging for this test
    mock_logger.log_request = MagicMock()
    mock_logger.log_response = MagicMock()
    mock_logger.extract_resource_info.return_value = (None, None)
    mock_logger.is_security_event.return_value = False
    mock_logger.generate_tags.return_value = []
    mock_logger.filter_sensitive_data = lambda d: d

    with patch("src.routes.auth.get_user_by_credentials", return_value=None), \
         patch("src.Util.api_audit_logger.APIAuditLogger", mock_logger), \
         patch("src.middleware.api_audit.APIAuditLogger", mock_logger):
        await client.post(
            "/auth/login",
            data={"username": "test", "password": "wrong"},
            headers={"User-Agent": "audit-test"},
        )

    # log_request MUST be called during the real HTTP request
    assert mock_logger.log_request.call_count == 1
    call_kwargs = mock_logger.log_request.call_args.kwargs
    assert call_kwargs["http_method"] == "POST"
    assert call_kwargs["endpoint_path"] == "/auth/login"
    # Request body for form-data is stored as {"_note": "Non-JSON body"}
    # since the middleware reads raw bytes before FastAPI parses form data
    body = call_kwargs["request_body"]
    assert body is not None


@pytest.mark.asyncio
async def test_audit_middleware_logs_protected_get_request(
    client, fake_redis, patched_db_connection, patched_db_error_logger,
    patched_cache_manager, patched_activity_logger, patched_audit_ids,
):
    """APIAuditMiddleware calls log_request for protected GET endpoints during real HTTP request."""
    mock_logger = MagicMock()
    mock_logger.should_log_request.return_value = True
    mock_logger.log_request = MagicMock()
    mock_logger.log_response = MagicMock()
    mock_logger.extract_resource_info.return_value = (None, None)
    mock_logger.is_security_event.return_value = False
    mock_logger.generate_tags.return_value = []
    mock_logger.filter_sensitive_data = lambda d: d

    with patch("src.Util.api_audit_logger.APIAuditLogger", mock_logger), \
         patch("src.middleware.api_audit.APIAuditLogger", mock_logger):
        # Unauthenticated request to protected endpoint → 401, but still logged
        await client.get(
            "/users/profile",
            headers={"User-Agent": "audit-test"},
        )

    # log_request MUST be called during the real HTTP request
    assert mock_logger.log_request.call_count == 1
    call_kwargs = mock_logger.log_request.call_args.kwargs
    assert call_kwargs["http_method"] == "GET"
    assert call_kwargs["endpoint_path"] == "/users/profile"


@pytest.mark.asyncio
async def test_audit_middleware_extracts_user_context(
    client, fake_redis, patched_db_connection, patched_db_error_logger,
    patched_cache_manager, patched_activity_logger, patched_audit_ids,
):
    """APIAuditMiddleware extracts user context from request.state during real request."""
    mock_logger = MagicMock()
    mock_logger.should_log_request.return_value = True
    mock_logger.log_request = MagicMock()
    mock_logger.log_response = MagicMock()
    mock_logger.extract_resource_info.return_value = (None, None)
    mock_logger.is_security_event.return_value = False
    mock_logger.generate_tags.return_value = []
    mock_logger.filter_sensitive_data = lambda d: d

    # Store a valid session so AuthContextMiddleware populates request.state.user
    import json
    session_token = "audit-session-token"
    session_payload = {
        "session_id": 99999,
        "user_id": "1",
        "user_hash": "usr-audit-001",
        "user_type": "consumer",
        "project_id": "1",
        "project_hash": "prj-audit-001",
        "project_name": "Audit Test Project",
        "permissions": [],
        "groups": [],
    }
    fake_redis.set(f"session:{session_token}", json.dumps(session_payload), ex=259200)

    with patch("src.Util.api_audit_logger.APIAuditLogger", mock_logger), \
         patch("src.middleware.api_audit.APIAuditLogger", mock_logger):
        await client.get(
            "/users/profile",
            headers={
                "Authorization": f"Bearer {session_token}",
                "User-Agent": "audit-test",
            },
        )

    # log_request MUST be called
    assert mock_logger.log_request.call_count == 1
    call_kwargs = mock_logger.log_request.call_args.kwargs
    # User context should be extracted from request.state (set by AuthContextMiddleware)
    assert call_kwargs["user_id"] == "1"
    assert call_kwargs["session_id"] is not None
    assert call_kwargs["client_ip"] is not None
