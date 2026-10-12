"""Unit tests for src/Util/security.py — Slice 9.

Tests extract_jwt_token_from_request and returnJson_* helpers.
The module imports db_config at module level, but the functions tested here
don't use the Redis client.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.responses import JSONResponse

from src.Util.security import (
    extract_jwt_token_from_request,
    extract_refresh_token_from_request,
    HTTPBearerOrCookie,
    ACCESS_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
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
        request.cookies = {ACCESS_COOKIE_NAME: "cookie-token-456"}

        result = extract_jwt_token_from_request(request)
        assert result == "cookie-token-456"

    def test_bearer_takes_precedence_over_cookie(self):
        request = MagicMock()
        request.headers = {"Authorization": "Bearer header-token"}
        request.cookies = {ACCESS_COOKIE_NAME: "cookie-token"}

        result = extract_jwt_token_from_request(request)
        assert result == "header-token"

    def test_returns_none_without_token(self):
        request = MagicMock()
        request.headers = {}
        request.cookies = {}

        result = extract_jwt_token_from_request(request)
        assert result is None


class TestExtractRefreshTokenFromRequest:
    def test_extracts_refresh_token_from_cookie(self):
        request = MagicMock()
        request.headers = {"Authorization": "Bearer access-token-ignored"}
        request.cookies = {REFRESH_COOKIE_NAME: "refresh-cookie-token"}

        assert extract_refresh_token_from_request(request) == "refresh-cookie-token"

    def test_extracts_refresh_token_from_explicit_body_value(self):
        request = MagicMock()
        request.headers = {}
        request.cookies = {}

        assert extract_refresh_token_from_request(request, "refresh-body-token") == "refresh-body-token"

    def test_matching_cookie_and_body_is_allowed(self):
        request = MagicMock()
        request.headers = {}
        request.cookies = {REFRESH_COOKIE_NAME: "same-refresh-token"}

        assert extract_refresh_token_from_request(request, "same-refresh-token") == "same-refresh-token"

    def test_mismatched_cookie_and_body_raises(self):
        request = MagicMock()
        request.headers = {}
        request.cookies = {REFRESH_COOKIE_NAME: "cookie-token"}

        with pytest.raises(HTTPException) as exc_info:
            extract_refresh_token_from_request(request, "body-token")

        assert exc_info.value.status_code == 401
        assert "mismatch" in exc_info.value.detail.lower() or "match" in exc_info.value.detail.lower()

    def test_authorization_header_is_not_refresh_transport(self):
        request = MagicMock()
        request.headers = {"Authorization": "Bearer access-token"}
        request.cookies = {}

        with pytest.raises(HTTPException) as exc_info:
            extract_refresh_token_from_request(request)

        assert exc_info.value.status_code == 401
        assert "refresh token" in exc_info.value.detail.lower()

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
        request.cookies = {ACCESS_COOKIE_NAME: "cookie-token"}

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


# ─── returnJson_* helpers ───────────────────────────────────────────────────
