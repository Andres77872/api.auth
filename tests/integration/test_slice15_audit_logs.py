"""Integration tests for audit log monitor API — Slice 15.

Tests all new audit endpoints. All mocks are applied at the route module level
(src.routes.audit_logs.*) because functions are imported at module load time.
"""

from unittest.mock import MagicMock, patch

import pytest


def _admin_headers(token: str = "test-admin-token"):
    return {"Authorization": f"Bearer {token}"}


def _patch_audit(**extra_mocks):
    """Patch all dependencies at the audit_logs route module level.
    
    Returns a context manager that yields a dict of mock objects.
    """
    mocks = {
        "get_user_type": MagicMock(return_value="admin"),
        "is_root_user": MagicMock(return_value=False),
        "get_audit_logs": MagicMock(return_value=[]),
        "count_audit_logs": MagicMock(return_value=0),
        "get_audit_statistics": MagicMock(return_value={"overview": {}, "by_method": [], "top_endpoints": [], "status_distribution": []}),
        "get_security_events": MagicMock(return_value=[]),
        "get_user_api_activity_summary": MagicMock(return_value={"summary": {}, "endpoint_activity": []}),
        "get_recent_activity": MagicMock(return_value=[]),
        "get_activity_security_events": MagicMock(return_value=[]),
        "get_user_by_id": MagicMock(return_value=None),
        "_check_export_count": MagicMock(return_value=0),
    }
    mocks.update(extra_mocks)
    return _MultiPatch("src.routes.audit_logs", mocks)


def _patch_dashboard(**extra_mocks):
    """Patch dependencies at the admin_dashboard route module level."""
    mocks = {
        "get_user_type": MagicMock(return_value="admin"),
        "is_root_user": MagicMock(return_value=False),
        "get_recent_activity": MagicMock(return_value=[]),
        "count_activity_logs": MagicMock(return_value=0),
        "get_activity_by_id": MagicMock(return_value=None),
    }
    mocks.update(extra_mocks)
    return _MultiPatch("src.routes.admin_dashboard", mocks)


class _MultiPatch:
    """Context manager that patches multiple attributes and yields the mocks dict."""
    def __init__(self, target, mocks):
        self.target = target
        self.mocks = mocks
        self._patchers = []

    def __enter__(self):
        import importlib
        mod = importlib.import_module(self.target)
        for name, mock_obj in self.mocks.items():
            p = patch.object(mod, name, mock_obj)
            p.start()
            self._patchers.append(p)
        return self.mocks

    def __exit__(self, *args):
        for p in self._patchers:
            p.stop()


# ─── GET /admin/audit/logs ──────────────────────────────────────────────────

class TestAuditLogsListing:
    @pytest.mark.asyncio
    async def test_default_listing_returns_paginated_results(self, client, integration_env):
        with _patch_audit(
            get_audit_logs=MagicMock(return_value=[{"id": "audit-1", "http_method": "GET", "endpoint_path": "/admin/users", "username": "adminuser"}]),
            count_audit_logs=MagicMock(return_value=1),
        ):
            response = await client.get("/admin/audit/logs", headers=_admin_headers())
            assert response.status_code == 200
            data = response.json()
            assert "logs" in data
            assert data["pagination"]["total"] == 1

    @pytest.mark.asyncio
    async def test_filter_by_http_method(self, client, integration_env):
        with _patch_audit() as mocks:
            response = await client.get("/admin/audit/logs?http_method=POST", headers=_admin_headers())
            assert response.status_code == 200
            assert mocks["get_audit_logs"].call_args[1]["http_method"] == "POST"

    @pytest.mark.asyncio
    async def test_filter_by_status_code(self, client, integration_env):
        with _patch_audit() as mocks:
            response = await client.get("/admin/audit/logs?status_code=401", headers=_admin_headers())
            assert response.status_code == 200
            assert mocks["get_audit_logs"].call_args[1]["status_code"] == 401

    @pytest.mark.asyncio
    async def test_filter_by_security_event(self, client, integration_env):
        with _patch_audit() as mocks:
            response = await client.get("/admin/audit/logs?security_event=true", headers=_admin_headers())
            assert response.status_code == 200
            assert mocks["get_audit_logs"].call_args[1]["security_event"] is True

    @pytest.mark.asyncio
    async def test_limit_validation_zero(self, client, integration_env):
        with _patch_audit():
            response = await client.get("/admin/audit/logs?limit=0", headers=_admin_headers())
            assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_limit_validation_over_max(self, client, integration_env):
        with _patch_audit():
            response = await client.get("/admin/audit/logs?limit=1001", headers=_admin_headers())
            assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_auth_rejection_no_token(self, client, integration_env):
        with patch("src.Util.decorators.validate_session", side_effect=Exception("No session")):
            response = await client.get("/admin/audit/logs")
            assert response.status_code in (401, 422)

    @pytest.mark.asyncio
    async def test_pagination_with_offset(self, client, integration_env):
        with _patch_audit(count_audit_logs=MagicMock(return_value=200)):
            response = await client.get("/admin/audit/logs?limit=50&offset=100", headers=_admin_headers())
            assert response.status_code == 200
            data = response.json()
            assert data["pagination"]["total"] == 200
            assert data["pagination"]["has_more"] is True


