"""Patreon source-of-truth sync worker.

Trace: SDD change ``patreon-account-link`` tasks ``8.1`` through ``8.7``:
worker foundation, creator-token failure posture, retention, quarantine, health
metrics, operational hooks, and fail-closed stale/degraded provider failures.

This worker is an entitlement/link synchronizer only.  It never registers routes,
never issues local sessions/JWTs/refresh tokens/cookies/API keys, and never logs
raw Patreon IDs, emails, payloads, signatures, hash prefixes, fingerprints, or
creator-token material.  Runtime wiring in ``src/main.py`` is intentionally a
later SDD phase.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import logging
import random
import signal
import time
import uuid
from dataclasses import dataclass, field, is_dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import src.Util.db_config as db_config
from src.Util import auth_constants as constants
from src.Util.db import db_patreon
from src.Util.patreon import sync as patreon_sync
from src.Util.patreon.client import PatreonClient, PatreonUnauthorizedError
from src.Util.patreon.config import load_patreon_config
from src.Util.patreon.security import hash_patreon_identifier, sanitize_patreon_log_value
from src.Util.system_metrics import SystemMetrics


logger = logging.getLogger(__name__)

_MODE_QUEUED = "queued"
_MODE_FULL_CAMPAIGN_SWEEP = "full_campaign_sweep"
_MODE_MANUAL_RESYNC_QUEUE = "manual_resync_queue"
_MODE_PER_MEMBER_SYNC = "per_member_sync"
_MODE_TOKEN_REFRESH = "token_refresh"
_MODE_RETENTION_ONLY = "retention_only"
_SUPPORTED_ONE_SHOT_MODES = frozenset(
    {
        _MODE_QUEUED,
        _MODE_FULL_CAMPAIGN_SWEEP,
        _MODE_MANUAL_RESYNC_QUEUE,
        _MODE_PER_MEMBER_SYNC,
        _MODE_TOKEN_REFRESH,
        _MODE_RETENTION_ONLY,
    }
)
_MODE_ALIASES = {
    "manual": _MODE_MANUAL_RESYNC_QUEUE,
    "manual_resync": _MODE_MANUAL_RESYNC_QUEUE,
    "manual_queue": _MODE_MANUAL_RESYNC_QUEUE,
    "member": _MODE_PER_MEMBER_SYNC,
    "manual_member": _MODE_PER_MEMBER_SYNC,
    "campaign": _MODE_FULL_CAMPAIGN_SWEEP,
    "full_campaign": _MODE_FULL_CAMPAIGN_SWEEP,
    "retention": _MODE_RETENTION_ONLY,
}
_JOB_TYPE_ALIASES = {
    "manual_member": patreon_sync.JOB_TYPE_USER_MEMBER,
    "member": patreon_sync.JOB_TYPE_USER_MEMBER,
    "per_member": patreon_sync.JOB_TYPE_USER_MEMBER,
    "campaign": patreon_sync.JOB_TYPE_FULL_CAMPAIGN,
    "full": patreon_sync.JOB_TYPE_FULL_CAMPAIGN,
    "full_campaign_sweep": patreon_sync.JOB_TYPE_FULL_CAMPAIGN,
    "retention": patreon_sync.JOB_TYPE_RETENTION,
    "retention_only": patreon_sync.JOB_TYPE_RETENTION,
    "token": patreon_sync.JOB_TYPE_TOKEN_REFRESH,
}


@dataclass(frozen=True)
class PatreonWorkerItemResult:
    """One safe worker item result."""

    status: str
    job_id: str | None = None
    job_type: str | None = None
    members_seen: int = 0
    members_persisted: int = 0
    pages_fetched: int = 0
    tier_map_misses: int = 0
    proof_requests_purged: int = 0
    webhook_delivery_hashes_purged: int = 0
    raw_payloads_purged: int = 0
    retry_after_seconds: int | None = None
    reason: str | None = None


@dataclass(frozen=True)
class PatreonWorkerRunResult:
    """Aggregate one-shot result returned by tests/local invocations."""

    worker_id: str
    mode: str
    results: tuple[PatreonWorkerItemResult, ...] = field(default_factory=tuple)

    @property
    def processed_count(self) -> int:
        return len(self.results)

    @property
    def members_seen(self) -> int:
        return sum(item.members_seen for item in self.results)

    @property
    def pages_fetched(self) -> int:
        return sum(item.pages_fetched for item in self.results)

    @property
    def tier_map_misses(self) -> int:
        return sum(item.tier_map_misses for item in self.results)

    @property
    def retry_count(self) -> int:
        return sum(1 for item in self.results if item.status == patreon_sync.SYNC_JOB_STATUS_RETRY)


def _utc_now(now: datetime | None = None) -> datetime:
    candidate = now or datetime.now(timezone.utc)
    if candidate.tzinfo is None:
        candidate = candidate.replace(tzinfo=timezone.utc)
    return candidate.astimezone(timezone.utc).replace(microsecond=0)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _plain_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if is_dataclass(value):
        return {str(key): item for key, item in asdict(value).items()}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump()
        except Exception:
            dumped = None
        if isinstance(dumped, Mapping):
            return {str(key): item for key, item in dumped.items()}
    return {}


def _text_field(value: Any, *names: str, default: str | None = None) -> str | None:
    for name in names:
        candidate = value.get(name) if isinstance(value, Mapping) else getattr(value, name, None)
        if candidate is None:
            continue
        text = str(candidate).strip()
        if text:
            return text
    return default


def _bool_field(value: Any, name: str, default: bool = False) -> bool:
    candidate = value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default)
    if isinstance(candidate, bool):
        return candidate
    if candidate is None:
        return default
    return str(candidate).strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_field(value: Any, *names: str, default: int = 0) -> int:
    for name in names:
        candidate = value.get(name) if isinstance(value, Mapping) else getattr(value, name, None)
        if candidate is None:
            continue
        try:
            if isinstance(candidate, bool):
                return default
            return int(candidate)
        except (TypeError, ValueError):
            return default
    return default


def _member_data_from_page(page: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    data = page.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, Mapping)]
    if isinstance(data, Mapping):
        return [data]
    return []


def _member_payload(page: Mapping[str, Any], member: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"data": [member]}
    included = page.get("included")
    if isinstance(included, list):
        payload["included"] = included
    return payload


def _relationships(member: Mapping[str, Any] | None) -> Mapping[str, Any]:
    rel = _plain_mapping(member).get("relationships")
    return rel if isinstance(rel, Mapping) else {}


def _relationship_id(member: Mapping[str, Any] | None, name: str) -> str | None:
    rel = _relationships(member).get(name)
    if not isinstance(rel, Mapping):
        return None
    data = rel.get("data")
    if isinstance(data, Mapping):
        return _text_field(data, "id")
    return None


def _safe_result_metadata(result: patreon_sync.PatreonMemberSyncResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "plan_code": result.plan_code,
        "tier_code": result.tier_code,
        "link_status": result.link_status,
        "tier_map_miss": result.tier_map_miss,
        "resync_required": result.resync_required,
        "persisted": result.persisted,
    }


def _safe_error_text(value: Any) -> str:
    return sanitize_patreon_log_value(str(value or "patreon_sync_failed"))[:500]


def _summary_count(summary: Mapping[str, Any] | None, marker: str) -> int:
    """Extract a safe purge count from SP or fake-store retention summaries."""

    if not isinstance(summary, Mapping):
        return 0
    marker_text = str(marker or "").lower()
    total = 0
    for key, value in summary.items():
        key_text = str(key).lower()
        if marker_text not in key_text:
            continue
        if isinstance(value, Mapping):
            total += _summary_count(value, "purged") or _summary_count(value, marker_text)
            continue
        if isinstance(value, bool):
            continue
        try:
            total += int(value)
        except (TypeError, ValueError):
            continue
    if total:
        return total
    if marker_text == "proof" and isinstance(summary.get("proofs"), Mapping):
        return _summary_count(summary["proofs"], "purged")
    if marker_text == "webhook" and isinstance(summary.get("webhook_hashes"), Mapping):
        return _summary_count(summary["webhook_hashes"], "purged")
    if marker_text == "raw" and isinstance(summary.get("raw_payloads"), Mapping):
        return _summary_count(summary["raw_payloads"], "purged")
    return 0


def _is_token_invalid_error(error: BaseException) -> bool:
    return bool(
        isinstance(error, PatreonUnauthorizedError)
        or getattr(error, "token_invalid", False)
        or getattr(error, "creator_token_invalid", False)
        or getattr(error, "token_state", None) == "invalid"
        or "unauthorized" in type(error).__name__.lower()
    )


def _job_type(row: Mapping[str, Any]) -> str:
    raw = str(row.get("job_type") or row.get("kind") or patreon_sync.JOB_TYPE_USER_MEMBER).strip()
    return _JOB_TYPE_ALIASES.get(raw, raw)


def _job_id(row: Mapping[str, Any]) -> str | None:
    return _text_field(row, "id", "job_id")


def _bytes_or_hex_field(value: Any) -> bytes | None:
    if isinstance(value, bytes):
        return value if len(value) == 32 else None
    if isinstance(value, bytearray):
        return bytes(value) if len(value) == 32 else None
    if isinstance(value, memoryview):
        data = bytes(value)
        return data if len(data) == 32 else None
    if isinstance(value, str):
        text = value.strip()
        if len(text) == 64:
            try:
                data = bytes.fromhex(text)
            except ValueError:
                return None
            return data if len(data) == 32 else None
    return None


def _campaign_ids_from_config(config: Any) -> list[str]:
    values = getattr(config, "campaign_ids", None)
    if callable(values):
        values = values()
    if values:
        return [str(item).strip() for item in values if str(item).strip()]
    entries = getattr(config, "campaign_tier_maps", None) or getattr(config, "tier_map_entries", None) or getattr(config, "tier_maps", None) or ()
    seen: set[str] = set()
    campaigns: list[str] = []
    for entry in entries:
        campaign_id = _text_field(entry, "campaign_id")
        if campaign_id and campaign_id not in seen:
            seen.add(campaign_id)
            campaigns.append(campaign_id)
    return campaigns


class PatreonSyncWorker:
    """Small async worker over Patreon sync jobs and scheduled sweeps."""

    def __init__(
        self,
        *,
        worker_id: str | None = None,
        client: Any | None = None,
        patreon_client: Any | None = None,
        db_module: Any | None = None,
        db: Any | None = None,
        redis=None,
        config: Any | None = None,
    ) -> None:
        self.config = config or load_patreon_config()
        self.worker_id = worker_id or f"patreon-sync-worker-{uuid.uuid4()}"
        self.redis = redis if redis is not None else db_config.redis_client
        self.db = db_module if db_module is not None else db if db is not None else db_patreon
        self.client = client if client is not None else patreon_client if patreon_client is not None else PatreonClient.from_config(self.config)
        self._stopping = False
        self._last_scheduled_sweep_monotonic: float | None = None
        self._next_scheduled_sweep_monotonic: float | None = None

    @property
    def sync_enabled(self) -> bool:
        return _bool_field(self.config, "sync_enabled", False) or _bool_field(self.config, "sync", False)

    @property
    def token_refresh_enabled(self) -> bool:
        return _bool_field(self.config, "creator_token_refresh_enabled", False)

    def request_stop(self, *_args: Any) -> None:
        self._stopping = True

    async def run_once(
        self,
        *,
        mode: str | None = None,
        limit: int | None = None,
        member_id: str | None = None,
        member_id_hash: bytes | str | None = None,
        user_id: str | None = None,
        campaign_id: str | None = None,
        now: datetime | None = None,
    ) -> PatreonWorkerRunResult:
        """Run one safe worker pass.

        ``retention_only`` executes only bounded Patreon retention cleanup.  It
        never deletes link, snapshot, entitlement, or unlink history.
        """

        normalized_mode = str(mode or _MODE_QUEUED).strip().lower()
        normalized_mode = _MODE_ALIASES.get(normalized_mode, normalized_mode)
        if normalized_mode == _MODE_RETENTION_ONLY:
            result = await self.run_retention_purge(now=now)
            await self._record_heartbeat(mode=normalized_mode, results=[result], now=now)
            return PatreonWorkerRunResult(self.worker_id, normalized_mode, (result,))

        if normalized_mode not in _SUPPORTED_ONE_SHOT_MODES:
            normalized_mode = _MODE_QUEUED

        if not self.sync_enabled and normalized_mode != _MODE_TOKEN_REFRESH:
            result = PatreonWorkerItemResult(status="disabled", reason="sync_disabled")
            await self._record_heartbeat(mode=normalized_mode, results=[result], now=now)
            return PatreonWorkerRunResult(self.worker_id, normalized_mode, (result,))

        if normalized_mode == _MODE_FULL_CAMPAIGN_SWEEP:
            results = await self.run_full_campaign_sweep(now=now)
        elif normalized_mode == _MODE_MANUAL_RESYNC_QUEUE:
            results = await self.process_manual_resync_queue(limit=limit)
        elif normalized_mode == _MODE_PER_MEMBER_SYNC:
            results = [
                await self.run_per_member_sync(
                    member_id=member_id,
                    member_id_hash=member_id_hash,
                    user_id=user_id,
                    campaign_id=campaign_id,
                    now=now,
                )
            ]
        elif normalized_mode == _MODE_TOKEN_REFRESH:
            try:
                results = [await self._run_token_refresh_job(job_id=None)]
            except Exception as exc:
                results = [
                    await self._handle_provider_failure(
                        error=exc,
                        job_id=None,
                        job_type=patreon_sync.JOB_TYPE_TOKEN_REFRESH,
                    )
                ]
        else:
            results = await self.process_queued_jobs(limit=limit)
            if not results and self._scheduled_sweep_due():
                results = await self.run_full_campaign_sweep(now=now)
                self._schedule_next_sweep()
            if not results:
                results = [PatreonWorkerItemResult(status="noop", reason="no_claimed_jobs")]

        await self._record_heartbeat(mode=normalized_mode, results=results, now=now)
        return PatreonWorkerRunResult(self.worker_id, normalized_mode, tuple(results))

    async def drain_once(self, **kwargs: Any) -> PatreonWorkerRunResult:
        return await self.run_once(**kwargs)

    async def process_once(self, **kwargs: Any) -> PatreonWorkerRunResult:
        return await self.run_once(**kwargs)

    async def sync_once(self, **kwargs: Any) -> PatreonWorkerRunResult:
        return await self.run_once(**kwargs)

    async def run_full_campaign_sweep(self, *, now: datetime | None = None) -> list[PatreonWorkerItemResult]:
        if not self.sync_enabled:
            return [PatreonWorkerItemResult(status="disabled", job_type=patreon_sync.JOB_TYPE_FULL_CAMPAIGN, reason="sync_disabled")]
        campaign_ids = self._campaign_ids()
        if not campaign_ids:
            return [PatreonWorkerItemResult(status="noop", reason="no_configured_campaigns")]

        results: list[PatreonWorkerItemResult] = []
        for campaign_id in campaign_ids:
            try:
                results.append(await self._sync_campaign(campaign_id=campaign_id, now=now))
            except Exception as exc:
                results.append(await self._handle_provider_failure(error=exc, job_id=None, job_type=patreon_sync.JOB_TYPE_FULL_CAMPAIGN))
        return results

    async def run_full_campaign_sync(self, *, now: datetime | None = None) -> list[PatreonWorkerItemResult]:
        """Operational hook for an explicit full source-of-truth campaign sync."""

        return await self.run_full_campaign_sweep(now=now)

    async def run_campaign_sync(self, *, campaign_id: str, now: datetime | None = None) -> PatreonWorkerItemResult:
        """Operational hook for one configured campaign; returns only counts."""

        if not self.sync_enabled:
            return PatreonWorkerItemResult(status="disabled", job_type=patreon_sync.JOB_TYPE_FULL_CAMPAIGN, reason="sync_disabled")
        safe_campaign_id = str(campaign_id or "").strip()
        if not safe_campaign_id:
            return PatreonWorkerItemResult(status="noop", job_type=patreon_sync.JOB_TYPE_FULL_CAMPAIGN, reason="missing_campaign")
        try:
            return await self._sync_campaign(campaign_id=safe_campaign_id, now=now)
        except Exception as exc:
            return await self._handle_provider_failure(error=exc, job_id=None, job_type=patreon_sync.JOB_TYPE_FULL_CAMPAIGN)

    async def process_queued_jobs(self, *, limit: int | None = None) -> list[PatreonWorkerItemResult]:
        if not self.sync_enabled:
            return [PatreonWorkerItemResult(status="disabled", reason="sync_disabled")]
        try:
            jobs = await _maybe_await(
                self.db.claim_patreon_sync_jobs(
                    worker_id=self.worker_id,
                    limit=max(1, int(limit or self._worker_batch_size())),
                    lease_seconds=max(1, self._worker_lease_seconds()),
                )
            )
        except AttributeError:
            jobs = await _maybe_await(
                self.db.claim_sync_jobs(
                    worker_id=self.worker_id,
                    limit=max(1, int(limit or self._worker_batch_size())),
                    lease_seconds=max(1, self._worker_lease_seconds()),
                )
            )
        except Exception as exc:
            logger.warning("Patreon sync job claim failed: %s", type(exc).__name__)
            return [PatreonWorkerItemResult(status="claim_failed", reason=_safe_error_text(exc))]

        results: list[PatreonWorkerItemResult] = []
        for row in jobs or []:
            results.append(await self._process_claimed_job(_plain_mapping(row)))
        return results

    async def process_manual_resync_queue(self, *, limit: int | None = None) -> list[PatreonWorkerItemResult]:
        """Operational hook for manual/internal resync queue draining."""

        return await self.process_queued_jobs(limit=limit)

    async def run_retention_only(self, *, now: datetime | None = None) -> PatreonWorkerItemResult:
        """Operational hook for bounded retention-only maintenance."""

        return await self.run_retention_purge(now=now)

    async def run_per_member_sync(
        self,
        *,
        member_id: str | None = None,
        member_id_hash: bytes | str | None = None,
        user_id: str | None = None,
        campaign_id: str | None = None,
        now: datetime | None = None,
    ) -> PatreonWorkerItemResult:
        """Operational hook for one member/user resync without exposing raw IDs."""

        row = {
            "job_type": patreon_sync.JOB_TYPE_USER_MEMBER,
            "member_id": member_id,
            "member_id_hash": member_id_hash,
            "user_id": user_id,
            "campaign_id": campaign_id,
        }
        try:
            result = await self._run_member_job(row=row, job_id=None, job_type=patreon_sync.JOB_TYPE_USER_MEMBER, now=now)
        except Exception as exc:
            result = await self._handle_provider_failure(
                error=exc,
                job_id=None,
                job_type=patreon_sync.JOB_TYPE_USER_MEMBER,
            )
        await self._record_heartbeat(mode=_MODE_PER_MEMBER_SYNC, results=[result], now=now)
        return result

    async def run_retention_purge(self, *, now: datetime | None = None) -> PatreonWorkerItemResult:
        """Run bounded Patreon retention cleanup.

        The purge contract is intentionally narrow: proof rows after
        expiry+24h, webhook delivery hashes after 90d, and encrypted raw-payload
        quarantine after at most 30d.  This worker never calls any history-delete
        seam; link, snapshot, entitlement, and unlink history remain indefinite.
        """

        windows = self._retention_windows()
        try:
            summary = await self._run_retention_backend(now=now, windows=windows)
            proof_count = _summary_count(summary, "proof")
            webhook_count = _summary_count(summary, "webhook")
            raw_count = _summary_count(summary, "raw")
            await self._record_activity(
                event="patreon_retention_purged",
                outcome=patreon_sync.SYNC_JOB_STATUS_COMPLETED,
                details={
                    "proof_retention_after_expiry_hours": windows["proof_retention_after_expiry_hours"],
                    "webhook_delivery_retention_days": windows["webhook_delivery_retention_days"],
                    "raw_payload_retention_days": windows["raw_payload_retention_days"],
                    "proof_requests_purged": proof_count,
                    "webhook_delivery_hashes_purged": webhook_count,
                    "raw_payloads_purged": raw_count,
                    "history_retention": "indefinite",
                },
            )
            return PatreonWorkerItemResult(
                status=patreon_sync.SYNC_JOB_STATUS_COMPLETED,
                job_type=patreon_sync.JOB_TYPE_RETENTION,
                proof_requests_purged=proof_count,
                webhook_delivery_hashes_purged=webhook_count,
                raw_payloads_purged=raw_count,
                reason="link_snapshot_unlink_history_preserved_indefinitely",
            )
        except Exception as exc:
            reason = _safe_error_text(exc)
            await self._record_activity(
                event="patreon_retention_purged",
                outcome=patreon_sync.SYNC_JOB_STATUS_FAILED,
                details={"reason": reason, "history_retention": "indefinite"},
            )
            return PatreonWorkerItemResult(
                status=patreon_sync.SYNC_JOB_STATUS_FAILED,
                job_type=patreon_sync.JOB_TYPE_RETENTION,
                reason=reason,
            )

    def _retention_windows(self) -> dict[str, int]:
        proof_hours = min(
            constants.MAX_PATREON_PROOF_RETENTION_AFTER_EXPIRY_HOURS,
            max(
                0,
                _int_field(
                    self.config,
                    "proof_retention_after_expiry_hours",
                    default=constants.DEFAULT_PATREON_PROOF_RETENTION_AFTER_EXPIRY_HOURS,
                ),
            ),
        )
        webhook_days = min(
            constants.MAX_PATREON_WEBHOOK_DELIVERY_RETENTION_DAYS,
            max(
                0,
                _int_field(
                    self.config,
                    "webhook_delivery_retention_days",
                    default=constants.DEFAULT_PATREON_WEBHOOK_DELIVERY_RETENTION_DAYS,
                ),
            ),
        )
        raw_days = min(
            constants.MAX_PATREON_RAW_PAYLOAD_RETENTION_DAYS,
            max(
                0,
                _int_field(
                    self.config,
                    "raw_payload_retention_days",
                    default=constants.DEFAULT_PATREON_RAW_PAYLOAD_RETENTION_DAYS,
                ),
            ),
        )
        return {
            "proof_retention_after_expiry_hours": proof_hours,
            "webhook_delivery_retention_days": webhook_days,
            "raw_payload_retention_days": raw_days,
        }

    async def _run_retention_backend(self, *, now: datetime | None, windows: Mapping[str, int]) -> Mapping[str, Any]:
        method = getattr(self.db, "run_patreon_retention_purge", None) or getattr(self.db, "run_retention_purge", None)
        if callable(method):
            try:
                result = await _maybe_await(
                    method(
                        proof_retention_after_expiry_hours=windows["proof_retention_after_expiry_hours"],
                        webhook_delivery_retention_days=windows["webhook_delivery_retention_days"],
                        raw_payload_retention_days=windows["raw_payload_retention_days"],
                    )
                )
            except TypeError:
                result = await _maybe_await(method())
            return _plain_mapping(result)

        fallback_summary: dict[str, Any] = {}
        proof_method = getattr(self.db, "purge_expired_patreon_proofs", None)
        if callable(proof_method):
            fallback_summary["proofs"] = await _maybe_await(
                proof_method(
                    now=_utc_now(now),
                    retention_hours=windows["proof_retention_after_expiry_hours"],
                    proof_retention_after_expiry_hours=windows["proof_retention_after_expiry_hours"],
                )
            )

        webhook_method = getattr(self.db, "purge_expired_webhook_deliveries", None)
        if callable(webhook_method):
            fallback_summary["webhook_hashes"] = await _maybe_await(
                webhook_method(
                    now=_utc_now(now),
                    retention_days=windows["webhook_delivery_retention_days"],
                    webhook_delivery_retention_days=windows["webhook_delivery_retention_days"],
                )
            )

        raw_method = getattr(self.db, "purge_expired_raw_payloads", None)
        if callable(raw_method):
            fallback_summary["raw_payloads"] = await _maybe_await(
                raw_method(
                    now=_utc_now(now),
                    retention_days=windows["raw_payload_retention_days"],
                    raw_payload_retention_days=windows["raw_payload_retention_days"],
                    max_retention_days=constants.MAX_PATREON_RAW_PAYLOAD_RETENTION_DAYS,
                )
            )

        fallback_summary["history_retention_status"] = "link_snapshot_unlink_history_preserved_indefinitely"
        return fallback_summary

    async def _maybe_quarantine_raw_payload(
        self,
        *,
        source: str,
        payload: Mapping[str, Any],
        capture_reason: str,
    ) -> None:
        """Optionally retain encrypted provider payload bytes for diagnostics.

        The feature is disabled by default.  When enabled, the DB wrapper owns
        encryption and retention-cap enforcement, and this method never logs or
        returns raw payload content.
        """

        if not _bool_field(self.config, "raw_payload_capture_enabled", False):
            return
        method = getattr(self.db, "quarantine_patreon_raw_payload", None) or getattr(
            self.db,
            "capture_patreon_raw_payload_quarantine",
            None,
        )
        if not callable(method):
            return
        try:
            raw_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
            await _maybe_await(
                method(
                    raw_payload=raw_payload,
                    source=source,
                    capture_enabled=True,
                    encryption_key=_text_field(self.config, "provider_token_encryption_key"),
                    encryption_key_id=_text_field(self.config, "provider_token_encryption_key_id"),
                    retention_days=self._retention_windows()["raw_payload_retention_days"],
                    capture_reason=capture_reason,
                    created_by=None,
                    sanitized_metadata={"source": source, "capture_reason": capture_reason},
                )
            )
        except Exception:
            logger.warning("Patreon raw-payload quarantine skipped: %s", "quarantine_unavailable")

    def run_forever(self, *, once: bool = False) -> None:
        signal.signal(signal.SIGTERM, self.request_stop)
        signal.signal(signal.SIGINT, self.request_stop)
        while not self._stopping:
            asyncio.run(self.run_once())
            if once:
                return
            time.sleep(max(1, self._worker_poll_seconds()))

    async def run_loop(self) -> None:
        while not self._stopping:
            await self.run_once()
            await asyncio.sleep(max(1, self._worker_poll_seconds()))

    def _worker_batch_size(self) -> int:
        return _int_field(
            self.config,
            "sync_worker_batch_size",
            "worker_batch_size",
            default=constants.DEFAULT_PATREON_SYNC_WORKER_BATCH_SIZE,
        )

    def _worker_lease_seconds(self) -> int:
        return _int_field(
            self.config,
            "sync_job_lease_seconds",
            "worker_lease_seconds",
            default=constants.DEFAULT_PATREON_SYNC_JOB_LEASE_SECONDS,
        )

    def _worker_poll_seconds(self) -> int:
        return _int_field(
            self.config,
            "sync_worker_poll_seconds",
            "worker_poll_seconds",
            default=constants.DEFAULT_PATREON_SYNC_WORKER_POLL_SECONDS,
        )

    def _campaign_ids(self) -> list[str]:
        config_campaigns = _campaign_ids_from_config(self.config)
        if config_campaigns:
            return config_campaigns
        for method_name in ("list_enabled_patreon_campaigns", "list_enabled_campaigns"):
            method = getattr(self.db, method_name, None)
            if not callable(method):
                continue
            try:
                rows = method()
            except Exception:
                continue
            campaigns = []
            for row in rows or []:
                campaign_id = _text_field(row, "campaign_id", "raw_campaign_id", "provider_campaign_id", "id")
                if campaign_id:
                    campaigns.append(campaign_id)
            if campaigns:
                return campaigns
        return []

    def _scheduled_sweep_due(self) -> bool:
        interval = _int_field(
            self.config,
            "sync_interval_seconds",
            default=constants.DEFAULT_PATREON_SYNC_INTERVAL_SECONDS,
        )
        if interval <= 0:
            return False
        now = time.monotonic()
        if self._next_scheduled_sweep_monotonic is None:
            self._next_scheduled_sweep_monotonic = now
        return now >= self._next_scheduled_sweep_monotonic

    def _schedule_next_sweep(self) -> None:
        interval = max(1, _int_field(self.config, "sync_interval_seconds", default=constants.DEFAULT_PATREON_SYNC_INTERVAL_SECONDS))
        jitter = max(0, _int_field(self.config, "sync_jitter_seconds", default=constants.DEFAULT_PATREON_SYNC_JITTER_SECONDS))
        self._last_scheduled_sweep_monotonic = time.monotonic()
        self._next_scheduled_sweep_monotonic = self._last_scheduled_sweep_monotonic + interval + random.SystemRandom().randint(0, jitter)

    async def _sync_campaign(self, *, campaign_id: str, now: datetime | None = None) -> PatreonWorkerItemResult:
        pages_fetched = 0
        members_seen = 0
        members_persisted = 0
        tier_map_misses = 0
        max_pages = _int_field(self.config, "api_max_pages_per_sync", default=constants.DEFAULT_PATREON_API_MAX_PAGES_PER_SYNC)

        async for page in patreon_sync.iter_campaign_member_pages(
            self.client,
            campaign_id,
            max_pages=max_pages if max_pages > 0 else None,
        ):
            pages_fetched += 1
            await self._maybe_quarantine_raw_payload(
                source=constants.PATREON_SYNC_SOURCE_API_PULL,
                payload=page,
                capture_reason="campaign_sync_page",
            )
            for member in _member_data_from_page(page):
                result = await self._process_member_payload(_member_payload(page, member), member=member, now=now)
                members_seen += 1
                members_persisted += 1 if result.persisted else 0
                tier_map_misses += 1 if result.tier_map_miss else 0

        await self._record_activity(
            event="patreon_sync_completed",
            outcome="completed",
            details={
                "pages_fetched": pages_fetched,
                "members_seen": members_seen,
                "members_persisted": members_persisted,
                "tier_map_misses": tier_map_misses,
            },
        )
        return PatreonWorkerItemResult(
            status=patreon_sync.SYNC_JOB_STATUS_COMPLETED,
            job_type=patreon_sync.JOB_TYPE_FULL_CAMPAIGN,
            members_seen=members_seen,
            members_persisted=members_persisted,
            pages_fetched=pages_fetched,
            tier_map_misses=tier_map_misses,
        )

    async def _process_member_payload(
        self,
        payload: Mapping[str, Any],
        *,
        member: Mapping[str, Any],
        now: datetime | None = None,
    ) -> patreon_sync.PatreonMemberSyncResult:
        persistence = await self._persistence_context_for_member(member)
        result = patreon_sync.classify_and_maybe_persist_member_payload(
            payload,
            config=self.config,
            tier_map=patreon_sync.tier_map_from_config(self.config),
            persistence=persistence,
            db_module=self.db,
            now=now,
            source=constants.PATREON_SYNC_SOURCE_SCHEDULED,
            is_complete=True,
        )

        await self._record_member_observation(result=result)
        if result.tier_map_miss or result.unknown_tier:
            await self._record_activity(
                event="patreon_tier_map_miss",
                outcome="failed_safe",
                details=patreon_sync.tier_map_miss_metadata(result),
            )
        return result

    async def _persistence_context_for_member(self, member: Mapping[str, Any]) -> patreon_sync.PatreonMemberPersistenceContext | None:
        provider_secret = _text_field(self.config, "provider_sub_pepper")
        id_secret = _text_field(self.config, "id_hmac_secret", "provider_sub_pepper")
        raw_user_id = _relationship_id(member, "user")
        if not provider_secret or not raw_user_id:
            return None
        try:
            provider_hash = hash_patreon_identifier(raw_id=raw_user_id, kind="user", pepper=provider_secret)
        except Exception:
            return None
        resolver = getattr(self.db, "resolve_patreon_link_by_provider_hash", None) or getattr(
            self.db,
            "get_patreon_link_by_provider_sub_hash",
            None,
        )
        if not callable(resolver):
            return None
        try:
            link_row = _plain_mapping(await _maybe_await(resolver(provider_sub_hash=provider_hash)))
        except Exception:
            return None
        user_id = _text_field(link_row, "user_id", "id")
        external_account_id = _text_field(link_row, "external_account_id")
        if not user_id or not external_account_id or not id_secret:
            return None
        current_snapshot = None
        user_hash = _text_field(link_row, "user_hash")
        if user_hash and callable(getattr(self.db, "get_entitlement_by_user_hash", None)):
            try:
                current_snapshot = _plain_mapping(await _maybe_await(self.db.get_entitlement_by_user_hash(user_hash)))
            except Exception:
                current_snapshot = None
        return patreon_sync.PatreonMemberPersistenceContext(
            user_id=user_id,
            external_account_id=external_account_id,
            raw_campaign_id=_relationship_id(member, "campaign"),
            raw_member_id=_text_field(member, "id"),
            raw_patreon_user_id=raw_user_id,
            current_snapshot=current_snapshot,
            id_hmac_secret=id_secret,
            safe_metadata={"source": "patreon_sync_worker"},
        )

    async def _record_member_observation(self, *, result: patreon_sync.PatreonMemberSyncResult) -> None:
        metadata = _safe_result_metadata(result)
        for method_name in ("record_member_observation", "upsert_member_observation"):
            method = getattr(self.db, method_name, None)
            if not callable(method):
                continue
            try:
                await _maybe_await(method(**metadata))
                break
            except TypeError:
                try:
                    await _maybe_await(method(metadata=metadata))
                    break
                except Exception:
                    break
            except Exception:
                break
        current_method = getattr(self.db, "upsert_current_entitlement", None)
        if callable(current_method):
            try:
                await _maybe_await(current_method(**result.safe_entitlement_dict()))
            except Exception:
                pass

    def _aggregate_provider_results(
        self,
        results: Sequence[PatreonWorkerItemResult],
    ) -> tuple[str, int | None, str | None]:
        """Return a safe final job status for multi-campaign provider results."""

        if any(item.status == patreon_sync.SYNC_JOB_STATUS_FAILED for item in results):
            reason = next((item.reason for item in results if item.reason), "provider_or_sync_failure")
            return patreon_sync.SYNC_JOB_STATUS_FAILED, None, reason
        retry_results = [item for item in results if item.status == patreon_sync.SYNC_JOB_STATUS_RETRY]
        if retry_results:
            retry_after = next((item.retry_after_seconds for item in retry_results if item.retry_after_seconds), None)
            reason = next((item.reason for item in retry_results if item.reason), "provider_degraded_retry")
            return patreon_sync.SYNC_JOB_STATUS_RETRY, retry_after, reason
        return patreon_sync.SYNC_JOB_STATUS_COMPLETED, None, None

    async def _process_claimed_job(self, row: Mapping[str, Any]) -> PatreonWorkerItemResult:
        job_id = _job_id(row)
        job_type = _job_type(row)
        try:
            if job_type == patreon_sync.JOB_TYPE_FULL_CAMPAIGN:
                campaign_id = _text_field(row, "campaign_id", "raw_campaign_id")
                results = await self.run_full_campaign_sweep() if not campaign_id else [await self._sync_campaign(campaign_id=campaign_id)]
                aggregate_status, retry_after_seconds, aggregate_reason = self._aggregate_provider_results(results)
                await self._complete_job(
                    job_id=job_id,
                    status=aggregate_status,
                    retry_after_seconds=retry_after_seconds,
                    last_error=aggregate_reason,
                )
                aggregate = PatreonWorkerItemResult(
                    status=aggregate_status,
                    job_id=job_id,
                    job_type=job_type,
                    members_seen=sum(item.members_seen for item in results),
                    members_persisted=sum(item.members_persisted for item in results),
                    pages_fetched=sum(item.pages_fetched for item in results),
                    tier_map_misses=sum(item.tier_map_misses for item in results),
                    retry_after_seconds=retry_after_seconds,
                    reason=aggregate_reason,
                )
                return aggregate
            if job_type == patreon_sync.JOB_TYPE_TOKEN_REFRESH:
                return await self._run_token_refresh_job(job_id=job_id)
            if job_type == patreon_sync.JOB_TYPE_RETENTION:
                result = await self.run_retention_purge()
                await self._complete_job(job_id=job_id, status=result.status, last_error=result.reason)
                return PatreonWorkerItemResult(
                    status=result.status,
                    job_id=job_id,
                    job_type=job_type,
                    proof_requests_purged=result.proof_requests_purged,
                    webhook_delivery_hashes_purged=result.webhook_delivery_hashes_purged,
                    raw_payloads_purged=result.raw_payloads_purged,
                    reason=result.reason,
                )
            if job_type in {patreon_sync.JOB_TYPE_CAMPAIGN_MEMBER, patreon_sync.JOB_TYPE_USER_MEMBER, patreon_sync.JOB_TYPE_WEBHOOK_RESYNC}:
                return await self._run_member_job(row=row, job_id=job_id, job_type=job_type)
            await self._complete_job(job_id=job_id, status=patreon_sync.SYNC_JOB_STATUS_COMPLETED, last_error="unsupported_job_noop")
            return PatreonWorkerItemResult(status="noop", job_id=job_id, job_type=job_type, reason="unsupported_job_noop")
        except Exception as exc:
            return await self._handle_provider_failure(error=exc, job_id=job_id, job_type=job_type, attempts=_int_field(row, "attempts", default=0), max_attempts=_int_field(row, "max_attempts", default=constants.DEFAULT_PATREON_SYNC_MAX_ATTEMPTS))

    async def _run_member_job(
        self,
        *,
        row: Mapping[str, Any],
        job_id: str | None,
        job_type: str,
        now: datetime | None = None,
    ) -> PatreonWorkerItemResult:
        if not self.sync_enabled:
            await self._complete_job(job_id=job_id, status=patreon_sync.SYNC_JOB_STATUS_COMPLETED, last_error="sync_disabled_noop")
            return PatreonWorkerItemResult(status="disabled", job_id=job_id, job_type=job_type, reason="sync_disabled")
        raw_member_id = _text_field(row, "member_id", "raw_member_id", "provider_member_id")
        member_hash = _bytes_or_hex_field(row.get("member_id_hash"))
        user_id = _text_field(row, "user_id")
        campaign_id = _text_field(row, "campaign_id", "raw_campaign_id")
        if raw_member_id:
            payload = await self.client.get_member(raw_member_id)
            await self._maybe_quarantine_raw_payload(
                source=constants.PATREON_SYNC_SOURCE_API_PULL,
                payload=payload,
                capture_reason="member_sync_payload",
            )
            members = _member_data_from_page(payload)
            for member in members:
                await self._process_member_payload(_member_payload(payload, member), member=member, now=now)
            await self._complete_job(job_id=job_id, status=patreon_sync.SYNC_JOB_STATUS_COMPLETED)
            return PatreonWorkerItemResult(status=patreon_sync.SYNC_JOB_STATUS_COMPLETED, job_id=job_id, job_type=job_type, members_seen=len(members))
        if member_hash:
            found = await self._scan_for_member_hash(member_hash, campaign_id=campaign_id, now=now)
            await self._complete_job(job_id=job_id, status=patreon_sync.SYNC_JOB_STATUS_COMPLETED, last_error=None if found else "member_hash_not_found_noop")
            return PatreonWorkerItemResult(status=patreon_sync.SYNC_JOB_STATUS_COMPLETED, job_id=job_id, job_type=job_type, members_seen=1 if found else 0, reason=None if found else "member_hash_not_found_noop")
        if user_id:
            result = await self._scan_for_user_id(user_id=user_id, campaign_id=campaign_id, now=now)
            await self._complete_job(job_id=job_id, status=result.status, last_error=result.reason)
            return PatreonWorkerItemResult(
                status=result.status,
                job_id=job_id,
                job_type=job_type,
                members_seen=result.members_seen,
                members_persisted=result.members_persisted,
                pages_fetched=result.pages_fetched,
                tier_map_misses=result.tier_map_misses,
                reason=result.reason,
            )
        await self._complete_job(job_id=job_id, status=patreon_sync.SYNC_JOB_STATUS_COMPLETED, last_error="member_job_no_fetch_key_noop")
        return PatreonWorkerItemResult(status="noop", job_id=job_id, job_type=job_type, reason="member_job_no_fetch_key_noop")

    async def _scan_for_member_hash(self, member_hash: bytes, *, campaign_id: str | None = None, now: datetime | None = None) -> bool:
        id_secret = _text_field(self.config, "id_hmac_secret", "provider_sub_pepper")
        if not id_secret:
            return False
        campaign_ids = [campaign_id] if campaign_id else self._campaign_ids()
        for candidate_campaign_id in campaign_ids:
            async for page in patreon_sync.iter_campaign_member_pages(self.client, candidate_campaign_id):
                for member in _member_data_from_page(page):
                    raw_member_id = _text_field(member, "id")
                    if not raw_member_id:
                        continue
                    try:
                        candidate = hash_patreon_identifier(raw_id=raw_member_id, kind="member", pepper=id_secret)
                    except Exception:
                        continue
                    if candidate == member_hash:
                        await self._process_member_payload(_member_payload(page, member), member=member, now=now)
                        return True
        return False

    async def _scan_for_user_id(self, *, user_id: str, campaign_id: str | None = None, now: datetime | None = None) -> PatreonWorkerItemResult:
        safe_user_id = str(user_id or "").strip()
        if not safe_user_id:
            return PatreonWorkerItemResult(status=patreon_sync.SYNC_JOB_STATUS_COMPLETED, job_type=patreon_sync.JOB_TYPE_USER_MEMBER, reason="missing_user_id_noop")

        pages_fetched = 0
        members_seen = 0
        members_persisted = 0
        tier_map_misses = 0
        campaign_ids = [campaign_id] if campaign_id else self._campaign_ids()
        if not campaign_ids:
            return PatreonWorkerItemResult(status=patreon_sync.SYNC_JOB_STATUS_COMPLETED, job_type=patreon_sync.JOB_TYPE_USER_MEMBER, reason="no_configured_campaigns_noop")

        for candidate_campaign_id in campaign_ids:
            async for page in patreon_sync.iter_campaign_member_pages(self.client, candidate_campaign_id):
                pages_fetched += 1
                await self._maybe_quarantine_raw_payload(
                    source=constants.PATREON_SYNC_SOURCE_API_PULL,
                    payload=page,
                    capture_reason="manual_user_resync_scan",
                )
                for member in _member_data_from_page(page):
                    context = await self._persistence_context_for_member(member)
                    if context is None or str(context.user_id) != safe_user_id:
                        continue
                    result = await self._process_member_payload(_member_payload(page, member), member=member, now=now)
                    members_seen += 1
                    members_persisted += 1 if result.persisted else 0
                    tier_map_misses += 1 if result.tier_map_miss else 0

        return PatreonWorkerItemResult(
            status=patreon_sync.SYNC_JOB_STATUS_COMPLETED,
            job_type=patreon_sync.JOB_TYPE_USER_MEMBER,
            members_seen=members_seen,
            members_persisted=members_persisted,
            pages_fetched=pages_fetched,
            tier_map_misses=tier_map_misses,
            reason=None if members_seen else "user_member_not_found_noop",
        )

    async def _run_token_refresh_job(self, *, job_id: str | None) -> PatreonWorkerItemResult:
        if not self.token_refresh_enabled:
            await self._complete_job(job_id=job_id, status=patreon_sync.SYNC_JOB_STATUS_COMPLETED, last_error="token_refresh_disabled_noop")
            return PatreonWorkerItemResult(status="disabled", job_id=job_id, job_type=patreon_sync.JOB_TYPE_TOKEN_REFRESH, reason="token_refresh_disabled")
        refresher = getattr(self.client, "refresh_creator_token", None)
        if not callable(refresher):
            await self._complete_job(job_id=job_id, status=patreon_sync.SYNC_JOB_STATUS_RETRY, retry_after_seconds=60, last_error="token_refresh_unavailable")
            return PatreonWorkerItemResult(status=patreon_sync.SYNC_JOB_STATUS_RETRY, job_id=job_id, job_type=patreon_sync.JOB_TYPE_TOKEN_REFRESH, retry_after_seconds=60, reason="token_refresh_unavailable")
        try:
            await _maybe_await(refresher(db_module=self.db))
            await self._record_provider_health(status="healthy", reason="creator_token_refreshed")
            await self._complete_job(job_id=job_id, status=patreon_sync.SYNC_JOB_STATUS_COMPLETED)
            return PatreonWorkerItemResult(status=patreon_sync.SYNC_JOB_STATUS_COMPLETED, job_id=job_id, job_type=patreon_sync.JOB_TYPE_TOKEN_REFRESH)
        except TypeError:
            await _maybe_await(refresher())
            await self._complete_job(job_id=job_id, status=patreon_sync.SYNC_JOB_STATUS_COMPLETED)
            return PatreonWorkerItemResult(status=patreon_sync.SYNC_JOB_STATUS_COMPLETED, job_id=job_id, job_type=patreon_sync.JOB_TYPE_TOKEN_REFRESH)

    async def _handle_provider_failure(
        self,
        *,
        error: BaseException,
        job_id: str | None,
        job_type: str | None,
        attempts: int = 0,
        max_attempts: int | None = None,
    ) -> PatreonWorkerItemResult:
        decision = patreon_sync.decide_retry_backoff(
            error=error,
            attempts=attempts,
            max_attempts=max_attempts,
            config=self.config,
        )
        degraded_reason = decision.reason or patreon_sync.provider_failure_reason(error)
        await self._record_provider_health(status="degraded", reason=degraded_reason)
        token_invalid = _is_token_invalid_error(error)
        if token_invalid:
            await self._record_creator_token_degraded(error=error)
            if self.token_refresh_enabled:
                try:
                    await self._run_token_refresh_job(job_id=None)
                except Exception:
                    await self._record_provider_health(status="degraded", reason="creator_token_refresh_failed")
        if decision.stale_existing_snapshot:
            await self._record_retry_or_stale(decision=decision)
        await self._complete_job(
            job_id=job_id,
            status=decision.status,
            retry_after_seconds=decision.retry_after_seconds,
            last_error=decision.reason,
        )
        await self._record_activity(
            event="patreon_sync_failed",
            outcome=decision.status,
            details={
                "reason": degraded_reason,
                "retry_after_seconds": decision.retry_after_seconds,
                "preserve_last_known_snapshot": True,
                "fail_closed_new_paid_grants": True,
            },
        )
        return PatreonWorkerItemResult(
            status=decision.status,
            job_id=job_id,
            job_type=job_type,
            retry_after_seconds=decision.retry_after_seconds,
            reason=degraded_reason,
        )

    async def _complete_job(
        self,
        *,
        job_id: str | None,
        status: str,
        retry_after_seconds: int | None = None,
        last_error: str | None = None,
    ) -> None:
        if not job_id:
            return
        method = getattr(self.db, "complete_sync_job", None) or getattr(self.db, "complete_patreon_sync_job", None)
        if not callable(method):
            return
        kwargs = {
            "job_id": job_id,
            "status": status,
            "retry_after_seconds": retry_after_seconds,
            "last_error_redacted": _safe_error_text(last_error) if last_error else None,
        }
        try:
            await _maybe_await(method(**kwargs))
        except TypeError:
            await _maybe_await(method(job_id=job_id, status=status))

    async def _record_activity(self, *, event: str, outcome: str, details: Mapping[str, Any] | None = None) -> None:
        safe_details = patreon_sync._safe_metadata(details or {}) if hasattr(patreon_sync, "_safe_metadata") else dict(details or {})
        for method_name in ("record_patreon_activity", "record_activity"):
            method = getattr(self.db, method_name, None)
            if not callable(method):
                continue
            try:
                await _maybe_await(method(event=event, outcome=outcome, details=safe_details))
                return
            except TypeError:
                try:
                    await _maybe_await(method(activity_type=event, outcome=outcome, details=safe_details))
                    return
                except Exception:
                    return
            except Exception:
                return

    async def _record_retry_or_stale(self, *, decision: patreon_sync.PatreonSyncBackoffDecision) -> None:
        payload = {
            "reason": decision.reason,
            "degraded_reason": decision.reason,
            "retry_after_seconds": decision.retry_after_seconds,
            "status": decision.status,
            "degraded": True,
            "preserve_last_known_snapshot": True,
            "fail_closed_new_paid_grants": True,
        }
        for method_name in ("record_sync_retry", "mark_entitlement_stale"):
            method = getattr(self.db, method_name, None)
            if not callable(method):
                continue
            try:
                await _maybe_await(method(**payload))
            except Exception:
                pass

    async def _record_provider_health(self, *, status: str, reason: str) -> None:
        method = getattr(self.db, "record_provider_health", None)
        if callable(method):
            try:
                await _maybe_await(method(provider=constants.PATREON_PROVIDER_NAME, status=status, reason=reason))
            except Exception:
                pass

    async def _record_creator_token_degraded(self, *, error: BaseException) -> None:
        method = getattr(self.db, "record_patreon_creator_token_degraded", None)
        if not callable(method):
            return
        try:
            await _maybe_await(
                method(
                    auto_refresh_enabled=self.token_refresh_enabled,
                    encryption_key_id=_text_field(self.config, "provider_token_encryption_key_id"),
                    status="revoked" if _is_token_invalid_error(error) else "refresh_failed",
                    last_error_redacted=_safe_error_text(error),
                )
            )
        except Exception:
            pass

    async def _record_heartbeat(
        self,
        *,
        mode: str,
        results: Sequence[PatreonWorkerItemResult],
        now: datetime | None = None,
    ) -> None:
        counters = {
            "processed": len(results),
            "members_seen": sum(item.members_seen for item in results),
            "members_persisted": sum(item.members_persisted for item in results),
            "pages_fetched": sum(item.pages_fetched for item in results),
            "tier_map_misses": sum(item.tier_map_misses for item in results),
            "retry": sum(1 for item in results if item.status == patreon_sync.SYNC_JOB_STATUS_RETRY),
            "failed": sum(1 for item in results if item.status == patreon_sync.SYNC_JOB_STATUS_FAILED),
            "proof_requests_purged": sum(item.proof_requests_purged for item in results),
            "webhook_delivery_hashes_purged": sum(item.webhook_delivery_hashes_purged for item in results),
            "raw_payloads_purged": sum(item.raw_payloads_purged for item in results),
        }
        payload = {
            "worker_id": self.worker_id,
            "mode": mode,
            "recorded_at": _utc_now(now).isoformat(),
            "counters": counters,
        }
        for method_name in ("record_patreon_worker_heartbeat", "record_worker_heartbeat"):
            method = getattr(self.db, method_name, None)
            if not callable(method):
                continue
            try:
                await _maybe_await(method(**payload))
                break
            except Exception:
                break
        SystemMetrics.record_patreon_worker_heartbeat(
            self.worker_id,
            mode=mode,
            counters=counters,
            results=[
                {
                    "status": item.status,
                    "job_type": item.job_type,
                    "members_seen": item.members_seen,
                    "members_persisted": item.members_persisted,
                    "pages_fetched": item.pages_fetched,
                    "tier_map_misses": item.tier_map_misses,
                    "proof_requests_purged": item.proof_requests_purged,
                    "webhook_delivery_hashes_purged": item.webhook_delivery_hashes_purged,
                    "raw_payloads_purged": item.raw_payloads_purged,
                    "retry_after_seconds": item.retry_after_seconds,
                    "reason": item.reason,
                }
                for item in results
            ],
            ttl_seconds=max(60, self._worker_poll_seconds() * 10),
        )
        logger.info("Patreon sync worker heartbeat: worker=%s mode=%s counters=%s", self.worker_id, mode, counters)


PatreonWorker = PatreonSyncWorker


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Patreon entitlement sync worker")
    parser.add_argument("--once", action="store_true", help="process one worker pass and exit")
    parser.add_argument("--mode", choices=sorted(_SUPPORTED_ONE_SHOT_MODES | {_MODE_RETENTION_ONLY}), default=_MODE_QUEUED)
    parser.add_argument("--worker-id", default=None, help="stable worker identifier")
    parser.add_argument("--member-id", default=None, help="server-only Patreon member id for one-shot per-member sync")
    parser.add_argument("--member-id-hash", default=None, help="server-only hex member hash for one-shot per-member sync")
    parser.add_argument("--user-id", default=None, help="local user id for manual resync scan")
    parser.add_argument("--campaign-id", default=None, help="server-only configured campaign id for scoped sync")
    parser.add_argument("--limit", type=int, default=None, help="maximum queued jobs to process in one pass")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    worker = PatreonSyncWorker(worker_id=args.worker_id)
    if args.once:
        asyncio.run(
            worker.run_once(
                mode=args.mode,
                limit=args.limit,
                member_id=args.member_id,
                member_id_hash=args.member_id_hash,
                user_id=args.user_id,
                campaign_id=args.campaign_id,
            )
        )
    else:
        worker.run_forever(once=False)
    return 0


async def run_patreon_sync_once(
    *,
    worker_id: str | None = None,
    mode: str | None = None,
    client: Any | None = None,
    db_module: Any | None = None,
    config: Any | None = None,
    member_id: str | None = None,
    member_id_hash: bytes | str | None = None,
    user_id: str | None = None,
    campaign_id: str | None = None,
    limit: int | None = None,
) -> PatreonWorkerRunResult:
    worker = PatreonSyncWorker(worker_id=worker_id, client=client, db_module=db_module, config=config)
    return await worker.run_once(
        mode=mode,
        limit=limit,
        member_id=member_id,
        member_id_hash=member_id_hash,
        user_id=user_id,
        campaign_id=campaign_id,
    )


if __name__ == "__main__":  # pragma: no cover - command entry point.
    raise SystemExit(main())
