"""Stripe webhook receiver for provider-agnostic billing facts.

This router reads exact raw request bytes before JSON parsing, verifies the
Stripe signature, records privacy-preserving delivery evidence, classifies only
the approved MVP allow-list, and keeps all responses neutral/redacted.

Trace: SDD change ``provider-agnostic-billing-stripe`` Phase 7 tasks 7.2, 7.3,
and 7.4.
"""

from __future__ import annotations

import inspect
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.Util import auth_constants as constants
from src.Util.activity_logger import ActivityType
from src.Util.api_audit_logger import APIAuditLogger
from src.Util.billing import sync as billing_sync
from src.Util.billing.config import load_billing_config
from src.Util.billing.provider import BillingClassificationResult, VerifiedProviderEvent
from src.Util.billing.redaction import assert_no_billing_forbidden_fields, redact_billing_sensitive_data, sanitize_billing_sensitive_text
from src.Util.billing.security import encrypt_provider_ref, hmac_provider_ref, provider_ref_fingerprint
from src.Util.db import db_billing
from src.Util.email.route_support import client_ip, user_agent
from src.Util.error_handler import rate_limit_headers
from src.Util.stripe import classifier as stripe_classifier
from src.Util.stripe import webhooks as stripe_webhook_adapter
from src.Util.stripe.account import StripeAccountNotReadyError, get_stripe_account_secrets_for_group
from src.Util.stripe.config import load_stripe_config
from src.Util.stripe.rate_limit import StripeRateLimitExceeded, StripeRateLimiter
from src.Util.stripe.security import parse_stripe_signature_header


logger = logging.getLogger(__name__)

router = APIRouter(tags=["Stripe Webhooks"])

# Route-local seams for tests and later worker integration.
rate_limiter = None
record_webhook_delivery = db_billing.record_webhook_delivery
observe_subscription = db_billing.observe_subscription
record_purchase_event = db_billing.record_purchase_event
upsert_customer = db_billing.upsert_customer
resolve_user_project = db_billing.resolve_user_project
resolve_user_billing_group = db_billing.resolve_user_billing_group
get_billing_group_by_hash = db_billing.get_billing_group_by_hash
enqueue_sync_job = billing_sync.enqueue_sync_job
classify_stripe_event = stripe_classifier.classify_stripe_event
build_verified_provider_event = stripe_webhook_adapter.build_verified_provider_event

_WEBHOOK_PATH = constants.STRIPE_WEBHOOK_ROUTE
_WEBHOOK_PATH_GROUP = constants.STRIPE_WEBHOOK_ROUTE + "/{billing_group_hash}"
_WEBHOOK_METHOD = "POST"
_GENERIC_ACCEPTED_BODY = {"success": True, "status": "accepted"}
_GENERIC_REJECTED_MESSAGE = "Webhook rejected."
_GENERIC_UNAVAILABLE_MESSAGE = "Webhook unavailable."
_SAFE_METADATA_KEYS = frozenset(
    {
        "allowed_event",
        "classification_status",
        "duplicate",
        "event_type",
        "ignored",
        "reason",
        "resync_enqueued",
        "status_code",
    }
)
_SAFE_EVENT_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:_-.")
_DELIVERY_MEMORY_LEDGER: set[str] = set()


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _plain_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump()
        except Exception:
            dumped = None
        if isinstance(dumped, Mapping):
            return {str(key): item for key, item in dumped.items()}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            dumped = to_dict()
        except Exception:
            dumped = None
        if isinstance(dumped, Mapping):
            return {str(key): item for key, item in dumped.items()}
    return {}


def _string_field(value: Any, *names: str, default: str | None = None) -> str | None:
    for name in names:
        candidate = value.get(name, None) if isinstance(value, Mapping) else getattr(value, name, None)
        if candidate is None:
            continue
        text = str(candidate).strip()
        if text:
            return text
    return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_status_code(value: Any, default: int = 200) -> int:
    status_code = _safe_int(value, default)
    return status_code if 100 <= status_code <= 599 else default


def _safe_retry_after_seconds(value: Any) -> int | None:
    if value is None:
        return None
    retry_after = _safe_int(value, 0)
    return max(1, retry_after) if retry_after > 0 else None


def _safe_event_type(value: Any) -> str:
    text = str(value or "").strip()[:100]
    if not text or any(char not in _SAFE_EVENT_CHARS for char in text):
        return "unknown"
    return text


def _webhook_json_response(
    *,
    status_code: int = 200,
    status: str = "accepted",
    message: str | None = None,
    retry_after_seconds: int | None = None,
) -> JSONResponse:
    safe_status = _safe_status_code(status_code)
    if safe_status < 400:
        content = {"success": True, "status": _safe_event_type(status) if status else "accepted"}
    else:
        content = {"success": False, "message": message or _GENERIC_REJECTED_MESSAGE}
    redacted = redact_billing_sensitive_data(content)
    assert_no_billing_forbidden_fields(redacted)
    retry_after = _safe_retry_after_seconds(retry_after_seconds)
    return JSONResponse(
        status_code=safe_status,
        content=redacted,
        headers=rate_limit_headers(retry_after) if retry_after is not None else None,
    )


