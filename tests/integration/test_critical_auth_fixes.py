"""
Critical Auth Contract Fixes — Regression Tests (G1–G14)

Traceability: Spec §6, Design §Testing Strategy, Proposal §Regression-Avoidance
Coverage: Fix 1 (session schema), Fix 2 (optional_auth), Fix 3 (authz checkers),
          Fix 4 (secondary permission swallows)
Type: Integration-level — mocks infrastructure at the boundary, NOT the function under test.
"""

import json
from unittest.mock import patch, MagicMock

import fakeredis
import pytest

from src.Util.error_handler import DatabaseError, InternalError


# =============================================================================
# Shared Fixtures
# =============================================================================

@pytest.fixture
def mock_fakeredis():
    """Provide a clean fakeredis instance."""
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    with patch("src.Util.db_config.redis_client", fake), \
         patch("src.Util.cache_manager.redis_client", fake), \
         patch("src.Util.auth_lifecycle.redis_client", fake), \
         patch("src.routes.auth.redis_client", fake), \
         patch("src.Util.db.db_enhanced.client", fake), \
         patch("src.Util.db.db_users.client", fake):
        # Also patch the cache_manager's redis reference directly
        from src.Util.cache_manager import cache_manager
        original_redis = getattr(cache_manager, "redis", None)
        cache_manager.redis = fake
        yield fake
        if original_redis is not None:
            cache_manager.redis = original_redis
        fake.flushall()


