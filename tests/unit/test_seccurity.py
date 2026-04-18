"""Unit tests for src/Util/Seccurity.py — Slice 9.

Tests extract_jwt_token_from_request and returnJson_* helpers.
The module imports db_config at module level, but the functions tested here
don't use the Redis client.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.responses import JSONResponse

from src.Util.Seccurity import (
    extract_jwt_token_from_request,
    returnJson_401,
    returnJson_403,
    returnJson_404,
    returnJson_413,
    returnJson_422,
    returnJson_500,
    returnJson_200,
    HTTPBearerOrCookie,
    JWT_COOKIE_NAME,
    middleware_user_token_validation,
    PLATFORM_COLLECTION_SENTINEL,
)


# ─── extract_jwt_token_from_request ─────────────────────────────────────────

class TestExtractJwtTokenFromRequest:
    def test_extracts_from_bearer_header(self):
        request = MagicMock()
        request.headers = {"Authorization": "Bearer my-token-123"}
        request.cookies = {}

        result = extract_jwt_token_from_request(request)
        assert result == "my-token-123"

    def test_extracts_from_cookie(self):
        request = MagicMock()
        request.headers = {}
        request.cookies = {JWT_COOKIE_NAME: "cookie-token-456"}

        result = extract_jwt_token_from_request(request)
        assert result == "cookie-token-456"

    def test_bearer_takes_precedence_over_cookie(self):
        request = MagicMock()
        request.headers = {"Authorization": "Bearer header-token"}
        request.cookies = {JWT_COOKIE_NAME: "cookie-token"}

        result = extract_jwt_token_from_request(request)
        assert result == "header-token"

    def test_returns_none_without_token(self):
        request = MagicMock()
        request.headers = {}
        request.cookies = {}

        result = extract_jwt_token_from_request(request)
        assert result is None

    def test_returns_none_with_non_bearer_auth(self):
        request = MagicMock()
        request.headers = {"Authorization": "Basic some-creds"}
        request.cookies = {}

        result = extract_jwt_token_from_request(request)
        assert result is None

    def test_returns_none_with_empty_bearer(self):
        """Empty Bearer token (e.g., 'Bearer ') should return None, not empty string."""
        request = MagicMock()
        request.headers = {"Authorization": "Bearer "}
        request.cookies = {}

        result = extract_jwt_token_from_request(request)
        assert result is None


# ─── HTTPBearerOrCookie ─────────────────────────────────────────────────────

class TestHTTPBearerOrCookie:
    @pytest.mark.anyio
    async def test_accepts_bearer_header(self):
        security = HTTPBearerOrCookie()
        request = MagicMock()
        request.headers = {"Authorization": "Bearer test-token"}
        request.cookies = {}

        result = await security(request)
        assert result.scheme == "Bearer"
        assert result.credentials == "test-token"

    @pytest.mark.anyio
    async def test_accepts_cookie(self):
        security = HTTPBearerOrCookie()
        request = MagicMock()
        request.headers = {}
        request.cookies = {JWT_COOKIE_NAME: "cookie-token"}

        result = await security(request)
        assert result.credentials == "cookie-token"

    @pytest.mark.anyio
    async def test_raises_when_no_token_auto_error_true(self):
        security = HTTPBearerOrCookie(auto_error=True)
        request = MagicMock()
        request.headers = {}
        request.cookies = {}

        with pytest.raises(HTTPException) as exc_info:
            await security(request)
        assert exc_info.value.status_code == 401

    @pytest.mark.anyio
    async def test_returns_none_when_no_token_auto_error_false(self):
        security = HTTPBearerOrCookie(auto_error=False)
        request = MagicMock()
        request.headers = {}
        request.cookies = {}

        result = await security(request)
        assert result is None


class TestMiddlewareUserTokenValidation:
    def test_accepts_platform_session_from_jwt(self):
        request = MagicMock()
        request.headers = {"Authorization": "Bearer test-token"}
        request.cookies = {}

        session = MagicMock()
        session.scope = "platform"
        session.project_hash = None
        session.session_token = "test-token"
        session.session_length = 259200
        session.user_hash = "usr-admin-001"
        session.user_id = "2"
        session.project_id = None
        session.user_project_id = None
        session.groups = ["platform_admins"]
        session.user_type = "admin"
        session.assigned_project_id = None

        with patch("src.Util.Seccurity.validate_session", return_value=session):
            result = middleware_user_token_validation(request)

        assert result.user_collection == PLATFORM_COLLECTION_SENTINEL
        assert result.user_type == "admin"

    def test_accepts_platform_session_from_legacy_headers(self):
        request = MagicMock()
        request.headers = {
            "X-token-user": "test-token",
            "X-token-collection": PLATFORM_COLLECTION_SENTINEL,
        }
        request.cookies = {}

        session = MagicMock()
        session.scope = "platform"
        session.project_hash = None
        session.session_token = "test-token"
        session.session_length = 259200
        session.user_hash = "usr-root-001"
        session.user_id = "0"
        session.project_id = None
        session.user_project_id = None
        session.groups = ["platform_root_users"]
        session.user_type = "root"
        session.assigned_project_id = None

        with patch("src.Util.Seccurity.validate_session", return_value=session):
            result = middleware_user_token_validation(request)

        assert result.user_collection == PLATFORM_COLLECTION_SENTINEL
        assert result.user_type == "root"


# ─── returnJson_* helpers ───────────────────────────────────────────────────

class TestReturnJsonHelpers:
    def _assert_json_response(self, response, expected_status, expected_status_key, expected_action):
        assert isinstance(response, JSONResponse)
        assert response.status_code == expected_status
        body = response.body.decode()
        import json
        data = json.loads(body)
        assert data["status"] == expected_status_key
        assert data["action"] == expected_action

    def test_returnJson_401(self):
        resp = returnJson_401()
        self._assert_json_response(resp, 401, "Error", "Access forbidden, access token required or token invalid")

    def test_returnJson_403(self):
        resp = returnJson_403()
        self._assert_json_response(resp, 403, "Error", "Access forbidden, insufficient permissions")

    def test_returnJson_404(self):
        resp = returnJson_404()
        self._assert_json_response(resp, 404, "Error", "Resource not found")

    def test_returnJson_413(self):
        resp = returnJson_413()
        self._assert_json_response(resp, 413, "Error", "Payload too large (max 8 MiB)")

    def test_returnJson_422(self):
        resp = returnJson_422()
        self._assert_json_response(resp, 422, "Error", "User-Agent header not found")

    def test_returnJson_500(self):
        resp = returnJson_500()
        self._assert_json_response(resp, 500, "Error", "Internal server error")

    def test_returnJson_200(self):
        resp = returnJson_200()
        self._assert_json_response(resp, 200, "OK", "Action successful")

    def test_returnJson_401_with_custom_data(self):
        resp = returnJson_401(data={"custom": "data"})
        import json
        body = json.loads(resp.body.decode())
        assert body == {"custom": "data"}

    def test_returnJson_500_with_custom_data(self):
        resp = returnJson_500(data={"error": "custom"})
        import json
        body = json.loads(resp.body.decode())
        assert body == {"error": "custom"}
