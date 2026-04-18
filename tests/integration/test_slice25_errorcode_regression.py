"""
Regression test: ErrorCode fix for admin_user_groups project-group 404 path.

This test proves that the fix for `ErrorCode.NOT_FOUND` → `ErrorCode.RESOURCE_NOT_FOUND`
in `src/routes/admin_user_groups.py` is correct and that the 404 path works at runtime.

The bug was: lines 517 and 587 used `ErrorCode.NOT_FOUND` which doesn't exist in the
ErrorCode enum, causing an AttributeError when project group was not found.

This is a runtime proof that the endpoints return 404 (not 500) for missing project groups.
"""

from unittest.mock import patch, MagicMock

import pytest

from tests.integration.conftest import make_session_payload, create_test_session


def _make_admin_session(user_id="admin-1", user_hash="usr-admin-001",
                        session_token="regression-token"):
    s = MagicMock()
    s.user_id = user_id
    s.user_hash = user_hash
    s.user_type = "admin"
    s.project_id = "1"
    s.project_hash = "prj-admin-001"
    s.permissions = ["admin"]
    s.session_token = session_token
    return s


def _make_user_group(group_id="ug-1", group_hash="grp-reg-001", group_name="Regression UG"):
    g = MagicMock()
    g.id = group_id
    g.group_hash = group_hash
    g.group_name = group_name
    g.group_description = "Regression test user group"
    return g


@pytest.mark.asyncio
async def test_grant_ug_pg_missing_project_group_returns_404_not_500(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """
    Regression: POST /admin/user-groups/{hash}/project-groups with missing project group
    must return 404 (not 500 from AttributeError on ErrorCode.NOT_FOUND).

    Before the fix: AttributeError: type object 'ErrorCode' has no attribute 'NOT_FOUND'
    After the fix: 404 with structured error response.
    """
    ug = _make_user_group()
    token = "regression-grant-404-token"
    admin_session = _make_admin_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    with patch("src.routes.admin_user_groups.validate_session", return_value=admin_session), \
         patch("src.routes.admin_user_groups.get_user_group_by_hash", return_value=ug), \
         patch("src.routes.admin_user_groups.get_project_permission_group_by_hash", return_value=None):
        response = await client.post(
            "/admin/user-groups/grp-reg-001/project-groups",
            data={"project_group_hash": "nonexistent-pg-hash"},
            headers={"Authorization": f"Bearer {token}"},
        )

    # Must be 404, NOT 500 (which would indicate the AttributeError bug)
    assert response.status_code == 404, (
        f"Expected 404 but got {response.status_code}. "
        "If 500, the ErrorCode.NOT_FOUND bug is NOT fixed."
    )
    data = response.json()
    assert data["status"] == "error"
    assert "error" in data
    assert "not found" in data["error"]["message"].lower()


@pytest.mark.asyncio
async def test_revoke_ug_pg_missing_project_group_returns_404_not_500(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """
    Regression: DELETE /admin/user-groups/{hash}/project-groups/{pg_hash} with missing
    project group must return 404 (not 500 from AttributeError on ErrorCode.NOT_FOUND).
    """
    ug = _make_user_group()
    token = "regression-revoke-404-token"
    admin_session = _make_admin_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    with patch("src.routes.admin_user_groups.validate_session", return_value=admin_session), \
         patch("src.routes.admin_user_groups.get_user_group_by_hash", return_value=ug), \
         patch("src.routes.admin_user_groups.get_project_permission_group_by_hash", return_value=None):
        response = await client.request(
            "DELETE",
            "/admin/user-groups/grp-reg-001/project-groups/nonexistent-pg-hash",
            headers={"Authorization": f"Bearer {token}"},
        )

    # Must be 404, NOT 500
    assert response.status_code == 404, (
        f"Expected 404 but got {response.status_code}. "
        "If 500, the ErrorCode.NOT_FOUND bug is NOT fixed."
    )
    data = response.json()
    assert data["status"] == "error"
