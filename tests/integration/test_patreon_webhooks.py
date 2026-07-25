"""RED integration contracts for Patreon webhook verification and idempotency.

Trace: `.dev/sdd/changes/patreon-account-link/tasks.md` task `1.10`.

These tests use the byte-exact fixtures from task `1.1`.  They must collect
cleanly before the production webhook route exists and then fail RED on the
missing `/webhooks/patreon` behavior.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from contextlib import ExitStack, contextmanager
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "patreon"
WEBHOOK_ROOT = FIXTURE_ROOT / "webhooks"
MANIFEST = FIXTURE_ROOT / "manifest.json"
EXPECTED_SIGNATURES = WEBHOOK_ROOT / "expected_signatures.json"
WEBHOOK_PATH = "/webhooks/patreon"

RAW_PROVIDER_SENTINELS = {
    "member-webhook-active-001",
    "member-webhook-partial-001",
    "member-webhook-unknown-tier-001",
    "user-fixture-linked-001",
    "campaign-mw-alpha",
    "tier-mw-alpha-artisan",
    "tier-mw-alpha-unknown",
    "patron-linked@example.test",
    "patron-unknown-tier@example.test",
}


@pytest.fixture
async def client():
    """Phase 6 isolated ASGI client for the unregistered webhook router.

    Runtime registration in ``src/main.py`` is intentionally deferred to SDD
    Phase 9. These Phase 6 webhook tests mount only
    ``patreon_webhooks.router`` in a throwaway app so task 6.7 validates the
    route behavior without starting Phase 9 router wiring.
    """

    from fastapi import FastAPI

    from src.middleware.error_handler import register_exception_handlers
    from src.routes import patreon_webhooks

    test_app = FastAPI(title="Patreon Phase 6 Test App")
    register_exception_handlers(test_app)
    test_app.include_router(patreon_webhooks.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app),
        base_url="http://test",
    ) as ac:
        yield ac


def _manifest() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _signature_manifest() -> dict[str, Any]:
    return json.loads(EXPECTED_SIGNATURES.read_text(encoding="utf-8"))


def _fixture_filename(key: str) -> str:
    rel_path = _manifest()["webhook_fixtures"][key]
    return Path(rel_path).name


def _raw_fixture(key: str) -> bytes:
    rel_path = _manifest()["webhook_fixtures"][key]
    return (FIXTURE_ROOT / rel_path).read_bytes()


def _fixture_meta(key: str) -> dict[str, Any]:
    return _signature_manifest()["fixtures"][_fixture_filename(key)]


def _signed_headers(key: str, *, signature: str | None = None, event: str | None = None) -> dict[str, str]:
    meta = _fixture_meta(key)
    return {
        "Content-Type": "application/json",
        "User-Agent": "patreon-webhook-red-test",
        "X-Patreon-Event": event or meta["event"],
        "X-Patreon-Signature": signature if signature is not None else meta["signature"],
    }


def _signature_for(raw_body: bytes, secret: str | None = None) -> str:
    fixture_secret = secret or _signature_manifest()["fixture_secret"]
    return hmac.new(fixture_secret.encode("utf-8"), raw_body, hashlib.md5).hexdigest()


def _assert_fixture_bytes_match_manifest(key: str) -> None:
    raw_body = _raw_fixture(key)
    meta = _fixture_meta(key)
    assert len(raw_body) == meta["byte_length"]
    assert hashlib.sha256(raw_body).hexdigest() == meta["raw_body_sha256"]
    assert _signature_for(raw_body) == meta["signature"]


def _is_unimplemented_route(response) -> bool:
    body = response.text.lower()
    return response.status_code == 404 and "not found" in body and "patreon" not in body


def _assert_webhook_route_exists(response) -> None:
    if _is_unimplemented_route(response):
        pytest.fail(
            "missing future route POST /webhooks/patreon; SDD tasks 6.1-6.5 must "
            "verify HMAC-MD5 raw bodies, dedupe deliveries, and enqueue resync safely",
            pytrace=False,
        )


def _assert_no_session_or_raw_provider_leaks(response, *, context: str) -> None:
    for cookie_name in ("session_token", "refresh_token", "access_token"):
        assert cookie_name not in response.cookies, f"webhook must not set local auth cookie {cookie_name}"

    leaked = sorted(value for value in RAW_PROVIDER_SENTINELS if value in response.text)
    assert not leaked, f"raw Patreon provider data leaked in {context}: {leaked[:3]}"


async def _post_webhook(client, raw_body: bytes, headers: dict[str, str]):
    return await client.post(WEBHOOK_PATH, content=raw_body, headers=headers)


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


class WebhookCapture:
    def __init__(self):
        self.deliveries = []
        self.classifications = []
        self.resyncs = []
        self.membership_observations = []
        self.current_updates = []

        self.db = MagicMock(name="fake_db_patreon_webhooks")
        self.db.record_webhook_delivery.side_effect = self._record_delivery
        self.db.record_patreon_webhook_delivery.side_effect = self._record_delivery
        self.db.resolve_patreon_link_by_provider_hash.side_effect = self._resolve_link
        self.db.get_patreon_link_by_provider_sub_hash.side_effect = self._resolve_link
        self.db.get_entitlement_by_user_hash.side_effect = self._current_snapshot
        self.db.observe_patreon_membership.side_effect = self._observe_membership
        self.db.upsert_patreon_entitlement_snapshot.side_effect = self._update_current
        self.db.mark_webhook_delivery_processed.return_value = {"status": "processed"}
        self.db.enqueue_sync_job.side_effect = self._enqueue_resync
        self.db.enqueue_resync.side_effect = self._enqueue_resync
        self.db.upsert_entitlement_snapshot.side_effect = self._update_current
        self.db.update_current_entitlement.side_effect = self._update_current

        self.classifier = MagicMock(name="fake_patreon_classifier", side_effect=self._classify)
        self.resync = MagicMock(name="fake_patreon_resync", side_effect=self._enqueue_resync)
        self.rate_limiter = MagicMock(name="fake_patreon_webhook_rate_limiter")
        self.rate_limiter.check_webhook_signature_failure.return_value = None
        self.activity_log = MagicMock(name="fake_patreon_webhook_activity_log", return_value=True)

    def _record_delivery(self, *args, **kwargs):
        delivery_hash = kwargs.get("delivery_hash") or kwargs.get("raw_body_sha256") or f"delivery-{len(self.deliveries)}"
        duplicate = any(item.get("delivery_hash") == delivery_hash for item in self.deliveries)
        record = {"delivery_hash": delivery_hash, "duplicate": duplicate, "kwargs": kwargs}
        self.deliveries.append(record)
        return {"status": "duplicate" if duplicate else "accepted", "duplicate": duplicate}

    def _classify(self, *args, **kwargs):
        self.classifications.append({"args_count": len(args), "kwargs": kwargs})
        return {"status": "active", "plan_code": "magic_worlds_plus", "tier_code": "artisan"}

    def _enqueue_resync(self, *args, **kwargs):
        self.resyncs.append({"args_count": len(args), "kwargs": kwargs})
        return {"status": "queued"}

    def _update_current(self, *args, **kwargs):
        self.current_updates.append({"args_count": len(args), "kwargs": kwargs})
        return {"status": "updated"}

    def _observe_membership(self, *args, **kwargs):
        self.membership_observations.append({"args_count": len(args), "kwargs": kwargs})
        return {"status": "observed"}

    def _resolve_link(self, *args, **kwargs):
        return {
            "user_id": "usr-webhook-linked-001",
            "id": "usr-webhook-linked-001",
            "user_hash": "usr-webhook-hash-001",
            "external_account_id": "uea-patreon-webhook-001",
        }

    def _current_snapshot(self, *args, **kwargs):
        return {
            "user_hash": "usr-webhook-hash-001",
            "status": "free",
            "plan_code": "free",
            "link_status": "linked",
        }


def _webhook_config() -> SimpleNamespace:
    return SimpleNamespace(
        webhooks_enabled=True,
        webhook_secret=_signature_manifest()["fixture_secret"],
        allowed_webhook_events={"members:create", "members:update", "members:delete", "members:pledge:update"},
        provider_sub_pepper="test-patreon-provider-sub-pepper-not-real-min-32-bytes!!",
        id_hmac_secret="test-patreon-id-hmac-secret-not-real-min-32-bytes!!",
        webhook_delivery_hash_pepper="test-patreon-delivery-hash-pepper-not-real-min-32-bytes!!",
        sync_stale_after_seconds=86400,
        explicit_test_runtime=True,
    )


@contextmanager
def _patched_webhook_seams(capture: WebhookCapture):
    with _optional_patch_targets(
        (
            "src.routes.patreon_webhooks.load_patreon_config",
            "src.Util.patreon.config.load_patreon_config",
        ),
        MagicMock(return_value=_webhook_config()),
    ), _optional_patch_targets(
        (
            "src.routes.patreon_webhooks.db_patreon",
            "src.Util.db.db_patreon",
        ),
        capture.db,
    ), _optional_patch_targets(
        (
            "src.routes.patreon_webhooks.classify_patreon_member",
            "src.Util.patreon.classifier.classify_patreon_member",
        ),
        capture.classifier,
    ), _optional_patch_targets(
        (
            "src.routes.patreon_webhooks.enqueue_member_resync",
            "src.routes.patreon_webhooks.enqueue_resync",
            "src.Util.patreon.sync.enqueue_member_resync",
        ),
        capture.resync,
    ), _optional_patch_targets(
        ("src.routes.patreon_webhooks.rate_limiter",),
        capture.rate_limiter,
    ), _optional_patch_targets(
        ("src.Util.activity_logger.log_patreon_activity",),
        capture.activity_log,
    ):
        yield capture


@pytest.mark.asyncio
async def test_signed_valid_webhook_is_accepted_without_local_session_requirement(client):
    _assert_fixture_bytes_match_manifest("member_update_active")
    capture = WebhookCapture()
    raw_body = _raw_fixture("member_update_active")

    with _patched_webhook_seams(capture):
        response = await _post_webhook(client, raw_body, _signed_headers("member_update_active"))

    _assert_webhook_route_exists(response)
    assert response.status_code == 200
    _assert_no_session_or_raw_provider_leaks(response, context="valid webhook response")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Patreon-Event": "members:update", "X-Patreon-Signature": "not-a-hex-signature"},
        {"X-Patreon-Event": "members:update", "X-Patreon-Signature": "0" * 32},
    ],
)
async def test_missing_malformed_or_invalid_signature_is_rejected_before_processing(client, headers):
    capture = WebhookCapture()
    raw_body = _raw_fixture("member_update_active")
    request_headers = {"Content-Type": "application/json", "User-Agent": "patreon-invalid-signature-test"}
    request_headers.update(headers)

    with _patched_webhook_seams(capture):
        response = await _post_webhook(client, raw_body, request_headers)

    _assert_webhook_route_exists(response)
    assert response.status_code == 401
    assert capture.deliveries == []
    assert capture.classifications == []
    assert capture.current_updates == []
    _assert_no_session_or_raw_provider_leaks(response, context="invalid signature response")


@pytest.mark.asyncio
async def test_exact_raw_body_bytes_are_verified_before_json_normalization(client):
    _assert_fixture_bytes_match_manifest("member_update_active_nbsp")
    _assert_fixture_bytes_match_manifest("member_update_active_nbsp_normalized")
    capture = WebhookCapture()
    exact_raw_body = _raw_fixture("member_update_active_nbsp")
    normalized_body = _raw_fixture("member_update_active_nbsp_normalized")
    exact_headers = _signed_headers("member_update_active_nbsp")
    tampered_headers = _signed_headers(
        "member_update_active_nbsp_normalized",
        signature=_fixture_meta("member_update_active_nbsp")["signature"],
        event="members:update",
    )

    with _patched_webhook_seams(capture):
        exact = await _post_webhook(client, exact_raw_body, exact_headers)
        normalized_with_exact_signature = await _post_webhook(client, normalized_body, tampered_headers)

    _assert_webhook_route_exists(exact)
    _assert_webhook_route_exists(normalized_with_exact_signature)
    assert exact.status_code == 200
    assert normalized_with_exact_signature.status_code == 401, "normalized bytes must not verify with the original NBSP signature"
    _assert_no_session_or_raw_provider_leaks(exact, context="NBSP exact body response")
    _assert_no_session_or_raw_provider_leaks(normalized_with_exact_signature, context="normalized body rejection")


@pytest.mark.asyncio
async def test_unsupported_event_is_ignored_safely_after_signature_verification(client):
    capture = WebhookCapture()
    raw_body = b'{"data":{"id":"unsupported-fixture","type":"post","attributes":{"title":"no entitlement"}}}\n'
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "patreon-unsupported-event-test",
        "X-Patreon-Event": "posts:publish",
        "X-Patreon-Signature": _signature_for(raw_body),
    }

    with _patched_webhook_seams(capture):
        response = await _post_webhook(client, raw_body, headers)

    _assert_webhook_route_exists(response)
    assert response.status_code == 200
    assert capture.current_updates == []
    assert capture.classifications == []
    _assert_no_session_or_raw_provider_leaks(response, context="unsupported event response")


@pytest.mark.asyncio
async def test_duplicate_delivery_is_idempotent_and_does_not_repeat_side_effects(client):
    capture = WebhookCapture()
    raw_body = _raw_fixture("member_update_active")
    headers = _signed_headers("member_update_active")

    with _patched_webhook_seams(capture):
        first = await _post_webhook(client, raw_body, headers)
        second = await _post_webhook(client, raw_body, headers)

    _assert_webhook_route_exists(first)
    _assert_webhook_route_exists(second)
    assert first.status_code == 200
    assert second.status_code == 200
    assert len(capture.current_updates) <= 1, "replayed Patreon webhook must not repeat entitlement side effects"
    _assert_no_session_or_raw_provider_leaks(second, context="duplicate webhook response")


@pytest.mark.asyncio
async def test_processing_failure_after_delivery_ledger_enqueues_source_of_truth_resync(client):
    capture = WebhookCapture()
    raw_body = _raw_fixture("member_update_active")
    headers = _signed_headers("member_update_active")

    async def fail_after_ledger(*args, **kwargs):
        raise RuntimeError("simulated post-ledger processing failure")

    with _patched_webhook_seams(capture), _optional_patch_targets(
        ("src.routes.patreon_webhooks._process_verified_member_payload",),
        fail_after_ledger,
    ):
        first = await _post_webhook(client, raw_body, headers)
        replay = await _post_webhook(client, raw_body, headers)

    _assert_webhook_route_exists(first)
    _assert_webhook_route_exists(replay)
    assert first.status_code == 500
    assert replay.status_code == 200
    assert len(capture.deliveries) == 2
    assert capture.deliveries[1]["duplicate"] is True
    assert capture.resyncs, "post-ledger processing failure must schedule source-of-truth resync"
    assert any(
        item["kwargs"].get("sanitized_metadata", {}).get("reason") == "processing_failed_after_delivery_ledger"
        for item in capture.resyncs
    )
    assert capture.current_updates == []
    _assert_no_session_or_raw_provider_leaks(first, context="post-ledger failure response")
    _assert_no_session_or_raw_provider_leaks(replay, context="post-ledger replay response")


@pytest.mark.asyncio
async def test_partial_payload_enqueues_resync_without_destructive_downgrade(client):
    capture = WebhookCapture()
    raw_body = _raw_fixture("member_delete_partial")
    headers = _signed_headers("member_delete_partial")

    forbidden_downgrade = MagicMock(side_effect=AssertionError("partial webhook must not destructively downgrade current entitlement"))
    capture.db.update_current_entitlement.side_effect = forbidden_downgrade
    capture.db.upsert_entitlement_snapshot.side_effect = forbidden_downgrade

    with _patched_webhook_seams(capture):
        response = await _post_webhook(client, raw_body, headers)

    _assert_webhook_route_exists(response)
    assert response.status_code == 200
    assert capture.current_updates == []
    assert capture.resyncs, "partial payload must enqueue source-of-truth resync instead of downgrading"
    _assert_no_session_or_raw_provider_leaks(response, context="partial webhook response")


@pytest.mark.asyncio
async def test_unknown_tier_or_out_of_order_payload_does_not_grant_paid_entitlement_without_source_of_truth(client):
    capture = WebhookCapture()
    raw_body = _raw_fixture("pledge_update_unknown_tier")
    headers = _signed_headers("pledge_update_unknown_tier")
    capture.classifier.side_effect = lambda *args, **kwargs: {
        "status": "pending",
        "plan_code": "free",
        "tier_code": None,
        "reason": "tier_map_miss",
    }

    with _patched_webhook_seams(capture):
        response = await _post_webhook(client, raw_body, headers)

    _assert_webhook_route_exists(response)
    assert response.status_code == 200
    for update in capture.current_updates:
        assert "magic_worlds_plus" not in repr(update), "unknown tier webhook must not grant paid entitlement directly"
    _assert_no_session_or_raw_provider_leaks(response, context="unknown tier webhook response")