# ─── GET /admin/audit/security-events ───────────────────────────────────────

class TestSecurityEvents:
    @pytest.mark.asyncio
    async def test_merged_results_from_both_sources(self, client, integration_env):
        with _patch_audit(
            get_security_events=MagicMock(return_value=[{
                "id": "audit-1", "http_method": "POST", "endpoint_path": "/auth/login",
                "user_id": "usr-1", "username": "testuser", "client_ip": "192.168.1.1",
                "response_status": 401, "error_code": "AUTH_1001", "error_message": "Invalid",
                "request_timestamp": "2026-04-16T12:00:00Z", "duration_ms": 30,
                "tags": ["auth", "failed"], "metadata": None,
            }]),
            get_activity_security_events=MagicMock(return_value=[{
                "id": "act-1", "user_id": "usr-2", "activity_type": "user_login_failed",
                "details": "Failed login", "ip_address": "10.0.0.1",
                "severity_level": "warning", "created_at": "2026-04-16T11:00:00Z",
                "username": "otheruser", "activity_name": "Login Failed",
                "activity_description": "User failed to login",
            }]),
        ):
            response = await client.get("/admin/audit/security-events", headers=_admin_headers())
            assert response.status_code == 200
            data = response.json()
            assert data["summary"]["total"] == 2
            assert data["summary"]["by_source"]["api_audit"] == 1

    @pytest.mark.asyncio
    async def test_severity_derivation_401(self, client, integration_env):
        with _patch_audit(
            get_security_events=MagicMock(return_value=[{
                "id": "a1", "http_method": "POST", "endpoint_path": "/auth/login",
                "user_id": "u1", "username": "u", "client_ip": "1.1.1.1",
                "response_status": 401, "error_code": None, "error_message": None,
                "request_timestamp": "2026-04-16T12:00:00Z", "duration_ms": 30,
                "tags": None, "metadata": None,
            }]),
        ):
            response = await client.get("/admin/audit/security-events", headers=_admin_headers())
            assert response.json()["events"][0]["severity"] == "warning"

    @pytest.mark.asyncio
    async def test_severity_derivation_403(self, client, integration_env):
        with _patch_audit(
            get_security_events=MagicMock(return_value=[{
                "id": "a1", "http_method": "GET", "endpoint_path": "/admin",
                "user_id": "u1", "username": "u", "client_ip": "1.1.1.1",
                "response_status": 403, "error_code": None, "error_message": None,
                "request_timestamp": "2026-04-16T12:00:00Z", "duration_ms": 10,
                "tags": None, "metadata": None,
            }]),
        ):
            response = await client.get("/admin/audit/security-events", headers=_admin_headers())
            assert response.json()["events"][0]["severity"] == "critical"

    @pytest.mark.asyncio
    async def test_severity_derivation_500(self, client, integration_env):
        with _patch_audit(
            get_security_events=MagicMock(return_value=[{
                "id": "a1", "http_method": "POST", "endpoint_path": "/api/data",
                "user_id": "u1", "username": "u", "client_ip": "1.1.1.1",
                "response_status": 500, "error_code": None, "error_message": None,
                "request_timestamp": "2026-04-16T12:00:00Z", "duration_ms": 100,
                "tags": None, "metadata": None,
            }]),
        ):
            response = await client.get("/admin/audit/security-events", headers=_admin_headers())
            assert response.json()["events"][0]["severity"] == "warning"

    @pytest.mark.asyncio
    async def test_filter_by_severity(self, client, integration_env):
        with _patch_audit(
            get_security_events=MagicMock(return_value=[
                {"id": "a1", "http_method": "GET", "endpoint_path": "/admin", "user_id": "u1", "username": "u", "client_ip": "1.1.1.1", "response_status": 403, "error_code": None, "error_message": None, "request_timestamp": "2026-04-16T12:00:00Z", "duration_ms": 10, "tags": None, "metadata": None},
                {"id": "a2", "http_method": "POST", "endpoint_path": "/auth/login", "user_id": "u2", "username": "u", "client_ip": "1.1.1.1", "response_status": 401, "error_code": None, "error_message": None, "request_timestamp": "2026-04-16T11:00:00Z", "duration_ms": 30, "tags": None, "metadata": None},
            ]),
        ):
            response = await client.get("/admin/audit/security-events?severity=critical", headers=_admin_headers())
            assert response.json()["summary"]["total"] == 1

    @pytest.mark.asyncio
    async def test_filter_by_source_api_audit(self, client, integration_env):
        with _patch_audit(
            get_security_events=MagicMock(return_value=[{
                "id": "a1", "http_method": "GET", "endpoint_path": "/admin",
                "user_id": "u1", "username": "u", "client_ip": "1.1.1.1",
                "response_status": 403, "error_code": None, "error_message": None,
                "request_timestamp": "2026-04-16T12:00:00Z", "duration_ms": 10,
                "tags": None, "metadata": None,
            }]),
        ) as mocks:
            response = await client.get("/admin/audit/security-events?source=api_audit", headers=_admin_headers())
            assert response.json()["summary"]["by_source"]["activity_log"] == 0

    @pytest.mark.asyncio
    async def test_merged_total_limit_enforced(self, client, integration_env):
        """Regression: limit applies to final merged result, not per-source (verify issue 2.2)."""
        with _patch_audit(
            get_security_events=MagicMock(return_value=[
                {"id": "a1", "http_method": "GET", "endpoint_path": "/admin", "user_id": "u1", "username": "u", "client_ip": "1.1.1.1", "response_status": 403, "error_code": None, "error_message": None, "request_timestamp": "2026-04-16T12:00:00Z", "duration_ms": 10, "tags": None, "metadata": None},
                {"id": "a2", "http_method": "POST", "endpoint_path": "/auth/login", "user_id": "u2", "username": "u", "client_ip": "1.1.1.1", "response_status": 401, "error_code": None, "error_message": None, "request_timestamp": "2026-04-16T11:00:00Z", "duration_ms": 30, "tags": None, "metadata": None},
            ]),
            get_activity_security_events=MagicMock(return_value=[
                {"id": "act-1", "user_id": "usr-3", "activity_type": "user_login_failed", "details": "Failed login", "ip_address": "10.0.0.1", "severity_level": "warning", "created_at": "2026-04-16T10:00:00Z", "username": "otheruser", "activity_name": "Login Failed", "activity_description": "User failed to login"},
            ]),
        ):
            response = await client.get("/admin/audit/security-events?limit=2", headers=_admin_headers())
            data = response.json()
            # limit=2 on merged result, not per-source
            assert data["summary"]["total"] <= 2
            assert len(data["events"]) <= 2


