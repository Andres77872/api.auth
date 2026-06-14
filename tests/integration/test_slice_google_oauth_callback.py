"""Phase 3 RED integration contracts for ``GET /auth/google/callback``.

Trace: `.dev/sdd/changes/google-oauth-login/tasks.md` task 3.2 and the
callback/session requirements in the Google OAuth spec and design.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from importlib import import_module
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


CALLBACK_PATH = "/auth/google/callback"

pytestmark = pytest.mark.usefixtures("integration_env")


async def _get_callback(client, *, code: str = "fake-google-auth-code-not-real", state: str = "fake-oauth-state-not-real"):
    return await client.get(
        CALLBACK_PATH,
        params={"code": code, "state": state},
        headers={"User-Agent": "phase3-google-oauth-callback-test"},
        follow_redirects=False,
    )


def _is_unimplemented_route(response) -> bool:
    body = response.text.lower()
    return response.status_code == 404 and "not found" in body and "ext_8" not in body


def _assert_callback_route_exists(response) -> None:
    if _is_unimplemented_route(response):
        pytest.fail(
            "missing future route GET /auth/google/callback; Phase 8.3-8.5 must "
            "implement callback, identity resolution, and LoginResponse reuse",
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
def _patched_callback_seams(fake_google_token_exchange, fake_google_verifier, db_patcher):
    with db_patcher() as db, _optional_patch_targets(
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
        fake_google_verifier,
    ):
        user = MagicMock()
        user.id = "1"
        user.user_hash = "usr-oauth-linked-001"
        user.username = "oauthuser"
        user.email = "oauth-user@example.test"
        user.user_type = "consumer"
        user.is_active = True
        project = MagicMock()
        project.id = "1"
        project.project_hash = "project-hash-redacted-by-contract"
        project.project_name = "OAuth Project"
        project.project_description = "OAuth project"
        group = MagicMock()
        group.id = "1"
        group.group_hash = "group-hash-redacted-by-contract"
        group.group_name = "OAuth Consumers"
        db["get_user_by_external_account"].return_value = user
        db["touch_external_account_last_seen"].return_value = True
        db["get_user_accessible_projects"].return_value = [project]
        db["get_project_by_hash"].return_value = project
        db["get_user_groups_for_user"].return_value = [group]
        yield db


@pytest.mark.asyncio
async def test_callback_rejects_unknown_state_before_google_code_exchange(
    client,
    fake_google_token_exchange,
    fake_google_verifier,
    db_patcher,
    oauth_assert_no_leaks,
):
    with _patched_callback_seams(fake_google_token_exchange, fake_google_verifier, db_patcher):
        response = await _get_callback(client, state="unknown-state-that-was-never-issued")

    _assert_callback_route_exists(response)
    assert response.status_code in {400, 401}
    assert fake_google_token_exchange.calls == [], "state must be consumed before any Google token exchange"
    assert fake_google_verifier.calls == [], "ID-token verifier must not run for unknown state"
    oauth_assert_no_leaks(response, context="unknown state callback response")


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["", "malformed state with spaces", "expired-state", "replayed-state"])
async def test_callback_rejects_replay_expired_and_malformed_state_without_cookies(
    client,
    state,
    fake_google_token_exchange,
    fake_google_verifier,
    db_patcher,
    oauth_assert_no_leaks,
):
    with _patched_callback_seams(fake_google_token_exchange, fake_google_verifier, db_patcher):
        response = await _get_callback(client, state=state)

    _assert_callback_route_exists(response)
    assert response.status_code in {400, 401}
    assert "session_token" not in response.cookies
    assert "refresh_token" not in response.cookies
    assert fake_google_token_exchange.calls == []
    oauth_assert_no_leaks(response, context="state rejected callback response")


@pytest.mark.asyncio
async def test_callback_exchanges_code_once_invokes_verifier_and_returns_login_response_parity(
    client,
    fake_redis,
    fake_google_token_exchange,
    fake_google_verifier,
    db_patcher,
    oauth_assert_no_leaks,
):
    # Future state implementation owns the exact Redis shape; this marker keeps
    # the test intentional during RED and gives GREEN code a deterministic value.
    fake_redis.set("google_oauth_state:test-valid-state", "phase3-callback-contract", ex=600)

    with _patched_callback_seams(fake_google_token_exchange, fake_google_verifier, db_patcher):
        response = await _get_callback(client, code="fake-google-auth-code-not-real", state="test-valid-state")

    _assert_callback_route_exists(response)
    assert response.status_code == 200
    data = response.json()
    expected_login_response_fields = {
        "success",
        "access_token",
        "refresh_token",
        "session_token",
        "user",
        "project",
        "accessible_projects",
        "user_groups",
    }
    assert expected_login_response_fields <= set(data)
    assert data["session_token"] == data["access_token"]
    assert "session_token" in response.cookies
    assert "refresh_token" in response.cookies
    assert len(fake_google_token_exchange.calls) == 1, "Google auth code must be exchanged exactly once"
    assert len(fake_google_verifier.calls) == 1, "callback must validate the Google ID token once"
    oauth_assert_no_leaks(response, context="successful callback response")


@pytest.mark.asyncio
async def test_callback_replay_does_not_exchange_code_twice_or_issue_second_session(
    client,
    fake_redis,
    fake_google_token_exchange,
    fake_google_verifier,
    db_patcher,
):
    fake_redis.set("google_oauth_state:test-replay-state", "phase3-callback-contract", ex=600)

    with _patched_callback_seams(fake_google_token_exchange, fake_google_verifier, db_patcher):
        first = await _get_callback(client, state="test-replay-state")
        second = await _get_callback(client, state="test-replay-state")

    _assert_callback_route_exists(first)
    _assert_callback_route_exists(second)
    assert first.status_code == 200
    assert second.status_code in {400, 401}
    assert len(fake_google_token_exchange.calls) == 1
    assert "session_token" not in second.cookies
    assert "refresh_token" not in second.cookies
