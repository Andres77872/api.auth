"""
Slice 17 (Strategy Slice 2) — Login Orchestration with Groups-of-Groups

Characterization test: Verify POST /auth/login for non-root user calls:
  get_user_by_credentials → get_user_accessible_projects →
  get_user_groups_for_user → _create_session with correct group data in Redis

Proof layer: Layer 2 (integration, mocked DB)
Trace: explore.md RISK 3, Gap 1
"""

import json
from unittest.mock import patch, MagicMock

import pytest


def _make_user(user_type="consumer", user_id="1", user_hash="usr-login-001",
               username="loginuser", email="login@example.com"):
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


def _make_project(project_id="1", project_hash="prj-login-001",
                  project_name="Login Project", project_description="A login test project"):
    p = MagicMock()
    p.id = project_id
    p.project_hash = project_hash
    p.project_name = project_name
    p.project_description = project_description
    p.owner_id = "1"
    p.is_active = True
    return p


def _make_group(group_id="1", group_hash="grp-login-001", group_name="Login Group"):
    g = MagicMock()
    g.id = group_id
    g.group_hash = group_hash
    g.group_name = group_name
    g.group_description = "A login test group"
    return g


@pytest.mark.asyncio
async def test_login_calls_credentials_first(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Login must verify credentials before any other DB call."""
    user = _make_user()
    project = _make_project()
    group = _make_group()

    call_sequence = []

    def track_creds(*args):
        call_sequence.append("credentials")
        return user

    def track_accessible(uid):
        call_sequence.append("accessible_projects")
        return [project]

    def track_groups(uid):
        call_sequence.append("user_groups")
        return [group]

    def track_project_by_hash(hash_val):
        call_sequence.append("project_by_hash")
        return project

    with patch("src.routes.auth.get_user_by_credentials", side_effect=track_creds), \
         patch("src.routes.auth.get_user_accessible_projects", side_effect=track_accessible), \
         patch("src.routes.auth.get_project_by_hash", side_effect=track_project_by_hash), \
         patch("src.routes.auth.get_user_groups_for_user", side_effect=track_groups):
        response = await client.post(
            "/auth/login",
            data={
                "username": "loginuser",
                "password": "correctpassword",
                "project_hash": "prj-login-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    # credentials must be checked first
    assert call_sequence[0] == "credentials"
    # accessible_projects must come before user_groups (login flow)
    assert call_sequence.index("accessible_projects") < call_sequence.index("user_groups")


@pytest.mark.asyncio
async def test_login_passes_user_id_to_accessible_projects(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Login must pass the authenticated user's ID to get_user_accessible_projects."""
    user = _make_user(user_id="user-42")
    project = _make_project()
    group = _make_group()

    captured_uid = None

    def capture_uid(uid):
        nonlocal captured_uid
        captured_uid = uid
        return [project]

    with patch("src.routes.auth.get_user_by_credentials", return_value=user), \
         patch("src.routes.auth.get_user_accessible_projects", side_effect=capture_uid), \
         patch("src.routes.auth.get_project_by_hash", return_value=project), \
         patch("src.routes.auth.get_user_groups_for_user", return_value=[group]):
        response = await client.post(
            "/auth/login",
            data={
                "username": "loginuser",
                "password": "correctpassword",
                "project_hash": "prj-login-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    assert captured_uid == "user-42"


@pytest.mark.asyncio
async def test_login_stores_user_groups_in_redis_session(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Login must store user_group_ids and user_group_names in the Redis session."""
    user = _make_user()
    project = _make_project()
    group1 = _make_group(group_id="g1", group_name="Admins")
    group2 = _make_group(group_id="g2", group_name="Users")

    with patch("src.routes.auth.get_user_by_credentials", return_value=user), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
         patch("src.routes.auth.get_project_by_hash", return_value=project), \
         patch("src.routes.auth.get_user_groups_for_user", return_value=[group1, group2]):
        response = await client.post(
            "/auth/login",
            data={
                "username": "loginuser",
                "password": "correctpassword",
                "project_hash": "prj-login-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    token = data["session_token"]

    # Verify session was stored in Redis with group data
    session_raw = fake_redis.get(f"session:{token}")
    assert session_raw is not None
    session_data = json.loads(session_raw)
    assert "user_group_ids" in session_data
    assert "user_group_names" in session_data
    assert session_data["user_group_ids"] == ["g1", "g2"]
    assert session_data["user_group_names"] == ["Admins", "Users"]


@pytest.mark.asyncio
async def test_login_returns_user_groups_in_response(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Login response must include user_groups list with group_hash and group_name."""
    user = _make_user()
    project = _make_project()
    group = _make_group(group_hash="grp-hash-abc", group_name="Test Group")

    with patch("src.routes.auth.get_user_by_credentials", return_value=user), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
         patch("src.routes.auth.get_project_by_hash", return_value=project), \
         patch("src.routes.auth.get_user_groups_for_user", return_value=[group]):
        response = await client.post(
            "/auth/login",
            data={
                "username": "loginuser",
                "password": "correctpassword",
                "project_hash": "prj-login-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert "user_groups" in data
    assert len(data["user_groups"]) == 1
    assert data["user_groups"][0]["group_hash"] == "grp-hash-abc"
    assert data["user_groups"][0]["group_name"] == "Test Group"


@pytest.mark.asyncio
async def test_login_root_skips_user_groups(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Root user login must NOT call get_user_groups_for_user."""
    root_user = _make_user(user_type="root", user_id="0", user_hash="usr-root-001")
    project = _make_project()

    groups_called = False

    def track_groups(uid):
        nonlocal groups_called
        groups_called = True
        return []

    with patch("src.routes.auth.get_user_by_credentials", return_value=root_user), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
         patch("src.routes.auth.get_project_by_hash", return_value=project), \
         patch("src.routes.auth.get_user_groups_for_user", side_effect=track_groups):
        response = await client.post(
            "/auth/login",
            data={
                "username": "rootuser",
                "password": "rootpass",
                "project_hash": "prj-login-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    assert not groups_called, "get_user_groups_for_user should NOT be called for root users"


@pytest.mark.asyncio
async def test_login_passes_user_id_to_user_groups(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Login must pass the correct user_id to get_user_groups_for_user."""
    user = _make_user(user_id="specific-user-id")
    project = _make_project()
    group = _make_group()

    captured_uid = None

    def capture_uid(uid):
        nonlocal captured_uid
        captured_uid = uid
        return [group]

    with patch("src.routes.auth.get_user_by_credentials", return_value=user), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
         patch("src.routes.auth.get_project_by_hash", return_value=project), \
         patch("src.routes.auth.get_user_groups_for_user", side_effect=capture_uid):
        response = await client.post(
            "/auth/login",
            data={
                "username": "loginuser",
                "password": "correctpassword",
                "project_hash": "prj-login-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    assert captured_uid == "specific-user-id"
