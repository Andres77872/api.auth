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
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Mapping

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse

from src.Util import auth_constants as constants
from src.Util.activity_logger import ActivityType
from src.Util.api_audit_logger import APIAuditLogger
from src.Util.billing import sync as billing_sync
from src.Util.billing.config import load_billing_config
from src.Util.billing.provider import BillingClassificationResult, VerifiedProviderEvent
from src.Util.billing.redaction import assert_no_billing_forbidden_fields, redact_billing_sensitive_data, sanitize_billing_sensitive_text
from src.Util.billing.security import provider_ref_evidence, provider_ref_hmac_or_none
from src.Util.db import db_billing
from src.Util.email.route_support import client_ip, user_agent
from src.Util.error_handler import rate_limit_headers
from src.Util.stripe import classifier as stripe_classifier
from src.Util.stripe import webhooks as stripe_webhook_adapter
from src.Util.stripe.account import StripeAccountNotReadyError, get_stripe_account_secrets_for_group
from src.Util.stripe.config import load_stripe_config
from src.Util.stripe.rate_limit import StripeRateLimitExceeded, StripeRateLimiter


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
resolve_event_scope = db_billing.resolve_event_scope
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


# --------------------------------------------------------------------------- OpenAPI documentation
# The handlers read the raw body and the signature header from the Request themselves, so the
# body and header are declared here for the schema only. Webhooks carry no security scheme:
# the Stripe signature is the credential.
def _webhook_openapi_extra(*, secret_label: str) -> dict[str, Any]:
    return {
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "description": "Raw Stripe event, verified byte-for-byte against Stripe-Signature",
                    }
                }
            },
        },
        "parameters": [
            {
                "name": constants.STRIPE_WEBHOOK_SIGNATURE_HEADER,
                "in": "header",
                "required": True,
                "schema": {"type": "string"},
                "description": f"Stripe signature (`t=...,v1=...`) over the exact raw body, made with {secret_label}.",
            }
        ],
    }


_WEBHOOK_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": (
            "`{\"success\": true, \"status\": ...}` with `accepted` (processed, queued for resync, or not "
            "attributable to any user), `ignored_noop` (event type not handled or not in "
            "`STRIPE_ALLOWED_WEBHOOK_EVENTS`), or `duplicate_replay_accepted` (already received)."
        )
    },
    401: {
        "description": (
            "`{\"success\": false, \"message\": \"Webhook rejected.\"}`: the signature, timestamp, JSON body, "
            "event id, or event `api_version` check failed."
        )
    },
    429: {"description": "Too many signature failures from this client IP; retry after `Retry-After`."},
}


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


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value if value is not None else "").strip().lower() in {"1", "true", "yes", "on"}


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


def _event_hmac_secret() -> str | None:
    """Webhook event dedupe/idempotency HMAC secret — ``BILLING_ID_HMAC_SECRET`` only.

    Billing signing secrets rotate per account. A separate HMAC secret keeps event
    fingerprints stable across rotation; a missing secret returns a neutral 503.
    """
    try:
        return load_billing_config().id_hmac_secret or None
    except Exception:
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


def _invoice_subscription_details(obj: Mapping[str, Any]) -> Mapping[str, Any]:
    """An invoice's subscription details: `parent.subscription_details` since Stripe API 2025-03-31."""

    parent = obj.get("parent")
    if isinstance(parent, Mapping) and isinstance(parent.get("subscription_details"), Mapping):
        return parent["subscription_details"]
    details = obj.get("subscription_details")
    return details if isinstance(details, Mapping) else {}


def _event_metadata(event: Mapping[str, Any]) -> dict[str, Any]:
    """The event object's metadata; invoices fall back to their subscription's metadata."""

    obj = _event_object(event)
    merged: dict[str, Any] = {}
    subscription_metadata = _invoice_subscription_details(obj).get("metadata")
    if isinstance(subscription_metadata, Mapping):
        merged.update({str(key): value for key, value in subscription_metadata.items()})
    own_metadata = obj.get("metadata")
    if isinstance(own_metadata, Mapping):
        merged.update({str(key): value for key, value in own_metadata.items() if value not in (None, "")})
    return merged


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
    return provider_ref_evidence(raw_id, kind=kind, config=load_billing_config(), provider=constants.STRIPE_PROVIDER_NAME)


def _id_field(value: Any) -> str | None:
    """A Stripe reference field is an id string, or the expanded object carrying `id`."""

    if isinstance(value, Mapping):
        return _string_field(value, "id")
    return _string_field({"value": value}, "value")


