"""
Slice 3 — Auth Flow: Register

Tests: POST /auth/register — valid registration (200 + token + cookie),
duplicate username (409), invalid group hash (404), group with no projects (400).
"""

from unittest.mock import patch, MagicMock

import pytest


def _make_user_group(group_id="1", group_hash="grp-test-001", group_name="Test Group"):
    g = MagicMock()
    g.id = group_id
    g.group_hash = group_hash
    g.group_name = group_name
    g.group_description = "A test group"
    return g


def _make_project(project_id="1", project_hash="prj-test-001",
                  project_name="Test Project"):
    p = MagicMock()
    p.id = project_id
    p.project_hash = project_hash
    p.project_name = project_name
    p.project_description = "A test project"
    return p


def _make_register_result(user_hash="usr-new-001", username="newuser",
                          email="new@example.com", user_type="consumer",
                          session_token="test-session-token",
                          project_hash="prj-test-001", project_name="Test Project",
                          user_id="99"):
    r = MagicMock()
    r.user_hash = user_hash
    r.username = username
    r.email = email
    r.user_type = user_type
    r.session_token = session_token
    r.project_hash = project_hash
    r.project_name = project_name
    r.user_id = user_id
    return r


@pytest.mark.asyncio
async def test_register_valid(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Valid registration returns 200 + session_token + cookie."""
    group = _make_user_group()
    project = _make_project()
    result = _make_register_result()

    with patch("src.routes.auth.check_username_email_available", return_value=True), \
         patch("src.routes.auth.get_user_group_by_hash", return_value=group), \
         patch("src.routes.auth.get_projects_for_user_group", return_value=[project]), \
         patch("src.routes.auth.enhanced_register", return_value=result):
        response = await client.post(
            "/auth/register",
            data={
                "username": "newuser",
                "password": "SecureP@ss123",
                "email": "new@example.com",
                "user_group_hash": "grp-test-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["user"]["username"] == "newuser"

    # Cookie should be set (session_token is in cookie, not response body for register)
    assert "session_token" in response.cookies


@pytest.mark.asyncio
async def test_register_duplicate_username(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Duplicate username returns 409 conflict."""
    with patch("src.routes.auth.check_username_email_available", return_value=False):
        response = await client.post(
            "/auth/register",
            data={
                "username": "existinguser",
                "password": "SecureP@ss123",
                "user_group_hash": "grp-test-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 409
    data = response.json()
    assert data["status"] == "error"


@pytest.mark.asyncio
async def test_register_invalid_group_hash(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Invalid group hash returns 404."""
    with patch("src.routes.auth.check_username_email_available", return_value=True), \
         patch("src.routes.auth.get_user_group_by_hash", return_value=None):
        response = await client.post(
            "/auth/register",
            data={
                "username": "newuser",
                "password": "SecureP@ss123",
                "user_group_hash": "grp-invalid-hash",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 404
    data = response.json()
    assert data["status"] == "error"


@pytest.mark.asyncio
async def test_register_group_no_projects(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Group with no linked projects returns 200 with project=null."""
    group = _make_user_group()
    result = _make_register_result(
        project_hash=None, project_name=None
    )

    with patch("src.routes.auth.check_username_email_available", return_value=True), \
         patch("src.routes.auth.get_user_group_by_hash", return_value=group), \
         patch("src.routes.auth.get_projects_for_user_group", return_value=[]), \
         patch("src.routes.auth.enhanced_register", return_value=result):
        response = await client.post(
            "/auth/register",
            data={
                "username": "newuser",
                "password": "SecureP@ss123",
                "user_group_hash": "grp-test-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["project"] is None


@pytest.mark.asyncio
async def test_register_duplicate_email(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Duplicate email returns 409 conflict."""
    group = _make_user_group()
    project = _make_project()

    def mock_check(val):
        if val == "newuser":
            return True
        return False  # email taken

    with patch("src.routes.auth.check_username_email_available", side_effect=mock_check), \
         patch("src.routes.auth.get_user_group_by_hash", return_value=group), \
         patch("src.routes.auth.get_projects_for_user_group", return_value=[project]):
        response = await client.post(
            "/auth/register",
            data={
                "username": "newuser",
                "password": "SecureP@ss123",
                "email": "taken@example.com",
                "user_group_hash": "grp-test-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 409
    data = response.json()
    assert data["status"] == "error"


@pytest.mark.asyncio
async def test_register_without_email(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Registration without email succeeds; response user email is None."""
    group = _make_user_group()
    project = _make_project()

    def make_result_no_email(*args, **kwargs):
        from src.Util.Models import EnhancedUserLogin
        r = EnhancedUserLogin(
            user_hash="usr-noemail-001",
            username=kwargs.get("username", "bob"),
            project_hash="prj-test-001",
            project_name="Test Project",
            session_token="tok-noemail",
            session_length=86400,
            user_id="101",
            project_id="1",
            user_project_id=None,
            user_project_hash="",
            groups=[],
            permissions=[],
            available_projects=[],
            user_type="consumer",
            assigned_project_id=None,
        )
        return r

    with patch("src.routes.auth.check_username_email_available", return_value=True), \
         patch("src.routes.auth.get_user_group_by_hash", return_value=group), \
         patch("src.routes.auth.get_projects_for_user_group", return_value=[project]), \
         patch("src.routes.auth.enhanced_register", side_effect=make_result_no_email):
        response = await client.post(
            "/auth/register",
            data={
                "username": "bob",
                "password": "SecureP@ss123",
                "user_group_hash": "grp-test-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["user"]["username"] == "bob"
    assert data["user"]["email"] is None


@pytest.mark.asyncio
async def test_register_username_none_in_result_does_not_crash(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Simulated register_result.username=None falls back to submitted username (no crash)."""
    group = _make_user_group()
    project = _make_project()
    result = MagicMock()
    result.user_hash = "usr-none-001"
    result.username = None
    result.email = None
    result.user_type = "consumer"
    result.session_token = "tok-none"
    result.project_hash = "prj-test-001"
    result.project_name = "Test Project"
    result.user_id = "102"

    with patch("src.routes.auth.check_username_email_available", return_value=True), \
         patch("src.routes.auth.get_user_group_by_hash", return_value=group), \
         patch("src.routes.auth.get_projects_for_user_group", return_value=[project]), \
         patch("src.routes.auth.enhanced_register", return_value=result):
        response = await client.post(
            "/auth/register",
            data={
                "username": "alice",
                "password": "SecureP@ss123",
                "user_group_hash": "grp-test-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["user"]["username"] == "alice"
