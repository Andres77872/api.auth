"""RED API contract tests for optional email and activation endpoints.

Trace: `.dev/sdd/changes/email-activation/tasks.md` task 1.5.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


GENERIC_ACCEPTED_BODY = {
    "success": True,
    "message": "If the request can be processed, it has been accepted.",
}


def test_register_and_admin_request_models_allow_omitted_email():
    from src.Util.Models import CreateAdminUserRequest, CreateRootUserRequest, RegisterRequest

    register = RegisterRequest(username="person", password="SecureP@ss123", user_group_hash="grp-1")
    admin = CreateAdminUserRequest(username="admin", password="SecureP@ss123")
    root = CreateRootUserRequest(username="root", password="SecureP@ss123")

    assert register.email is None
    assert admin.email is None
    assert root.email is None


@pytest.mark.asyncio
async def test_authenticated_email_add_returns_generic_202(client, integration_env):
    response = await client.post(
        "/users/me/emails",
        data={"email": " Person@Example.COM "},
        headers={"Authorization": "Bearer test-token", "Idempotency-Key": "idem-1"},
    )

    assert response.status_code == 202
    assert response.json() == GENERIC_ACCEPTED_BODY


@pytest.mark.asyncio
async def test_authenticated_email_list_exposes_only_owner_state(client, integration_env):
    response = await client.get(
        "/users/me/emails",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "emails" in body
    assert all("status" in item and "is_primary" in item for item in body["emails"])


@pytest.mark.asyncio
async def test_authenticated_email_resend_returns_generic_202(client, integration_env):
    response = await client.post(
        "/users/me/emails/ue-123/resend",
        headers={"Authorization": "Bearer test-token", "Idempotency-Key": "idem-resend-1"},
    )

    assert response.status_code == 202
    assert response.json() == GENERIC_ACCEPTED_BODY


@pytest.mark.asyncio
async def test_public_email_verify_is_generic_202_and_creates_no_session(client, integration_env):
    response = await client.post(
        "/auth/email/verify",
        json={"token": "lookup.secret"},
        headers={"Idempotency-Key": "idem-verify-1"},
    )

    assert response.status_code == 202
    assert response.json() == GENERIC_ACCEPTED_BODY
    assert "session_token" not in response.cookies
    assert "refresh_token" not in response.cookies


@pytest.mark.asyncio
async def test_public_forgot_password_known_and_unknown_are_byte_stable(client, integration_env):
    known = await client.post(
        "/auth/password/forgot",
        json={"email_or_username": "known@example.com"},
        headers={"Idempotency-Key": "idem-known"},
    )
    unknown = await client.post(
        "/auth/password/forgot",
        json={"email_or_username": "unknown@example.com"},
        headers={"Idempotency-Key": "idem-unknown"},
    )

    assert known.status_code == 202
    assert unknown.status_code == 202
    assert known.content == unknown.content


@pytest.mark.asyncio
async def test_rate_limited_public_email_flow_returns_429_retry_after(client, integration_env):
    response = await client.post(
        "/auth/password/forgot",
        json={"email_or_username": "person@example.com"},
        headers={"X-Force-Email-Rate-Limit-Test": "true"},
    )

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
    body = response.json()
    assert body["error"]["code"] == "INT_7005"


@pytest.mark.asyncio
async def test_activated_email_login_uses_existing_login_contract(client, integration_env):
    user = MagicMock()
    user.id = "usr-1"
    user.user_hash = "usr-hash-1"
    user.username = "person"
    user.email = "person@example.com"
    user.user_type = "consumer"

    project = MagicMock()
    project.id = "proj-1"
    project.project_hash = "prj-test-001"
    project.project_name = "Project"
    project.project_description = None
    project.is_active = True
    project.archived = False

    with patch("src.routes.auth.get_user_by_credentials", return_value=user) as credentials_lookup, \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
         patch("src.routes.auth.get_project_by_hash", return_value=project), \
         patch("src.routes.auth.get_user_groups_for_user", return_value=[]):
        response = await client.post(
            "/auth/login",
            data={"username": "Person@Example.COM", "password": "SecureP@ss123", "project_hash": "prj-test-001"},
        )

    assert response.status_code == 200
    credentials_lookup.assert_called_once_with("Person@Example.COM", "SecureP@ss123")
