"""Dedicated internal Patreon entitlement S2S routes.

Patreon is entitlement/link proof only.  This router is a server-to-server
boundary for Magic Worlds projection and never accepts browser cookies as
authority, never loads local user-session context, and never issues local auth
credentials.

Trace: SDD change ``patreon-account-link`` tasks ``7.1`` through ``7.5``.
"""

from __future__ import annotations

import inspect
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from src.Util import auth_constants as constants
from src.Util.Models import (
    PATREON_FORBIDDEN_RESPONSE_FIELD_NAMES,
    PATREON_SAFE_ENTITLEMENT_FIELD_NAMES,
    PatreonEntitlementS2SResponse,
    PatreonResyncAcceptedResponse,
    PatreonResyncRequest,
    PatreonSafeEntitlement,
    ValidateSessionResponse,
    UserLogin,
    EnhancedUserLogin,
    assert_patreon_response_model_allow_lists,
)
from src.Util.activity_logger import ActivityType
from src.Util.api_audit_logger import APIAuditLogger
from src.Util.db import db_patreon
from src.Util.email.route_support import client_ip, user_agent
from src.Util.error_handler import rate_limit_headers
from src.Util.patreon import sync as patreon_sync
from src.Util.patreon.config import load_patreon_config
from src.Util.patreon.rate_limit import PatreonRateLimitExceeded, PatreonRateLimiter
from src.Util.patreon.security import sanitize_patreon_log_value, verify_s2s_bearer_token


logger = logging.getLogger(__name__)

router = APIRouter(tags=["Patreon Internal"])

# Test/integration seams.  Defaults point at the real Phase 3/4 helpers without
# creating DB/Redis side effects at import time.
rate_limiter = None
get_entitlement_by_user_hash = db_patreon.get_entitlement_by_user_hash
get_patreon_entitlement_by_user_hash = db_patreon.get_patreon_entitlement_by_user_hash
enqueue_member_resync = patreon_sync.enqueue_member_resync

_GENERIC_DENIAL_MESSAGE = "Request could not be processed."
_GENERIC_UNAUTHORIZED_MESSAGE = "Unauthorized."
_GENERIC_RESYNC_ACCEPTED_MESSAGE = "Request accepted."
_INTERNAL_ENTITLEMENTS_PATH = constants.PATREON_INTERNAL_ENTITLEMENTS_ROUTE_TEMPLATE
_INTERNAL_RESYNC_PATH = constants.PATREON_INTERNAL_ENTITLEMENTS_RESYNC_ROUTE_TEMPLATE
_ALLOWED_INTERNAL_ROUTES = frozenset({_INTERNAL_ENTITLEMENTS_PATH, _INTERNAL_RESYNC_PATH})
_FORBIDDEN_AUTH_VALIDATE_FIELD_FRAGMENTS = frozenset(
    {
        "patreon",
        "entitlement",
        "plan_code",
        "tier_code",
        "subscription_status",
        "link_status",
        "external_source",
    }
)
_FORBIDDEN_AUTH_CONTEXT_GLOBALS = frozenset(
    {
        "HTTPBearerOrCookie",
        "validate_access_session",
        "require_recent_reauthentication",
    }
)
_FORBIDDEN_RESPONSE_KEYS_NORMALIZED = frozenset(
    str(field).lower().replace("-", "_") for field in PATREON_FORBIDDEN_RESPONSE_FIELD_NAMES
)
_SAFE_INTERNAL_METADATA_KEYS = frozenset(
    {
        "accepted",
        "auth_method",
        "contract_version",
        "retry_after_seconds",
        "resync_status",
        "status_code",
    }
)


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


def _safe_int(value: Any, default: int) -> int:
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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _extract_bearer_token(request: Request) -> str | None:
    authorization = request.headers.get(constants.PATREON_AUTHORIZATION_HEADER)
    if not authorization:
        return None
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def _s2s_feature_ready(config: Any) -> bool:
    return bool(_bool_field(config, "s2s_entitlement_enabled") and _string_field(config, "s2s_bearer_token"))


