"""Phase 1 RED tests for the Patreon S2S entitlement boundary.

Trace: `.dev/sdd/changes/patreon-account-link/tasks.md` task `1.11`.

These tests started as RED proofs.  The Phase 7 validation gate now imports and
mounts the isolated internal router directly because production registration in
``src.main`` is intentionally deferred to Phase 9.
"""

from __future__ import annotations

import json
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI

from src.Util import auth_constants as constants
from src.routes import internal_patreon


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "patreon"
MANIFEST_PATH = FIXTURE_ROOT / "manifest.json"

S2S_TOKEN = "test-patreon-s2s-token-not-real"
S2S_PATH = "/internal/users/{user_hash}/entitlements"
MAGIC_WORLDS_CONTRACT_CASES = ("linked", "unlinked", "stale", "unknown_tier", "revoked")
MAGIC_WORLDS_FIXTURE_NOW = datetime(2026, 6, 16, 12, 0, 0, tzinfo=timezone.utc)

SAFE_TOP_LEVEL_FIELDS = {"success", "message", "user_hash", "entitlement", "contract_version"}
SAFE_ENTITLEMENT_FIELDS = {
    "external_source",
    "status",
    "plan_code",
    "tier_code",
    "tier_name",
    "link_status",
    "next_renewal_at",
    "grace_period_until",
    "last_synced_at",
    "stale_after",
    "classification_version",
}
RAW_PROVIDER_VALUE_FRAGMENTS = (
    "patron-linked@example.test",
    "patron-unknown-tier@example.test",
    "campaign-mw-",
    "tier-mw-",
    "member-active-",
    "member-unknown-tier-",
    "user-fixture-",
    "x-patreon-signature",
    "webhook_secret",
    "creator_access_token",
    "creator_refresh_token",
    "provider_sub_hash",
    "provider_sub_fingerprint",
)

pytestmark = pytest.mark.usefixtures("integration_env")


@pytest.fixture
def app():
    """Mount only the Phase 7 internal Patreon router for S2S contract tests.

    Router registration in ``src.main`` is intentionally deferred to Phase 9,
    so this validation gate must prove the route contract through an isolated
    FastAPI app instead of mutating production runtime wiring.
    """

    test_app = FastAPI(title="Patreon S2S Contract Test App")
    test_app.include_router(internal_patreon.router)
    return test_app


def _manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _contract_fixture(name: str) -> dict[str, Any]:
    path = FIXTURE_ROOT / _manifest()["s2s_contract_fixtures"][name]
    return json.loads(path.read_text(encoding="utf-8"))


def _path(user_hash: str) -> str:
    return S2S_PATH.format(user_hash=user_hash)


def _auth_headers(token: str = S2S_TOKEN) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": "patreon-s2s-red-contract-test",
    }


def _json_or_text(response) -> Any:
    try:
        return response.json()
    except Exception:
        return response.text


def _parse_contract_datetime(value: Any, *, field: str, context: str) -> datetime | None:
    if value is None:
        return None
    assert isinstance(value, str) and value, f"{context}: `{field}` must be an ISO-8601 string when present"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        pytest.fail(f"{context}: `{field}` is not valid ISO-8601: {value!r}", pytrace=False)
    assert parsed.tzinfo is not None and parsed.utcoffset() is not None, f"{context}: `{field}` must be timezone-aware"
    return parsed


def _fail_if_future_route_missing(response, path: str) -> None:
    body = response.text.lower()
    if response.status_code == 404 and "not found" in body:
        pytest.fail(
            f"missing future Patreon S2S route {path}; task 7.1 must register "
            "the dedicated internal entitlement endpoint before this RED proof can pass",
            pytrace=False,
        )


