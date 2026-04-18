"""
Slice 6 — Permission Enforcement (Auth Boundary Tests)

Tests: Unauthenticated → 401 on protected endpoints. Consumer → 403 on admin endpoints.
Admin → 403 on root-only endpoints. Root → 200 everywhere.
Uses the REAL app with all middleware active.
"""

from unittest.mock import patch, MagicMock

import pytest

from tests.integration.conftest import make_session_payload, create_test_session


def _make_session(user_type="consumer", user_id="1", user_hash="usr-test-001",
                  project_hash="prj-test-001", project_id="1", permissions=None,
                  session_token="test-token"):
    s = MagicMock()
    s.user_id = user_id
    s.user_hash = user_hash
    s.user_type = user_type
    s.project_hash = project_hash
    s.project_name = "Test Project"
    s.project_id = project_id
    s.permissions = permissions or []
    s.groups = []
    s.session_token = session_token
    s.session_length = 259200
    s.username = "testuser"
    return s


def _make_user(user_type="consumer", user_id="1", user_hash="usr-test-001",
               username="testuser"):
    u = MagicMock()
    u.id = user_id
    u.user_hash = user_hash
    u.username = username
    u.email = "test@example.com"
    u.user_type = user_type
    u.is_active = True
    u.assigned_project_id = None
    return u


