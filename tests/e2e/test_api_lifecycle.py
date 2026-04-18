"""
High-Fidelity ASGI Integration Test Suite — Full API Lifecycle

These tests verify the complete request lifecycle through the real FastAPI app
with ALL middleware active. They cover the most critical user journeys.

NOTE: Despite the "e2e" directory name, these are **high-fidelity ASGI integration
tests**, not full infrastructure end-to-end. They exercise the full application
stack while using test doubles only at infrastructure boundaries (DB patched,
Redis = fakeredis, audit logger mocked).

What is truly integration-tested:
- Full middleware stack (CORS, RequestValidation, APIAudit, AuthContext)
- Real FastAPI routing and dependency injection
- Real JWT/session logic
- Real exception handlers
- Real response serialization

What uses test doubles (infrastructure boundaries):
- DB: patched at src.Util.db boundary (MySQL stored procedures not available)
- Redis: fakeredis (API-compatible in-memory)
- Audit logger: mocked (writes to DB)

Full MySQL+Redis E2E would require docker-compose with MySQL 8.0.
"""

import json
from unittest.mock import patch, MagicMock

import pytest

from tests.e2e.conftest import make_e2e_session, make_e2e_user, create_e2e_session


# ─── E2E 1: Health Check Pipeline ────────────────────────────────────────────

class TestHealthCheckPipeline:
    """E2E: Verify full middleware pipeline works for health endpoints."""

    @pytest.mark.asyncio
    async def test_ping_through_full_pipeline(self, client, e2e_env):
        """GET /ping flows through all middleware and returns 204."""
        response = await client.get(
            "/ping",
            headers={"User-Agent": "e2e-test-client"},
        )
        assert response.status_code == 204
        # Verify X-Process-Time from RequestValidationMiddleware
        process_time = response.headers.get("x-process-time")
        assert process_time is not None


# ─── E2E 2: Auth Flow Lifecycle ─────────────────────────────────────────────

class TestAuthFlowLifecycle:
    """E2E: Full auth flow — login → validate → logout."""

    @pytest.mark.asyncio
    async def test_login_returns_token_and_cookie(self, client, e2e_env):
        """POST /auth/login → 200 + session_token + cookie with security flags."""
        user = make_e2e_user()
        project = MagicMock()
        project.id = "1"
        project.project_hash = "prj-e2e-001"
        project.project_name = "E2E Project"
        project.project_description = "E2E project"
        group = MagicMock()
        group.id = "1"
        group.group_hash = "grp-e2e-001"
        group.group_name = "E2E Group"
        group.group_description = "E2E group"

        with patch("src.routes.auth.get_user_by_credentials", return_value=user), \
             patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
             patch("src.routes.auth.get_project_by_hash", return_value=project), \
             patch("src.routes.auth.get_user_groups_for_user", return_value=[group]):
            response = await client.post(
                "/auth/login",
                data={
                    "username": "e2euser",
                    "password": "e2epass",
                    "project_hash": "prj-e2e-001",
                },
                headers={"User-Agent": "e2e-test-client"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "session_token" in data
        assert data["user"]["username"] == "e2euser"

        # Verify cookie with security flags
        cookies = response.cookies
        assert "session_token" in cookies
        set_cookie = response.headers.get_list("set-cookie")[0].lower()
        assert "httponly" in set_cookie
        assert "secure" in set_cookie
        assert "samesite=strict" in set_cookie

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, client, e2e_env):
        """POST /auth/login with wrong password → 401."""
        with patch("src.routes.auth.get_user_by_credentials", return_value=None):
            response = await client.post(
                "/auth/login",
                data={"username": "e2euser", "password": "wrongpass"},
                headers={"User-Agent": "e2e-test-client"},
            )

        assert response.status_code == 401
        data = response.json()
        assert data["status"] == "error"


# ─── E2E 3: Permission Enforcement ──────────────────────────────────────────

class TestPermissionEnforcement:
    """E2E: Permission boundaries at the HTTP layer."""

    @pytest.mark.asyncio
    async def test_unauthenticated_access_denied(self, client, e2e_env):
        """No auth → 401 on protected endpoints."""
        response = await client.get(
            "/users/profile",
            headers={"User-Agent": "e2e-test-client"},
        )
        assert response.status_code == 401


# ─── E2E 4: Error Handling Contract ─────────────────────────────────────────

class TestErrorHandlingContract:
    """E2E: Error response shape consistency across all error types."""

    @pytest.mark.asyncio
    async def test_auth_error_shape(self, client, e2e_env):
        """Auth errors return standardized shape with authentication category."""
        response = await client.get(
            "/users/profile",
            headers={"User-Agent": "e2e-test-client"},
        )

        assert response.status_code == 401
        data = response.json()
        assert data["status"] == "error"
        assert data["error"]["category"] == "authentication"


# ─── E2E 5: Security ────────────────────────────────────────────────────────

class TestSecurity:
    """E2E: Security properties of the API."""

    @pytest.mark.asyncio
    async def test_cors_not_wildcard(self, client, e2e_env):
        """CORS should not use wildcard origin with credentials."""
        response = await client.get(
            "/ping",
            headers={"Origin": "http://localhost:3000", "User-Agent": "e2e-test-client"},
        )
        acao = response.headers.get("access-control-allow-origin")
        assert acao != "*"
        assert acao == "http://localhost:3000"

    @pytest.mark.asyncio
    async def test_cors_rejects_unknown_origin(self, client, e2e_env):
        """CORS should not reflect unknown origins."""
        response = await client.get(
            "/ping",
            headers={"Origin": "http://evil.com", "User-Agent": "e2e-test-client"},
        )
        acao = response.headers.get("access-control-allow-origin")
        assert acao is None or acao != "http://evil.com"

    @pytest.mark.asyncio
    async def test_empty_bearer_rejected(self, client, e2e_env):
        """Empty Bearer token → 401, not 500."""
        with patch("src.Util.Seccurity.validate_session", return_value=None):
            response = await client.get(
                "/auth/validate",
                headers={"Authorization": "Bearer ", "User-Agent": "e2e-test-client"},
            )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_no_password_leak_in_errors(self, client, e2e_env):
        """Error responses should not contain password fields."""
        with patch("src.routes.auth.get_user_by_credentials", return_value=None):
            response = await client.post(
                "/auth/login",
                data={"username": "test", "password": "secret123"},
                headers={"User-Agent": "e2e-test-client"},
            )

        assert response.status_code == 401
        body = response.text.lower()
        assert "secret123" not in body
