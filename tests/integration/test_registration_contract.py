"""
Slice 5 (Strategy Slice 5) — Registration Endpoint Contract

Contract-heavy test: Full registration flow with valid/invalid inputs,
verifying response shapes, status codes, and error messages.

Includes:
- Valid registration (200, correct response shape)
- Duplicate username (409)
- Duplicate email (409)
- Invalid user_group_hash (404)
- User group with no linked projects (200, project=null)
- Missing required fields (422)

Proof layer: Layer 3 (ASGI integration, mocked DB)
Trace: explore.md Gap 2
"""

from unittest.mock import patch, MagicMock

import pytest


def _make_user_group(group_id="1", group_hash="grp-contract-001", group_name="Contract Group"):
    g = MagicMock()
    g.id = group_id
    g.group_hash = group_hash
    g.group_name = group_name
    g.group_description = "A contract test group"
    return g


def _make_project(project_id="1", project_hash="prj-contract-001",
                  project_name="Contract Project"):
    p = MagicMock()
    p.id = project_id
    p.project_hash = project_hash
    p.project_name = project_name
    p.project_description = "A contract test project"
    return p


def _make_register_result(user_hash="usr-new-001", username="newuser",
                          email="new@example.com", user_type="consumer",
                          session_token="contract-session-token",
                          project_hash="prj-contract-001", project_name="Contract Project",
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


# ─── Valid Registration ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_registration_valid_response_shape(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Valid registration returns 200 with correct response shape."""
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
                "user_group_hash": "grp-contract-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()

    # Response shape contract
    assert "success" in data
    assert data["success"] is True
    assert "message" in data
    assert "user" in data
    assert "project" in data
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["session_token"] == data["access_token"]
    assert data["expires_in"]
    assert data["refresh_expires_in"]

    # User shape
    user = data["user"]
    assert "user_hash" in user
    assert "username" in user
    assert "user_type" in user
    assert user["username"] == "newuser"
    assert user["user_type"] == "consumer"

    # Project shape
    proj = data["project"]
    assert "project_hash" in proj
    assert "project_name" in proj
    assert proj["project_name"] == "Contract Project"


@pytest.mark.asyncio
async def test_registration_sets_cookie(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Valid registration must set access and refresh cookies."""
    group = _make_user_group()
    project = _make_project()
    result = _make_register_result(session_token="cookie-test-token")

    with patch("src.routes.auth.check_username_email_available", return_value=True), \
         patch("src.routes.auth.get_user_group_by_hash", return_value=group), \
         patch("src.routes.auth.get_projects_for_user_group", return_value=[project]), \
         patch("src.routes.auth.enhanced_register", return_value=result):
        response = await client.post(
            "/auth/register",
            data={
                "username": "newuser",
                "password": "SecureP@ss123",
                "user_group_hash": "grp-contract-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    assert "session_token" in response.cookies
    assert "refresh_token" in response.cookies
    data = response.json()
    assert response.cookies["session_token"] == data["access_token"]
    assert response.cookies["refresh_token"] == data["refresh_token"]


@pytest.mark.asyncio
async def test_registration_cookie_flags(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Registration cookie must have httponly, secure, samesite=strict flags."""
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
                "user_group_hash": "grp-contract-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    set_cookie_headers = response.headers.get_list("set-cookie")
    assert len(set_cookie_headers) >= 2
    cookie_headers = [value.lower() for value in set_cookie_headers]
    for expected_name in ("session_token", "refresh_token"):
        cookie_header = next((value for value in cookie_headers if f"{expected_name}=" in value), None)
        assert cookie_header is not None
        assert "httponly" in cookie_header
        assert "secure" in cookie_header
        assert "samesite=strict" in cookie_header


# ─── Error Contracts ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_registration_duplicate_username_409(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Duplicate username returns 409 with structured error."""
    with patch("src.routes.auth.check_username_email_available", return_value=False):
        response = await client.post(
            "/auth/register",
            data={
                "username": "existinguser",
                "password": "SecureP@ss123",
                "user_group_hash": "grp-contract-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 409
    data = response.json()
    assert data["status"] == "error"
    assert "error" in data
    assert "message" in data["error"]


@pytest.mark.asyncio
async def test_registration_duplicate_email_409(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Duplicate email returns 409 with structured error."""
    group = _make_user_group()
    project = _make_project()

    def mock_check(val):
        return val != "taken@example.com"

    with patch("src.routes.auth.check_username_email_available", side_effect=mock_check), \
         patch("src.routes.auth.get_user_group_by_hash", return_value=group), \
         patch("src.routes.auth.get_projects_for_user_group", return_value=[project]):
        response = await client.post(
            "/auth/register",
            data={
                "username": "newuser",
                "password": "SecureP@ss123",
                "email": "taken@example.com",
                "user_group_hash": "grp-contract-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 409
    data = response.json()
    assert data["status"] == "error"


@pytest.mark.asyncio
async def test_registration_invalid_group_hash_404(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Invalid user_group_hash returns 404 with structured error."""
    with patch("src.routes.auth.check_username_email_available", return_value=True), \
         patch("src.routes.auth.get_user_group_by_hash", return_value=None):
        response = await client.post(
            "/auth/register",
            data={
                "username": "newuser",
                "password": "SecureP@ss123",
                "user_group_hash": "nonexistent-hash",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 404
    data = response.json()
    assert data["status"] == "error"
    assert "error" in data
    assert "User group not found" in data["error"]["message"]


@pytest.mark.asyncio
async def test_registration_group_no_projects_succeeds(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """User group with no linked projects returns 200 with project=null.

    Batch registration before any project exists is valid per domain rules.
    """
    group = _make_user_group()
    result = _make_register_result(project_hash=None, project_name=None)

    with patch("src.routes.auth.check_username_email_available", return_value=True), \
         patch("src.routes.auth.get_user_group_by_hash", return_value=group), \
         patch("src.routes.auth.get_projects_for_user_group", return_value=[]), \
         patch("src.routes.auth.enhanced_register", return_value=result):
        response = await client.post(
            "/auth/register",
            data={
                "username": "newuser",
                "password": "SecureP@ss123",
                "user_group_hash": "grp-contract-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["project"] is None


@pytest.mark.asyncio
async def test_registration_without_email_succeeds(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Registration without email field should still succeed (email is optional)."""
    group = _make_user_group()
    project = _make_project()
    result = _make_register_result(email=None)

    with patch("src.routes.auth.check_username_email_available", return_value=True), \
         patch("src.routes.auth.get_user_group_by_hash", return_value=group), \
         patch("src.routes.auth.get_projects_for_user_group", return_value=[project]), \
         patch("src.routes.auth.enhanced_register", return_value=result):
        response = await client.post(
            "/auth/register",
            data={
                "username": "noemailuser",
                "password": "SecureP@ss123",
                "user_group_hash": "grp-contract-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
