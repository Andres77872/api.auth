"""RED integration contracts for Patreon link/proof lifecycle.

Trace: `.dev/sdd/changes/patreon-account-link/tasks.md` task `1.9`.

Patreon is entitlement/link proof only.  These tests intentionally fail until
`src/routes/auth_patreon.py` and its no-login proof pipeline exist.  Collection
must stay clean while production modules are absent.
"""

from __future__ import annotations

import copy
import json
from contextlib import ExitStack, contextmanager
from importlib import import_module
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import MagicMock, patch

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "patreon"
MANIFEST = FIXTURE_ROOT / "manifest.json"

LINK_REQUEST_PATH = "/auth/patreon/link/request"
LINK_CONFIRM_PATH = "/auth/patreon/link/confirm"
LINK_STATUS_PATH = "/auth/patreon/link/status"
LINK_UNLINK_PATH = "/auth/patreon/link"

pytestmark = pytest.mark.usefixtures("integration_env")

FORBIDDEN_SESSION_FIELDS = {
    "access_token",
    "refresh_token",
    "session_token",
    "api_key",
    "token_type",
    "expires_in",
    "refresh_expires_in",
}

RAW_PATREON_SENTINELS = {
    "user-fixture-linked-001",
    "member-active-alpha-001",
    "member-mismatch-alpha-001",
    "member-hidden-email-alpha-001",
    "campaign-mw-alpha",
    "tier-mw-alpha-artisan",
    "patron-linked@example.test",
    "patron-different@example.test",
}


@pytest.fixture
async def client():
    """Phase 5 isolated ASGI client for the unregistered Patreon link router.

    Runtime registration in ``src/main.py`` is intentionally deferred to SDD
    Phase 9.  These Phase 5 proof-lifecycle tests mount only
    ``auth_patreon.router`` in a throwaway app so task 5.8 can validate the
    route behavior without starting Phase 9 router wiring.
    """

    from fastapi import FastAPI

    from src.middleware.error_handler import register_exception_handlers
    from src.routes import auth_patreon

    test_app = FastAPI(title="Patreon Phase 5 Test App")
    register_exception_handlers(test_app)
    test_app.include_router(auth_patreon.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app),
        base_url="http://test",
    ) as ac:
        yield ac


def _manifest() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _member_fixture(name: str) -> dict[str, Any]:
    rel_path = _manifest()["member_fixtures"][name]
    return json.loads((FIXTURE_ROOT / rel_path).read_text(encoding="utf-8"))


