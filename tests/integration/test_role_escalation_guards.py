"""A `manage_roles` holder cannot mint the permission names other routers trust.

Session permissions come from the caller's global role, and routers grant power on names
such as `admin`, `global_admin` or `manage_users` (bulk operations, project and user-group
admin, `verify_root_access`). Without a guard, a consumer with `manage_roles` could create a
permission named `admin`, put it in a group, link the group to a role and give itself that
role. Those names are now reserved: only root may create them, attach them to a group, link
such a group to a role, assign or remove a role granting them, or edit/delete the objects
carrying them. Non-root callers also cannot change their own role.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tests.integration.admin_scope_support import ADMIN, AUTH, CONSUMER_ADMIN, MEMBER_A, MEMBER_B, ROOT, USERS, router_client


pytestmark = pytest.mark.usefixtures("patched_db_error_logger")

ROLES = "src.routes.global_roles"


class FakeRoleDB:
    def __init__(self):
        self.permissions = {
            "PH-ADMIN": {"id": "perm-admin", "permission_hash": "PH-ADMIN", "permission_name": "admin"},
            "PH-READ": {"id": "perm-read", "permission_hash": "PH-READ", "permission_name": "read_reports"},
        }
        self.groups = {
            "GH-PRIV": {"id": "pg-priv", "group_hash": "GH-PRIV", "group_name": "privileged", "_perms": ["perm-admin"]},
            "GH-PLAIN": {"id": "pg-plain", "group_hash": "GH-PLAIN", "group_name": "plain", "_perms": ["perm-read"]},
        }
        self.roles = {
            "RH-PRIV": {"id": "role-priv", "role_hash": "RH-PRIV", "role_name": "superusers", "_groups": ["pg-priv"]},
            "RH-PLAIN": {"id": "role-plain", "role_hash": "RH-PLAIN", "role_name": "readers", "_groups": ["pg-plain"]},
        }
        self.user_roles = {MEMBER_A.id: "role-priv"}
        self.writes = []
        for name in (
            "assign_permission_to_group", "remove_permission_from_group", "assign_permission_group_to_role",
            "remove_permission_group_from_role", "assign_role_to_user", "remove_role_from_user", "update_permission",
            "delete_permission", "update_permission_group", "delete_permission_group", "update_role", "delete_role",
        ):
            setattr(self, name, self._writer(name))

    def _writer(self, name):
        def write(*args, **kwargs):
            self.writes.append(name)
            return True
        return write

    def check_user_has_permission(self, user_id, permission_name):
        return user_id == CONSUMER_ADMIN.id and permission_name == "manage_roles"

    def create_permission(self, **kwargs):
        self.writes.append("create_permission")
        return {"permission_hash": "PH-NEW", **kwargs}

    def get_permission_by_hash(self, permission_hash):
        return self.permissions.get(permission_hash)

    def get_permission_group_by_hash(self, group_hash):
        return self.groups.get(group_hash)

    def get_role_by_hash(self, role_hash):
        return self.roles.get(role_hash)

    def get_permission_group_permissions(self, permission_group_id):
        group = next(g for g in self.groups.values() if g["id"] == permission_group_id)
        return [p for p in self.permissions.values() if p["id"] in group["_perms"]]

    def get_role_permission_groups(self, role_id):
        role = next(r for r in self.roles.values() if r["id"] == role_id)
        return [g for g in self.groups.values() if g["id"] in role["_groups"]]

    def get_user_role(self, user_id):
        role_id = self.user_roles.get(user_id)
        return next((r for r in self.roles.values() if r["id"] == role_id), None)


@contextmanager
def _as(caller, role_db):
    session = SimpleNamespace(user_id=caller.id, user_hash=caller.user_hash, permissions=["manage_roles"])
    with ExitStack() as stack:
        stack.enter_context(patch(f"{ROLES}.validate_session", return_value=session))
        stack.enter_context(patch(f"{ROLES}.get_user_by_hash", side_effect=lambda user_hash, **kw: USERS.get(user_hash)))
        stack.enter_context(patch(f"{ROLES}.global_roles", role_db))
        stack.enter_context(patch("src.Util.db.get_user_type", side_effect=lambda user_id: next(
            (u.user_type for u in USERS.values() if u.id == user_id), None)))
        stack.enter_context(patch(f"{ROLES}.is_root_user", side_effect=lambda user_id: user_id == ROOT.id, create=True))
        yield


async def _send(caller, method, path, **kwargs):
    role_db = FakeRoleDB()
    with _as(caller, role_db):
        async with router_client(ROLES) as client:
            response = await getattr(client, method)(path, headers=AUTH, **kwargs)
    return response, role_db


NON_ROOT = [CONSUMER_ADMIN, ADMIN]
NON_ROOT_IDS = ["consumer-with-manage_roles", "admin-user"]


def _permission_form(name):
    return {"data": {"permission_name": name, "permission_display_name": name}}


@pytest.mark.asyncio
@pytest.mark.parametrize("caller", NON_ROOT, ids=NON_ROOT_IDS)
@pytest.mark.parametrize("name", ["admin", "global_admin", "manage_users", "Manage_Roles", " ádmin ", "ＡＤＭＩＮ", "manage_billing"])
async def test_non_root_cannot_create_a_reserved_permission(caller, name):
    response, role_db = await _send(caller, "post", "/roles/permissions", **_permission_form(name))

    assert response.status_code == 403, response.text
    assert "create_permission" not in role_db.writes


@pytest.mark.asyncio
async def test_non_root_can_still_create_ordinary_permissions_and_root_reserved_ones():
    ordinary, _ = await _send(CONSUMER_ADMIN, "post", "/roles/permissions", **_permission_form("read_reports_v2"))
    reserved, _ = await _send(ROOT, "post", "/roles/permissions", **_permission_form("manage_users"))

    assert ordinary.status_code == 201, ordinary.text
    assert reserved.status_code == 201, reserved.text


@pytest.mark.asyncio
@pytest.mark.parametrize("caller", NON_ROOT, ids=NON_ROOT_IDS)
@pytest.mark.parametrize(
    "method, path, writer",
    [
        ("post", "/roles/permission-groups/GH-PLAIN/permissions/PH-ADMIN", "assign_permission_to_group"),
        ("delete", "/roles/permission-groups/GH-PRIV/permissions/PH-ADMIN", "remove_permission_from_group"),
        ("post", "/roles/RH-PLAIN/permission-groups/GH-PRIV", "assign_permission_group_to_role"),
        ("delete", "/roles/RH-PRIV/permission-groups/GH-PRIV", "remove_permission_group_from_role"),
        ("put", f"/roles/users/{MEMBER_A.user_hash}/role", "assign_role_to_user"),
        ("delete", f"/roles/users/{MEMBER_A.user_hash}/role", "remove_role_from_user"),
        ("put", "/roles/permissions/PH-ADMIN", "update_permission"),
        ("delete", "/roles/permissions/PH-ADMIN", "delete_permission"),
        ("put", "/roles/permission-groups/GH-PRIV", "update_permission_group"),
        ("delete", "/roles/permission-groups/GH-PRIV", "delete_permission_group"),
        ("put", "/roles/RH-PRIV", "update_role"),
        ("delete", "/roles/RH-PRIV", "delete_role"),
    ],
)
async def test_non_root_cannot_move_or_alter_reserved_permissions(caller, method, path, writer):
    kwargs = {"data": {"role_hash": "RH-PRIV", "permission_display_name": "x", "group_display_name": "x",
                       "role_display_name": "x"}} if method == "put" else {}
    response, role_db = await _send(caller, method, path, **kwargs)

    assert response.status_code == 403, f"{method.upper()} {path}: {response.status_code} {response.text}"
    assert writer not in role_db.writes


@pytest.mark.asyncio
@pytest.mark.parametrize("caller", NON_ROOT, ids=NON_ROOT_IDS)
@pytest.mark.parametrize("method", ["put", "delete"])
async def test_non_root_cannot_change_its_own_role(caller, method):
    kwargs = {"data": {"role_hash": "RH-PLAIN"}} if method == "put" else {}
    response, role_db = await _send(caller, method, f"/roles/users/{caller.user_hash}/role", **kwargs)

    assert response.status_code == 403, response.text
    assert not {"assign_role_to_user", "remove_role_from_user"} & set(role_db.writes)


@pytest.mark.asyncio
async def test_ordinary_role_work_is_unchanged_for_manage_roles_holders():
    linked, _ = await _send(CONSUMER_ADMIN, "post", "/roles/permission-groups/GH-PLAIN/permissions/PH-READ")
    grouped, _ = await _send(CONSUMER_ADMIN, "post", "/roles/RH-PLAIN/permission-groups/GH-PLAIN")
    assigned, _ = await _send(CONSUMER_ADMIN, "put", f"/roles/users/{ADMIN.user_hash}/role", data={"role_hash": "RH-PLAIN"})

    assert linked.status_code == 200, linked.text
    assert grouped.status_code == 200, grouped.text
    assert assigned.status_code == 200, assigned.text


@pytest.mark.asyncio
async def test_root_manages_reserved_permissions_and_roles():
    linked, _ = await _send(ROOT, "post", "/roles/permission-groups/GH-PLAIN/permissions/PH-ADMIN")
    assigned, _ = await _send(ROOT, "put", f"/roles/users/{ROOT.user_hash}/role", data={"role_hash": "RH-PRIV"})

    assert linked.status_code == 200, linked.text
    assert assigned.status_code == 200, assigned.text


def test_reserved_names_cover_every_permission_name_routers_trust():
    """Every name a router or middleware checks in session permissions must be reserved."""
    import re
    from pathlib import Path

    from src.Util.admin_scope import RESERVED_PERMISSION_NAMES

    trusted = set()
    for source in list(Path("src/routes").glob("*.py")) + [Path("src/middleware/authentication.py"), Path("src/Util/db/db_project_groups.py")]:
        text = source.read_text()
        trusted.update(re.findall(r"['\"]([a-z_]+)['\"]\s+(?:not\s+)?in\s+(?:user_permissions|permissions|perms|session_permissions)\b", text))
    assert trusted, "the scan found no permission checks; update the pattern"
    assert trusted <= set(RESERVED_PERMISSION_NAMES), sorted(trusted - set(RESERVED_PERMISSION_NAMES))


# ── bulk role assignment (src/routes/bulk_operations.py) ──────────────────────

BULK = "src.routes.bulk_operations"


async def _bulk_assign(caller, user_hashes, role_names):
    role_db = FakeRoleDB()
    role_db.get_role_by_name = lambda name: next((r for r in role_db.roles.values() if r["role_name"] == name), None)
    assign = MagicMock(return_value={"success_count": len(user_hashes), "error_count": 0, "results": [], "errors": []})
    session = SimpleNamespace(user_id=caller.id, user_hash=caller.user_hash, permissions=["admin"])
    project = SimpleNamespace(id="prj-A", project_hash="ph-A", project_name="Project A")
    with ExitStack() as stack:
        stack.enter_context(patch(f"{BULK}.validate_session", return_value=session))
        stack.enter_context(patch(f"{BULK}.get_user_by_hash", side_effect=lambda user_hash, **kw: USERS.get(user_hash)))
        stack.enter_context(patch(f"{BULK}.is_root_user", side_effect=lambda user_id: user_id == ROOT.id))
        stack.enter_context(patch(f"{BULK}.db_global_roles", role_db))
        stack.enter_context(patch(f"{BULK}.bulk_assign_roles", assign))
        stack.enter_context(patch(f"{BULK}.ActivityLogger", MagicMock()))
        stack.enter_context(patch("src.Util.db.get_project_by_hash", return_value=project))
        async with router_client(BULK) as client:
            response = await client.post(
                "/admin/projects/ph-A/bulk-assign-roles", headers=AUTH,
                data={"user_hashes": user_hashes, "role_names": role_names},
            )
    return response, assign


@pytest.mark.asyncio
async def test_bulk_role_assignment_cannot_grant_reserved_permissions_or_target_the_caller():
    privileged, privileged_assign = await _bulk_assign(ADMIN, [MEMBER_B.user_hash], ["superusers"])
    own, own_assign = await _bulk_assign(ADMIN, [ADMIN.user_hash, MEMBER_B.user_hash], ["readers"])
    ordinary, ordinary_assign = await _bulk_assign(ADMIN, [MEMBER_B.user_hash], ["readers"])
    by_root, root_assign = await _bulk_assign(ROOT, [ROOT.user_hash], ["superusers"])

    assert privileged.status_code == 403, privileged.text
    privileged_assign.assert_not_called()
    assert own.status_code == 403, own.text
    own_assign.assert_not_called()
    assert ordinary.status_code == 200, ordinary.text
    ordinary_assign.assert_called_once()
    assert by_root.status_code == 200, by_root.text
    root_assign.assert_called_once()


@pytest.mark.asyncio
async def test_bulk_role_assignment_cannot_replace_a_role_granting_reserved_permissions():
    """Like PUT /roles/users/{user_hash}/role: the user's current role is checked too."""
    demote, demote_assign = await _bulk_assign(ADMIN, [MEMBER_B.user_hash, MEMBER_A.user_hash], ["readers"])
    by_root, root_assign = await _bulk_assign(ROOT, [MEMBER_A.user_hash], ["readers"])

    assert demote.status_code == 403, demote.text
    assert demote.json()["error"]["details"]["context"]["user_hashes"] == [MEMBER_A.user_hash]
    demote_assign.assert_not_called()
    assert by_root.status_code == 200, by_root.text
    root_assign.assert_called_once()


