"""Unit contracts for the Patreon integration hardening pass.

Each test pins a defect that previously broke the integration against the real
Patreon API or leaked information: missing ``campaign`` relationships, merged
rate-limit keys, lost refreshed tokens, crash-looping workers, entitlements that
were never revoked, and health that reported healthy while the token was revoked.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import patch

import fakeredis
import pytest

from src.Util.patreon import catalog as patreon_catalog
from src.Util.patreon import client as patreon_client
from src.Util.patreon import sync as patreon_sync
from src.Util.patreon.config import load_patreon_config
from src.Util.patreon.rate_limit import PatreonRateLimiter, PatreonRateLimitExceeded, PatreonRateLimitPolicy
from src.Util.patreon.security import hash_patreon_identifier, verify_s2s_bearer_token


ID_SECRET = "unit-id-hmac-secret-not-real-0123456789"
PROVIDER_PEPPER = "unit-provider-pepper-not-real-0123456789"
CAMPAIGN = "camp-100"
TIER = "tier-200"


def _env(**overrides: str) -> dict[str, str]:
    env = {
        "APP_ENV": "test",
        "PATREON_LINKING_ENABLED": "true",
        "PATREON_SYNC_ENABLED": "true",
        "PATREON_CREATOR_ACCESS_TOKEN": "creator-token-not-real",
        "PATREON_PROVIDER_SUB_PEPPER": PROVIDER_PEPPER,
        "PATREON_EMAIL_HASH_PEPPER": "unit-email-pepper-not-real-0123456789",
        "PATREON_PROOF_TOKEN_PEPPER": "unit-proof-pepper-not-real-0123456789",
        "PATREON_ID_HMAC_SECRET": ID_SECRET,
        "PATREON_CAMPAIGN_TIER_MAP": json.dumps(
            [{"campaign_id": CAMPAIGN, "tier_id": TIER, "plan_code": "plus", "tier_code": "pro", "priority": 10}]
        ),
    }
    env.update(overrides)
    return env


def _member(member_id: str, user_id: str, *, status: str = "active_patron", tiers: tuple[str, ...] = (TIER,), campaign: bool = True) -> dict[str, Any]:
    relationships: dict[str, Any] = {
        "user": {"data": {"id": user_id, "type": "user"}},
        "currently_entitled_tiers": {"data": [{"id": tier, "type": "tier"} for tier in tiers]},
    }
    if campaign:
        relationships["campaign"] = {"data": {"id": CAMPAIGN, "type": "campaign"}}
    return {
        "id": member_id,
        "type": "member",
        "attributes": {"patron_status": status, "email": f"{member_id}@example.test"},
        "relationships": relationships,
    }


# ---------------------------------------------------------------------------
# Rate limits: one counter per dimension
# ---------------------------------------------------------------------------


def _limiter(**limits: int) -> PatreonRateLimiter:
    return PatreonRateLimiter(redis_client=fakeredis.FakeStrictRedis(), policy=PatreonRateLimitPolicy(**limits))


def test_link_request_budget_cannot_be_reset_by_changing_ip_or_hint():
    limiter = _limiter(link_request_limit=2)
    limiter.check_link_request(user_id="u1", ip_address="1.1.1.1", email_hint="a@example.test")
    limiter.check_link_request(user_id="u1", ip_address="2.2.2.2", email_hint="b@example.test")
    with pytest.raises(PatreonRateLimitExceeded):
        limiter.check_link_request(user_id="u1", ip_address="3.3.3.3", email_hint="c@example.test")


def test_proof_consume_budget_is_per_proof_not_per_guess():
    limiter = _limiter(proof_consume_limit=2)
    # The submitted secret is not part of the key: every guess spends the same budget.
    limiter.check_proof_consume(ip_address="1.1.1.1", lookup_id="lk", proof_token_fingerprint="g1", user_id="u1")
    limiter.check_proof_consume(ip_address="2.2.2.2", lookup_id="lk", proof_token_fingerprint="g2", user_id="u2")
    with pytest.raises(PatreonRateLimitExceeded):
        limiter.check_proof_consume(ip_address="3.3.3.3", lookup_id="lk", proof_token_fingerprint="g3", user_id="u3")


def test_shared_ip_gets_headroom_over_the_per_user_limit():
    limiter = _limiter(unlink_limit=1)
    for index in range(5):
        limiter.check_unlink(user_id=f"user-{index}", ip_address="10.0.0.1")
    with pytest.raises(PatreonRateLimitExceeded):
        limiter.check_unlink(user_id="user-6", ip_address="10.0.0.1")


def test_webhook_signature_failures_are_counted_per_ip_regardless_of_event_header():
    limiter = _limiter(webhook_signature_failure_limit=1)
    limiter.check_webhook_signature_failure(ip_address="9.9.9.9", event_type="members:create")
    with pytest.raises(PatreonRateLimitExceeded):
        limiter.check_webhook_signature_failure(ip_address="9.9.9.9", event_type="members:update")


# ---------------------------------------------------------------------------
# Creator API client
# ---------------------------------------------------------------------------


def test_member_reads_request_the_campaign_relationship():
    params = patreon_client.build_member_query_params()
    assert "campaign" in params["include"].split(",")


def test_member_url_has_no_pagination_parameter():
    client = patreon_client.PatreonClient(access_token="token-not-real", session=object())
    assert "page%5Bcount%5D" not in client._member_url("m-1")
    assert "include=currently_entitled_tiers,user,campaign" in client._member_url("m-1")


def test_documented_meta_cursor_drives_pagination():
    class _Session:
        closed = False

        def __init__(self) -> None:
            self.urls: list[str] = []

        def get(self, url: str, **_kwargs: Any):
            self.urls.append(url)
            payload = (
                {"data": [], "meta": {"pagination": {"cursors": {"next": "cursor-2"}}}}
                if "page%5Bcursor%5D" not in url
                else {"data": []}
            )

            class _Response:
                status = 200
                headers: dict[str, str] = {}

                async def __aenter__(self_inner):
                    return self_inner

                async def __aexit__(self_inner, *args):
                    return False

                async def json(self_inner):
                    return payload

                async def text(self_inner):
                    return json.dumps(payload)

            return _Response()

    session = _Session()
    client = patreon_client.PatreonClient(access_token="token-not-real", session=session)
    first = asyncio.run(client.list_campaign_members(CAMPAIGN))
    assert first["next_cursor"] == "cursor-2"
    asyncio.run(client.fetch_campaign_members(CAMPAIGN))
    assert "page%5Bcursor%5D=cursor-2" in session.urls[-1]


def test_restart_reuses_the_last_refreshed_creator_token():
    key = "provider-token-key-not-real-0123456789"
    config = load_patreon_config(
        env=_env(
            PATREON_CREATOR_TOKEN_REFRESH_ENABLED="true",
            PATREON_PROVIDER_TOKEN_ENCRYPTION_KEY=key,
            PATREON_PROVIDER_TOKEN_ENCRYPTION_KEY_ID="kid-1",
        )
    )

    class _Db:
        @staticmethod
        def get_patreon_provider_token_state_encrypted():
            return {
                "status": "active",
                "encryption_key_id": "kid-1",
                "access_token_ciphertext": patreon_client._encrypt_provider_token_payload(
                    token_value="refreshed-access", key=key, token_kind="creator_access"
                ),
                "refresh_token_ciphertext": patreon_client._encrypt_provider_token_payload(
                    token_value="refreshed-refresh", key=key, token_kind="creator_refresh"
                ),
            }

    assert patreon_client.load_persisted_creator_tokens(config, db_module=_Db) == (
        "refreshed-access",
        "refreshed-refresh",
    )
    # Refresh disabled: the bootstrap env token is used as-is.
    assert patreon_client.load_persisted_creator_tokens(load_patreon_config(env=_env()), db_module=_Db) == (None, None)


# ---------------------------------------------------------------------------
# Catalog id mapping
# ---------------------------------------------------------------------------


def test_stored_campaign_reference_maps_back_to_the_configured_raw_id():
    config = load_patreon_config(env=_env())
    ref = patreon_catalog.campaign_db_id(CAMPAIGN, config)
    assert ref.startswith("pcamp-") and CAMPAIGN not in ref
    assert patreon_catalog.raw_campaign_id_for(ref, config) == CAMPAIGN
    assert patreon_catalog.raw_campaign_id_for(CAMPAIGN, config) == CAMPAIGN
    assert patreon_catalog.raw_campaign_id_for("pcamp-unknown", config) is None


# ---------------------------------------------------------------------------
# Sync worker
# ---------------------------------------------------------------------------


class _FakeDb:
    """Records writes; resolves every member's Patreon user to one linked account."""

    def __init__(self, *, active_memberships: list[dict[str, Any]] | None = None, fail_member: str | None = None):
        self.snapshots: list[dict[str, Any]] = []
        self.observed: list[dict[str, Any]] = []
        self.completed: list[dict[str, Any]] = []
        self.active_memberships = active_memberships or []
        self.fail_member_hash = (
            hash_patreon_identifier(raw_id=fail_member, kind="member", pepper=ID_SECRET) if fail_member else None
        )

    # catalog mirror
    def upsert_patreon_catalog_campaign(self, **_kwargs):
        return {}

    def upsert_patreon_catalog_tier(self, **_kwargs):
        return {}

    def retire_unconfigured_patreon_catalog(self, **_kwargs):
        return {}

    def get_patreon_link_by_provider_sub_hash(self, *, provider_sub_hash: bytes):
        return {"id": "user-1", "user_hash": "uh-1", "external_account_id": "uea-1"}

    def get_entitlement_by_user_hash(self, _user_hash: str):
        return {"entitlement_status": "active", "plan_code": "plus", "link_status": "linked"}

    def observe_patreon_membership(self, **kwargs):
        if self.fail_member_hash and kwargs["member_id_hash"] == self.fail_member_hash:
            raise RuntimeError("simulated DB failure")
        self.observed.append(kwargs)
        return {"membership_id": kwargs["membership_id"]}

    def upsert_patreon_entitlement_snapshot(self, **kwargs):
        self.snapshots.append(kwargs)
        return {"snapshot_id": kwargs["snapshot_id"]}

    def list_active_patreon_memberships(self, **_kwargs):
        return list(self.active_memberships)

    def complete_patreon_sync_job(self, **kwargs):
        self.completed.append(kwargs)
        return {}


