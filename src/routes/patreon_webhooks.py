"""Patreon webhook receiver foundation.

Patreon webhooks are an entitlement fast path only.  This module reads exact raw
request bytes, verifies Patreon's HMAC-MD5 signature before parsing JSON or
mutating durable state, records local idempotency, classifies complete member
payloads, and falls back to source-of-truth resync for ambiguous data.

Trace: SDD change ``patreon-account-link`` tasks ``6.1`` through ``6.6``.
"""

from __future__ import annotations

import inspect
import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.Util import auth_constants as constants
from src.Util.activity_logger import ActivityType
from src.Util.api_audit_logger import APIAuditLogger
from src.Util.db import db_patreon
from src.Util.email.route_support import client_ip, user_agent
from src.Util.error_handler import rate_limit_headers
from src.Util.patreon import classifier as patreon_classifier
from src.Util.patreon import sync as patreon_sync
from src.Util.patreon.config import load_patreon_config
from src.Util.patreon.rate_limit import PatreonRateLimitExceeded, PatreonRateLimiter
from src.Util.patreon.security import (
    compute_patreon_delivery_hash,
    fingerprint_from_digest,
    hash_patreon_identifier,
    raw_body_sha256,
    sanitize_patreon_log_value,
    verify_patreon_webhook_signature,
)


logger = logging.getLogger(__name__)

router = APIRouter(tags=["Patreon Webhooks"])

# Test/integration seams.  They default to the real Phase 3/4 helpers without
# creating Redis/DB/provider side effects at import time.
rate_limiter = None
classify_patreon_member = patreon_classifier.classify_patreon_entitlement
enqueue_member_resync = patreon_sync.enqueue_member_resync
enqueue_resync = enqueue_member_resync

_WEBHOOK_PATH = constants.PATREON_WEBHOOK_ROUTE
_WEBHOOK_METHOD = "POST"
_GENERIC_ACCEPTED_BODY = {"success": True, "status": "accepted"}
_GENERIC_REJECTED_MESSAGE = "Webhook rejected."
_GENERIC_UNAVAILABLE_MESSAGE = "Webhook unavailable."
_GENERIC_RETRY_MESSAGE = "Webhook processing failed."
_SAFE_METADATA_DETAIL_KEYS = frozenset(
    {
        "allowed_event",
        "classification_status",
        "duplicate",
        "event_type",
        "is_complete",
        "reason",
        "resync_enqueued",
        "retry_after_seconds",
        "status_code",
        "tier_map_miss",
        "unknown_tier",
    }
)
_SAFE_CLASSIFICATION_STATUSES = frozenset(constants.PATREON_SAFE_ENTITLEMENT_STATUSES)
_SAFE_EVENT_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:_-.")


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
    legacy_dict = getattr(value, "dict", None)
    if callable(legacy_dict):
        try:
            dumped = legacy_dict()
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


def _bool_field(value: Any, name: str, default: bool = False) -> bool:
    candidate = value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default)
    if isinstance(candidate, bool):
        return candidate
    if candidate is None:
        return default
    return str(candidate).strip().lower() in {"1", "true", "yes", "y", "on"}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_event_type(value: Any) -> str:
    text = str(value or "").strip()[:80]
    if not text or any(char not in _SAFE_EVENT_CHARS for char in text):
        return "unknown"
    return text


def _safe_status_code(value: Any, default: int = 200) -> int:
    try:
        status_code = int(value)
    except (TypeError, ValueError):
        return default
    return status_code if 100 <= status_code <= 599 else default


def _safe_retry_after_seconds(value: Any) -> int | None:
    if value is None:
        return None
    retry_after = _safe_int(value, 0)
    return max(1, retry_after) if retry_after > 0 else None


def _webhook_json_response(
    *,
    status_code: int = 200,
    message: str | None = None,
    retry_after_seconds: int | None = None,
) -> JSONResponse:
    """Return a generic webhook response with no provider-derived fields."""

    safe_status = _safe_status_code(status_code)
    content = dict(_GENERIC_ACCEPTED_BODY) if safe_status < 400 else {
        "success": False,
        "message": message or _GENERIC_REJECTED_MESSAGE,
    }
    headers = None
    retry_after = _safe_retry_after_seconds(retry_after_seconds)
    if retry_after is not None:
        headers = rate_limit_headers(retry_after)
    return JSONResponse(status_code=safe_status, content=content, headers=headers)


