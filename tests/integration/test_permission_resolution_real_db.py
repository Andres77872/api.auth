"""Permission resolution honours the soft-delete flag of every hop (real MySQL).

A documentation review of the roles and permissions suites found two resolver gaps:

1. The auth-time resolver (``sp_global_get_user_permissions`` and
   ``sp_global_check_user_has_permission``) did not check the permission group's own
   ``is_active``, while the lookups behind the reserved-name check
   (``sp_global_get_role_permission_groups``) did. A deleted group still linked to a role
   kept granting its permissions but vanished from the check, so a non-root
   ``manage_roles`` holder could assign a role that still granted ``admin``.
2. The inspection resolvers (``sp_get_user_all_permissions`` and
   ``sp_check_user_has_permission_extended``, which is also the ``/permissions`` admin
   guard) ignored whether the role, the permission group or the user group was active, so
   ``manage_roles`` from a deleted source still opened the ``/permissions`` admin routes.

Everything is driven through the ``src.Util.db`` wrappers the routes call, and deletions
go through the same functions the DELETE routes use where one exists.
"""

from __future__ import annotations

import uuid
from contextlib import ExitStack
from unittest.mock import patch

import pymysql
import pytest

from src.Util.admin_scope import is_reserved_permission_name, role_grants_reserved_permission
from src.Util.db import db_global_roles, db_permission_assignments
from tests.integration.conftest import _REAL_DB_CONFIG


pytestmark = pytest.mark.real_db


def _connect():
    cfg = {**_REAL_DB_CONFIG}
    cfg.pop("cursorclass", None)
    return pymysql.connect(**cfg)


@pytest.fixture
def real_db_wrappers():
    """Point the role and permission-assignment DB modules at the real test database."""
    with ExitStack() as stack:
        for module in (db_global_roles, db_permission_assignments):
            stack.enter_context(patch.object(module, "get_connection", _connect))
        yield


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


class RoleGraph:
    """Creates roles, permission groups, permissions and their links; soft-deletes them after."""

    def __init__(self, conn):
        self.conn = conn
        self._created: list[tuple[str, str]] = []

    def _insert(self, table: str, row: dict) -> str:
        columns = ", ".join(row)
        placeholders = ", ".join(["%s"] * len(row))
        with self.conn.cursor() as cur:
            cur.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(row.values()))
        self.conn.commit()
        self._created.append((table, row["id"]))
        return row["id"]

    def permission(self, name: str) -> dict:
        """A permission row. Reserved names are shared, so reuse an active one if present."""
        if is_reserved_permission_name(name):
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM global_permissions WHERE permission_name = %s AND is_active = 1", (name,)
                )
                row = cur.fetchone()
            self.conn.commit()
            if row:
                return {"id": row["id"], "permission_name": name}
            permission_id = f"perm-{uuid.uuid4()}"
            with self.conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO global_permissions (id, permission_hash, permission_name, permission_display_name) "
                    "VALUES (%s, %s, %s, %s)",
                    (permission_id, uuid.uuid4().hex, name, name),
                )
            self.conn.commit()  # left in place: other tests may share it
            return {"id": permission_id, "permission_name": name}
        name = f"{name}_{_suffix()}"
        permission_id = self._insert("global_permissions", {
            "id": f"perm-{uuid.uuid4()}", "permission_hash": uuid.uuid4().hex,
            "permission_name": name, "permission_display_name": name,
        })
        return {"id": permission_id, "permission_name": name}

    def group(self, name: str, permissions: list[dict]) -> dict:
        name = f"{name}_{_suffix()}"
        group_id = self._insert("global_permission_groups", {
            "id": f"pg-{uuid.uuid4()}", "group_hash": uuid.uuid4().hex,
            "group_name": name, "group_display_name": name,
        })
        for permission in permissions:
            self._insert("global_permission_group_permissions", {
                "id": f"pgp-{uuid.uuid4()}", "permission_group_id": group_id, "permission_id": permission["id"],
            })
        return {"id": group_id, "group_name": name}

    def role(self, name: str, groups: list[dict]) -> dict:
        name = f"{name}_{_suffix()}"
        role_id = self._insert("roles", {
            "id": f"role-{uuid.uuid4()}", "role_hash": uuid.uuid4().hex,
            "role_name": name, "role_display_name": name,
        })
        for group in groups:
            self._insert("role_permission_groups", {
                "id": f"rpg-{uuid.uuid4()}", "role_id": role_id, "permission_group_id": group["id"],
            })
        return {"id": role_id, "role_name": name}

    def give_user_group(self, user_group_id: str, group: dict) -> None:
        self._insert("user_group_permission_groups", {
            "id": f"ugpg-{uuid.uuid4()}", "user_group_id": user_group_id, "permission_group_id": group["id"],
        })

    def give_user(self, user_id: str, group: dict) -> None:
        self._insert("user_permission_groups", {
            "id": f"upg-{uuid.uuid4()}", "user_id": user_id, "permission_group_id": group["id"],
        })

    def cleanup(self) -> None:
        with self.conn.cursor() as cur:
            for table, row_id in reversed(self._created):
                cur.execute(f"UPDATE {table} SET is_active = 0 WHERE id = %s", (row_id,))
        self.conn.commit()


