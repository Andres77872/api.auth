"""Slice 18 — Platform login and admin dashboard access."""

from unittest.mock import patch, MagicMock

import pytest


def _make_session(user_id="2", user_hash="usr-admin-001", user_type="admin"):
    session = MagicMock()
    session.user_id = user_id
    session.user_hash = user_hash
    session.user_type = user_type
    session.project_hash = None
    session.project_name = None
    session.project_id = None
    session.permissions = ["admin", "manage_users", "manage_roles"]
    session.groups = ["platform_admins"]
    session.session_token = "platform-token"
    session.session_length = 259200
    session.scope = "platform"
    return session


@pytest.mark.asyncio
async def test_admin_dashboard_stats_accepts_platform_session(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Admin dashboard endpoint can be reached with a platform-scoped admin session."""
    session = _make_session()

    with patch("src.Util.decorators.validate_session", return_value=session), \
         patch("src.Util.decorators.get_user_by_hash", return_value=MagicMock(username="adminuser")), \
         patch("src.routes.admin_dashboard.get_user_type", return_value="admin"), \
         patch("src.routes.admin_dashboard.is_root_user", return_value=False), \
         patch("src.routes.admin_dashboard.count_users", return_value=10), \
         patch("src.routes.admin_dashboard.count_projects", return_value=3), \
         patch("src.routes.admin_dashboard.count_active_sessions", return_value=7), \
         patch("src.routes.admin_dashboard.count_user_groups", return_value=4), \
         patch("src.routes.admin_dashboard.count_project_groups", return_value=2), \
         patch("src.routes.admin_dashboard.get_recent_users_count", return_value=1), \
         patch("src.routes.admin_dashboard.get_recent_projects_count", return_value=1), \
         patch("src.routes.admin_dashboard.get_recent_activity_count", return_value=5), \
         patch("src.routes.admin_dashboard.check_database_health", return_value={"status": "healthy"}), \
         patch("src.routes.admin_dashboard.check_redis_health", return_value={"status": "healthy"}):
        response = await client.get(
            "/admin/dashboard/stats",
            headers={"Authorization": "Bearer platform-token", "User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["totals"]["users"] == 10
