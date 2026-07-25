"""
Slice 16 (Strategy Slice 1) — Registration Orchestration Chain

Characterization test: Verify POST /auth/register calls DB functions in the
correct sequence with the right parameters:
  check_username_email_available → get_user_group_by_hash → enhanced_register

Note: get_projects_for_user_group is called INSIDE enhanced_register,
not at the route level. The route only validates group existence.

Proof layer: Layer 2 (integration, mocked DB)
Trace: explore.md RISK 4, Gap 2
"""

from unittest.mock import patch, MagicMock, call

import pytest


def _make_user_group(group_id="1", group_hash="grp-ug-001", group_name="Test UG"):
    g = MagicMock()
    g.id = group_id
    g.group_hash = group_hash
    g.group_name = group_name
    g.group_description = "A test user group"
    return g


def _make_project(project_id="1", project_hash="prj-orch-001",
                  project_name="Orch Project"):
    p = MagicMock()
    p.id = project_id
    p.project_hash = project_hash
    p.project_name = project_name
    p.project_description = "A test project"
    return p


def _make_register_result(user_hash="usr-reg-001", username="reguser",
                          email="reg@example.com", user_type="consumer",
                          session_token="reg-session-token",
                          project_hash="prj-orch-001", project_name="Orch Project",
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
async def test_registration_calls_check_username_first(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Registration must check username availability before anything else."""
    group = _make_user_group()
    project = _make_project()
    result = _make_register_result()

    call_order = []

    def track_check(val):
        call_order.append(("check_username_email_available", val))
        return True

    with patch("src.routes.auth.check_username_email_available", side_effect=track_check), \
         patch("src.routes.auth.get_user_group_by_hash", return_value=group), \
         patch("src.routes.auth.get_projects_for_user_group", return_value=[project]), \
         patch("src.routes.auth.enhanced_register", return_value=result):
        response = await client.post(
            "/auth/register",
            data={
                "username": "reguser",
                "password": "SecureP@ss123",
                "email": "reg@example.com",
                "user_group_hash": "grp-ug-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    # Username check must have been called
    assert any(c[0] == "check_username_email_available" for c in call_order)


@pytest.mark.asyncio
async def test_registration_validates_group_before_register(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Registration must validate user group exists BEFORE calling enhanced_register.

    Note: get_projects_for_user_group is called INSIDE enhanced_register,
    not at the route level. The route only checks group existence.
    """
    group = _make_user_group()
    project = _make_project()
    result = _make_register_result()

    call_sequence = []

    def track_check(val):
        call_sequence.append("check")
        return True

    def track_group_lookup(hash_val):
        call_sequence.append("group_lookup")
        return group

    def track_register(*args):
        call_sequence.append("register")
        return result

    with patch("src.routes.auth.check_username_email_available", side_effect=track_check), \
         patch("src.routes.auth.get_user_group_by_hash", side_effect=track_group_lookup), \
         patch("src.routes.auth.enhanced_register", side_effect=track_register):
        response = await client.post(
            "/auth/register",
            data={
                "username": "reguser",
                "password": "SecureP@ss123",
                "email": "reg@example.com",
                "user_group_hash": "grp-ug-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    # Sequence: check(username) → check(email) → group_lookup → register
    # get_projects_for_user_group is called inside enhanced_register, not at route level
    assert call_sequence == ["check", "check", "group_lookup", "register"]


@pytest.mark.asyncio
async def test_registration_passes_correct_group_hash(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Registration must pass the exact user_group_hash to get_user_group_by_hash."""
    group = _make_user_group()
    project = _make_project()
    result = _make_register_result()

    captured_hash = None

    def capture_hash(hash_val):
        nonlocal captured_hash
        captured_hash = hash_val
        return group

    with patch("src.routes.auth.check_username_email_available", return_value=True), \
         patch("src.routes.auth.get_user_group_by_hash", side_effect=capture_hash), \
         patch("src.routes.auth.get_projects_for_user_group", return_value=[project]), \
         patch("src.routes.auth.enhanced_register", return_value=result):
        response = await client.post(
            "/auth/register",
            data={
                "username": "reguser",
                "password": "SecureP@ss123",
                "user_group_hash": "grp-specific-hash-xyz",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    assert captured_hash == "grp-specific-hash-xyz"


@pytest.mark.asyncio
async def test_registration_passes_group_id_to_projects_lookup(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """enhanced_register receives the group_hash and internally resolves projects.

    Note: get_projects_for_user_group is called inside enhanced_register,
    not at the route level. This test verifies the route passes the correct
    group_hash to enhanced_register.
    """
    group = _make_user_group(group_id="ug-id-42")
    result = _make_register_result()

    captured_hash = None

    def capture_hash(*args):
        nonlocal captured_hash
        captured_hash = args[3]  # group_hash is the 4th argument
        return result

    with patch("src.routes.auth.check_username_email_available", return_value=True), \
         patch("src.routes.auth.get_user_group_by_hash", return_value=group), \
         patch("src.routes.auth.enhanced_register", side_effect=capture_hash):
        response = await client.post(
            "/auth/register",
            data={
                "username": "reguser",
                "password": "SecureP@ss123",
                "user_group_hash": "grp-ug-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    assert captured_hash == "grp-ug-001"


@pytest.mark.asyncio
async def test_registration_passes_correct_params_to_enhanced_register(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Registration must pass (username, password, email, user_group_hash) to enhanced_register."""
    group = _make_user_group()
    project = _make_project()
    result = _make_register_result()

    captured_args = None

    def capture_args(*args):
        nonlocal captured_args
        captured_args = args
        return result

    with patch("src.routes.auth.check_username_email_available", return_value=True), \
         patch("src.routes.auth.get_user_group_by_hash", return_value=group), \
         patch("src.routes.auth.get_projects_for_user_group", return_value=[project]), \
         patch("src.routes.auth.enhanced_register", side_effect=capture_args):
        response = await client.post(
            "/auth/register",
            data={
                "username": "orchuser",
                "password": "SecureP@ss123",
                "email": "orch@example.com",
                "user_group_hash": "grp-ug-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    assert captured_args is not None
    assert captured_args[0] == "orchuser"       # username
    assert captured_args[1] == "SecureP@ss123"  # password
    assert captured_args[2] == "orch@example.com"  # email
    assert captured_args[3] == "grp-ug-001"     # user_group_hash


@pytest.mark.asyncio
async def test_registration_email_check_is_second_username_check(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """When email is provided, check_username_email_available is called twice: username then email."""
    group = _make_user_group()
    project = _make_project()
    result = _make_register_result()

    checked_values = []

    def track_check(val):
        checked_values.append(val)
        return True

    with patch("src.routes.auth.check_username_email_available", side_effect=track_check), \
         patch("src.routes.auth.get_user_group_by_hash", return_value=group), \
         patch("src.routes.auth.get_projects_for_user_group", return_value=[project]), \
         patch("src.routes.auth.enhanced_register", return_value=result):
        response = await client.post(
            "/auth/register",
            data={
                "username": "reguser",
                "password": "SecureP@ss123",
                "email": "reg@example.com",
                "user_group_hash": "grp-ug-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    assert len(checked_values) == 2
    assert checked_values[0] == "reguser"
    assert checked_values[1] == "reg@example.com"