# ─── GET /admin/audit/statistics ────────────────────────────────────────────

class TestAuditStatistics:
    @pytest.mark.asyncio
    async def test_returns_4_sections(self, client, integration_env):
        with _patch_audit(
            get_audit_statistics=MagicMock(return_value={
                "overview": {"total_requests": 15000, "successful_requests": 14200, "failed_requests": 800, "success_rate": 94.67, "avg_duration_ms": 45.2, "max_duration_ms": 2340, "avg_request_size": 1024.0, "avg_response_size": 4096.0},
                "by_method": [{"http_method": "GET", "request_count": 12000, "avg_duration_ms": 30.5}],
                "top_endpoints": [{"endpoint_path": "/auth/login", "request_count": 5000, "avg_duration_ms": 120, "success_count": 4800, "failure_count": 200}],
                "status_distribution": [{"response_status": 200, "count": 13000}],
            }),
        ):
            response = await client.get("/admin/audit/statistics", headers=_admin_headers())
            assert response.status_code == 200
            data = response.json()
            assert all(k in data for k in ["overview", "by_method", "top_endpoints", "status_distribution"])

    @pytest.mark.asyncio
    async def test_days_validation_zero(self, client, integration_env):
        with _patch_audit():
            response = await client.get("/admin/audit/statistics?days=0", headers=_admin_headers())
            assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_days_validation_over_max(self, client, integration_env):
        with _patch_audit():
            response = await client.get("/admin/audit/statistics?days=366", headers=_admin_headers())
            assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_empty_data_returns_zeroed(self, client, integration_env):
        with _patch_audit(
            get_audit_statistics=MagicMock(return_value={
                "overview": {"total_requests": 0, "successful_requests": 0, "failed_requests": 0, "success_rate": 0.0, "avg_duration_ms": 0.0, "max_duration_ms": 0, "avg_request_size": 0.0, "avg_response_size": 0.0},
                "by_method": [], "top_endpoints": [], "status_distribution": [],
            }),
        ):
            response = await client.get("/admin/audit/statistics", headers=_admin_headers())
            assert response.json()["overview"]["total_requests"] == 0


