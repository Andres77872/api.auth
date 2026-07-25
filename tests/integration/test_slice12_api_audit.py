"""
Slice 12 — Middleware: API Audit

Proves APIAuditMiddleware invokes the audit logger with the right parameters during
real ASGI request processing, through the full middleware stack.  Response logging
runs in a background task and is not awaited here; the synchronous request-logging
path is what these assert.

The pure-logic surface of APIAuditLogger — should_log_request path/method filtering,
filter_sensitive_data masking, generate_tags — is covered (more thoroughly) by
tests/unit/test_api_audit_logger.py and is deliberately not re-tested here.
"""

import pytest
from unittest.mock import patch, MagicMock, call

from src.Util.api_audit_logger import APIAuditLogger


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

    session_token = "header.payload.signature"
    session_data = MagicMock()
    session_data.user_id = "1"
    session_data.user_hash = "usr-audit-001"
    session_data.user_type = "consumer"
    session_data.username = "audit-user"
    session_data.project_id = "1"
    session_data.project_hash = "prj-audit-001"
    session_data.permissions = []
    session_data.groups = []

    with patch("src.Util.api_audit_logger.APIAuditLogger", mock_logger), \
         patch("src.middleware.api_audit.APIAuditLogger", mock_logger), \
         patch("src.Util.db.db_enhanced.validate_session", return_value=session_data):
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