# ── /permissions assignments (src/routes/permission_assignments.py) ───────────

PERMS = "src.routes.permission_assignments"
TEAM = SimpleNamespace(id="ug-team", group_hash="UGH-TEAM", group_name="team")
ASSIGNMENT_WRITERS = (
    "assign_permission_group_to_user_group", "remove_permission_group_from_user_group",
    "assign_permission_group_to_user", "remove_permission_group_from_user",
)


async def _assign(caller, method, path, **kwargs):
    """Call a /permissions route as `caller`; returns the response and the writers it reached."""
    role_db = FakeRoleDB()
    writers = {name: MagicMock(return_value=True) for name in ASSIGNMENT_WRITERS}
    session = SimpleNamespace(user_id=caller.id, user_hash=caller.user_hash, permissions=[])
    with ExitStack() as stack:
        stack.enter_context(patch(f"{PERMS}.validate_session", return_value=session))
        stack.enter_context(patch(f"{PERMS}.get_user_by_hash", side_effect=lambda user_hash, **kw: USERS.get(user_hash)))
        stack.enter_context(patch(f"{PERMS}.get_user_group_by_hash", side_effect={TEAM.group_hash: TEAM}.get))
        # The router's guard admits a consumer holding manage_roles from any source.
        stack.enter_context(patch(f"{PERMS}.check_user_has_permission_extended", side_effect=role_db.check_user_has_permission))
        stack.enter_context(patch(f"{PERMS}.is_root_user", side_effect=lambda user_id: user_id == ROOT.id, create=True))
        stack.enter_context(patch(f"{PERMS}.global_roles", role_db))
        for name, writer in writers.items():
            stack.enter_context(patch(f"{PERMS}.{name}", writer))
        async with router_client(PERMS) as client:
            response = await getattr(client, method)(path, headers=AUTH, **kwargs)
    return response, {name for name, writer in writers.items() if writer.called}


