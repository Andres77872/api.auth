"""
Slice 5 — Auth Flow: Switch Project + Check Availability

Tests: POST /auth/switch-project (valid switch → 200 + new token, invalid project → 404),
POST /auth/check-availability (available → 200, taken → 409).

All tests run through the REAL app with ALL middleware active (CORS, RequestValidation,
APIAudit, AuthContext). No workaround app is used.
"""

import json
from unittest.mock import patch, MagicMock

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


def _make_redis_session_payload(user_hash="usr-test-001", user_id="1",
                                user_type="consumer", project_hash="prj-test-001",
                                project_name="Test Project", project_id="1"):
    return {
        "session_id": 12345,
        "user_id": user_id,
        "user_hash": user_hash,
        "user_type": user_type,
        "project_id": project_id,
        "project_hash": project_hash,
        "project_name": project_name,
        "user_group_ids": [],
        "user_group_names": [],
    }


SESSION_TOKEN = "test-session-token-switch"


def _store_session_in_redis(fake_redis, token, payload):
    fake_redis.set(f"session:{token}", json.dumps(payload), ex=259200)


@pytest.mark.asyncio
async def test_switch_project_valid(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Valid switch requires access + current refresh and rotates both credentials."""
    from src.Util.auth_lifecycle import issue_project_token_pair

    user = _make_user()
    current_project = _make_project(project_hash="prj-test-001", project_name="Test Project")
    new_project = _make_project(project_hash="prj-other-002", project_name="Other Project")
    group = _make_group()
    with patch("src.Util.auth_lifecycle.redis_client", fake_redis):
        pair = issue_project_token_pair(
            user={"id": user.id, "user_hash": user.user_hash, "username": user.username, "user_type": user.user_type},
            project={"id": current_project.id, "project_hash": current_project.project_hash, "project_name": current_project.project_name},
            groups=[group.group_name],
            permissions=[],
            remember_me=True,
        )
    old_access_jti = pair.access_claims["jti"]

    with patch("src.routes.auth.get_user_by_hash", return_value=user), \
          patch("src.routes.auth.get_project_by_hash", return_value=new_project), \
          patch("src.routes.auth.get_user_accessible_projects", return_value=[new_project]), \
          patch("src.routes.auth.get_user_groups_in_project", return_value=[group]):
        response = await client.post(
            "/auth/switch-project",
            data={"project_hash": "prj-other-002", "refresh_token": pair.refresh_token},
            cookies={"refresh_token": pair.refresh_token},
            headers={"Authorization": f"Bearer {pair.access_token}", "User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["session_token"] == data["access_token"]
    assert data["project"]["project_hash"] == "prj-other-002"
    assert data["remember_me"] is True
    assert fake_redis.get(f"session:{old_access_jti}") is None


@pytest.mark.asyncio
async def test_switch_project_rejects_refresh_token_as_access_credential(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Refresh JWTs are not valid access credentials for switch-project."""
    from src.Util.auth_lifecycle import issue_project_token_pair

    user = _make_user()
    current_project = _make_project(project_hash="prj-test-001", project_name="Test Project")
    group = _make_group()
    with patch("src.Util.auth_lifecycle.redis_client", fake_redis):
        pair = issue_project_token_pair(
            user={"id": user.id, "user_hash": user.user_hash, "username": user.username, "user_type": user.user_type},
            project={"id": current_project.id, "project_hash": current_project.project_hash, "project_name": current_project.project_name},
            groups=[group.group_name],
            permissions=[],
        )

    response = await client.post(
        "/auth/switch-project",
        data={"project_hash": "prj-other-002", "refresh_token": pair.refresh_token},
        headers={"Authorization": f"Bearer {pair.refresh_token}", "User-Agent": "test"},
    )

    assert response.status_code == 401
    data = response.json()
    assert data["status"] == "error"
    assert "type" in data["error"]["message"].lower() or "access" in data["error"]["message"].lower()


@pytest.mark.asyncio
async def test_switch_project_not_found(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Switch to nonexistent project returns 404 through REAL middleware stack."""
    from src.Util.auth_lifecycle import issue_project_token_pair

    user = _make_user()
    current_project = _make_project(project_hash="prj-test-001", project_name="Test Project")
    group = _make_group()
    with patch("src.Util.auth_lifecycle.redis_client", fake_redis):
        pair = issue_project_token_pair(
            user={"id": user.id, "user_hash": user.user_hash, "username": user.username, "user_type": user.user_type},
            project={"id": current_project.id, "project_hash": current_project.project_hash, "project_name": current_project.project_name},
            groups=[group.group_name],
            permissions=[],
        )

    with patch("src.routes.auth.get_user_by_hash", return_value=user), \
         patch("src.routes.auth.get_project_by_hash", side_effect=[current_project, None]), \
         patch("src.routes.auth.get_user_groups_in_project_by_hash", return_value=[group]), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[current_project]):
        response = await client.post(
            "/auth/switch-project",
            data={"project_hash": "prj-nonexistent", "refresh_token": pair.refresh_token},
            cookies={"refresh_token": pair.refresh_token},
            headers={"Authorization": f"Bearer {pair.access_token}", "User-Agent": "test"},
        )

    assert response.status_code == 404
    data = response.json()
    assert data["status"] == "error"


@pytest.mark.asyncio
async def test_switch_project_access_denied(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Switch to project user doesn't have access to returns 403 through REAL middleware stack."""
    from src.Util.auth_lifecycle import issue_project_token_pair

    user = _make_user()
    current_project = _make_project(project_hash="prj-test-001", project_name="Test Project")
    other_project = _make_project(project_hash="prj-other-002", project_name="Other Project")
    group = _make_group()
    with patch("src.Util.auth_lifecycle.redis_client", fake_redis):
        pair = issue_project_token_pair(
            user={"id": user.id, "user_hash": user.user_hash, "username": user.username, "user_type": user.user_type},
            project={"id": current_project.id, "project_hash": current_project.project_hash, "project_name": current_project.project_name},
            groups=[group.group_name],
            permissions=[],
        )

    with patch("src.routes.auth.get_user_by_hash", return_value=user), \
         patch("src.routes.auth.get_project_by_hash", side_effect=[current_project, other_project]), \
         patch("src.routes.auth.get_user_groups_in_project_by_hash", return_value=[group]), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[]):
        response = await client.post(
            "/auth/switch-project",
            data={"project_hash": "prj-other-002", "refresh_token": pair.refresh_token},
            cookies={"refresh_token": pair.refresh_token},
            headers={"Authorization": f"Bearer {pair.access_token}", "User-Agent": "test"},
        )

    assert response.status_code == 403
    data = response.json()
    assert data["status"] == "error"


@pytest.mark.asyncio
async def test_switch_project_invalid_session(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Switch project with invalid session returns 401 through REAL middleware stack."""
    response = await client.post(
        "/auth/switch-project",
        data={"project_hash": "prj-test-001"},
        headers={"Authorization": "Bearer invalid-token", "User-Agent": "test"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_check_availability_username_available(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Check availability for available username returns 200."""
    with patch("src.routes.auth.check_username_email_available", return_value=True):
        response = await client.post(
            "/auth/check-availability",
            data={"username": "newuser"},
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["username_available"] is True


@pytest.mark.asyncio
async def test_check_availability_username_taken(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Check availability for taken username returns 200 with available=False."""
    with patch("src.routes.auth.check_username_email_available", return_value=False):
        response = await client.post(
            "/auth/check-availability",
            data={"username": "existinguser"},
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["username_available"] is False


@pytest.mark.asyncio
async def test_check_availability_email(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Check availability for email works correctly."""
    with patch("src.routes.auth.check_username_email_available", return_value=True):
        response = await client.post(
            "/auth/check-availability",
            data={"email": "new@example.com"},
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["email_available"] is True


@pytest.mark.asyncio
async def test_check_availability_missing_fields(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Check availability without username or email returns 400."""
    response = await client.post(
        "/auth/check-availability",
        data={},
        headers={"User-Agent": "test"},
    )

    assert response.status_code in (400, 422)
