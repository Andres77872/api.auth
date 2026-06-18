"""Shared Patreon sync orchestration helpers.

Trace: SDD change ``patreon-account-link`` tasks 4.6 and 8.7.

This module composes the Phase 4 Patreon client, classifier, DB wrappers, and
DTO models without creating routes, workers, login behavior, JWT/session state,
or raw-provider response surfaces.  All durable mutations go through the real
``src.Util.db.db_patreon`` wrapper surface; fail/retry/release semantics use the
single real ``complete_patreon_sync_job(status=...)`` stored procedure instead
of inventing non-existent finalizers.
"""

from __future__ import annotations

import hashlib
import json
import random
import uuid
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Callable, Iterable, Mapping, MutableMapping, Sequence

from src.Util import auth_constants as constants
from src.Util.Models import (
    PatreonEntitlementS2SResponse,
    PatreonResyncAcceptedResponse,
    PatreonSafeEntitlement,
)
from src.Util.db import db_patreon
from src.Util.patreon import classifier
from src.Util.patreon.client import PatreonAPIError, PatreonRateLimitError, PatreonUnauthorizedError
from src.Util.patreon.config import PatreonConfig
from src.Util.patreon.security import (
    fingerprint_from_digest,
    hash_patreon_identifier,
    raw_body_sha256,
    redact_patreon_mapping,
    sanitize_patreon_log_value,
)


SYNC_JOB_STATUS_PENDING = "pending"
SYNC_JOB_STATUS_RUNNING = "running"
SYNC_JOB_STATUS_RETRY = "retry"
SYNC_JOB_STATUS_COMPLETED = "completed"
SYNC_JOB_STATUS_FAILED = "failed"
SYNC_JOB_STATUS_CANCELLED = "cancelled"
SYNC_JOB_FINAL_STATUSES = frozenset(
    {SYNC_JOB_STATUS_RETRY, SYNC_JOB_STATUS_COMPLETED, SYNC_JOB_STATUS_FAILED, SYNC_JOB_STATUS_CANCELLED}
)

JOB_TYPE_FULL_CAMPAIGN = "full_campaign"
JOB_TYPE_CAMPAIGN_MEMBER = "campaign_member"
JOB_TYPE_USER_MEMBER = "user_member"
JOB_TYPE_RETENTION = "retention"
JOB_TYPE_TOKEN_REFRESH = "token_refresh"
JOB_TYPE_WEBHOOK_RESYNC = "webhook_resync"
DB_JOB_TYPES = frozenset(
    {
        JOB_TYPE_FULL_CAMPAIGN,
        JOB_TYPE_CAMPAIGN_MEMBER,
        JOB_TYPE_USER_MEMBER,
        JOB_TYPE_RETENTION,
        JOB_TYPE_TOKEN_REFRESH,
        JOB_TYPE_WEBHOOK_RESYNC,
    }
)

DB_SNAPSHOT_SYNC_SOURCES = frozenset(
    {"webhook", "api_pull", "manual_resync", "link_activation", "admin_correction"}
)
DB_JOB_SOURCES = frozenset({"webhook", "scheduled", "manual", "link_activation", "retention", "health"})

SAFE_DB_ROW_FIELDS = frozenset(
    {
        "user_hash",
        "external_source",
        "entitlement_status",
        "status",
        "link_status",
        "plan_code",
        "tier_code",
        "tier_name",
        "next_renewal_at",
        "grace_period_until",
        "last_synced_at",
        "stale_after",
        "classification_version",
    }
)


class PatreonSyncError(RuntimeError):
    """Raised for caller/config mistakes in sync orchestration helpers."""


@dataclass(frozen=True)
class PatreonSyncBackoffDecision:
    """Safe retry/finalization decision for a sync job failure."""

    status: str
    retry_after_seconds: int | None = None
    retryable: bool = False
    reason: str = "sync_failed"
    rate_limited: bool = False
    token_invalid: bool = False
    stale_existing_snapshot: bool = True


@dataclass(frozen=True)
class ClaimedPatreonSyncJob:
    """Sanitized representation of a claimed sync job row.

    Hash bytes remain server-only and are hidden from repr.  Raw Patreon IDs are
    never stored here because the DB job table does not store them.
    """

    job_id: str
    job_type: str
    status: str = SYNC_JOB_STATUS_RUNNING
    campaign_id: str | None = None
    user_id: str | None = None
    priority: int | None = None
    attempts: int = 0
    max_attempts: int = constants.DEFAULT_PATREON_SYNC_MAX_ATTEMPTS
    source: str | None = None
    not_before: datetime | str | None = None
    lease_until: datetime | str | None = None
    sanitized_metadata: Mapping[str, Any] | None = None
    member_id_hash: bytes | None = field(default=None, repr=False)


@dataclass(frozen=True)
class PatreonHashedMemberIdentity:
    """Server-only hashed identifiers needed for DB persistence."""

    campaign_db_id: str
    campaign_id_hash: bytes = field(repr=False)
    campaign_id_fingerprint: str
    member_id_hash: bytes = field(repr=False)
    member_id_fingerprint: str
    patreon_user_id_hash: bytes = field(repr=False)
    patreon_user_id_fingerprint: str
    membership_id: str


@dataclass(frozen=True)
class PatreonMemberPersistenceContext:
    """Caller-supplied link authority required to persist one member sync.

    ``raw_*`` fields are accepted only as in-memory server-side inputs for HMAC
    computation and are hidden from repr.  They are never copied to DTOs, logs,
    sync-job metadata, or DB JSON metadata by this module.
    """

    user_id: str
    external_account_id: str
    membership_id: str | None = None
    campaign_db_id: str | None = None
    raw_campaign_id: str | None = field(default=None, repr=False)
    raw_member_id: str | None = field(default=None, repr=False)
    raw_patreon_user_id: str | None = field(default=None, repr=False)
    current_snapshot: Mapping[str, Any] | PatreonSafeEntitlement | None = field(default=None, repr=False)
    id_hmac_secret: str | bytes | None = field(default=None, repr=False)
    safe_metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class PatreonMemberSyncResult:
    """Result of classifying and optionally persisting one member observation."""

    entitlement: PatreonSafeEntitlement
    status: str
    plan_code: str
    tier_code: str | None = None
    link_status: str = constants.PATREON_LINK_STATUS_LINKED
    resync_required: bool = False
    tier_map_miss: bool = False
    unknown_tier: bool = False
    downgrade_applied: bool = False
    persisted: bool = False
    persistence_status: str | None = None
    reasons: tuple[str, ...] = field(default_factory=tuple)
    classification: classifier.PatreonClassificationResult = field(repr=False, default=None)  # type: ignore[assignment]

    def safe_entitlement_dict(self) -> dict[str, Any]:
        return self.entitlement.model_dump_safe()