def _assert_contract_shape(payload: dict[str, Any], *, context: str, require_top_level_version: bool = False) -> None:
    assert set(payload) <= SAFE_TOP_LEVEL_FIELDS, f"{context} exposes non-S2S top-level fields: {set(payload) - SAFE_TOP_LEVEL_FIELDS}"
    assert payload.get("success") is True, context
    assert isinstance(payload.get("user_hash"), str) and payload["user_hash"], context
    if require_top_level_version:
        assert payload.get("contract_version") == constants.PATREON_DEFAULT_CONTRACT_VERSION, (
            f"{context} must expose the versioned Magic Worlds S2S contract"
        )

    entitlement = payload.get("entitlement")
    assert isinstance(entitlement, dict), f"{context} must include a normalized entitlement object"
    assert set(entitlement) == SAFE_ENTITLEMENT_FIELDS, (
        f"{context} entitlement DTO must stay fixture-aligned and allow-listed; "
        f"unexpected={set(entitlement) - SAFE_ENTITLEMENT_FIELDS}, missing={SAFE_ENTITLEMENT_FIELDS - set(entitlement)}"
    )


def _assert_versioned_magic_worlds_contract(
    payload: dict[str, Any],
    *,
    context: str,
    require_top_level_version: bool = False,
) -> None:
    entitlement = payload["entitlement"]
    classification_version = entitlement.get("classification_version")
    assert classification_version == constants.PATREON_DEFAULT_CONTRACT_VERSION, (
        f"{context} must carry classification version {constants.PATREON_DEFAULT_CONTRACT_VERSION}"
    )
    if require_top_level_version or "contract_version" in payload:
        assert payload.get("contract_version") == classification_version, (
            f"{context} top-level contract version must match the entitlement classification version"
        )
    assert _manifest()["fixture_set"].endswith(f".v{classification_version}"), (
        f"{context} fixture set must advertise the same v{classification_version} contract"
    )


def _assert_magic_worlds_bounded_staleness(payload: dict[str, Any], *, context: str) -> None:
    entitlement = payload["entitlement"]
    last_synced_at = _parse_contract_datetime(
        entitlement.get("last_synced_at"),
        field="last_synced_at",
        context=context,
    )
    stale_after = _parse_contract_datetime(
        entitlement.get("stale_after"),
        field="stale_after",
        context=context,
    )

    requires_bounded_staleness = (
        entitlement.get("external_source") == "patreon"
        and entitlement.get("link_status") == "linked"
        and entitlement.get("status") in {"active", "pending", "stale"}
    )
    if requires_bounded_staleness:
        assert last_synced_at is not None, f"{context}: Magic Worlds needs last_synced_at for cache freshness"
        assert stale_after is not None, f"{context}: Magic Worlds needs stale_after for bounded cache staleness"
        assert stale_after > last_synced_at, f"{context}: stale_after must be after last_synced_at"
        staleness_window = (stale_after - last_synced_at).total_seconds()
        assert 0 < staleness_window <= constants.DEFAULT_PATREON_SYNC_STALE_AFTER_SECONDS, (
            f"{context}: staleness window must be bounded by api.auth freshness policy"
        )

    if entitlement.get("status") == "stale":
        assert stale_after is not None and stale_after <= MAGIC_WORLDS_FIXTURE_NOW, (
            f"{context}: stale fixture must be recognizably stale to the companion cache"
        )

    if entitlement.get("link_status") in {"unlinked", "revoked"}:
        assert stale_after is None, f"{context}: terminal/free projections must not imply a paid cache freshness window"


def _assert_safe_free_or_unlinked_projection(payload: dict[str, Any], *, context: str) -> None:
    entitlement = payload["entitlement"]
    if entitlement.get("link_status") in {"none", "unlinked"}:
        assert entitlement.get("external_source") is None, f"{context}: terminal/free response must not project Patreon as active source"
        assert entitlement.get("status") == "free", f"{context}: terminal/free response must be safe free"
        assert entitlement.get("plan_code") == "free", f"{context}: terminal/free response must not grant a paid plan"
        assert entitlement.get("tier_code") is None, f"{context}: terminal/free response must not include a paid tier code"
        assert entitlement.get("tier_name") is None, f"{context}: terminal/free response must not include a paid tier name"
        assert entitlement.get("next_renewal_at") is None, f"{context}: terminal/free response must not include renewal metadata"
        assert entitlement.get("grace_period_until") is None, f"{context}: terminal/free response must not include grace metadata"
        assert entitlement.get("stale_after") is None, f"{context}: terminal/free response must not include paid-cache staleness metadata"

    if entitlement.get("link_status") == "revoked":
        assert entitlement.get("status") == "revoked", f"{context}: revoked response must preserve the revoked lifecycle state"
        assert entitlement.get("plan_code") == "free", f"{context}: revoked response must not grant a paid plan"
        assert entitlement.get("tier_code") is None, f"{context}: revoked response must not include a paid tier code"
        assert entitlement.get("tier_name") is None, f"{context}: revoked response must not include a paid tier name"

    if entitlement.get("plan_code") == "free":
        assert entitlement.get("tier_code") is None, f"{context}: free projections must not carry a tier code"
        assert entitlement.get("tier_name") is None, f"{context}: free projections must not carry a tier name"


