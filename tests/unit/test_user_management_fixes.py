"""Regressions from verifying docs/USAGE/users against the code.

Each test runs the real function under test; only the DB cursor, Redis and the
auth-lifecycle boundary are stubbed.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import fakeredis
import pytest

from src.Util.Models import ProfileProjectInfo, UserProfileResponse, UserTypeInfo
from src.Util.admin_scope import AdminScope, user_in_scope
from src.Util.bulk_operations import _target_denial
from src.Util.cache_manager import CacheManager
from src.Util.db import db_users
from src.Util.error_handler import ErrorCode, NotFoundError, ValidationError
from tests.support import make_db_connection_mock, make_db_cursor_mock


DB_USERS = "src.Util.db.db_users"


@contextmanager
def _db_users(cursor):
    """Point db_users at ``cursor`` and silence its cache and auth-lifecycle side effects."""
    conn = make_db_connection_mock(cursor)
    with patch(f"{DB_USERS}.get_connection", return_value=conn), \
         patch(f"{DB_USERS}.cache_manager") as cache, \
         patch("src.Util.auth_lifecycle.revoke_user_auth_state") as revoke:
        yield SimpleNamespace(conn=conn, cache=cache, revoke=revoke)


def _procedures(cursor) -> list[str]:
    return [call.args[0] for call in cursor.callproc.call_args_list]


# ── 1. PUT /users/{hash}/status: a status setter that exists ─────────────────

def test_set_user_active_status_calls_the_status_procedure_and_commits():
    cursor = make_db_cursor_mock(fetchone=(1,))
    with _db_users(cursor) as seams:
        assert db_users.set_user_active_status("u-1", False) is True

    cursor.callproc.assert_called_once_with("sp_set_user_status", ["u-1", False])
    seams.conn.commit.assert_called_once()
    seams.cache.invalidate_user_cache.assert_called_once_with("u-1")


def test_set_user_active_status_reports_an_unknown_user():
    cursor = make_db_cursor_mock(fetchone=(0,))
    with _db_users(cursor) as seams:
        assert db_users.set_user_active_status("missing", True) is False

    seams.conn.commit.assert_not_called()


# ── 3. NotFoundError with a plain code string must not become a 500 ──────────

def test_app_exception_accepts_a_code_string():
    error = NotFoundError(message="gone", error_code="NF_4003")

    assert error.error_code is ErrorCode.GROUP_NOT_FOUND
    assert error.to_dict()["error"]["code"] == "NF_4003"


def test_app_exception_with_an_unknown_code_string_still_serialises():
    error = NotFoundError(message="gone", error_code="NOT_A_CODE")

    assert error.to_dict()["error"]["code"] == ErrorCode.INTERNAL_ERROR.value


def test_remove_admin_from_unassigned_project_returns_false():
    cursor = make_db_cursor_mock(fetchone=(0,))
    with _db_users(cursor):
        assert db_users.remove_admin_from_project("u-admin", "prj-B") is False
    assert _procedures(cursor) == ["sp_remove_admin_from_project"]


def test_add_admin_to_project_for_a_consumer_is_a_validation_error():
    with _db_users(make_db_cursor_mock()), \
         patch(f"{DB_USERS}.get_user_type", return_value="consumer"), \
         pytest.raises(ValidationError) as raised:
        db_users.add_admin_to_project("u-1", "prj-A")

    assert raised.value.error_code is ErrorCode.INVALID_INPUT


def test_promoting_to_admin_of_a_project_without_admin_group_changes_nothing():
    cursor = make_db_cursor_mock(fetchone=None)
    with _db_users(cursor) as seams, \
         patch(f"{DB_USERS}.get_user_type", return_value="consumer"), \
         pytest.raises(NotFoundError) as raised:
        db_users.update_user_type("u-1", "admin", project_ids=["prj-no-admin-group"])

    assert raised.value.error_code is ErrorCode.GROUP_NOT_FOUND
    assert raised.value.details == {"project_id": "prj-no-admin-group"}
    assert _procedures(cursor) == ["sp_find_admin_group_for_project"]
    seams.conn.commit.assert_not_called()
    seams.revoke.assert_not_called()


# ── 4. Profile/password changes keep sessions; type changes sign out ─────────

def _seed(fake, key, payload):
    fake.set(key, json.dumps(payload))


def test_invalidate_user_cache_keeps_access_sessions():
    fake = fakeredis.FakeStrictRedis()
    cache = CacheManager()
    cache.redis = fake
    _seed(fake, "session:jti-own", {"user_id": "u-1"})
    _seed(fake, "session_full:jti-own", {"user_id": "u-1"})
    _seed(fake, "session:jti-other", {"user_id": "u-2"})
    _seed(fake, "session_full:jti-other", {"user_id": "u-2"})
    fake.set("access:u-1_prj-A", "1")

    assert cache.invalidate_user_cache("u-1") is True

    assert fake.exists("session:jti-own")  # still signed in
    assert not fake.exists("session_full:jti-own")  # rebuilt from fresh data on next validate
    assert not fake.exists("access:u-1_prj-A")
    assert fake.exists("session:jti-other") and fake.exists("session_full:jti-other")


def test_invalidate_user_sessions_still_drops_access_sessions():
    fake = fakeredis.FakeStrictRedis()
    cache = CacheManager()
    cache.redis = fake
    _seed(fake, "session:jti-own", {"user_id": "u-1"})
    _seed(fake, "session_full:jti-own", {"user_id": "u-1"})

    assert cache.invalidate_user_sessions("u-1") == 2
    assert not fake.exists("session:jti-own")


def test_password_change_keeps_the_callers_session_and_revokes_the_others():
    """change_user_password drops the user's cache, then the route revokes all but the current session."""
    from src.Util.auth_lifecycle import issue_project_token_pair, revoke_user_auth_state_except_current

    fake = fakeredis.FakeStrictRedis()
    user = {"id": "u-1", "user_hash": "uh-1", "username": "alice", "user_type": "consumer"}
    project = {"id": "prj-A", "project_hash": "ph-A", "project_name": "Project A"}
    cache = CacheManager()
    cache.redis = fake
    with patch("src.Util.auth_lifecycle.redis_client", fake):
        current = issue_project_token_pair(user=user, project=project, groups=["readers"], permissions=[])
        other = issue_project_token_pair(user=user, project=project, groups=["readers"], permissions=[])

        cache.invalidate_user_cache("u-1")  # what change_user_password does after the update
        revoke_user_auth_state_except_current(
            "u-1",
            current_access_jti=current.access_claims["jti"],
            current_family_id=current.access_claims["family_id"],
            reason="password_change",
        )

    assert fake.exists(f"session:{current.access_claims['jti']}")
    assert not fake.exists(f"session:{other.access_claims['jti']}")