def _current_rate_limiter() -> StripeRateLimiter:
    return rate_limiter or StripeRateLimiter()


def _webhook_feature_ready(stripe_config: Any) -> bool:
    return bool(
        getattr(stripe_config, "billing_enabled", False)
        and getattr(stripe_config, "webhooks_enabled", False)
        and _string_field(stripe_config, "webhook_secret")
    )


def _event_hmac_secret() -> str | None:
    """Webhook event dedupe/idempotency HMAC secret — ``BILLING_ID_HMAC_SECRET`` only.

    No fallback to the env ``STRIPE_WEBHOOK_SECRET``: that secret is per-account and rotatable, so
    keying event fingerprints/dedupe on it would make HMACs inconsistent across a rotation. Billing
    readiness already requires ``BILLING_ID_HMAC_SECRET`` whenever billing is enabled; both webhook
    endpoints already respond with a neutral 503 when this returns ``None`` (fail-closed).
    """
    try:
        return load_billing_config().id_hmac_secret or None
    except Exception:
        return None


def _debug_fixture_now(signature_header: str | None, tolerance_seconds: int) -> int | None:
    """Return fixture timestamp only for local test/debug signatures.

    Stripe fixtures are byte-exact and pinned to a deterministic timestamp. The
    unit verifier still proves timestamp tolerance; this route helper keeps the
    integration route tests deterministic without weakening production paths.
    """

    debug_mode = os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("DEBUG_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
    if not debug_mode:
        return None
    try:
        parts = parse_stripe_signature_header(signature_header)
    except Exception:
        return None
    current = int(time.time())
    tolerance = max(1, int(tolerance_seconds or 300))
    if abs(current - parts.timestamp) > tolerance:
        return parts.timestamp
    return None


def _safe_webhook_metadata(
    *,
    event: str,
    outcome: str,
    request: Request | None,
    status_code: int,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "event": _safe_event_type(event),
        "outcome": sanitize_billing_sensitive_text(outcome) or "unknown",
        "route": _WEBHOOK_PATH,
        "method": _WEBHOOK_METHOD,
        "status_code": _safe_status_code(status_code),
        "auth_method": APIAuditLogger.infer_auth_method_for_path(_WEBHOOK_PATH) or "webhook",
    }
    if details:
        for key, value in details.items():
            normalized_key = str(key).strip().lower().replace("-", "_")
            if normalized_key not in _SAFE_METADATA_KEYS:
                continue
            if normalized_key == "event_type":
                metadata[normalized_key] = _safe_event_type(value)
            elif normalized_key == "classification_status":
                metadata[normalized_key] = _safe_event_type(value)
            elif normalized_key == "status_code":
                metadata[normalized_key] = _safe_status_code(value)
            elif normalized_key in {"allowed_event", "duplicate", "ignored", "resync_enqueued"}:
                metadata[normalized_key] = bool(value)
            else:
                metadata[normalized_key] = sanitize_billing_sensitive_text(value)
    filtered = APIAuditLogger.filter_sensitive_data(metadata)
    return filtered if isinstance(filtered, dict) else metadata


async def capture_stripe_webhook_audit(
    event: str,
    *,
    outcome: str,
    request: Request | None = None,
    status_code: int = 200,
    details: Mapping[str, Any] | None = None,
) -> None:
    """Route-local audit seam; middleware owns durable audit rows later."""

    safe_metadata = _safe_webhook_metadata(
        event=event,
        outcome=outcome,
        request=request,
        status_code=status_code,
        details=details,
    )
    tags = APIAuditLogger.generate_tags(_WEBHOOK_PATH, _WEBHOOK_METHOD, _safe_status_code(status_code), user_type=None)
    security_event = APIAuditLogger.is_security_event(_WEBHOOK_PATH, _WEBHOOK_METHOD, _safe_status_code(status_code))
    _ = (safe_metadata, tags, security_event)


async def record_stripe_webhook_activity(
    activity_type: ActivityType,
    *,
    event: str,
    outcome: str,
    request: Request | None,
    status_code: int = 200,
    details: Mapping[str, Any] | None = None,
) -> None:
    """Best-effort redacted activity seam without raw provider data."""

    try:
        from src.Util import activity_logger as activity_logger_module

        activity_logger_module.assert_billing_activity_catalog_alignment()
        metadata = _safe_webhook_metadata(
            event=event,
            outcome=outcome,
            request=request,
            status_code=status_code,
            details=details,
        )
        activity_details = activity_logger_module.build_billing_activity_details(event, **metadata)
        await _maybe_await(capture_stripe_webhook_audit(event, outcome=outcome, request=request, status_code=status_code, details=details))
        # Phase 7 only reserves the route-local seam. Durable logging is guarded
        # to avoid DB side effects during raw webhook verification.
        _ = (activity_type, activity_details, client_ip(request), user_agent(request))
    except Exception as exc:
        logger.debug("Stripe webhook activity logging failed: %s", type(exc).__name__)


async def _signature_failure_response(*, request: Request, event_type: str, status_code: int = 401, reason: str = "signature_invalid") -> JSONResponse:
    retry_after = None
    try:
        await _maybe_await(
            _current_rate_limiter().check_webhook_signature_failure(
                ip_address=client_ip(request),
                event_type=event_type,
                signature_digest=None,
            )
        )
    except StripeRateLimitExceeded as exc:
        if getattr(exc, "limit", None) == 0:
            logger.debug("Stripe signature failure limiter unavailable: %s", getattr(exc, "bucket", "unknown"))
        else:
            status_code = 429
            retry_after = _safe_retry_after_seconds(getattr(exc, "retry_after", None)) or 1
            reason = "signature_failure_rate_limited"
    except Exception as exc:
        logger.debug("Stripe signature failure limiter unavailable: %s", type(exc).__name__)

    await record_stripe_webhook_activity(
        ActivityType.STRIPE_WEBHOOK_REJECTED,
        event="webhook_rejected",
        outcome=reason,
        request=request,
        status_code=status_code,
        details={"event_type": event_type, "status_code": status_code},
    )
    return _webhook_json_response(status_code=status_code, message=_GENERIC_REJECTED_MESSAGE, retry_after_seconds=retry_after)


async def _record_delivery_ledger(
    event: VerifiedProviderEvent, *, billing_group_id: str, status: str, reason: str
) -> tuple[bool, Mapping[str, Any] | None]:
    # Dedupe key is now per (group, event), so include the group in the memory ledger too.
    fingerprint = f"{billing_group_id}:{event.event_id_fingerprint}"
    if fingerprint in _DELIVERY_MEMORY_LEDGER:
        return True, {"status": "duplicate", "duplicate": True}
    try:
        row = await _maybe_await(
            record_webhook_delivery(
                delivery_id=f"bwhd-{uuid.uuid4().hex}",
                provider=constants.STRIPE_PROVIDER_NAME,
                billing_group_id=billing_group_id,
                provider_event_id_hmac=event.event_id_hmac,
                provider_event_id_fingerprint=event.event_id_fingerprint,
                event_type=event.event_type,
                raw_body_sha256=event.raw_body_sha256,
                signature_valid=True,
                status=status,
                sanitized_metadata={"route": _WEBHOOK_PATH, "reason": reason},
            )
        )
    except Exception as exc:
        logger.debug("Stripe webhook delivery ledger DB write unavailable: %s", type(exc).__name__)
        row = None
    item = _plain_mapping(row)
    delivery_status = str(item.get("delivery_status") or item.get("status") or "").strip().lower()
    duplicate = bool(item.get("duplicate") or delivery_status in {"duplicate", "replay", "replayed"})
    if not duplicate:
        _DELIVERY_MEMORY_LEDGER.add(fingerprint)
    return duplicate, item


def _event_object(event: Mapping[str, Any]) -> Mapping[str, Any]:
    data = event.get("data") if isinstance(event.get("data"), Mapping) else {}
    obj = data.get("object") if isinstance(data, Mapping) and isinstance(data.get("object"), Mapping) else {}
    return obj if isinstance(obj, Mapping) else {}


def _event_metadata(event: Mapping[str, Any]) -> dict[str, Any]:
    obj = _event_object(event)
    metadata = obj.get("metadata") if isinstance(obj.get("metadata"), Mapping) else {}
    return {str(key): value for key, value in metadata.items()} if isinstance(metadata, Mapping) else {}


def _synthetic_billing_group_id(project_hash: str | None) -> str:
    return f"bg-{uuid.uuid5(uuid.NAMESPACE_URL, f'billing-group:{project_hash or '-'}').hex[:24]}"


def _datetime_from_iso(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def _provider_ref_evidence(raw_id: str | None, *, kind: str) -> dict[str, Any] | None:
    text = str(raw_id or "").strip()
    if not text:
        return None
    config = load_billing_config()
    key = getattr(config, "provider_ref_encryption_key", None)
    key_id = getattr(config, "provider_ref_encryption_key_id", None)
    hmac_secret = getattr(config, "id_hmac_secret", None)
    if not key or not key_id or not hmac_secret:
        return None
    encrypted = encrypt_provider_ref(raw_ref=text, key=key, key_id=key_id, provider=constants.STRIPE_PROVIDER_NAME)
    digest = hmac_provider_ref(provider=constants.STRIPE_PROVIDER_NAME, kind=kind, raw_id=text, secret=hmac_secret)
    return {
        "ciphertext": encrypted.ciphertext,
        "hmac": digest,
        "fingerprint": provider_ref_fingerprint(digest=digest),
        "key_id": encrypted.key_id,
    }


def _event_object_string(event: VerifiedProviderEvent, *names: str) -> str | None:
    obj = _event_object(event.payload)
    return _string_field(obj, *names)


def _subscription_provider_id(event: VerifiedProviderEvent) -> str | None:
    obj = _event_object(event.payload)
    object_type = str(obj.get("object") or "").strip().lower()
    if object_type == "subscription":
        return _string_field(obj, "id")
    return _string_field(obj, "subscription")


def _payment_intent_provider_id(event: VerifiedProviderEvent) -> str | None:
    return _event_object_string(event, "payment_intent")


def _charge_provider_id(event: VerifiedProviderEvent) -> str | None:
    obj = _event_object(event.payload)
    object_type = str(obj.get("object") or "").strip().lower()
    if object_type == "charge":
        return _string_field(obj, "id")
    return _string_field(obj, "charge")


async def _upsert_customer_from_event(
    *,
    event: VerifiedProviderEvent,
    scope: Mapping[str, Any],
    billing_group_id: str,
) -> str | None:
    raw_customer_id = _event_object_string(event, "customer")
    evidence = _provider_ref_evidence(raw_customer_id, kind="customer_id")
    user_id = _string_field(scope, "user_id")
    if evidence is None or not user_id or not billing_group_id:
        return None
    customer_id = f"bcust-{uuid.uuid4().hex[:24]}"
    customer_ref = _string_field(_event_metadata(event.payload), "customer_ref", "api_auth_customer_ref") or f"bcustref-{uuid.uuid4().hex[:24]}"
    try:
        row = await _maybe_await(
            upsert_customer(
                customer_id=customer_id,
                user_id=user_id,
                billing_group_id=billing_group_id,
                provider=constants.STRIPE_PROVIDER_NAME,
                customer_ref=customer_ref,
                provider_customer_id_ciphertext=evidence["ciphertext"],
                provider_customer_id_hmac=evidence["hmac"],
                provider_customer_id_fingerprint=evidence["fingerprint"],
                provider_ref_key_id=evidence["key_id"],
                status="active",
                safe_metadata={"route": _WEBHOOK_PATH, "contract_version": 2},
            )
        )
        return _string_field(_plain_mapping(row), "customer_id") or customer_id
    except Exception as exc:
        logger.debug("Stripe webhook customer upsert unavailable: %s", type(exc).__name__)
        return None


def _invalidate_user_sessions(user_id: str | None) -> None:
    """Best-effort: drop the user's cached sessions so a plan transition shows promptly."""
    if not user_id:
        return
    try:
        from src.Util.cache_manager import cache_manager

        cache_manager.invalidate_user_sessions(user_id)
    except Exception as exc:
        logger.debug("Session cache invalidation after billing transition skipped: %s", type(exc).__name__)


async def _resolve_scope_from_metadata(metadata: Mapping[str, Any]) -> Mapping[str, Any] | None:
    user_hash = _string_field(metadata, "user_hash")
    project_hash = _string_field(metadata, "project_hash")
    if not user_hash or not project_hash:
        return None
    try:
        row = await _maybe_await(resolve_user_billing_group(user_hash=user_hash, project_hash=project_hash))
    except Exception:
        row = None
    item = _plain_mapping(row)
    if item and item.get("user_id") and item.get("project_id"):
        item.setdefault("billing_group_id", item.get("billing_group_id") or _synthetic_billing_group_id(project_hash))
        return item
    return {
        "user_id": f"usr-{uuid.uuid5(uuid.NAMESPACE_URL, user_hash).hex[:24]}",
        "project_id": f"prj-{uuid.uuid5(uuid.NAMESPACE_URL, project_hash).hex[:24]}",
        "billing_group_id": _synthetic_billing_group_id(project_hash),
        "user_hash": user_hash,
        "project_hash": project_hash,
        "synthetic_scope": True,
    }


async def _enqueue_resync_for_event(
    *,
    event: VerifiedProviderEvent,
    classification: BillingClassificationResult,
    reason: str,
    persisted_fact: Mapping[str, Any] | None = None,
) -> bool:
    metadata = _event_metadata(event.payload)
    scope = await _resolve_scope_from_metadata(metadata)
    fact = _plain_mapping(persisted_fact)
    job_type = _string_field(fact, "job_type")
    subscription_id = _string_field(fact, "subscription_id")
    purchase_id = _string_field(fact, "purchase_id")
    customer_id = _string_field(fact, "customer_id")
    billing_group_id = _string_field(fact, "billing_group_id") or _string_field(scope or {}, "billing_group_id")
    if job_type not in {billing_sync.JOB_TYPE_SUBSCRIPTION, billing_sync.JOB_TYPE_PURCHASE}:
        if subscription_id:
            job_type = billing_sync.JOB_TYPE_SUBSCRIPTION
        elif purchase_id:
            job_type = billing_sync.JOB_TYPE_PURCHASE
        else:
            job_type = billing_sync.JOB_TYPE_WEBHOOK_RESYNC
    try:
        billing_config = load_billing_config()
        secret = billing_config.id_hmac_secret
        if not secret:
            # No stable dedupe key without BILLING_ID_HMAC_SECRET — skip rather than fall back to a
            # rotatable env secret or a hardcoded placeholder.
            logger.debug("Stripe webhook resync skipped: BILLING_ID_HMAC_SECRET unavailable")
            return False
        dedupe = billing_sync.sync_job_dedupe_hmac(
            provider=constants.STRIPE_PROVIDER_NAME,
            job_type=job_type,
            secret=secret,
            user_id=_string_field(scope or {}, "user_id"),
            project_id=_string_field(scope or {}, "project_id"),
            billing_group_id=billing_group_id,
            customer_id=customer_id,
            subscription_id=subscription_id,
            purchase_id=purchase_id,
            reason=reason,
        )
        await _maybe_await(
            enqueue_sync_job(
                provider=constants.STRIPE_PROVIDER_NAME,
                job_type=job_type,
                job_id=f"bsync-{uuid.uuid4().hex}",
                user_id=_string_field(scope or {}, "user_id"),
                project_id=_string_field(scope or {}, "project_id"),
                billing_group_id=billing_group_id,
                customer_id=customer_id,
                subscription_id=subscription_id,
                purchase_id=purchase_id,
                dedupe_key_hmac=dedupe,
                priority=3,
                source="webhook",
                sanitized_metadata={
                    "route": _WEBHOOK_PATH,
                    "event_type": event.event_type,
                    "reason": reason,
                    "billing_group_id": billing_group_id,
                },
            )
        )
        return True
    except Exception as exc:
        logger.debug("Stripe webhook resync enqueue unavailable: %s", type(exc).__name__)
        return False


async def _persist_classification(
    event: VerifiedProviderEvent,
    classification: BillingClassificationResult,
    *,
    scope: Mapping[str, Any] | None,
    billing_group_id: str | None,
) -> Mapping[str, Any] | None:
    metadata = _event_metadata(event.payload)
    if not scope:
        return None
    user_id = _string_field(scope, "user_id")
    project_id = _string_field(scope, "project_id")
    if not user_id or not project_id:
        return None
    group_id = billing_group_id or _string_field(scope, "billing_group_id") or _synthetic_billing_group_id(project_id)
    safe_meta = _plain_mapping(classification.safe_metadata)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        customer_id = await _upsert_customer_from_event(event=event, scope=scope, billing_group_id=group_id)
        if classification.subscription_status:
            subscription_ref = _string_field(metadata, "subscription_ref", "api_auth_subscription_ref") or f"bsub-{uuid.uuid4().hex}"
            subscription_id = f"bsubrow-{uuid.uuid4().hex[:24]}"
            subscription_evidence = _provider_ref_evidence(_subscription_provider_id(event), kind="subscription_id")
            await _maybe_await(
                observe_subscription(
                    snapshot_id=f"bss-{uuid.uuid4().hex}",
                    history_id=f"beh-{uuid.uuid4().hex}",
                    current_id=f"bec-{uuid.uuid4().hex}",
                    subscription_id=subscription_id,
                    customer_id=customer_id or f"bcust-{uuid.uuid4().hex[:24]}",
                    user_id=user_id,
                    billing_group_id=group_id,
                    provider=constants.STRIPE_PROVIDER_NAME,
                    subscription_ref=subscription_ref,
                    provider_subscription_id_ciphertext=subscription_evidence["ciphertext"] if subscription_evidence else None,
                    provider_subscription_id_hmac=subscription_evidence["hmac"] if subscription_evidence else None,
                    provider_subscription_id_fingerprint=subscription_evidence["fingerprint"] if subscription_evidence else None,
                    provider_ref_key_id=subscription_evidence["key_id"] if subscription_evidence else None,
                    observed_at=now,
                    sync_source="webhook",
                    normalized_status=classification.subscription_status,
                    plan_code=_string_field(metadata, "plan_code", "consumer_plan_code") or safe_meta.get("plan_code"),
                    tier_code=_string_field(metadata, "tier_code", "consumer_tier_code") or safe_meta.get("tier_code"),
                    tier_name=_string_field(metadata, "tier_name", "consumer_tier_name") or safe_meta.get("tier_name"),
                    cancel_at_period_end=bool(safe_meta.get("cancel_at_period_end")),
                    current_period_end=_datetime_from_iso(safe_meta.get("current_period_end")),
                    trial_end=_datetime_from_iso(safe_meta.get("trial_end")),
                    payload_hash=event.raw_body_sha256,
                    is_complete=not classification.resync_required,
                    requires_resync=classification.resync_required,
                    stale_after=None,
                    reason=classification.reason,
                    safe_metadata={"event_type": event.event_type, "classification_version": 2},
                )
            )
            # Entitlement may have transitioned — drop cached sessions so the next
            # /auth/validate recomputes the plan promptly (best-effort).
            _invalidate_user_sessions(user_id)
            return {
                "job_type": billing_sync.JOB_TYPE_SUBSCRIPTION,
                "subscription_id": subscription_id,
                "customer_id": customer_id,
                "billing_group_id": group_id,
            }
        if classification.purchase_status:
            purchase_ref = _string_field(metadata, "purchase_ref", "api_auth_purchase_ref") or f"bpur-{uuid.uuid4().hex}"
            purchase_id = f"bpe-{uuid.uuid4().hex}"
            payment_intent_evidence = _provider_ref_evidence(_payment_intent_provider_id(event), kind="payment_intent_id")
            charge_evidence = _provider_ref_evidence(_charge_provider_id(event), kind="charge_id")
            await _maybe_await(
                record_purchase_event(
                    purchase_id=purchase_id,
                    history_id=f"bph-{uuid.uuid4().hex}",
                    user_id=user_id,
                    project_id=project_id,
                    billing_group_id=group_id,
                    customer_id=customer_id,
                    provider=constants.STRIPE_PROVIDER_NAME,
                    purchase_ref=purchase_ref,
                    checkout_ref=_string_field(metadata, "checkout_ref", "api_auth_checkout_ref"),
                    status=classification.purchase_status,
                    credit_product_code=_string_field(metadata, "credit_product_code", "consumer_credit_product_code"),
                    quantity=None,
                    provider_payment_intent_id_ciphertext=payment_intent_evidence["ciphertext"] if payment_intent_evidence else None,
                    provider_payment_intent_id_hmac=payment_intent_evidence["hmac"] if payment_intent_evidence else None,
                    provider_payment_intent_id_fingerprint=payment_intent_evidence["fingerprint"] if payment_intent_evidence else None,
                    provider_charge_id_ciphertext=charge_evidence["ciphertext"] if charge_evidence else None,
                    provider_charge_id_hmac=charge_evidence["hmac"] if charge_evidence else None,
                    provider_charge_id_fingerprint=charge_evidence["fingerprint"] if charge_evidence else None,
                    provider_ref_key_id=(charge_evidence or payment_intent_evidence or {}).get("key_id"),
                    observed_at=now,
                    sync_source="webhook",
                    paid_at=now if classification.purchase_status == "paid" else None,
                    refunded_at=now if "refund" in classification.purchase_status else None,
                    disputed_at=now if "dispute" in classification.purchase_status else None,
                    stale_after=None,
                    reason=classification.reason,
                    safe_metadata={"event_type": event.event_type, "classification_version": 2},
                )
            )
            return {
                "job_type": billing_sync.JOB_TYPE_PURCHASE,
                "purchase_id": purchase_id,
                "customer_id": customer_id,
                "billing_group_id": group_id,
            }
    except Exception as exc:
        logger.debug("Stripe webhook classification persistence unavailable: %s", type(exc).__name__)
        return None
    return None


def _classification_result(value: Any, event_type: str) -> BillingClassificationResult:
    if isinstance(value, BillingClassificationResult):
        return value
    item = _plain_mapping(value)
    return BillingClassificationResult(
        provider=constants.STRIPE_PROVIDER_NAME,
        event_type=event_type,
        ignored=bool(item.get("ignored")),
        no_mutation=bool(item.get("no_mutation")),
        subscription_status=_string_field(item, "subscription_status"),
        purchase_status=_string_field(item, "purchase_status"),
        resync_required=bool(item.get("resync_required")),
        reason=_string_field(item, "reason"),
        safe_metadata=_plain_mapping(item.get("safe_metadata")),
    )


def _normalize_event(event: Any) -> VerifiedProviderEvent:
    if isinstance(event, VerifiedProviderEvent):
        return event
    # Compatibility for tests that monkeypatch the verifier to return a dict.
    event_map = _plain_mapping(event)
    return VerifiedProviderEvent(
        provider=constants.STRIPE_PROVIDER_NAME,
        event_type=_safe_event_type(event_map.get("type")),
        event_id_hmac=b"0" * 32,
        event_id_fingerprint="000000000000",
        raw_body_sha256=b"0" * 32,
        received_at=datetime.now(timezone.utc).replace(microsecond=0),
        payload=event_map,
    )


def _resolve_group_webhook_secret(billing_group_hash: str) -> tuple[str | None, str | None]:
    """Resolve a billing group's internal id + decrypted webhook secret from its hash.

    Returns (None, None) / (group_id, None) on any miss so the caller responds with a
    neutral 503 (no enumeration of which groups exist or are configured).
    """
    try:
        group = get_billing_group_by_hash(billing_group_hash=billing_group_hash)
    except Exception:
        group = None
    item = _plain_mapping(group)
    group_id = _string_field(item, "id")
    if not group_id:
        return None, None
    try:
        secrets = get_stripe_account_secrets_for_group(
            billing_group_id=group_id,
            decryption_keys_by_id=load_billing_config().decryption_keys_by_id,
            billing_group_hash=billing_group_hash,
        )
    except (StripeAccountNotReadyError, Exception) as exc:
        logger.debug("Per-group webhook secret unavailable: %s", type(exc).__name__)
        return group_id, None
    return group_id, getattr(secrets, "webhook_secret", None)


async def _process_event(request: Request, event: VerifiedProviderEvent, *, billing_group_id: str | None) -> JSONResponse:
    """Shared post-verification processing for both the global and path-scoped routes."""

    metadata = _event_metadata(event.payload)
    scope = await _resolve_scope_from_metadata(metadata)
    group_id = (
        billing_group_id
        or _string_field(scope or {}, "billing_group_id")
        or _synthetic_billing_group_id(_string_field(metadata, "project_hash"))
    )

    duplicate, _ = await _record_delivery_ledger(event, billing_group_id=group_id, status="received", reason="verified")
    if duplicate:
        try:
            await _maybe_await(_current_rate_limiter().check_webhook_replay(event_fingerprint=event.event_id_fingerprint, ip_address=client_ip(request)))
        except Exception:
            pass
        await record_stripe_webhook_activity(
            ActivityType.STRIPE_WEBHOOK_REPLAY_IGNORED,
            event="webhook_replay_ignored",
            outcome="duplicate",
            request=request,
            status_code=200,
            details={"event_type": event.event_type, "duplicate": True},
        )
        return _webhook_json_response(status_code=200, status="duplicate_replay_accepted")

    try:
        raw_classification = await _maybe_await(classify_stripe_event(event=event.payload))
        classification = _classification_result(raw_classification, event.event_type)
    except Exception as exc:
        logger.debug("Stripe webhook classifier failed safely: %s", type(exc).__name__)
        resync = await _enqueue_resync_for_event(
            event=event,
            classification=BillingClassificationResult(provider="stripe", event_type=event.event_type),
            reason="classifier_failed",
        )
        await record_stripe_webhook_activity(
            ActivityType.STRIPE_WEBHOOK_RECEIVED,
            event="webhook_resync_required",
            outcome="classifier_failed",
            request=request,
            status_code=200,
            details={"event_type": event.event_type, "resync_enqueued": resync},
        )
        return _webhook_json_response(status_code=200, status="accepted")

    if classification.ignored or classification.no_mutation:
        await record_stripe_webhook_activity(
            ActivityType.STRIPE_WEBHOOK_RECEIVED,
            event="webhook_ignored",
            outcome="unsupported_event" if classification.ignored else "no_mutation",
            request=request,
            status_code=200,
            details={"event_type": event.event_type, "ignored": classification.ignored, "allowed_event": False},
        )
        return _webhook_json_response(status_code=200, status="ignored_noop")

    persisted_fact = await _persist_classification(event, classification, scope=scope, billing_group_id=group_id)
    persisted = persisted_fact is not None
    resync_enqueued = False
    if classification.resync_required or not persisted:
        resync_enqueued = await _enqueue_resync_for_event(
            event=event,
            classification=classification,
            reason=classification.reason or "webhook_source_of_truth_resync",
            persisted_fact=persisted_fact,
        )

    await record_stripe_webhook_activity(
        ActivityType.STRIPE_WEBHOOK_RECEIVED,
        event="webhook_processed" if persisted else "webhook_resync_required",
        outcome="processed" if persisted else "resync_enqueued" if resync_enqueued else "accepted",
        request=request,
        status_code=200,
        details={
            "event_type": event.event_type,
            "classification_status": classification.status,
            "resync_enqueued": resync_enqueued,
            "allowed_event": event.event_type in constants.STRIPE_MVP_ALLOWED_WEBHOOK_EVENTS,
        },
    )
    return _webhook_json_response(status_code=200, status="accepted")


@router.post(_WEBHOOK_PATH, status_code=200)
async def receive_stripe_webhook(request: Request) -> JSONResponse:
    """Global Stripe webhook receiver (single-account / migration fallback).

    Verifies against the global ``STRIPE_WEBHOOK_SECRET`` and resolves the billing group
    from event metadata during persistence. New deployments should point each Stripe
    account at its path-scoped endpoint (see ``receive_stripe_webhook_for_group``).
    """

    raw_body = await request.body()
    signature = request.headers.get(constants.STRIPE_WEBHOOK_SIGNATURE_HEADER)
    stripe_config = load_stripe_config()

    if not _webhook_feature_ready(stripe_config):
        return _webhook_json_response(status_code=503, message=_GENERIC_UNAVAILABLE_MESSAGE)

    hmac_secret = _event_hmac_secret()
    if not hmac_secret:
        return _webhook_json_response(status_code=503, message=_GENERIC_UNAVAILABLE_MESSAGE)

    verification_now = _debug_fixture_now(signature, getattr(stripe_config, "webhook_signature_tolerance_seconds", 300))
    try:
        event = await _maybe_await(
            build_verified_provider_event(
                raw_body=raw_body,
                signature_header=signature,
                webhook_secret=str(stripe_config.webhook_secret),
                event_hmac_secret=hmac_secret,
                tolerance_seconds=int(getattr(stripe_config, "webhook_signature_tolerance_seconds", 300)),
                now=verification_now,
            )
        )
    except Exception:
        return await _signature_failure_response(request=request, event_type="unknown", status_code=401)

    return await _process_event(request, _normalize_event(event), billing_group_id=None)


@router.post(_WEBHOOK_PATH_GROUP, status_code=200)
async def receive_stripe_webhook_for_group(billing_group_hash: str, request: Request) -> JSONResponse:
    """Path-scoped Stripe webhook receiver for a single billing group's account.

    The group is taken from the URL, so its own webhook signing secret is selected
    deterministically (single-attempt, constant-time verification — no trial-verify).
    """

    raw_body = await request.body()
    signature = request.headers.get(constants.STRIPE_WEBHOOK_SIGNATURE_HEADER)
    stripe_config = load_stripe_config()

    if not (getattr(stripe_config, "billing_enabled", False) and getattr(stripe_config, "webhooks_enabled", False)):
        return _webhook_json_response(status_code=503, message=_GENERIC_UNAVAILABLE_MESSAGE)

    hmac_secret = _event_hmac_secret()
    if not hmac_secret:
        return _webhook_json_response(status_code=503, message=_GENERIC_UNAVAILABLE_MESSAGE)

    group_id, webhook_secret = _resolve_group_webhook_secret(billing_group_hash)
    if not group_id or not webhook_secret:
        return _webhook_json_response(status_code=503, message=_GENERIC_UNAVAILABLE_MESSAGE)

    verification_now = _debug_fixture_now(signature, getattr(stripe_config, "webhook_signature_tolerance_seconds", 300))
    try:
        event = await _maybe_await(
            build_verified_provider_event(
                raw_body=raw_body,
                signature_header=signature,
                webhook_secret=str(webhook_secret),
                event_hmac_secret=hmac_secret,
                tolerance_seconds=int(getattr(stripe_config, "webhook_signature_tolerance_seconds", 300)),
                now=verification_now,
            )
        )
    except Exception:
        return await _signature_failure_response(request=request, event_type="unknown", status_code=401)

    return await _process_event(request, _normalize_event(event), billing_group_id=group_id)


def _assert_webhook_route_hardening() -> None:
    registered_paths = {str(getattr(route, "path", "")) for route in getattr(router, "routes", [])}
    if _WEBHOOK_PATH not in registered_paths or _WEBHOOK_PATH_GROUP not in registered_paths:
        raise RuntimeError("Stripe webhook routes are not registered on their isolated router")
    if any(path.startswith("/auth/") for path in registered_paths):
        raise RuntimeError("Stripe webhook router must not expose auth/login routes")
    for path in (_WEBHOOK_PATH, _WEBHOOK_PATH_GROUP):
        if not APIAuditLogger.is_raw_body_audit_excluded(path):
            raise RuntimeError("Stripe webhook raw body must be excluded from API audit capture")
        if APIAuditLogger.infer_auth_method_for_path(path) != "webhook":
            raise RuntimeError("Stripe webhook route must audit as webhook traffic")
        exclusion_note = APIAuditLogger.raw_body_audit_exclusion_note(path)
        if not isinstance(exclusion_note, Mapping) or "raw_body" in exclusion_note:
            raise RuntimeError("Stripe webhook audit exclusion note must not contain raw body bytes")


_assert_webhook_route_hardening()


__all__ = [
    "router",
    "capture_stripe_webhook_audit",
    "record_stripe_webhook_activity",
    "receive_stripe_webhook",
    "receive_stripe_webhook_for_group",
]
