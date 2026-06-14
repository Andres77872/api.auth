"""Phase 3 RED acceptance tests for strict project/group hash secrecy.

Trace: `.dev/sdd/changes/google-oauth-login/tasks.md` task 3.3 and spec
scenarios requiring raw strict binding values to stay out of browser-visible,
audit, activity, and log surfaces.
"""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import ExitStack, contextmanager, nullcontext
from importlib import import_module
from typing import Any
from unittest.mock import patch

import pytest


START_PATH = "/auth/google/start"
CALLBACK_PATH = "/auth/google/callback"

pytestmark = pytest.mark.usefixtures("integration_env")


def _strict_sentinels() -> dict[str, str]:
    # Synthetic values only; failure messages report labels/paths, never values.
    seed = "phase3-google-oauth-strict-binding-contract"
    return {
        "project_hash": "ph_" + hashlib.sha256(f"{seed}:project".encode()).hexdigest(),
        "user_group_hash": "ugh_" + hashlib.sha256(f"{seed}:group".encode()).hexdigest(),
    }


async def _start(client, token: str):
    return await client.post(
        START_PATH,
        json={
            "provider_init_token": token,
            "redirect_uri": "http://localhost:8000/auth/google/callback",
            "return_origin": "http://localhost:3000",
        },
        headers={"User-Agent": "phase3-strict-hash-secrecy-test"},
        follow_redirects=False,
    )


async def _callback(client, *, code: str = "fake-google-auth-code-not-real", state: str = "strict-hash-state"):
    return await client.get(
        CALLBACK_PATH,
        params={"code": code, "state": state},
        headers={"User-Agent": "phase3-strict-hash-secrecy-test"},
        follow_redirects=False,
    )


def _is_unimplemented_route(response) -> bool:
    body = response.text.lower()
    return response.status_code == 404 and "not found" in body and "ext_8" not in body


def _assert_oauth_route_exists(response, path: str) -> None:
    if _is_unimplemented_route(response):
        pytest.fail(
            f"missing future OAuth route {path}; strict-hash secrecy acceptance "
            "cannot pass until Phase 8 route implementation exists",
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
def _patched_secrecy_seams(fake_provider_init_redeemer, oauth_audit_capture, oauth_activity_capture):
    redeem = getattr(fake_provider_init_redeemer, "redeem_provider_init_token", None)
    redeem_context = (
        _optional_patch_targets(
            (
                "src.routes.auth_google.redeem_provider_init_token",
                "src.routes.auth_google.redeem_provider_init",
                "src.Util.provider_init.redeem_provider_init_token",
            ),
            redeem,
        )
        if callable(redeem)
        else nullcontext()
    )
    with redeem_context, _optional_patch_targets(
        (
            "src.routes.auth_google.capture_oauth_audit",
            "src.routes.auth_google.record_oauth_audit",
        ),
        oauth_audit_capture.capture_async,
    ), _optional_patch_targets(
        (
            "src.routes.auth_google.record_google_oauth_activity",
            "src.Util.activity_logger.record_google_oauth_activity",
        ),
        oauth_activity_capture.capture_async,
    ):
        yield


def _log_surface(caplog) -> dict[str, list[str]]:
    application_records = [record for record in caplog.records if record.name.startswith("src.")]
    return {
        "messages": [record.getMessage() for record in application_records],
        "logger_names": [record.name for record in application_records],
    }


@pytest.mark.asyncio
async def test_strict_hashes_absent_from_start_success_url_headers_cookies_body_and_logs(
    client,
    fake_provider_init_redeemer,
    oauth_audit_capture,
    oauth_activity_capture,
    oauth_assert_no_leaks,
    caplog,
    monkeypatch,
):
    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "true")
    sentinels = _strict_sentinels()
    token = "fake-provider-init-strict-hash-success-token-not-real"
    fake_provider_init_redeemer.add_token(
        token,
        fake_provider_init_redeemer.default_payload | sentinels,
    )

    caplog.set_level(logging.INFO)
    with _patched_secrecy_seams(fake_provider_init_redeemer, oauth_audit_capture, oauth_activity_capture):
        response = await _start(client, token)

    _assert_oauth_route_exists(response, START_PATH)
    assert response.status_code in {200, 302, 303}
    oauth_assert_no_leaks(response, forbidden_values=sentinels, context="start success browser response")
    oauth_assert_no_leaks(_log_surface(caplog), forbidden_values=sentinels, context="start success logs")
    oauth_audit_capture.assert_no_leaks(sentinels)
    oauth_activity_capture.assert_no_leaks(sentinels)


@pytest.mark.asyncio
async def test_strict_hashes_absent_from_callback_success_login_response_and_cookies(
    client,
    fake_redis,
    oauth_audit_capture,
    oauth_activity_capture,
    oauth_assert_no_leaks,
    caplog,
):
    sentinels = _strict_sentinels()
    fake_redis.set(
        "google_oauth_state:strict-hash-state",
        json.dumps({"strict_binding": "server-side-only"}),
        ex=600,
    )

    caplog.set_level(logging.INFO)
    with _patched_secrecy_seams(
        fake_provider_init_redeemer=type("NoopRedeemer", (), {"redeem_provider_init_token": None})(),
        oauth_audit_capture=oauth_audit_capture,
        oauth_activity_capture=oauth_activity_capture,
    ):
        response = await _callback(client)

    _assert_oauth_route_exists(response, CALLBACK_PATH)
    assert response.status_code == 200
    oauth_assert_no_leaks(response, forbidden_values=sentinels, context="callback success browser response")
    oauth_assert_no_leaks(_log_surface(caplog), forbidden_values=sentinels, context="callback success logs")
    oauth_audit_capture.assert_no_leaks(sentinels)
    oauth_activity_capture.assert_no_leaks(sentinels)


@pytest.mark.asyncio
async def test_strict_hashes_absent_from_callback_failure_and_companion_facing_error_surface(
    client,
    oauth_audit_capture,
    oauth_activity_capture,
    oauth_assert_no_leaks,
    caplog,
):
    sentinels = _strict_sentinels()

    caplog.set_level(logging.INFO)
    with _patched_secrecy_seams(
        fake_provider_init_redeemer=type("NoopRedeemer", (), {"redeem_provider_init_token": None})(),
        oauth_audit_capture=oauth_audit_capture,
        oauth_activity_capture=oauth_activity_capture,
    ):
        response = await _callback(client, state="missing-or-expired-state")

    _assert_oauth_route_exists(response, CALLBACK_PATH)
    assert response.status_code in {400, 401, 403}
    oauth_assert_no_leaks(response, forbidden_values=sentinels, context="callback failure browser response")
    oauth_assert_no_leaks(_log_surface(caplog), forbidden_values=sentinels, context="callback failure logs")
    oauth_audit_capture.assert_no_leaks(sentinels)
    oauth_activity_capture.assert_no_leaks(sentinels)
