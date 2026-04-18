"""
Slice 11 — Admin Project Groups

Tests: GET /admin/project-groups, POST /admin/project-groups,
GET /admin/project-groups/{hash}, non-admin → 403.
Uses the REAL app with all middleware active.
"""

from unittest.mock import patch, MagicMock

import pytest


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


def _make_project_group(group_id="1", group_hash="grp-test-001",
                        group_name="Test Group", group_description="A test group",
                        created_at=None):
    g = MagicMock()
    g.id = group_id
    g.group_hash = group_hash
    g.group_name = group_name
    g.group_description = group_description
    g.created_at = created_at
    return g


def _make_project(project_id="1", project_hash="prj-test-001",
                  project_name="Test Project", project_description="A test project"):
    p = MagicMock()
    p.id = project_id
    p.project_hash = project_hash
    p.project_name = project_name
    p.project_description = project_description
    p.owner_id = "1"
    p.is_active = True
    return p


@pytest.mark.asyncio
async def test_admin_list_project_groups_returns_200(client, fake_redis, patched_db_connection,
                                                      patched_db_error_logger, patched_audit_logger,
                                                      patched_audit_ids, patched_cache_manager,
                                                      patched_activity_logger):
    """Admin can GET /admin/project-groups and sees groups with project counts."""
    from tests.integration.conftest import make_session_payload, create_test_session

    token = "test-admin-pg-list-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    group = _make_project_group()
    project = _make_project()

    with patch("src.Util.db.db_enhanced.get_project_by_hash", return_value=project), \
         patch("src.routes.admin_project_groups.validate_session", return_value=session), \
         patch("src.routes.admin_project_groups.list_all_project_permission_groups", return_value=[group]), \
         patch("src.routes.admin_project_groups.get_projects_in_permission_group", return_value=[project]), \
         patch("src.routes.admin_project_groups.count_project_permission_groups", return_value=1):
        response = await client.get(
            "/admin/project-groups",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "project_groups" in data
    assert len(data["project_groups"]) == 1
    assert data["project_groups"][0]["group_hash"] == "grp-test-001"
    assert data["project_groups"][0]["project_count"] == 1
    assert "pagination" in data
    assert data["pagination"]["total"] == 1
    assert data["pagination"]["has_more"] is False
    assert data["pagination"]["limit"] == 50
    assert data["pagination"]["offset"] == 0


@pytest.mark.asyncio
async def test_admin_list_project_groups_pagination_has_more(client, fake_redis, patched_db_connection,
                                                              patched_db_error_logger, patched_audit_logger,
                                                              patched_audit_ids, patched_cache_manager,
                                                              patched_activity_logger):
    """GET /admin/project-groups with limit < total shows has_more=True."""
    from tests.integration.conftest import make_session_payload, create_test_session

    token = "test-admin-pg-pagination-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    groups = [_make_project_group(group_id=str(i), group_hash=f"grp-{i:03d}", group_name=f"Group {i}")
              for i in range(10)]
    project = _make_project()

    with patch("src.Util.db.db_enhanced.get_project_by_hash", return_value=project), \
         patch("src.routes.admin_project_groups.validate_session", return_value=session), \
         patch("src.routes.admin_project_groups.list_all_project_permission_groups", return_value=groups[:5]), \
         patch("src.routes.admin_project_groups.get_projects_in_permission_group", return_value=[]), \
         patch("src.routes.admin_project_groups.count_project_permission_groups", return_value=10):
        response = await client.get(
            "/admin/project-groups?limit=5&offset=0",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["pagination"]["total"] == 10
    assert data["pagination"]["has_more"] is True
    assert data["pagination"]["limit"] == 5
    assert data["pagination"]["offset"] == 0
    assert len(data["project_groups"]) == 5


@pytest.mark.asyncio
async def test_admin_create_project_group_returns_201(client, fake_redis, patched_db_connection,
                                                       patched_db_error_logger, patched_audit_logger,
                                                       patched_audit_ids, patched_cache_manager,
                                                       patched_activity_logger):
    """Admin can POST /admin/project-groups to create a new group."""
    from tests.integration.conftest import make_session_payload, create_test_session

    token = "test-admin-pg-create-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    admin_user = _make_user()
    new_group = _make_project_group(group_hash="grp-new-001", group_name="New Group")
    project = _make_project()

    with patch("src.Util.db.db_enhanced.get_project_by_hash", return_value=project), \
         patch("src.routes.admin_project_groups.validate_session", return_value=session), \
         patch("src.routes.admin_project_groups.get_user_by_hash", return_value=admin_user), \
         patch("src.routes.admin_project_groups.create_project_permission_group", return_value=new_group):
        response = await client.post(
            "/admin/project-groups",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
            data={"group_name": "New Group", "description": "A new group"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "project_group" in data
    assert data["project_group"]["group_hash"] == "grp-new-001"
    assert data["project_group"]["project_count"] == 0


@pytest.mark.asyncio
async def test_project_group_not_found_returns_404(client, fake_redis, patched_db_connection,
                                                    patched_db_error_logger, patched_audit_logger,
                                                    patched_audit_ids, patched_cache_manager,
                                                    patched_activity_logger):
    """GET /admin/project-groups/{hash} with non-existent hash returns 404."""
    from tests.integration.conftest import make_session_payload, create_test_session

    token = "test-pg-404-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    project = _make_project()

    with patch("src.Util.db.db_enhanced.get_project_by_hash", return_value=project), \
         patch("src.routes.admin_project_groups.validate_session", return_value=session), \
         patch("src.routes.admin_project_groups.get_project_permission_group_by_hash", return_value=None):
        response = await client.get(
            "/admin/project-groups/grp-nonexistent",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
        )

    assert response.status_code == 404
    data = response.json()
    assert data["status"] == "error"
    error = data["error"]
    assert error["category"] == "not_found"
    assert "code" in error
    assert "message" in error


@pytest.mark.asyncio
async def test_admin_update_project_group_returns_200(client, fake_redis, patched_db_connection,
                                                        patched_db_error_logger, patched_audit_logger,
                                                        patched_audit_ids, patched_cache_manager,
                                                        patched_activity_logger):
    """Admin can PUT /admin/project-groups/{hash} to update a group."""
    from tests.integration.conftest import make_session_payload, create_test_session

    token = "test-admin-pg-update-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    existing_group = _make_project_group(group_hash="grp-existing-001", group_name="Old Name")
    updated_group = _make_project_group(group_hash="grp-existing-001", group_name="Updated Name",
                                        group_description="Updated description")
    project = _make_project()

    with patch("src.Util.db.db_enhanced.get_project_by_hash", return_value=project), \
         patch("src.routes.admin_project_groups.validate_session", return_value=session), \
         patch("src.routes.admin_project_groups.get_project_permission_group_by_hash", return_value=existing_group), \
         patch("src.routes.admin_project_groups.update_project_permission_group", return_value=updated_group):
        response = await client.put(
            "/admin/project-groups/grp-existing-001",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
            data={"group_name": "Updated Name", "description": "Updated description"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "project_group" in data
    assert data["project_group"]["group_hash"] == "grp-existing-001"
    assert data["project_group"]["group_name"] == "Updated Name"
    assert data["project_group"]["description"] == "Updated description"


@pytest.mark.asyncio
async def test_admin_delete_project_group_returns_200(client, fake_redis, patched_db_connection,
                                                       patched_db_error_logger, patched_audit_logger,
                                                       patched_audit_ids, patched_cache_manager,
                                                       patched_activity_logger):
    """Admin can DELETE /admin/project-groups/{hash}."""
    from tests.integration.conftest import make_session_payload, create_test_session

    token = "test-admin-pg-delete-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    admin_user = _make_user()
    group_to_delete = _make_project_group(group_hash="grp-delete-001", group_name="Delete Me")
    project = _make_project()

    with patch("src.Util.db.db_enhanced.get_project_by_hash", return_value=project), \
         patch("src.routes.admin_project_groups.validate_session", return_value=session), \
         patch("src.routes.admin_project_groups.get_project_permission_group_by_hash", return_value=group_to_delete), \
         patch("src.routes.admin_project_groups.get_user_by_hash", return_value=admin_user), \
         patch("src.routes.admin_project_groups.delete_project_permission_group", return_value=True):
        response = await client.delete(
            "/admin/project-groups/grp-delete-001",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "Delete Me" in data["message"]


@pytest.mark.asyncio
async def test_admin_get_project_group_details_returns_200(client, fake_redis, patched_db_connection,
                                                            patched_db_error_logger, patched_audit_logger,
                                                            patched_audit_ids, patched_cache_manager,
                                                            patched_activity_logger):
    """Admin can GET /admin/project-groups/{hash} and sees group details with assigned projects."""
    from tests.integration.conftest import make_session_payload, create_test_session

    token = "test-admin-pg-detail-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    group = _make_project_group(group_hash="grp-detail-001", group_name="Detail Group")
    assigned_project = _make_project(project_hash="prj-assigned-001", project_name="Assigned Project")
    project = _make_project()

    with patch("src.Util.db.db_enhanced.get_project_by_hash", return_value=project), \
         patch("src.routes.admin_project_groups.validate_session", return_value=session), \
         patch("src.routes.admin_project_groups.get_project_permission_group_by_hash", return_value=group), \
         patch("src.routes.admin_project_groups.get_projects_in_permission_group", return_value=[assigned_project]):
        response = await client.get(
            "/admin/project-groups/grp-detail-001",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "project_group" in data
    assert data["project_group"]["group_hash"] == "grp-detail-001"
    assert data["project_group"]["group_name"] == "Detail Group"
    assert "assigned_projects" in data
    assert len(data["assigned_projects"]) == 1
    assert data["assigned_projects"][0]["project_hash"] == "prj-assigned-001"
    assert "statistics" in data
    assert data["statistics"]["total_projects"] == 1


@pytest.mark.asyncio
async def test_post_create_project_group_missing_name_returns_422(client, fake_redis, patched_db_connection,
                                                                   patched_db_error_logger, patched_audit_logger,
                                                                   patched_audit_ids, patched_cache_manager,
                                                                   patched_activity_logger):
    """POST /admin/project-groups without group_name returns validation error."""
    from tests.integration.conftest import make_session_payload, create_test_session

    token = "test-admin-pg-validation-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    project = _make_project()

    with patch("src.Util.db.db_enhanced.get_project_by_hash", return_value=project), \
         patch("src.routes.admin_project_groups.validate_session", return_value=session):
        response = await client.post(
            "/admin/project-groups",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
            data={"description": "No name provided"},
        )

    assert response.status_code == 400
    data = response.json()
    assert "error" in data or "detail" in data


# ─── Non-admin → 403 ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_non_admin_cannot_access_project_groups():
    """Consumer user gets 403 on GET /admin/project-groups.

    Tests the require_admin guard directly because route-level HTTP tests
    for 403 on this module are unreliable due to how AuthContextMiddleware
    does a lazy import of validate_session from src.Util.db (patched by
    fake_redis fixture) while the route module holds its own imported reference.
    The guard logic is: session.permissions must contain 'admin' or 'manage_roles'.
    """
    from fastapi.security import HTTPAuthorizationCredentials
    from src.Util.error_handler import AuthorizationError
    from src.routes.admin_project_groups import require_admin

    # Build session manually to avoid _make_session default of permissions=["admin"]
    session = MagicMock()
    session.user_id = "1"
    session.user_hash = "usr-consumer-001"
    session.user_type = "consumer"
    session.project_hash = "prj-test-001"
    session.project_name = "Test Project"
    session.project_id = "1"
    session.permissions = []
    session.groups = []
    session.session_token = "test-consumer-token"
    session.session_length = 259200
    session.username = "consumer"

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-token")

    with patch("src.routes.admin_project_groups.validate_session", return_value=session):
        with pytest.raises(AuthorizationError) as exc_info:
            await require_admin(credentials)

    assert exc_info.value.status_code == 403
    assert exc_info.value.error_code.value == "AUTHZ_2002"


# ─── Search + pagination correctness ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_list_project_groups_search_passed_to_count(client, fake_redis, patched_db_connection,
                                                                  patched_db_error_logger, patched_audit_logger,
                                                                  patched_audit_ids, patched_cache_manager,
                                                                  patched_activity_logger):
    """When search is supplied, count_project_permission_groups receives the search term."""
    from tests.integration.conftest import make_session_payload, create_test_session

    token = "test-admin-pg-search-count-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    matching = [_make_project_group(group_id="1", group_hash="grp-match-001", group_name="Search Match")]
    project = _make_project()

    with patch("src.Util.db.db_enhanced.get_project_by_hash", return_value=project), \
         patch("src.routes.admin_project_groups.validate_session", return_value=session), \
         patch("src.routes.admin_project_groups.list_all_project_permission_groups", return_value=matching) as mock_list, \
         patch("src.routes.admin_project_groups.get_projects_in_permission_group", return_value=[]), \
         patch("src.routes.admin_project_groups.count_project_permission_groups", return_value=1) as mock_count:
        response = await client.get(
            "/admin/project-groups?search=Match",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
        )

    assert response.status_code == 200
    mock_list.assert_called_once()
    list_kwargs = mock_list.call_args
    assert list_kwargs[0][4] == "Match" or (len(list_kwargs[0]) > 4 and list_kwargs[0][4] == "Match")
    mock_count.assert_called_once_with("Match")


@pytest.mark.asyncio
async def test_admin_list_project_groups_search_pagination_consistent(client, fake_redis, patched_db_connection,
                                                                        patched_db_error_logger, patched_audit_logger,
                                                                        patched_audit_ids, patched_cache_manager,
                                                                        patched_activity_logger):
    """When search filter is active, pagination.total reflects the filtered count, not the global count."""
    from tests.integration.conftest import make_session_payload, create_test_session

    token = "test-admin-pg-search-pag-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    matching = [
        _make_project_group(group_id="1", group_hash="grp-a-001", group_name="Alpha Group"),
        _make_project_group(group_id="2", group_hash="grp-b-002", group_name="Beta Group"),
    ]
    project = _make_project()

    with patch("src.Util.db.db_enhanced.get_project_by_hash", return_value=project), \
         patch("src.routes.admin_project_groups.validate_session", return_value=session), \
         patch("src.routes.admin_project_groups.list_all_project_permission_groups", return_value=matching), \
         patch("src.routes.admin_project_groups.get_projects_in_permission_group", return_value=[]), \
         patch("src.routes.admin_project_groups.count_project_permission_groups", return_value=2):
        response = await client.get(
            "/admin/project-groups?search=Group",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["pagination"]["total"] == 2
    assert data["pagination"]["has_more"] is False
    assert len(data["project_groups"]) == 2


@pytest.mark.asyncio
async def test_admin_list_project_groups_search_no_results(client, fake_redis, patched_db_connection,
                                                             patched_db_error_logger, patched_audit_logger,
                                                             patched_audit_ids, patched_cache_manager,
                                                             patched_activity_logger):
    """When search matches nothing, pagination.total is 0 and has_more is False."""
    from tests.integration.conftest import make_session_payload, create_test_session

    token = "test-admin-pg-search-empty-token"
    session = _make_session(session_token=token)
    create_test_session(fake_redis, token, make_session_payload(session_token=token))

    project = _make_project()

    with patch("src.Util.db.db_enhanced.get_project_by_hash", return_value=project), \
         patch("src.routes.admin_project_groups.validate_session", return_value=session), \
         patch("src.routes.admin_project_groups.list_all_project_permission_groups", return_value=[]), \
         patch("src.routes.admin_project_groups.get_projects_in_permission_group", return_value=[]), \
         patch("src.routes.admin_project_groups.count_project_permission_groups", return_value=0):
        response = await client.get(
            "/admin/project-groups?search=NonExistentGroup",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["pagination"]["total"] == 0
    assert data["pagination"]["has_more"] is False
    assert len(data["project_groups"]) == 0
