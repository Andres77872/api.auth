"""
Slice 8 — User Management (Admin Operations)

Tests: GET /users/list, GET /users/{hash}, PUT /users/{hash}/status,
DELETE /users/{hash}, POST /users/{hash}/reset-password.
Uses the REAL app with all middleware active.

NOTE: users.py uses HTTPBearerOrCookie (Seccurity.validate_session) for auth
and @log_and_handle_errors (decorators.validate_session) for log context.
"""

from unittest.mock import patch, MagicMock

import pytest

from tests.integration.conftest import make_session_payload, create_test_session


def _make_session(user_type="admin", user_id="1", user_hash="usr-admin-001",
                  project_hash="prj-test-001", project_id="1", permissions=None,
                  session_token="test-token"):
    s = MagicMock()
    s.user_id = user_id
    s.user_hash = user_hash
    s.user_type = user_type
    s.project_hash = project_hash
    s.project_name = "Test Project"
    s.project_id = project_id
    s.permissions = permissions or ["admin"]
    s.groups = []
    s.session_token = session_token
    s.session_length = 259200
    s.username = "adminuser"
    return s


def _make_user(user_type="admin", user_id="1", user_hash="usr-admin-001",
               username="adminuser", email="admin@example.com"):
    u = MagicMock()
    u.id = user_id
    u.user_hash = user_hash
    u.username = username
    u.email = email
    u.user_type = user_type
    u.is_active = True
    u.assigned_project_id = "1"
    return u


