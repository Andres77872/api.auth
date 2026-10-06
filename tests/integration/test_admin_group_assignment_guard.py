"""Only root may change who administers a project.

An admin user's project assignment *is* membership of a user group named
``admin_<project_id>`` that is granted the project's project group (see
``sp_get_admin_assigned_projects``; the MySQL collation makes the name match
case-insensitive). If a non-root admin could join such a group, rename or create one,
or re-point its project-group grants, it could assign itself to any project and bypass
every project-scope check. Other user groups keep their existing rules.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests.integration.admin_scope_support import (
    ADMIN, AUTH, MEMBER_A, PROJECT_B, ROOT, directory, router_client, session_for,
)


pytestmark = pytest.mark.usefixtures("patched_db_error_logger")

GROUPS = "src.routes.admin_user_groups"


def _group(name, group_hash="ug-hash"):
    return SimpleNamespace(
        id=f"id-{group_hash}", group_hash=group_hash, group_name=name, group_description=None,
        description=None, created_at=None, updated_at=None, is_active=True,
    )


ADMIN_GROUP_B = _group(f"admin_{PROJECT_B.id}", "ug-admin-b")
SHOUTED_ADMIN_GROUP_B = _group(f"  ADMIN_{PROJECT_B.id} ", "ug-admin-b-upper")
PLAIN_GROUP = _group("team", "ug-team")
GROUPS_BY_HASH = {g.group_hash: g for g in (ADMIN_GROUP_B, SHOUTED_ADMIN_GROUP_B, PLAIN_GROUP)}


def _seams():
    project_group = SimpleNamespace(id="pg-1", group_hash="pg-hash", group_name="pg")
    seams = {
        "get_user_group_by_hash": MagicMock(side_effect=lambda group_hash: GROUPS_BY_HASH.get(group_hash)),
        "assign_user_to_user_group": MagicMock(return_value=True),
        "remove_user_from_user_group": MagicMock(return_value=True),
        "grant_user_group_project_group_access": MagicMock(return_value={"granted": True}),
        "revoke_user_group_project_group_access": MagicMock(return_value=True),
        "get_project_group_by_hash": MagicMock(return_value=project_group),
        "create_user_group": MagicMock(side_effect=lambda name, *a, **k: _group(name, "ug-new")),
        "update_user_group": MagicMock(side_effect=lambda group_id, **k: _group(k.get("group_name") or "team", "ug-team")),
        "delete_user_group": MagicMock(return_value=True),
        "get_users_in_group": MagicMock(return_value=[]),
        "get_projects_for_user_group": MagicMock(return_value=[]),
        "get_projects_in_group": MagicMock(return_value=[]),
        "revoke_project_sessions_losing_access": MagicMock(return_value=0),
    }
    return seams, [(f"{GROUPS}.{name}", mock) for name, mock in seams.items()]


REQUESTS = [
    ("post", "/admin/user-groups/{g}/members", {"data": {"user_hash": MEMBER_A.user_hash}}, "assign_user_to_user_group"),
    ("delete", "/admin/user-groups/{g}/members/" + MEMBER_A.user_hash, {}, "remove_user_from_user_group"),
    ("post", "/admin/user-groups/{g}/members/bulk", {"json": {"user_hashes": [MEMBER_A.user_hash]}}, "assign_user_to_user_group"),
    ("post", "/admin/user-groups/{g}/project-groups", {"data": {"project_group_hash": "pg-hash"}}, "grant_user_group_project_group_access"),
    ("delete", "/admin/user-groups/{g}/project-groups/pg-hash", {}, "revoke_user_group_project_group_access"),
    ("delete", "/admin/user-groups/{g}", {}, "delete_user_group"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [ADMIN_GROUP_B, SHOUTED_ADMIN_GROUP_B], ids=["admin_", "ADMIN_"])
@pytest.mark.parametrize("method, path, kwargs, writer", REQUESTS, ids=[r[0] + ":" + r[1] for r in REQUESTS])
async def test_non_root_admin_cannot_touch_a_project_admin_group(group, method, path, kwargs, writer):
    seams, extra = _seams()
    with directory(session_for(ADMIN), extra=extra):
        async with router_client(GROUPS) as client:
            response = await getattr(client, method)(path.format(g=group.group_hash), headers=AUTH, **kwargs)

    assert response.status_code == 403, response.text
    seams[writer].assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", [f"admin_{PROJECT_B.id}", f"Admin_{PROJECT_B.id}"])
async def test_non_root_admin_cannot_create_or_rename_a_group_into_an_admin_group(name):
    seams, extra = _seams()
    with directory(session_for(ADMIN), extra=extra):
        async with router_client(GROUPS) as client:
            created = await client.post("/admin/user-groups", headers=AUTH, data={"group_name": name})
            renamed = await client.put(f"/admin/user-groups/{PLAIN_GROUP.group_hash}", headers=AUTH, data={"group_name": name})

    assert created.status_code == 403, created.text
    assert renamed.status_code == 403, renamed.text
    seams["create_user_group"].assert_not_called()
    seams["update_user_group"].assert_not_called()


@pytest.mark.asyncio
async def test_root_still_manages_admin_groups():
    seams, extra = _seams()
    with directory(session_for(ROOT), extra=extra):
        async with router_client(GROUPS) as client:
            response = await client.post(
                f"/admin/user-groups/{ADMIN_GROUP_B.group_hash}/members", headers=AUTH, data={"user_hash": MEMBER_A.user_hash},
            )

    assert response.status_code == 200, response.text
    seams["assign_user_to_user_group"].assert_called_once()


@pytest.mark.asyncio
async def test_ordinary_groups_are_unchanged_for_admins():
    seams, extra = _seams()
    with directory(session_for(ADMIN), extra=extra):
        async with router_client(GROUPS) as client:
            response = await client.post(
                f"/admin/user-groups/{PLAIN_GROUP.group_hash}/members", headers=AUTH, data={"user_hash": MEMBER_A.user_hash},
            )

    assert response.status_code == 200, response.text