def _iter_mapping_keys(value: Any):
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _iter_mapping_keys(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_mapping_keys(item)


def _json_or_empty(response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _is_unimplemented_route(response) -> bool:
    body = response.text.lower()
    return response.status_code == 404 and "not found" in body and "patreon" not in body


def _assert_patreon_route_exists(response, method: str, path: str) -> None:
    if _is_unimplemented_route(response):
        pytest.fail(
            f"missing future Patreon route {method} {path}; SDD tasks 5.1-5.5 must "
            "implement link request/confirm/status/unlink without login/session issuance",
            pytrace=False,
        )


def _assert_no_session_material(response) -> None:
    data = _json_or_empty(response)
    keys = {key.lower() for key in _iter_mapping_keys(data)}
    leaked = FORBIDDEN_SESSION_FIELDS.intersection(keys)
    assert not leaked, f"Patreon link/proof response must not expose session/token fields: {sorted(leaked)}"
    for cookie_name in ("session_token", "refresh_token", "access_token"):
        assert cookie_name not in response.cookies, f"Patreon route must not set {cookie_name} cookie"


def _assert_no_raw_patreon_leaks(response, *, context: str) -> None:
    body = response.text
    leaked = sorted(value for value in RAW_PATREON_SENTINELS if value in body)
    assert not leaked, f"raw Patreon provider data leaked in {context}: {leaked[:3]}"


def _auth_headers(*, reauth: bool = True) -> dict[str, str]:
    headers = {
        "Authorization": "Bearer test-token",
        "User-Agent": "patreon-link-proof-red-test",
    }
    if reauth:
        # Future route code may accept this only as a test seam.  Real production
        # must use local password/MFA/session proof, not a browser-controlled flag.
        headers["X-Test-Recent-Reauth"] = "true"
    return headers


async def _post_link_request(client, payload: Mapping[str, Any] | None = None, *, reauth: bool = True, headers=None):
    return await client.post(
        LINK_REQUEST_PATH,
        json=dict(payload or {"patreon_email_hint": "patron-linked@example.test", "explicit_user_intent": True}),
        headers=headers or _auth_headers(reauth=reauth),
    )


async def _post_confirm(client, payload: Mapping[str, Any] | None = None, *, reauth: bool = True):
    return await client.post(
        LINK_CONFIRM_PATH,
        json=dict(payload or {"token": "plp-valid-lookup.fixture-secret", "explicit_user_intent": True}),
        headers=_auth_headers(reauth=reauth),
    )


async def _get_status(client):
    return await client.get(LINK_STATUS_PATH, headers=_auth_headers())


async def _delete_link(client, *, reauth: bool = True):
    return await client.delete(LINK_UNLINK_PATH, headers=_auth_headers(reauth=reauth))


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


class PatreonProofHarness:
    """Route seam fake for future GREEN code; records only sanitized evidence."""

    def __init__(self, member_fixture_name: str = "active_mapped"):
        self.member_fixture_name = member_fixture_name
        self.member_payload = _member_fixture(member_fixture_name)
        self.member_email = self.member_payload["data"][0]["attributes"].get("email")
        self.proof_emails = []
        self.activations = []
        self.unlinks = []
        self.resyncs = []
        self.status_response = {
            "success": True,
            "link_status": "linked" if self.member_email else "blocked",
            "entitlement": {
                "external_source": "patreon" if self.member_email else None,
                "status": "active" if self.member_email else "pending",
                "plan_code": "magic_worlds_plus" if self.member_email else "free",
                "tier_code": "artisan" if self.member_email else None,
                "link_status": "linked" if self.member_email else "blocked",
                "classification_version": 1,
            },
        }

        self.patreon_client = MagicMock(name="fake_patreon_client")
        self.patreon_client.find_member_for_link = MagicMock(return_value=copy.deepcopy(self.member_payload))
        self.patreon_client.get_member_by_email_hint = MagicMock(return_value=copy.deepcopy(self.member_payload))
        self.patreon_client.lookup_member = MagicMock(return_value=copy.deepcopy(self.member_payload))

        self.db = MagicMock(name="fake_db_patreon")
        self.db.create_or_reuse_link_request.return_value = {"link_request_id": "plr-fixture-001", "status": "pending"}
        self.db.create_link_proof.side_effect = self._create_proof
        self.db.enqueue_link_proof_email.side_effect = self._create_proof
        self.db.consume_link_proof.return_value = {"consume_status": "consumed", "proof_id": "plp-fixture-001"}
        self.db.activate_link.side_effect = self._activate
        self.db.get_link_status.return_value = copy.deepcopy(self.status_response)
        self.db.unlink_account.side_effect = self._unlink
        self.db.enqueue_resync.side_effect = self.resyncs.append

    def _create_proof(self, *args, **kwargs):
        email = kwargs.get("recipient_email") or kwargs.get("proof_email") or self.member_email
        self.proof_emails.append({"recipient_email": email, "kwargs": kwargs})
        return {"proof_id": "plp-fixture-001", "recipient_email": email, "status": "queued"}

    def _activate(self, *args, **kwargs):
        self.activations.append({"args_count": len(args), "kwargs": kwargs})
        return copy.deepcopy(self.status_response)

    def _unlink(self, *args, **kwargs):
        self.unlinks.append({"args_count": len(args), "kwargs": kwargs})
        return {"success": True, "link_status": "unlinked", "entitlement": {"status": "free", "plan_code": "free"}}


def _reauth_required(*args, **kwargs):
    from src.Util.error_handler import AuthenticationError, ErrorCode

    raise AuthenticationError(
        message="Recent reauthentication required",
        error_code=ErrorCode.MFA_REQUIRED,
        details={"operation": "patreon_link"},
    )


@contextmanager
def _patched_link_seams(harness: PatreonProofHarness, *, recent_reauth: bool = True, conflict: bool = False):
    reauth = MagicMock(return_value=True) if recent_reauth else MagicMock(side_effect=_reauth_required)
    if conflict:
        harness.db.activate_link.side_effect = RuntimeError("provider identity already linked to another user")

    forbidden_local_email_mutation = MagicMock(side_effect=AssertionError("Patreon must not activate local email state"))
    forbidden_session_revocation = MagicMock(side_effect=AssertionError("Patreon unlink must not revoke local auth sessions"))

    with _optional_patch_targets(
        (
            "src.routes.auth_patreon.load_patreon_config",
            "src.Util.patreon.config.load_patreon_config",
        ),
        MagicMock(return_value=MagicMock(linking_enabled=True, sync_enabled=True, explicit_test_runtime=True)),
    ), _optional_patch_targets(
        (
            "src.routes.auth_patreon.require_recent_reauthentication",
            "src.Util.auth_flow.require_recent_reauthentication",
        ),
        reauth,
    ), _optional_patch_targets(
        (
            "src.routes.auth_patreon.PatreonClient",
            "src.Util.patreon.client.PatreonClient",
        ),
        MagicMock(return_value=harness.patreon_client),
    ), _optional_patch_targets(
        (
            "src.routes.auth_patreon.patreon_client",
            "src.routes.auth_patreon.client",
        ),
        harness.patreon_client,
    ), _optional_patch_targets(
        (
            "src.routes.auth_patreon.db_patreon",
            "src.Util.db.db_patreon",
        ),
        harness.db,
    ), _optional_patch_targets(
        (
            "src.routes.auth_patreon.db_email.consume_email_activation_token",
            "src.Util.db.db_email.consume_email_activation_token",
            "src.routes.auth_patreon.activate_user_email",
            "src.Util.db.update_user",
            "src.routes.auth_patreon.update_user",
        ),
        forbidden_local_email_mutation,
    ), _optional_patch_targets(
        (
            "src.routes.auth_patreon.revoke_user_auth_state",
            "src.Util.auth_lifecycle.revoke_user_auth_state",
            "src.Util.auth_lifecycle.revoke_user_auth_state_except_current",
        ),
        forbidden_session_revocation,
    ):
        yield harness


@pytest.mark.asyncio
async def test_unauthenticated_link_request_is_rejected_without_provider_lookup(client):
    harness = PatreonProofHarness("active_mapped")

    with _patched_link_seams(harness):
        response = await _post_link_request(client, headers={"User-Agent": "patreon-link-no-auth-test"})

    _assert_patreon_route_exists(response, "POST", LINK_REQUEST_PATH)
    assert response.status_code in {401, 403}
    assert harness.patreon_client.method_calls == [], "Patreon API must not be queried before local authentication"
    _assert_no_session_material(response)


@pytest.mark.asyncio
async def test_link_request_requires_recent_local_reauthentication_before_creating_proof(client):
    harness = PatreonProofHarness("active_mapped")

    with _patched_link_seams(harness, recent_reauth=False):
        response = await _post_link_request(client, reauth=False)

    _assert_patreon_route_exists(response, "POST", LINK_REQUEST_PATH)
    assert response.status_code in {401, 403}
    assert harness.proof_emails == []
    assert harness.activations == []
    _assert_no_session_material(response)


@pytest.mark.asyncio
async def test_email_match_confirmation_can_activate_link_but_never_issues_local_session(client):
    harness = PatreonProofHarness("active_mapped")

    payload = {
        "patreon_email_hint": "patron-linked@example.test",
        "explicit_user_intent": True,
        "confirm_email_match": True,
    }
    with _patched_link_seams(harness):
        response = await _post_link_request(client, payload)

    _assert_patreon_route_exists(response, "POST", LINK_REQUEST_PATH)
    assert response.status_code in {200, 202}
    data = _json_or_empty(response)
    assert data.get("link_status") in {"pending", "linked", None}
    _assert_no_session_material(response)
    _assert_no_raw_patreon_leaks(response, context="email-match confirmation")


@pytest.mark.asyncio
async def test_mismatched_email_requires_email_loop_proof_to_patreon_api_email_only(client):
    harness = PatreonProofHarness("mismatched_email")

    payload = {
        "patreon_email_hint": "local-owner@example.test",
        "explicit_user_intent": True,
    }
    with _patched_link_seams(harness):
        response = await _post_link_request(client, payload)

    _assert_patreon_route_exists(response, "POST", LINK_REQUEST_PATH)
    assert response.status_code in {200, 202}
    assert harness.activations == [], "mismatched email must not grant entitlement before email-loop proof succeeds"
    if harness.proof_emails:
        assert harness.proof_emails[-1]["recipient_email"] == "patron-different@example.test"
    _assert_no_session_material(response)
    _assert_no_raw_patreon_leaks(response, context="mismatched email proof request")


@pytest.mark.asyncio
async def test_hidden_or_null_patreon_email_blocks_v1_proof_without_user_supplied_fallback(client):
    harness = PatreonProofHarness("hidden_email")

    payload = {
        "patreon_email_hint": "attacker-supplied@example.test",
        "explicit_user_intent": True,
    }
    with _patched_link_seams(harness):
        response = await _post_link_request(client, payload)

    _assert_patreon_route_exists(response, "POST", LINK_REQUEST_PATH)
    assert response.status_code in {200, 202, 409}
    data = _json_or_empty(response)
    assert data.get("link_status") in {"blocked", "pending", None}
    assert not any(item.get("recipient_email") == "attacker-supplied@example.test" for item in harness.proof_emails)
    assert harness.activations == []
    _assert_no_session_material(response)


@pytest.mark.asyncio
async def test_valid_proof_consumes_once_and_confirm_response_contains_no_login_material(client):
    harness = PatreonProofHarness("mismatched_email")

    with _patched_link_seams(harness):
        first = await _post_confirm(client, {"lookup_id": "plp-fixture-001", "secret": "valid-fixture-secret"})
        second = await _post_confirm(client, {"lookup_id": "plp-fixture-001", "secret": "valid-fixture-secret"})

    _assert_patreon_route_exists(first, "POST", LINK_CONFIRM_PATH)
    _assert_patreon_route_exists(second, "POST", LINK_CONFIRM_PATH)
    assert first.status_code in {200, 202}
    assert second.status_code in {200, 202, 400, 401, 409}
    assert len(harness.activations) <= 1, "proof replay must not repeat link activation or entitlement side effects"
    _assert_no_session_material(first)
    _assert_no_session_material(second)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"token": "malformed"},
        {"lookup_id": "unknown-proof", "secret": "wrong-secret"},
        {"lookup_id": "expired-proof", "secret": "expired-secret"},
        {"lookup_id": "replayed-proof", "secret": "already-consumed-secret"},
    ],
)
async def test_invalid_expired_or_replayed_proof_is_generic_and_non_mutating(client, payload):
    harness = PatreonProofHarness("mismatched_email")
    harness.db.activate_link.side_effect = AssertionError("invalid proof must not activate a Patreon link")

    with _patched_link_seams(harness):
        response = await _post_confirm(client, payload)

    _assert_patreon_route_exists(response, "POST", LINK_CONFIRM_PATH)
    assert response.status_code in {202, 400, 401, 404, 409}
    assert harness.activations == []
    _assert_no_session_material(response)
    _assert_no_raw_patreon_leaks(response, context="invalid proof response")