def _current_rate_limiter() -> PatreonRateLimiter:
    return rate_limiter or PatreonRateLimiter()


def _webhook_feature_ready(config: Any) -> bool:
    return bool(_bool_field(config, "webhooks_enabled") and _string_field(config, "webhook_secret"))


def _configured_allowed_events(config: Any) -> frozenset[str]:
    configured = (
        getattr(config, "allowed_webhook_events", None)
        or getattr(config, "webhook_event_allowlist", None)
        or getattr(config, "webhook_event_allow_list", None)
        or constants.DEFAULT_PATREON_ALLOWED_WEBHOOK_EVENTS
    )
    if isinstance(configured, str):
        values = [item.strip() for item in configured.split(",")]
    elif isinstance(configured, (list, tuple, set, frozenset)):
        values = [str(item).strip() for item in configured]
    else:
        values = list(constants.DEFAULT_PATREON_ALLOWED_WEBHOOK_EVENTS)
    return frozenset(_safe_event_type(item) for item in values if _safe_event_type(item) != "unknown")


def _event_allowed(config: Any, event_type: str) -> bool:
    checker = getattr(config, "is_webhook_event_allowed", None)
    if callable(checker):
        try:
            return bool(checker(event_type))
        except Exception:
            return False
    return event_type in _configured_allowed_events(config)


