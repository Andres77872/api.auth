"""Phase 3 RED security-negative matrix for Google OAuth.

Trace: `.dev/sdd/changes/google-oauth-login/tasks.md` task 3.4. These tests
exercise protocol, identity-policy, project-access, and token-minimization
contracts without importing future OAuth implementation modules at collection.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from importlib import import_module
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


CALLBACK_PATH = "/auth/google/callback"

pytestmark = pytest.mark.usefixtures("integration_env")


async def _callback(client, *, code: str = "fake-google-auth-code-not-real", state: str = "security-state"):
    return await client.get(
        CALLBACK_PATH,
        params={"code": code, "state": state},
        headers={"User-Agent": "phase3-google-oauth-security-test"},
        follow_redirects=False,
    )


def _is_unimplemented_route(response) -> bool:
    body = response.text.lower()
    return response.status_code == 404 and "not found" in body and "ext_8" not in body


def _assert_callback_route_exists(response) -> None:
    if _is_unimplemented_route(response):
        pytest.fail(
            "missing future route GET /auth/google/callback; security matrix "
            "requires Phase 8 callback implementation",
            pytrace=False,
        )


@contextmanager
def _optional_patch_targets(targets: tuple[str, ...], value: Any):
    with ExitStack() as stack:
        for target in targets:
            module_name, _, _ = target.rpartition(".")
            try:
                import_module(module_name)
            except ImportError:
                continue
            stack.enter_context(patch(target, value, create=True))
        yield


@contextmanager
def _patched_security_seams(fake_google_token_exchange, verifier):
    with _optional_patch_targets(
        (
            "src.routes.auth_google.google_oauth_client",
            "src.routes.auth_google.oauth_client",
            "src.Util.oauth_clients.google_oauth_client",
        ),
        fake_google_token_exchange,
    ), _optional_patch_targets(
        (
            "src.routes.auth_google.verify_google_id_token",
            "src.routes.auth_google.google_id_token_verifier",
            "src.Util.google_id_token_verifier.verify_google_id_token",
        ),
        verifier,
    ):
        yield


class RejectingVerifier:
    def __init__(self, reason: str):
        self.reason = reason
        self.calls = []

    def __call__(self, id_token: str, **kwargs: Any):
        self.calls.append({"kwargs": kwargs})
        raise RuntimeError(self.reason)

    def verify(self, id_token: str, **kwargs: Any):
        return self(id_token, **kwargs)


def _consumer_user(user_type: str = "consumer"):
    user = MagicMock()
    user.id = "1"
    user.user_hash = f"usr-{user_type}-oauth-001"
    user.username = f"{user_type}user"
    user.email = f"{user_type}@example.test"
    user.user_type = user_type
    user.is_active = True
    return user


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    [
        "nonce mismatch",
        "PKCE verifier mismatch",
        "JOSE alg none rejected",
        "JOSE alg HS256 rejected",
        "JWKS kid miss after one refetch",
        "Workspace hd rejected",
    ],
)
async def test_protocol_security_rejections_do_not_issue_local_session_or_persist_google_tokens(
    client,
    fake_google_token_exchange,
    reason,
    oauth_assert_no_leaks,
):
    verifier = RejectingVerifier(reason)

    with _patched_security_seams(fake_google_token_exchange, verifier):
        response = await _callback(client, state=f"security-{reason.replace(' ', '-')}")

    _assert_callback_route_exists(response)
    assert response.status_code in {400, 401, 403, 502}
    assert "session_token" not in response.cookies
    assert "refresh_token" not in response.cookies
    oauth_assert_no_leaks(response, context=f"protocol rejection: {reason}")


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_user_type", ["root", "admin", "platform"])
async def test_root_admin_and_platform_google_oauth_are_refused_indistinguishably(
    client,
    fake_google_token_exchange,
    fake_google_verifier,
    db_patcher,
    blocked_user_type,
):
    with db_patcher() as db, _patched_security_seams(fake_google_token_exchange, fake_google_verifier):
        db["get_user_by_external_account"].return_value = _consumer_user(blocked_user_type)
        response = await _callback(client, state=f"state-for-{blocked_user_type}")

    _assert_callback_route_exists(response)
    assert response.status_code in {401, 403, 404}
    assert "session_token" not in response.cookies
    assert "refresh_token" not in response.cookies
    assert blocked_user_type not in response.text.lower(), "public error must not disclose ineligible account type"


@pytest.mark.asyncio
async def test_email_only_collision_blocks_account_takeover_without_auto_linking(
    client,
    fake_google_token_exchange,
    fake_google_verifier,
    db_patcher,
    oauth_assert_no_leaks,
):
    with db_patcher() as db, _patched_security_seams(fake_google_token_exchange, fake_google_verifier):
        db["get_user_by_external_account"].return_value = None
        db["link_external_account"].side_effect = AssertionError("must not auto-link by email alone")
        db["create_consumer_user_from_external_account"].side_effect = AssertionError(
            "must not auto-create on email collision"
        )
        response = await _callback(client, state="email-collision-state")

    _assert_callback_route_exists(response)
    assert response.status_code in {401, 403, 409}
    assert not db["link_external_account"].called
    assert not db["create_consumer_user_from_external_account"].called
    oauth_assert_no_leaks(response, context="email-only collision response")


@pytest.mark.asyncio
async def test_bound_project_access_denial_cannot_auto_pick_another_project(
    client,
    fake_google_token_exchange,
    fake_google_verifier,
    db_patcher,
):
    user = _consumer_user("consumer")
    accessible_other_project = MagicMock()
    accessible_other_project.project_hash = "other-project-hash-not-bound"

    with db_patcher() as db, _patched_security_seams(fake_google_token_exchange, fake_google_verifier):
        db["get_user_by_external_account"].return_value = user
        db["get_user_accessible_projects"].return_value = [accessible_other_project]
        response = await _callback(client, state="project-access-denied-state")

    _assert_callback_route_exists(response)
    assert response.status_code in {401, 403}
    assert "session_token" not in response.cookies
    assert "refresh_token" not in response.cookies


@pytest.mark.asyncio
async def test_auto_create_missing_provider_init_group_binding_fails_closed(
    client,
    fake_google_token_exchange,
    fake_google_verifier,
    db_patcher,
):
    with db_patcher() as db, _patched_security_seams(fake_google_token_exchange, fake_google_verifier):
        db["get_user_by_external_account"].return_value = None
        db["create_consumer_user_from_external_account"].side_effect = AssertionError(
            "auto-create must not run without provider-init user group binding"
        )
        response = await _callback(client, state="auto-create-no-group-binding-state")

    _assert_callback_route_exists(response)
    assert response.status_code in {400, 401, 403}
    assert not db["create_consumer_user_from_external_account"].called


@pytest.mark.asyncio
async def test_google_email_verified_does_not_activate_or_promote_local_email_state(
    client,
    fake_google_token_exchange,
    fake_google_verifier,
    db_patcher,
):
    with db_patcher() as db, _patched_security_seams(fake_google_token_exchange, fake_google_verifier):
        db["get_user_by_external_account"].return_value = _consumer_user("consumer")
        db["update_user"].side_effect = AssertionError("Google email_verified must not mutate users.email")
        response = await _callback(client, state="email-verified-no-local-activation-state")

    _assert_callback_route_exists(response)
    assert response.status_code in {200, 401, 403}
    assert not db["update_user"].called


@pytest.mark.asyncio
async def test_callback_never_persists_google_code_access_refresh_or_id_token_material(
    client,
    fake_google_token_exchange,
    fake_google_verifier,
    db_patcher,
):
    with db_patcher() as db, _patched_security_seams(fake_google_token_exchange, fake_google_verifier):
        db["get_user_by_external_account"].return_value = _consumer_user("consumer")
        response = await _callback(client, state="token-minimization-state")

    _assert_callback_route_exists(response)
    assert response.status_code in {200, 400, 401, 403}
    forbidden_argument_fragments = ("access_token", "refresh_token", "id_token", "authorization_code", "code_verifier")
    for name in ("link_external_account", "touch_external_account_last_seen", "create_consumer_user_from_external_account"):
        serialized_calls = repr(db[name].call_args_list)
        assert not any(fragment in serialized_calls for fragment in forbidden_argument_fragments), (
            f"{name} must not receive raw Google token/code material for persistence"
        )
