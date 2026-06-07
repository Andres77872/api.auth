"""
Slice 2 — Auth Flow: Login

Tests: POST /auth/login — valid credentials (200 + token + cookie),
invalid credentials (401), missing fields (422), root user login (no project),
consumer user with project, consumer user without project.
"""

from unittest.mock import patch, MagicMock

import pytest


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
    u.password_hash = "$argon2id$fake"
    return u


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


def _make_group(group_id="1", group_hash="grp-test-001", group_name="Test Group"):
    g = MagicMock()
    g.id = group_id
    g.group_hash = group_hash
    g.group_name = group_name
    g.group_description = "A test group"
    return g


@pytest.mark.asyncio
async def test_login_valid_consumer_credentials(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Valid consumer login returns 200 + session_token + cookie."""
    user = _make_user(user_type="consumer")
    project = _make_project()
    group = _make_group()

    with patch("src.routes.auth.get_user_by_credentials", return_value=user), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
         patch("src.routes.auth.get_project_by_hash", return_value=project), \
         patch("src.routes.auth.get_user_groups_for_user", return_value=[group]):
        response = await client.post(
            "/auth/login",
            data={
                "username": "testuser",
                "password": "correctpassword",
                "project_hash": "prj-test-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "session_token" in data
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["session_token"] == data["access_token"]
    assert data["user"]["username"] == "testuser"
    assert data["user"]["user_type"] == "consumer"
    assert len(data["accessible_projects"]) >= 1
    assert len(data["user_groups"]) >= 1

    # Cookie should be set
    cookies = response.cookies
    assert "session_token" in cookies
    assert "refresh_token" in cookies


@pytest.mark.asyncio
async def test_login_invalid_credentials(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Invalid credentials return 401 with structured error."""
    with patch("src.routes.auth.get_user_by_credentials", return_value=None):
        response = await client.post(
            "/auth/login",
            data={"username": "testuser", "password": "wrongpassword"},
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 401
    data = response.json()
    assert data["status"] == "error"
    assert "error" in data


@pytest.mark.asyncio
async def test_login_missing_fields(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Missing username or password returns 422 validation error."""
    response = await client.post(
        "/auth/login",
        data={"username": ""},
        headers={"User-Agent": "test"},
    )

    # FastAPI Form validation catches empty required fields
    assert response.status_code in (422, 400)


@pytest.mark.asyncio
async def test_login_root_user_with_project(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Root user login with project_hash succeeds and returns project-bound session."""
    root_user = _make_user(user_type="root", user_id="0", user_hash="usr-root-001",
                           username="rootuser", email="root@example.com")
    project = _make_project()

    with patch("src.routes.auth.get_user_by_credentials", return_value=root_user), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
         patch("src.routes.auth.get_project_by_hash", return_value=project), \
         patch("src.routes.auth.get_user_groups_for_user", return_value=[]):
        response = await client.post(
            "/auth/login",
            data={
                "username": "rootuser",
                "password": "rootpass",
                "project_hash": "prj-test-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["user"]["user_type"] == "root"
    assert data["project"] is not None
    assert data["project"]["project_hash"] == "prj-test-001"
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["session_token"] == data["access_token"]


@pytest.mark.asyncio
async def test_login_root_without_project_rejected(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Root user login without project_hash returns 400 validation error."""
    root_user = _make_user(user_type="root", user_id="0", user_hash="usr-root-001",
                           username="rootuser", email="root@example.com")

    with patch("src.routes.auth.get_user_by_credentials", return_value=root_user):
        response = await client.post(
            "/auth/login",
            data={"username": "rootuser", "password": "rootpass"},
            headers={"User-Agent": "test"},
        )

    assert response.status_code in (400, 422)
    data = response.json()
    assert data["status"] == "error"


@pytest.mark.asyncio
async def test_login_root_with_invalid_project_rejected(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Root user login with non-existent project_hash returns 404."""
    root_user = _make_user(user_type="root", user_id="0", user_hash="usr-root-001",
                           username="rootuser", email="root@example.com")

    with patch("src.routes.auth.get_user_by_credentials", return_value=root_user), \
         patch("src.routes.auth.get_project_by_hash", return_value=None):
        response = await client.post(
            "/auth/login",
            data={
                "username": "rootuser",
                "password": "rootpass",
                "project_hash": "prj-nonexistent",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 404
    data = response.json()
    assert data["status"] == "error"


@pytest.mark.asyncio
async def test_login_root_bypasses_group_validation(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Root user can login to any project without group membership."""
    root_user = _make_user(user_type="root", user_id="0", user_hash="usr-root-001",
                           username="rootuser", email="root@example.com")
    project = _make_project()

    # Root gets ALL projects from accessible_projects SP bypass
    with patch("src.routes.auth.get_user_by_credentials", return_value=root_user), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
         patch("src.routes.auth.get_project_by_hash", return_value=project):
        # Note: get_user_groups_for_user is NOT patched — it should NOT be called
        response = await client.post(
            "/auth/login",
            data={
                "username": "rootuser",
                "password": "rootpass",
                "project_hash": "prj-test-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["user"]["user_type"] == "root"
    assert data["project"]["project_hash"] == "prj-test-001"
    assert data["user_groups"] == []


@pytest.mark.asyncio
async def test_login_consumer_without_project_rejected(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Non-root user login without project_hash returns 400 validation error."""
    user = _make_user(user_type="consumer")

    with patch("src.routes.auth.get_user_by_credentials", return_value=user):
        response = await client.post(
            "/auth/login",
            data={"username": "testuser", "password": "correctpassword"},
            headers={"User-Agent": "test"},
        )

    assert response.status_code in (400, 422)
    data = response.json()
    assert data["status"] == "error"


@pytest.mark.asyncio
async def test_login_consumer_no_accessible_projects(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Consumer with no project access gets 403."""
    user = _make_user(user_type="consumer")

    with patch("src.routes.auth.get_user_by_credentials", return_value=user), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[]):
        response = await client.post(
            "/auth/login",
            data={
                "username": "testuser",
                "password": "correctpassword",
                "project_hash": "prj-test-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 403
    data = response.json()
    assert data["status"] == "error"


@pytest.mark.asyncio
async def test_login_consumer_with_specific_project(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Consumer can login to a specific project they have access to."""
    user = _make_user(user_type="consumer")
    project = _make_project()
    group = _make_group()

    with patch("src.routes.auth.get_user_by_credentials", return_value=user), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
         patch("src.routes.auth.get_project_by_hash", return_value=project), \
         patch("src.routes.auth.get_user_groups_for_user", return_value=[group]):
        response = await client.post(
            "/auth/login",
            data={
                "username": "testuser",
                "password": "correctpassword",
                "project_hash": "prj-test-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["project"]["project_hash"] == "prj-test-001"


@pytest.mark.asyncio
async def test_login_consumer_denied_project(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Consumer denied access to project they don't have access to."""
    user = _make_user(user_type="consumer")
    project = _make_project()

    with patch("src.routes.auth.get_user_by_credentials", return_value=user), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[project]):
        response = await client.post(
            "/auth/login",
            data={
                "username": "testuser",
                "password": "correctpassword",
                "project_hash": "prj-other-project",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 403
    data = response.json()
    assert data["status"] == "error"


@pytest.mark.asyncio
async def test_login_cookie_flags(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Login cookie should have httponly, secure, samesite=strict flags."""
    user = _make_user(user_type="consumer")
    project = _make_project()
    group = _make_group()

    with patch("src.routes.auth.get_user_by_credentials", return_value=user), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
         patch("src.routes.auth.get_project_by_hash", return_value=project), \
         patch("src.routes.auth.get_user_groups_for_user", return_value=[group]):
        response = await client.post(
            "/auth/login",
            data={
                "username": "testuser",
                "password": "correctpassword",
                "project_hash": "prj-test-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    # Check set-cookie header for flags
    set_cookie_headers = response.headers.get_list("set-cookie")
    assert len(set_cookie_headers) >= 1
    cookie_header = set_cookie_headers[0].lower()
    assert "httponly" in cookie_header
    assert "secure" in cookie_header
    assert "samesite=strict" in cookie_header


@pytest.mark.asyncio
async def test_login_admin_without_project_rejected(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Admin user (non-root) login without project_hash returns 400 validation error."""
    admin_user = _make_user(user_type="admin", user_id="2", user_hash="usr-admin-001",
                            username="adminuser", email="admin@example.com")

    with patch("src.routes.auth.get_user_by_credentials", return_value=admin_user):
        response = await client.post(
            "/auth/login",
            data={"username": "adminuser", "password": "correctpassword"},
            headers={"User-Agent": "test"},
        )

    assert response.status_code in (400, 422)
    data = response.json()
    assert data["status"] == "error"


@pytest.mark.asyncio
async def test_login_admin_with_project_succeeds(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Admin user login with valid project_hash returns 200 + session_token."""
    admin_user = _make_user(user_type="admin", user_id="2", user_hash="usr-admin-001",
                            username="adminuser", email="admin@example.com")
    project = _make_project()
    group = _make_group()

    with patch("src.routes.auth.get_user_by_credentials", return_value=admin_user), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
         patch("src.routes.auth.get_project_by_hash", return_value=project), \
         patch("src.routes.auth.get_user_groups_for_user", return_value=[group]):
        response = await client.post(
            "/auth/login",
            data={
                "username": "adminuser",
                "password": "correctpassword",
                "project_hash": "prj-test-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "session_token" in data
    assert data["user"]["username"] == "adminuser"
    assert data["user"]["user_type"] == "admin"
    assert data["project"]["project_hash"] == "prj-test-001"
    assert len(data["accessible_projects"]) >= 1
    assert len(data["user_groups"]) >= 1


@pytest.mark.asyncio
async def test_login_admin_denied_project(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Admin denied access to project they don't have access to."""
    admin_user = _make_user(user_type="admin", user_id="2", user_hash="usr-admin-001",
                            username="adminuser", email="admin@example.com")
    project = _make_project()

    with patch("src.routes.auth.get_user_by_credentials", return_value=admin_user), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[project]):
        response = await client.post(
            "/auth/login",
            data={
                "username": "adminuser",
                "password": "correctpassword",
                "project_hash": "prj-other-project",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 403
    data = response.json()
    assert data["status"] == "error"


@pytest.mark.asyncio
async def test_platform_login_root_success(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Root can use dedicated platform login without project_hash."""
    root_user = _make_user(user_type="root", user_id="0", user_hash="usr-root-001",
                           username="rootuser", email="root@example.com")

    with patch("src.routes.auth.get_user_by_credentials", return_value=root_user):
        response = await client.post(
            "/auth/platform/login",
            data={"username": "rootuser", "password": "rootpass"},
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["user"]["user_type"] == "root"
    assert data["project"] is None
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["session_token"] == data["access_token"]
    token = data["session_token"]
    from src.Util.JWT_Security import JWTTokenHandler
    access_jti = JWTTokenHandler.decode_access_token(token)["jti"]
    session_raw = fake_redis.get(f"session:{access_jti}")
    assert session_raw is not None


@pytest.mark.asyncio
async def test_platform_login_admin_success(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Admin can use dedicated platform login without project_hash."""
    admin_user = _make_user(user_type="admin", user_id="2", user_hash="usr-admin-001",
                            username="adminuser", email="admin@example.com")

    with patch("src.routes.auth.get_user_by_credentials", return_value=admin_user):
        response = await client.post(
            "/auth/platform/login",
            data={"username": "adminuser", "password": "correctpassword"},
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["user"]["user_type"] == "admin"
    assert data["project"] is None
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["session_token"] == data["access_token"]


@pytest.mark.asyncio
async def test_platform_login_consumer_rejected(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Consumer credentials are rejected from platform login early."""
    consumer_user = _make_user(user_type="consumer")

    with patch("src.routes.auth.get_user_by_credentials", return_value=consumer_user):
        response = await client.post(
            "/auth/platform/login",
            data={"username": "testuser", "password": "correctpassword"},
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 403
    data = response.json()
    assert data["status"] == "error"


@pytest.mark.asyncio
async def test_login_multi_group_one_group_has_projects(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """User belongs to two groups: one with projects, one without.
    Login to the accessible project succeeds — multi-group resilience.
    """
    user = _make_user(user_type="consumer")
    project = _make_project()
    group_with_projects = _make_group(
        group_id="1", group_hash="grp-linked", group_name="Linked Group"
    )
    group_without_projects = _make_group(
        group_id="2", group_hash="grp-orphan", group_name="Orphan Group"
    )

    with patch("src.routes.auth.get_user_by_credentials", return_value=user), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
         patch("src.routes.auth.get_project_by_hash", return_value=project), \
         patch("src.routes.auth.get_user_groups_for_user",
               return_value=[group_with_projects, group_without_projects]):
        response = await client.post(
            "/auth/login",
            data={
                "username": "testuser",
                "password": "correctpassword",
                "project_hash": "prj-test-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["project"]["project_hash"] == "prj-test-001"
    # Both groups appear in response
    assert len(data["user_groups"]) == 2
