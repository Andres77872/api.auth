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
    oauth_state_factory,
    fake_google_token_exchange,
    fake_google_verifier,
    db_patcher,
    oauth_assert_no_leaks,
    monkeypatch,
):
    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "true")
    # A state is valid only when the production store issued it.
    state = oauth_state_factory()

    with _patched_callback_seams(fake_google_token_exchange, fake_google_verifier, db_patcher):
        response = await _get_callback(client, code="fake-google-auth-code-not-real", state=state)

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
    oauth_state_factory,
    fake_google_token_exchange,
    fake_google_verifier,
    db_patcher,
    monkeypatch,
):
    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "true")
    state = oauth_state_factory()

    with _patched_callback_seams(fake_google_token_exchange, fake_google_verifier, db_patcher):
        first = await _get_callback(client, state=state)
        second = await _get_callback(client, state=state)

    _assert_callback_route_exists(first)
    _assert_callback_route_exists(second)
    assert first.status_code == 200
    assert second.status_code in {400, 401}
    assert len(fake_google_token_exchange.calls) == 1
    assert "session_token" not in second.cookies
    assert "refresh_token" not in second.cookies


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "forged_state",
    [
        # Literal values that an earlier revision of the route accepted in a test
        # runtime without any Redis record. They must be plain unknown states.
        "companion-contract-state",
        "strict-hash-state",
        "e2e-valid-state",
        "security-anything",
        "state-for-root",
    ],
)
async def test_callback_has_no_test_runtime_state_bypass(
    client,
    forged_state,
    fake_google_token_exchange,
    fake_google_verifier,
    db_patcher,
    monkeypatch,
):
    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "true")

    with _patched_callback_seams(fake_google_token_exchange, fake_google_verifier, db_patcher):
        response = await _get_callback(client, code="fake-google-auth-code-not-real", state=forged_state)

    assert response.status_code in {400, 401}
    assert fake_google_token_exchange.calls == []
    assert "session_token" not in response.cookies


@pytest.mark.asyncio
async def test_callback_rejects_forged_code_and_token_when_no_test_double_is_installed(
    client,
    oauth_state_factory,
    db_patcher,
    monkeypatch,
):
    """With a genuine state but no injected fakes, a forged code must not yield a session."""
    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "true")
    state = oauth_state_factory()

    with db_patcher(), patch(
        "src.Util.oauth.adapters.oidc.guarded_post_form", side_effect=RuntimeError("no network in tests")
    ):
        response = await _get_callback(client, code="fake-google-auth-code-forged", state=state)

    assert response.status_code == 502
    assert "session_token" not in response.cookies
    assert "refresh_token" not in response.cookies


@pytest.mark.asyncio
async def test_callback_user_cancel_returns_distinct_neutral_code_and_consumes_state(
    client,
    oauth_state_factory,
    fake_google_token_exchange,
    fake_google_verifier,
    db_patcher,
    monkeypatch,
):
    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "true")
    state = oauth_state_factory()

    with _patched_callback_seams(fake_google_token_exchange, fake_google_verifier, db_patcher):
        cancelled = await client.get(CALLBACK_PATH, params={"error": "access_denied", "state": state})
        replay = await _get_callback(client, state=state)

    assert cancelled.status_code == 400
    assert cancelled.json()["error"]["code"] == "EXT_8031"
    assert replay.status_code in {400, 401}, "a cancelled round trip must consume its state"
    assert fake_google_token_exchange.calls == []


@pytest.mark.asyncio
async def test_callback_refuses_in_flight_transaction_after_provider_is_disabled(
    client,
    oauth_state_factory,
    fake_google_token_exchange,
    fake_google_verifier,
    db_patcher,
    monkeypatch,
):
    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "true")
    state = oauth_state_factory()
    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "false")

    with _patched_callback_seams(fake_google_token_exchange, fake_google_verifier, db_patcher):
        response = await _get_callback(client, state=state)

    assert response.status_code in {403, 404}
    assert fake_google_token_exchange.calls == []
    assert "session_token" not in response.cookies


@pytest.mark.asyncio
async def test_environment_mode_never_depends_on_the_namespace_aware_schema(
    client,
    oauth_state_factory,
    fake_google_token_exchange,
    fake_google_verifier,
    db_patcher,
    monkeypatch,
):
    """Deploying this code before the schema catch-up must not break Google sign-in."""
    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_OAUTH_PROVISIONING_MODE", "both")

    with _patched_callback_seams(fake_google_token_exchange, fake_google_verifier, db_patcher) as db:
        created = db["get_user_by_external_account"].return_value  # the fully populated mock user
        db["get_user_by_external_account"].return_value = None
        db["create_consumer_user_from_external_account"].return_value = created
        db["get_user_group_by_hash"].return_value = MagicMock(id="ug-1")
        response = await _get_callback(client, state=oauth_state_factory())

    assert response.status_code == 200, response.text

    for name in ("get_user_by_external_account", "create_consumer_user_from_external_account"):
        assert db[name].called, name
        kwargs = db[name].call_args.kwargs
        assert kwargs.get("identity_namespace") is None, f"{name} must use the provider-keyed procedure in env mode"
        assert kwargs["provider"] == "google"


@pytest.mark.asyncio
async def test_incomplete_provisioning_result_fails_closed_instead_of_erroring(
    client,
    oauth_state_factory,
    fake_google_token_exchange,
    fake_google_verifier,
    db_patcher,
    monkeypatch,
):
    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_OAUTH_PROVISIONING_MODE", "both")

    with _patched_callback_seams(fake_google_token_exchange, fake_google_verifier, db_patcher) as db:
        db["get_user_by_external_account"].return_value = None
        db["get_user_group_by_hash"].return_value = MagicMock(id="ug-1")
        db["create_consumer_user_from_external_account"].return_value = {"id": "usr-partial"}  # no hash, no name
        response = await _get_callback(client, state=oauth_state_factory())

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "EXT_8024"
    assert "session_token" not in response.cookies
