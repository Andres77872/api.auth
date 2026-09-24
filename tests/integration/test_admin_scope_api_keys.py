"""Admin API-key listings stay inside the caller's administrative scope.

`GET /api-keys` used to (a) list every key of `user_hash` in all projects once
`project_hash` passed the scope gate, and (b) ignore `user_hash` for admins without
`project_hash`. Consumers holding `admin` through a global role have no admin scope.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests.integration.admin_scope_support import (
    ADMIN, AUTH, CONSUMER_ADMIN, MEMBER_A, MEMBER_B, PROJECT_A, PROJECT_B, ROOT, directory, router_client, session_for,
)


pytestmark = pytest.mark.usefixtures("patched_db_error_logger")

API_KEYS = "src.routes.api_keys"


def _key(key_id, owner, project):
    return {
        "id": key_id, "public_id": f"pub{key_id}", "name": key_id, "description": None,
        "project_id": project.id, "owner_user_id": owner.id, "is_active": True,
    }


KEYS = [
    _key("k1", MEMBER_A, PROJECT_A),
    _key("k2", MEMBER_A, PROJECT_B),
    _key("k3", MEMBER_B, PROJECT_B),
    _key("k4", CONSUMER_ADMIN, PROJECT_A),
]


def _page(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)


def _seams():
    by_user = MagicMock(side_effect=lambda owner_user_id, limit=50, offset=0: _page(
        [k for k in KEYS if k["owner_user_id"] == owner_user_id], limit, offset))
    by_project = MagicMock(side_effect=lambda project_id, limit=50, offset=0, active_only=False: _page(
        [k for k in KEYS if k["project_id"] == project_id], limit, offset))
    return [(f"{API_KEYS}.list_user_api_keys", by_user), (f"{API_KEYS}.list_project_api_keys", by_project)]


async def _list(caller, **params):
    with directory(session_for(caller), extra=_seams()):
        async with router_client(API_KEYS) as client:
            return await client.get("/api-keys", params=params, headers=AUTH)


def _ids(response):
    return sorted(k["id"] for k in response.json()["data"]["keys"])


@pytest.mark.asyncio
async def test_user_and_project_filters_intersect_for_admins():
    response = await _list(ADMIN, user_hash=MEMBER_A.user_hash, project_hash=PROJECT_A.project_hash)

    assert response.status_code == 200, response.text
    assert _ids(response) == ["k1"], "a key of the user in a project outside the admin's scope leaked"
    assert response.json()["data"]["total"] == 1


@pytest.mark.asyncio
async def test_admin_user_filter_is_honoured_without_project_hash():
    response = await _list(ADMIN, user_hash=MEMBER_A.user_hash)

    assert response.status_code == 200, response.text
    assert _ids(response) == ["k1"]


@pytest.mark.asyncio
async def test_admin_cannot_list_a_user_outside_its_projects():
    response = await _list(ADMIN, user_hash=MEMBER_B.user_hash)

    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_admin_without_filters_sees_only_its_projects_keys():
    response = await _list(ADMIN)

    assert response.status_code == 200, response.text
    assert _ids(response) == ["k1", "k4"]


@pytest.mark.asyncio
async def test_root_filters_intersect_too():
    response = await _list(ROOT, user_hash=MEMBER_A.user_hash, project_hash=PROJECT_B.project_hash)

    assert response.status_code == 200, response.text
    assert _ids(response) == ["k2"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params", [{}, {"project_hash": PROJECT_A.project_hash}, {"user_hash": MEMBER_A.user_hash}], ids=["none", "project", "user"],
)
async def test_consumer_with_admin_permission_lists_nothing(params):
    response = await _list(CONSUMER_ADMIN, **params)

    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_user_key_listing_route_is_scoped_too():
    with directory(session_for(CONSUMER_ADMIN), extra=_seams()):
        async with router_client(API_KEYS) as client:
            consumer = await client.get(f"/api-keys/users/{MEMBER_A.user_hash}", headers=AUTH)
    with directory(session_for(ADMIN), extra=_seams()):
        async with router_client(API_KEYS) as client:
            admin = await client.get(f"/api-keys/users/{MEMBER_A.user_hash}", headers=AUTH)

    assert consumer.status_code == 403, consumer.text
    assert admin.status_code == 200, admin.text
    assert _ids(admin) == ["k1"]
    assert admin.json()["data"]["total"] == 1
