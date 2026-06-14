"""Phase 3 RED api.auth-side companion contract tests.

Trace: `.dev/sdd/changes/google-oauth-login/tasks.md` task 3.7 and the
cross-repo compatibility specification. This file does not import or modify
``magic-worlds-api``; it asserts the api.auth-facing contract only.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from importlib import import_module
from typing import Any
from unittest.mock import patch

import pytest


START_PATH = "/auth/google/start"
CALLBACK_PATH = "/auth/google/callback"

pytestmark = pytest.mark.usefixtures("integration_env")


def _is_unimplemented_route(response) -> bool:
    body = response.text.lower()
    return response.status_code == 404 and "not found" in body and "ext_8" not in body


def _assert_oauth_route_exists(response, path: str) -> None:
    if _is_unimplemented_route(response):
        pytest.fail(
            f"missing future OAuth route {path}; api.auth companion contract "
            "requires Phase 8 route implementation before rollout",
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
def _patched_provider_init(fake_provider_init_redeemer):
    with _optional_patch_targets(
        (
            "src.routes.auth_google.redeem_provider_init_token",
            "src.routes.auth_google.redeem_provider_init",
            "src.Util.provider_init.redeem_provider_init_token",
        ),
        fake_provider_init_redeemer.redeem_provider_init_token,
    ):
        yield


async def _start(client, payload: dict[str, Any]):
    return await client.post(
        START_PATH,
        json=payload,
        headers={"User-Agent": "phase3-google-oauth-companion-contract-test"},
        follow_redirects=False,
    )


async def _callback(client, *, state: str = "companion-contract-state"):
    return await client.get(
        CALLBACK_PATH,
        params={"code": "fake-google-auth-code-not-real", "state": state},
        headers={"User-Agent": "phase3-google-oauth-companion-contract-test"},
        follow_redirects=False,
    )


@pytest.mark.asyncio
async def test_provider_init_start_accepts_opaque_browser_token_only_and_rejects_strict_hash_inputs(
    client,
    fake_provider_init_redeemer,
    monkeypatch,
    oauth_assert_no_leaks,
):
    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "true")
    strict_inputs = {
        "project_hash": "browser-supplied-project-hash-must-be-rejected",
        "user_group_hash": "browser-supplied-user-group-hash-must-be-rejected",
    }

    with _patched_provider_init(fake_provider_init_redeemer):
        response = await _start(
            client,
            {
                "provider_init_token": "fake-provider-init-token-not-real",
                **strict_inputs,
                "redirect_uri": "http://localhost:8000/auth/google/callback",
                "return_origin": "http://localhost:3000",
            },
        )

    _assert_oauth_route_exists(response, START_PATH)
    assert response.status_code in {400, 403}
    assert "location" not in response.headers
    oauth_assert_no_leaks(
        response,
        forbidden_values=strict_inputs,
        context="companion strict-hash input rejection",
    )


@pytest.mark.asyncio
async def test_provider_init_redemption_shape_is_server_side_and_browser_response_stays_opaque(
    client,
    fake_provider_init_redeemer,
    monkeypatch,
    oauth_assert_no_leaks,
):
    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "true")
    token = "fake-provider-init-contract-token-not-real"
    fake_provider_init_redeemer.add_token(token)

    with _patched_provider_init(fake_provider_init_redeemer):
        response = await _start(
            client,
            {
                "provider_init_token": token,
                "redirect_uri": "http://localhost:8000/auth/google/callback",
                "return_origin": "http://localhost:3000",
            },
        )

    _assert_oauth_route_exists(response, START_PATH)
    assert response.status_code in {200, 302, 303}
    assert fake_provider_init_redeemer.calls, "api.auth must redeem the opaque companion token server-side"
    oauth_assert_no_leaks(response, context="companion opaque provider-init start response")


@pytest.mark.asyncio
async def test_callback_success_stays_login_response_compatible_for_companion_clients(
    client,
    fake_redis,
    oauth_assert_no_leaks,
):
    fake_redis.set("google_oauth_state:companion-contract-state", "phase3-companion-contract", ex=600)

    response = await _callback(client)

    _assert_oauth_route_exists(response, CALLBACK_PATH)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["session_token"] == data["access_token"]
    assert data["refresh_token"]
    assert "user" in data and "project" in data and "accessible_projects" in data
    assert "google_access_token" not in data
    assert "google_refresh_token" not in data
    assert "id_token" not in data
    assert "provider_sub" not in data
    oauth_assert_no_leaks(response, context="companion LoginResponse-compatible callback")


@pytest.mark.asyncio
async def test_contract_skew_failure_is_actionable_without_real_hashes_or_google_tokens(
    client,
    fake_provider_init_redeemer,
    monkeypatch,
    oauth_assert_no_leaks,
):
    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "true")
    skewed_token = "fake-provider-init-contract-skew-token-not-real"
    fake_provider_init_redeemer.add_token(
        skewed_token,
        {"provider": "google", "purpose": "login", "return_origin": "http://localhost:3000"},
    )

    with _patched_provider_init(fake_provider_init_redeemer):
        response = await _start(
            client,
            {
                "provider_init_token": skewed_token,
                "redirect_uri": "http://localhost:8000/auth/google/callback",
                "return_origin": "http://localhost:3000",
            },
        )

    _assert_oauth_route_exists(response, START_PATH)
    assert response.status_code in {400, 401, 403}
    body = response.text.lower()
    assert "contract" in body or "provider-init" in body or "binding" in body
    assert "google_access_token" not in body
    assert "google_refresh_token" not in body
    assert "id_token" not in body
    oauth_assert_no_leaks(response, context="contract skew error response")