class _FakePatreon:
    def __init__(self, members: list[dict[str, Any]]):
        self.members = members
        self.campaigns: list[str] = []

    async def list_campaign_members(self, campaign_id: str, *, page_cursor: str | None = None):
        self.campaigns.append(campaign_id)
        return {"data": list(self.members), "next_cursor": None}


def _worker(db: _FakeDb, client: Any, **env: str):
    from src.workers.patreon_sync_worker import PatreonSyncWorker

    return PatreonSyncWorker(worker_id="unit-worker", client=client, db_module=db, config=load_patreon_config(env=_env(**env)))


def test_worker_starts_without_a_creator_token_when_sync_is_disabled():
    from src.workers.patreon_sync_worker import PatreonSyncWorker

    config = load_patreon_config(env={"APP_ENV": "test"})
    worker = PatreonSyncWorker(worker_id="unit-worker", db_module=_FakeDb(), config=config)
    with patch("src.workers.patreon_sync_worker.SystemMetrics.record_patreon_worker_heartbeat", return_value=True):
        result = asyncio.run(worker.run_once())
    assert result.results[0].status == "disabled"


def test_complete_sweep_downgrades_linked_members_patreon_no_longer_returns():
    present_hash = hash_patreon_identifier(raw_id="m-present", kind="member", pepper=ID_SECRET)
    gone_hash = hash_patreon_identifier(raw_id="m-gone", kind="member", pepper=ID_SECRET)
    db = _FakeDb(
        active_memberships=[
            {"membership_id": "pmem-present", "user_id": "user-1", "external_account_id": "uea-1", "member_id_hash": present_hash},
            {"membership_id": "pmem-gone", "user_id": "user-2", "external_account_id": "uea-2", "member_id_hash": gone_hash},
        ]
    )
    worker = _worker(db, _FakePatreon([_member("m-present", "pu-1")]))
    with patch("src.workers.patreon_sync_worker.SystemMetrics.record_patreon_worker_heartbeat", return_value=True):
        asyncio.run(worker._sync_campaign(campaign_id=CAMPAIGN))

    downgraded = [row for row in db.snapshots if row["reason"] == patreon_sync.ABSENT_MEMBER_REASON]
    assert [row["membership_id"] for row in downgraded] == ["pmem-gone"]
    assert downgraded[0]["entitlement_status"] == "former" and downgraded[0]["plan_code"] == "free"
    assert any(row["entitlement_status"] == "active" for row in db.snapshots)


