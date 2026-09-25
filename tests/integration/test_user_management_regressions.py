"""Route-level regressions from verifying docs/USAGE/users against the code.

The routes run over HTTP through the production exception handlers. Identity lookups
come from the admin-scope directory; the functions that used to break (the status
setter, the admin-group helpers, the bulk helpers) run for real over DB doubles.
Unlike the directory's default, root users reach every project here, as
``sp_get_user_accessible_projects`` makes them.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.Util.bulk_operations import BulkOperations
from tests.integration.admin_scope_support import (
    ACCESSIBLE, ADMIN, AUTH, CONSUMER_ADMIN, MEMBER_A, MEMBER_B, PROJECT_A, PROJECT_B, ROOT, USERS,
    directory, router_client, session_for,
)
from tests.support import ALL_DB_CONNECTION_PATCH_LOCATIONS, make_db_connection_mock, make_db_cursor_mock


pytestmark = pytest.mark.usefixtures("patched_db_error_logger")

USERS_ROUTES = "src.routes.users"
USER_TYPES = "src.routes.user_types_auth"
BULK = "src.routes.bulk_operations"
BULK_HELPERS = "src.Util.bulk_operations"


def _accessible(user_id, *_args, **_kwargs):
    if str(user_id) == ROOT.id:
        return [PROJECT_A, PROJECT_B]
    return list(ACCESSIBLE.get(str(user_id), []))


def _root_reaches_every_project():
    return [
        (f"{module}.get_user_accessible_projects", MagicMock(side_effect=_accessible))
        for module in ("src.Util.db", USERS_ROUTES)
    ]


@contextmanager
def _db(cursor):
    conn = make_db_connection_mock(cursor)
    with ExitStack() as stack:
        for location in ALL_DB_CONNECTION_PATCH_LOCATIONS:
            stack.enter_context(patch(location, return_value=conn))
        yield conn


def _procedures(cursor):
    return [call.args[0] for call in cursor.callproc.call_args_list]


def _error(response):
    return response.json()["error"]


# ── 1. PUT /users/{hash}/status ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_status_route_deactivates_through_the_real_status_setter():
    cursor = make_db_cursor_mock(fetchone=(1,))
    revoke = MagicMock()
    extra = [
        ("src.Util.db.db_users.cache_manager", MagicMock()),
        ("src.Util.cache_manager.cache_manager", MagicMock()),
        ("src.Util.db.invalidate_user_sessions", MagicMock(return_value=True)),
        (f"{USERS_ROUTES}.revoke_user_auth_state", revoke),
        (f"{USERS_ROUTES}.log_operation_details", MagicMock()),
    ]
    with _db(cursor), directory(session_for(ADMIN), extra=extra):
        async with router_client(USERS_ROUTES) as client:
            response = await client.put(
                f"/users/{MEMBER_A.user_hash}/status", params={"is_active": "false"}, headers=AUTH,
            )

    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is False
    assert ("sp_set_user_status", [MEMBER_A.id, False]) in [call.args for call in cursor.callproc.call_args_list]
    revoke.assert_called_once_with(MEMBER_A.id, reason="user_deactivated")


# ── 3. Admin-group lookups answer 404, not 500 ───────────────────────────────

@pytest.mark.asyncio
async def test_removing_an_admin_from_a_project_it_does_not_administer_is_404():
    with _db(make_db_cursor_mock(fetchall=[])), directory(session_for(ROOT)):
        async with router_client(USER_TYPES) as client:
            response = await client.delete(
                f"/user-types/admin/{ADMIN.user_hash}/projects/{PROJECT_B.id}", headers=AUTH,
            )

    assert response.status_code == 404, response.text
    assert _error(response)["code"] == "NF_4003"


@pytest.mark.asyncio
async def test_promoting_to_admin_of_a_project_without_admin_group_is_404_and_changes_nothing():
    cursor = make_db_cursor_mock(fetchone=None)
    revoke = MagicMock()
    extra = [("src.Util.db.db_users.cache_manager", MagicMock()), ("src.Util.auth_lifecycle.revoke_user_auth_state", revoke)]
    with _db(cursor), directory(session_for(ROOT), extra=extra):
        async with router_client(USER_TYPES) as client:
            response = await client.put(
                f"/user-types/{MEMBER_A.user_hash}/type",
                data={"user_type": "admin", "assigned_project_id": PROJECT_A.id},
                headers=AUTH,
            )

    assert response.status_code == 404, response.text
    assert _error(response)["code"] == "NF_4003"
    assert "sp_update_user_type" not in _procedures(cursor)
    revoke.assert_not_called()


# ── 5. Root users are outside every admin's scope ────────────────────────────

@pytest.mark.asyncio
async def test_admin_cannot_read_rename_or_deactivate_a_root_user():
    update_user = MagicMock()
    set_status = MagicMock(return_value=True)
    extra = [
        *_root_reaches_every_project(),
        (f"{USERS_ROUTES}.update_user", update_user),
        (f"{USERS_ROUTES}.set_user_active_status", set_status),
        (f"{USERS_ROUTES}.log_operation_details", MagicMock()),
    ]
    with directory(session_for(ADMIN), extra=extra):
        async with router_client(USERS_ROUTES) as client:
            read = await client.get(f"/users/{ROOT.user_hash}", headers=AUTH)
            rename = await client.put(f"/users/{ROOT.user_hash}", data={"username": "owned"}, headers=AUTH)
            deactivate = await client.put(
                f"/users/{ROOT.user_hash}/status", params={"is_active": "false"}, headers=AUTH,
            )

    assert [read.status_code, rename.status_code, deactivate.status_code] == [403, 403, 403]
    update_user.assert_not_called()
    set_status.assert_not_called()


@pytest.mark.asyncio
async def test_admin_user_list_and_search_leave_out_root_users():
    rows = [
        {"id": user.id, "user_hash": user.user_hash, "username": user.username, "email": user.email,
         "user_type": user.user_type, "created_at": None, "last_login": None, "is_active": True,
         "groups_json": None, "projects_json": None}
        for user in (ROOT, ADMIN, MEMBER_A, MEMBER_B)
    ]
    extra = [
        *_root_reaches_every_project(),
        (f"{USERS_ROUTES}.list_users_with_access", MagicMock(return_value=rows)),
        (f"{USERS_ROUTES}.count_users", MagicMock(return_value=len(rows))),
        (f"{USERS_ROUTES}.get_user_type_info", MagicMock(return_value={})),
        ("src.Util.db.search_users", MagicMock(return_value=[ROOT, ADMIN, MEMBER_A, MEMBER_B])),
    ]
    with directory(session_for(ADMIN), extra=extra):
        async with router_client(USERS_ROUTES) as client:
            listed = await client.get("/users/list", headers=AUTH)
            found = await client.get("/users/search/query", params={"q": "u"}, headers=AUTH)

    assert listed.status_code == 200, listed.text
    assert found.status_code == 200, found.text
    assert {user["user_hash"] for user in listed.json()["users"]} == {ADMIN.user_hash, MEMBER_A.user_hash}
    assert {user["user_hash"] for user in found.json()["users"]} == {ADMIN.user_hash, MEMBER_A.user_hash}


@contextmanager
def _bulk(caller, *, revoke=None):
    seams = SimpleNamespace(
        set_status=MagicMock(return_value=True),
        delete_user=MagicMock(return_value=True),
        revoke=revoke or MagicMock(),
    )
    lookup = MagicMock(side_effect=lambda user_hash, *a, **k: USERS.get(user_hash))
    extra = [
        *_root_reaches_every_project(),
        (f"{BULK}.validate_session", MagicMock(return_value=session_for(caller))),
        (f"{BULK}.get_user_by_hash", lookup),
        (f"{BULK}.ActivityLogger", MagicMock()),
        (f"{BULK}.revoke_user_auth_state", MagicMock()),
        (f"{BULK_HELPERS}.get_connection", MagicMock(return_value=make_db_connection_mock())),
        (f"{BULK_HELPERS}.get_user_by_hash", lookup),
        (f"{BULK_HELPERS}.delete_user", seams.delete_user),
        (f"{BULK_HELPERS}.log_activity", MagicMock()),
        ("src.Util.auth_lifecycle.revoke_user_auth_state", seams.revoke),
    ]
    with directory(session_for(caller), extra=extra), \
         patch.object(BulkOperations, "_update_user_status", seams.set_status):
        yield seams


def _results(response):
    return {item["user_hash"]: item for item in response.json()["results"]}


TARGETS = [ROOT.user_hash, ADMIN.user_hash, MEMBER_B.user_hash, MEMBER_A.user_hash]


@pytest.mark.asyncio
async def test_admin_bulk_deactivation_skips_root_self_and_foreign_users():
    with _bulk(ADMIN) as seams:
        async with router_client(BULK) as client:
            response = await client.post(
                "/admin/users/bulk-update", data={"user_hashes": TARGETS, "is_active": "false"}, headers=AUTH,
            )

    assert response.status_code == 200, response.text
    results = _results(response)
    assert results[MEMBER_A.user_hash]["success"] is True
    assert results[ROOT.user_hash]["error"] == "Root users are outside your administrative scope"
    assert results[ADMIN.user_hash]["error"] == "Cannot deactivate your own account"
    assert results[MEMBER_B.user_hash]["error"] == "User not in your administrative scope"
    seams.set_status.assert_called_once_with(MEMBER_A.id, False)


@pytest.mark.asyncio
async def test_consumer_holding_manage_users_cannot_run_bulk_user_operations():
    with _bulk(CONSUMER_ADMIN) as seams:
        async with router_client(BULK) as client:
            updated = await client.post(
                "/admin/users/bulk-update", data={"user_hashes": [MEMBER_A.user_hash], "is_active": "false"},
                headers=AUTH,
            )
            deleted = await client.post(
                "/admin/users/bulk-delete", data={"user_hashes": [MEMBER_A.user_hash], "confirm_deletion": "true"},
                headers=AUTH,
            )

    assert [updated.status_code, deleted.status_code] == [403, 403]
    seams.set_status.assert_not_called()
    seams.delete_user.assert_not_called()


@pytest.mark.asyncio
async def test_admin_bulk_delete_is_scoped_revokes_sessions_and_reports_revocation_failures():
    with _bulk(ADMIN, revoke=MagicMock(side_effect=RuntimeError("redis down"))) as seams:
        async with router_client(BULK) as client:
            response = await client.post(
                "/admin/users/bulk-delete", data={"user_hashes": TARGETS, "confirm_deletion": "true"}, headers=AUTH,
            )

    assert response.status_code == 200, response.text
    body = response.json()
    results = _results(response)
    assert results[MEMBER_A.user_hash]["success"] is True
    assert results[ROOT.user_hash]["error"] == "Cannot bulk delete root users"
    assert results[ADMIN.user_hash]["error"] == "Cannot delete your own account"
    assert results[MEMBER_B.user_hash]["error"] == "User not in your administrative scope"
    assert body["summary"]["protected_count"] == 1
    seams.delete_user.assert_called_once_with(MEMBER_A.id, deleted_by=ADMIN.id)
    seams.revoke.assert_called_once_with(MEMBER_A.id, reason="bulk_user_deleted")
    assert body["warnings"] == [{"user": MEMBER_A.user_hash, "warning": "Deleted, but session revocation failed"}]


# ── 6. Response fields that used to be dropped ───────────────────────────────

@pytest.mark.asyncio
async def test_profile_projects_carry_the_callers_permissions():
    extra = [
        (f"{USERS_ROUTES}.get_user_type_info", MagicMock(return_value={"user_type": "consumer"})),
        (f"{USERS_ROUTES}.get_user_groups_for_user", MagicMock(return_value=[])),
        (f"{USERS_ROUTES}.get_user_effective_permissions", MagicMock(return_value=["read", "write"])),
    ]
    with directory(session_for(MEMBER_A), extra=extra):
        async with router_client(USERS_ROUTES) as client:
            response = await client.get("/users/profile", headers=AUTH)

    assert response.status_code == 200, response.text
    assert response.json()["projects"] == [{
        "project_hash": PROJECT_A.project_hash, "project_name": PROJECT_A.project_name,
        "project_description": PROJECT_A.project_description, "created_at": None, "updated_at": None,
        "permissions": ["read", "write"],
    }]


def _type_info(user_id):
    user = {u.id: u for u in USERS.values()}[user_id]
    return {"user_id": user.id, "user_hash": user.user_hash, "username": user.username,
            "user_type": user.user_type, "capabilities": []}


@pytest.mark.asyncio
async def test_user_type_routes_report_admin_project_assignments():
    extra = [
        (f"{USER_TYPES}.get_user_type_info", MagicMock(side_effect=_type_info)),
        (f"{USER_TYPES}.update_user_type", MagicMock(return_value=True)),
        (f"{USER_TYPES}.list_users", MagicMock(return_value=[ADMIN])),
        (f"{USER_TYPES}.count_users", MagicMock(return_value=1)),
    ]
    with directory(session_for(ROOT), extra=extra):
        async with router_client(USER_TYPES) as client:
            info = await client.get(f"/user-types/{ADMIN.user_hash}/info", headers=AUTH)
            retyped = await client.put(
                f"/user-types/{ADMIN.user_hash}/type",
                data={"user_type": "admin", "assigned_project_id": PROJECT_A.id}, headers=AUTH,
            )
            listed = await client.get("/user-types/users/admin", headers=AUTH)

    for response in (info, retyped, listed):
        assert response.status_code == 200, response.text
    for body in (info.json(), retyped.json()):
        assert body["user_type_info"]["total_assigned_projects"] == 1
        assert body["user_type_info"]["assigned_project_id"] == PROJECT_A.id
    assert listed.json()["users"][0]["assigned_project"] == {
        "project_id": PROJECT_A.id, "project_hash": PROJECT_A.project_hash, "project_name": PROJECT_A.project_name,
    }


@pytest.mark.asyncio
async def test_create_admin_reports_projects_skipped_for_lacking_an_admin_group():
    created = SimpleNamespace(id="u-new", user_hash="uh-new", username="newadmin", email=None, created_at=None)
    assignments = [{"project_id": PROJECT_A.id, "project_hash": PROJECT_A.project_hash,
                    "project_name": PROJECT_A.project_name}]
    extra = [
        (f"{USER_TYPES}.create_admin_user", MagicMock(return_value=created)),
        (f"{USER_TYPES}.get_admin_project_assignments_with_details", MagicMock(return_value=assignments)),
    ]
    with directory(session_for(ROOT), extra=extra):
        async with router_client(USER_TYPES) as client:
            response = await client.post(
                "/user-types/admin",
                data={"username": "newadmin", "password": "vX9#qLm2$Tr8!pZw-long",
                      "assigned_project_ids": [PROJECT_A.id, PROJECT_B.id]},
                headers=AUTH,
            )

    assert response.status_code == 200, response.text
    body = response.json()
    user = body["user"]
    assert user["assigned_project_ids"] == [PROJECT_A.id]
    assert [p["project_id"] for p in user["assigned_projects"]] == [PROJECT_A.id]
    assert user["skipped_projects"] == [{
        "project_id": PROJECT_B.id, "project_hash": PROJECT_B.project_hash,
        "project_name": PROJECT_B.project_name, "reason": "no_admin_group",
    }]
    assert user["primary_project_id"] == PROJECT_A.id
    assert "1 project(s)" in body["message"]