def _assignment_routes(group_hash):
    """(method, path, kwargs, writer) for every route that assigns or removes a permission group."""
    return [
        ("post", f"/permissions/admin/user-groups/{TEAM.group_hash}/permission-groups",
         {"data": {"permission_group_hash": group_hash}}, "assign_permission_group_to_user_group"),
        ("delete", f"/permissions/admin/user-groups/{TEAM.group_hash}/permission-groups/{group_hash}",
         {}, "remove_permission_group_from_user_group"),
        ("post", f"/permissions/admin/user-groups/{TEAM.group_hash}/permission-groups/bulk",
         {"data": {"permission_group_hashes": ["GH-PLAIN", group_hash]}}, "assign_permission_group_to_user_group"),
        ("post", f"/permissions/users/{MEMBER_A.user_hash}/permission-groups",
         {"data": {"permission_group_hash": group_hash}}, "assign_permission_group_to_user"),
        ("delete", f"/permissions/users/{MEMBER_A.user_hash}/permission-groups/{group_hash}",
         {}, "remove_permission_group_from_user"),
    ]


ASSIGNMENT_ROUTE_IDS = ["user-group-assign", "user-group-remove", "user-group-bulk", "user-assign", "user-remove"]


@pytest.mark.asyncio
@pytest.mark.parametrize("caller", NON_ROOT, ids=NON_ROOT_IDS)
@pytest.mark.parametrize("method, path, kwargs, writer", _assignment_routes("GH-PRIV"), ids=ASSIGNMENT_ROUTE_IDS)
async def test_non_root_cannot_assign_or_remove_groups_granting_reserved_permissions(caller, method, path, kwargs, writer):
    """`manage_roles` via a group assignment unlocks this router, so its names must be root-only here too."""
    response, reached = await _assign(caller, method, path, **kwargs)

    assert response.status_code == 403, f"{method.upper()} {path}: {response.status_code} {response.text}"
    assert response.json()["error"]["code"] == "AUTHZ_2002"
    assert writer not in reached  # the bulk route writes nothing, not even GH-PLAIN


@pytest.mark.asyncio
@pytest.mark.parametrize("method, path, kwargs, writer", _assignment_routes("GH-PLAIN"), ids=ASSIGNMENT_ROUTE_IDS)
async def test_ordinary_group_assignments_are_unchanged_for_manage_roles_holders(method, path, kwargs, writer):
    response, reached = await _assign(CONSUMER_ADMIN, method, path, **kwargs)

    assert response.status_code == 200, f"{method.upper()} {path}: {response.status_code} {response.text}"
    assert writer in reached


@pytest.mark.asyncio
@pytest.mark.parametrize("method, path, kwargs, writer", _assignment_routes("GH-PRIV"), ids=ASSIGNMENT_ROUTE_IDS)
async def test_root_assigns_and_removes_groups_granting_reserved_permissions(method, path, kwargs, writer):
    response, reached = await _assign(ROOT, method, path, **kwargs)

    assert response.status_code == 200, f"{method.upper()} {path}: {response.status_code} {response.text}"
    assert writer in reached
