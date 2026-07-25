"""
Slice 1 — Health & Ping Endpoints

The ping endpoints are public. Detailed health and aggregate system information
require a valid session because they expose tenant and infrastructure state.

CRITICAL: system.py imports count_users etc. from src.Util.db at module load time.
We must patch at src.routes.system.count_users (usage location), not src.Util.db.count_users.
"""

import pytest
from unittest.mock import patch


AUTH_HEADERS = {
    "Authorization": "Bearer test-system-session",
    "User-Agent": "test",
}


@pytest.mark.asyncio
async def test_ping_returns_204(client):
    """GET /ping returns 204 No Content."""
    response = await client.get("/ping")
    assert response.status_code == 204
    assert response.content == b""


@pytest.mark.asyncio
async def test_system_ping_returns_200(client, fake_redis):
    """GET /system/ping returns 200 with success payload."""
    response = await client.get("/system/ping")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "message" in data
    assert "timestamp" in data


@pytest.mark.parametrize("path", ["/system/health", "/system/info"])
@pytest.mark.asyncio
async def test_system_details_require_a_session(client, path):
    """Detailed tenant and infrastructure state is not public."""
    response = await client.get(path, headers={"User-Agent": "test"})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_system_health_returns_200(client, fake_redis, patched_cache_manager, patched_activity_logger, patched_audit_logger, patched_audit_ids, patched_db_connection, patched_db_error_logger):
    """An authenticated GET /system/health returns component statuses."""
    # Patch at USAGE location in system.py (where names are bound at import time)
    with patch("src.routes.system.validate_session", return_value=object()), \
         patch("src.routes.system.count_users", return_value=42), \
         patch("src.routes.system.count_user_groups", return_value=5), \
         patch("src.routes.system.count_project_permission_groups", return_value=3):
        response = await client.get("/system/health", headers=AUTH_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["status"] in ("healthy", "degraded")
    assert "timestamp" in data
    assert "components" in data
    assert data["components"]["redis"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_system_info_returns_200(client, fake_redis, patched_cache_manager, patched_activity_logger, patched_audit_logger, patched_audit_ids, patched_db_connection, patched_db_error_logger):
    """An authenticated GET /system/info returns aggregate statistics."""
    with patch("src.routes.system.validate_session", return_value=object()), \
         patch("src.routes.system.count_users", return_value=100), \
         patch("src.routes.system.count_projects", return_value=25), \
         patch("src.routes.system.count_user_groups", return_value=10), \
         patch("src.routes.system.count_project_permission_groups", return_value=8):
        response = await client.get("/system/info", headers=AUTH_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["system"]["name"] == "Group-Based Multi-Project Authentication API"
    assert data["statistics"]["total_users"] == 100
    assert data["statistics"]["total_projects"] == 25


@pytest.mark.asyncio
async def test_health_degraded_when_db_fails(client, fake_redis, patched_cache_manager, patched_activity_logger, patched_audit_logger, patched_audit_ids, patched_db_connection, patched_db_error_logger):
    """Authenticated health reports degraded when the DB is unreachable."""
    with patch("src.routes.system.validate_session", return_value=object()), \
         patch("src.routes.system.count_users", return_value=None), \
         patch("src.routes.system.count_user_groups", return_value=5), \
         patch("src.routes.system.count_project_permission_groups", return_value=3):
        response = await client.get("/system/health", headers=AUTH_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["components"]["database"]["status"] == "unhealthy"


@pytest.mark.asyncio
async def test_health_degraded_when_email_delivery_enabled_but_worker_missing(client, fake_redis, patched_cache_manager, patched_activity_logger, patched_audit_logger, patched_audit_ids, patched_db_connection, patched_db_error_logger):
    """Enabled email delivery must not look operational without a worker heartbeat."""
    billing_disabled = {
        "status": "disabled",
        "readiness": {"disabled": True},
        "provider_stripe": {"status": "disabled"},
        "webhooks": {"status": "disabled"},
        "sync": {"status": "disabled"},
    }

    with patch("src.routes.system.validate_session", return_value=object()), \
         patch("src.routes.system.count_users", return_value=42), \
         patch("src.routes.system.count_user_groups", return_value=5), \
         patch("src.routes.system.count_project_permission_groups", return_value=3), \
         patch("src.routes.system.SystemMetrics.get_email_provider_health", return_value={"status": "ready", "ready": True, "delivery_enabled": True}), \
         patch("src.routes.system.SystemMetrics.get_email_outbox_metrics", return_value={"status": "healthy"}), \
         patch("src.routes.system.SystemMetrics.get_email_worker_metrics", return_value={"status": "unknown", "delivery_enabled": True, "heartbeat_count": 0}), \
         patch("src.routes.system.SystemMetrics.get_patreon_metrics", return_value={"status": "disabled"}), \
         patch("src.routes.system.SystemMetrics.get_billing_metrics", return_value=billing_disabled):
        response = await client.get("/system/health", headers=AUTH_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["components"]["email_worker"]["status"] == "unknown"
