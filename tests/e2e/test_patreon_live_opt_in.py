"""Opt-in live Patreon smoke tests.

Trace: `.dev/sdd/changes/patreon-account-link/tasks.md` task `1.14`.

These tests are skipped by default and must never be required for normal local
acceptance. They only run when `RUN_PATREON_E2E=1` and all test creator/member
secrets are provided by the operator.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest


RUN_FLAG = "RUN_PATREON_E2E"
REQUIRED_LIVE_ENV = (
    "PATREON_LIVE_TEST_USER_HASH",
    "PATREON_S2S_BEARER_TOKEN",
    "PATREON_CREATOR_ACCESS_TOKEN",
    "PATREON_TEST_CAMPAIGN_ID",
    "PATREON_TEST_MEMBER_EMAIL",
)
FORBIDDEN_LIVE_FIELDS = {
    "access_token",
    "refresh_token",
    "session_token",
    "api_key",
    "patreon_user_id",
    "patreon_member_id",
    "patreon_campaign_id",
    "patreon_tier_id",
    "raw_patreon_email",
    "masked_patreon_email",
    "provider_sub_hash",
    "provider_sub_fingerprint",
    "x-patreon-signature",
    "webhook_secret",
    "creator_access_token",
    "creator_refresh_token",
    "patreon_payload",
}


@pytest.fixture
def live_patreon_config():
    if os.environ.get(RUN_FLAG, "").strip().lower() not in {"1", "true", "yes", "on"}:
        pytest.skip(f"live Patreon smoke disabled; set {RUN_FLAG}=1 to run")

    missing = [name for name in REQUIRED_LIVE_ENV if not os.environ.get(name)]
    if missing:
        pytest.fail(
            f"live Patreon smoke was enabled but required env vars are missing: {', '.join(missing)}",
            pytrace=False,
        )

    return {name: os.environ[name] for name in REQUIRED_LIVE_ENV}


def _assert_future_route_exists(response, path: str) -> None:
    if response.status_code == 404 and "not found" in response.text.lower():
        pytest.fail(f"missing future Patreon route {path}; live smoke cannot run until runtime wiring exists", pytrace=False)


def _assert_no_live_secret_or_provider_leak(response, *, context: str) -> None:
    try:
        payload: Any = response.json()
    except Exception:
        payload = response.text
    serialized = json.dumps(payload, sort_keys=True).lower() if not isinstance(payload, str) else payload.lower()
    for field in FORBIDDEN_LIVE_FIELDS:
        assert field not in serialized, f"{context}: forbidden field `{field}` leaked in live smoke response"
    assert os.environ.get("PATREON_CREATOR_ACCESS_TOKEN", "").lower() not in serialized
    assert "session_token" not in response.cookies
    assert "refresh_token" not in response.cookies


@pytest.mark.live_provider
@pytest.mark.asyncio
async def test_live_patreon_manual_resync_and_s2s_read_are_opt_in_only(client, e2e_env, live_patreon_config, monkeypatch):
    monkeypatch.setenv("PATREON_LINKING_ENABLED", "true")
    monkeypatch.setenv("PATREON_SYNC_ENABLED", "true")
    monkeypatch.setenv("PATREON_S2S_ENTITLEMENT_ENABLED", "true")

    user_hash = live_patreon_config["PATREON_LIVE_TEST_USER_HASH"]
    headers = {
        "Authorization": f"Bearer {live_patreon_config['PATREON_S2S_BEARER_TOKEN']}",
        "User-Agent": "patreon-live-opt-in-e2e-red-test",
    }
    resync_path = f"/internal/users/{user_hash}/entitlements/patreon/resync"
    read_path = f"/internal/users/{user_hash}/entitlements"

    resync = await client.post(resync_path, headers=headers)
    _assert_future_route_exists(resync, resync_path)
    assert resync.status_code in {200, 202}
    _assert_no_live_secret_or_provider_leak(resync, context="live manual resync")

    entitlement = await client.get(read_path, headers=headers)
    _assert_future_route_exists(entitlement, read_path)
    assert entitlement.status_code == 200
    _assert_no_live_secret_or_provider_leak(entitlement, context="live S2S entitlement read")

    payload = entitlement.json()
    assert payload.get("user_hash") == user_hash
    assert isinstance(payload.get("entitlement"), dict)
    assert payload["entitlement"].get("plan_code") is not None