@dataclass(frozen=True)
class PatreonCampaignSyncResult:
    """Aggregate result for a full campaign sweep without raw provider IDs."""

    campaign_fingerprint: str | None
    pages_fetched: int
    members_seen: int
    members_classified: int
    members_persisted: int
    tier_map_misses: int
    resync_required: int
    retry_after_seconds: int | None = None
    status: str = SYNC_JOB_STATUS_COMPLETED


def _plain_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if is_dataclass(value):
        return {str(key): item for key, item in asdict(value).items()}
    if hasattr(value, "model_dump") and callable(value.model_dump):
        dumped = value.model_dump()
        if isinstance(dumped, Mapping):
            return {str(key): item for key, item in dumped.items()}
    if hasattr(value, "dict") and callable(value.dict):
        dumped = value.dict()
        if isinstance(dumped, Mapping):
            return {str(key): item for key, item in dumped.items()}
    return {}


def _utc_now(now: datetime | str | None = None) -> datetime:
    if now is None:
        candidate = datetime.now(timezone.utc)
    elif isinstance(now, datetime):
        candidate = now
    elif isinstance(now, str) and now.strip():
        candidate = datetime.fromisoformat(now.strip().replace("Z", "+00:00"))
    else:
        raise PatreonSyncError("now must be a datetime, ISO string, or None")
    if candidate.tzinfo is None:
        candidate = candidate.replace(tzinfo=timezone.utc)
    return candidate.astimezone(timezone.utc).replace(microsecond=0)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _redacted_error(value: Any, *, fallback: str = "patreon_sync_failed", max_length: int = 512) -> str:
    text = sanitize_patreon_log_value(str(value or fallback)) or fallback
    return text[:max_length]