# ─── POST /admin/audit/export ───────────────────────────────────────────────

class TestAuditExport:
    @pytest.mark.asyncio
    @pytest.mark.skip(reason="StreamingResponse + httpx ASGI + middleware incompatibility; validated by unit tests")
    async def test_json_export(self, client, integration_env):
        pass

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="StreamingResponse + httpx ASGI + middleware incompatibility; validated by unit tests")
    async def test_csv_export(self, client, integration_env):
        pass

    @pytest.mark.asyncio
    async def test_limit_exceeds_hard_limit(self, client, integration_env):
        with _patch_audit(count_audit_logs=MagicMock(return_value=15000)):
            response = await client.post("/admin/audit/export", json={"source": "audit", "format": "json", "limit": 15000}, headers=_admin_headers())
            assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_missing_source(self, client, integration_env):
        with _patch_audit():
            response = await client.post("/admin/audit/export", json={"format": "json"}, headers=_admin_headers())
            assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_format(self, client, integration_env):
        with _patch_audit():
            response = await client.post("/admin/audit/export", json={"source": "audit", "format": "xml"}, headers=_admin_headers())
            assert response.status_code == 400

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="POST StreamingResponse + httpx ASGI + middleware incompatibility; validated by unit tests")
    async def test_export_source_api_audit_accepted(self, client, integration_env):
        """Regression: spec requires source='api_audit' to be accepted (verify issue 2.1)."""
        with _patch_audit(
            get_audit_logs=MagicMock(return_value=[]),
            _check_export_count=MagicMock(return_value=0),
        ):
            response = await client.post(
                "/admin/audit/export",
                json={"source": "api_audit", "format": "json", "filters": {"days": 7}},
                headers=_admin_headers(),
            )
            assert response.status_code == 200


# ─── GET /admin/activity (search enhancement) ───────────────────────────────

