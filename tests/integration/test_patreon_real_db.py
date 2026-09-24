"""Patreon link, snapshot, queue, ledger and retention procedures against real MySQL.

The route/worker suites replace ``db_patreon`` with fakes, so they cannot see what the
stored procedures and triggers actually do. These tests run the real procedures and
pin the behaviours that broke silently before: proof replay, relinking after unlink,
re-syncing an unchanged member, re-created members, multi-campaign entitlements,
queue dedupe ids, failed-delivery redelivery, absent-member downgrades and retention.

Needs the disposable MySQL from ``docker-compose.test.yml``; skipped otherwise.
"""

from __future__ import annotations

import hashlib
import secrets
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pymysql
import pytest

from src.Util.db import db_patreon
from src.Util.patreon import catalog as patreon_catalog
from src.Util.patreon import sync as patreon_sync
from tests.integration.conftest import _REAL_DB_CONFIG


pytestmark = pytest.mark.real_db


def _tuple_connection():
    cfg = {**_REAL_DB_CONFIG}
    cfg.pop("cursorclass", None)
    return pymysql.connect(**cfg)


@contextmanager
def _real_db():
    with patch("src.Util.db.db_patreon.get_connection", _tuple_connection):
        yield


def _digest() -> bytes:
    return secrets.token_bytes(32)


def _fp(digest: bytes) -> str:
    return digest.hex()[:12]


def _utc(**delta) -> datetime:
    return (datetime.now(timezone.utc) + timedelta(**delta)).replace(microsecond=0, tzinfo=None)


@pytest.fixture
def consumer(real_factory):
    return real_factory.create_user(user_type="consumer")


@pytest.fixture
def campaign():
    digest = _digest()
    campaign_db_id = f"pcamp-{_fp(digest)}"
    with _real_db():
        db_patreon.upsert_patreon_catalog_campaign(
            campaign_db_id=campaign_db_id,
            campaign_id_hash=digest,
            campaign_id_fingerprint=_fp(digest),
            display_name="Real DB campaign",
            enabled=True,
        )
    return campaign_db_id


def _link(user_id: str, campaign_db_id: str, provider_hash: bytes, member_hash: bytes, *, external_id: str | None = None):
    return db_patreon.link_patreon_account(
        external_account_id=external_id or f"uea-{secrets.token_hex(8)}",
        user_id=user_id,
        provider_sub_hash=provider_hash,
        provider_sub_fingerprint=_fp(provider_hash),
        provider_email_hash=None,
        provider_email_masked=None,
        linked_by=user_id,
        proof_id=None,
        campaign_id=campaign_db_id,
        membership_id=f"pmem-{campaign_db_id.removeprefix('pcamp-')}-{_fp(member_hash)}",
        member_id_hash=member_hash,
        member_id_fingerprint=_fp(member_hash),
        metadata={"source": "real_db_test"},
    )


def _snapshot(user_id: str, external_id: str, membership_id: str, *, status="active", plan="pro", tier="artisan", payload_hash=None, reason="snapshot_upsert", observed_at=None):
    return db_patreon.upsert_patreon_entitlement_snapshot(
        snapshot_id=f"psnap-{secrets.token_hex(8)}",
        history_id=None,
        current_id=None,
        user_id=user_id,
        external_account_id=external_id,
        membership_id=membership_id,
        observed_at=observed_at or _utc(),
        sync_source="api_pull",
        patron_status_normalized="active_patron" if status == "active" else "former_patron",
        tier_hashes_json=[],
        last_charge_status_normalized=None,
        next_charge_at=None,
        payload_hash=payload_hash if payload_hash is not None else _digest(),
        is_complete=True,
        requires_resync=False,
        entitlement_status=status,
        link_status="linked",
        plan_code=plan,
        tier_code=tier if plan != "free" else None,
        tier_name=None,
        next_renewal_at=None,
        grace_period_until=None,
        stale_after=_utc(hours=24),
        reason=reason,
        safe_metadata={"source": "real_db_test"},
    )


def _count(real_db_conn, sql: str, params: tuple) -> int:
    with real_db_conn.cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
    real_db_conn.commit()
    return int(next(iter(row.values())))


