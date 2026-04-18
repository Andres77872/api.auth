"""
Slice 19 (Strategy Slice 4) — User Group → Project Group Linking Orchestration

Characterization test: Verify POST/DELETE /admin/user-groups/{hash}/project-groups
call the correct DB functions (grant_user_group_project_group_access,
revoke_user_group_project_group_access) with correct parameters.

Proof layer: Layer 2 (integration, mocked DB)
Trace: explore.md Gap 3, RISK 1
"""

from unittest.mock import patch, MagicMock

import pytest

from tests.integration.conftest import make_session_payload, create_test_session


def _make_admin_session(user_id="admin-1", user_hash="usr-admin-001",
                        session_token="test-admin-token"):
    s = MagicMock()
    s.user_id = user_id
    s.user_hash = user_hash
    s.user_type = "admin"
    s.project_id = "1"
    s.project_hash = "prj-admin-001"
    s.permissions = ["admin"]
    s.session_token = session_token
    return s


def _make_user_group(group_id="ug-1", group_hash="grp-ug-link-001", group_name="Link Group"):
    g = MagicMock()
    g.id = group_id
    g.group_hash = group_hash
    g.group_name = group_name
    g.group_description = "A link test group"
    return g


def _make_project_group(pg_id="pg-1", group_hash="grp-pg-link-001", group_name="Link PG"):
    pg = MagicMock()
    pg.id = pg_id
    pg.group_hash = group_hash
    pg.group_name = group_name
    pg.group_description = "A link test project group"
    pg.permissions = []
    return pg


@pytest.mark.asyncio
async def test_grant_ug_pg_calls_correct_db_function(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """POST /admin/user-groups/{hash}/project-groups must call grant_user_group_project_group_access."""
    ug = _make_user_group()
    pg = _make_project_group()
    token = "grant-test-token"
    admin_session = _make_admin_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    captured_args = None

    def capture_grant(ug_id, pg_id, granted_by):
        nonlocal captured_args
        captured_args = (ug_id, pg_id, granted_by)
        return {
            "access_id": "access-1",
            "user_group_id": ug_id,
            "project_group_id": pg_id,
            "granted_by": granted_by,
        }

    with patch("src.routes.admin_user_groups.validate_session", return_value=admin_session), \
         patch("src.routes.admin_user_groups.get_user_group_by_hash", return_value=ug), \
         patch("src.routes.admin_user_groups.get_project_permission_group_by_hash", return_value=pg), \
         patch("src.routes.admin_user_groups.get_user_by_hash", return_value=MagicMock(id="admin-1")), \
         patch("src.routes.admin_user_groups.grant_user_group_project_group_access", side_effect=capture_grant):
        response = await client.post(
            "/admin/user-groups/grp-ug-link-001/project-groups",
            data={"project_group_hash": "grp-pg-link-001"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert captured_args is not None
    assert captured_args[0] == "ug-1"       # user_group.id
    assert captured_args[1] == "pg-1"       # project_group.id
    assert captured_args[2] == "admin-1"    # granted_by (current user id)


@pytest.mark.asyncio
async def test_revoke_ug_pg_calls_correct_db_function(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """DELETE /admin/user-groups/{hash}/project-groups/{pg_hash} must call revoke_user_group_project_group_access."""
    ug = _make_user_group()
    pg = _make_project_group()
    token = "revoke-test-token"
    admin_session = _make_admin_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    captured_args = None

    def capture_revoke(ug_id, pg_id, revoked_by):
        nonlocal captured_args
        captured_args = (ug_id, pg_id, revoked_by)
        return True

    with patch("src.routes.admin_user_groups.validate_session", return_value=admin_session), \
         patch("src.routes.admin_user_groups.get_user_group_by_hash", return_value=ug), \
         patch("src.routes.admin_user_groups.get_project_permission_group_by_hash", return_value=pg), \
         patch("src.routes.admin_user_groups.get_user_by_hash", return_value=MagicMock(id="admin-1")), \
         patch("src.routes.admin_user_groups.revoke_user_group_project_group_access", side_effect=capture_revoke):
        response = await client.request(
            "DELETE",
            "/admin/user-groups/grp-ug-link-001/project-groups/grp-pg-link-001",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert captured_args is not None
    assert captured_args[0] == "ug-1"       # user_group.id
    assert captured_args[1] == "pg-1"       # project_group.id
    assert captured_args[2] == "admin-1"    # revoked_by


@pytest.mark.asyncio
async def test_grant_ug_pg_returns_404_for_missing_user_group(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Grant must return 404 if user group doesn't exist."""
    token = "grant-404-token"
    admin_session = _make_admin_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    with patch("src.routes.admin_user_groups.validate_session", return_value=admin_session), \
         patch("src.routes.admin_user_groups.get_user_group_by_hash", return_value=None):
        response = await client.post(
            "/admin/user-groups/nonexistent-group/project-groups",
            data={"project_group_hash": "grp-pg-link-001"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_grant_ug_pg_returns_404_for_missing_project_group(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Grant must return 404 if project group doesn't exist."""
    ug = _make_user_group()
    token = "grant-404-pg-token"
    admin_session = _make_admin_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    with patch("src.routes.admin_user_groups.validate_session", return_value=admin_session), \
         patch("src.routes.admin_user_groups.get_user_group_by_hash", return_value=ug), \
         patch("src.routes.admin_user_groups.get_project_permission_group_by_hash", return_value=None):
        response = await client.post(
            "/admin/user-groups/grp-ug-link-001/project-groups",
            data={"project_group_hash": "nonexistent-pg"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_revoke_ug_pg_returns_404_for_missing_user_group(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Revoke must return 404 if user group doesn't exist."""
    token = "revoke-404-token"
    admin_session = _make_admin_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    with patch("src.routes.admin_user_groups.validate_session", return_value=admin_session), \
         patch("src.routes.admin_user_groups.get_user_group_by_hash", return_value=None):
        response = await client.request(
            "DELETE",
            "/admin/user-groups/nonexistent-group/project-groups/grp-pg-link-001",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_grant_ug_pg_response_contains_access_details(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Grant response must include access_details, user_group, and project_group info."""
    ug = _make_user_group()
    pg = _make_project_group()
    token = "grant-details-token"
    admin_session = _make_admin_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    access_result = {
        "access_id": "access-123",
        "user_group_id": "ug-1",
        "project_group_id": "pg-1",
        "granted_by": "admin-1",
    }

    with patch("src.routes.admin_user_groups.validate_session", return_value=admin_session), \
         patch("src.routes.admin_user_groups.get_user_group_by_hash", return_value=ug), \
         patch("src.routes.admin_user_groups.get_project_permission_group_by_hash", return_value=pg), \
         patch("src.routes.admin_user_groups.get_user_by_hash", return_value=MagicMock(id="admin-1")), \
         patch("src.routes.admin_user_groups.grant_user_group_project_group_access", return_value=access_result):
        response = await client.post(
            "/admin/user-groups/grp-ug-link-001/project-groups",
            data={"project_group_hash": "grp-pg-link-001"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "access_details" in data
    assert "user_group" in data
    assert "project_group" in data
    assert data["user_group"]["group_hash"] == "grp-ug-link-001"
    assert data["project_group"]["group_hash"] == "grp-pg-link-001"
