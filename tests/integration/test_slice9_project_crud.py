"""
Slice 9 — Project CRUD

Tests: GET /projects, POST /projects, GET /projects/{hash}, PUT /projects/{hash},
DELETE /projects/{hash}. Also verifies stub endpoints return 501.
Uses the REAL app with all middleware active.
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
               username="adminuser"):
    u = MagicMock()
    u.id = user_id
    u.user_hash = user_hash
    u.username = username
    u.email = "admin@example.com"
    u.user_type = user_type
    u.is_active = True
    u.assigned_project_id = "1"
    return u


def _make_project(project_id="1", project_hash="prj-test-001",
                  project_name="Test Project"):
    p = MagicMock()
    p.id = project_id
    p.project_hash = project_hash
    p.project_name = project_name
    p.project_description = "A test project"
    p.owner_id = "1"
    p.is_active = True
    return p


@pytest.mark.asyncio
async def test_admin_list_projects_returns_200(client, fake_redis, patched_db_connection,
                                                patched_db_error_logger, patched_audit_logger,
                                                patched_audit_ids, patched_cache_manager,
                                                patched_activity_logger):
    """Admin can GET /projects and sees all projects."""
    token = "test-admin-projects-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    admin_user = _make_user()
    project = _make_project()

    with patch("src.Util.db.validate_session", return_value=session), \
         patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.routes.projects.validate_session", return_value=session), \
         patch("src.routes.projects.get_user_by_hash", return_value=admin_user), \
         patch("src.routes.projects.list_all_projects", return_value=[project]), \
         patch("src.routes.projects.get_user_groups_for_user", return_value=[]), \
         patch("src.routes.projects.get_permission_groups_for_project", return_value=[]), \
         patch("src.routes.projects.get_project_stats", return_value={}):
        response = await client.get(
            "/projects",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert "projects" in data or "data" in data


@pytest.mark.asyncio
async def test_admin_create_project_returns_200(client, fake_redis, patched_db_connection,
                                                 patched_db_error_logger, patched_audit_logger,
                                                 patched_audit_ids, patched_cache_manager,
                                                 patched_activity_logger):
    """Admin can POST /projects to create a new project."""
    token = "test-admin-create-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    admin_user = _make_user()
    new_project = _make_project(project_hash="prj-new-001", project_name="New Project")

    with patch("src.Util.db.validate_session", return_value=session), \
         patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.routes.projects.validate_session", return_value=session), \
         patch("src.routes.projects.get_user_by_hash", return_value=admin_user), \
         patch("src.routes.projects.create_project", return_value=new_project):
        response = await client.post(
            "/projects",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
            data={"project_name": "New Project", "project_description": "A new project"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


@pytest.mark.asyncio
async def test_get_project_details_returns_200(client, fake_redis, patched_db_connection,
                                                patched_db_error_logger, patched_audit_logger,
                                                patched_audit_ids, patched_cache_manager,
                                                patched_activity_logger):
    """GET /projects/{hash} returns project details."""
    token = "test-project-details-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    admin_user = _make_user()
    project = _make_project()

    with patch("src.Util.db.validate_session", return_value=session), \
         patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.routes.projects.validate_session", return_value=session), \
         patch("src.routes.projects.get_user_by_hash", return_value=admin_user), \
         patch("src.routes.projects.get_project_by_hash", return_value=project), \
         patch("src.routes.projects.get_project_stats", return_value={}), \
         patch("src.routes.projects.get_user_groups_for_user", return_value=[]), \
         patch("src.routes.projects.get_permission_groups_for_project", return_value=[]):
        response = await client.get(
            "/projects/prj-test-001",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert "project" in data


@pytest.mark.asyncio
async def test_admin_update_project_returns_200(client, fake_redis, patched_db_connection,
                                                 patched_db_error_logger, patched_audit_logger,
                                                 patched_audit_ids, patched_cache_manager,
                                                 patched_activity_logger):
    """Admin can PUT /projects/{hash} to update."""
    token = "test-admin-update-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    admin_user = _make_user()
    project = _make_project()

    updated_project = MagicMock()
    updated_project.project_hash = "prj-test-001"
    updated_project.project_name = "Updated Project"
    updated_project.project_description = "Updated description"
    updated_project.id = "1"
    updated_project.owner_id = "1"
    updated_project.is_active = True

    with patch("src.Util.db.validate_session", return_value=session), \
         patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.routes.projects.validate_session", return_value=session), \
         patch("src.routes.projects.get_user_by_hash", return_value=admin_user), \
         patch("src.routes.projects.get_project_by_hash", return_value=project), \
         patch("src.routes.projects.update_project", return_value=updated_project):
        response = await client.put(
            "/projects/prj-test-001",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
            data={"project_name": "Updated Project"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


@pytest.mark.asyncio
async def test_admin_delete_project_returns_200(client, fake_redis, patched_db_connection,
                                                 patched_db_error_logger, patched_audit_logger,
                                                 patched_audit_ids, patched_cache_manager,
                                                 patched_activity_logger):
    """Admin can DELETE /projects/{hash}."""
    token = "test-admin-delete-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    admin_user = _make_user()
    project = _make_project()

    with patch("src.Util.db.validate_session", return_value=session), \
         patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.routes.projects.validate_session", return_value=session), \
         patch("src.routes.projects.get_user_by_hash", return_value=admin_user), \
         patch("src.routes.projects.get_project_by_hash", return_value=project), \
         patch("src.routes.projects.delete_project", return_value={"success": True}):
        response = await client.delete(
            "/projects/prj-test-001",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


@pytest.mark.asyncio
async def test_project_not_found_returns_404(client, fake_redis, patched_db_connection,
                                              patched_db_error_logger, patched_audit_logger,
                                              patched_audit_ids, patched_cache_manager,
                                              patched_activity_logger):
    """GET /projects/{hash} with non-existent hash returns 404."""
    token = "test-project-404-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    admin_user = _make_user()

    with patch("src.Util.db.validate_session", return_value=session), \
         patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.routes.projects.validate_session", return_value=session), \
         patch("src.routes.projects.get_user_by_hash", return_value=admin_user), \
         patch("src.routes.projects.get_project_by_hash", return_value=None):
        response = await client.get(
            "/projects/prj-nonexistent",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_stub_owner_endpoint_returns_501(client, fake_redis, patched_db_connection,
                                                patched_db_error_logger, patched_audit_logger,
                                                patched_audit_ids, patched_cache_manager,
                                                patched_activity_logger):
    """PATCH /projects/{hash}/owner returns 501 Not Implemented."""
    token = "test-admin-owner-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    admin_user = _make_user()
    project = _make_project()
    new_owner = _make_user(user_id="2", user_hash="usr-new-owner")

    def mock_get_user(h, **kw):
        if h == "usr-admin-001":
            return admin_user
        return new_owner

    with patch("src.Util.db.validate_session", return_value=session), \
         patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.routes.projects.validate_session", return_value=session), \
         patch("src.routes.projects.get_user_by_hash", side_effect=mock_get_user), \
         patch("src.routes.projects.get_project_by_hash", return_value=project):
        response = await client.patch(
            "/projects/prj-test-001/owner",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
            data={"new_owner_hash": "usr-new-owner"},
        )

    assert response.status_code == 501
    data = response.json()
    assert data["error"]["code"] == "INT_7006"


@pytest.mark.asyncio
async def test_stub_archive_endpoint_returns_501(client, fake_redis, patched_db_connection,
                                                  patched_db_error_logger, patched_audit_logger,
                                                  patched_audit_ids, patched_cache_manager,
                                                  patched_activity_logger):
    """PATCH /projects/{hash}/archive returns 501 Not Implemented."""
    token = "test-admin-archive-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    admin_user = _make_user()
    project = _make_project()

    with patch("src.Util.db.validate_session", return_value=session), \
         patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.routes.projects.validate_session", return_value=session), \
         patch("src.routes.projects.get_user_by_hash", return_value=admin_user), \
         patch("src.routes.projects.get_project_by_hash", return_value=project):
        response = await client.patch(
            "/projects/prj-test-001/archive",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
            data={"archived": "true"},
        )

    assert response.status_code == 501
    data = response.json()
    assert data["error"]["code"] == "INT_7006"


@pytest.mark.asyncio
async def test_get_project_activity_pagination_is_honest(client, fake_redis, patched_db_connection,
                                                          patched_db_error_logger, patched_audit_logger,
                                                          patched_audit_ids, patched_cache_manager,
                                                          patched_activity_logger):
    """GET /projects/{hash}/activity returns correct pagination.total and has_more."""
    token = "test-activity-pagination-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    admin_user = _make_user()
    project = _make_project()

    # Simulate 5 activities returned on this page, but 23 total exist
    mock_activities = [{"id": str(i), "activity_type": "login", "details": {}} for i in range(5)]

    with patch("src.Util.db.validate_session", return_value=session), \
         patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.routes.projects.validate_session", return_value=session), \
         patch("src.routes.projects.get_user_by_hash", return_value=admin_user), \
         patch("src.routes.projects.get_project_by_hash", return_value=project), \
         patch("src.routes.projects.get_recent_activity", return_value=mock_activities), \
         patch("src.routes.projects.count_activity_logs", return_value=23):
        response = await client.get(
            "/projects/prj-test-001/activity?limit=5&offset=0",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["pagination"]["total"] == 23
    assert data["pagination"]["has_more"] is True
    assert data["pagination"]["limit"] == 5
    assert data["pagination"]["offset"] == 0


@pytest.mark.asyncio
async def test_get_project_activity_pagination_no_more_pages(client, fake_redis, patched_db_connection,
                                                              patched_db_error_logger, patched_audit_logger,
                                                              patched_audit_ids, patched_cache_manager,
                                                              patched_activity_logger):
    """GET /projects/{hash}/activity has_more=false when on last page."""
    token = "test-activity-last-page-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    admin_user = _make_user()
    project = _make_project()

    # 3 activities on page, total is also 3 — no more pages
    mock_activities = [{"id": str(i), "activity_type": "login", "details": {}} for i in range(3)]

    with patch("src.Util.db.validate_session", return_value=session), \
         patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.routes.projects.validate_session", return_value=session), \
         patch("src.routes.projects.get_user_by_hash", return_value=admin_user), \
         patch("src.routes.projects.get_project_by_hash", return_value=project), \
         patch("src.routes.projects.get_recent_activity", return_value=mock_activities), \
         patch("src.routes.projects.count_activity_logs", return_value=3):
        response = await client.get(
            "/projects/prj-test-001/activity?limit=10&offset=0",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["pagination"]["total"] == 3
    assert data["pagination"]["has_more"] is False