@pytest.fixture
def role_graph(real_db_conn):
    graph = RoleGraph(real_db_conn)
    try:
        yield graph
    finally:
        graph.cleanup()


def _deactivate(conn, table: str, row_id: str) -> bool:
    """Flip one row's flag, leaving every link around it active."""
    with conn.cursor() as cur:
        changed = cur.execute(f"UPDATE {table} SET is_active = 0 WHERE id = %s", (row_id,))
    conn.commit()
    return changed == 1


def _source_groups(user_id: str) -> set[str]:
    return {row["permission_group_name"] for row in db_permission_assignments.get_user_permission_sources(user_id)}


# ── 1. auth-time resolver versus the reserved-name check ─────────────────────

def test_deleted_group_linked_to_a_role_stops_granting_and_the_reserved_check_agrees(
    real_db_wrappers, real_factory, role_graph
):
    admin = role_graph.permission("admin")
    reads = role_graph.permission("rr_read_reports")
    privileged = role_graph.group("rr_privileged", [admin])
    plain = role_graph.group("rr_plain", [reads])
    role = role_graph.role("rr_superusers", [privileged, plain])
    holder = real_factory.create_user(username="rr_holder")
    assert db_global_roles.assign_role_to_user(holder["id"], role["id"])

    def reserved_names_granted() -> bool:
        return any(is_reserved_permission_name(name) for name in db_global_roles.get_user_permissions(holder["id"]))

    assert set(db_global_roles.get_user_permissions(holder["id"])) == {"admin", reads["permission_name"]}
    assert db_global_roles.check_user_has_permission(holder["id"], "admin") is True
    assert role_grants_reserved_permission(db_global_roles, role) is True
    assert reserved_names_granted() is True

    # What DELETE /roles/permission-groups/{group_hash} runs: the group's flag only.
    assert db_global_roles.delete_permission_group(privileged["id"]) is True

    assert db_global_roles.get_user_permissions(holder["id"]) == [reads["permission_name"]]
    assert db_global_roles.check_user_has_permission(holder["id"], "admin") is False
    # The reserved-name check and the resolver see the same role again.
    assert role_grants_reserved_permission(db_global_roles, role) is False
    assert reserved_names_granted() is False


# ── 2. inspection resolvers and the /permissions admin guard ─────────────────

def _grant_through_deleted_role(conn, graph, factory, user, group):
    role = graph.role("ir_role", [group])
    assert db_global_roles.assign_role_to_user(user["id"], role["id"])
    return lambda: db_global_roles.delete_role(role["id"])


def _grant_through_role_with_deleted_group(conn, graph, factory, user, group):
    role = graph.role("ir_role", [group])
    assert db_global_roles.assign_role_to_user(user["id"], role["id"])
    return lambda: db_global_roles.delete_permission_group(group["id"])


def _grant_through_deleted_user_group(conn, graph, factory, user, group):
    user_group = factory.create_user_group(group_name="ir_team")
    factory.link_user_to_group(user["id"], user_group["id"])
    graph.give_user_group(user_group["id"], group)
    return lambda: _deactivate(conn, "user_groups", user_group["id"])


def _grant_through_user_group_with_deleted_group(conn, graph, factory, user, group):
    user_group = factory.create_user_group(group_name="ir_team")
    factory.link_user_to_group(user["id"], user_group["id"])
    graph.give_user_group(user_group["id"], group)
    return lambda: db_global_roles.delete_permission_group(group["id"])


def _grant_directly_with_deleted_group(conn, graph, factory, user, group):
    graph.give_user(user["id"], group)
    return lambda: db_global_roles.delete_permission_group(group["id"])


@pytest.mark.parametrize(
    "grant",
    [
        _grant_through_deleted_role,
        _grant_through_role_with_deleted_group,
        _grant_through_deleted_user_group,
        _grant_through_user_group_with_deleted_group,
        _grant_directly_with_deleted_group,
    ],
    ids=["deleted-role", "role/deleted-group", "deleted-user-group", "user-group/deleted-group", "direct/deleted-group"],
)
def test_inspection_resolvers_drop_manage_roles_from_a_deleted_source(
    real_db_wrappers, real_db_conn, real_factory, role_graph, grant
):
    manage_roles = role_graph.permission("manage_roles")
    delegated = role_graph.group("ir_delegated", [manage_roles])
    control_permission = role_graph.permission("ir_control_perm")
    control = role_graph.group("ir_control", [control_permission])
    control_name = control_permission["permission_name"]
    user = real_factory.create_user(username="ir_delegate")
    role_graph.give_user(user["id"], control)
    delete_source = grant(real_db_conn, role_graph, real_factory, user, delegated)

    assert set(db_permission_assignments.get_user_all_permissions(user["id"])) == {"manage_roles", control_name}
    assert db_permission_assignments.check_user_has_permission_extended(user["id"], "manage_roles") is True
    assert delegated["group_name"] in _source_groups(user["id"])

    assert delete_source()

    assert db_permission_assignments.get_user_all_permissions(user["id"]) == [control_name]
    # This call is the `/permissions` admin guard's consumer fallback.
    assert db_permission_assignments.check_user_has_permission_extended(user["id"], "manage_roles") is False
    assert db_permission_assignments.check_user_has_permission_extended(user["id"], control_name) is True
    # The permission list and the source list agree again.
    assert _source_groups(user["id"]) == {control["group_name"]}