# ---------------------------------------------------------------------------
# Proof lifecycle
# ---------------------------------------------------------------------------


def _create_proof(user_id: str, campaign_db_id: str, token_hash: bytes) -> str:
    lookup_id = secrets.token_hex(8)
    db_patreon.create_patreon_proof(
        proof_id=f"plp-{secrets.token_hex(8)}",
        user_id=user_id,
        campaign_id=campaign_db_id,
        patreon_user_id_hash=_digest(),
        patreon_user_id_fingerprint="a" * 12,
        member_id_hash=_digest(),
        member_id_fingerprint="b" * 12,
        proof_email_hash=_digest(),
        proof_email_masked="p***@example.test",
        lookup_id=lookup_id,
        token_hash=token_hash,
        token_fingerprint="c" * 12,
        expires_at=_utc(minutes=15),
        email_message_id=f"em-{secrets.token_hex(8)}",
        recipient_email="patron@example.test",
        provider="fake",
        provider_idempotency_key=f"patreon-link-proof-{lookup_id}",
        render_payload_ciphertext=b"ciphertext",
        created_ip_hash=None,
        created_user_agent_hash=None,
        metadata={"source": "real_db_test"},
    )
    return lookup_id


def test_proof_is_single_use_and_a_replay_releases_nothing(consumer, campaign):
    token_hash = _digest()
    with _real_db():
        lookup_id = _create_proof(consumer["id"], campaign, token_hash)
        first = db_patreon.consume_patreon_proof(
            lookup_id=lookup_id, token_hash=token_hash, consumed_ip_hash=None,
            consumed_user_agent_hash=None, user_id=consumer["id"],
        )
        replay = db_patreon.consume_patreon_proof(
            lookup_id=lookup_id, token_hash=token_hash, consumed_ip_hash=None,
            consumed_user_agent_hash=None, user_id=consumer["id"],
        )

    assert first["consume_status"] == "consumed"
    assert first["proof_id"] and first["member_id_hash"]
    assert replay["consume_status"] == "already_consumed"
    assert "proof_id" not in replay and "member_id_hash" not in replay


def test_proof_rejects_wrong_secret_and_other_users(consumer, campaign, real_factory):
    other = real_factory.create_user(user_type="consumer")
    token_hash = _digest()
    with _real_db():
        lookup_id = _create_proof(consumer["id"], campaign, token_hash)
        wrong_secret = db_patreon.consume_patreon_proof(
            lookup_id=lookup_id, token_hash=_digest(), consumed_ip_hash=None,
            consumed_user_agent_hash=None, user_id=consumer["id"],
        )
        other_user = db_patreon.consume_patreon_proof(
            lookup_id=lookup_id, token_hash=token_hash, consumed_ip_hash=None,
            consumed_user_agent_hash=None, user_id=other["id"],
        )
    assert wrong_secret["consume_status"] == "invalid"
    assert other_user["consume_status"] == "not_found"


# ---------------------------------------------------------------------------
# Link / unlink / relink and membership resolution
# ---------------------------------------------------------------------------


def test_relink_after_unlink_gets_a_fresh_membership(consumer, campaign):
    provider_hash, member_hash = _digest(), _digest()
    with _real_db():
        first = _link(consumer["id"], campaign, provider_hash, member_hash)
        _snapshot(consumer["id"], first["external_account_id"], first["membership_id"])
        db_patreon.unlink_patreon_account(
            user_id=consumer["id"], unlinked_by=consumer["id"], reason="user_requested", history_id=None
        )
        second = _link(consumer["id"], campaign, provider_hash, member_hash)
        observed = db_patreon.observe_patreon_membership(
            membership_id=first["membership_id"],  # the canonical id callers derive
            user_id=consumer["id"],
            external_account_id=second["external_account_id"],
            campaign_id=campaign,
            member_id_hash=member_hash,
            member_id_fingerprint=_fp(member_hash),
            patreon_user_id_hash=provider_hash,
            patreon_user_id_fingerprint=_fp(provider_hash),
            status="active",
            metadata=None,
        )
        snapshot = _snapshot(consumer["id"], second["external_account_id"], observed["membership_id"])

    assert second["link_status"] == "linked"
    assert second["membership_id"] != first["membership_id"]
    assert observed["membership_id"] == second["membership_id"]
    assert snapshot["current_updated"] in (1, True)


