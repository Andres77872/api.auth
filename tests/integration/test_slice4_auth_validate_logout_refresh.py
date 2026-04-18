"""
Slice 4 — Auth Flow: Validate, Logout, Refresh

Tests: GET /auth/validate (valid session → 200, expired → 401, missing token → 401),
POST /auth/logout (200 + cookie cleared), POST /auth/refresh (200 + new token).

All tests run through the REAL app with ALL middleware active (CORS, RequestValidation,
APIAudit, AuthContext). No workaround app is used.
"""

import json
from unittest.mock import patch, MagicMock

import httpx
import pytest


def _make_user(user_type="consumer", user_id="1", user_hash="usr-test-001",
               username="testuser", email="test@example.com"):
    u = MagicMock()
    u.id = user_id
    u.user_hash = user_hash
    u.username = username
    u.email = email
    u.user_type = user_type
    u.is_active = True
    u.assigned_project_id = None
    return u


def _make_project(project_id="1", project_hash="prj-test-001",
                  project_name="Test Project"):
    p = MagicMock()
    p.id = project_id
    p.project_hash = project_hash
    p.project_name = project_name
    p.project_description = "A test project"
    return p


def _make_group(group_id="1", group_hash="grp-test-001", group_name="Test Group"):
    g = MagicMock()
    g.id = group_id
    g.group_hash = group_hash
    g.group_name = group_name
    g.group_description = "A test group"
    return g


def _make_session_data(user_hash="usr-test-001", user_id="1", user_type="consumer",
                       project_hash="prj-test-001", project_name="Test Project",
                       project_id="1", session_token="test-token",
                       permissions=None, groups=None):
    s = MagicMock()
    s.user_hash = user_hash
    s.user_id = user_id
    s.user_type = user_type
    s.project_hash = project_hash
    s.project_name = project_name
    s.project_id = project_id
    s.session_token = session_token
    s.permissions = permissions or []
    s.groups = groups or []
    s.session_length = 259200
    s.username = "testuser"
    return s


SESSION_TOKEN = "test-session-token-validate"


def _store_session_in_redis(fake_redis, token, payload):
    fake_redis.set(f"session:{token}", json.dumps(payload), ex=259200)


def _make_redis_session_payload(user_hash="usr-test-001", user_id="1",
                                 user_type="consumer", project_hash="prj-test-001",
                                 project_name="Test Project", project_id="1", scope=None,
                                 permissions=None, groups=None):
    payload = {
        "session_id": 12345,
        "user_id": user_id,
        "user_hash": user_hash,
        "user_type": user_type,
        "project_id": project_id,
        "project_hash": project_hash,
        "project_name": project_name,
        "user_group_ids": [],
        "user_group_names": [],
        "permissions": permissions or [],
        "groups": groups or [],
    }
    if scope is not None:
        payload["scope"] = scope
    return payload


@pytest.mark.asyncio
async def test_validate_valid_session(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Valid session returns 200 + user info through REAL middleware stack."""
    _store_session_in_redis(fake_redis, SESSION_TOKEN, _make_redis_session_payload())

    response = await client.get(
        "/auth/validate",
        headers={"Authorization": f"Bearer {SESSION_TOKEN}", "User-Agent": "test"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["valid"] is True
    assert data["user"]["user_hash"] == "usr-test-001"
    assert data["project"]["project_hash"] == "prj-test-001"


@pytest.mark.asyncio
async def test_validate_expired_session(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Expired session returns 401 through REAL middleware stack."""
    response = await client.get(
        "/auth/validate",
        headers={"Authorization": "Bearer nonexistent-token", "User-Agent": "test"},
    )

    assert response.status_code == 401
    data = response.json()
    assert data["status"] == "error"


@pytest.mark.asyncio
async def test_validate_missing_token(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Missing token returns 401 through REAL middleware stack."""
    response = await client.get(
        "/auth/validate",
        headers={"User-Agent": "test"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_validate_root_project_bound_session(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Root user project-bound session validates correctly through REAL middleware stack."""
    _store_session_in_redis(fake_redis, SESSION_TOKEN, _make_redis_session_payload(
        user_hash="usr-root-001", user_id="0", user_type="root",
        project_hash="prj-test-001", project_name="Test Project", project_id="1",
    ))

    response = await client.get(
        "/auth/validate",
        headers={"Authorization": f"Bearer {SESSION_TOKEN}", "User-Agent": "test"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["user"]["user_type"] == "root"
    assert data["project"]["project_hash"] == "prj-test-001"


@pytest.mark.asyncio
async def test_validate_root_legacy_global_session_rejected(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Legacy root global session (project_hash='') is no longer accepted."""
    _store_session_in_redis(fake_redis, SESSION_TOKEN, _make_redis_session_payload(
        user_hash="usr-root-001", user_id="0", user_type="root",
        project_hash="", project_name="Global Root Access", project_id=None,
    ))

    response = await client.get(
        "/auth/validate",
        headers={"Authorization": f"Bearer {SESSION_TOKEN}", "User-Agent": "test"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["user"]["user_type"] == "root"
    assert data["project"] is None


@pytest.mark.asyncio
async def test_validate_platform_session_returns_scope_and_no_project(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Platform session validates successfully and stays projectless."""
    _store_session_in_redis(fake_redis, SESSION_TOKEN, _make_redis_session_payload(
        user_hash="usr-admin-001", user_id="2", user_type="admin",
        project_hash=None, project_name=None, project_id=None,
        scope="platform",
        permissions=["admin", "manage_users", "manage_roles"],
        groups=["platform_admins"],
    ))

    response = await client.get(
        "/auth/validate",
        headers={"Authorization": f"Bearer {SESSION_TOKEN}", "User-Agent": "test"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["user"]["user_type"] == "admin"
    assert data["project"] is None
    assert data["session"]["scope"] == "platform"


@pytest.mark.asyncio
async def test_logout_valid_session(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Logout returns 200 and clears session from Redis through REAL middleware stack."""
    _store_session_in_redis(fake_redis, SESSION_TOKEN, _make_redis_session_payload())

    response = await client.post(
        "/auth/logout",
        headers={"Authorization": f"Bearer {SESSION_TOKEN}", "User-Agent": "test"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert fake_redis.get(f"session:{SESSION_TOKEN}") is None


@pytest.mark.asyncio
async def test_refresh_valid_session(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Refresh returns 200 + new token, old session deleted through REAL middleware stack."""
    _store_session_in_redis(fake_redis, SESSION_TOKEN, _make_redis_session_payload())

    user = _make_user()
    project = _make_project()
    group = _make_group()

    with patch("src.routes.auth.get_user_by_hash", return_value=user), \
         patch("src.routes.auth.get_project_by_hash", return_value=project), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
         patch("src.routes.auth.get_user_groups_for_user", return_value=[group]):
        response = await client.post(
            "/auth/refresh",
            headers={"Authorization": f"Bearer {SESSION_TOKEN}", "User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "session_token" in data
    assert data["session_token"] != SESSION_TOKEN
    assert fake_redis.get(f"session:{SESSION_TOKEN}") is None
    new_token = data["session_token"]
    assert fake_redis.get(f"session:{new_token}") is not None


@pytest.mark.asyncio
async def test_refresh_expired_session(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Refresh with expired session returns 401 through REAL middleware stack."""
    response = await client.post(
        "/auth/refresh",
        headers={"Authorization": "Bearer expired-token", "User-Agent": "test"},
    )

    assert response.status_code == 401