def _assert_no_raw_provider_internals(payload: Any, *, context: str) -> None:
    forbidden_fields = {field.lower() for field in _manifest()["forbidden_s2s_and_client_fields"]}

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                lowered_key = str(key).lower()
                assert lowered_key not in forbidden_fields, f"{context}: forbidden field `{path}.{key}` leaked"
                walk(child, f"{path}.{key}")
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")
            return
        if isinstance(value, str):
            lowered_value = value.lower()
            for fragment in RAW_PROVIDER_VALUE_FRAGMENTS:
                assert fragment not in lowered_value, f"{context}: raw provider value fragment `{fragment}` leaked at {path}"

    walk(payload, "$root")


def _assert_generic_denial(response, *, context: str) -> None:
    payload = _json_or_text(response)
    _assert_no_raw_provider_internals(payload, context=context)
    body = response.text.lower()
    assert "linked user" not in body
    assert "member exists" not in body
    assert "campaign" not in body
    assert "tier" not in body
    assert "patreon email" not in body


@contextmanager
def _optional_patch_targets(targets: tuple[str, ...], value: Any) -> Iterator[MagicMock]:
    with ExitStack() as stack:
        for target in targets:
            module_name, _, _ = target.rpartition(".")
            try:
                import_module(module_name)
            except ImportError:
                continue
            stack.enter_context(patch(target, value, create=True))
        yield value


@contextmanager
def _patched_entitlement_result(result: dict[str, Any] | None) -> Iterator[MagicMock]:
    """Patch likely future DB/service seams without requiring them today."""

    mock = MagicMock(return_value=result)
    with _optional_patch_targets(
        (
            "src.routes.internal_patreon.get_entitlement_by_user_hash",
            "src.routes.internal_patreon.get_patreon_entitlement_by_user_hash",
            "src.Util.db.db_patreon.get_entitlement_by_user_hash",
            "src.Util.db.db_patreon.get_patreon_entitlement_by_user_hash",
        ),
        mock,
    ):
        yield mock


@pytest.mark.asyncio
async def test_s2s_entitlement_requires_dedicated_bearer_and_rejects_cookie_only(client, monkeypatch):
    monkeypatch.setenv("PATREON_S2S_ENTITLEMENT_ENABLED", "true")
    monkeypatch.setenv("PATREON_S2S_BEARER_TOKEN", S2S_TOKEN)

    linked = _contract_fixture("linked")
    path = _path(linked["user_hash"])

    no_auth = await client.get(path, headers={"User-Agent": "patreon-s2s-red-contract-test"})
    assert no_auth.status_code in {401, 403}, "S2S endpoint must reject missing dedicated bearer auth"
    _assert_generic_denial(no_auth, context="missing bearer denial")

    cookie_only = await client.get(
        path,
        cookies={"session_token": "local-session-cookie-must-not-authorize-s2s"},
        headers={"User-Agent": "patreon-s2s-red-contract-test"},
    )
    assert cookie_only.status_code in {401, 403}, "browser cookies must never authorize the internal S2S endpoint"
    _assert_generic_denial(cookie_only, context="cookie-only denial")

    wrong_bearer = await client.get(path, headers=_auth_headers("wrong-patreon-s2s-token-not-real"))
    assert wrong_bearer.status_code in {401, 403}, "invalid S2S bearer must be denied generically"
    _assert_generic_denial(wrong_bearer, context="wrong bearer denial")