# ─── Unauthenticated → 401 ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unauthenticated_profile_returns_401(client, fake_redis, patched_db_connection,
                                                    patched_db_error_logger, patched_audit_logger,
                                                    patched_audit_ids, patched_cache_manager,
                                                    patched_activity_logger):
    """GET /users/profile without auth returns 401."""
    response = await client.get("/users/profile", headers={"User-Agent": "test"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_unauthenticated_projects_returns_401(client, fake_redis, patched_db_connection,
                                                     patched_db_error_logger, patched_audit_logger,
                                                     patched_audit_ids, patched_cache_manager,
                                                     patched_activity_logger):
    """GET /projects without auth returns 401."""
    response = await client.get("/projects", headers={"User-Agent": "test"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_unauthenticated_users_list_returns_401(client, fake_redis, patched_db_connection,
                                                       patched_db_error_logger, patched_audit_logger,
                                                       patched_audit_ids, patched_cache_manager,
                                                       patched_activity_logger):
    """GET /users/list without auth returns 401."""
    response = await client.get("/users/list", headers={"User-Agent": "test"})
    assert response.status_code == 401


# ─── Consumer → 403 on admin endpoints ───────────────────────────────────────

@pytest.mark.asyncio
async def test_consumer_cannot_list_users(client, fake_redis, patched_db_connection,
                                           patched_db_error_logger, patched_audit_logger,
                                           patched_audit_ids, patched_cache_manager,
                                           patched_activity_logger):
    """Consumer user gets 403 on GET /users/list."""
    token = "test-consumer-token"
    session = _make_session(user_type="consumer", session_token=token)
    create_test_session(fake_redis, token, make_session_payload(
        user_type="consumer", session_token=token))

    # users.py uses HTTPBearerOrCookie → Seccurity.validate_session
    # and @log_and_handle_errors → decorators.validate_session
    with patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.Util.decorators.validate_session", return_value=session), \
         patch("src.Util.decorators.get_user_by_hash", return_value=_make_user(user_type="consumer")), \
         patch("src.routes.users.get_user_by_hash", return_value=_make_user(user_type="consumer")), \
         patch("src.routes.users.is_root_user", return_value=False), \
         patch("src.routes.users.get_user_type", return_value="consumer"):
        response = await client.get(
            "/users/list",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_consumer_cannot_create_project(client, fake_redis, patched_db_connection,
                                               patched_db_error_logger, patched_audit_logger,
                                               patched_audit_ids, patched_cache_manager,
                                               patched_activity_logger):
    """Consumer user gets 403 on POST /projects."""
    token = "test-consumer-token2"
    session = _make_session(user_type="consumer", session_token=token)
    create_test_session(fake_redis, token, make_session_payload(
        user_type="consumer", session_token=token))

    # projects.py directly imports validate_session from src.Util.db
    # Admin check is done via session_data.permissions, not is_admin_user
    with patch("src.Util.db.validate_session", return_value=session), \
         patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.routes.projects.validate_session", return_value=session), \
         patch("src.routes.projects.get_user_by_hash", return_value=_make_user(user_type="consumer")):
        response = await client.post(
            "/projects",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
            data={"project_name": "Test", "project_description": "Test"},
        )

    assert response.status_code == 403


# ─── Admin → 403 on root-only endpoints ──────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_cannot_change_user_type(client, fake_redis, patched_db_connection,
                                              patched_db_error_logger, patched_audit_logger,
                                              patched_audit_ids, patched_cache_manager,
                                              patched_activity_logger):
    """Admin user gets 403 on PATCH /users/{hash}/type (root only)."""
    token = "test-admin-token"
    session = _make_session(user_type="admin", session_token=token,
                            permissions=["admin"])
    create_test_session(fake_redis, token, make_session_payload(
        user_type="admin", session_token=token, permissions=["admin"]))

    with patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.Util.decorators.validate_session", return_value=session), \
         patch("src.Util.decorators.get_user_by_hash", return_value=_make_user(user_type="admin")), \
         patch("src.routes.users.get_user_by_hash", return_value=_make_user(user_type="admin")), \
         patch("src.routes.users.is_root_user", return_value=False), \
         patch("src.routes.users.get_user_type", return_value="admin"):
        response = await client.patch(
            "/users/usr-test-001/type",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
            data={"user_type": "admin"},
        )

    assert response.status_code == 403


# ─── Root → 200 everywhere ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_root_can_list_users(client, fake_redis, patched_db_connection,
                                    patched_db_error_logger, patched_audit_logger,
                                    patched_audit_ids, patched_cache_manager,
                                    patched_activity_logger):
    """Root user can access GET /users/list."""
    token = "test-root-token"
    session = _make_session(user_type="root", user_id="0", user_hash="usr-root-001",
                            project_hash=None, project_id=None, session_token=token)
    create_test_session(fake_redis, token, make_session_payload(
        user_type="root", user_id="0", user_hash="usr-root-001",
        project_hash=None, project_id=None, session_token=token))

    root_user = _make_user(user_type="root", user_id="0", user_hash="usr-root-001")

    with patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.Util.decorators.validate_session", return_value=session), \
         patch("src.Util.decorators.get_user_by_hash", return_value=root_user), \
         patch("src.routes.users.get_user_by_hash", return_value=root_user), \
         patch("src.routes.users.is_root_user", return_value=True), \
         patch("src.routes.users.get_user_type", return_value="root"), \
         patch("src.routes.users.list_users_with_access", return_value=[]), \
         patch("src.routes.users.count_users", return_value=0), \
         patch("src.routes.users.get_user_accessible_projects", return_value=[]), \
         patch("src.routes.users.get_user_type_info", return_value=MagicMock()), \
         patch("src.routes.users.get_project_by_hash", return_value=None), \
         patch("src.routes.users.get_user_effective_permissions", return_value=[]), \
         patch("src.routes.users.get_user_groups_in_project_by_hash", return_value=[]):
        response = await client.get(
            "/users/list?page=1&per_page=10",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_root_can_change_user_type(client, fake_redis, patched_db_connection,
                                          patched_db_error_logger, patched_audit_logger,
                                          patched_audit_ids, patched_cache_manager,
                                          patched_activity_logger):
    """Root user can access PATCH /users/{hash}/type."""
    token = "test-root-token2"
    session = _make_session(user_type="root", user_id="0", user_hash="usr-root-001",
                            project_hash=None, project_id=None, session_token=token)
    create_test_session(fake_redis, token, make_session_payload(
        user_type="root", user_id="0", user_hash="usr-root-001",
        project_hash=None, project_id=None, session_token=token))

    root_user = _make_user(user_type="root", user_id="0", user_hash="usr-root-001")
    target_user = _make_user(user_type="consumer", user_id="2", user_hash="usr-target-001")

    with patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.Util.decorators.validate_session", return_value=session), \
         patch("src.Util.decorators.get_user_by_hash", side_effect=lambda h, **kw: root_user if h == "usr-root-001" else target_user), \
         patch("src.routes.users.get_user_by_hash", side_effect=lambda h, **kw: root_user if h == "usr-root-001" else target_user), \
         patch("src.routes.users.is_root_user", return_value=True), \
         patch("src.routes.users.get_user_type", return_value="root"), \
         patch("src.routes.users.update_user_type", return_value={"success": True}):
        response = await client.patch(
            "/users/usr-target-001/type",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
            data={"user_type": "admin"},
        )

    assert response.status_code == 200


# ─── verify_session dependency rejects missing tokens ────────────────────────

@pytest.mark.asyncio
async def test_missing_bearer_on_protected_endpoint(client, fake_redis, patched_db_connection,
                                                     patched_db_error_logger, patched_audit_logger,
                                                     patched_audit_ids, patched_cache_manager,
                                                     patched_activity_logger):
    """No Authorization header on protected endpoint → 401."""
    response = await client.get(
        "/users/profile",
        headers={"User-Agent": "test"},
    )
    assert response.status_code == 401
