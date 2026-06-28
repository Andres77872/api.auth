"""Provider-agnostic billing source-of-truth sync worker.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` tasks
`8.1` and `8.4`.

The worker owns only billing/provider-fact repair and bounded retention. It does
not issue local sessions/JWTs/cookies/API keys, does not mutate consumer product
membership or credit ledgers, and never logs/returns raw Stripe identifiers,
signatures, idempotency keys, HMACs, fingerprints, secrets, or raw payloads.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import logging
import os
import signal
import time
import uuid
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import src.Util.db_config as db_config
from src.Util import auth_constants as constants
from src.Util.billing import sync as billing_sync
from src.Util.billing.config import load_billing_config
from src.Util.billing.provider import BillingSyncJob, BillingSyncResult
from src.Util.billing.redaction import redact_billing_sensitive_data, sanitize_billing_sensitive_text
from src.Util.billing.security import EncryptedProviderRef
from src.Util.db import db_billing
from src.Util.stripe import sync as stripe_source_sync
from src.Util.stripe.account import StripeAccountNotReadyError, get_stripe_client_for_group
from src.Util.stripe.client import StripeBillingClient
from src.Util.stripe.config import load_stripe_config, validate_stripe_runtime_readiness
from src.Util.system_metrics import SystemMetrics


logger = logging.getLogger(__name__)

_MODE_QUEUED = "queued"
_MODE_RETENTION_ONLY = "retention_only"
_SUPPORTED_ONE_SHOT_MODES = frozenset({_MODE_QUEUED, _MODE_RETENTION_ONLY})
_MODE_ALIASES = {"retention": _MODE_RETENTION_ONLY, "purge": _MODE_RETENTION_ONLY}

_DEFAULT_WORKER_POLL_SECONDS = 30
_DEFAULT_WORKER_BATCH_SIZE = 25
_DEFAULT_WORKER_LEASE_SECONDS = 5 * 60
_DEFAULT_RETENTION_PURGE_INTERVAL_SECONDS = 60 * 60
_RETENTION_INTERVAL_ENV = "BILLING_RETENTION_PURGE_INTERVAL_SECONDS"


@dataclass(frozen=True)
class BillingWorkerItemResult:
    """One safe worker item result."""

    status: str
    job_id: str | None = None
    job_type: str | None = None
    provider: str = constants.STRIPE_PROVIDER_NAME
    retry_after_seconds: int | None = None
    reason: str | None = None
    webhook_delivery_rows_purged: int = 0
    raw_payload_rows_purged: int = 0
    decrypt_failures: int = 0
    safe_metadata: Mapping[str, Any] = field(default_factory=dict)

    def safe_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        redacted = redact_billing_sensitive_data(payload)
        return redacted if isinstance(redacted, dict) else {}


@dataclass(frozen=True)
class BillingWorkerRunResult:
    """Aggregate one-shot result returned by tests/local invocations."""

    worker_id: str
    mode: str
    results: tuple[BillingWorkerItemResult, ...] = field(default_factory=tuple)

    @property
    def processed_count(self) -> int:
        return len(self.results)

    @property
    def retry_count(self) -> int:
        return sum(1 for item in self.results if item.status == billing_sync.SYNC_JOB_STATUS_RETRY)

    @property
    def failed_count(self) -> int:
        return sum(1 for item in self.results if item.status == billing_sync.SYNC_JOB_STATUS_FAILED)


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


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name, str(default))).strip())
    except (TypeError, ValueError):
        return default


def _safe_error_text(value: Any, *, fallback: str = "billing_sync_failed") -> str:
    return billing_sync.redacted_error_text(value, fallback=fallback, max_length=500)


def _safe_metadata(metadata: Mapping[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if metadata:
        merged.update({str(key): item for key, item in metadata.items()})
    for key, value in extra.items():
        if value is not None:
            merged[key] = value
    redacted = redact_billing_sensitive_data(merged)
    return redacted if isinstance(redacted, dict) else {}


def _summary_count(summary: Mapping[str, Any] | None, marker: str) -> int:
    if not summary:
        return 0
    marker_text = marker.lower()
    for key, value in summary.items():
        if marker_text not in str(key).lower():
            continue
        try:
            if isinstance(value, bool):
                continue
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _to_sync_result(value: Any, *, job: billing_sync.ClaimedBillingSyncJob) -> BillingSyncResult:
    if isinstance(value, BillingSyncResult):
        return value
    mapped = _plain_mapping(value)
    if mapped:
        status = str(mapped.get("status") or billing_sync.SYNC_JOB_STATUS_COMPLETED).strip().lower()
        return BillingSyncResult(
            provider=str(mapped.get("provider") or job.provider or constants.STRIPE_PROVIDER_NAME),
            job_id=str(mapped.get("job_id") or job.job_id),
            status=status,
            retry_after_seconds=_int_field(mapped, "retry_after_seconds", default=0) or None,
            retryable=_bool_field(mapped, "retryable", status == billing_sync.SYNC_JOB_STATUS_RETRY),
            reason=_text_field(mapped, "reason"),
            safe_metadata=_safe_metadata(mapped.get("safe_metadata") if isinstance(mapped.get("safe_metadata"), Mapping) else None),
        )
    return BillingSyncResult(provider=job.provider, job_id=job.job_id, status=billing_sync.SYNC_JOB_STATUS_COMPLETED)


def _encrypted_ref_from_row(row: Mapping[str, Any], *ciphertext_names: str) -> EncryptedProviderRef | None:
    key_id = _text_field(row, "provider_ref_key_id", "key_id", "encryption_key_id")
    if not key_id:
        return None
    for name in ciphertext_names:
        ciphertext = row.get(name)
        if ciphertext is None:
            continue
        if isinstance(ciphertext, memoryview):
            ciphertext = ciphertext.tobytes()
        if isinstance(ciphertext, str):
            ciphertext_bytes = ciphertext.encode("utf-8")
        elif isinstance(ciphertext, bytes):
            ciphertext_bytes = ciphertext
        else:
            continue
        if ciphertext_bytes:
            return EncryptedProviderRef(ciphertext=ciphertext_bytes, key_id=key_id)
    return None


class BillingSyncWorker:
    """Small async worker over generic billing sync jobs and retention purge."""

    def __init__(
        self,
        *,
        worker_id: str | None = None,
        client: Any | None = None,
        stripe_client: Any | None = None,
        provider_adapter: Any | None = None,
        db_module: Any | None = None,
        db: Any | None = None,
        redis: Any | None = None,
        config: Any | None = None,
        stripe_config: Any | None = None,
    ) -> None:
        self.config = config or load_billing_config()
        self.stripe_config = stripe_config or load_stripe_config()
        self.worker_id = worker_id or f"billing-sync-worker-{uuid.uuid4()}"
        self.redis = redis if redis is not None else db_config.redis_client
        self.db = db_module if db_module is not None else db if db is not None else db_billing
        self.provider_adapter = provider_adapter
        self._client_injected = client is not None or stripe_client is not None
        self.client = client if client is not None else stripe_client if stripe_client is not None else self._client_from_config()
        self._stopping = False
        self._last_retention_purge_monotonic: float | None = None

    @property
    def sync_enabled(self) -> bool:
        return bool(
            _bool_field(self.config, "sync_enabled", False)
            or _bool_field(self.stripe_config, "sync_enabled", False)
            or self.provider_adapter is not None
        )

    def _client_from_config(self) -> StripeBillingClient | None:
        try:
            readiness = validate_stripe_runtime_readiness(self.stripe_config)
            if not readiness.ready or not _bool_field(self.stripe_config, "sync_enabled", False):
                return None
            return StripeBillingClient.from_config(self.stripe_config)
        except Exception:
            return None

    def request_stop(self, *_args: Any) -> None:
        self._stopping = True

    async def run_once(self, *, mode: str | None = None, limit: int | None = None, now: datetime | None = None) -> BillingWorkerRunResult:
        """Run one safe worker pass.

        ``retention_only`` executes only bounded billing retention cleanup:
        webhook ledger rows after 90 days and raw encrypted quarantine after at
        most 30 days. It never deletes normalized entitlement or purchase history.
        """

        normalized_mode = str(mode or _MODE_QUEUED).strip().lower()
        normalized_mode = _MODE_ALIASES.get(normalized_mode, normalized_mode)
        if normalized_mode not in _SUPPORTED_ONE_SHOT_MODES:
            normalized_mode = _MODE_QUEUED

        if normalized_mode == _MODE_RETENTION_ONLY:
            result = await self.run_retention_purge(now=now)
            await self._record_heartbeat(mode=normalized_mode, results=[result])
            return BillingWorkerRunResult(self.worker_id, normalized_mode, (result,))

        if not self.sync_enabled:
            result = BillingWorkerItemResult(status="disabled", reason="sync_disabled")
            await self._record_heartbeat(mode=normalized_mode, results=[result])
            return BillingWorkerRunResult(self.worker_id, normalized_mode, (result,))

        results = await self.process_queued_jobs(limit=limit)
        retention_result = await self._maybe_run_retention_purge(now=now)
        if retention_result is not None:
            results.append(retention_result)
        if not results:
            results = [BillingWorkerItemResult(status="noop", reason="no_claimed_jobs")]
        await self._record_heartbeat(mode=normalized_mode, results=results)
        return BillingWorkerRunResult(self.worker_id, normalized_mode, tuple(results))

    async def drain_once(self, **kwargs: Any) -> BillingWorkerRunResult:
        return await self.run_once(**kwargs)

    async def process_once(self, **kwargs: Any) -> BillingWorkerRunResult:
        return await self.run_once(**kwargs)

    async def sync_once(self, **kwargs: Any) -> BillingWorkerRunResult:
        return await self.run_once(**kwargs)

    async def process_queued_jobs(self, *, limit: int | None = None) -> list[BillingWorkerItemResult]:
        if not self.sync_enabled:
            return [BillingWorkerItemResult(status="disabled", reason="sync_disabled")]
        try:
            jobs = billing_sync.claim_sync_jobs(
                worker_id=self.worker_id,
                limit=max(1, int(limit or self._worker_batch_size())),
                lease_seconds=max(1, self._worker_lease_seconds()),
                db_module=self.db,
            )
        except Exception as exc:
            logger.warning("Billing sync job claim failed: %s", type(exc).__name__)
            return [BillingWorkerItemResult(status="claim_failed", reason=_safe_error_text(exc))]

        results: list[BillingWorkerItemResult] = []
        for row in jobs or []:
            results.append(await self._process_claimed_job(row))
        return results

    async def run_retention_only(self, *, now: datetime | None = None) -> BillingWorkerItemResult:
        """Operational hook for bounded retention-only maintenance."""

        return await self.run_retention_purge(now=now)

    async def run_retention_purge(self, *, now: datetime | None = None) -> BillingWorkerItemResult:
        """Invoke `sp_billing_retention_purge` through the DB wrapper.

        The SQL procedure purges only bounded webhook ledger rows and encrypted
        raw quarantine ciphertext. Normalized billing entitlement and purchase
        histories remain indefinite.
        """

        _ = now
        windows = self._retention_windows()
        try:
            summary = await self._run_retention_backend(windows=windows)
            webhook_count = _summary_count(summary, "webhook")
            raw_count = _summary_count(summary, "raw")
            await self._record_activity(
                event="billing_retention_purged",
                outcome=billing_sync.SYNC_JOB_STATUS_COMPLETED,
                details={
                    "webhook_delivery_retention_days": windows["webhook_delivery_retention_days"],
                    "raw_payload_retention_days": windows["raw_payload_retention_days"],
                    "webhook_delivery_rows_purged": webhook_count,
                    "raw_payload_rows_purged": raw_count,
                    "history_retention": "indefinite",
                },
            )
            return BillingWorkerItemResult(
                status=billing_sync.SYNC_JOB_STATUS_COMPLETED,
                job_type=billing_sync.JOB_TYPE_RETENTION,
                webhook_delivery_rows_purged=webhook_count,
                raw_payload_rows_purged=raw_count,
                reason="normalized_billing_history_preserved_indefinitely",
            )
        except Exception as exc:
            reason = _safe_error_text(exc)
            await self._record_activity(
                event="billing_retention_purged",
                outcome=billing_sync.SYNC_JOB_STATUS_FAILED,
                details={"reason": reason, "history_retention": "indefinite"},
            )
            return BillingWorkerItemResult(status=billing_sync.SYNC_JOB_STATUS_FAILED, job_type=billing_sync.JOB_TYPE_RETENTION, reason=reason)

    async def _process_claimed_job(self, row: Any) -> BillingWorkerItemResult:
        row_map = _plain_mapping(row)
        try:
            job = row if isinstance(row, billing_sync.ClaimedBillingSyncJob) else billing_sync.claimed_sync_job_from_row(row_map)
        except Exception as exc:
            job_id = _text_field(row_map, "id", "job_id")
            if job_id:
                await self._complete_job(job_id=job_id, status=billing_sync.SYNC_JOB_STATUS_FAILED, last_error=exc)
            return BillingWorkerItemResult(status=billing_sync.SYNC_JOB_STATUS_FAILED, job_id=job_id, reason=_safe_error_text(exc))

        if job.job_type == billing_sync.JOB_TYPE_RETENTION:
            result = await self.run_retention_purge()
            await self._complete_job(job_id=job.job_id, status=result.status, last_error=result.reason)
            return BillingWorkerItemResult(
                status=result.status,
                job_id=job.job_id,
                job_type=job.job_type,
                provider=job.provider,
                webhook_delivery_rows_purged=result.webhook_delivery_rows_purged,
                raw_payload_rows_purged=result.raw_payload_rows_purged,
                reason=result.reason,
            )

        if job.provider != constants.STRIPE_PROVIDER_NAME:
            await self._complete_job(job_id=job.job_id, status=billing_sync.SYNC_JOB_STATUS_FAILED, last_error="unsupported_provider")
            return BillingWorkerItemResult(
                status=billing_sync.SYNC_JOB_STATUS_FAILED,
                job_id=job.job_id,
                job_type=job.job_type,
                provider=job.provider,
                reason="unsupported_provider",
            )

        if not self.sync_enabled:
            await self._complete_job(job_id=job.job_id, status=billing_sync.SYNC_JOB_STATUS_COMPLETED, last_error="sync_disabled_noop")
            return BillingWorkerItemResult(status="disabled", job_id=job.job_id, job_type=job.job_type, provider=job.provider, reason="sync_disabled")

        try:
            await self._record_activity(
                event="billing_sync_started",
                outcome="started",
                details={"provider": job.provider, "job_type": job.job_type},
            )
            sync_result = await self._dispatch_stripe_sync(job=job, row=row_map)
            item = await self._finalize_sync_job(job=job, result=sync_result)
            await self._record_activity(
                event="billing_sync_completed" if item.status == billing_sync.SYNC_JOB_STATUS_COMPLETED else "billing_sync_failed",
                outcome=item.status,
                details={"provider": job.provider, "job_type": job.job_type, "reason": item.reason},
            )
            return item
        except Exception as exc:
            return await self._handle_provider_failure(error=exc, job=job)

    async def _dispatch_stripe_sync(self, *, job: billing_sync.ClaimedBillingSyncJob, row: Mapping[str, Any]) -> BillingSyncResult:
        provider_job = BillingSyncJob(
            job_id=job.job_id,
            provider=job.provider,
            job_type=job.job_type,
            user_id=job.user_id,
            project_id=job.project_id,
            billing_group_id=job.billing_group_id,
            customer_id=job.customer_id,
            subscription_id=job.subscription_id,
            purchase_id=job.purchase_id,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
            safe_metadata=_safe_metadata(job.sanitized_metadata),
        )

        adapter = self.provider_adapter or (self.client if callable(getattr(self.client, "source_of_truth_resync", None)) else None)
        method = getattr(adapter, "source_of_truth_resync", None) if adapter is not None else None
        if callable(method):
            try:
                raw_result = await _maybe_await(method(job=provider_job))
            except TypeError:
                raw_result = await _maybe_await(method(provider_job))
            return _to_sync_result(raw_result, job=job)

        operational_refs = await self._operational_refs_for_job(job=job, row=row)
        client = self._client_for_job(job)
        raw_result = stripe_source_sync.source_of_truth_resync(
            job=provider_job,
            client=client,
            operational_refs=operational_refs,
            decryption_keys_by_id=getattr(self.config, "decryption_keys_by_id", {}),
        )
        return _to_sync_result(raw_result, job=job)

    def _client_for_job(self, job: billing_sync.ClaimedBillingSyncJob) -> StripeBillingClient | None:
        if self._client_injected:
            return self.client
        billing_group_id = job.billing_group_id
        if not billing_group_id and isinstance(job.sanitized_metadata, Mapping):
            billing_group_id = _text_field(job.sanitized_metadata, "billing_group_id")
        if not billing_group_id:
            return None
        try:
            return get_stripe_client_for_group(
                billing_group_id=billing_group_id,
                decryption_keys_by_id=getattr(self.config, "decryption_keys_by_id", {}),
                stripe_global_config=self.stripe_config,
                db=self.db,
            )
        except (StripeAccountNotReadyError, Exception) as exc:
            logger.debug("Billing sync per-group Stripe client unavailable: %s", type(exc).__name__)
            return None

    async def _finalize_sync_job(self, *, job: billing_sync.ClaimedBillingSyncJob, result: BillingSyncResult) -> BillingWorkerItemResult:
        result_status = str(result.status or billing_sync.SYNC_JOB_STATUS_COMPLETED).strip().lower()
        if result_status == billing_sync.SYNC_JOB_STATUS_COMPLETED:
            await self._complete_job(job_id=job.job_id, status=billing_sync.SYNC_JOB_STATUS_COMPLETED)
            return BillingWorkerItemResult(
                status=billing_sync.SYNC_JOB_STATUS_COMPLETED,
                job_id=job.job_id,
                job_type=job.job_type,
                provider=job.provider,
                safe_metadata=_safe_metadata(result.safe_metadata),
            )

        retryable = bool(result.retryable or result_status == billing_sync.SYNC_JOB_STATUS_RETRY)
        if retryable:
            decision = billing_sync.decide_retry_backoff(
                error=result.reason or "provider_or_sync_failure",
                attempts=job.attempts,
                max_attempts=job.max_attempts,
                retry_after_seconds=result.retry_after_seconds,
            )
            await self._complete_job(
                job_id=job.job_id,
                status=decision.status,
                retry_after_seconds=decision.retry_after_seconds,
                last_error=result.reason or decision.reason,
            )
            return BillingWorkerItemResult(
                status=decision.status,
                job_id=job.job_id,
                job_type=job.job_type,
                provider=job.provider,
                retry_after_seconds=decision.retry_after_seconds,
                reason=_safe_error_text(result.reason or decision.reason),
                decrypt_failures=1 if "decrypt" in str(result.reason or "").lower() else 0,
                safe_metadata=_safe_metadata(result.safe_metadata),
            )

        await self._complete_job(job_id=job.job_id, status=billing_sync.SYNC_JOB_STATUS_FAILED, last_error=result.reason or result_status)
        return BillingWorkerItemResult(
            status=billing_sync.SYNC_JOB_STATUS_FAILED,
            job_id=job.job_id,
            job_type=job.job_type,
            provider=job.provider,
            reason=_safe_error_text(result.reason or result_status),
            decrypt_failures=1 if "decrypt" in str(result.reason or "").lower() else 0,
            safe_metadata=_safe_metadata(result.safe_metadata),
        )

    async def _handle_provider_failure(self, *, error: Any, job: billing_sync.ClaimedBillingSyncJob) -> BillingWorkerItemResult:
        decision = billing_sync.decide_retry_backoff(error=error, attempts=job.attempts, max_attempts=job.max_attempts)
        await self._complete_job(
            job_id=job.job_id,
            status=decision.status,
            retry_after_seconds=decision.retry_after_seconds,
            last_error=error or decision.reason,
        )
        reason = _safe_error_text(error or decision.reason)
        await self._record_activity(
            event="billing_sync_failed",
            outcome=decision.status,
            details={"provider": job.provider, "job_type": job.job_type, "reason": reason},
        )
        return BillingWorkerItemResult(
            status=decision.status,
            job_id=job.job_id,
            job_type=job.job_type,
            provider=job.provider,
            retry_after_seconds=decision.retry_after_seconds,
            reason=reason,
            decrypt_failures=1 if "decrypt" in reason.lower() else 0,
        )

    async def _complete_job(
        self,
        *,
        job_id: str | None,
        status: str,
        retry_after_seconds: int | None = None,
        last_error: Any = None,
    ) -> Mapping[str, Any] | None:
        if not job_id:
            return None
        try:
            return await _maybe_await(
                billing_sync.complete_sync_job(
                    job_id=job_id,
                    status=status,
                    retry_after_seconds=retry_after_seconds,
                    last_error=last_error,
                    db_module=self.db,
                )
            )
        except Exception:
            logger.warning("Billing sync job completion failed: %s", "completion_unavailable")
            return None

    async def _operational_refs_for_job(self, *, job: billing_sync.ClaimedBillingSyncJob, row: Mapping[str, Any]) -> dict[str, EncryptedProviderRef]:
        refs: dict[str, EncryptedProviderRef] = {}

        for method_name in ("get_billing_operational_refs_for_sync_job", "get_operational_refs_for_billing_sync_job"):
            method = getattr(self.db, method_name, None)
            if callable(method):
                try:
                    result = _plain_mapping(await _maybe_await(method(job_id=job.job_id)))
                except TypeError:
                    result = _plain_mapping(await _maybe_await(method(job)))
                refs.update(self._refs_from_mapping(result))
                if refs:
                    return refs

        refs.update(self._refs_from_mapping(row))
        if refs:
            return refs

        if job.job_type == billing_sync.JOB_TYPE_CUSTOMER:
            customer_ref = await self._customer_ref_for_job(job)
            if customer_ref is not None:
                refs["customer"] = customer_ref
        elif job.job_type == billing_sync.JOB_TYPE_SUBSCRIPTION:
            subscription_ref = await self._subscription_ref_for_job(job)
            if subscription_ref is not None:
                refs["subscription"] = subscription_ref
        elif job.job_type in {billing_sync.JOB_TYPE_PURCHASE, billing_sync.JOB_TYPE_WEBHOOK_RESYNC}:
            purchase_refs = await self._purchase_refs_for_job(job)
            refs.update(purchase_refs)
        return refs

    def _refs_from_mapping(self, row: Mapping[str, Any]) -> dict[str, EncryptedProviderRef]:
        refs: dict[str, EncryptedProviderRef] = {}
        customer = _encrypted_ref_from_row(row, "provider_customer_id_ciphertext", "customer_ciphertext", "customer")
        subscription = _encrypted_ref_from_row(row, "provider_subscription_id_ciphertext", "subscription_ciphertext", "subscription")
        charge = _encrypted_ref_from_row(row, "provider_charge_id_ciphertext", "charge_ciphertext", "charge")
        payment_intent = _encrypted_ref_from_row(row, "provider_payment_intent_id_ciphertext", "payment_intent_ciphertext", "payment_intent")
        if customer is not None:
            refs["customer"] = customer
        if subscription is not None:
            refs["subscription"] = subscription
        if charge is not None:
            refs["charge"] = charge
        if payment_intent is not None:
            refs["payment_intent"] = payment_intent
        return refs

    async def _customer_ref_for_job(self, job: billing_sync.ClaimedBillingSyncJob) -> EncryptedProviderRef | None:
        method = getattr(self.db, "get_customer_operational_ref", None)
        if not callable(method) or not job.user_id:
            return None
        try:
            if job.billing_group_id:
                row = _plain_mapping(
                    await _maybe_await(
                        method(user_id=job.user_id, billing_group_id=job.billing_group_id, provider=job.provider)
                    )
                )
            elif job.project_id:
                row = _plain_mapping(await _maybe_await(method(user_id=job.user_id, project_id=job.project_id, provider=job.provider)))
            else:
                return None
        except Exception:
            return None
        return _encrypted_ref_from_row(row, "provider_customer_id_ciphertext", "ciphertext")

    async def _subscription_ref_for_job(self, job: billing_sync.ClaimedBillingSyncJob) -> EncryptedProviderRef | None:
        for method_name in ("get_subscription_operational_ref", "get_billing_subscription_operational_ref"):
            method = getattr(self.db, method_name, None)
            if not callable(method):
                continue
            try:
                row = _plain_mapping(await _maybe_await(method(subscription_id=job.subscription_id, provider=job.provider)))
            except TypeError:
                row = _plain_mapping(await _maybe_await(method(job.subscription_id)))
            except Exception:
                row = {}
            ref = _encrypted_ref_from_row(row, "provider_subscription_id_ciphertext", "ciphertext")
            if ref is not None:
                return ref
        if not job.subscription_id:
            return None
        try:
            from src.Util.db_config import get_connection

            with get_connection() as con:
                cur = con.cursor()
                cur.execute(
                    """
                    SELECT provider_subscription_id_ciphertext, provider_ref_key_id
                    FROM billing_subscriptions
                    WHERE id = %s AND provider = %s
                    LIMIT 1
                    """,
                    (job.subscription_id, job.provider),
                )
                row = cur.fetchone()
                columns = [desc[0] for desc in cur.description] if cur.description else []
                mapped = dict(zip(columns, row)) if row else {}
            return _encrypted_ref_from_row(mapped, "provider_subscription_id_ciphertext")
        except Exception:
            return None

    async def _purchase_refs_for_job(self, job: billing_sync.ClaimedBillingSyncJob) -> dict[str, EncryptedProviderRef]:
        for method_name in ("get_purchase_operational_ref", "get_billing_purchase_operational_ref"):
            method = getattr(self.db, method_name, None)
            if not callable(method):
                continue
            try:
                row = _plain_mapping(await _maybe_await(method(purchase_id=job.purchase_id, provider=job.provider)))
            except TypeError:
                row = _plain_mapping(await _maybe_await(method(job.purchase_id)))
            except Exception:
                row = {}
            refs = self._refs_from_mapping(row)
            if refs:
                return refs
        if not job.purchase_id:
            return {}
        try:
            from src.Util.db_config import get_connection

            with get_connection() as con:
                cur = con.cursor()
                cur.execute(
                    """
                    SELECT provider_payment_intent_id_ciphertext,
                           provider_charge_id_ciphertext,
                           provider_ref_key_id
                    FROM billing_purchase_events
                    WHERE id = %s AND provider = %s
                    LIMIT 1
                    """,
                    (job.purchase_id, job.provider),
                )
                row = cur.fetchone()
                columns = [desc[0] for desc in cur.description] if cur.description else []
                mapped = dict(zip(columns, row)) if row else {}
            return self._refs_from_mapping(mapped)
        except Exception:
            return {}

    def _retention_windows(self) -> dict[str, int]:
        webhook_days = min(
            constants.MAX_BILLING_WEBHOOK_DELIVERY_RETENTION_DAYS,
            max(
                0,
                _int_field(
                    self.config,
                    "webhook_delivery_retention_days",
                    default=constants.DEFAULT_BILLING_WEBHOOK_DELIVERY_RETENTION_DAYS,
                ),
            ),
        )
        raw_days = min(
            constants.MAX_BILLING_RAW_PAYLOAD_RETENTION_DAYS,
            max(
                0,
                _int_field(
                    self.config,
                    "raw_payload_retention_days",
                    default=constants.DEFAULT_BILLING_RAW_PAYLOAD_RETENTION_DAYS,
                ),
            ),
        )
        return {
            "webhook_delivery_retention_days": webhook_days,
            "raw_payload_retention_days": raw_days,
        }

    async def _run_retention_backend(self, *, windows: Mapping[str, int]) -> Mapping[str, Any]:
        method = getattr(self.db, "run_billing_retention_purge", None) or getattr(self.db, "run_retention_purge", None)
        if callable(method):
            try:
                result = await _maybe_await(
                    method(
                        webhook_delivery_retention_days=windows["webhook_delivery_retention_days"],
                        raw_payload_retention_days=windows["raw_payload_retention_days"],
                    )
                )
            except TypeError:
                result = await _maybe_await(method())
            return _plain_mapping(result)
        return {
            "webhook_delivery_rows_purged_after_90d": 0,
            "raw_payload_quarantine_rows_purged_after_max_30d": 0,
            "history_retention_status": "billing_entitlement_history_and_billing_purchase_history_preserved_indefinitely",
        }

    async def _maybe_run_retention_purge(self, *, now: datetime | None = None) -> BillingWorkerItemResult | None:
        interval = self._retention_purge_interval_seconds()
        if interval <= 0:
            return None
        current = time.monotonic()
        last = self._last_retention_purge_monotonic
        if last is not None and (current - last) < interval:
            return None
        self._last_retention_purge_monotonic = current
        return await self.run_retention_purge(now=now)

    def _worker_batch_size(self) -> int:
        return _int_field(self.config, "sync_worker_batch_size", "worker_batch_size", default=_DEFAULT_WORKER_BATCH_SIZE)

    def _worker_lease_seconds(self) -> int:
        return _int_field(self.config, "sync_job_lease_seconds", "worker_lease_seconds", default=_DEFAULT_WORKER_LEASE_SECONDS)

    def _worker_poll_seconds(self) -> int:
        return _int_field(self.config, "sync_worker_poll_seconds", "worker_poll_seconds", default=_DEFAULT_WORKER_POLL_SECONDS)

    def _retention_purge_interval_seconds(self) -> int:
        configured = _int_field(self.config, "retention_purge_interval_seconds", default=-1)
        if configured >= 0:
            return configured
        return _env_int(_RETENTION_INTERVAL_ENV, _DEFAULT_RETENTION_PURGE_INTERVAL_SECONDS)

    async def _record_activity(self, *, event: str, outcome: str, details: Mapping[str, Any]) -> None:
        payload = _safe_metadata(details, event=event, outcome=outcome)
        for method_name in ("record_billing_activity", "record_activity"):
            method = getattr(self.db, method_name, None)
            if not callable(method):
                continue
            try:
                await _maybe_await(method(event=event, outcome=outcome, details=payload))
                return
            except TypeError:
                try:
                    await _maybe_await(method(activity_type=event, outcome=outcome, details=payload))
                    return
                except Exception:
                    return
            except Exception:
                return

    async def _record_heartbeat(self, *, mode: str, results: Sequence[BillingWorkerItemResult]) -> None:
        counters = {
            "processed": len(results),
            "completed": sum(1 for item in results if item.status == billing_sync.SYNC_JOB_STATUS_COMPLETED),
            "retry": sum(1 for item in results if item.status == billing_sync.SYNC_JOB_STATUS_RETRY),
            "failed": sum(1 for item in results if item.status == billing_sync.SYNC_JOB_STATUS_FAILED),
            "disabled": sum(1 for item in results if item.status == "disabled"),
            "noop": sum(1 for item in results if item.status == "noop"),
            "claim_failed": sum(1 for item in results if item.status == "claim_failed"),
            "decrypt_failures": sum(item.decrypt_failures for item in results),
            "webhook_delivery_rows_purged": sum(item.webhook_delivery_rows_purged for item in results),
            "raw_payload_rows_purged": sum(item.raw_payload_rows_purged for item in results),
        }
        safe_results = [item.safe_dict() for item in results]

        for method_name in ("record_billing_worker_heartbeat", "record_worker_heartbeat"):
            method = getattr(self.db, method_name, None)
            if not callable(method):
                continue
            try:
                await _maybe_await(method(worker_id=self.worker_id, mode=mode, counters=counters, results=safe_results))
                break
            except TypeError:
                try:
                    await _maybe_await(method(worker_id=self.worker_id, counters=counters, results=safe_results))
                    break
                except Exception:
                    break
            except Exception:
                break

        payload = {
            "worker_id": self.worker_id[:128],
            "mode": mode[:64],
            "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "counters": counters,
            "results": safe_results[:10],
        }
        try:
            self.redis.set(
                SystemMetrics.billing_worker_heartbeat_key(self.worker_id),
                json.dumps(payload, sort_keys=True, default=str),
                ex=300,
            )
        except Exception:
            try:
                SystemMetrics.record_billing_worker_heartbeat(
                    self.worker_id,
                    mode=mode,
                    counters=counters,
                    results=safe_results,
                )
            except Exception:
                pass

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


BillingWorker = BillingSyncWorker


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the billing sync worker once or forever")
    parser.add_argument("--once", action="store_true", help="Process one batch and exit")
    parser.add_argument("--mode", default=_MODE_QUEUED, choices=sorted(_SUPPORTED_ONE_SHOT_MODES), help="One-shot mode")
    parser.add_argument("--limit", type=int, default=None, help="Maximum jobs to claim")
    args = parser.parse_args(argv)

    worker = BillingSyncWorker()
    if args.once:
        asyncio.run(worker.run_once(mode=args.mode, limit=args.limit))
    else:
        worker.run_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI hook.
    raise SystemExit(main())


__all__ = [
    "BillingSyncWorker",
    "BillingWorker",
    "BillingWorkerItemResult",
    "BillingWorkerRunResult",
    "main",
]
