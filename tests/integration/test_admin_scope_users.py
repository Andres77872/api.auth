"""User administration routes keep an admin inside its assigned projects.

An admin user may manage itself and users who reach one of its assigned projects; root
may manage anyone. The routes below used to check only "root or admin".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests.integration.admin_scope_support import (
    ACCESSIBLE, ADMIN, AUTH, CONSUMER_ADMIN, MEMBER_A, MEMBER_B, ROOT, USERS_BY_ID, directory, router_client, session_for,
)


pytestmark = pytest.mark.usefixtures("patched_db_error_logger")

USERS = "src.routes.users"
USER_TYPES = "src.routes.user_types_auth"


def _email_seams():
    generated = SimpleNamespace(
        lookup_id="lookup", token_hash=b"h" * 32, token_fingerprint="fp", expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_email = MagicMock()
    db_email.enqueue_admin_password_reset_link.return_value = {"email_message_id": "m-1", "user_email_id": "e-1"}
    db_email.list_admin_user_emails.return_value = [{"id": "e-1", "email_normalized": "x@example.com", "status": "active"}]
    db_email.resend_user_email_activation.return_value = {"email_message_id": "m-2"}
    seams = {
        "db_email": db_email,
        "load_route_email_config": MagicMock(return_value=SimpleNamespace(provider="mailpit")),
        "hash_route_value": MagicMock(return_value=b"\x01" * 32),
        "_check_email_send_rate_limit": MagicMock(return_value=None),
        "_check_resend_cooldown": MagicMock(return_value=None),
        "_mark_resend_sent": MagicMock(),
        "make_link_token_and_payload": MagicMock(return_value=(generated, b"payload")),
        "_safe_log_email_activity": MagicMock(),
        "log_operation_details": MagicMock(),
    }
    return seams, [(f"{USERS}.{name}", mock) for name, mock in seams.items()]


async def _call(caller, method, path, **kwargs):
    seams, extra = _email_seams()
    with directory(session_for(caller), extra=extra):
        async with router_client(USERS) as client:
            response = await getattr(client, method)(path, headers=AUTH, **kwargs)
    return response, seams


@pytest.mark.asyncio
async def test_admin_cannot_send_a_password_reset_to_a_user_outside_its_projects():
    foreign, seams = await _call(ADMIN, "post", f"/users/{MEMBER_B.user_hash}/reset-password")

    assert foreign.status_code == 403, foreign.text
    seams["db_email"].enqueue_admin_password_reset_link.assert_not_called()


@pytest.mark.asyncio
async def test_admin_can_send_a_password_reset_to_a_user_in_its_project():
    own, seams = await _call(ADMIN, "post", f"/users/{MEMBER_A.user_hash}/reset-password")

    assert own.status_code == 200, own.text
    seams["db_email"].enqueue_admin_password_reset_link.assert_called_once()


@pytest.mark.asyncio
async def test_admin_email_list_and_resend_are_scoped():
    listed, _ = await _call(ADMIN, "get", f"/users/{MEMBER_B.user_hash}/emails")
    resent, seams = await _call(ADMIN, "post", f"/users/{MEMBER_B.user_hash}/emails/e-1/resend")
    own, _ = await _call(ADMIN, "get", f"/users/{MEMBER_A.user_hash}/emails")

    assert listed.status_code == 403, listed.text
    assert resent.status_code == 403, resent.text
    seams["db_email"].resend_user_email_activation.assert_not_called()
    assert own.status_code == 200, own.text


@pytest.mark.asyncio
async def test_root_manages_any_user():
    reset, _ = await _call(ROOT, "post", f"/users/{MEMBER_B.user_hash}/reset-password")
    listed, _ = await _call(ROOT, "get", f"/users/{MEMBER_B.user_hash}/emails")

    assert reset.status_code == 200, reset.text
    assert listed.status_code == 200, listed.text


@pytest.mark.asyncio
async def test_admin_search_only_returns_users_in_its_projects():
    everyone = [ROOT, ADMIN, CONSUMER_ADMIN, MEMBER_A, MEMBER_B]
    seams, extra = _email_seams()
    extra.append(("src.Util.db.search_users", MagicMock(return_value=everyone)))
    with directory(session_for(ADMIN), extra=extra):
        async with router_client(USERS) as client:
            response = await client.get("/users/search/query", params={"q": "u"}, headers=AUTH)

    assert response.status_code == 200, response.text
    found = {user["user_hash"] for user in response.json()["users"]}
    assert found == {ADMIN.user_hash, CONSUMER_ADMIN.user_hash, MEMBER_A.user_hash}
    assert response.json()["total_results"] == 3


# ── /user-types ───────────────────────────────────────────────────────────────

def _list_users(limit=100, offset=0, user_type=None, project_id=None, user_type_filter=None, project_filter=None, **_):
    """Mirror sp_list_users_with_access: the project filter matches a project name or hash."""
    wanted_type = user_type_filter or user_type
    wanted_project = project_filter or project_id
    rows = [
        user for user in USERS_BY_ID.values()
        if (not wanted_type or user.user_type == wanted_type)
        and (not wanted_project or any(
            wanted_project in (project.project_hash, project.project_name) for project in ACCESSIBLE.get(user.id, [])
        ))
    ]
    rows.sort(key=lambda user: user.username)
    return rows[offset:offset + limit]


def _user_type_seams():
    return [
        (f"{USER_TYPES}.list_users", MagicMock(side_effect=_list_users)),
        (f"{USER_TYPES}.count_users", MagicMock(return_value=len(USERS_BY_ID))),
        (f"{USER_TYPES}.get_user_type_info", MagicMock(side_effect=lambda user_id: {
            "user_id": user_id, "user_hash": USERS_BY_ID[user_id].user_hash, "username": user_id,
            "user_type": USERS_BY_ID[user_id].user_type, "capabilities": [],
        })),
    ]


@pytest.mark.asyncio
async def test_admin_type_listing_is_restricted_to_its_projects():
    with directory(session_for(ADMIN), extra=_user_type_seams()):
        async with router_client(USER_TYPES) as client:
            response = await client.get("/user-types/users/consumer", headers=AUTH)

    assert response.status_code == 200, response.text
    assert {user["user_hash"] for user in response.json()["users"]} == {CONSUMER_ADMIN.user_hash, MEMBER_A.user_hash}
    assert response.json()["pagination"]["total"] == 2


@pytest.mark.asyncio
async def test_admin_cannot_read_type_info_of_a_consumer_outside_its_projects():
    with directory(session_for(ADMIN), extra=_user_type_seams()):
        async with router_client(USER_TYPES) as client:
            foreign = await client.get(f"/user-types/{MEMBER_B.user_hash}/info", headers=AUTH)
            own = await client.get(f"/user-types/{MEMBER_A.user_hash}/info", headers=AUTH)

    assert foreign.status_code == 403, foreign.text
    assert own.status_code == 200, own.text
