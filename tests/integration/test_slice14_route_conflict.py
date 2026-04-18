"""
Slice 14 — Route Conflict Detection (Verification)

Tests: Verify that the route shadowing fix works correctly.
After removing duplicate routes from global_roles.py, the permission_assignments.py
versions should be the only ones handling /users/me/permissions endpoints.
Uses the REAL app with all middleware active.
"""

from unittest.mock import patch, MagicMock

import pytest

from tests.integration.conftest import make_session_payload, create_test_session


def _make_session(user_type="consumer", user_id="1", user_hash="usr-test-001",
                  project_hash="prj-test-001", project_id="1", permissions=None,
                  session_token="test-token"):
    s = MagicMock()
    s.user_id = user_id
    s.user_hash = user_hash
    s.user_type = user_type
    s.project_hash = project_hash
    s.project_name = "Test Project"
    s.project_id = project_id
    s.permissions = permissions or []
    s.groups = []
    s.session_token = session_token
    s.session_length = 259200
    s.username = "testuser"
    return s


def _make_user(user_type="consumer", user_id="1", user_hash="usr-test-001",
               username="testuser"):
    u = MagicMock()
    u.id = user_id
    u.user_hash = user_hash
    u.username = username
    u.email = "test@example.com"
    u.user_type = user_type
    u.is_active = True
    return u


@pytest.mark.asyncio
async def test_permissions_endpoint_resolves_correctly(client, fake_redis, patched_db_connection,
                                                        patched_db_error_logger, patched_audit_logger,
                                                        patched_audit_ids, patched_cache_manager,
                                                        patched_activity_logger):
    """GET /users/me/permissions should resolve to the permission_assignments handler.

    After removing duplicate routes from global_roles.py, only the
    permission_assignments.py version should handle this endpoint.
    This test verifies the endpoint works (not 404 or wrong handler).
    """
    token = "test-permissions-token"
    session = _make_session(session_token=token, permissions=["read", "write"])
    create_test_session(fake_redis, token, make_session_payload(
        session_token=token, permissions=["read", "write"]))

    user = _make_user()

    with patch("src.Util.db.validate_session", return_value=session), \
         patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.routes.permission_assignments.validate_session", return_value=session), \
         patch("src.routes.permission_assignments.get_user_by_hash", return_value=user), \
         patch("src.routes.permission_assignments.get_user_all_permissions", return_value={
             "permissions": ["read", "write"],
             "sources": []
         }):
        response = await client.get(
            "/permissions/users/me/permissions",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
        )

    # Should not be 404 (route exists) and not 500 (handler works)
    assert response.status_code in (200, 403, 401)

    if response.status_code == 200:
        data = response.json()
        # The permission_assignments handler returns permissions with sources
        assert "permissions" in data or "data" in data


@pytest.mark.asyncio
async def test_permissions_check_endpoint_resolves_correctly(client, fake_redis, patched_db_connection,
                                                              patched_db_error_logger, patched_audit_logger,
                                                              patched_audit_ids, patched_cache_manager,
                                                              patched_activity_logger):
    """GET /users/me/permissions/check/{name} should resolve correctly.

    After removing duplicate routes, only the permission_assignments.py version
    should handle this endpoint.
    """
    token = "test-perm-check-token"
    session = _make_session(session_token=token, permissions=["read", "write"])
    create_test_session(fake_redis, token, make_session_payload(
        session_token=token, permissions=["read", "write"]))

    user = _make_user()

    with patch("src.Util.db.validate_session", return_value=session), \
         patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.routes.permission_assignments.validate_session", return_value=session), \
         patch("src.routes.permission_assignments.get_user_by_hash", return_value=user), \
         patch("src.routes.permission_assignments.check_user_has_permission_extended", return_value={
             "has_permission": True,
             "permission": "read",
             "sources": []
         }):
        response = await client.get(
            "/permissions/users/me/permissions/check/read",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "test"},
        )

    # Should not be 404 (route exists)
    assert response.status_code != 404


@pytest.mark.asyncio
async def test_no_duplicate_routes_in_global_roles():
    """Verify that global_roles.py no longer has duplicate /users/me/permissions routes.

    This is a static verification that the fix was applied correctly.
    """
    import inspect
    from src.routes import global_roles

    # Get all route paths from global_roles router
    route_paths = []
    for route in global_roles.router.routes:
        route_paths.append(route.path)

    # The duplicate routes should NOT be present (they had prefix /users in global_roles)
    # Note: permission_assignments has prefix /permissions so its routes are /permissions/users/me/permissions
    has_user_permissions = any("/users/me/permissions" in p and not p.startswith("/permissions") for p in route_paths)
    assert not has_user_permissions, \
        "global_roles.py should not have /users/me/permissions routes (duplicate removed)"