def _subscription_provider_id(event: VerifiedProviderEvent) -> str | None:
    obj = _event_object(event.payload)
    object_type = str(obj.get("object") or "").strip().lower()
    if object_type == "subscription":
        return _string_field(obj, "id")
    if object_type == "invoice":
        return _id_field(_invoice_subscription_details(obj).get("subscription")) or _id_field(obj.get("subscription"))
    return _id_field(obj.get("subscription"))


def _payment_intent_provider_id(event: VerifiedProviderEvent) -> str | None:
    return _id_field(_event_object(event.payload).get("payment_intent"))


def _charge_provider_id(event: VerifiedProviderEvent) -> str | None:
    obj = _event_object(event.payload)
    object_type = str(obj.get("object") or "").strip().lower()
    if object_type == "charge":
        return _string_field(obj, "id")
    return _id_field(obj.get("charge"))


def _customer_provider_id(event: VerifiedProviderEvent) -> str | None:
    return _id_field(_event_object(event.payload).get("customer"))


def _price_provider_id(event: VerifiedProviderEvent) -> str | None:
    obj = _event_object(event.payload)
    if str(obj.get("object") or "").strip().lower() != "subscription":
        return None
    items = obj.get("items")
    data = items.get("data") if isinstance(items, Mapping) else None
    if isinstance(data, list) and data and isinstance(data[0], Mapping):
        return _id_field(data[0].get("price"))
    return None


def _checkout_ref_from_event(event: VerifiedProviderEvent, metadata: Mapping[str, Any]) -> str | None:
    ref = _string_field(metadata, "api_auth_checkout_ref", "checkout_ref")
    if ref:
        return ref
    obj = _event_object(event.payload)
    if str(obj.get("object") or "").strip().lower() == "checkout.session":
        # Checkout sets client_reference_id to the checkout ref.
        candidate = _string_field(obj, "client_reference_id")
        if candidate and candidate.startswith("bco-"):
            return candidate
    return None


def _usable_label(value: Any) -> str | None:
    text = _string_field({"value": value}, "value")
    return None if not text or text.lower() == "free" else text


async def _upsert_customer_from_event(
    *,
    event: VerifiedProviderEvent,
    scope: Mapping[str, Any],
    billing_group_id: str,
) -> str | None:
    raw_customer_id = _customer_provider_id(event)
    evidence = _provider_ref_evidence(raw_customer_id, kind="customer_id")
    user_id = _string_field(scope, "user_id")
    if evidence is None or not user_id or not billing_group_id:
        return None
    customer_id = f"bcustrow-{uuid.uuid4().hex[:24]}"
    customer_ref = _string_field(_event_metadata(event.payload), "customer_ref", "api_auth_customer_ref") or f"bcust-{uuid.uuid4().hex}"
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
    """Best-effort: drop the user's derived ``session_full:*`` entries so the next validate
    recomputes the plan.

    The ``session:*`` access sessions are auth state, not a cache, and stay valid: a plan
    transition must not sign the user out.
    """
    if not user_id:
        return
    try:
        from src.Util.cache_manager import cache_manager

        cache_manager.invalidate_user_full_sessions(user_id)
    except Exception as exc:
        logger.debug("Session cache invalidation after billing transition skipped: %s", type(exc).__name__)


async def _resolve_scope_from_metadata(metadata: Mapping[str, Any]) -> dict[str, Any] | None:
    """Resolve `user_hash` + `project_hash` metadata to internal ids; None when they do not resolve.

    Never invents ids: an event that cannot be tied to a real user writes no fact.
    """

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
        return item
    return None


async def _lookup_event_refs(
    event: VerifiedProviderEvent,
    metadata: Mapping[str, Any],
    *,
    billing_group_id: str | None,
) -> dict[str, Any]:
    """Map the event's checkout ref and provider ids to rows api.auth already stored."""

    config = load_billing_config()
    provider = constants.STRIPE_PROVIDER_NAME
    lookup_args = {
        "checkout_ref": _checkout_ref_from_event(event, metadata),
        "subscription_id_hmac": provider_ref_hmac_or_none(_subscription_provider_id(event), kind="subscription_id", config=config, provider=provider),
        "payment_intent_id_hmac": provider_ref_hmac_or_none(_payment_intent_provider_id(event), kind="payment_intent_id", config=config, provider=provider),
        "charge_id_hmac": provider_ref_hmac_or_none(_charge_provider_id(event), kind="charge_id", config=config, provider=provider),
        "customer_id_hmac": provider_ref_hmac_or_none(_customer_provider_id(event), kind="customer_id", config=config, provider=provider),
        "price_id_hmac": provider_ref_hmac_or_none(_price_provider_id(event), kind="price_id", config=config, provider=provider),
    }
    if not any(lookup_args.values()):
        return {}
    try:
        row = await _maybe_await(resolve_event_scope(provider=provider, billing_group_id=billing_group_id, **lookup_args))
    except Exception as exc:
        logger.debug("Stripe webhook ref lookup unavailable: %s", type(exc).__name__)
        row = None
    return _plain_mapping(row)