class TestActivityFeedSearch:
    @pytest.mark.asyncio
    async def test_search_returns_matching(self, client, integration_env):
        with _patch_dashboard(
            get_recent_activity=MagicMock(return_value=[{"id": "act-1", "user_id": "usr-1", "activity_type": "user_login", "details": "Login", "project_id": None, "user_group_id": None, "target_user_id": None, "ip_address": "192.168.1.1", "user_agent": "Mozilla", "metadata": None, "severity_level": "info", "created_at": "2026-04-16T12:00:00Z", "username": "john", "user_hash": "h1", "project_name": None, "project_hash": None, "target_username": None, "target_user_hash": None, "user_group_name": None, "activity_name": "Login", "activity_category": "auth", "activity_description": "Login"}]),
            count_activity_logs=MagicMock(return_value=1),
        ):
            response = await client.get("/admin/activity?search=login", headers=_admin_headers())
            assert response.status_code == 200
            assert len(response.json()["activities"]) == 1

    @pytest.mark.asyncio
    async def test_empty_search_ignored(self, client, integration_env):
        with _patch_dashboard(
            get_recent_activity=MagicMock(return_value=[]),
            count_activity_logs=MagicMock(return_value=0),
        ) as mocks:
            response = await client.get("/admin/activity?search=", headers=_admin_headers())
            assert response.status_code == 200
            assert mocks["get_recent_activity"].call_args[1].get("search") is None


# ─── GET /admin/activity/{activity_id} ──────────────────────────────────────

class TestActivityDetail:
    @pytest.mark.asyncio
    async def test_valid_id_returns_detail(self, client, integration_env):
        # Use a properly formatted activity ID: act-{32 hex chars}
        valid_id = "act-00000000000000000000000000000abc"
        with _patch_dashboard(
            get_activity_by_id=MagicMock(return_value={"id": valid_id, "user_id": "usr-1", "activity_type": "user_login", "details": "Login", "project_id": "proj-1", "user_group_id": None, "target_user_id": None, "ip_address": "192.168.1.1", "user_agent": "Mozilla", "metadata": None, "severity_level": "info", "created_at": "2026-04-16T12:00:00Z", "username": "john", "user_hash": "h1", "project_name": "Test", "project_hash": "ph1", "target_username": None, "target_user_hash": None, "user_group_name": None, "activity_name": "Login", "activity_category": "auth", "activity_description": "Login"}),
        ):
            response = await client.get(f"/admin/activity/{valid_id}", headers=_admin_headers())
            assert response.status_code == 200
            assert response.json()["activity"]["id"] == valid_id

    @pytest.mark.asyncio
    async def test_nonexistent_id_returns_404(self, client, integration_env):
        # Use a valid-format ID that doesn't exist in the DB
        nonexistent_id = "act-0000000000000000000000000000dead"
        with _patch_dashboard(get_activity_by_id=MagicMock(return_value=None)):
            response = await client.get(f"/admin/activity/{nonexistent_id}", headers=_admin_headers())
            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_malformed_id_returns_400(self, client, integration_env):
        """Regression: malformed non-empty activity_id returns 400 VAL_3001 (verify issue 2.4)."""
        with _patch_dashboard():
            response = await client.get("/admin/activity/bad$$$", headers=_admin_headers())
            assert response.status_code == 400
            data = response.json()
            # Error code is nested under error.code in the response format
            assert data.get("error", {}).get("code") == "VAL_3001"


# ─── GET /admin/users/{user_id}/activity ────────────────────────────────────