def test_profile_update_does_not_revoke_sessions():
    cursor = make_db_cursor_mock(fetchone=(1,))
    with _db_users(cursor) as seams, patch(f"{DB_USERS}.get_user_by_id", return_value=MagicMock()):
        db_users.update_user("u-1", username="renamed")

    seams.revoke.assert_not_called()
    seams.cache.invalidate_user_cache.assert_called_once_with("u-1")


@pytest.mark.parametrize("previous, revoked", [("consumer", True), ("admin", False)])
def test_update_user_signs_out_only_when_the_type_changes(previous, revoked):
    cursor = make_db_cursor_mock(fetchone=(1,))
    with _db_users(cursor) as seams, \
         patch(f"{DB_USERS}.get_user_type", return_value=previous), \
         patch(f"{DB_USERS}.get_user_by_id", return_value=MagicMock()):
        db_users.update_user("u-1", user_type="admin")

    if revoked:
        seams.revoke.assert_called_once_with("u-1", reason="user_type_changed")
    else:
        seams.revoke.assert_not_called()


def test_update_user_type_signs_the_user_out():
    cursor = make_db_cursor_mock()
    cursor.fetchone.side_effect = [("grp-admin-A",), ("grp-admin-A",), (0,)]
    with _db_users(cursor) as seams, \
         patch(f"{DB_USERS}.get_user_type", side_effect=["consumer", "admin"]), \
         patch("src.Util.db.db_user_groups.assign_user_to_group", return_value={"id": "m-1"}):
        assert db_users.update_user_type("u-1", "admin", project_ids=["prj-A"]) is True

    assert "sp_update_user_type" in _procedures(cursor)
    seams.revoke.assert_called_once_with("u-1", reason="user_type_changed")


