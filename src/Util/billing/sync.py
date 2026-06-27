"""Generic billing sync job helpers and safe retry modeling.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 4.8.

This module models provider-fact resync. It does not call consumers, does not
send callbacks, and does not project product access. Consumers pull safe facts.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from src.Util.billing.redaction import redact_billing_sensitive_data, sanitize_billing_sensitive_text


SYNC_JOB_STATUS_PENDING = "pending"
SYNC_JOB_STATUS_RUNNING = "running"
SYNC_JOB_STATUS_RETRY = "retry"
SYNC_JOB_STATUS_COMPLETED = "completed"
SYNC_JOB_STATUS_FAILED = "failed"
SYNC_JOB_STATUS_CANCELLED = "cancelled"
SYNC_JOB_FINAL_STATUSES = frozenset(
    {SYNC_JOB_STATUS_RETRY, SYNC_JOB_STATUS_COMPLETED, SYNC_JOB_STATUS_FAILED, SYNC_JOB_STATUS_CANCELLED}
)

JOB_TYPE_CUSTOMER = "customer"
JOB_TYPE_SUBSCRIPTION = "subscription"
JOB_TYPE_PURCHASE = "purchase"
JOB_TYPE_WEBHOOK_RESYNC = "webhook_resync"
JOB_TYPE_RETENTION = "retention"
SUPPORTED_JOB_TYPES = frozenset(
    {JOB_TYPE_CUSTOMER, JOB_TYPE_SUBSCRIPTION, JOB_TYPE_PURCHASE, JOB_TYPE_WEBHOOK_RESYNC, JOB_TYPE_RETENTION}
)

PURCHASE_FACT_STATUSES = frozenset({"paid", "refunded", "partially_refunded", "disputed", "dispute_won", "dispute_lost"})
DEFAULT_SYNC_MAX_ATTEMPTS = 8
DEFAULT_SYNC_BACKOFF_SECONDS = (60, 300, 900, 3600, 10800, 21600)


class BillingSyncError(RuntimeError):
    """Raised for invalid generic billing sync orchestration inputs."""


@dataclass(frozen=True)
class BillingSyncBackoffDecision:
    status: str
    retry_after_seconds: int | None = None
    retryable: bool = False
    reason: str = "billing_sync_failed"
    provider_unavailable: bool = False


@dataclass(frozen=True)
class ClaimedBillingSyncJob:
    job_id: str
    provider: str
    job_type: str
    status: str = SYNC_JOB_STATUS_RUNNING
    user_id: str | None = None
    project_id: str | None = None
    billing_group_id: str | None = None
    customer_id: str | None = None
    subscription_id: str | None = None
    purchase_id: str | None = None
    priority: int | None = None
    attempts: int = 0
    max_attempts: int = DEFAULT_SYNC_MAX_ATTEMPTS
    source: str | None = None
    not_before: datetime | str | None = None
    lease_until: datetime | str | None = None
    sanitized_metadata: Mapping[str, Any] = field(default_factory=dict)


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_int(value: Any, default: int) -> int:
    try:
        if isinstance(value, bool):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _utc_now(now: datetime | str | None = None) -> datetime:
    if isinstance(now, datetime):
        parsed = now
    elif isinstance(now, str) and now.strip():
        parsed = datetime.fromisoformat(now.strip().replace("Z", "+00:00"))
    else:
        parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def normalize_job_type(job_type: str | None) -> str:
    normalized = str(job_type or JOB_TYPE_WEBHOOK_RESYNC).strip().lower()
    aliases = {"webhook": JOB_TYPE_WEBHOOK_RESYNC, "source_of_truth": JOB_TYPE_WEBHOOK_RESYNC, "payment": JOB_TYPE_PURCHASE}
    normalized = aliases.get(normalized, normalized)
    if normalized not in SUPPORTED_JOB_TYPES:
        raise BillingSyncError(f"unsupported billing sync job_type: {normalized}")
    return normalized


def redacted_error_text(value: Any, *, fallback: str = "billing_sync_failed", max_length: int = 512) -> str:
    text = sanitize_billing_sensitive_text(value or fallback) or fallback
    return text[:max_length]


def safe_metadata(metadata: Mapping[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if metadata:
        merged.update({str(key): item for key, item in metadata.items()})
    for key, value in extra.items():
        if value is not None:
            merged[key] = value
    redacted = redact_billing_sensitive_data(merged)
    return redacted if isinstance(redacted, dict) else {}


def sync_job_dedupe_hmac(
    *,
    provider: str,
    job_type: str,
    secret: str | bytes,
    user_id: str | None = None,
    project_id: str | None = None,
    billing_group_id: str | None = None,
    customer_id: str | None = None,
    subscription_id: str | None = None,
    purchase_id: str | None = None,
    reason: str | None = None,
) -> bytes:
    provider_value = _clean_text(provider) or "stripe"
    kind = normalize_job_type(job_type)
    material = ":".join(
        [
            "v1",
            "billing_sync",
            provider_value,
            kind,
            _clean_text(user_id) or "",
            _clean_text(project_id) or "",
            _clean_text(billing_group_id) or "",
            _clean_text(customer_id) or "",
            _clean_text(subscription_id) or "",
            _clean_text(purchase_id) or "",
            _clean_text(reason) or "",
        ]
    ).encode("utf-8")
    key = secret if isinstance(secret, bytes) else str(secret or "").encode("utf-8")
    if not key:
        raise BillingSyncError("billing sync HMAC secret is required")
    return hmac.digest(key, material, "sha256")


def sync_job_dedupe_key(*parts: Any) -> bytes:
    """Return a non-reversible local dedupe hash from internal opaque parts."""

    material = ":".join(_clean_text(part) or "" for part in parts).encode("utf-8")
    return hashlib.sha256(material).digest()


def claimed_sync_job_from_row(row: Mapping[str, Any]) -> ClaimedBillingSyncJob:
    item = {str(key): value for key, value in row.items()}
    job_id = _clean_text(item.get("id") or item.get("job_id"))
    if not job_id:
        raise BillingSyncError("claimed billing sync job row is missing id/job_id")
    return ClaimedBillingSyncJob(
        job_id=job_id,
        provider=_clean_text(item.get("provider")) or "stripe",
        job_type=normalize_job_type(_clean_text(item.get("job_type"))),
        status=_clean_text(item.get("status")) or SYNC_JOB_STATUS_RUNNING,
        user_id=_clean_text(item.get("user_id")),
        project_id=_clean_text(item.get("project_id")),
        billing_group_id=_clean_text(item.get("billing_group_id")),
        customer_id=_clean_text(item.get("customer_id")),
        subscription_id=_clean_text(item.get("subscription_id")),
        purchase_id=_clean_text(item.get("purchase_id")),
        priority=_coerce_int(item.get("priority"), 5),
        attempts=_coerce_int(item.get("attempts"), 0),
        max_attempts=_coerce_int(item.get("max_attempts"), DEFAULT_SYNC_MAX_ATTEMPTS),
        source=_clean_text(item.get("source")),
        not_before=item.get("not_before"),
        lease_until=item.get("lease_until"),
        sanitized_metadata=safe_metadata(item.get("sanitized_metadata") if isinstance(item.get("sanitized_metadata"), Mapping) else None),
    )


def _db_module(db_module: Any = None) -> Any:
    if db_module is not None:
        return db_module
    from src.Util.db import db_billing

    return db_billing


def enqueue_sync_job(
    *,
    provider: str,
    job_type: str,
    dedupe_key_hmac: bytes,
    job_id: str | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
    billing_group_id: str | None = None,
    customer_id: str | None = None,
    subscription_id: str | None = None,
    purchase_id: str | None = None,
    priority: int | None = None,
    not_before: datetime | None = None,
    source: str = "manual",
    sanitized_metadata: Mapping[str, Any] | None = None,
    db_module: Any = None,
) -> dict[str, Any] | None:
    return _db_module(db_module).enqueue_sync_job(
        job_id=job_id or _new_id("bsj"),
        provider=_clean_text(provider) or "stripe",
        job_type=normalize_job_type(job_type),
        user_id=_clean_text(user_id),
        project_id=_clean_text(project_id),
        billing_group_id=_clean_text(billing_group_id),
        customer_id=_clean_text(customer_id),
        subscription_id=_clean_text(subscription_id),
        purchase_id=_clean_text(purchase_id),
        dedupe_key_hmac=dedupe_key_hmac,
        priority=priority,
        not_before=not_before,
        source=_clean_text(source) or "manual",
        sanitized_metadata=safe_metadata(sanitized_metadata),
    )


def claim_sync_jobs(
    *,
    worker_id: str,
    limit: int = 25,
    lease_seconds: int = 300,
    db_module: Any = None,
) -> list[ClaimedBillingSyncJob]:
    worker = _clean_text(worker_id)
    if not worker:
        raise BillingSyncError("worker_id is required")
    rows = _db_module(db_module).claim_sync_jobs(worker_id=worker, limit=max(1, int(limit)), lease_seconds=max(1, int(lease_seconds)))
    return [claimed_sync_job_from_row(row) for row in rows]


def complete_sync_job(
    *,
    job_id: str,
    status: str = SYNC_JOB_STATUS_COMPLETED,
    retry_after_seconds: int | None = None,
    last_error: Any = None,
    db_module: Any = None,
) -> dict[str, Any] | None:
    normalized = str(status or "").strip().lower()
    if normalized not in SYNC_JOB_FINAL_STATUSES:
        raise BillingSyncError(f"unsupported billing sync final status: {normalized}")
    return _db_module(db_module).complete_sync_job(
        job_id=job_id,
        status=normalized,
        retry_after_seconds=retry_after_seconds,
        last_error_redacted=redacted_error_text(last_error) if last_error is not None else None,
    )


def decide_retry_backoff(
    *,
    error: Any = None,
    attempts: int = 0,
    max_attempts: int = DEFAULT_SYNC_MAX_ATTEMPTS,
    retry_after_seconds: int | None = None,
    backoff_seconds: Sequence[int] = DEFAULT_SYNC_BACKOFF_SECONDS,
) -> BillingSyncBackoffDecision:
    attempt_count = max(0, _coerce_int(attempts, 0))
    max_allowed = max(1, _coerce_int(max_attempts, DEFAULT_SYNC_MAX_ATTEMPTS))
    retryable = attempt_count < max_allowed
    provider_retry_after = retry_after_seconds or _coerce_int(getattr(error, "retry_after_seconds", 0), 0) or None
    if provider_retry_after:
        return BillingSyncBackoffDecision(
            status=SYNC_JOB_STATUS_RETRY if retryable else SYNC_JOB_STATUS_FAILED,
            retry_after_seconds=max(1, provider_retry_after) if retryable else None,
            retryable=retryable,
            reason="provider_rate_limited",
            provider_unavailable=True,
        )
    sequence = tuple(max(1, _coerce_int(item, 1)) for item in backoff_seconds) or DEFAULT_SYNC_BACKOFF_SECONDS
    index = min(attempt_count, len(sequence) - 1)
    return BillingSyncBackoffDecision(
        status=SYNC_JOB_STATUS_RETRY if retryable else SYNC_JOB_STATUS_FAILED,
        retry_after_seconds=sequence[index] if retryable else None,
        retryable=retryable,
        reason="provider_or_sync_failure",
        provider_unavailable=True,
    )


def fail_sync_job(
    *,
    job_id: str,
    error: Any = None,
    attempts: int = 0,
    max_attempts: int = DEFAULT_SYNC_MAX_ATTEMPTS,
    db_module: Any = None,
) -> dict[str, Any] | None:
    decision = decide_retry_backoff(error=error, attempts=attempts, max_attempts=max_attempts)
    return complete_sync_job(
        job_id=job_id,
        status=decision.status,
        retry_after_seconds=decision.retry_after_seconds,
        last_error=error or decision.reason,
        db_module=db_module,
    )


def not_before_after(seconds: int, *, now: datetime | str | None = None) -> datetime:
    return _utc_now(now) + timedelta(seconds=max(1, _coerce_int(seconds, 1)))


__all__ = [
    "BillingSyncBackoffDecision",
    "BillingSyncError",
    "ClaimedBillingSyncJob",
    "JOB_TYPE_CUSTOMER",
    "JOB_TYPE_PURCHASE",
    "JOB_TYPE_RETENTION",
    "JOB_TYPE_SUBSCRIPTION",
    "JOB_TYPE_WEBHOOK_RESYNC",
    "PURCHASE_FACT_STATUSES",
    "SYNC_JOB_STATUS_CANCELLED",
    "SYNC_JOB_STATUS_COMPLETED",
    "SYNC_JOB_STATUS_FAILED",
    "SYNC_JOB_STATUS_PENDING",
    "SYNC_JOB_STATUS_RETRY",
    "SYNC_JOB_STATUS_RUNNING",
    "claim_sync_jobs",
    "claimed_sync_job_from_row",
    "complete_sync_job",
    "decide_retry_backoff",
    "enqueue_sync_job",
    "fail_sync_job",
    "normalize_job_type",
    "not_before_after",
    "redacted_error_text",
    "safe_metadata",
    "sync_job_dedupe_hmac",
    "sync_job_dedupe_key",
]