def test_same_member_cannot_be_linked_to_a_second_user(consumer, campaign, real_factory):
    other = real_factory.create_user(user_type="consumer")
    member_hash = _digest()
    with _real_db():
        _link(consumer["id"], campaign, _digest(), member_hash)
        with pytest.raises(Exception):
            _link(other["id"], campaign, _digest(), member_hash)


def test_recreated_member_supersedes_the_old_membership(consumer, campaign):
    provider_hash = _digest()
    old_member, new_member = _digest(), _digest()
    with _real_db():
        linked = _link(consumer["id"], campaign, provider_hash, old_member)
        observed = db_patreon.observe_patreon_membership(
            membership_id=f"pmem-{campaign.removeprefix('pcamp-')}-{_fp(new_member)}",
            user_id=consumer["id"],
            external_account_id=linked["external_account_id"],
            campaign_id=campaign,
            member_id_hash=new_member,
            member_id_fingerprint=_fp(new_member),
            patreon_user_id_hash=provider_hash,
            patreon_user_id_fingerprint=_fp(provider_hash),
            status="active",
            metadata=None,
        )
        _snapshot(consumer["id"], linked["external_account_id"], observed["membership_id"])
        active = db_patreon.list_active_patreon_memberships(user_id=consumer["id"])

    assert observed["membership_id"] != linked["membership_id"]
    assert [row["membership_id"] for row in active] == [observed["membership_id"]]


# ---------------------------------------------------------------------------
# Snapshots, history and multi-campaign entitlements
# ---------------------------------------------------------------------------


def test_unchanged_resync_succeeds_without_growing_history(consumer, campaign, real_db_conn):
    payload_hash = _digest()
    with _real_db():
        linked = _link(consumer["id"], campaign, _digest(), _digest())
        first = _snapshot(consumer["id"], linked["external_account_id"], linked["membership_id"], payload_hash=payload_hash)
        second = _snapshot(consumer["id"], linked["external_account_id"], linked["membership_id"], payload_hash=payload_hash)

    assert second["snapshot_id"] == first["snapshot_id"]
    history = _count(real_db_conn, "SELECT COUNT(*) FROM patreon_entitlement_history WHERE user_id=%s", (consumer["id"],))
    snapshots = _count(
        real_db_conn,
        "SELECT COUNT(*) FROM patreon_member_snapshots WHERE membership_id=%s",
        (linked["membership_id"],),
    )
    assert history == 1
    assert snapshots == 1


def test_free_membership_does_not_overwrite_paid_one_from_another_campaign(consumer, campaign):
    other_digest = _digest()
    other_campaign = f"pcamp-{_fp(other_digest)}"
    provider_hash = _digest()
    with _real_db():
        db_patreon.upsert_patreon_catalog_campaign(
            campaign_db_id=other_campaign, campaign_id_hash=other_digest,
            campaign_id_fingerprint=_fp(other_digest), display_name=None, enabled=True,
        )
        paid = _link(consumer["id"], campaign, provider_hash, _digest())
        free = _link(consumer["id"], other_campaign, provider_hash, _digest())
        _snapshot(consumer["id"], paid["external_account_id"], paid["membership_id"])
        kept = _snapshot(
            consumer["id"], free["external_account_id"], free["membership_id"], status="former", plan="free"
        )
        current_after_free = db_patreon.get_entitlement_by_user_hash(consumer["user_hash"])
        _snapshot(consumer["id"], paid["external_account_id"], paid["membership_id"], status="former", plan="free")
        current_after_cancel = db_patreon.get_entitlement_by_user_hash(consumer["user_hash"])

    assert kept["current_updated"] in (0, False)
    assert current_after_free["plan_code"] == "pro"
    assert current_after_cancel["plan_code"] == "free"
    assert current_after_cancel["entitlement_status"] == "former"