def _authorized_internal_bearer(request: Request, config: Any) -> bool:
    """Validate the dedicated S2S bearer without touching user-session auth."""

    presented = _extract_bearer_token(request)
    expected = _string_field(config, "s2s_bearer_token")
    token_matches = verify_s2s_bearer_token(presented=presented, expected=expected)
    return bool(_s2s_feature_ready(config) and token_matches)


def _response_path(request: Request | None, fallback: str = _INTERNAL_ENTITLEMENTS_PATH) -> str:
    if request is None:
        return fallback
    try:
        return str(request.url.path or fallback)
    except Exception:
        return fallback


def _response_method(request: Request | None, default: str = "GET") -> str:
    if request is None:
        return default
    try:
        method = str(request.method or "").upper()
    except Exception:
        method = ""
    return method or default


def _iter_mapping_keys(value: Any):
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _iter_mapping_keys(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_mapping_keys(item)


def _assert_safe_response_content(content: Mapping[str, Any]) -> None:
    normalized_keys = {str(key).lower().replace("-", "_") for key in _iter_mapping_keys(content)}
    forbidden = sorted(normalized_keys & _FORBIDDEN_RESPONSE_KEYS_NORMALIZED)
    if forbidden:
        raise RuntimeError(f"Unsafe Patreon internal response fields would be serialized: {forbidden}")


def _normalize_utc_json_offsets(value: Any) -> Any:
    """Keep S2S fixture-compatible UTC offsets after Pydantic JSON dumping."""

    if isinstance(value, str) and value.endswith("Z") and "T" in value:
        return f"{value[:-1]}+00:00"
    if isinstance(value, dict):
        return {key: _normalize_utc_json_offsets(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_utc_json_offsets(item) for item in value]
    return value


def _safe_json_response_from_model(
    response_model: Any,
    *,
    status_code: int,
    retry_after_seconds: int | None = None,
) -> JSONResponse:
    model_dump_safe = getattr(response_model, "model_dump_safe", None)
    if not callable(model_dump_safe):
        raise RuntimeError("Patreon internal route attempted to serialize a non-safe response model")
    content = model_dump_safe(mode="json")
    if not isinstance(content, Mapping):
        raise RuntimeError("Patreon internal safe response serialization did not produce a mapping")
    content = _normalize_utc_json_offsets(dict(content))
    _assert_safe_response_content(content)
    retry_after = _safe_retry_after_seconds(retry_after_seconds)
    return JSONResponse(
        status_code=_safe_status_code(status_code),
        content=content,
        headers=rate_limit_headers(retry_after) if retry_after is not None else None,
    )


def _generic_error_response(
    *,
    status_code: int,
    message: str = _GENERIC_DENIAL_MESSAGE,
    retry_after_seconds: int | None = None,
) -> JSONResponse:
    retry_after = _safe_retry_after_seconds(retry_after_seconds)
    return JSONResponse(
        status_code=_safe_status_code(status_code, 403),
        content={"success": False, "message": message},
        headers=rate_limit_headers(retry_after) if retry_after is not None else None,
    )


def _safe_internal_metadata(
    *,
    event: str,
    outcome: str,
    request: Request | None,
    status_code: int,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "event": event,
        "outcome": sanitize_patreon_log_value(outcome) or "unknown",
        "route": _response_path(request),
        "method": _response_method(request),
        "status_code": _safe_status_code(status_code),
        "auth_method": "api_key",
    }
    if details:
        for key, value in details.items():
            normalized_key = str(key).strip().lower().replace("-", "_")
            if normalized_key not in _SAFE_INTERNAL_METADATA_KEYS:
                continue
            if normalized_key in {"accepted"}:
                metadata[normalized_key] = bool(value)
            elif normalized_key in {"retry_after_seconds", "contract_version", "status_code"}:
                safe_value = _safe_retry_after_seconds(value) if normalized_key == "retry_after_seconds" else _safe_int(value, 0)
                if safe_value:
                    metadata[normalized_key] = safe_value
            elif normalized_key == "resync_status":
                candidate = str(value or "").strip().lower()
                if candidate in {"accepted", "queued", "disabled", "rate_limited", "degraded"}:
                    metadata[normalized_key] = candidate
            elif normalized_key == "auth_method":
                metadata[normalized_key] = "api_key"
    filtered = APIAuditLogger.filter_sensitive_data(metadata)
    return filtered if isinstance(filtered, dict) else metadata


async def capture_patreon_internal_audit(
    event: str,
    *,
    outcome: str,
    request: Request | None = None,
    status_code: int = 200,
    details: Mapping[str, Any] | None = None,
) -> None:
    """Route-local audit seam; API audit middleware owns durable rows later."""

    safe_metadata = _safe_internal_metadata(
        event=event,
        outcome=outcome,
        request=request,
        status_code=status_code,
        details=details,
    )
    tags = APIAuditLogger.generate_tags(
        _response_path(request),
        _response_method(request),
        _safe_status_code(status_code),
        user_type=None,
    )
    security_event = APIAuditLogger.is_security_event(
        _response_path(request),
        _response_method(request),
        _safe_status_code(status_code),
        user_type=None,
    )
    _ = (safe_metadata, tags, security_event)


async def record_patreon_internal_activity(
    activity_type: ActivityType,
    *,
    event: str,
    outcome: str,
    request: Request | None,
    status_code: int = 202,
    details: Mapping[str, Any] | None = None,
) -> None:
    """Persist redacted internal Patreon activity without provider internals."""

    try:
        from src.Util import activity_logger as activity_logger_module

        activity_logger_module.assert_patreon_activity_catalog_alignment()
        metadata = _safe_internal_metadata(
            event=event,
            outcome=outcome,
            request=request,
            status_code=status_code,
            details=details,
        )
        activity_details = activity_logger_module.build_patreon_activity_details(event, **metadata)
        await _maybe_await(
            capture_patreon_internal_audit(
                event,
                outcome=outcome,
                request=request,
                status_code=status_code,
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
        logger.debug("Patreon internal activity logging failed: %s", type(exc).__name__)


def _current_rate_limiter() -> PatreonRateLimiter:
    return rate_limiter or PatreonRateLimiter()


def _retry_after_from_rate_limit(exc: PatreonRateLimitExceeded) -> int:
    return _safe_retry_after_seconds(getattr(exc, "retry_after", None)) or 1


async def _check_s2s_rate_limit(*, request: Request, user_hash: str) -> JSONResponse | None:
    try:
        await _maybe_await(
            _current_rate_limiter().check_s2s(
                user_hash=user_hash,
                client_id=request.headers.get("X-Internal-Client") or request.headers.get(constants.PATREON_USER_AGENT_HEADER),
                ip_address=client_ip(request),
            )
        )
        return None
    except PatreonRateLimitExceeded as exc:
        retry_after = _retry_after_from_rate_limit(exc)
        return _generic_error_response(
            status_code=429,
            retry_after_seconds=retry_after,
        )


async def _check_sync_enqueue_rate_limit(*, user_hash: str) -> int | None:
    try:
        await _maybe_await(
            _current_rate_limiter().check_sync_enqueue(
                kind=patreon_sync.JOB_TYPE_USER_MEMBER,
                user_id=user_hash,
                source="manual",
            )
        )
        return None
    except PatreonRateLimitExceeded as exc:
        return _retry_after_from_rate_limit(exc)


def _safe_entitlement_from_payload(payload: Any) -> PatreonSafeEntitlement:
    if isinstance(payload, PatreonSafeEntitlement):
        return payload
    row = _plain_mapping(payload)
    safe_payload = {key: row[key] for key in PATREON_SAFE_ENTITLEMENT_FIELD_NAMES if key in row}
    return PatreonSafeEntitlement(**safe_payload)


def _s2s_response_from_row(row: Any, *, user_hash: str) -> PatreonEntitlementS2SResponse | None:
    if row is None:
        return None
    if isinstance(row, PatreonEntitlementS2SResponse):
        item = row.model_dump()
    else:
        item = _plain_mapping(row)
    if not item:
        return None

    if "entitlement" in item:
        entitlement = _safe_entitlement_from_payload(item.get("entitlement"))
        return PatreonEntitlementS2SResponse(
            success=True,
            message=item.get("message") if isinstance(item.get("message"), str) else None,
            user_hash=_string_field(item, "user_hash") or user_hash,
            entitlement=entitlement,
            contract_version=_safe_int(item.get("contract_version"), entitlement.classification_version),
        )

    return patreon_sync.db_entitlement_row_to_s2s_response(
        item,
        user_hash=user_hash,
        now=_utc_now(),
    )


def _free_s2s_response(*, user_hash: str) -> PatreonEntitlementS2SResponse:
    return PatreonEntitlementS2SResponse(
        success=True,
        message="Patreon entitlement retrieved.",
        user_hash=user_hash,
        entitlement=PatreonSafeEntitlement(
            external_source=None,
            status=constants.PATREON_ENTITLEMENT_STATUS_FREE,
            plan_code="free",
            tier_code=None,
            tier_name=None,
            link_status=constants.PATREON_LINK_STATUS_NONE,
            next_renewal_at=None,
            grace_period_until=None,
            last_synced_at=None,
            stale_after=None,
            classification_version=constants.PATREON_DEFAULT_CONTRACT_VERSION,
        ),
        contract_version=constants.PATREON_DEFAULT_CONTRACT_VERSION,
    )


async def _read_current_entitlement_row(user_hash: str) -> Any:
    return await _maybe_await(get_entitlement_by_user_hash(user_hash))


def _resync_response(
    *,
    accepted: bool,
    status: str,
    user_hash: str | None = None,
    status_code: int = 202,
    retry_after_seconds: int | None = None,
    not_before: Any = None,
    correlation_id: str | None = None,
    message: str | None = None,
) -> JSONResponse:
    response = PatreonResyncAcceptedResponse(
        success=True,
        accepted=accepted,
        status=status,  # type: ignore[arg-type]
        user_hash=user_hash if accepted else None,
        retry_after_seconds=_safe_retry_after_seconds(retry_after_seconds),
        not_before=not_before,
        correlation_id=correlation_id,
        contract_version=constants.PATREON_DEFAULT_CONTRACT_VERSION,
        message=message or (_GENERIC_RESYNC_ACCEPTED_MESSAGE if accepted else _GENERIC_DENIAL_MESSAGE),
    )
    return _safe_json_response_from_model(
        response,
        status_code=status_code,
        retry_after_seconds=retry_after_seconds,
    )


def _sync_disabled(config: Any) -> bool:
    return not _bool_field(config, "sync_enabled")


def _job_id() -> str:
    return f"psj-{uuid.uuid4().hex}"


async def _enqueue_user_hash_resync(
    *,
    user_hash: str,
    row: Any,
    resync_request: PatreonResyncRequest | None,
) -> PatreonResyncAcceptedResponse:
    row_map = _plain_mapping(row)
    local_user_id = _string_field(row_map, "user_id", "id")
    job_id = _job_id()
    reason = _string_field(resync_request, "reason", default="internal_manual_resync") if resync_request else "internal_manual_resync"
    metadata = {"source": "internal_s2s", "reason": reason, "user_hash": user_hash}

    if local_user_id:
        return await _maybe_await(
            enqueue_member_resync(
                user_id=local_user_id,
                user_hash=user_hash,
                job_type=patreon_sync.JOB_TYPE_USER_MEMBER,
                job_id=job_id,
                priority=1 if bool(getattr(resync_request, "force", False)) else 5,
                source=constants.PATREON_SYNC_SOURCE_MANUAL_RESYNC,
                sanitized_metadata=metadata,
                db_module=db_patreon,
            )
        )

    db_patreon.enqueue_patreon_sync_job(
        job_id=job_id,
        job_type=patreon_sync.JOB_TYPE_USER_MEMBER,
        campaign_id=None,
        member_id_hash=None,
        user_id=None,
        dedupe_key_hash=patreon_sync.sync_job_dedupe_hash(
            patreon_sync.JOB_TYPE_USER_MEMBER,
            user_hash,
        ),
        priority=1 if bool(getattr(resync_request, "force", False)) else 5,
        not_before=None,
        source="manual",
        sanitized_metadata=metadata,
    )
    return PatreonResyncAcceptedResponse(
        accepted=True,
        status="queued",
        user_hash=user_hash,
        correlation_id=job_id,
        contract_version=constants.PATREON_DEFAULT_CONTRACT_VERSION,
        message=_GENERIC_RESYNC_ACCEPTED_MESSAGE,
    )


@router.get(_INTERNAL_ENTITLEMENTS_PATH, response_model=PatreonEntitlementS2SResponse, status_code=200)
async def get_internal_patreon_entitlement(user_hash: str, request: Request) -> JSONResponse:
    """Return a normalized Patreon entitlement for an authenticated S2S caller."""

    config = load_patreon_config()
    if not _authorized_internal_bearer(request, config):
        await capture_patreon_internal_audit(
            "s2s_entitlement_denied",
            outcome="unauthorized",
            request=request,
            status_code=401,
        )
        return _generic_error_response(status_code=401, message=_GENERIC_UNAUTHORIZED_MESSAGE)

    rate_limited = await _check_s2s_rate_limit(request=request, user_hash=user_hash)
    if rate_limited is not None:
        await capture_patreon_internal_audit(
            "s2s_entitlement_rate_limited",
            outcome="rate_limited",
            request=request,
            status_code=429,
        )
        return rate_limited

    try:
        row = await _read_current_entitlement_row(user_hash)
        response = _s2s_response_from_row(row, user_hash=user_hash)
        if response is None:
            await capture_patreon_internal_audit(
                "s2s_entitlement_read",
                outcome="free_no_patreon",
                request=request,
                status_code=200,
            )
            return _safe_json_response_from_model(_free_s2s_response(user_hash=user_hash), status_code=200)
        await capture_patreon_internal_audit(
            "s2s_entitlement_read",
            outcome="served",
            request=request,
            status_code=200,
            details={"contract_version": response.contract_version},
        )
        return _safe_json_response_from_model(response, status_code=200)
    except Exception as exc:
        logger.warning("Patreon S2S entitlement read failed generically: %s", type(exc).__name__)
        await capture_patreon_internal_audit(
            "s2s_entitlement_denied",
            outcome="degraded",
            request=request,
            status_code=404,
        )
        return _generic_error_response(status_code=404)


@router.post(
    _INTERNAL_RESYNC_PATH,
    response_model=PatreonResyncAcceptedResponse,
    status_code=202,
)
async def enqueue_internal_patreon_resync(
    user_hash: str,
    request: Request,
    resync_request: PatreonResyncRequest | None = Body(default=None),
) -> JSONResponse:
    """Accept an authenticated internal/manual Patreon entitlement resync enqueue."""

    config = load_patreon_config()
    if not _authorized_internal_bearer(request, config):
        await capture_patreon_internal_audit(
            "s2s_resync_denied",
            outcome="unauthorized",
            request=request,
            status_code=401,
        )
        return _generic_error_response(status_code=401, message=_GENERIC_UNAUTHORIZED_MESSAGE)

    rate_limited = await _check_s2s_rate_limit(request=request, user_hash=user_hash)
    if rate_limited is not None:
        await capture_patreon_internal_audit(
            "s2s_resync_rate_limited",
            outcome="rate_limited",
            request=request,
            status_code=429,
        )
        return rate_limited

    sync_retry_after = await _check_sync_enqueue_rate_limit(user_hash=user_hash)
    if sync_retry_after is not None:
        await record_patreon_internal_activity(
            ActivityType.PATREON_SYNC_FAILED,
            event="s2s_resync_rate_limited",
            outcome="rate_limited",
            request=request,
            status_code=429,
            details={"resync_status": "rate_limited", "retry_after_seconds": sync_retry_after},
        )
        return _resync_response(
            accepted=False,
            status="rate_limited",
            status_code=429,
            retry_after_seconds=sync_retry_after,
        )

    if _sync_disabled(config):
        await record_patreon_internal_activity(
            ActivityType.PATREON_SYNC_FAILED,
            event="s2s_resync_disabled",
            outcome="disabled",
            request=request,
            status_code=202,
            details={"accepted": False, "resync_status": "disabled"},
        )
        return _resync_response(accepted=False, status="disabled", status_code=202)

    try:
        row = await _read_current_entitlement_row(user_hash)
        if row is None:
            await record_patreon_internal_activity(
                ActivityType.PATREON_SYNC_FAILED,
                event="s2s_resync_degraded",
                outcome="degraded",
                request=request,
                status_code=202,
                details={"accepted": False, "resync_status": "degraded"},
            )
            return _resync_response(accepted=False, status="degraded", status_code=202)

        accepted = await _enqueue_user_hash_resync(
            user_hash=user_hash,
            row=row,
            resync_request=resync_request,
        )
        await record_patreon_internal_activity(
            ActivityType.PATREON_SYNC_STARTED,
            event="s2s_resync_enqueued",
            outcome="queued",
            request=request,
            status_code=202,
            details={"accepted": True, "resync_status": accepted.status},
        )
        return _safe_json_response_from_model(accepted, status_code=202)
    except Exception as exc:
        logger.warning("Patreon S2S resync enqueue degraded generically: %s", type(exc).__name__)
        await record_patreon_internal_activity(
            ActivityType.PATREON_SYNC_FAILED,
            event="s2s_resync_degraded",
            outcome="degraded",
            request=request,
            status_code=202,
            details={"accepted": False, "resync_status": "degraded"},
        )
        return _resync_response(accepted=False, status="degraded", status_code=202)


def _route_path(route: Any) -> str:
    return str(getattr(route, "path", ""))


def _assert_identity_contract_unchanged() -> None:
    for model_cls in (ValidateSessionResponse, UserLogin, EnhancedUserLogin):
        fields = {str(field).lower() for field in getattr(model_cls, "model_fields", {})}
        offenders = sorted(fields & _FORBIDDEN_AUTH_VALIDATE_FIELD_FRAGMENTS)
        if offenders:
            raise RuntimeError(f"{model_cls.__name__} drifted into Patreon entitlement fields: {offenders}")

    jwt_claim_sets = (
        getattr(constants, "BASE_REQUIRED_JWT_CLAIMS", ()),
        getattr(constants, "AUTH_REQUIRED_JWT_CLAIMS", ()),
    )
    for claim_set in jwt_claim_sets:
        offenders = sorted(
            str(claim).lower()
            for claim in claim_set
            if str(claim).lower() in _FORBIDDEN_AUTH_VALIDATE_FIELD_FRAGMENTS
        )
        if offenders:
            raise RuntimeError(f"JWT claim contract drifted into Patreon entitlement fields: {offenders}")


def _assert_internal_route_hardening() -> None:
    assert_patreon_response_model_allow_lists()
    _assert_identity_contract_unchanged()

    registered_paths = {_route_path(route) for route in getattr(router, "routes", [])}
    if registered_paths != _ALLOWED_INTERNAL_ROUTES:
        raise RuntimeError(f"Unexpected Patreon internal routes: {sorted(registered_paths)}")

    for path in registered_paths:
        if not APIAuditLogger.is_patreon_internal_entitlement_path(path):
            raise RuntimeError(f"Patreon internal route is not classified as S2S entitlement path: {path}")
        if APIAuditLogger.infer_auth_method_for_path(path) != "api_key":
            raise RuntimeError(f"Patreon internal route must audit as api_key/S2S: {path}")

    for route in getattr(router, "routes", []):
        response_model = getattr(route, "response_model", None)
        if response_model is None:
            continue
        safe_fields = frozenset(getattr(response_model, "safe_fields", frozenset()))
        if not safe_fields:
            raise RuntimeError(f"{response_model.__name__} is missing Patreon safe_fields")
        model_fields = frozenset(getattr(response_model, "model_fields", frozenset()))
        forbidden = sorted(
            str(field).lower().replace("-", "_")
            for field in model_fields
            if str(field).lower().replace("-", "_") in _FORBIDDEN_RESPONSE_KEYS_NORMALIZED
        )
        if forbidden:
            raise RuntimeError(f"{response_model.__name__} exposes forbidden fields: {forbidden}")

    forbidden_globals = sorted(name for name in _FORBIDDEN_AUTH_CONTEXT_GLOBALS if name in globals())
    if forbidden_globals:
        raise RuntimeError(f"Patreon internal route imported user auth/session seams: {forbidden_globals}")


_assert_internal_route_hardening()


__all__ = [
    "router",
    "capture_patreon_internal_audit",
    "record_patreon_internal_activity",
    "get_entitlement_by_user_hash",
    "get_patreon_entitlement_by_user_hash",
    "get_internal_patreon_entitlement",
    "enqueue_internal_patreon_resync",
]
