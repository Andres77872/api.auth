"""High-fidelity auth refresh lifecycle contract test.

This is intentionally RED before the true refresh-family implementation exists.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.Util.JWT_Security import JWTTokenHandler


def _make_user():
    user = MagicMock()
    user.id = "1"
    user.user_hash = "usr-e2e-001"
    user.username = "e2euser"
    user.email = "e2e@example.com"
    user.user_type = "consumer"
    user.is_active = True
    user.assigned_project_id = None
    return user


def _make_project(project_hash="prj-e2e-001", project_name="E2E Project"):
    project = MagicMock()
    project.id = "1"
    project.project_hash = project_hash
    project.project_name = project_name
    project.project_description = "E2E project"
    return project


def _make_group():
    group = MagicMock()
    group.id = "1"
    group.group_hash = "grp-e2e-001"
    group.group_name = "E2E Consumers"
    group.group_description = "E2E group"
    return group


@pytest.mark.asyncio
async def test_login_refresh_retry_old_access_and_reuse_revocation_lifecycle(
    client, fake_redis, patched_db_connection, patched_audit_logger,
    patched_audit_ids, patched_db_error_logger, patched_activity_logger,
):
    user = _make_user()
    project = _make_project()
    group = _make_group()

    with patch("src.routes.auth.get_user_by_credentials", return_value=user), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
         patch("src.routes.auth.resolve_target_project", return_value=project), \
         patch("src.routes.auth.get_user_groups_for_user", return_value=[group]), \
         patch("src.routes.auth.get_user_by_hash", return_value=user), \
         patch("src.routes.auth.get_project_by_hash", return_value=project), \
         patch("src.Util.db.db_enhanced.get_user_by_hash", return_value=user), \
         patch("src.Util.db.db_enhanced.get_project_by_hash", return_value=project), \
         patch("src.Util.db.db_enhanced.get_user_groups_in_project_by_hash", return_value=[group]), \
         patch("src.Util.db.db_enhanced.get_user_accessible_projects", return_value=[project]):
        login_response = await client.post(
            "/auth/login",
            data={"username": "e2euser", "password": "secret", "project_hash": "prj-e2e-001"},
            headers={"User-Agent": "test"},
        )
        assert login_response.status_code == 200
        login_data = login_response.json()
        access_token = login_data["access_token"]
        refresh_token = login_data["refresh_token"]
        access_claims = JWTTokenHandler.decode_access_token(access_token)

        initial_access_validate = await client.get(
            "/auth/validate",
            headers={"Authorization": f"Bearer {access_token}", "User-Agent": "test"},
        )
        assert initial_access_validate.status_code == 200

        fake_redis.delete(
            f"session:{access_claims['jti']}",
            f"session_full:{access_claims['jti']}",
        )

        old_access_validate = await client.get(
            "/auth/validate",
            headers={"Authorization": f"Bearer {access_token}", "User-Agent": "test"},
        )
        assert old_access_validate.status_code == 401

        first_refresh = await client.post(
            "/auth/refresh",
            data={"refresh_token": refresh_token},
            cookies={"refresh_token": refresh_token},
            headers={"User-Agent": "test"},
        )
        assert first_refresh.status_code == 200
        refreshed_data = first_refresh.json()
        assert refreshed_data["access_token"] != access_token
        assert refreshed_data["refresh_token"] != refresh_token

        new_access_validate = await client.get(
            "/auth/validate",
            headers={"Authorization": f"Bearer {refreshed_data['access_token']}", "User-Agent": "test"},
        )
        assert new_access_validate.status_code == 200

        reuse_response = await client.post(
            "/auth/refresh",
            data={"refresh_token": refresh_token},
            cookies={"refresh_token": refresh_token},
            headers={"User-Agent": "test"},
        )
        assert reuse_response.status_code == 401

        latest_child_after_reuse = await client.post(
            "/auth/refresh",
            data={"refresh_token": refreshed_data["refresh_token"]},
            cookies={"refresh_token": refreshed_data["refresh_token"]},
            headers={"User-Agent": "test"},
        )
        assert latest_child_after_reuse.status_code == 401