@pytest.mark.asyncio
async def test_provider_identity_conflict_is_blocked_without_revealing_existing_user(client):
    harness = PatreonProofHarness("active_mapped")

    with _patched_link_seams(harness, conflict=True):
        response = await _post_confirm(client, {"lookup_id": "plp-conflict", "secret": "valid-fixture-secret"})

    _assert_patreon_route_exists(response, "POST", LINK_CONFIRM_PATH)
    assert response.status_code in {202, 400, 401, 403, 409}
    forbidden_disclosures = {"user a", "existing owner", "usr-conflict", "linked user", "patron-linked@example.test"}
    body = response.text.lower()
    assert not any(disclosure in body for disclosure in forbidden_disclosures)
    _assert_no_session_material(response)


@pytest.mark.asyncio
async def test_status_unlink_and_relink_are_owner_safe_soft_lifecycle_without_session_revocation(client):
    harness = PatreonProofHarness("active_mapped")

    with _patched_link_seams(harness):
        status = await _get_status(client)
        unlink = await _delete_link(client)
        relink = await _post_link_request(
            client,
            {"patreon_email_hint": "patron-linked@example.test", "explicit_user_intent": True},
        )

    _assert_patreon_route_exists(status, "GET", LINK_STATUS_PATH)
    _assert_patreon_route_exists(unlink, "DELETE", LINK_UNLINK_PATH)
    _assert_patreon_route_exists(relink, "POST", LINK_REQUEST_PATH)
    assert status.status_code in {200, 202}
    assert unlink.status_code in {200, 202, 204}
    assert relink.status_code in {200, 202, 409}
    _assert_no_session_material(status)
    _assert_no_session_material(unlink)
    _assert_no_session_material(relink)
    _assert_no_raw_patreon_leaks(status, context="link status")
    _assert_no_raw_patreon_leaks(unlink, context="unlink")
    _assert_no_raw_patreon_leaks(relink, context="relink")
