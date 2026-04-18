"""
Slice 7 — User Profile & Access Summary

Tests: GET /users/profile, GET /users/access-summary, PUT /users/profile.
Uses the REAL app with all middleware active.

NOTE: users.py uses HTTPBearerOrCookie (Seccurity.validate_session) for auth
and @log_and_handle_errors (decorators.validate_session) for log context.
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


@pytest.mark.asyncio
async def test_get_user_profile_returns_200(client, fake_redis, patched_db_connection,
                                             patched_db_error_logger, patched_audit_logger,
                                             patched_audit_ids, patched_cache_manager,
                                             patched_activity_logger):
    """GET /users/profile returns 200 with profile data for authenticated user."""
    token = "test-profile-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    user = _make_user()
    group = MagicMock()
    group.id = "1"
    group.group_hash = "grp-001"
    group.group_name = "Test Group"
    group.group_description = "A group"

    project = MagicMock()
    project.id = "1"
    project.project_hash = "prj-001"
    project.project_name = "Test Project"
    project.project_description = "A test project"

    membership = MagicMock()
    membership.joined_at = None
    membership.is_active = True
    membership.assigned_at = None
    membership.assigned_by = None

    type_info = {
        "role_name": None,
        "role_hash": None,
        "role_description": None,
        "permissions": [],
    }

    with patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.Util.decorators.validate_session", return_value=session), \
         patch("src.Util.decorators.get_user_by_hash", return_value=user), \
         patch("src.routes.users.get_user_by_hash", return_value=user), \
         patch("src.routes.users.get_user_type_info", return_value=type_info), \
         patch("src.routes.users.get_user_groups_for_user", return_value=[group]), \
         patch("src.routes.users.get_user_accessible_projects", return_value=[project]), \
         patch("src.routes.users.get_user_group_membership", return_value=membership), \
         patch("src.routes.users.get_user_effective_permissions", return_value=[]):
        response = await client.get(
            "/users/profile",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    # Profile response shape: {user: {...}, groups: [...], accessible_projects: [...]}
    # or may be wrapped differently
    assert "user" in data or "profile" in data or "username" in str(data)


@pytest.mark.asyncio
async def test_get_user_profile_unauthenticated_returns_401(client, fake_redis, patched_db_connection,
                                                             patched_db_error_logger, patched_audit_logger,
                                                             patched_audit_ids, patched_cache_manager,
                                                             patched_activity_logger):
    """GET /users/profile without auth returns 401."""
    response = await client.get(
        "/users/profile",
        headers={"User-Agent": "test"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_access_summary_returns_200(client, fake_redis, patched_db_connection,
                                               patched_db_error_logger, patched_audit_logger,
                                               patched_audit_ids, patched_cache_manager,
                                               patched_activity_logger):
    """GET /users/access-summary returns 200 with hierarchical access data."""
    token = "test-summary-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    user = _make_user()
    group = MagicMock()
    group.id = "1"
    group.group_hash = "grp-001"
    group.group_name = "Test Group"
    group.group_description = "A group"

    project = MagicMock()
    project.id = "1"
    project.project_hash = "prj-001"
    project.project_name = "Test Project"
    project.project_description = "A test project"

    membership = MagicMock()
    membership.joined_at = None
    membership.is_active = True
    membership.assigned_at = None
    membership.assigned_by = None

    type_info = {
        "role_name": None,
        "role_hash": None,
        "role_description": None,
        "permissions": [],
    }

    with patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.Util.decorators.validate_session", return_value=session), \
         patch("src.Util.decorators.get_user_by_hash", return_value=user), \
         patch("src.routes.users.get_user_by_hash", return_value=user), \
         patch("src.routes.users.get_user_type_info", return_value=type_info), \
         patch("src.routes.users.get_user_groups_for_user", return_value=[group]), \
         patch("src.routes.users.get_user_accessible_projects", return_value=[project]), \
         patch("src.routes.users.get_user_group_membership", return_value=membership), \
         patch("src.routes.users.get_user_effective_permissions", return_value=[]), \
         patch("src.routes.users.get_projects_for_user_group", return_value=[project]), \
         patch("src.routes.users.get_user_groups_in_project_by_hash", return_value=[]):
        response = await client.get(
            "/users/access-summary",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert "access_summary" in data or "user" in data


@pytest.mark.asyncio
async def test_update_user_profile_returns_200(client, fake_redis, patched_db_connection,
                                                patched_db_error_logger, patched_audit_logger,
                                                patched_audit_ids, patched_cache_manager,
                                                patched_activity_logger):
    """PUT /users/profile returns 200 with updated profile."""
    token = "test-update-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    user = _make_user()

    updated_user = MagicMock()
    updated_user.user_hash = "usr-test-001"
    updated_user.username = "testuser"
    updated_user.email = "newemail@example.com"
    updated_user.user_type = "consumer"
    updated_user.id = "1"

    with patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.Util.decorators.validate_session", return_value=session), \
         patch("src.Util.decorators.get_user_by_hash", return_value=user), \
         patch("src.routes.users.get_user_by_hash", return_value=user), \
         patch("src.routes.users.update_user", return_value=updated_user):
        response = await client.put(
            "/users/profile",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
            data={"email": "newemail@example.com"},
        )

    assert response.status_code == 200