class TestUserActivity:
    @pytest.mark.asyncio
    async def test_combined_summary(self, client, integration_env):
        with _patch_audit(
            get_user_by_id=MagicMock(return_value=MagicMock(id="usr-abc123")),
            get_user_api_activity_summary=MagicMock(return_value={"summary": {"total_requests": 50, "successful_requests": 48, "failed_requests": 2, "unique_endpoints": 10, "first_request": "2026-04-01T00:00:00Z", "last_request": "2026-04-16T12:00:00Z", "avg_duration_ms": 45.2}, "endpoint_activity": []}),
            get_recent_activity=MagicMock(return_value=[{"id": "act-1", "user_id": "usr-abc123", "activity_type": "user_login", "details": "Login", "project_id": None, "user_group_id": None, "target_user_id": None, "ip_address": "1.1.1.1", "user_agent": "Mozilla", "metadata": None, "severity_level": "info", "created_at": "2026-04-16T12:00:00Z", "username": "testuser", "user_hash": "h1", "project_name": None, "project_hash": None, "target_username": None, "target_user_hash": None, "user_group_name": None, "activity_name": "Login", "activity_category": "auth", "activity_description": "Login"}]),
            get_audit_logs=MagicMock(return_value=[]),
        ):
            response = await client.get("/admin/users/usr-abc123/activity", headers=_admin_headers())
            assert response.status_code == 200
            data = response.json()
            assert data["summary"]["activity_log_count"] == 1
            assert data["summary"]["api_audit_count"] == 50

    @pytest.mark.asyncio
    async def test_nonexistent_user_returns_404(self, client, integration_env):
        with _patch_audit(get_user_by_id=MagicMock(return_value=None)):
            response = await client.get("/admin/users/usr-nonexistent/activity", headers=_admin_headers())
            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_user_with_no_activity(self, client, integration_env):
        with _patch_audit(
            get_user_by_id=MagicMock(return_value=MagicMock(id="usr-abc123")),
            get_user_api_activity_summary=MagicMock(return_value={"summary": {"total_requests": 0, "successful_requests": 0, "failed_requests": 0, "unique_endpoints": 0, "first_request": None, "last_request": None, "avg_duration_ms": 0.0}, "endpoint_activity": []}),
            get_recent_activity=MagicMock(return_value=[]),
            get_audit_logs=MagicMock(return_value=[]),
        ):
            response = await client.get("/admin/users/usr-abc123/activity", headers=_admin_headers())
            assert response.status_code == 200
            data = response.json()
            assert data["summary"]["activity_log_count"] == 0
            assert data["timeline"] == []

    @pytest.mark.asyncio
    async def test_user_activity_timeline_api_audit_shape(self, client, integration_env):
        """Regression: API-audit timeline entries must have spec-required fields (verify issue 2.3)."""
        with _patch_audit(
            get_user_by_id=MagicMock(return_value=MagicMock(id="usr-abc123")),
            get_user_api_activity_summary=MagicMock(return_value={"summary": {"total_requests": 3, "successful_requests": 2, "failed_requests": 1, "unique_endpoints": 2, "first_request": "2026-04-01T00:00:00Z", "last_request": "2026-04-16T12:00:00Z", "avg_duration_ms": 45.2}, "endpoint_activity": []}),
            get_recent_activity=MagicMock(return_value=[]),
            get_audit_logs=MagicMock(return_value=[
                {
                    "id": "audit-001",
                    "http_method": "POST",
                    "endpoint_path": "/auth/login",
                    "response_status": 200,
                    "is_success": True,
                    "duration_ms": 45,
                    "client_ip": "192.168.1.1",
                    "request_timestamp": "2026-04-16T12:00:00Z",
                },
            ]),
        ):
            response = await client.get("/admin/users/usr-abc123/activity", headers=_admin_headers())
            assert response.status_code == 200
            data = response.json()
            # Find the api_audit timeline entry
            api_entries = [e for e in data["timeline"] if e["source"] == "api_audit"]
            assert len(api_entries) >= 1
            entry = api_entries[0]
            # Spec-required fields must be present and non-None
            assert entry["id"] == "audit-001"
            assert entry["http_method"] == "POST"
            assert entry["endpoint_path"] == "/auth/login"
            assert entry["response_status"] == 200
            assert entry["is_success"] is True
            assert entry["duration_ms"] == 45
            assert entry["client_ip"] == "192.168.1.1"