def test_absent_member_is_downgraded_once_and_reuses_its_snapshot(consumer, campaign, real_db_conn):
    member_hash = _digest()
    with _real_db():
        linked = _link(consumer["id"], campaign, _digest(), member_hash)
        _snapshot(consumer["id"], linked["external_account_id"], linked["membership_id"])
        [membership] = db_patreon.list_active_patreon_memberships(member_id_hash=member_hash)
        assert patreon_sync.persist_absent_membership(membership, db_module=db_patreon)
        assert patreon_sync.persist_absent_membership(membership, db_module=db_patreon)
        current = db_patreon.get_entitlement_by_user_hash(consumer["user_hash"])

    assert current["entitlement_status"] == "former"
    assert current["plan_code"] == "free"
    assert current["link_status"] == "linked"
    absent_snapshots = _count(
        real_db_conn,
        "SELECT COUNT(*) FROM patreon_member_snapshots WHERE membership_id=%s AND patron_status_normalized='former_patron'",
        (linked["membership_id"],),
    )
    assert absent_snapshots == 1


def test_admin_reads_search_and_history(consumer, campaign):
    with _real_db():
        linked = _link(consumer["id"], campaign, _digest(), _digest())
        _snapshot(consumer["id"], linked["external_account_id"], linked["membership_id"], observed_at=_utc(minutes=-5))
        _snapshot(consumer["id"], linked["external_account_id"], linked["membership_id"], status="former", plan="free")
        rows, total = db_patreon.list_patreon_entitlements_admin(
            status=None, plan_code=None, link_status="linked", search=consumer["username"], limit=10, offset=0
        )
        history = db_patreon.list_patreon_entitlement_history_admin(user_hash=consumer["user_hash"], limit=10)

    assert total == 1 and rows[0]["user_hash"] == consumer["user_hash"]
    assert [item["new_status"] for item in history] == ["former", "active"]
    assert all("hash" not in key or key == "user_hash" for item in history for key in item)


# ---------------------------------------------------------------------------
# Sync-job queue
# ---------------------------------------------------------------------------


def _enqueue(dedupe: bytes):
    return db_patreon.enqueue_patreon_sync_job(
        job_id=f"psj-{secrets.token_hex(8)}",
        job_type="full_campaign",
        campaign_id=None,
        member_id_hash=None,
        user_id=None,
        dedupe_key_hash=dedupe,
        priority=5,
        not_before=None,
        source="manual",
        sanitized_metadata={"source": "real_db_test"},
    )


def test_enqueue_reports_the_active_job_it_merged_into():
    dedupe = _digest()
    with _real_db():
        first = _enqueue(dedupe)
        second = _enqueue(dedupe)
    assert first["job_status"] == "enqueued"
    assert second["job_status"] == "deduplicated"
    assert second["job_id"] == first["job_id"]


def test_request_during_a_running_job_reruns_it(real_db_conn):
    dedupe = _digest()
    with _real_db():
        job_id = _enqueue(dedupe)["job_id"]
    with real_db_conn.cursor() as cursor:
        cursor.execute("UPDATE patreon_sync_jobs SET status='running', attempts=1 WHERE id=%s", (job_id,))
    real_db_conn.commit()
    with _real_db():
        merged = _enqueue(dedupe)
        completed = db_patreon.complete_patreon_sync_job(
            job_id=job_id, status="completed", retry_after_seconds=None, last_error_redacted=None
        )
    assert merged["job_id"] == job_id
    assert completed["job_status"] == "pending"
    with real_db_conn.cursor() as cursor:
        cursor.execute("SELECT status, attempts, sanitized_metadata FROM patreon_sync_jobs WHERE id=%s", (job_id,))
        row = cursor.fetchone()
    real_db_conn.commit()
    assert row["status"] == "pending" and row["attempts"] == 0
    assert "rerun_requested" not in (row["sanitized_metadata"] or "")


# ---------------------------------------------------------------------------
# Webhook ledger
# ---------------------------------------------------------------------------