def _parse_json_after_verification(raw_body: bytes) -> Mapping[str, Any] | None:
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _payload_member(payload: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    data = payload.get("data")
    if isinstance(data, Mapping) and _string_field(data, "type") == "member":
        return data
    if _string_field(payload, "type") == "member":
        return payload
    return None


def _relationships(member: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(member, Mapping):
        return {}
    relationships = member.get("relationships")
    return relationships if isinstance(relationships, Mapping) else {}


def _relationship_id(member: Mapping[str, Any] | None, name: str) -> str | None:
    relationship = _relationships(member).get(name)
    if not isinstance(relationship, Mapping):
        return None
    data = relationship.get("data")
    if isinstance(data, Mapping):
        return _string_field(data, "id")
    return None


def _relationship_present(member: Mapping[str, Any] | None, name: str) -> bool:
    relationship = _relationships(member).get(name)
    return isinstance(relationship, Mapping) and "data" in relationship


def _payload_for_single_member(payload: Mapping[str, Any], member: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"data": [member]}
    included = payload.get("included")
    if isinstance(included, list):
        result["included"] = included
    return result


def _member_complete_for_webhook(member: Mapping[str, Any] | None) -> bool:
    return bool(
        _string_field(member, "id")
        and _relationship_id(member, "user")
        and _relationship_id(member, "campaign")
        and _relationship_present(member, "currently_entitled_tiers")
    )


def _config_secret(config: Any, *names: str) -> str | None:
    for name in names:
        value = _string_field(config, name)
        if value:
            return value
    return None


def _hash_identifier_or_none(
    *,
    raw_id: str | None,
    kind: str,
    secret: str | bytes | None,
) -> bytes | None:
    if not raw_id or not secret:
        return None
    try:
        return hash_patreon_identifier(raw_id=raw_id, kind=kind, pepper=secret)
    except Exception:
        return None


def _fingerprint_or_none(digest: bytes | None) -> str | None:
    if not digest:
        return None
    try:
        return fingerprint_from_digest(digest)
    except Exception:
        return None


def _campaign_db_id_from_hash(campaign_hash: bytes | None) -> str | None:
    fingerprint = _fingerprint_or_none(campaign_hash)
    return f"pcamp-{fingerprint}" if fingerprint else None


def _membership_id_from_hashes(campaign_hash: bytes | None, member_hash: bytes | None) -> str | None:
    campaign_fp = _fingerprint_or_none(campaign_hash)
    member_fp = _fingerprint_or_none(member_hash)
    if not campaign_fp or not member_fp:
        return None
    return f"pmem-{campaign_fp}-{member_fp}"


def _delivery_hash_material(
    *,
    event_type: str,
    raw_body: bytes,
    raw_member_id: str | None,
    raw_campaign_id: str | None,
    member_hash: bytes | None,
    campaign_hash: bytes | None,
    config: Any,
) -> bytes:
    member_reference = member_hash.hex() if member_hash else ("member-present" if raw_member_id else "member-unknown")
    campaign_reference = campaign_hash.hex() if campaign_hash else ("campaign-present" if raw_campaign_id else "campaign-unknown")
    return compute_patreon_delivery_hash(
        event_type=event_type,
        raw_body=raw_body,
        member_reference=member_reference,
        campaign_id=campaign_reference,
        pepper=_config_secret(config, "webhook_delivery_hash_pepper"),
    )


async def _call_record_delivery(**kwargs: Any) -> Mapping[str, Any] | None:
    for method_name in ("record_webhook_delivery", "record_patreon_webhook_delivery"):
        method = getattr(db_patreon, method_name, None)
        if callable(method):
            return await _maybe_await(method(**kwargs))
    raise RuntimeError("Patreon webhook delivery DB wrapper is not available")


def _delivery_is_duplicate(row: Mapping[str, Any] | None) -> bool:
    item = _plain_mapping(row)
    status = (_string_field(item, "delivery_status", "status", default="") or "").lower()
    return bool(item.get("duplicate") or status in {"duplicate", "replay", "replayed"})


async def _record_delivery_ledger(
    *,
    event_type: str,
    raw_body: bytes,
    member_hash: bytes | None,
    campaign_hash: bytes | None,
    delivery_hash: bytes,
    status: str,
    reason: str,
) -> Mapping[str, Any] | None:
    return await _call_record_delivery(
        delivery_id=f"pwhd-{uuid4().hex}",
        delivery_hash=delivery_hash,
        event_type=event_type,
        member_id_hash=member_hash,
        campaign_id_hash=campaign_hash,
        raw_body_sha256=raw_body_sha256(raw_body),
        signature_valid=True,
        status=status,
        sanitized_metadata={"route": _WEBHOOK_PATH, "reason": reason},
    )


def _safe_webhook_metadata(
    *,
    event: str,
    outcome: str,
    request: Request | None,
    status_code: int,
    reason: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "event": event,
        "outcome": outcome,
        "route": _WEBHOOK_PATH,
        "method": _WEBHOOK_METHOD,
        "status_code": _safe_status_code(status_code),
        "auth_method": APIAuditLogger.infer_auth_method_for_path(_WEBHOOK_PATH) or "webhook",
    }
    if reason:
        metadata["reason"] = sanitize_patreon_log_value(reason)
    if details:
        for key, value in details.items():
            normalized_key = str(key).strip().lower().replace("-", "_")
            if normalized_key not in _SAFE_METADATA_DETAIL_KEYS:
                continue
            if normalized_key == "event_type":
                metadata[normalized_key] = _safe_event_type(value)
            elif normalized_key == "classification_status":
                candidate = str(value or "").strip().lower()
                metadata[normalized_key] = candidate if candidate in _SAFE_CLASSIFICATION_STATUSES else "unknown"
            elif normalized_key == "retry_after_seconds":
                retry_after = _safe_retry_after_seconds(value)
                if retry_after is not None:
                    metadata[normalized_key] = retry_after
            elif normalized_key == "status_code":
                metadata[normalized_key] = _safe_status_code(value)
            elif normalized_key in {"allowed_event", "duplicate", "is_complete", "resync_enqueued", "tier_map_miss", "unknown_tier"}:
                metadata[normalized_key] = bool(value)
            elif normalized_key == "reason":
                metadata[normalized_key] = sanitize_patreon_log_value(value)
    filtered = APIAuditLogger.filter_sensitive_data(metadata)
    return filtered if isinstance(filtered, dict) else metadata


async def capture_patreon_webhook_audit(
    event: str,
    *,
    outcome: str,
    request: Request | None = None,
    status_code: int = 200,
    reason: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> None:
    """Route-local audit seam; middleware owns durable API audit rows later.

    The raw request body is deliberately absent here.  The middleware exclusion
    helper remains the source of truth for raw-body audit capture.
    """

    safe_metadata = _safe_webhook_metadata(
        event=event,
        outcome=outcome,
        request=request,
        status_code=status_code,
        reason=reason,
        details=details,
    )
    tags = APIAuditLogger.generate_tags(_WEBHOOK_PATH, _WEBHOOK_METHOD, _safe_status_code(status_code), user_type=None)
    security_event = APIAuditLogger.is_security_event(_WEBHOOK_PATH, _WEBHOOK_METHOD, _safe_status_code(status_code))
    _ = (safe_metadata, tags, security_event)


async def record_patreon_webhook_activity(
    activity_type: ActivityType,
    *,
    event: str,
    outcome: str,
    request: Request | None,
    status_code: int = 200,
    reason: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> None:
    """Persist redacted Patreon webhook activity without provider internals."""

    try:
        from src.Util import activity_logger as activity_logger_module

        activity_logger_module.assert_patreon_activity_catalog_alignment()
        metadata = _safe_webhook_metadata(
            event=event,
            outcome=outcome,
            request=request,
            status_code=status_code,
            reason=reason,
            details=details,
        )
        activity_details = activity_logger_module.build_patreon_activity_details(event, **metadata)
        await _maybe_await(
            capture_patreon_webhook_audit(
                event,
                outcome=outcome,
                request=request,
                status_code=status_code,
                reason=reason,
                details=details,
            )
        )
        activity_logger_module.log_patreon_activity(
            activity_type,
            activity_details,
            user_id=None,
            ip_address=client_ip(request) if request is not None else None,
            user_agent=APIAuditLogger.sanitize_sensitive_text(user_agent(request)) if request is not None else None,
        )
    except Exception as exc:
        logger.debug("Patreon webhook activity logging failed: %s", type(exc).__name__)


async def _signature_failure_response(
    *,
    request: Request,
    event_type: str,
    status_code: int = 401,
    reason: str = "signature_invalid",
) -> JSONResponse:
    retry_after = None
    try:
        await _maybe_await(
            _current_rate_limiter().check_webhook_signature_failure(
                ip_address=client_ip(request),
                event_type=event_type,
                signature_digest=None,
            )
        )
    except PatreonRateLimitExceeded as exc:
        if _safe_int(getattr(exc, "limit", None), 0) > 0:
            status_code = 429
            retry_after = _safe_retry_after_seconds(getattr(exc, "retry_after", None)) or 1
            reason = "signature_failure_rate_limited"

    await record_patreon_webhook_activity(
        ActivityType.PATREON_WEBHOOK_REJECTED,
        event="webhook_rejected",
        outcome=reason,
        request=request,
        status_code=status_code,
        reason=reason,
        details={"event_type": event_type, "retry_after_seconds": retry_after},
    )
    return _webhook_json_response(
        status_code=status_code,
        message=_GENERIC_REJECTED_MESSAGE,
        retry_after_seconds=retry_after,
    )


def _classification_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, patreon_classifier.PatreonClassificationResult):
        return asdict(value)
    return _plain_mapping(value)


def _classification_result_from(value: Any, *, source: str, is_complete: bool) -> patreon_classifier.PatreonClassificationResult:
    if isinstance(value, patreon_classifier.PatreonClassificationResult):
        return value
    item = _classification_mapping(value)
    reasons_value = item.get("reasons")
    if isinstance(reasons_value, str):
        reasons = (reasons_value,)
    elif isinstance(reasons_value, Sequence) and not isinstance(reasons_value, (str, bytes, bytearray)):
        reasons = tuple(str(reason) for reason in reasons_value if str(reason or "").strip())
    else:
        reason = _string_field(item, "reason")
        reasons = (reason,) if reason else ()
    tier_map_miss = bool(item.get("tier_map_miss") or item.get("unknown_tier") or "tier_map_miss" in reasons)
    status = str(item.get("status") or constants.PATREON_ENTITLEMENT_STATUS_PENDING).strip().lower()
    if status not in constants.PATREON_SAFE_ENTITLEMENT_STATUSES:
        status = constants.PATREON_ENTITLEMENT_STATUS_PENDING
    return patreon_classifier.PatreonClassificationResult(
        external_source=item.get("external_source") or constants.PATREON_PROVIDER_NAME,
        status=status,
        plan_code=str(item.get("plan_code") or "free"),
        tier_code=item.get("tier_code"),
        tier_name=item.get("tier_name"),
        link_status=str(item.get("link_status") or constants.PATREON_LINK_STATUS_LINKED),
        next_renewal_at=item.get("next_renewal_at"),
        grace_period_until=item.get("grace_period_until"),
        last_synced_at=item.get("last_synced_at"),
        stale_after=item.get("stale_after"),
        classification_version=_safe_int(item.get("classification_version"), constants.PATREON_DEFAULT_CONTRACT_VERSION),
        source=source,
        is_complete=bool(item.get("is_complete", is_complete)),
        resync_required=bool(item.get("resync_required") or tier_map_miss),
        tier_map_miss=tier_map_miss,
        unknown_tier=bool(item.get("unknown_tier") or tier_map_miss),
        downgrade_applied=bool(item.get("downgrade_applied")),
        reasons=reasons,
    )


async def _classify_payload(
    *,
    payload: Mapping[str, Any],
    config: Any,
    is_complete: bool,
    current_snapshot: Mapping[str, Any] | None,
) -> patreon_classifier.PatreonClassificationResult:
    kwargs = {
        "patreon_payload": payload,
        "tier_map": patreon_sync.tier_map_from_config(config),
        "now": datetime.now(timezone.utc).replace(microsecond=0),
        "source": constants.PATREON_SYNC_SOURCE_WEBHOOK,
        "is_complete": is_complete,
        "current_snapshot": current_snapshot or {},
        "stale_after_seconds": _safe_int(
            getattr(config, "sync_stale_after_seconds", None),
            constants.DEFAULT_PATREON_SYNC_STALE_AFTER_SECONDS,
        ),
    }
    result = await _maybe_await(classify_patreon_member(**kwargs))
    return _classification_result_from(
        result,
        source=constants.PATREON_SYNC_SOURCE_WEBHOOK,
        is_complete=is_complete,
    )


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


def _member_attribute(member: Mapping[str, Any] | None, name: str) -> Any:
    if not isinstance(member, Mapping):
        return None
    attrs = member.get("attributes")
    if isinstance(attrs, Mapping) and name in attrs:
        return attrs.get(name)
    return member.get(name)


def _member_observed_at(member: Mapping[str, Any] | None) -> datetime | None:
    for field_name in ("last_charge_date", "next_charge_date", "updated_at", "created_at"):
        observed = _parse_datetime(_member_attribute(member, field_name))
        if observed is not None:
            return observed
    return None


def _snapshot_has_paid_plan(snapshot: Mapping[str, Any] | None) -> bool:
    row = _plain_mapping(snapshot)
    plan_code = str(row.get("plan_code") or "free").strip().lower()
    status = str(row.get("status") or row.get("entitlement_status") or "").strip().lower()
    return bool(plan_code and plan_code != "free" and status in {"", constants.PATREON_ENTITLEMENT_STATUS_ACTIVE, constants.PATREON_ENTITLEMENT_STATUS_STALE})


def _is_out_of_order(member: Mapping[str, Any] | None, current_snapshot: Mapping[str, Any] | None) -> bool:
    observed_at = _member_observed_at(member)
    last_synced_at = _parse_datetime(_plain_mapping(current_snapshot).get("last_synced_at"))
    return bool(observed_at and last_synced_at and observed_at < last_synced_at)


def _should_resync_instead_of_commit(
    *,
    event_type: str,
    member: Mapping[str, Any] | None,
    classification: patreon_classifier.PatreonClassificationResult,
    is_complete: bool,
    current_snapshot: Mapping[str, Any] | None,
) -> tuple[bool, str]:
    if not is_complete or not classification.is_complete:
        return True, "partial_payload_resync_required"
    if event_type.endswith(":delete"):
        return True, "delete_event_requires_source_of_truth_resync"
    if classification.tier_map_miss or classification.unknown_tier:
        return True, "tier_map_miss_resync_required"
    if classification.resync_required:
        return True, "classifier_requested_resync"
    if _is_out_of_order(member, current_snapshot):
        return True, "out_of_order_resync_required"
    if classification.downgrade_applied and _snapshot_has_paid_plan(current_snapshot):
        return True, "destructive_downgrade_requires_source_of_truth"
    if classification.status in {constants.PATREON_ENTITLEMENT_STATUS_FREE, constants.PATREON_ENTITLEMENT_STATUS_FORMER, constants.PATREON_ENTITLEMENT_STATUS_REVOKED} and _snapshot_has_paid_plan(current_snapshot):
        return True, "non_paid_webhook_requires_source_of_truth"
    return False, "complete_verified_payload"


async def _resolve_link_by_provider_hash(provider_sub_hash: bytes) -> Mapping[str, Any] | None:
    for method_name in ("resolve_patreon_link_by_provider_hash", "get_patreon_link_by_provider_sub_hash"):
        method = getattr(db_patreon, method_name, None)
        if callable(method):
            return await _maybe_await(method(provider_sub_hash=provider_sub_hash))
    raise RuntimeError("Patreon provider-hash link resolver DB wrapper is not available")


async def _current_snapshot_for_user(user_hash: str | None) -> Mapping[str, Any] | None:
    if not user_hash:
        return None
    try:
        row = await _maybe_await(db_patreon.get_entitlement_by_user_hash(user_hash))
    except Exception:
        return None
    return _plain_mapping(row) or None


async def _enqueue_member_source_of_truth_resync(
    *,
    raw_member_id: str | None,
    campaign_db_id: str | None,
    member_hash: bytes | None,
    user_id: str | None,
    config: Any,
    reason: str,
) -> bool:
    if not raw_member_id and member_hash is None and not user_id:
        return False
    try:
        await _maybe_await(
            enqueue_member_resync(
                campaign_id=campaign_db_id,
                user_id=user_id,
                member_id_hash=member_hash,
                raw_member_id=raw_member_id if member_hash is None else None,
                config=config,
                id_hmac_secret=_config_secret(config, "id_hmac_secret", "provider_sub_pepper"),
                job_type=patreon_sync.JOB_TYPE_WEBHOOK_RESYNC,
                source=constants.PATREON_SYNC_SOURCE_WEBHOOK,
                sanitized_metadata={"reason": reason, "route": _WEBHOOK_PATH},
                db_module=db_patreon,
            )
        )
        return True
    except Exception as exc:
        logger.debug("Patreon webhook resync enqueue failed: %s", type(exc).__name__)
        return False


async def _persist_classification(
    *,
    payload: Mapping[str, Any],
    member: Mapping[str, Any],
    classification: patreon_classifier.PatreonClassificationResult,
    link_row: Mapping[str, Any],
    campaign_db_id: str,
    membership_id: str,
    id_secret: str,
    config: Any,
) -> None:
    user_id = _string_field(link_row, "user_id", "id")
    external_account_id = _string_field(link_row, "external_account_id")
    if not user_id or not external_account_id:
        raise RuntimeError("Patreon webhook link resolver returned incomplete server-side link context")
    persistence = patreon_sync.PatreonMemberPersistenceContext(
        user_id=user_id,
        external_account_id=external_account_id,
        membership_id=membership_id,
        campaign_db_id=campaign_db_id,
        id_hmac_secret=id_secret,
        safe_metadata={"source": "patreon_webhook", "reason": "verified_webhook"},
    )
    patreon_sync.persist_member_classification(
        patreon_payload=payload,
        classification_result=classification,
        persistence=persistence,
        config=config,
        db_module=db_patreon,
        now=datetime.now(timezone.utc).replace(microsecond=0),
        source=constants.PATREON_SYNC_SOURCE_WEBHOOK,
    )


async def _process_verified_member_payload(
    *,
    request: Request,
    event_type: str,
    payload: Mapping[str, Any],
    member: Mapping[str, Any],
    config: Any,
    raw_member_id: str | None,
    raw_campaign_id: str | None,
    raw_user_id: str | None,
    member_hash: bytes | None,
    campaign_hash: bytes | None,
) -> None:
    is_complete = _member_complete_for_webhook(member)
    provider_secret = _config_secret(config, "provider_sub_pepper")
    id_secret = _config_secret(config, "id_hmac_secret", "provider_sub_pepper")
    provider_sub_hash = _hash_identifier_or_none(raw_id=raw_user_id, kind="user", secret=provider_secret)
    campaign_db_id = _campaign_db_id_from_hash(campaign_hash)
    membership_id = _membership_id_from_hashes(campaign_hash, member_hash)

    link_row = await _resolve_link_by_provider_hash(provider_sub_hash) if provider_sub_hash else None
    current_snapshot = await _current_snapshot_for_user(_string_field(link_row, "user_hash")) if link_row else None
    member_payload = _payload_for_single_member(payload, member)

    classification = await _classify_payload(
        payload=member_payload,
        config=config,
        is_complete=is_complete,
        current_snapshot=current_snapshot,
    )
    should_resync, reason = _should_resync_instead_of_commit(
        event_type=event_type,
        member=member,
        classification=classification,
        is_complete=is_complete,
        current_snapshot=current_snapshot,
    )

    if not link_row or not campaign_db_id or not membership_id or not id_secret:
        reason = "unknown_member_resync_required" if not link_row else "incomplete_server_context_resync_required"
        resync_enqueued = await _enqueue_member_source_of_truth_resync(
            raw_member_id=raw_member_id,
            campaign_db_id=campaign_db_id,
            member_hash=member_hash,
            user_id=_string_field(link_row, "user_id", "id") if link_row else None,
            config=config,
            reason=reason,
        )
        await record_patreon_webhook_activity(
            ActivityType.PATREON_WEBHOOK_RECEIVED,
            event="webhook_received",
            outcome="resync_enqueued" if resync_enqueued else "resync_unavailable",
            request=request,
            status_code=200,
            reason=reason,
            details={
                "event_type": event_type,
                "is_complete": is_complete,
                "classification_status": classification.status,
                "resync_enqueued": resync_enqueued,
                "tier_map_miss": classification.tier_map_miss,
                "unknown_tier": classification.unknown_tier,
            },
        )
        return

    if should_resync:
        resync_enqueued = await _enqueue_member_source_of_truth_resync(
            raw_member_id=raw_member_id,
            campaign_db_id=campaign_db_id,
            member_hash=member_hash,
            user_id=_string_field(link_row, "user_id", "id"),
            config=config,
            reason=reason,
        )
        activity_type = ActivityType.PATREON_TIER_MAP_MISS if classification.tier_map_miss else ActivityType.PATREON_WEBHOOK_RECEIVED
        await record_patreon_webhook_activity(
            activity_type,
            event="webhook_resync_required",
            outcome="resync_enqueued" if resync_enqueued else "resync_unavailable",
            request=request,
            status_code=200,
            reason=reason,
            details={
                "event_type": event_type,
                "is_complete": is_complete,
                "classification_status": classification.status,
                "resync_enqueued": resync_enqueued,
                "tier_map_miss": classification.tier_map_miss,
                "unknown_tier": classification.unknown_tier,
            },
        )
        return

    await _maybe_await(
        _persist_classification(
            payload=member_payload,
            member=member,
            classification=classification,
            link_row=link_row,
            campaign_db_id=campaign_db_id,
            membership_id=membership_id,
            id_secret=id_secret,
            config=config,
        )
    )
    await record_patreon_webhook_activity(
        ActivityType.PATREON_ENTITLEMENT_CHANGED,
        event="webhook_processed",
        outcome="snapshot_upserted",
        request=request,
        status_code=200,
        reason=reason,
        details={
            "event_type": event_type,
            "is_complete": is_complete,
            "classification_status": classification.status,
            "tier_map_miss": classification.tier_map_miss,
            "unknown_tier": classification.unknown_tier,
        },
    )


@router.post(_WEBHOOK_PATH, status_code=200)
async def receive_patreon_webhook(request: Request) -> JSONResponse:
    """Receive a Patreon webhook without requiring or creating local sessions."""

    raw_body = await request.body()
    event_type = _safe_event_type(request.headers.get(constants.PATREON_WEBHOOK_EVENT_HEADER))
    signature = request.headers.get(constants.PATREON_WEBHOOK_SIGNATURE_HEADER)
    config = load_patreon_config()

    if not _webhook_feature_ready(config):
        return _webhook_json_response(status_code=503, message=_GENERIC_UNAVAILABLE_MESSAGE)

    if not verify_patreon_webhook_signature(
        raw_body=raw_body,
        signature=signature,
        secret=str(_string_field(config, "webhook_secret")),
    ):
        return await _signature_failure_response(request=request, event_type=event_type)

    if not _event_allowed(config, event_type):
        # Signature is valid, so recording an ignored delivery is safe.  Do not
        # parse or trust unsupported payloads for entitlement mutation.
        delivery_hash = compute_patreon_delivery_hash(
            event_type=event_type,
            raw_body=raw_body,
            member_reference="unsupported",
            pepper=_config_secret(config, "webhook_delivery_hash_pepper"),
        )
        try:
            await _record_delivery_ledger(
                event_type=event_type,
                raw_body=raw_body,
                member_hash=None,
                campaign_hash=None,
                delivery_hash=delivery_hash,
                status="ignored",
                reason="unsupported_event",
            )
        except Exception as exc:
            logger.debug("Patreon unsupported webhook delivery ledger write failed: %s", type(exc).__name__)
        await record_patreon_webhook_activity(
            ActivityType.PATREON_WEBHOOK_RECEIVED,
            event="webhook_ignored",
            outcome="unsupported_event",
            request=request,
            status_code=200,
            reason="unsupported_event",
            details={"event_type": event_type, "allowed_event": False},
        )
        return _webhook_json_response(status_code=200)

    payload = _parse_json_after_verification(raw_body)
    member = _payload_member(payload)
    raw_member_id = _string_field(member, "id")
    raw_campaign_id = _relationship_id(member, "campaign")
    raw_user_id = _relationship_id(member, "user")

    id_secret = _config_secret(config, "id_hmac_secret", "provider_sub_pepper")
    member_hash = _hash_identifier_or_none(raw_id=raw_member_id, kind="member", secret=id_secret)
    campaign_hash = _hash_identifier_or_none(raw_id=raw_campaign_id, kind="campaign", secret=id_secret)
    delivery_hash = _delivery_hash_material(
        event_type=event_type,
        raw_body=raw_body,
        raw_member_id=raw_member_id,
        raw_campaign_id=raw_campaign_id,
        member_hash=member_hash,
        campaign_hash=campaign_hash,
        config=config,
    )

    try:
        delivery_row = await _record_delivery_ledger(
            event_type=event_type,
            raw_body=raw_body,
            member_hash=member_hash,
            campaign_hash=campaign_hash,
            delivery_hash=delivery_hash,
            status="received",
            reason="verified",
        )
    except Exception:
        logger.warning("Patreon webhook delivery could not be recorded; returning retryable response")
        return _webhook_json_response(status_code=500, message=_GENERIC_RETRY_MESSAGE)

    if _delivery_is_duplicate(delivery_row):
        return _webhook_json_response(status_code=200)

    if payload is None or member is None:
        await _enqueue_member_source_of_truth_resync(
            raw_member_id=raw_member_id,
            campaign_db_id=_campaign_db_id_from_hash(campaign_hash),
            member_hash=member_hash,
            user_id=None,
            config=config,
            reason="invalid_or_missing_member_payload",
        )
        await record_patreon_webhook_activity(
            ActivityType.PATREON_WEBHOOK_RECEIVED,
            event="webhook_resync_required",
            outcome="invalid_payload",
            request=request,
            status_code=200,
            reason="invalid_or_missing_member_payload",
            details={"event_type": event_type, "is_complete": False, "resync_enqueued": True},
        )
        return _webhook_json_response(status_code=200)

    try:
        await _process_verified_member_payload(
            request=request,
            event_type=event_type,
            payload=payload,
            member=member,
            config=config,
            raw_member_id=raw_member_id,
            raw_campaign_id=raw_campaign_id,
            raw_user_id=raw_user_id,
            member_hash=member_hash,
            campaign_hash=campaign_hash,
        )
    except Exception:
        logger.warning("Patreon webhook processing failed after verification; returning retryable response")
        resync_enqueued = await _enqueue_member_source_of_truth_resync(
            raw_member_id=raw_member_id,
            campaign_db_id=_campaign_db_id_from_hash(campaign_hash),
            member_hash=member_hash,
            user_id=None,
            config=config,
            reason="processing_failed_after_delivery_ledger",
        )
        await record_patreon_webhook_activity(
            ActivityType.PATREON_WEBHOOK_RECEIVED,
            event="webhook_processing_failed",
            outcome="resync_enqueued" if resync_enqueued else "resync_unavailable",
            request=request,
            status_code=500,
            reason="processing_failed_after_delivery_ledger",
            details={"event_type": event_type, "resync_enqueued": resync_enqueued},
        )
        return _webhook_json_response(status_code=500, message=_GENERIC_RETRY_MESSAGE)

    return _webhook_json_response(status_code=200)


def _assert_webhook_route_hardening() -> None:
    registered_paths = {str(getattr(route, "path", "")) for route in getattr(router, "routes", [])}
    if _WEBHOOK_PATH not in registered_paths:
        raise RuntimeError("Patreon webhook route is not registered on its isolated router")
    if any(path.startswith("/auth/patreon") for path in registered_paths):
        raise RuntimeError("Patreon webhook router must not expose auth/login routes")
    if not APIAuditLogger.is_raw_body_audit_excluded(_WEBHOOK_PATH):
        raise RuntimeError("Patreon webhook raw body must be excluded from API audit capture")
    exclusion_note = APIAuditLogger.raw_body_audit_exclusion_note(_WEBHOOK_PATH)
    if not isinstance(exclusion_note, Mapping) or "raw_body" in exclusion_note:
        raise RuntimeError("Patreon webhook audit exclusion note must not contain raw body bytes")


_assert_webhook_route_hardening()


__all__ = [
    "router",
    "capture_patreon_webhook_audit",
    "record_patreon_webhook_activity",
    "receive_patreon_webhook",
]
