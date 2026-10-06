"""Project routes: a project-scoped admin only administers its assigned projects.

Every admin session carries the ``admin`` permission, so a guard that only checks that
name lets an admin assigned to project A read and write project B. Root still reaches
every project; a consumer holding ``admin`` through a global role gets no admin scope.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests.integration.admin_scope_support import (
    ADMIN, AUTH, CONSUMER_ADMIN, PROJECT_A, PROJECT_B, ROOT, directory, router_client, session_for,
)


pytestmark = pytest.mark.usefixtures("patched_db_error_logger")

PROJECTS = "src.routes.projects"


def _project_seams(**overrides):
    seams = {
        "list_all_projects": MagicMock(return_value=[PROJECT_A, PROJECT_B]),
        "search_projects": MagicMock(return_value=[PROJECT_A, PROJECT_B]),
        "create_project": MagicMock(return_value=PROJECT_B),
        "update_project": MagicMock(side_effect=lambda project_id, **kw: PROJECT_A if project_id == PROJECT_A.id else PROJECT_B),
        "delete_project": MagicMock(return_value=True),
        "get_project_stats": MagicMock(return_value={}),
        "get_user_groups_for_user": MagicMock(return_value=[]),
        "get_project_groups_for_project": MagicMock(return_value=[]),
        "get_project_members_page": MagicMock(return_value=([], 0)),
        "get_user_groups_for_project": MagicMock(return_value=[]),
        "get_recent_activity": MagicMock(return_value=[]),
        "count_activity_logs": MagicMock(return_value=0),
    }
    seams.update(overrides)
    return seams, [(f"{PROJECTS}.{name}", mock) for name, mock in seams.items()]


@pytest.mark.asyncio
async def test_admin_project_list_only_shows_assigned_projects():
    seams, extra = _project_seams()
    with directory(session_for(ADMIN), extra=extra):
        async with router_client(PROJECTS) as client:
            listed = await client.get("/projects", headers=AUTH)
            searched = await client.get("/projects", params={"search": "Project"}, headers=AUTH)

    assert listed.status_code == 200, listed.text
    assert [p["project_hash"] for p in listed.json()["projects"]] == [PROJECT_A.project_hash]
    assert listed.json()["user_access_level"] == "admin"
    assert listed.json()["pagination"]["total"] == 1
    assert [p["project_hash"] for p in searched.json()["projects"]] == [PROJECT_A.project_hash]
    seams["list_all_projects"].assert_not_called()
    seams["search_projects"].assert_not_called()


@pytest.mark.asyncio
async def test_root_project_list_still_sees_every_project():
    seams, extra = _project_seams()
    with directory(session_for(ROOT), extra=extra):
        async with router_client(PROJECTS) as client:
            listed = await client.get("/projects", headers=AUTH)

    assert listed.status_code == 200, listed.text
    assert {p["project_hash"] for p in listed.json()["projects"]} == {PROJECT_A.project_hash, PROJECT_B.project_hash}


@pytest.mark.asyncio
async def test_consumer_with_admin_permission_gets_the_group_access_view():
    seams, extra = _project_seams()
    with directory(session_for(CONSUMER_ADMIN), extra=extra):
        async with router_client(PROJECTS) as client:
            listed = await client.get("/projects", headers=AUTH)

    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["user_access_level"] == "user"
    assert [p["project_hash"] for p in body["projects"]] == [PROJECT_A.project_hash]
    assert body["projects"][0]["access_level"] == "group_access"
    seams["list_all_projects"].assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("caller", [ADMIN, CONSUMER_ADMIN], ids=["admin", "consumer-with-admin"])
async def test_only_root_creates_projects(caller):
    seams, extra = _project_seams()
    with directory(session_for(caller), extra=extra):
        async with router_client(PROJECTS) as client:
            response = await client.post("/projects", headers=AUTH, data={"project_name": "New"})

    assert response.status_code == 403, response.text
    seams["create_project"].assert_not_called()


@pytest.mark.asyncio
async def test_root_creates_projects():
    seams, extra = _project_seams()
    with directory(session_for(ROOT), extra=extra):
        async with router_client(PROJECTS) as client:
            response = await client.post("/projects", headers=AUTH, data={"project_name": "New"})

    assert response.status_code == 200, response.text
    seams["create_project"].assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method, path, kwargs, side_effect",
    [
        ("put", f"/projects/{PROJECT_B.project_hash}", {"data": {"project_name": "Taken"}}, "update_project"),
        ("delete", f"/projects/{PROJECT_B.project_hash}", {}, "delete_project"),
        ("get", f"/projects/{PROJECT_B.project_hash}", {}, "get_project_stats"),
        ("get", f"/projects/{PROJECT_B.project_hash}/members", {}, "get_project_members_page"),
        ("get", f"/projects/{PROJECT_B.project_hash}/activity", {}, "get_recent_activity"),
        ("get", f"/projects/{PROJECT_B.project_hash}/stats", {}, "get_project_stats"),
        ("get", f"/projects/{PROJECT_B.project_hash}/groups", {}, "get_user_groups_for_project"),
    ],
)
async def test_admin_cannot_reach_a_project_it_is_not_assigned_to(method, path, kwargs, side_effect):
    seams, extra = _project_seams()
    with directory(session_for(ADMIN), extra=extra):
        async with router_client(PROJECTS) as client:
            response = await getattr(client, method)(path, headers=AUTH, **kwargs)

    assert response.status_code == 403, f"{method.upper()} {path}: {response.status_code} {response.text}"
    seams[side_effect].assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method, path, kwargs",
    [
        ("put", f"/projects/{PROJECT_A.project_hash}", {"data": {"project_name": "Renamed"}}),
        ("delete", f"/projects/{PROJECT_A.project_hash}", {}),
        ("get", f"/projects/{PROJECT_A.project_hash}", {}),
        ("get", f"/projects/{PROJECT_A.project_hash}/members", {}),
        ("get", f"/projects/{PROJECT_A.project_hash}/stats", {}),
        ("get", f"/projects/{PROJECT_A.project_hash}/groups", {}),
    ],
)
async def test_admin_still_administers_its_assigned_project(method, path, kwargs):
    seams, extra = _project_seams()
    with directory(session_for(ADMIN), extra=extra):
        async with router_client(PROJECTS) as client:
            response = await getattr(client, method)(path, headers=AUTH, **kwargs)

    assert response.status_code == 200, f"{method.upper()} {path}: {response.status_code} {response.text}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method, path, kwargs",
    [
        ("put", f"/projects/{PROJECT_A.project_hash}", {"data": {"project_name": "Taken"}}),
        ("delete", f"/projects/{PROJECT_A.project_hash}", {}),
        ("get", f"/projects/{PROJECT_A.project_hash}/members", {}),
        ("get", f"/projects/{PROJECT_A.project_hash}/groups", {}),
    ],
)
async def test_consumer_permission_names_grant_no_project_admin_scope(method, path, kwargs):
    seams, extra = _project_seams()
    with directory(session_for(CONSUMER_ADMIN), extra=extra):
        async with router_client(PROJECTS) as client:
            response = await getattr(client, method)(path, headers=AUTH, **kwargs)

    assert response.status_code == 403, f"{method.upper()} {path}: {response.status_code} {response.text}"


@pytest.mark.asyncio
async def test_consumer_with_admin_permission_reads_its_own_project_as_a_member():
    seams, extra = _project_seams()
    with directory(session_for(CONSUMER_ADMIN), extra=extra):
        async with router_client(PROJECTS) as client:
            own = await client.get(f"/projects/{PROJECT_A.project_hash}", headers=AUTH)
            foreign = await client.get(f"/projects/{PROJECT_B.project_hash}", headers=AUTH)

    assert own.status_code == 200, own.text
    assert own.json()["user_access"]["access_level"] == "group_access"
    assert foreign.status_code == 403, foreign.text


@pytest.mark.asyncio
async def test_root_reaches_any_project():
    seams, extra = _project_seams()
    with directory(session_for(ROOT), extra=extra):
        async with router_client(PROJECTS) as client:
            updated = await client.put(f"/projects/{PROJECT_B.project_hash}", headers=AUTH, data={"project_name": "B2"})
            deleted = await client.delete(f"/projects/{PROJECT_B.project_hash}", headers=AUTH)

    assert updated.status_code == 200, updated.text
    assert deleted.status_code == 200, deleted.text