# ── 5. Root users are outside every admin's scope ────────────────────────────

ADMIN_SCOPE = AdminScope(user_id="u-admin", user_type="admin", project_ids=frozenset({"prj-A"}))
ROOT_SCOPE = AdminScope(user_id="u-root", user_type="root")


def _reaches(*project_ids):
    return [SimpleNamespace(id=project_id) for project_id in project_ids]


def test_admin_scope_excludes_root_users_even_though_they_reach_every_project():
    with patch("src.Util.db.get_user_type", return_value="root"), \
         patch("src.Util.db.get_user_accessible_projects", return_value=_reaches("prj-A", "prj-B")):
        assert user_in_scope(ADMIN_SCOPE, "u-root") is False
        assert user_in_scope(ADMIN_SCOPE, "u-root", "root") is False
        assert user_in_scope(ROOT_SCOPE, "u-other-root", "root") is True


def test_admin_scope_still_covers_non_root_users_of_its_projects():
    with patch("src.Util.db.get_user_accessible_projects", return_value=_reaches("prj-A")):
        assert user_in_scope(ADMIN_SCOPE, "u-member", "consumer") is True
        assert user_in_scope(ADMIN_SCOPE, "u-other-admin", "admin") is True
    with patch("src.Util.db.get_user_accessible_projects", return_value=_reaches("prj-B")):
        assert user_in_scope(ADMIN_SCOPE, "u-foreign", "consumer") is False


def _user(user_id, user_type="consumer"):
    return SimpleNamespace(id=user_id, user_type=user_type)


def test_bulk_target_denials():
    with patch("src.Util.db.get_user_accessible_projects", side_effect=lambda user_id: (
        _reaches("prj-A") if user_id == "u-member" else _reaches("prj-B")
    )):
        assert _target_denial(ADMIN_SCOPE, "u-admin", _user("u-root", "root"), removal="deactivate")
        assert _target_denial(ADMIN_SCOPE, "u-admin", _user("u-admin", "admin"), removal="deactivate") == (
            "Cannot deactivate your own account"
        )
        assert _target_denial(ADMIN_SCOPE, "u-admin", _user("u-foreign"), removal=None) == (
            "User not in your administrative scope"
        )
        assert _target_denial(ADMIN_SCOPE, "u-admin", _user("u-member"), removal="delete") is None
        assert _target_denial(ROOT_SCOPE, "u-root", _user("u-root", "root"), removal="delete") == (
            "Cannot delete your own account"
        )
        assert _target_denial(ROOT_SCOPE, "u-root", _user("u-other-root", "root"), removal="deactivate") is None
        assert _target_denial(None, "u-admin", _user("u-root", "root"), removal="delete") is None


# ── 6. Response fields that used to be dropped ───────────────────────────────

def test_profile_projects_keep_permissions():
    response = UserProfileResponse(
        success=True,
        projects=[ProfileProjectInfo(project_hash="ph-A", project_name="A", permissions=["read", "write"])],
    )

    assert response.model_dump()["projects"][0]["permissions"] == ["read", "write"]


def test_user_type_info_keeps_total_assigned_projects():
    info = UserTypeInfo(
        user_id="u-admin", user_hash="uh-admin", username="admin", user_type="admin",
        assigned_projects=[{"project_id": "prj-A"}], total_assigned_projects=1,
    )

    assert info.model_dump()["total_assigned_projects"] == 1