def _safe_metadata(metadata: Mapping[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if metadata:
        merged.update(_plain_mapping(metadata))
    for key, value in extra.items():
        if value is not None:
            merged[key] = value
    redacted = redact_patreon_mapping(merged)
    return redacted if isinstance(redacted, dict) else {}


def _coerce_int(value: Any, default: int) -> int:
    try:
        if isinstance(value, bool):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _config_value(config: Any | None, *names: str, default: Any = None) -> Any:
    for name in names:
        if config is not None and hasattr(config, name):
            value = getattr(config, name)
            if value is not None:
                return value
    return default


def _retry_backoff_sequence(config: Any | None) -> tuple[int, ...]:
    value = _config_value(config, "sync_backoff_seconds", "api_retry_backoff_seconds", default=None)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        cleaned = tuple(max(1, _coerce_int(item, 1)) for item in value)
        if cleaned:
            return cleaned
    return tuple(constants.DEFAULT_PATREON_SYNC_BACKOFF_SECONDS)


def _local_backoff_seconds(*, attempts: int, config: Any | None = None, include_jitter: bool = True) -> int:
    sequence = _retry_backoff_sequence(config)
    index = min(max(0, int(attempts) - 1), len(sequence) - 1)
    delay = sequence[index]
    jitter_limit = _coerce_int(
        _config_value(config, "sync_jitter_seconds", "api_retry_jitter_seconds", default=0),
        0,
    )
    if include_jitter and jitter_limit > 0:
        delay += random.SystemRandom().randint(0, jitter_limit)
    return max(1, delay)


def _retry_after_from_error(error: BaseException | Any | None) -> int | None:
    for name in ("retry_after_seconds", "backoff_seconds", "retry_after"):
        value = getattr(error, name, None)
        if value is None:
            continue
        retry_after = _coerce_int(value, 0)
        if retry_after > 0:
            return retry_after
    return None


def _is_token_invalid_error(error: BaseException | Any | None) -> bool:
    return bool(
        isinstance(error, PatreonUnauthorizedError)
        or getattr(error, "token_invalid", False)
        or getattr(error, "creator_token_invalid", False)
        or getattr(error, "token_state", None) == "invalid"
        or getattr(error, "status_code", None) == 401
        or getattr(error, "status", None) == 401
        or "unauthorized" in type(error).__name__.lower()
    )


def _is_rate_limited_error(error: BaseException | Any | None) -> bool:
    return bool(isinstance(error, PatreonRateLimitError) or _retry_after_from_error(error) is not None)


def provider_failure_reason(error: BaseException | Any | None) -> str:
    """Return a non-secret provider-degraded reason for metrics/status.

    The value is intentionally coarse.  It must be safe for activity rows,
    worker heartbeat status, and health metrics: no raw provider body, token,
    member id, campaign id, tier id, email, signature, hash prefix, or payload
    fragment is copied from the exception string.
    """

    if _is_rate_limited_error(error):
        return "provider_rate_limited"
    if _is_token_invalid_error(error):
        return "creator_token_invalid"
    if getattr(error, "timeout", False):
        return "provider_timeout"
    status_code = _coerce_int(getattr(error, "status_code", getattr(error, "status", 0)), 0)
    if status_code >= 500:
        return "provider_outage"
    if isinstance(error, PatreonAPIError):
        return "provider_api_failure"
    return "provider_or_sync_failure"


def _db_snapshot_source(source: str | None) -> str:
    normalized = str(source or constants.PATREON_SYNC_SOURCE_API_PULL).strip()
    aliases = {
        constants.PATREON_SYNC_SOURCE_SCHEDULED: constants.PATREON_SYNC_SOURCE_API_PULL,
        "scheduled": constants.PATREON_SYNC_SOURCE_API_PULL,
        "manual": constants.PATREON_SYNC_SOURCE_MANUAL_RESYNC,
        "member_resync": constants.PATREON_SYNC_SOURCE_MANUAL_RESYNC,
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in DB_SNAPSHOT_SYNC_SOURCES:
        return constants.PATREON_SYNC_SOURCE_API_PULL
    return normalized


def _db_job_source(source: str | None) -> str:
    normalized = str(source or "manual").strip()
    aliases = {
        constants.PATREON_SYNC_SOURCE_WEBHOOK: "webhook",
        constants.PATREON_SYNC_SOURCE_SCHEDULED: "scheduled",
        constants.PATREON_SYNC_SOURCE_MANUAL_RESYNC: "manual",
        constants.PATREON_SYNC_SOURCE_API_PULL: "scheduled",
        "manual_resync": "manual",
        "scheduled_sync": "scheduled",
        "api_pull": "scheduled",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in DB_JOB_SOURCES:
        return "manual"
    return normalized


def _db_job_type(job_type: str | None) -> str:
    normalized = str(job_type or JOB_TYPE_USER_MEMBER).strip()
    aliases = {
        "manual_member": JOB_TYPE_USER_MEMBER,
        "member": JOB_TYPE_USER_MEMBER,
        "per_member": JOB_TYPE_USER_MEMBER,
        "campaign": JOB_TYPE_FULL_CAMPAIGN,
        "full": JOB_TYPE_FULL_CAMPAIGN,
        "retention_only": JOB_TYPE_RETENTION,
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in DB_JOB_TYPES:
        raise PatreonSyncError(f"unsupported Patreon sync job_type: {normalized}")
    return normalized


def calculate_stale_after(
    *,
    now: datetime | str | None = None,
    stale_after_seconds: int | None = None,
    config: PatreonConfig | Any | None = None,
) -> datetime:
    """Return the next safe freshness boundary for an entitlement snapshot."""

    seconds = _coerce_int(
        stale_after_seconds
        if stale_after_seconds is not None
        else _config_value(config, "sync_stale_after_seconds", "stale_after_seconds", default=None),
        constants.DEFAULT_PATREON_SYNC_STALE_AFTER_SECONDS,
    )
    return _utc_now(now) + timedelta(seconds=max(0, seconds))


def is_snapshot_stale(snapshot: Mapping[str, Any] | PatreonSafeEntitlement | None, *, now: datetime | str | None = None) -> bool:
    """Return whether a safe snapshot has crossed its ``stale_after`` timestamp."""

    row = _plain_mapping(snapshot)
    stale_after = _parse_datetime(row.get("stale_after"))
    return bool(stale_after and _utc_now(now) >= stale_after)


def _safe_entitlement_status(status: Any) -> str:
    normalized = str(status or constants.PATREON_ENTITLEMENT_STATUS_FREE).strip().lower()
    if normalized in constants.PATREON_SAFE_ENTITLEMENT_STATUSES:
        return normalized
    return constants.PATREON_ENTITLEMENT_STATUS_FREE


def _safe_link_status(status: Any) -> str:
    normalized = str(status or constants.PATREON_LINK_STATUS_NONE).strip().lower()
    if normalized == constants.PATREON_LINK_STATUS_PROOF_REQUIRED:
        return constants.PATREON_LINK_STATUS_PENDING
    if normalized == constants.PATREON_LINK_STATUS_CONFLICT:
        return constants.PATREON_LINK_STATUS_BLOCKED
    if normalized == constants.PATREON_LINK_STATUS_STALE:
        return constants.PATREON_LINK_STATUS_LINKED
    if normalized in {
        constants.PATREON_LINK_STATUS_NONE,
        constants.PATREON_LINK_STATUS_PENDING,
        constants.PATREON_LINK_STATUS_LINKED,
        constants.PATREON_LINK_STATUS_UNLINKED,
        constants.PATREON_LINK_STATUS_REVOKED,
        constants.PATREON_LINK_STATUS_BLOCKED,
    }:
        return normalized
    return constants.PATREON_LINK_STATUS_NONE


def db_entitlement_row_to_safe_entitlement(
    row: Mapping[str, Any] | None,
    *,
    now: datetime | str | None = None,
) -> PatreonSafeEntitlement:
    """Map a DB current-entitlement row to the Phase 4 safe DTO.

    The DB uses ``entitlement_status``; the DTO contract uses ``status``.  This
    function is the explicit seam that prevents raw DB row exposure.
    """

    safe_row = {key: value for key, value in _plain_mapping(row).items() if key in SAFE_DB_ROW_FIELDS}
    status = _safe_entitlement_status(safe_row.get("status") or safe_row.get("entitlement_status"))
    stale_after = _parse_datetime(safe_row.get("stale_after"))
    if stale_after and _utc_now(now) >= stale_after and status == constants.PATREON_ENTITLEMENT_STATUS_ACTIVE:
        status = constants.PATREON_ENTITLEMENT_STATUS_STALE

    link_status = _safe_link_status(safe_row.get("link_status"))
    external_source = safe_row.get("external_source")
    if link_status in {constants.PATREON_LINK_STATUS_NONE, constants.PATREON_LINK_STATUS_UNLINKED}:
        external_source = None
    elif external_source != constants.PATREON_PROVIDER_NAME:
        external_source = constants.PATREON_PROVIDER_NAME if row else None

    return PatreonSafeEntitlement(
        external_source=external_source,
        status=status,
        plan_code=_clean_text(safe_row.get("plan_code")) or "free",
        tier_code=_clean_text(safe_row.get("tier_code")),
        tier_name=_clean_text(safe_row.get("tier_name")),
        link_status=link_status,
        next_renewal_at=safe_row.get("next_renewal_at"),
        grace_period_until=safe_row.get("grace_period_until"),
        last_synced_at=safe_row.get("last_synced_at"),
        stale_after=safe_row.get("stale_after"),
        classification_version=_coerce_int(
            safe_row.get("classification_version"), constants.PATREON_DEFAULT_CONTRACT_VERSION
        ),
    )


def safe_entitlement_to_dict(entitlement: PatreonSafeEntitlement | Mapping[str, Any]) -> dict[str, Any]:
    """Serialize a safe entitlement through the DTO allow-list."""

    if isinstance(entitlement, PatreonSafeEntitlement):
        return entitlement.model_dump_safe()
    return PatreonSafeEntitlement(**_plain_mapping(entitlement)).model_dump_safe()


def db_entitlement_row_to_s2s_response(
    row: Mapping[str, Any] | None,
    *,
    user_hash: str | None = None,
    now: datetime | str | None = None,
) -> PatreonEntitlementS2SResponse:
    """Build a safe S2S response from a DB row without exposing raw DB fields."""

    row_map = _plain_mapping(row)
    safe_user_hash = _clean_text(user_hash) or _clean_text(row_map.get("user_hash"))
    if not safe_user_hash:
        raise PatreonSyncError("user_hash is required for Patreon S2S response mapping")
    entitlement = db_entitlement_row_to_safe_entitlement(row, now=now)
    return PatreonEntitlementS2SResponse(
        user_hash=safe_user_hash,
        entitlement=entitlement,
        contract_version=entitlement.classification_version,
    )


def get_safe_entitlement_by_user_hash(
    user_hash: str,
    *,
    db_module: Any = db_patreon,
    now: datetime | str | None = None,
) -> PatreonEntitlementS2SResponse:
    """Read current entitlement through the real DB wrapper and map to safe DTO."""

    row = db_module.get_entitlement_by_user_hash(user_hash)
    return db_entitlement_row_to_s2s_response(row, user_hash=user_hash, now=now)


def classification_to_safe_entitlement(
    classification_result: classifier.PatreonClassificationResult | Mapping[str, Any],
) -> PatreonSafeEntitlement:
    """Convert classifier output to the Phase 4 DTO allow-list."""

    safe = classifier.to_safe_entitlement(classification_result)
    return PatreonSafeEntitlement(**safe)


def tier_map_from_config(config: PatreonConfig | Any | None) -> list[dict[str, Any]]:
    """Return classifier tier-map rows from server-only config entries.

    Raw campaign/tier IDs stay in memory and are fed only into the classifier;
    they are not returned by DTO mapping or safe metadata helpers.
    """

    entries = _config_value(config, "campaign_tier_maps", "tier_map_entries", "tier_maps", default=()) or ()
    tier_map: list[dict[str, Any]] = []
    for entry in entries:
        row = _plain_mapping(entry)
        campaign_id = _clean_text(row.get("campaign_id") or getattr(entry, "campaign_id", None))
        tier_id = _clean_text(row.get("tier_id") or getattr(entry, "tier_id", None))
        plan_code = _clean_text(row.get("plan_code") or getattr(entry, "plan_code", None))
        tier_code = _clean_text(row.get("tier_code") or getattr(entry, "tier_code", None))
        if not campaign_id or not tier_id or not plan_code or not tier_code:
            continue
        tier_map.append(
            {
                "campaign_id": campaign_id,
                "tier_id": tier_id,
                "plan_code": plan_code,
                "tier_code": tier_code,
                "tier_name": _clean_text(row.get("tier_name") or getattr(entry, "tier_name", None)),
                "priority": _coerce_int(row.get("priority", getattr(entry, "priority", 0)), 0),
                "active": bool(row.get("active", getattr(entry, "active", True))),
            }
        )
    return tier_map


def classify_member_payload(
    patreon_payload: Mapping[str, Any] | Sequence[Any] | None,
    *,
    config: PatreonConfig | Any | None = None,
    tier_map: Sequence[Any] | None = None,
    now: datetime | str | None = None,
    source: str = constants.PATREON_SYNC_SOURCE_API_PULL,
    is_complete: bool = True,
    current_snapshot: Mapping[str, Any] | PatreonSafeEntitlement | None = None,
    provider_degraded_reason: str | None = None,
    force_stale: bool = False,
) -> PatreonMemberSyncResult:
    """Classify one member payload through ``classifier.py`` and safe DTOs."""

    classification_result = classifier.classify_patreon_entitlement(
        patreon_payload=patreon_payload,
        tier_map=tier_map if tier_map is not None else tier_map_from_config(config),
        now=now,
        source=source,
        is_complete=is_complete,
        current_snapshot=_plain_mapping(current_snapshot),
        stale_after_seconds=_coerce_int(
            _config_value(config, "sync_stale_after_seconds", "stale_after_seconds", default=None),
            constants.DEFAULT_PATREON_SYNC_STALE_AFTER_SECONDS,
        ),
        provider_degraded_reason=provider_degraded_reason,
        force_stale=force_stale,
    )
    entitlement = classification_to_safe_entitlement(classification_result)
    return PatreonMemberSyncResult(
        entitlement=entitlement,
        status=entitlement.status,
        plan_code=entitlement.plan_code,
        tier_code=entitlement.tier_code,
        link_status=entitlement.link_status,
        resync_required=classification_result.resync_required,
        tier_map_miss=classification_result.tier_map_miss,
        unknown_tier=classification_result.unknown_tier,
        downgrade_applied=classification_result.downgrade_applied,
        reasons=tuple(classification_result.reasons),
        classification=classification_result,
    )


def classify_provider_failure_snapshot(
    current_snapshot: Mapping[str, Any] | PatreonSafeEntitlement | None,
    *,
    reason: str,
    config: PatreonConfig | Any | None = None,
    now: datetime | str | None = None,
    source: str = constants.PATREON_SYNC_SOURCE_API_PULL,
) -> PatreonMemberSyncResult:
    """Preserve the last-known safe snapshot under provider-degraded reads.

    With a current paid snapshot, the output is labeled stale/degraded instead
    of refreshing it as active.  With no current snapshot, the output fails
    closed to a non-paid pending/free posture and carries only non-secret reason
    markers.
    """

    return classify_member_payload(
        None,
        config=config,
        tier_map=(),
        now=now,
        source=source,
        is_complete=False,
        current_snapshot=current_snapshot,
        provider_degraded_reason=reason,
        force_stale=True,
    )


def claim_sync_jobs(
    *,
    worker_id: str,
    limit: int | None = None,
    lease_seconds: int | None = None,
    config: PatreonConfig | Any | None = None,
    db_module: Any = db_patreon,
) -> list[ClaimedPatreonSyncJob]:
    """Claim sync jobs through ``db_patreon.claim_patreon_sync_jobs`` only."""

    worker = _clean_text(worker_id)
    if not worker:
        raise PatreonSyncError("worker_id is required to claim Patreon sync jobs")
    batch_size = _coerce_int(
        limit if limit is not None else _config_value(config, "sync_worker_batch_size", "worker_batch_size", default=None),
        constants.DEFAULT_PATREON_SYNC_WORKER_BATCH_SIZE,
    )
    lease = _coerce_int(
        lease_seconds
        if lease_seconds is not None
        else _config_value(config, "sync_job_lease_seconds", "worker_lease_seconds", default=None),
        constants.DEFAULT_PATREON_SYNC_JOB_LEASE_SECONDS,
    )
    rows = db_module.claim_patreon_sync_jobs(worker_id=worker, limit=max(1, batch_size), lease_seconds=max(1, lease))
    return [claimed_sync_job_from_row(row) for row in rows]


def claimed_sync_job_from_row(row: Mapping[str, Any]) -> ClaimedPatreonSyncJob:
    """Map a DB sync-job row to a sanitized internal dataclass."""

    item = _plain_mapping(row)
    job_id = _clean_text(item.get("id") or item.get("job_id"))
    if not job_id:
        raise PatreonSyncError("claimed Patreon sync job row is missing id/job_id")
    return ClaimedPatreonSyncJob(
        job_id=job_id,
        job_type=_db_job_type(item.get("job_type") or item.get("kind")),
        status=_clean_text(item.get("status")) or SYNC_JOB_STATUS_RUNNING,
        campaign_id=_clean_text(item.get("campaign_id")),
        user_id=_clean_text(item.get("user_id")),
        priority=_coerce_int(item.get("priority"), 5),
        attempts=_coerce_int(item.get("attempts"), 0),
        max_attempts=_coerce_int(item.get("max_attempts"), constants.DEFAULT_PATREON_SYNC_MAX_ATTEMPTS),
        source=_clean_text(item.get("source")),
        not_before=item.get("not_before"),
        lease_until=item.get("lease_until"),
        sanitized_metadata=_plain_mapping(item.get("sanitized_metadata")),
        member_id_hash=item.get("member_id_hash") if isinstance(item.get("member_id_hash"), bytes) else None,
    )


def finalize_sync_job(
    *,
    job_id: str,
    status: str,
    retry_after_seconds: int | None = None,
    last_error: Any = None,
    db_module: Any = db_patreon,
) -> dict[str, Any] | None:
    """Finalize/release a sync job using the one real completion wrapper."""

    normalized = str(status or "").strip().lower()
    if normalized not in SYNC_JOB_FINAL_STATUSES:
        raise PatreonSyncError(f"unsupported Patreon sync final status: {normalized}")
    return db_module.complete_patreon_sync_job(
        job_id=job_id,
        status=normalized,
        retry_after_seconds=retry_after_seconds,
        last_error_redacted=_redacted_error(last_error) if last_error is not None else None,
    )


def complete_sync_job(*, job_id: str, db_module: Any = db_patreon) -> dict[str, Any] | None:
    return finalize_sync_job(job_id=job_id, status=SYNC_JOB_STATUS_COMPLETED, db_module=db_module)


def release_sync_job(
    *,
    job_id: str,
    retry_after_seconds: int | None = None,
    reason: str | None = None,
    db_module: Any = db_patreon,
) -> dict[str, Any] | None:
    """Release a claimed job back to retry state without a fake release SP."""

    return finalize_sync_job(
        job_id=job_id,
        status=SYNC_JOB_STATUS_RETRY,
        retry_after_seconds=max(1, retry_after_seconds or 1),
        last_error=reason or "sync_job_released",
        db_module=db_module,
    )


def fail_sync_job(
    *,
    job_id: str,
    error: Any = None,
    attempts: int = 0,
    max_attempts: int | None = None,
    config: PatreonConfig | Any | None = None,
    db_module: Any = db_patreon,
) -> dict[str, Any] | None:
    """Fail or retry a sync job according to safe backoff rules."""

    decision = decide_retry_backoff(
        error=error,
        attempts=attempts,
        max_attempts=max_attempts,
        config=config,
    )
    return finalize_sync_job(
        job_id=job_id,
        status=decision.status,
        retry_after_seconds=decision.retry_after_seconds,
        last_error=error or decision.reason,
        db_module=db_module,
    )


def decide_retry_backoff(
    *,
    error: BaseException | Any | None = None,
    attempts: int = 0,
    max_attempts: int | None = None,
    config: PatreonConfig | Any | None = None,
    retry_after_seconds: int | None = None,
    include_jitter: bool = True,
) -> PatreonSyncBackoffDecision:
    """Decide retry/fail status while preserving snapshots on provider failures."""

    max_allowed = _coerce_int(
        max_attempts if max_attempts is not None else _config_value(config, "sync_max_attempts", default=None),
        constants.DEFAULT_PATREON_SYNC_MAX_ATTEMPTS,
    )
    attempt_count = max(0, _coerce_int(attempts, 0))
    retryable = attempt_count < max(1, max_allowed)
    provider_retry_after = retry_after_seconds or _retry_after_from_error(error)
    rate_limited = _is_rate_limited_error(error) or provider_retry_after is not None
    token_invalid = _is_token_invalid_error(error)

    if rate_limited:
        delay = max(1, _coerce_int(provider_retry_after, _local_backoff_seconds(attempts=attempt_count, config=config, include_jitter=False)))
        return PatreonSyncBackoffDecision(
            status=SYNC_JOB_STATUS_RETRY if retryable else SYNC_JOB_STATUS_FAILED,
            retry_after_seconds=delay if retryable else None,
            retryable=retryable,
            reason="provider_rate_limited",
            rate_limited=True,
            token_invalid=token_invalid,
            stale_existing_snapshot=True,
        )

    if token_invalid:
        return PatreonSyncBackoffDecision(
            status=SYNC_JOB_STATUS_RETRY if retryable else SYNC_JOB_STATUS_FAILED,
            retry_after_seconds=_local_backoff_seconds(attempts=attempt_count, config=config, include_jitter=include_jitter) if retryable else None,
            retryable=retryable,
            reason="creator_token_invalid",
            rate_limited=False,
            token_invalid=True,
            stale_existing_snapshot=True,
        )

    return PatreonSyncBackoffDecision(
        status=SYNC_JOB_STATUS_RETRY if retryable else SYNC_JOB_STATUS_FAILED,
        retry_after_seconds=_local_backoff_seconds(attempts=attempt_count, config=config, include_jitter=include_jitter) if retryable else None,
        retryable=retryable,
        reason=provider_failure_reason(error),
        stale_existing_snapshot=True,
    )


def sync_job_dedupe_hash(*parts: Any) -> bytes:
    """Return a non-reversible active-job dedupe hash from safe/internal parts."""

    material = ":".join(_clean_text(part) or "" for part in parts).encode("utf-8")
    return hashlib.sha256(material).digest()


def enqueue_full_campaign_sync(
    *,
    campaign_id: str,
    job_id: str | None = None,
    priority: int | None = None,
    not_before: datetime | None = None,
    source: str = "scheduled",
    sanitized_metadata: Mapping[str, Any] | None = None,
    db_module: Any = db_patreon,
) -> dict[str, Any] | None:
    """Enqueue a full-campaign job through the real DB wrapper."""

    safe_campaign_id = _clean_text(campaign_id)
    if not safe_campaign_id:
        raise PatreonSyncError("campaign_id is required for full campaign sync enqueue")
    return db_module.enqueue_patreon_sync_job(
        job_id=job_id or _new_id("psj"),
        job_type=JOB_TYPE_FULL_CAMPAIGN,
        campaign_id=safe_campaign_id,
        member_id_hash=None,
        user_id=None,
        dedupe_key_hash=sync_job_dedupe_hash(JOB_TYPE_FULL_CAMPAIGN, safe_campaign_id),
        priority=priority,
        not_before=not_before,
        source=_db_job_source(source),
        sanitized_metadata=_safe_metadata(sanitized_metadata, reason="full_campaign_sync"),
    )


def enqueue_member_resync(
    *,
    campaign_id: str | None = None,
    user_id: str | None = None,
    member_id_hash: bytes | None = None,
    raw_member_id: str | None = None,
    config: PatreonConfig | Any | None = None,
    id_hmac_secret: str | bytes | None = None,
    job_type: str = JOB_TYPE_USER_MEMBER,
    job_id: str | None = None,
    priority: int | None = None,
    not_before: datetime | None = None,
    source: str = "manual",
    user_hash: str | None = None,
    retry_after_seconds: int | None = None,
    sanitized_metadata: Mapping[str, Any] | None = None,
    db_module: Any = db_patreon,
) -> PatreonResyncAcceptedResponse:
    """Enqueue a per-member/user resync and return a safe acceptance DTO."""

    db_job_type = _db_job_type(job_type)
    digest = member_id_hash
    if digest is None and raw_member_id is not None:
        digest = _hash_identifier(raw_member_id, kind="member", config=config, id_hmac_secret=id_hmac_secret)
    if db_job_type in {JOB_TYPE_CAMPAIGN_MEMBER, JOB_TYPE_USER_MEMBER, JOB_TYPE_WEBHOOK_RESYNC} and digest is None and not user_id:
        raise PatreonSyncError("member_id_hash/raw_member_id or user_id is required for member resync enqueue")

    not_before_value = not_before
    if not_before_value is None and retry_after_seconds:
        not_before_value = _utc_now() + timedelta(seconds=max(1, retry_after_seconds))

    db_module.enqueue_patreon_sync_job(
        job_id=job_id or _new_id("psj"),
        job_type=db_job_type,
        campaign_id=_clean_text(campaign_id),
        member_id_hash=digest,
        user_id=_clean_text(user_id),
        dedupe_key_hash=sync_job_dedupe_hash(db_job_type, campaign_id, user_id, digest.hex() if digest else ""),
        priority=priority,
        not_before=not_before_value,
        source=_db_job_source(source),
        sanitized_metadata=_safe_metadata(sanitized_metadata, reason="member_resync"),
    )
    return PatreonResyncAcceptedResponse(
        accepted=True,
        status="queued",
        user_hash=user_hash,
        retry_after_seconds=retry_after_seconds,
        not_before=not_before_value,
        correlation_id=job_id,
    )


async def iter_campaign_member_pages(
    client: Any,
    campaign_id: str,
    *,
    max_pages: int | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield Patreon campaign member pages using ``client.list_campaign_members``."""

    page_cursor: str | None = None
    seen_cursors: set[str | None] = set()
    page_count = 0
    while True:
        if page_cursor in seen_cursors:
            raise PatreonSyncError("Patreon campaign pagination loop detected")
        seen_cursors.add(page_cursor)
        page_count += 1
        if max_pages is not None and max_pages > 0 and page_count > max_pages:
            raise PatreonSyncError("Patreon campaign pagination page cap exceeded")
        page = await client.list_campaign_members(campaign_id, page_cursor=page_cursor)
        yield page
        next_cursor = _clean_text(_plain_mapping(page).get("next_cursor"))
        if not next_cursor:
            break
        page_cursor = next_cursor


async def fetch_campaign_members_paginated(
    client: Any,
    campaign_id: str,
    *,
    max_pages: int | None = None,
) -> dict[str, Any]:
    """Fetch all campaign pages while preserving JSON:API included resources."""

    members: list[Any] = []
    included: list[Any] = []
    pages = 0
    async for page in iter_campaign_member_pages(client, campaign_id, max_pages=max_pages):
        pages += 1
        page_data = page.get("data") if isinstance(page, Mapping) else None
        if isinstance(page_data, list):
            members.extend(page_data)
        elif page_data is not None:
            members.append(page_data)
        page_included = page.get("included") if isinstance(page, Mapping) else None
        if isinstance(page_included, list):
            included.extend(page_included)
    result: dict[str, Any] = {"data": members, "page_count": pages}
    if included:
        result["included"] = included
    return result


async def resync_member(
    client: Any,
    member_id: str,
    *,
    config: PatreonConfig | Any | None = None,
    tier_map: Sequence[Any] | None = None,
    persistence: PatreonMemberPersistenceContext | None = None,
    db_module: Any = db_patreon,
    now: datetime | str | None = None,
    source: str = constants.PATREON_SYNC_SOURCE_MANUAL_RESYNC,
) -> PatreonMemberSyncResult:
    """Fetch, classify, and optionally persist one Patreon member API read."""

    payload = await client.get_member(member_id)
    return classify_and_maybe_persist_member_payload(
        payload,
        config=config,
        tier_map=tier_map,
        persistence=persistence,
        db_module=db_module,
        now=now,
        source=source,
        is_complete=True,
    )


async def resync_full_campaign(
    client: Any,
    campaign_id: str,
    *,
    config: PatreonConfig | Any | None = None,
    tier_map: Sequence[Any] | None = None,
    db_module: Any = db_patreon,
    now: datetime | str | None = None,
    source: str = constants.PATREON_SYNC_SOURCE_SCHEDULED,
    max_pages: int | None = None,
    persistence_resolver: Callable[[Mapping[str, Any]], PatreonMemberPersistenceContext | None] | None = None,
) -> PatreonCampaignSyncResult:
    """Run a source-of-truth campaign sweep using the Phase 4 client/classifier."""

    page_limit = max_pages if max_pages is not None else _coerce_int(
        _config_value(config, "api_max_pages_per_sync", default=None),
        constants.DEFAULT_PATREON_API_MAX_PAGES_PER_SYNC,
    )
    pages = await fetch_campaign_members_paginated(client, campaign_id, max_pages=page_limit)
    members = _payload_members(pages)
    classified = 0
    persisted = 0
    tier_map_misses = 0
    resync_required = 0

    for member in members:
        if not isinstance(member, Mapping):
            continue
        persistence = persistence_resolver(member) if persistence_resolver else None
        result = classify_and_maybe_persist_member_payload(
            {"data": [member], "included": pages.get("included", [])},
            config=config,
            tier_map=tier_map,
            persistence=persistence,
            db_module=db_module,
            now=now,
            source=source,
            is_complete=True,
        )
        classified += 1
        persisted += 1 if result.persisted else 0
        tier_map_misses += 1 if result.tier_map_miss else 0
        resync_required += 1 if result.resync_required else 0

    return PatreonCampaignSyncResult(
        campaign_fingerprint=_campaign_fingerprint(campaign_id, config=config),
        pages_fetched=_coerce_int(pages.get("page_count"), 0),
        members_seen=len(members),
        members_classified=classified,
        members_persisted=persisted,
        tier_map_misses=tier_map_misses,
        resync_required=resync_required,
    )


def classify_and_maybe_persist_member_payload(
    patreon_payload: Mapping[str, Any] | Sequence[Any] | None,
    *,
    config: PatreonConfig | Any | None = None,
    tier_map: Sequence[Any] | None = None,
    persistence: PatreonMemberPersistenceContext | None = None,
    db_module: Any = db_patreon,
    now: datetime | str | None = None,
    source: str = constants.PATREON_SYNC_SOURCE_API_PULL,
    is_complete: bool = True,
    allow_incomplete_snapshot_commit: bool = False,
) -> PatreonMemberSyncResult:
    """Classify a member payload and persist only safe complete observations."""

    current_snapshot = persistence.current_snapshot if persistence else None
    result = classify_member_payload(
        patreon_payload,
        config=config,
        tier_map=tier_map,
        now=now,
        source=source,
        is_complete=is_complete,
        current_snapshot=current_snapshot,
    )
    if persistence is None:
        return result

    if not result.classification.is_complete and not allow_incomplete_snapshot_commit:
        return _copy_member_result(result, persisted=False, persistence_status="skipped_incomplete_non_destructive")

    persistence_status = persist_member_classification(
        patreon_payload=patreon_payload,
        classification_result=result.classification,
        persistence=persistence,
        config=config,
        db_module=db_module,
        now=now,
        source=source,
    )
    return _copy_member_result(result, persisted=True, persistence_status=persistence_status)


def _copy_member_result(
    result: PatreonMemberSyncResult,
    *,
    persisted: bool,
    persistence_status: str | None,
) -> PatreonMemberSyncResult:
    return PatreonMemberSyncResult(
        entitlement=result.entitlement,
        status=result.status,
        plan_code=result.plan_code,
        tier_code=result.tier_code,
        link_status=result.link_status,
        resync_required=result.resync_required,
        tier_map_miss=result.tier_map_miss,
        unknown_tier=result.unknown_tier,
        downgrade_applied=result.downgrade_applied,
        persisted=persisted,
        persistence_status=persistence_status,
        reasons=result.reasons,
        classification=result.classification,
    )


def persist_member_classification(
    *,
    patreon_payload: Mapping[str, Any] | Sequence[Any] | None,
    classification_result: classifier.PatreonClassificationResult,
    persistence: PatreonMemberPersistenceContext,
    config: PatreonConfig | Any | None = None,
    db_module: Any = db_patreon,
    now: datetime | str | None = None,
    source: str = constants.PATREON_SYNC_SOURCE_API_PULL,
) -> str:
    """Persist a complete classified observation via real Patreon DB wrappers."""

    member = _first_member(patreon_payload)
    identity = build_hashed_member_identity(member, persistence=persistence, config=config)
    observed_at = _utc_now(now)
    patron_status = _patron_status_normalized(member)
    tier_hashes = _tier_hashes_json(member, config=config, id_hmac_secret=persistence.id_hmac_secret)
    payload_hash = _payload_hash(patreon_payload)
    safe_metadata = _safe_metadata(
        persistence.safe_metadata,
        reasons=list(classification_result.reasons),
        tier_map_miss=classification_result.tier_map_miss,
        resync_required=classification_result.resync_required,
        downgrade_applied=classification_result.downgrade_applied,
        observed_members=classification_result.observed_members,
        observed_mapped_tiers=classification_result.observed_mapped_tiers,
        observed_unmapped_tiers=classification_result.observed_unmapped_tiers,
    )

    db_module.observe_patreon_membership(
        membership_id=identity.membership_id,
        user_id=persistence.user_id,
        external_account_id=persistence.external_account_id,
        campaign_id=identity.campaign_db_id,
        member_id_hash=identity.member_id_hash,
        member_id_fingerprint=identity.member_id_fingerprint,
        patreon_user_id_hash=identity.patreon_user_id_hash,
        patreon_user_id_fingerprint=identity.patreon_user_id_fingerprint,
        status=_membership_status_from_classification(classification_result),
        metadata=safe_metadata,
    )
    db_module.upsert_patreon_entitlement_snapshot(
        snapshot_id=_new_id("psnap"),
        history_id=None,
        current_id=None,
        user_id=persistence.user_id,
        external_account_id=persistence.external_account_id,
        membership_id=identity.membership_id,
        observed_at=observed_at,
        sync_source=_db_snapshot_source(source),
        patron_status_normalized=patron_status,
        tier_hashes_json=tier_hashes,
        last_charge_status_normalized=_last_charge_status(member),
        next_charge_at=_parse_datetime(_member_attribute(member, "next_charge_date")),
        payload_hash=payload_hash,
        is_complete=classification_result.is_complete,
        requires_resync=classification_result.resync_required,
        entitlement_status=classification_result.status,
        link_status=_safe_link_status(classification_result.link_status),
        plan_code=classification_result.plan_code,
        tier_code=classification_result.tier_code,
        tier_name=classification_result.tier_name,
        next_renewal_at=_parse_datetime(classification_result.next_renewal_at),
        grace_period_until=_parse_datetime(classification_result.grace_period_until),
        stale_after=_parse_datetime(classification_result.stale_after),
        reason=_snapshot_reason(classification_result),
        safe_metadata=safe_metadata,
    )
    return "snapshot_upserted"


def build_hashed_member_identity(
    member: Mapping[str, Any] | None,
    *,
    persistence: PatreonMemberPersistenceContext,
    config: PatreonConfig | Any | None = None,
) -> PatreonHashedMemberIdentity:
    """Hash raw provider IDs before any DB persistence."""

    member_map = _plain_mapping(member)
    raw_member_id = persistence.raw_member_id or _clean_text(member_map.get("id"))
    raw_campaign_id = persistence.raw_campaign_id or _extract_relationship_id(member_map, "campaign")
    raw_user_id = persistence.raw_patreon_user_id or _extract_relationship_id(member_map, "user")
    if not raw_member_id or not raw_campaign_id or not raw_user_id:
        raise PatreonSyncError("raw member, campaign, and Patreon user IDs are required only for server-side HMAC persistence")

    campaign_hash = _hash_identifier(raw_campaign_id, kind="campaign", config=config, id_hmac_secret=persistence.id_hmac_secret)
    member_hash = _hash_identifier(raw_member_id, kind="member", config=config, id_hmac_secret=persistence.id_hmac_secret)
    user_hash = _hash_identifier(raw_user_id, kind="user", config=config, id_hmac_secret=persistence.id_hmac_secret)
    campaign_fp = fingerprint_from_digest(campaign_hash)
    member_fp = fingerprint_from_digest(member_hash)
    user_fp = fingerprint_from_digest(user_hash)
    return PatreonHashedMemberIdentity(
        campaign_db_id=persistence.campaign_db_id or f"pcamp-{campaign_fp}",
        campaign_id_hash=campaign_hash,
        campaign_id_fingerprint=campaign_fp,
        member_id_hash=member_hash,
        member_id_fingerprint=member_fp,
        patreon_user_id_hash=user_hash,
        patreon_user_id_fingerprint=user_fp,
        membership_id=persistence.membership_id or f"pmem-{campaign_fp}-{member_fp}",
    )


def _hash_identifier(
    raw_value: str,
    *,
    kind: str,
    config: PatreonConfig | Any | None = None,
    id_hmac_secret: str | bytes | None = None,
) -> bytes:
    secret = id_hmac_secret or _config_value(config, "id_hmac_secret", "provider_sub_pepper", default=None)
    if not secret:
        raise PatreonSyncError("Patreon ID HMAC secret is required for sync persistence")
    return hash_patreon_identifier(raw_id=raw_value, kind=kind, pepper=secret)


def _campaign_fingerprint(campaign_id: str, *, config: PatreonConfig | Any | None = None) -> str | None:
    try:
        return fingerprint_from_digest(_hash_identifier(campaign_id, kind="campaign", config=config))
    except Exception:
        return None


def _payload_members(payload: Mapping[str, Any] | Sequence[Any] | None) -> list[Any]:
    if payload is None:
        return []
    if isinstance(payload, Mapping):
        data = payload.get("data")
        if isinstance(data, list):
            return list(data)
        if data is not None:
            return [data]
        members = payload.get("members")
        return list(members) if isinstance(members, list) else []
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return list(payload)
    return []


def _first_member(payload: Mapping[str, Any] | Sequence[Any] | None) -> Mapping[str, Any] | None:
    for item in _payload_members(payload):
        if isinstance(item, Mapping):
            return item
    return None


def _relationships(member: Mapping[str, Any] | None) -> Mapping[str, Any]:
    rel = _plain_mapping(member).get("relationships")
    return rel if isinstance(rel, Mapping) else {}


def _extract_relationship_id(member: Mapping[str, Any] | None, name: str) -> str | None:
    relationships = _relationships(member)
    rel = relationships.get(name)
    if not isinstance(rel, Mapping):
        return None
    data = rel.get("data")
    if isinstance(data, Mapping):
        return _clean_text(data.get("id"))
    return None


def _tier_ids(member: Mapping[str, Any] | None) -> tuple[str, ...]:
    relationships = _relationships(member)
    rel = relationships.get("currently_entitled_tiers")
    if not isinstance(rel, Mapping):
        direct = _plain_mapping(member).get("currently_entitled_tiers")
        if isinstance(direct, Mapping):
            rel = direct
        elif isinstance(direct, list):
            return tuple(_clean_text(item.get("id") if isinstance(item, Mapping) else item) for item in direct if _clean_text(item.get("id") if isinstance(item, Mapping) else item))
        else:
            return ()
    data = rel.get("data")
    if isinstance(data, list):
        return tuple(_clean_text(item.get("id")) for item in data if isinstance(item, Mapping) and _clean_text(item.get("id")))
    if isinstance(data, Mapping):
        value = _clean_text(data.get("id"))
        return (value,) if value else ()
    return ()


def _member_attributes(member: Mapping[str, Any] | None) -> Mapping[str, Any]:
    attrs = _plain_mapping(member).get("attributes")
    return attrs if isinstance(attrs, Mapping) else {}


def _member_attribute(member: Mapping[str, Any] | None, name: str) -> Any:
    attrs = _member_attributes(member)
    if name in attrs:
        return attrs.get(name)
    return _plain_mapping(member).get(name)


def _patron_status_normalized(member: Mapping[str, Any] | None) -> str:
    raw = str(_member_attribute(member, "patron_status") or _plain_mapping(member).get("status") or "").strip().lower()
    if raw in {"active", "active_patron"}:
        return "active_patron"
    if raw in {"declined", "declined_patron"}:
        return "declined_patron"
    if raw in {"former", "former_patron", "deleted", "inactive", "cancelled", "canceled"}:
        return "former_patron"
    if raw in {"none", "null"}:
        return "none"
    return "unknown"


def _last_charge_status(member: Mapping[str, Any] | None) -> str | None:
    return _clean_text(_member_attribute(member, "last_charge_status"))


def _tier_hashes_json(
    member: Mapping[str, Any] | None,
    *,
    config: PatreonConfig | Any | None = None,
    id_hmac_secret: str | bytes | None = None,
) -> list[str]:
    hashes: list[str] = []
    for tier_id in _tier_ids(member):
        try:
            hashes.append(_hash_identifier(tier_id, kind="tier", config=config, id_hmac_secret=id_hmac_secret).hex())
        except PatreonSyncError:
            continue
    return hashes


def _payload_hash(payload: Mapping[str, Any] | Sequence[Any] | None) -> bytes:
    raw = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return raw_body_sha256(raw)


def _snapshot_reason(classification_result: classifier.PatreonClassificationResult) -> str:
    if classification_result.tier_map_miss:
        return "tier_map_miss"
    if classification_result.resync_required:
        return "resync_required"
    if classification_result.downgrade_applied:
        return "source_of_truth_downgrade"
    if classification_result.reasons:
        return str(classification_result.reasons[0])[:128]
    return "snapshot_upsert"


def _membership_status_from_classification(classification_result: classifier.PatreonClassificationResult) -> str:
    link_status = _safe_link_status(classification_result.link_status)
    if link_status in {constants.PATREON_LINK_STATUS_PENDING, constants.PATREON_LINK_STATUS_UNLINKED, constants.PATREON_LINK_STATUS_REVOKED}:
        return link_status
    if link_status == constants.PATREON_LINK_STATUS_BLOCKED:
        return constants.PATREON_LINK_STATUS_BLOCKED
    if classification_result.status == constants.PATREON_ENTITLEMENT_STATUS_STALE:
        return constants.PATREON_LINK_STATUS_STALE
    return "active"


def tier_map_miss_metadata(result: PatreonMemberSyncResult | classifier.PatreonClassificationResult) -> dict[str, Any]:
    """Return non-secret metadata for health/activity tier-map-miss handling."""

    classification_result = result.classification if isinstance(result, PatreonMemberSyncResult) else result
    return _safe_metadata(
        reason="tier_map_miss",
        resync_required=classification_result.resync_required,
        observed_members=classification_result.observed_members,
        observed_active_members=classification_result.observed_active_members,
        observed_unmapped_tiers=classification_result.observed_unmapped_tiers,
        observed_ignored_campaigns=classification_result.observed_ignored_campaigns,
    )


def should_commit_classification(classification_result: classifier.PatreonClassificationResult) -> bool:
    """Return False for partial/ambiguous observations that would refresh current state."""

    if not classification_result.is_complete:
        return False
    return True


def safe_resync_response_dict(response: PatreonResyncAcceptedResponse) -> dict[str, Any]:
    return response.model_dump_safe()


__all__ = [
    "ClaimedPatreonSyncJob",
    "PatreonCampaignSyncResult",
    "PatreonHashedMemberIdentity",
    "PatreonMemberPersistenceContext",
    "PatreonMemberSyncResult",
    "PatreonSyncBackoffDecision",
    "PatreonSyncError",
    "calculate_stale_after",
    "claim_sync_jobs",
    "claimed_sync_job_from_row",
    "classification_to_safe_entitlement",
    "classify_and_maybe_persist_member_payload",
    "classify_member_payload",
    "classify_provider_failure_snapshot",
    "complete_sync_job",
    "db_entitlement_row_to_s2s_response",
    "db_entitlement_row_to_safe_entitlement",
    "decide_retry_backoff",
    "enqueue_full_campaign_sync",
    "enqueue_member_resync",
    "fail_sync_job",
    "fetch_campaign_members_paginated",
    "finalize_sync_job",
    "get_safe_entitlement_by_user_hash",
    "is_snapshot_stale",
    "iter_campaign_member_pages",
    "persist_member_classification",
    "provider_failure_reason",
    "release_sync_job",
    "resync_full_campaign",
    "resync_member",
    "safe_entitlement_to_dict",
    "safe_resync_response_dict",
    "should_commit_classification",
    "sync_job_dedupe_hash",
    "tier_map_from_config",
    "tier_map_miss_metadata",
]
