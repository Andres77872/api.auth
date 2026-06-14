"""Phase 3 RED integration contracts for ``POST /auth/google/start``.

Trace: `.dev/sdd/changes/google-oauth-login/tasks.md` task 3.1 plus
spec/design start-flow requirements. Future OAuth modules are intentionally not
imported at module import time so collection remains clean while Phase 8 is
still missing.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from importlib import import_module
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest


START_PATH = "/auth/google/start"
CALLBACK_URI = "http://localhost:8000/auth/google/callback"
RETURN_ORIGIN = "http://localhost:3000"

pytestmark = pytest.mark.usefixtures("integration_env")


def _start_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "provider_init_token": "fake-provider-init-token-not-real",
        "redirect_uri": CALLBACK_URI,
        "return_origin": RETURN_ORIGIN,
        "remember_me": False,
    }
    payload.update(overrides)
    return payload


async def _post_start(client, payload: dict[str, Any] | None = None):
    return await client.post(
        START_PATH,
        json=payload or _start_payload(),
        headers={"User-Agent": "phase3-google-oauth-start-test"},
        follow_redirects=False,
    )


def _is_unimplemented_route(response) -> bool:
    body = response.text.lower()
    return response.status_code == 404 and "not found" in body and "ext_8" not in body


def _assert_start_route_exists(response) -> None:
    if _is_unimplemented_route(response):
        pytest.fail(
            "missing future route POST /auth/google/start; Phase 8.2 must "
            "implement the start contract asserted by this RED test",
            pytrace=False,
        )


def _authorization_url(response) -> str:
    location = response.headers.get("location")
    if location:
        return location
    try:
        body = response.json()
    except ValueError:
        body = {}
    auth_url = body.get("authorization_url") or body.get("url")
    assert auth_url, "start success must return or redirect to a Google authorization URL"
    return auth_url


@contextmanager
def _optional_patch_targets(targets: tuple[str, ...], value: Any):
    """Patch likely future seams only after their modules exist."""
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
def _patched_start_seams(fake_provider_init_redeemer, oauth_activity_capture):
    fake_config = MagicMock(
        enabled=True,
        provisioning_mode="link_only",
        redirect_uris=[CALLBACK_URI],
        return_origins=[RETURN_ORIGIN],
        scopes="openid email",
    )
    with _optional_patch_targets(
        (
            "src.routes.auth_google.redeem_provider_init_token",
            "src.routes.auth_google.redeem_provider_init",
            "src.Util.provider_init.redeem_provider_init_token",
        ),
        fake_provider_init_redeemer.redeem_provider_init_token,
    ), _optional_patch_targets(
        (
            "src.routes.auth_google.load_google_oauth_config",
            "src.Util.google_oauth_config.load_google_oauth_config",
        ),
        MagicMock(return_value=fake_config),
    ), _optional_patch_targets(
        (
            "src.routes.auth_google.record_google_oauth_activity",
            "src.Util.activity_logger.record_google_oauth_activity",
        ),
        oauth_activity_capture.capture_async,
    ):
        yield


@pytest.mark.asyncio
async def test_google_oauth_start_denies_disabled_config_without_state_or_redirect(
    client,
    fake_redis,
    monkeypatch,
    oauth_assert_no_leaks,
):
    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "false")

    response = await _post_start(client)

    _assert_start_route_exists(response)
    assert response.status_code in {403, 404, 503}
    assert "location" not in response.headers
    assert not list(fake_redis.scan_iter(match="*google_oauth_state*"))
    oauth_assert_no_leaks(response, context="disabled start response")


@pytest.mark.asyncio
async def test_google_oauth_start_redeems_provider_init_and_builds_minimal_google_authorization_url(
    client,
    fake_provider_init_redeemer,
    oauth_activity_capture,
    monkeypatch,
    oauth_assert_no_leaks,
):
    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "true")

    with _patched_start_seams(fake_provider_init_redeemer, oauth_activity_capture):
        response = await _post_start(client)

    _assert_start_route_exists(response)
    assert response.status_code in {200, 302, 303}
    auth_url = _authorization_url(response)
    parsed = urlparse(auth_url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert query["response_type"] == ["code"]
    assert query["redirect_uri"] == [CALLBACK_URI]
    assert query["code_challenge_method"] == ["S256"]
    assert "state" in query and query["state"][0]
    assert "nonce" in query and query["nonce"][0]
    assert "code_challenge" in query and query["code_challenge"][0]
    assert set(query["scope"][0].split()) == {"openid", "email"}
    assert "profile" not in query["scope"][0].split()
    assert "offline_access" not in query["scope"][0].split()
    assert "access_type" not in query
    assert query.get("prompt") != ["consent"]
    assert fake_provider_init_redeemer.calls, "start must redeem provider-init server-side before Google redirect"
    oauth_assert_no_leaks(response, context="start success response")


@pytest.mark.asyncio
async def test_google_oauth_start_rejects_provider_init_failure_and_replay_without_creating_state(
    client,
    fake_redis,
    fake_provider_init_redeemer,
    oauth_activity_capture,
    monkeypatch,
    oauth_assert_no_leaks,
):
    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "true")
    rejected_token = "fake-provider-init-token-rejected-not-real"
    fake_provider_init_redeemer.reject_token(rejected_token, reason="provider_init_replay")

    with _patched_start_seams(fake_provider_init_redeemer, oauth_activity_capture):
        response = await _post_start(client, _start_payload(provider_init_token=rejected_token))

    _assert_start_route_exists(response)
    assert response.status_code in {400, 401, 403}
    assert "location" not in response.headers
    assert not list(fake_redis.scan_iter(match="*google_oauth_state*"))
    oauth_assert_no_leaks(response, context="provider-init rejected start response")


@pytest.mark.asyncio
async def test_google_oauth_start_enforces_exact_redirect_uri_and_return_origin_allowlists(
    client,
    fake_provider_init_redeemer,
    oauth_activity_capture,
    monkeypatch,
    oauth_assert_no_leaks,
):
    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "true")

    with _patched_start_seams(fake_provider_init_redeemer, oauth_activity_capture):
        bad_redirect = await _post_start(
            client,
            _start_payload(redirect_uri=f"{CALLBACK_URI}/"),
        )
        bad_origin = await _post_start(
            client,
            _start_payload(return_origin="http://evil.localhost:3000"),
        )

    for response in (bad_redirect, bad_origin):
        _assert_start_route_exists(response)
        assert response.status_code in {400, 403}
        assert "location" not in response.headers
        oauth_assert_no_leaks(response, context="allowlist rejection response")


@pytest.mark.asyncio
async def test_google_oauth_start_creates_redis_state_and_start_rate_limit_bucket(
    client,
    fake_redis,
    fake_provider_init_redeemer,
    oauth_activity_capture,
    monkeypatch,
):
    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "true")

    with _patched_start_seams(fake_provider_init_redeemer, oauth_activity_capture):
        response = await _post_start(client)

    _assert_start_route_exists(response)
    assert response.status_code in {200, 302, 303}
    redis_keys = [key.decode() if isinstance(key, bytes) else str(key) for key in fake_redis.scan_iter(match="*")]

    assert any("google_oauth_state" in key for key in redis_keys), "start must persist server-side OAuth state"
    assert any("google_oauth" in key and "rate" in key and "start" in key for key in redis_keys), (
        "start must apply the OAuth start/provider-init rate-limit bucket"
    )