def test_one_failing_member_neither_aborts_the_sweep_nor_triggers_downgrades():
    gone_hash = hash_patreon_identifier(raw_id="m-gone", kind="member", pepper=ID_SECRET)
    db = _FakeDb(
        fail_member="m-bad",
        active_memberships=[{"membership_id": "pmem-gone", "user_id": "u", "external_account_id": "e", "member_id_hash": gone_hash}],
    )
    worker = _worker(db, _FakePatreon([_member("m-bad", "pu-1"), _member("m-good", "pu-2")]))
    result = asyncio.run(worker._sync_campaign(campaign_id=CAMPAIGN))

    assert result.members_seen == 2 and result.members_persisted == 1
    assert result.reason == "member_failures_skipped"
    assert not [row for row in db.snapshots if row["reason"] == patreon_sync.ABSENT_MEMBER_REASON]


def test_campaign_job_calls_patreon_with_the_raw_campaign_id():
    db = _FakeDb()
    fake = _FakePatreon([])
    worker = _worker(db, fake)
    stored_ref = patreon_catalog.campaign_db_id(CAMPAIGN, worker.config)
    asyncio.run(
        worker._process_claimed_job(
            {"id": "psj-1", "job_type": "full_campaign", "campaign_id": stored_ref, "attempts": 1, "max_attempts": 8}
        )
    )
    assert fake.campaigns == [CAMPAIGN]
    assert db.completed[-1]["status"] == "completed"


