"""
Slice 18 (Strategy Slice 3) — Project Creation → Default Groups Orchestration

Characterization test: Verify `POST /projects` calls DB functions in the correct
sequence: validate_session → get_user_by_hash → create_project → create_default_groups.

The `create_project` function internally calls `create_default_groups` which executes
4 raw SQL INSERTs (project_group, project_group_members, 3 user_groups, 3
user_group_project_groups links).

Proof layer: Layer 2 (integration, mocked DB)
Trace: explore.md RISK 2, Gap 4
"""

from unittest.mock import patch, MagicMock, call

import pytest

from tests.support import make_db_connection_mock


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


def _make_project(project_id="proj-new-001", project_hash="prj-new-001",
                  project_name="New Project"):
    p = MagicMock()
    p.id = project_id
    p.project_hash = project_hash
    p.project_name = project_name
    p.project_description = "A new project"
    p.project_created = "2026-04-17T12:00:00"
    p.is_active = True
    return p


@pytest.mark.asyncio
async def test_project_creation_calls_validate_session_first(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Project creation must validate the session before anything else."""
    admin_session = _make_admin_session()
    project = _make_project()

    call_sequence = []

    def track_validate(token):
        call_sequence.append("validate_session")
        return admin_session

    def track_user_lookup(hash_val):
        call_sequence.append("get_user_by_hash")
        return MagicMock(id="admin-1", username="adminuser", user_hash="usr-admin-001")

    def track_create_project(name, desc, created_by, owner_id):
        call_sequence.append("create_project")
        return project

    with patch("src.routes.projects.validate_session", side_effect=track_validate), \
         patch("src.routes.projects.get_user_by_hash", side_effect=track_user_lookup), \
         patch("src.routes.projects.create_project", side_effect=track_create_project):
        response = await client.post(
            "/projects",
            data={
                "project_name": "New Project",
                "project_description": "A new project",
            },
            headers={"Authorization": f"Bearer {admin_session.session_token}"},
        )

    assert response.status_code == 200
    # Session must be validated first
    assert call_sequence[0] == "validate_session"
    # Then user lookup, then project creation
    assert call_sequence == ["validate_session", "get_user_by_hash", "create_project"]


@pytest.mark.asyncio
async def test_project_creation_passes_user_id_to_create_project(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Project creation must pass the authenticated user's ID as created_by and owner_id."""
    admin_session = _make_admin_session(user_id="specific-admin-id")
    project = _make_project()

    captured_args = None

    def track_create(name, desc, created_by, owner_id):
        nonlocal captured_args
        captured_args = (name, desc, created_by, owner_id)
        return project

    with patch("src.routes.projects.validate_session", return_value=admin_session), \
         patch("src.routes.projects.get_user_by_hash", return_value=MagicMock(id="specific-admin-id", username="adminuser", user_hash="usr-admin-001")), \
         patch("src.routes.projects.create_project", side_effect=track_create):
        response = await client.post(
            "/projects",
            data={
                "project_name": "Test Project",
                "project_description": "Test description",
            },
            headers={"Authorization": f"Bearer {admin_session.session_token}"},
        )

    assert response.status_code == 200
    assert captured_args is not None
    assert captured_args[0] == "Test Project"          # project_name
    assert captured_args[1] == "Test description"      # project_description
    assert captured_args[2] == "specific-admin-id"     # created_by
    assert captured_args[3] == "specific-admin-id"     # owner_id


@pytest.mark.asyncio
async def test_project_creation_requires_admin_permission(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Project creation must reject non-admin users."""
    non_admin_session = _make_admin_session()
    non_admin_session.permissions = ["read"]

    with patch("src.routes.projects.validate_session", return_value=non_admin_session):
        response = await client.post(
            "/projects",
            data={
                "project_name": "New Project",
            },
            headers={"Authorization": f"Bearer {non_admin_session.session_token}"},
        )

    assert response.status_code == 403
    data = response.json()
    assert data["status"] == "error"
    assert "error" in data
    assert "admin" in data["error"]["message"].lower()


@pytest.mark.asyncio
async def test_project_creation_requires_project_name(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Project creation must reject requests without project_name."""
    admin_session = _make_admin_session()

    with patch("src.routes.projects.validate_session", return_value=admin_session), \
         patch("src.routes.projects.get_user_by_hash", return_value=MagicMock(id="admin-1", username="adminuser", user_hash="usr-admin-001")):
        response = await client.post(
            "/projects",
            data={},  # No project_name
            headers={"Authorization": f"Bearer {admin_session.session_token}"},
        )

    # FastAPI Form validation returns 422 for missing required fields
    assert response.status_code in (422, 400), (
        f"Expected 422 or 400 for missing required field, got {response.status_code}"
    )


@pytest.mark.asyncio
async def test_project_creation_returns_correct_response_shape(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Project creation must return 200 with correct response shape."""
    admin_session = _make_admin_session()
    project = _make_project()

    with patch("src.routes.projects.validate_session", return_value=admin_session), \
         patch("src.routes.projects.get_user_by_hash", return_value=MagicMock(id="admin-1", username="adminuser", user_hash="usr-admin-001")), \
         patch("src.routes.projects.create_project", return_value=project):
        response = await client.post(
            "/projects",
            data={
                "project_name": "New Project",
                "project_description": "A new project",
            },
            headers={"Authorization": f"Bearer {admin_session.session_token}"},
        )

    assert response.status_code == 200
    data = response.json()

    # Response shape contract
    assert "success" in data
    assert data["success"] is True
    assert "message" in data
    assert "project" in data

    # Project shape
    proj = data["project"]
    assert "project_hash" in proj
    assert "project_name" in proj
    assert proj["project_name"] == "New Project"


@pytest.mark.asyncio
async def test_create_project_calls_create_default_groups(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """create_project must call create_default_groups after creating the project.

    This test verifies the DB layer: create_project() internally calls
    create_default_groups() which creates the project_group, project_group_members,
    3 user_groups, and 3 user_group_project_groups links.
    """
    from src.Util.db.db_projects import create_project
    from unittest.mock import MagicMock, patch as mock_patch

    mock_conn = make_db_connection_mock()

    create_groups = MagicMock()
    with mock_patch("src.Util.db.db_projects.get_connection", return_value=mock_conn), \
         mock_patch("src.Util.db.db_projects.create_default_groups", create_groups):
        project = create_project(
            "Test Project",
            "Test desc",
            created_by="admin-1",
            owner_id="admin-1",
        )

    assert project.project_name == "Test Project"
    create_groups.assert_called_once_with(project.id)
    mock_conn.commit.assert_called_once_with()
