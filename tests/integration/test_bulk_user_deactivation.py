"""RED contract tests for bulk user deactivation auth revocation."""

from unittest.mock import MagicMock, patch

import pytest


def _admin_session():
    session = MagicMock()
    session.user_id = "1"
    session.user_hash = "usr-admin-001"
    session.user_type = "admin"
    session.project_id = "1"
    session.project_hash = "prj-test-001"
    session.permissions = ["admin", "manage_users"]
    session.groups = ["project_admins"]
    session.session_token = "bulk-admin-token"
    return session


def _admin_user():
    user = MagicMock()
    user.id = "1"
    user.user_hash = "usr-admin-001"
    user.username = "adminuser"
    user.user_type = "admin"
    return user


@pytest.mark.asyncio
async def test_bulk_deactivation_uses_correct_helper_shape_and_revokes_auth_state(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Bulk is_active=False must call the fixed helper shape and revoke families."""
    session = _admin_session()
    admin = _admin_user()
    result = {
        "success_count": 2,
        "error_count": 0,
        "skipped_count": 0,
        "results": [
            {"user_hash": "usr-target-001", "success": True, "user_id": "2"},
            {"user_hash": "usr-target-002", "success": True, "user_id": "3"},
        ],
        "errors": [],
    }

    with patch("src.routes.bulk_operations.validate_session", return_value=session), \
         patch("src.routes.bulk_operations.get_user_by_hash", return_value=admin), \
         patch("src.routes.bulk_operations.bulk_update_users", return_value=result) as bulk_update, \
         patch("src.routes.bulk_operations.revoke_user_auth_state", create=True) as revoke_auth_state, \
         patch("src.routes.bulk_operations.ActivityLogger.log_bulk_user_update", return_value=None):
        response = await client.post(
            "/admin/users/bulk-update",
            data={"user_hashes": ["usr-target-001", "usr-target-002"], "is_active": "false"},
            headers={"Authorization": "Bearer bulk-admin-token", "User-Agent": "test"},
        )

    assert response.status_code == 200
    bulk_update.assert_called_once_with(
        [
            {"user_hash": "usr-target-001", "updates": {"is_active": False}},
            {"user_hash": "usr-target-002", "updates": {"is_active": False}},
        ],
        updated_by="1",
    )
    revoke_auth_state.assert_any_call("2", reason="bulk_user_deactivated")
    revoke_auth_state.assert_any_call("3", reason="bulk_user_deactivated")


@pytest.mark.asyncio
async def test_bulk_deactivated_credentials_fail_closed_after_revocation(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Old access/refresh credentials for bulk-deactivated users must not remain usable."""
    from src.Util.auth_lifecycle import issue_project_token_pair, revoke_user_auth_state

    with patch("src.Util.auth_lifecycle.redis_client", fake_redis):
        pair = issue_project_token_pair(
            user={"id": "2", "user_hash": "usr-target-001", "username": "target", "user_type": "consumer"},
            project={"id": "1", "project_hash": "prj-test-001", "project_name": "Test Project"},
            groups=["Consumers"],
            permissions=[],
        )
        revoke_user_auth_state("2", reason="bulk_user_deactivated")

    validate_response = await client.get(
        "/auth/validate",
        headers={"Authorization": f"Bearer {pair.access_token}", "User-Agent": "test"},
    )
    refresh_response = await client.post(
        "/auth/refresh",
        data={"refresh_token": pair.refresh_token},
        cookies={"refresh_token": pair.refresh_token},
        headers={"User-Agent": "test"},
    )

    assert validate_response.status_code == 401
    assert refresh_response.status_code == 401