def test_exhausted_campaign_job_fails_instead_of_retrying_forever():
    class _Down(_FakePatreon):
        async def list_campaign_members(self, campaign_id: str, *, page_cursor: str | None = None):
            raise patreon_client.PatreonAPIError(status_code=503)

    db = _FakeDb()
    worker = _worker(db, _Down([]))
    asyncio.run(
        worker._process_claimed_job(
            {"id": "psj-2", "job_type": "full_campaign", "campaign_id": None, "attempts": 8, "max_attempts": 8}
        )
    )
    assert db.completed[-1]["status"] == "failed"


# ---------------------------------------------------------------------------
# Link flow helpers
# ---------------------------------------------------------------------------


def test_link_discovery_reports_the_campaign_it_searched():
    from src.routes import auth_patreon

    class _Provider:
        async def fetch_campaign_members(self, campaign_id: str):
            return {"data": [_member("m-1", "pu-1", campaign=False)]}

    config = load_patreon_config(env=_env())
    payload, member, campaign = asyncio.run(
        auth_patreon._discover_member_for_link(provider_client=_Provider(), config=config, email_hint="M-1@example.test")
    )
    assert member["id"] == "m-1" and campaign == CAMPAIGN
    # No hint, no member: email equality is the only selector, never "first member".
    assert asyncio.run(
        auth_patreon._discover_member_for_link(provider_client=_Provider(), config=config, email_hint=None)
    )[1] is None


def test_link_request_readiness_requires_the_id_secret_and_a_tier_map():
    from src.routes import auth_patreon

    assert auth_patreon._feature_ready_for_link_request(load_patreon_config(env=_env()))
    assert not auth_patreon._feature_ready_for_link_request(
        load_patreon_config(env=_env(PATREON_ID_HMAC_SECRET=""))
    )
    assert not auth_patreon._feature_ready_for_link_request(
        load_patreon_config(env=_env(PATREON_CAMPAIGN_TIER_MAP=""))
    )
    assert not auth_patreon._feature_ready_for_link_request(None)


def test_only_consumer_sessions_may_request_a_link():
    from src.routes import auth_patreon

    assert auth_patreon._is_consumer_session({"user_type": "consumer"})
    assert auth_patreon._is_consumer_session({})
    assert not auth_patreon._is_consumer_session({"user_type": "admin"})
    assert not auth_patreon._is_consumer_session({"user_type": "root"})