async def _resolve_event_scope(
    event: VerifiedProviderEvent,
    metadata: Mapping[str, Any],
    *,
    billing_group_id: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Return (scope, lookup): who the event belongs to, and the local rows it maps to.

    Metadata identifies the user and project when the object carries it (Checkout copies it
    onto the Subscription and PaymentIntent). Rows matched by the checkout ref or by a
    provider id are authoritative for the user and group; disputes and older objects without
    metadata resolve through them alone.
    """

    metadata_scope = await _resolve_scope_from_metadata(metadata)
    lookup = await _lookup_event_refs(
        event,
        metadata,
        billing_group_id=billing_group_id or _string_field(metadata_scope or {}, "billing_group_id"),
    )
    lookup_user_id = _string_field(lookup, "user_id")
    if not lookup_user_id:
        return metadata_scope, lookup
    if metadata_scope and _string_field(metadata_scope, "user_id") != lookup_user_id:
        metadata_scope = None
    scope = dict(metadata_scope or {})
    for key in ("user_id", "project_id", "billing_group_id"):
        value = _string_field(lookup, key)
        if value:
            scope[key] = value
    return scope, lookup


async def _enqueue_resync_for_event(
    *,
    event: VerifiedProviderEvent,
    classification: BillingClassificationResult,
    reason: str,
    scope: Mapping[str, Any] | None,
    persisted_fact: Mapping[str, Any] | None = None,
) -> bool:
    fact = _plain_mapping(persisted_fact)
    user_id = _string_field(scope or {}, "user_id")
    billing_group_id = _string_field(fact, "billing_group_id") or _string_field(scope or {}, "billing_group_id")
    if not user_id or not billing_group_id:
        # The worker resolves what to fetch from the user and group; without them a job can only fail.
        logger.debug("Stripe webhook resync skipped: event scope unresolved")
        return False
    job_type = _string_field(fact, "job_type")
    subscription_id = _string_field(fact, "subscription_id")
    purchase_id = _string_field(fact, "purchase_id")
    customer_id = _string_field(fact, "customer_id")
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
            user_id=user_id,
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
                user_id=user_id,
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


# Statuses a late `checkout.session.completed` (always `pending`) must not overwrite.
_SUBSCRIPTION_STATUSES_AHEAD_OF_PENDING = frozenset({"incomplete", "trialing", "active", "past_due", "unpaid", "paused"})


async def _persist_classification(
    event: VerifiedProviderEvent,
    classification: BillingClassificationResult,
    *,
    scope: Mapping[str, Any] | None,
    billing_group_id: str | None,
    lookup: Mapping[str, Any] | None = None,
) -> Mapping[str, Any] | None:
    metadata = _event_metadata(event.payload)
    if not scope:
        return None
    lookup = _plain_mapping(lookup)
    user_id = _string_field(scope, "user_id")
    group_id = billing_group_id or _string_field(scope, "billing_group_id")
    if not user_id or not group_id:
        return None
    safe_meta = _plain_mapping(classification.safe_metadata)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        customer_id = await _upsert_customer_from_event(event=event, scope=scope, billing_group_id=group_id) or _string_field(lookup, "customer_id")
        if classification.subscription_status:
            if not customer_id:
                # billing_subscriptions.customer_id is required; the resync worker can recover it.
                return None
            subscription_ref = (
                _string_field(metadata, "api_auth_subscription_ref", "subscription_ref")
                or _string_field(lookup, "subscription_ref")
                or f"bsub-{uuid.uuid4().hex}"
            )
            subscription_id = _string_field(lookup, "subscription_id") or f"bsubrow-{uuid.uuid4().hex[:24]}"
            status = classification.subscription_status
            known_status = _string_field(lookup, "subscription_status")
            if status == "pending" and known_status in _SUBSCRIPTION_STATUSES_AHEAD_OF_PENDING:
                status = known_status
            subscription_evidence = _provider_ref_evidence(_subscription_provider_id(event), kind="subscription_id")
            observed = await _maybe_await(
                observe_subscription(
                    snapshot_id=f"bss-{uuid.uuid4().hex}",
                    history_id=f"beh-{uuid.uuid4().hex}",
                    current_id=f"bec-{uuid.uuid4().hex}",
                    subscription_id=subscription_id,
                    customer_id=customer_id,
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
                    normalized_status=status,
                    plan_code=_string_field(metadata, "consumer_plan_code", "plan_code")
                    or _usable_label(lookup.get("plan_code"))
                    or _usable_label(lookup.get("catalog_plan_code"))
                    or safe_meta.get("plan_code"),
                    tier_code=_string_field(metadata, "consumer_tier_code", "tier_code")
                    or _string_field(lookup, "tier_code", "catalog_tier_code")
                    or safe_meta.get("tier_code"),
                    tier_name=_string_field(metadata, "consumer_tier_name", "tier_name")
                    or _string_field(lookup, "tier_name", "catalog_tier_name")
                    or safe_meta.get("tier_name"),
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
            # Entitlement may have transitioned — drop the cached validate results so the
            # next /auth/validate recomputes the plan promptly (best-effort, no sign-out).
            _invalidate_user_sessions(user_id)
            return {
                "job_type": billing_sync.JOB_TYPE_SUBSCRIPTION,
                "subscription_id": _string_field(_plain_mapping(observed), "subscription_id") or subscription_id,
                "customer_id": customer_id,
                "billing_group_id": group_id,
            }
        if classification.purchase_status:
            project_id = _string_field(scope, "project_id") or _string_field(lookup, "project_id")
            if not project_id:
                return None
            purchase_ref = (
                _string_field(metadata, "api_auth_purchase_ref", "purchase_ref")
                or _string_field(lookup, "purchase_ref")
                or f"bpur-{uuid.uuid4().hex}"
            )
            purchase_id = _string_field(lookup, "purchase_id") or f"bpe-{uuid.uuid4().hex}"
            payment_intent_evidence = _provider_ref_evidence(_payment_intent_provider_id(event), kind="payment_intent_id")
            charge_evidence = _provider_ref_evidence(_charge_provider_id(event), kind="charge_id")
            quantity = _safe_int(lookup.get("quantity"), 0) or None
            recorded = await _maybe_await(
                record_purchase_event(
                    purchase_id=purchase_id,
                    history_id=f"bph-{uuid.uuid4().hex}",
                    user_id=user_id,
                    project_id=project_id,
                    billing_group_id=group_id,
                    customer_id=customer_id,
                    provider=constants.STRIPE_PROVIDER_NAME,
                    purchase_ref=purchase_ref,
                    checkout_ref=_string_field(metadata, "api_auth_checkout_ref", "checkout_ref") or _string_field(lookup, "checkout_ref"),
                    status=classification.purchase_status,
                    credit_product_code=_string_field(metadata, "consumer_credit_product_code", "credit_product_code")
                    or _string_field(lookup, "credit_product_code"),
                    quantity=quantity,
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
                "purchase_id": _string_field(_plain_mapping(recorded), "purchase_id") or purchase_id,
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


def _resolve_group_webhook_secret(billing_group_hash: str) -> tuple[str | None, str | None]:
    """Resolve a billing group's internal id + decrypted webhook secret from its hash.

    Returns (None, None) / (group_id, None) on any miss, including a group that is not
    ``active`` or has its ``webhooks_enabled`` capability off, so the caller responds with a
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
    if _string_field(item, "status") != "active" or not _truthy(item.get("webhooks_enabled")):
        return group_id, None
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


def _event_type_enabled(stripe_config: Any, event_type: str) -> bool:
    """`STRIPE_ALLOWED_WEBHOOK_EVENTS` narrows the handled event types (it can never widen them)."""

    allowed = getattr(stripe_config, "allowed_webhook_events", None)
    if allowed is None:
        return True
    return str(event_type or "").strip() in set(allowed)


async def _process_event(
    request: Request,
    event: VerifiedProviderEvent,
    *,
    billing_group_id: str,
    stripe_config: Any = None,
) -> JSONResponse:
    """Process a verified event within the billing group selected by the URL."""

    metadata = _event_metadata(event.payload)
    scope, lookup = await _resolve_event_scope(event, metadata, billing_group_id=billing_group_id)
    group_id = billing_group_id

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

    if not _event_type_enabled(stripe_config, event.event_type):
        await record_stripe_webhook_activity(
            ActivityType.STRIPE_WEBHOOK_RECEIVED,
            event="webhook_ignored",
            outcome="event_type_disabled",
            request=request,
            status_code=200,
            details={"event_type": event.event_type, "ignored": True, "allowed_event": False},
        )
        return _webhook_json_response(status_code=200, status="ignored_noop")

    try:
        raw_classification = await _maybe_await(classify_stripe_event(event=event.payload))
        classification = _classification_result(raw_classification, event.event_type)
    except Exception as exc:
        logger.debug("Stripe webhook classifier failed safely: %s", type(exc).__name__)
        resync = await _enqueue_resync_for_event(
            event=event,
            classification=BillingClassificationResult(provider="stripe", event_type=event.event_type),
            reason="classifier_failed",
            scope=scope,
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

    persisted_fact = await _persist_classification(
        event,
        classification,
        scope=scope,
        billing_group_id=billing_group_id or _string_field(scope or {}, "billing_group_id"),
        lookup=lookup,
    )
    persisted = persisted_fact is not None
    resync_enqueued = False
    if classification.resync_required or not persisted:
        resync_enqueued = await _enqueue_resync_for_event(
            event=event,
            classification=classification,
            reason=classification.reason or "webhook_source_of_truth_resync",
            scope=scope,
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


@router.post(
    _WEBHOOK_PATH_GROUP,
    status_code=200,
    responses={
        **_WEBHOOK_RESPONSES,
        503: {
            "description": (
                "`{\"success\": false, \"message\": \"Webhook unavailable.\"}`: `BILLING_ENABLED` or "
                "`STRIPE_WEBHOOKS_ENABLED` is off, `BILLING_ID_HMAC_SECRET` is not set, or the group is unknown, "
                "not `active`, has its `webhooks_enabled` capability off, has inactive credentials, or has no usable "
                "webhook secret. Unknown, disabled, and unconfigured groups are indistinguishable."
            )
        },
    },
    openapi_extra=_webhook_openapi_extra(secret_label="the billing group's own stored webhook secret"),
)
async def receive_stripe_webhook_for_group(
    billing_group_hash: Annotated[
        str, Path(description="`group_hash` of the billing group whose Stripe account sends the events.")
    ],
    request: Request,
) -> JSONResponse:
    """Receive a Stripe event from one billing group's Stripe account, verified with that group's webhook secret.

    Register this URL (the group's `readiness.webhook_endpoint_path` in the admin API) as the
    webhook endpoint of the group's Stripe account.

    **Auth:** no user credentials. The `Stripe-Signature` header must be a valid Stripe
    signature over the exact raw body, made with the webhook secret stored for this group
    through the admin credentials endpoint, within the signature tolerance window. Only that
    one stored secret is tried. Repeated failures from one IP are
    rate limited.

    **Request:** the Stripe event JSON exactly as Stripe sent it. The event `api_version` must
    equal the Stripe API version this server is pinned to.

    **Group gate:** the group must be `active`, have its `webhooks_enabled` capability on, and
    have active credentials with a stored webhook secret; otherwise the delivery is answered
    `503` before its signature is checked or anything is recorded, and Stripe retries it later.

    **Processing:** record delivery once, resolve the user within this group, and update
    subscription or purchase facts. Duplicate deliveries are acknowledged without processing.
    Events without a resolvable user write no entitlement facts.
    \f
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

    try:
        event = await _maybe_await(
            build_verified_provider_event(
                raw_body=raw_body,
                signature_header=signature,
                webhook_secret=str(webhook_secret),
                event_hmac_secret=hmac_secret,
                tolerance_seconds=int(getattr(stripe_config, "webhook_signature_tolerance_seconds", 300)),
            )
        )
    except Exception:
        return await _signature_failure_response(request=request, event_type="unknown", status_code=401)

    return await _process_event(request, event, billing_group_id=group_id, stripe_config=stripe_config)


def _assert_webhook_route_hardening() -> None:
    registered_paths = {str(getattr(route, "path", "")) for route in getattr(router, "routes", [])}
    if registered_paths != {_WEBHOOK_PATH_GROUP}:
        raise RuntimeError("Stripe webhook routes are not registered on their isolated router")
    if any(path.startswith("/auth/") for path in registered_paths):
        raise RuntimeError("Stripe webhook router must not expose auth/login routes")
    for path in (_WEBHOOK_PATH_GROUP,):
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
    "receive_stripe_webhook_for_group",
]