@pytest.mark.asyncio
async def test_admin_list_users_returns_200(client, fake_redis, patched_db_connection,
                                             patched_db_error_logger, patched_audit_logger,
                                             patched_audit_ids, patched_cache_manager,
                                             patched_activity_logger):
    """Admin can GET /users/list with paginated results."""
    token = "test-admin-list-token"
    session = _make_session(session_token=token, user_type="admin", permissions=["admin"])
    create_test_session(fake_redis, token, make_session_payload(
        user_type="admin", session_token=token, permissions=["admin"]))

    admin_user = _make_user(user_type="admin")

    with patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.Util.decorators.validate_session", return_value=session), \
         patch("src.Util.decorators.get_user_by_hash", return_value=admin_user), \
         patch("src.routes.users.get_user_by_hash", return_value=admin_user), \
         patch("src.routes.users.is_root_user", return_value=False), \
         patch("src.routes.users.get_user_type", return_value="admin"), \
         patch("src.routes.users.list_users_with_access", return_value=[]), \
         patch("src.routes.users.count_users", return_value=0), \
         patch("src.routes.users.get_user_accessible_projects", return_value=[]), \
         patch("src.routes.users.get_user_type_info", return_value=MagicMock()), \
         patch("src.routes.users.get_project_by_hash", return_value=MagicMock()), \
         patch("src.routes.users.get_user_effective_permissions", return_value=["admin"]), \
         patch("src.routes.users.get_user_groups_in_project_by_hash", return_value=[]):
        response = await client.get(
            "/users/list?page=1&per_page=10",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert "users" in data or "data" in data


@pytest.mark.asyncio
async def test_admin_get_user_details_returns_200(client, fake_redis, patched_db_connection,
                                                   patched_db_error_logger, patched_audit_logger,
                                                   patched_audit_ids, patched_cache_manager,
                                                   patched_activity_logger):
    """Admin can GET /users/{hash} for user details."""
    token = "test-admin-details-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    admin_user = _make_user()
    target_user = _make_user(user_id="2", user_hash="usr-target-001", username="targetuser")
    shared_project = MagicMock()
    shared_project.id = "1"
    shared_project.project_hash = "prj-test-001"
    shared_project.project_name = "Shared Project"

    with patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.Util.decorators.validate_session", return_value=session), \
         patch("src.Util.decorators.get_user_by_hash", side_effect=lambda h, **kw: admin_user if h == "usr-admin-001" else target_user), \
         patch("src.routes.users.get_user_by_hash", side_effect=lambda h, **kw: admin_user if h == "usr-admin-001" else target_user), \
         patch("src.routes.users.is_root_user", return_value=False), \
         patch("src.routes.users.get_user_type", return_value="admin"), \
         patch("src.routes.users.get_user_accessible_projects", return_value=[shared_project]), \
         patch("src.routes.users.get_user_type_info", return_value=MagicMock()), \
         patch("src.routes.users.get_user_groups_for_user", return_value=[]), \
         patch("src.routes.users.get_user_group_membership", return_value=MagicMock()), \
         patch("src.routes.users.get_projects_for_user_group", return_value=[]), \
         patch("src.routes.users.get_user_effective_permissions", return_value=[]), \
         patch("src.routes.users.get_user_groups_in_project_by_hash", return_value=[]), \
         patch("src.routes.users.get_project_by_hash", return_value=MagicMock()):
        response = await client.get(
            "/users/usr-target-001",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_admin_update_user_status_returns_200(client, fake_redis, patched_db_connection,
                                                     patched_db_error_logger, patched_audit_logger,
                                                     patched_audit_ids, patched_cache_manager,
                                                     patched_activity_logger):
    """Admin can PUT /users/{hash}/status to activate/deactivate."""
    token = "test-admin-status-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    admin_user = _make_user()
    target_user = _make_user(user_id="2", user_hash="usr-target-001")
    shared_project = MagicMock()
    shared_project.id = "1"
    shared_project.project_hash = "prj-test-001"
    shared_project.project_name = "Shared Project"
    shared_project.project_description = "A shared project"

    with patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.Util.decorators.validate_session", return_value=session), \
         patch("src.Util.decorators.get_user_by_hash", side_effect=lambda h, **kw: admin_user if h == "usr-admin-001" else target_user), \
         patch("src.routes.users.get_user_by_hash", side_effect=lambda h, **kw: admin_user if h == "usr-admin-001" else target_user), \
         patch("src.routes.users.is_root_user", return_value=False), \
         patch("src.routes.users.get_user_type", return_value="admin"), \
         patch("src.routes.users.get_user_accessible_projects", return_value=[shared_project]), \
         patch("src.routes.users.update_user", return_value={"success": True}), \
         patch("src.Util.db.invalidate_user_sessions", return_value=True), \
         patch("src.Util.cache_manager.cache_manager.invalidate_user_cache", return_value=True):
        response = await client.put(
            "/users/usr-target-001/status",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
            params={"is_active": "false"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


@pytest.mark.asyncio
async def test_admin_deactivate_user_revokes_refresh_families(client, fake_redis, patched_db_connection,
                                                              patched_db_error_logger, patched_audit_logger,
                                                              patched_audit_ids, patched_cache_manager,
                                                              patched_activity_logger):
    """Deactivation must call lifecycle user-wide auth revocation, not just legacy sessions."""
    token = "test-admin-status-revoke-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    admin_user = _make_user()
    target_user = _make_user(user_id="2", user_hash="usr-target-001")
    shared_project = MagicMock()
    shared_project.id = "1"
    shared_project.project_hash = "prj-test-001"
    shared_project.project_name = "Shared Project"

    with patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.Util.decorators.validate_session", return_value=session), \
         patch("src.Util.decorators.get_user_by_hash", side_effect=lambda h, **kw: admin_user if h == "usr-admin-001" else target_user), \
         patch("src.routes.users.get_user_by_hash", side_effect=lambda h, **kw: admin_user if h == "usr-admin-001" else target_user), \
         patch("src.routes.users.is_root_user", return_value=False), \
         patch("src.routes.users.get_user_type", return_value="admin"), \
         patch("src.routes.users.get_user_accessible_projects", return_value=[shared_project]), \
         patch("src.routes.users.update_user", return_value={"success": True}), \
         patch("src.routes.users.revoke_user_auth_state", create=True) as revoke_auth_state:
        response = await client.put(
            "/users/usr-target-001/status",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
            params={"is_active": "false"},
        )

    assert response.status_code == 200
    revoke_auth_state.assert_called_once_with("2", reason="user_deactivated")


@pytest.mark.asyncio
async def test_admin_reset_password_no_plaintext(client, fake_redis, patched_db_connection,
                                                  patched_db_error_logger, patched_audit_logger,
                                                  patched_audit_ids, patched_cache_manager,
                                                  patched_activity_logger):
    """POST /users/{hash}/reset-password returns 200 WITHOUT temporary_password."""
    token = "test-admin-reset-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    admin_user = _make_user()
    target_user = _make_user(user_id="2", user_hash="usr-target-001")

    with patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.Util.decorators.validate_session", return_value=session), \
         patch("src.Util.decorators.get_user_by_hash", side_effect=lambda h, **kw: admin_user if h == "usr-admin-001" else target_user), \
         patch("src.routes.users.get_user_by_hash", side_effect=lambda h, **kw: admin_user if h == "usr-admin-001" else target_user), \
         patch("src.routes.users.get_user_type", return_value="admin"), \
         patch("src.routes.users.is_root_user", return_value=False), \
         patch("src.routes.users.update_user", return_value={
             "success": True,
             "expires_at": "2026-04-16T00:00:00Z",
             "must_change_on_login": True,
         }):
        response = await client.post(
            "/users/usr-target-001/reset-password",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    # KEY SECURITY ASSERTION: no plaintext password in response
    reset_data = data.get("reset_data", data)
    assert "temporary_password" not in reset_data, "SECURITY: temporary_password must not be in response"


@pytest.mark.asyncio
async def test_admin_delete_user_returns_200(client, fake_redis, patched_db_connection,
                                              patched_db_error_logger, patched_audit_logger,
                                              patched_audit_ids, patched_cache_manager,
                                              patched_activity_logger):
    """Admin can DELETE /users/{hash} (soft delete)."""
    token = "test-admin-delete-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    admin_user = _make_user()
    target_user = _make_user(user_id="2", user_hash="usr-target-001")
    shared_project = MagicMock()
    shared_project.id = "1"
    shared_project.project_hash = "prj-test-001"
    shared_project.project_name = "Shared Project"
    shared_project.project_description = "A shared project"

    with patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.Util.decorators.validate_session", return_value=session), \
         patch("src.Util.decorators.get_user_by_hash", side_effect=lambda h, **kw: admin_user if h == "usr-admin-001" else target_user), \
         patch("src.routes.users.get_user_by_hash", side_effect=lambda h, **kw: admin_user if h == "usr-admin-001" else target_user), \
         patch("src.routes.users.is_root_user", return_value=False), \
         patch("src.routes.users.get_user_type", return_value="admin"), \
         patch("src.routes.users.get_user_accessible_projects", return_value=[shared_project]), \
         patch("src.Util.db.delete_user", return_value={"success": True}), \
         patch("src.Util.db.invalidate_user_sessions", return_value=True), \
         patch("src.Util.cache_manager.cache_manager.invalidate_user_cache", return_value=True):
        response = await client.delete(
            "/users/usr-target-001",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


@pytest.mark.asyncio
async def test_admin_delete_user_revokes_refresh_families(client, fake_redis, patched_db_connection,
                                                          patched_db_error_logger, patched_audit_logger,
                                                          patched_audit_ids, patched_cache_manager,
                                                          patched_activity_logger):
    """Delete/soft-delete must revoke access sessions and refresh families centrally."""
    token = "test-admin-delete-revoke-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    admin_user = _make_user()
    target_user = _make_user(user_id="2", user_hash="usr-target-001")
    shared_project = MagicMock()
    shared_project.id = "1"
    shared_project.project_hash = "prj-test-001"
    shared_project.project_name = "Shared Project"

    with patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.Util.decorators.validate_session", return_value=session), \
         patch("src.Util.decorators.get_user_by_hash", side_effect=lambda h, **kw: admin_user if h == "usr-admin-001" else target_user), \
         patch("src.routes.users.get_user_by_hash", side_effect=lambda h, **kw: admin_user if h == "usr-admin-001" else target_user), \
         patch("src.routes.users.is_root_user", return_value=False), \
         patch("src.routes.users.get_user_type", return_value="admin"), \
         patch("src.routes.users.get_user_accessible_projects", return_value=[shared_project]), \
         patch("src.Util.db.delete_user", return_value={"success": True}), \
         patch("src.routes.users.revoke_user_auth_state", create=True) as revoke_auth_state:
        response = await client.delete(
            "/users/usr-target-001",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
        )

    assert response.status_code == 200
    revoke_auth_state.assert_called_once_with("2", reason="user_deleted")