def test_committed_link_is_reported_linked_even_when_the_first_read_fails(monkeypatch):
    from src.routes import auth_patreon

    async def _boom(**_kwargs):
        raise RuntimeError("simulated snapshot failure")

    queued: list[dict[str, Any]] = []
    monkeypatch.setattr(auth_patreon, "_classify_and_persist_initial_entitlement", _boom)
    monkeypatch.setattr(auth_patreon.patreon_sync, "enqueue_member_resync", lambda **kwargs: queued.append(kwargs))
    entitlement = asyncio.run(
        auth_patreon._initial_entitlement_after_link(
            config=load_patreon_config(env=_env()),
            context={},
            link_result={"external_account_id": "uea-1", "membership_id": "pmem-1"},
            user_id="user-1",
            user_hash="uh-1",
        )
    )
    assert entitlement.link_status == "linked"
    assert entitlement.plan_code == "free"
    assert queued and queued[0]["user_id"] == "user-1"


# ---------------------------------------------------------------------------
# Webhook commit rules
# ---------------------------------------------------------------------------


def _classification(payload: dict[str, Any], *, current: dict[str, Any] | None = None):
    from src.Util.patreon import classifier

    return classifier.classify_patreon_entitlement(
        patreon_payload=payload,
        tier_map=patreon_sync.tier_map_from_config(load_patreon_config(env=_env())),
        current_snapshot=current,
    )


def test_complete_cancellation_webhook_is_applied_directly():
    from src.routes.patreon_webhooks import _should_resync_instead_of_commit

    classification = _classification(
        {"data": [_member("m-1", "pu-1", status="former_patron", tiers=())]},
        current={"entitlement_status": "active", "plan_code": "plus"},
    )
    assert classification.status == "former"
    assert _should_resync_instead_of_commit(
        event_type="members:pledge:update", classification=classification, is_complete=True
    ) == (False, "complete_verified_payload")
    assert _should_resync_instead_of_commit(
        event_type="members:pledge:delete", classification=classification, is_complete=True
    )[0] is True


def test_classifier_reads_db_snapshot_status_key():
    from src.Util.patreon import classifier

    assert classifier._snapshot_status({"entitlement_status": "active"}) == "active"


# ---------------------------------------------------------------------------
# Security and health
# ---------------------------------------------------------------------------


def test_non_ascii_s2s_bearer_is_rejected_not_crashing():
    assert verify_s2s_bearer_token(presented="tökén", expected="token") is False
    assert verify_s2s_bearer_token(presented="token", expected="token") is True


def test_revoked_creator_token_degrades_overall_patreon_health():
    from src.Util.system_metrics import SystemMetrics

    healthy = {"status": "healthy"}
    with patch.multiple(
        SystemMetrics,
        get_patreon_readiness_metrics=staticmethod(lambda: {"status": "ready", "disabled": False, "configured_tier_map_entries": 1}),
        get_patreon_creator_token_health=staticmethod(lambda: {"status": "revoked", "degraded": True}),
        get_patreon_webhook_metrics=staticmethod(lambda: healthy),
        get_patreon_snapshot_metrics=staticmethod(lambda: {"status": "healthy", "tier_map_misses_24h": 0}),
        get_patreon_proof_delivery_health=staticmethod(lambda: healthy),
        get_patreon_s2s_health=staticmethod(lambda: healthy),
        get_patreon_worker_metrics=staticmethod(lambda: healthy),
        get_patreon_sync_queue_metrics=staticmethod(lambda: healthy),
        get_patreon_db_timezone_health=staticmethod(lambda: healthy),
    ):
        metrics = SystemMetrics.get_patreon_metrics()
    assert metrics["status"] == "degraded"
    assert metrics["tier_map"]["status"] == "healthy"


def test_env_creator_token_without_refresh_state_is_reported_configured():
    from src.Util.system_metrics import SystemMetrics

    with patch("src.Util.system_metrics.load_patreon_config", lambda: load_patreon_config(env=_env())), patch(
        "src.Util.db.db_patreon.get_patreon_creator_token_health", lambda: {"status": "disabled", "configured": False}
    ):
        health = SystemMetrics.get_patreon_creator_token_health()
    assert health["status"] == "configured"
    assert health["configured"] is True and health["degraded"] is False
    assert health["source"] == "environment"