@pytest.mark.asyncio
async def test_s2s_unknown_user_returns_safe_free_projection_for_magic_worlds(client, monkeypatch):
    monkeypatch.setenv("PATREON_S2S_ENTITLEMENT_ENABLED", "true")
    monkeypatch.setenv("PATREON_S2S_BEARER_TOKEN", S2S_TOKEN)

    with _patched_entitlement_result(None):
        response = await client.get(_path("usr_contract_unknown_missing_001"), headers=_auth_headers())

    assert response.status_code == 200
    payload = response.json()
    _assert_contract_shape(payload, context="unknown user free S2S response", require_top_level_version=True)
    _assert_versioned_magic_worlds_contract(
        payload,
        context="unknown user free S2S response",
        require_top_level_version=True,
    )
    _assert_safe_free_or_unlinked_projection(payload, context="unknown user free S2S response")
    _assert_no_raw_provider_internals(payload, context="unknown user free S2S response")


@pytest.mark.parametrize("fixture_name", MAGIC_WORLDS_CONTRACT_CASES)
@pytest.mark.asyncio
async def test_authorized_s2s_read_returns_only_normalized_contract_fixtures(client, monkeypatch, fixture_name):
    monkeypatch.setenv("PATREON_S2S_ENTITLEMENT_ENABLED", "true")
    monkeypatch.setenv("PATREON_S2S_BEARER_TOKEN", S2S_TOKEN)

    expected = _contract_fixture(fixture_name)
    with _patched_entitlement_result(expected) as patched_lookup:
        response = await client.get(_path(expected["user_hash"]), headers=_auth_headers())

    _fail_if_future_route_missing(response, _path(expected["user_hash"]))
    assert response.status_code == 200
    payload = response.json()
    _assert_contract_shape(payload, context=f"{fixture_name} S2S response", require_top_level_version=True)
    _assert_versioned_magic_worlds_contract(
        payload,
        context=f"{fixture_name} S2S response",
        require_top_level_version=True,
    )
    _assert_magic_worlds_bounded_staleness(payload, context=f"{fixture_name} S2S response")
    _assert_safe_free_or_unlinked_projection(payload, context=f"{fixture_name} S2S response")
    _assert_no_raw_provider_internals(payload, context=f"{fixture_name} S2S response")
    assert payload["user_hash"] == expected["user_hash"]
    assert payload["entitlement"] == expected["entitlement"]
    assert "session_token" not in response.cookies
    assert "refresh_token" not in response.cookies
    assert patched_lookup.called, "the endpoint must read entitlement from the Patreon entitlement boundary, not auth/session state"


def test_s2s_fixture_manifest_covers_magic_worlds_companion_contract_cases():
    fixtures = _manifest()["s2s_contract_fixtures"]
    assert set(MAGIC_WORLDS_CONTRACT_CASES) <= set(fixtures), (
        "manifest must keep linked/unlinked/stale/unknown-tier/revoked S2S fixtures for Magic Worlds"
    )


@pytest.mark.parametrize("fixture_name", MAGIC_WORLDS_CONTRACT_CASES)
def test_s2s_contract_fixtures_encode_magic_worlds_companion_expectations(fixture_name):
    payload = _contract_fixture(fixture_name)
    _assert_contract_shape(payload, context=f"fixture {fixture_name}")
    _assert_versioned_magic_worlds_contract(payload, context=f"fixture {fixture_name}")
    _assert_magic_worlds_bounded_staleness(payload, context=f"fixture {fixture_name}")
    _assert_safe_free_or_unlinked_projection(payload, context=f"fixture {fixture_name}")
    _assert_no_raw_provider_internals(payload, context=f"fixture {fixture_name}")


@pytest.mark.asyncio
async def test_s2s_response_contract_fixtures_are_allow_listed_and_free_of_raw_provider_fields():
    for fixture_name in _manifest()["s2s_contract_fixtures"]:
        payload = _contract_fixture(fixture_name)
        _assert_contract_shape(payload, context=f"fixture {fixture_name}")
        _assert_no_raw_provider_internals(payload, context=f"fixture {fixture_name}")