@pytest.fixture
def patched_db_connections():
    """Patch get_connection at all relevant locations with a shared mock conn."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    mock_cursor.fetchone.return_value = None
    mock_cursor.fetchall.return_value = []
    targets = [
        "src.Util.db_config.get_connection",
        "src.Util.db.db_users.get_connection",
        "src.Util.db.db_enhanced.get_connection",
        "src.Util.db.db_user_groups.get_connection",
        "src.Util.db.db_global_roles.get_connection",
        "src.Util.db.db_projects.get_connection",
    ]
    patchers = [patch(t, return_value=mock_conn) for t in targets]
    for p in patchers:
        p.start()
    try:
        yield mock_conn
    finally:
        for p in patchers:
            p.stop()


# =============================================================================
# G5 — Old Redis session (no 'groups' key) still returns valid EnhancedUserLogin
# =============================================================================

def test_old_session_without_groups_key_still_valid(mock_fakeredis):
    """
    G5: Old Redis session WITHOUT 'groups' key must still return a valid
    EnhancedUserLogin with correct hardcoded defaults.

    Should PASS before AND after Fix 1 (backward compat is pre-existing behavior).
    """
    from src.Util.db.db_enhanced import validate_session
    from src.Util.db_config import redis_client

    mock_project = MagicMock()
    mock_project.id = "1"
    mock_project.project_hash = "prj-test-001"
    mock_project.project_name = "Test Project"

    # ---- Test admin user ----
    admin_session = {
        "session_id": 12345,
        "user_id": "42",
        "user_hash": "usr-test-042",
        "user_type": "admin",
        "project_id": "1",
        "project_hash": "prj-test-001",
        "project_name": "Test Project",
        "user_group_ids": ["10", "20"],
        "user_group_names": ["project_admins", "devops"],
        # Deliberately NO 'groups' key — pre-fix format
    }
    redis_client.set("session:admin-token", json.dumps(admin_session))

    # is_admin_user() calls get_user_type via the import in db_enhanced's namespace
    # check_admin_project_access dynamically imports check_admin_multi_project_access
    with patch("src.Util.db.db_enhanced.get_user_type", return_value="admin"), \
         patch("src.Util.db.db_enhanced.get_project_by_hash", return_value=mock_project), \
         patch("src.Util.db.db_users.check_admin_multi_project_access",
               return_value=True), \
         patch("src.Util.db.db_enhanced.get_user_accessible_projects",
               return_value=[]):

        result = validate_session("admin-token")

        assert result is not None, (
            "G5 FAIL: validate_session returned None for old admin session"
        )
        # Admin default hardcoded in validate_session line 451
        assert result.groups == ["project_admins"], (
            f"G5 FAIL: admin groups should default to ['project_admins'], "
            f"got {result.groups}"
        )
        assert result.user_id == "42"
        assert result.user_type == "admin"

    # ---- Test root user ----
    # Root path through validate_session (line 439-441):
    #   groups = session_data.get('groups', ['root_users'])
    # Root does NOT call check_admin_project_access, only get_project_by_hash
    root_session = dict(admin_session)
    root_session["user_type"] = "root"
    root_session["session_id"] = 54321  # Different ID to avoid cache collision
    redis_client.set("session:root-token", json.dumps(root_session))

    with patch("src.Util.db.db_enhanced.get_project_by_hash", return_value=mock_project):
        result_root = validate_session("root-token")

        assert result_root is not None, (
            "G5 FAIL: validate_session returned None for old root session"
        )
        assert result_root.groups == ["root_users"], (
            f"G5 FAIL: root groups should default to ['root_users'], "
            f"got {result_root.groups}"
        )
        assert result_root.user_type == "root"




# =============================================================================
# G7 — Consumer user session: groups resolved fresh from DB (not hardcoded)
# =============================================================================

def test_consumer_session_groups_fresh_from_db(mock_fakeredis):
    """
    G7: Consumer user via issue_project_token_pair() → validate_session() returns
    correct groups resolved fresh from DB (NOT from session_data.get('groups')).

    Should PASS before AND after Fix 1 (consumer path unaffected by additive change).
    """
    from src.Util.auth_lifecycle import issue_project_token_pair
    from src.Util.db.db_enhanced import validate_session

    user = MagicMock()
    user.id = "99"
    user.user_hash = "usr-test-099"
    user.username = "consumer1"
    user.user_type = "consumer"

    mock_group = MagicMock()
    mock_group.id = "10"
    mock_group.group_name = "developers"

    project = MagicMock()
    project.id = "1"
    project.project_hash = "prj-test-001"
    project.project_name = "Test Project"

    token_pair = issue_project_token_pair(
        user=user,
        project=project,
        permissions=[],
        groups=[mock_group.group_name],
        group_ids=[str(mock_group.id)],
    )
    token = token_pair.access_token

    # validate_session consumer path (line 458-478):
    #   461: groups_objs = get_user_groups_in_project_by_hash(user_id, project_hash)
    #   466: groups = [g.group_name for g in groups_objs]
    #   472: permissions = get_user_permissions(user_id)  [lazy import from db_global_roles]
    #   478: available_projects = get_user_accessible_projects(user_id)
    with patch("src.Util.db.db_enhanced.get_user_by_hash", return_value=user), \
         patch("src.Util.db.db_enhanced.get_user_groups_in_project_by_hash",
               return_value=[mock_group]), \
         patch("src.Util.db.db_enhanced.get_project_by_hash", return_value=project), \
         patch("src.Util.db.db_global_roles.get_user_permissions",
               return_value=[]), \
         patch("src.Util.db.db_enhanced.get_user_accessible_projects",
               return_value=[]):

        result = validate_session(token)

        assert result is not None, "G7 FAIL: validate_session returned None for consumer"
        assert result.user_type == "consumer"
        assert "developers" in result.groups, (
            f"G7 FAIL: Consumer groups should contain 'developers' from DB, "
            f"got {result.groups}"
        )


# =============================================================================
# G2 — optional_auth: Redis failure returns 500 (not None)
# =============================================================================

@pytest.mark.asyncio
async def test_optional_auth_redis_failure_returns_500():
    """
    G2 (RED → GREEN): When validate_session() raises (Redis down),
    optional_auth() must raise HTTPException(500), NOT return None.

    Should FAIL before Fix 2 (silent None).
    Should PASS after Fix 2.
    """
    from src.middleware.authentication import optional_auth
    from fastapi import HTTPException

    # Mock credentials with a real-looking token
    creds = MagicMock()
    creds.credentials = "test-token-abcdef123456"

    # Patch validate_session to raise InternalError (simulating Redis down)
    with patch("src.middleware.authentication.validate_session",
               side_effect=InternalError("Redis connection failed")), \
         patch("src.middleware.authentication.logger") as mock_logger:

        with pytest.raises(HTTPException) as exc_info:
            await optional_auth(creds)

        # Verify it's a 500 error
        assert exc_info.value.status_code == 500, (
            f"G2 FAIL (RED): Expected HTTPException(500), "
            f"got {exc_info.value.status_code}"
        )
        assert "Authentication system error" in str(exc_info.value.detail), (
            f"G2 FAIL: Expected 'Authentication system error' in detail, "
            f"got '{exc_info.value.detail}'"
        )

        # Verify logger.warning was called with truncated token
        mock_logger.warning.assert_called_once()
        log_msg = mock_logger.warning.call_args[0][0]
        assert "test-tok" in log_msg, (
            f"G2 FAIL: Logger warning should contain truncated token, "
            f"got: {log_msg}"
        )
        assert "optional_auth" in log_msg, (
            f"G2 FAIL: Logger warning should contain 'optional_auth', "
            f"got: {log_msg}"
        )


# =============================================================================
# G14 — optional_auth: Malformed/invalid JWT returns None (not 500)
# =============================================================================

@pytest.mark.asyncio
async def test_optional_auth_malformed_jwt_returns_none(mock_fakeredis):
    """
    G14: Invalid/malformed JWT string → optional_auth() returns None (NOT 500).
    validate_session() treats the token as an opaque Redis key lookup,
    not JWT decoding. A key miss returns None naturally.

    Should PASS before AND after Fix 2 (malformed JWT never reaches except block).
    """
    from src.middleware.authentication import optional_auth

    creds = MagicMock()
    creds.credentials = "this.is.not.a.valid.jwt.its.garbage"

    # Redis has no session for this token — validate_session() returns None
    # via a natural Redis key miss (key doesn't exist), NOT via an exception.
    result = await optional_auth(creds)

    assert result is None, (
        f"G14 FAIL: Expected None for malformed JWT, got {result}"
    )
    # No HTTPException raised — the malformed-JWT path is a normal key miss


# =============================================================================
# G2 variant — Logger assertion in optional_auth
# =============================================================================

@pytest.mark.asyncio
async def test_optional_auth_logs_warning_on_failure():
    """
    G2 (logger variant): Verify logger.warning is called with truncated
    session token (first 8 chars) when validate_session raises.
    """
    from src.middleware.authentication import optional_auth
    from fastapi import HTTPException

    creds = MagicMock()
    creds.credentials = "abcdef123456token"

    with patch("src.middleware.authentication.validate_session",
               side_effect=InternalError("Redis down")), \
         patch("src.middleware.authentication.logger") as mock_logger:

        with pytest.raises(HTTPException):
            await optional_auth(creds)

        mock_logger.warning.assert_called_once()
        args, kwargs = mock_logger.warning.call_args
        log_msg = args[0]
        assert "abcdef12" in log_msg, (
            f"G2 LOG: Expected truncated token 'abcdef12' in warning, "
            f"got: {log_msg}"
        )


# =============================================================================
# G8 — User-type checkers return False on non-matching types (NOT exceptions)
# =============================================================================

@pytest.mark.parametrize("checker_name,user_type_return,expected", [
    ("is_root_user", "admin", False),
    ("is_admin_user", "root", False),
    ("is_consumer_user", "admin", False),
])
def test_user_type_checkers_return_false_on_mismatch(checker_name, user_type_return, expected):
    """
    G8: User-type checkers must return False (NOT raise) when the user type
    does not match. These are legitimate non-match paths, not exceptions.

    G8a: is_root_user(consumer_id) → False
    G8b: is_admin_user(root_id) → False
    G8c: is_consumer_user(admin_id) → False

    Should PASS before AND after Fix 3.
    """
    from src.Util.db.db_enhanced import is_root_user, is_admin_user, is_consumer_user

    checker_map = {
        "is_root_user": is_root_user,
        "is_admin_user": is_admin_user,
        "is_consumer_user": is_consumer_user,
    }
    checker = checker_map[checker_name]

    with patch("src.Util.db.db_enhanced.get_user_type", return_value=user_type_return):
        result = checker("some_user_id")
        assert result is expected, (
            f"G8 FAIL ({checker_name}): Expected {expected}, "
            f"got {result} for get_user_type()='{user_type_return}'"
        )


# =============================================================================
# G9 — check_admin_project_access returns False for no-access admin
# =============================================================================

def test_check_admin_project_access_returns_false_no_access():
    """
    G9: check_admin_project_access() must return False (NOT exception) when an
    admin user legitimately has no access to the requested project.

    Should PASS before AND after Fix 3.
    """
    from src.Util.db.db_enhanced import check_admin_project_access

    with patch("src.Util.db.db_enhanced.is_admin_user", return_value=True), \
         patch("src.Util.db.db_users.check_admin_multi_project_access",
               return_value=False):
        result = check_admin_project_access("admin_id", "project_999")
        assert result is False, (
            f"G9 FAIL: Expected False for admin without project access, "
            f"got {result}"
        )


# =============================================================================
# G10 — verify_admin_access returns 403 for consumer user (true auth denial)
# =============================================================================

@pytest.mark.asyncio
async def test_verify_admin_access_consumer_returns_403():
    """
    G10: Consumer user with valid session → verify_admin_access() must raise
    HTTPException(403) with 'Admin access required'.

    Should PASS before AND after Fix 3 — this is TRUE authorization denial,
    NOT a masked system failure.
    """
    from src.middleware.authentication import verify_admin_access
    from fastapi import HTTPException

    session_data = {
        "user_id": "99",
        "user_hash": "usr-consumer-099",
        "user_type": "consumer",
        "permissions": [],
        "project_id": "1",
        "project_hash": "prj-test-001",
    }

    # Patch is_root_user and is_admin_user at the authentication module's
    # namespace (imported via `from src.Util.db import is_root_user, is_admin_user`)
    with patch("src.middleware.authentication.is_root_user", return_value=False), \
         patch("src.middleware.authentication.is_admin_user", return_value=False):

        with pytest.raises(HTTPException) as exc_info:
            await verify_admin_access(session_data)

        # Verify it's 403 (true auth denial), NOT 500
        assert exc_info.value.status_code == 403, (
            f"G10 FAIL: Expected HTTPException(403) for consumer user, "
            f"got {exc_info.value.status_code}"
        )
        assert "Admin access required" in str(exc_info.value.detail), (
            f"G10 FAIL: Expected 'Admin access required' in detail, "
            f"got '{exc_info.value.detail}'"
        )


# =============================================================================
# G3 — DB failure propagates as 500 through verify_admin_access (NOT 403)
# =============================================================================

@pytest.mark.asyncio
async def test_db_failure_propagates_500_via_admin_checker():
    """
    G3 (RED → GREEN): When get_user_type() raises InternalError inside
    is_root_user(), verify_admin_access() MUST let the exception propagate
    (not catch it and convert to 403).

    Before Fix 3: except Exception in verify_admin_access() catches
    InternalError → HTTPException(403).
    After Fix 3: except (DatabaseError, InternalError): raise → propagates.
    """
    from src.middleware.authentication import verify_admin_access
    from src.Util.error_handler import DatabaseError, InternalError

    session_data = {
        "user_id": "42",
        "user_hash": "usr-test-042",
        "user_type": "consumer",  # Not root/admin — so verify_admin_access proceeds to is_root_user()
        "permissions": [],
        "project_id": "1",
        "project_hash": "prj-test-001",
    }

    # Patch get_user_type at db_enhanced's namespace — is_root_user()
    # calls `get_user_type(user_id)` which was imported from db_users
    # into db_enhanced's module namespace.
    with patch("src.Util.db.db_enhanced.get_user_type",
               side_effect=InternalError("DB connection failed")):
        with pytest.raises(InternalError) as exc_info:
            await verify_admin_access(session_data)

        # Before Fix 3: this would raise HTTPException(403) — test FAILS
        # After Fix 3: InternalError propagates through — test PASSES
        assert "DB connection failed" in str(exc_info.value), (
            f"G3 FAIL: Expected InternalError message to propagate, "
            f"got '{exc_info.value}'"
        )


# =============================================================================
# G4 — enhanced_login admin path DB failure returns 500 (NOT 401)
# =============================================================================

@pytest.mark.asyncio
async def test_enhanced_login_admin_db_failure_returns_500():
    """
    G4 (RED → GREEN): When check_admin_multi_project_access() raises
    DatabaseError inside enhanced_login() admin path, the exception MUST
    propagate (not silently return False → 401).

    Before Fix 3: bare except in check_admin_project_access() catches
    DatabaseError → returns False → enhanced_login returns None → 401.
    After Fix 3: except Exception raises → propagates through
    enhanced_login() → caller sees 500.
    """
    from src.Util.db.db_enhanced import enhanced_login
    from src.Util.error_handler import DatabaseError

    # Build mock user
    user = MagicMock()
    user.id = "42"
    user.user_hash = "usr-admin-042"
    user.username = "admin1"
    user.user_type = "admin"

    project = MagicMock()
    project.id = "1"
    project.project_hash = "prj-test-001"
    project.project_name = "Test Project"

    # Patch the chain: get_user_by_credentials → user, get_user_type → "admin",
    # get_project_by_hash → project, then check_admin_multi_project_access → raise
    with patch("src.Util.db.db_enhanced.get_user_by_credentials",
               return_value=user), \
         patch("src.Util.db.db_enhanced.get_user_type",
               return_value="admin"), \
         patch("src.Util.db.db_enhanced.get_project_by_hash",
               return_value=project), \
         patch("src.Util.db.db_users.check_admin_multi_project_access",
               side_effect=DatabaseError("Global roles DB connection failed")):

        with pytest.raises((DatabaseError, Exception)) as exc_info:
            enhanced_login("admin1", "password123", "prj-test-001")

        # Verify it's a system failure exception (NOT None / 401 behavior)
        # Before Fix 3: enhanced_login() returns None silently
        # After Fix 3: exception propagates
        assert "DB" in str(exc_info.value) or "connection" in str(exc_info.value).lower() or "DatabaseError" in type(exc_info.value).__name__, (
            f"G4 FAIL: Expected DatabaseError to propagate, "
            f"got {type(exc_info.value).__name__}: {exc_info.value}"
        )


# =============================================================================
# G11 — auth_context.py logs on consumer permission failure (with exc_info=True)
# =============================================================================

def test_auth_context_logs_on_permission_failure():
    """
    G11 (RED → GREEN): When get_user_permissions() raises DatabaseError inside
    auth_context.py consumer permission resolution (_resolve_api_key_permissions),
    logger.warning MUST be called with exc_info=True AND permissions = []
    must be returned (graceful degradation preserved).

    Before fix: silent except Exception → permissions = [] (NO log).
    After fix: logger.warning(..., exc_info=True) → permissions = [].
    """
    from src.middleware.auth_context import AuthContextMiddleware

    # Instantiate middleware
    app = MagicMock()
    middleware = AuthContextMiddleware(app)

    # Mock owner as consumer user
    owner = MagicMock()
    owner.id = "99"
    owner.user_hash = "usr-consumer-099"
    owner.username = "consumer1"
    owner.user_type = "consumer"

    project = MagicMock()
    project.id = "1"
    project.project_hash = "prj-test-001"
    project.project_name = "Test Project"

    mock_group = MagicMock()
    mock_group.group_name = "developers"

    # Patch: groups resolve successfully (inline import → patch original module)
    # Permissions fail via get_user_permissions (inline import → patch original module)
    with patch("src.Util.db.db_user_groups.get_user_groups_in_project_by_hash",
               return_value=[mock_group]), \
         patch("src.Util.db.db_global_roles.get_user_permissions",
               side_effect=DatabaseError("Global roles DB connection failed")), \
         patch("src.middleware.auth_context.logger") as mock_logger:

        permissions, groups = middleware._resolve_api_key_permissions(
            owner, project, "99", "1"
        )

        # Graceful degradation: permissions = []
        assert permissions == [], (
            f"G11 FAIL: Expected permissions = [] on DB failure, "
            f"got {permissions}"
        )
        assert groups == ["developers"], (
            f"G11 FAIL: Expected groups to be resolved, got {groups}"
        )

        # Logger.warning MUST have been called with exc_info=True
        mock_logger.warning.assert_called_once()
        _, log_kwargs = mock_logger.warning.call_args
        assert log_kwargs.get("exc_info") is True, (
            "G11 FAIL: logger.warning must be called with exc_info=True, "
            f"got exc_info={log_kwargs.get('exc_info')}"
        )


# =============================================================================
# G12 — db/__init__.py inner try/except removed (dead code cleanup)
# =============================================================================

def test_init_py_inner_try_except_removed():
    """
    G12 (RED → GREEN): When check_user_has_permission() raises DatabaseError
    inside check_user_type_permission(), the inner try/except must be removed
    so the exception propagates to handle_db_operation, which logs and
    returns False via default_return=False.

    Before fix: inner try/except catches silently → handle_db_operation
    never sees the exception → no log.
    After fix: exception propagates to handle_db_operation → logs warning
    with exc_info=True → returns False.
    """
    from src.Util.db import check_user_type_permission

    # Patch: get_user_type returns consumer, check_user_has_permission raises
    # check_user_has_permission is imported inline from db_global_roles
    with patch("src.Util.db.get_user_type", return_value="consumer"), \
         patch("src.Util.db.db_global_roles.check_user_has_permission",
               side_effect=DatabaseError("Global roles DB failed")), \
         patch("src.Util.db_error_wrapper.logger") as mock_wrapper_logger:

        result = check_user_type_permission("99", "read")

        # Must return False (via handle_db_operation default_return=False)
        assert result is False, (
            f"G12 FAIL: Expected False from handle_db_operation, got {result}"
        )

        # handle_db_operation MUST have logged a warning
        # (Before fix: inner try/except caught silently — no log)
        # (After fix: inner try/except removed — handle_db_operation logs)
        mock_wrapper_logger.warning.assert_called_once()
        _, log_kwargs = mock_wrapper_logger.warning.call_args
        assert log_kwargs.get("exc_info") is True, (
            "G12 FAIL: handle_db_operation must log with exc_info=True, "
            f"got exc_info={log_kwargs.get('exc_info')}"
        )
        # Verify the log message references check_user_type_permission
        assert "check_user_type_permission" in mock_wrapper_logger.warning.call_args[0][0], (
            "G12 FAIL: log message must include the error context "
            "'check_user_type_permission'"
        )


# =============================================================================
# G13 — validate_session() consumer permission failure logs exc_info=True
# =============================================================================

def test_validate_session_consumer_permission_failure_logs_exc_info(mock_fakeredis):
    """
    G13 (RED → GREEN): When get_user_permissions() raises DatabaseError in
    validate_session() consumer permission resolution (db_enhanced.py:478-479),
    logger.warning MUST be called with exc_info=True AND the returned
    EnhancedUserLogin must have permissions = [] (graceful degradation preserved).

    Before fix: logger.warning called WITHOUT exc_info=True.
    After fix: exc_info=True added, graceful degradation preserved.
    """
    from src.Util.db.db_enhanced import validate_session
    from src.Util.db_config import redis_client
    import json

    # Create session in Redis with consumer user data (including groups key)
    session_data = {
        "session_id": 99999,
        "user_id": "99",
        "user_hash": "usr-consumer-099",
        "user_type": "consumer",
        "project_id": "1",
        "project_hash": "prj-test-001",
        "project_name": "Test Project",
        "user_group_ids": ["10"],
        "user_group_names": ["developers"],
        "groups": ["developers"],
    }
    redis_client.set("session:g13-token", json.dumps(session_data))

    mock_group = MagicMock()
    mock_group.group_name = "developers"

    project = MagicMock()
    project.id = "1"
    project.project_hash = "prj-test-001"
    project.project_name = "Test Project"

    # Patch chain: groups resolve, permissions fail
    with patch("src.Util.db.db_enhanced.get_user_groups_in_project_by_hash",
               return_value=[mock_group]), \
         patch("src.Util.db.db_enhanced.get_project_by_hash", return_value=project), \
         patch("src.Util.db.db_global_roles.get_user_permissions",
               side_effect=DatabaseError("Global roles DB connection failed")), \
         patch("src.Util.db.db_enhanced.get_user_accessible_projects",
               return_value=[]), \
         patch("src.Util.db.db_enhanced.logger") as mock_logger:

        result = validate_session("g13-token")

        # Must return valid EnhancedUserLogin (graceful degradation)
        assert result is not None, (
            "G13 FAIL: validate_session returned None on consumer permission failure"
        )
        assert result.user_type == "consumer", (
            f"G13 FAIL: Expected consumer user_type, got {result.user_type}"
        )

        # permissions must be gracefully degraded (empty list)
        # EnhancedUserLogin stores permissions as list — check attribute
        perms = getattr(result, "permissions", "NO_PERMS_ATTR")
        assert perms == [] or perms is None, (
            f"G13 FAIL: Expected empty permissions on DB failure, "
            f"got {perms}"
        )

        # Logger.warning MUST have been called
        mock_logger.warning.assert_called_once()
        _, log_kwargs = mock_logger.warning.call_args
        assert log_kwargs.get("exc_info") is True, (
            "G13 FAIL: logger.warning must be called with exc_info=True, "
            f"got exc_info={log_kwargs.get('exc_info')}"
        )