def _record(delivery_hash: bytes):
    return db_patreon.record_patreon_webhook_delivery(
        delivery_id=f"pwhd-{secrets.token_hex(8)}",
        delivery_hash=delivery_hash,
        event_type="members:pledge:update",
        member_id_hash=None,
        campaign_id_hash=None,
        raw_body_sha256=hashlib.sha256(b"{}").digest(),
        signature_valid=True,
        status="received",
        sanitized_metadata={"source": "real_db_test"},
    )


def test_failed_delivery_is_reprocessed_and_processed_one_is_a_replay():
    delivery_hash = _digest()
    with _real_db():
        first = _record(delivery_hash)
        db_patreon.mark_patreon_webhook_delivery(delivery_id=first["delivery_id"], status="failed")
        redelivered = _record(delivery_hash)
        db_patreon.mark_patreon_webhook_delivery(delivery_id=first["delivery_id"], status="processed")
        replay = _record(delivery_hash)
    assert first["delivery_status"] == "accepted"
    assert redelivered == {"delivery_id": first["delivery_id"], "delivery_status": "accepted"}
    assert replay["delivery_status"] == "replay"


# ---------------------------------------------------------------------------
# Retention and catalog mirror
# ---------------------------------------------------------------------------


def test_retention_purges_old_finished_jobs_only(real_db_conn):
    with _real_db():
        old_done = _enqueue(_digest())["job_id"]
        old_pending = _enqueue(_digest())["job_id"]
    with real_db_conn.cursor() as cursor:
        cursor.execute(
            "UPDATE patreon_sync_jobs SET status='completed', completed_at=DATE_SUB(NOW(), INTERVAL 40 DAY) WHERE id=%s",
            (old_done,),
        )
        cursor.execute(
            "UPDATE patreon_sync_jobs SET created_at=DATE_SUB(NOW(), INTERVAL 40 DAY) WHERE id=%s",
            (old_pending,),
        )
    real_db_conn.commit()
    with _real_db():
        summary = db_patreon.run_patreon_retention_purge(
            proof_retention_after_expiry_hours=24,
            webhook_delivery_retention_days=90,
            raw_payload_retention_days=30,
            sync_job_retention_days=30,
        )
    assert summary["sync_jobs_purged"] >= 1
    assert _count(real_db_conn, "SELECT COUNT(*) FROM patreon_sync_jobs WHERE id=%s", (old_done,)) == 0
    assert _count(real_db_conn, "SELECT COUNT(*) FROM patreon_sync_jobs WHERE id=%s", (old_pending,)) == 1


@dataclass(frozen=True)
class _Entry:
    campaign_id: str
    tier_id: str
    plan_code: str
    tier_code: str
    tier_name: str | None = None
    priority: int = 0
    active: bool = True
    campaign_name: str | None = None


@dataclass
class _CatalogConfig:
    campaign_tier_maps: tuple = ()
    id_hmac_secret: str = field(default_factory=lambda: secrets.token_hex(32))

    @property
    def campaign_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(entry.campaign_id for entry in self.campaign_tier_maps))


def test_catalog_mirror_upserts_and_retires_tiers(real_db_conn):
    campaign_raw = f"camp-{secrets.token_hex(4)}"
    config = _CatalogConfig(
        campaign_tier_maps=(
            _Entry(campaign_raw, "tier-a", "plus", "artisan", "Artisan", 10, campaign_name="Main"),
            _Entry(campaign_raw, "tier-b", "plus", "pro", "Pro", 20),
        )
    )
    patreon_catalog.reset_catalog_cache()
    with _real_db():
        first = patreon_catalog.ensure_patreon_catalog(config, db_module=db_patreon)
        campaign_ref = patreon_catalog.campaign_db_id(campaign_raw, config)
        config.campaign_tier_maps = config.campaign_tier_maps[:1]
        patreon_catalog.ensure_patreon_catalog(config, db_module=db_patreon)
    patreon_catalog.reset_catalog_cache()

    assert first == {"campaigns": 1, "tiers": 2, "skipped": 0}
    assert patreon_catalog.raw_campaign_id_for(campaign_ref, config) == campaign_raw
    active = _count(
        real_db_conn,
        "SELECT COUNT(*) FROM patreon_tier_map WHERE campaign_id=%s AND active=1",
        (campaign_ref,),
    )
    assert active == 1
