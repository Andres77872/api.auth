"""Authenticated Patreon account-link routes.

Patreon is deliberately entitlement/link proof only.  This module owns the
browser-owned link lifecycle routes and never issues local sessions, JWTs,
refresh tokens, cookies, or API keys.

Trace: SDD change ``patreon-account-link`` tasks ``5.1``, ``5.3``, ``5.4``, ``5.5``, ``5.6``, and ``5.7``.
"""

from __future__ import annotations

import inspect
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials

from src.Util import auth_constants as constants
from src.Util.Models import (
    PATREON_FORBIDDEN_RESPONSE_FIELD_NAMES,
    PatreonLinkRequest,
    PatreonLinkStatusResponse,
    PatreonProofConfirmRequest,
    PatreonProofRequestResponse,
    PatreonSafeEntitlement,
    PatreonUnlinkResponse,
    assert_patreon_response_model_allow_lists,
)
from src.Util.security import HTTPBearerOrCookie
from src.Util.activity_logger import ActivityType
from src.Util.api_audit_logger import APIAuditLogger
from src.Util.auth_flow import access_token_session_id, require_recent_reauthentication
from src.Util.auth_lifecycle import validate_access_session
from src.Util.db import db_patreon
from src.Util.email.config import load_email_config
from src.Util.email.route_support import client_ip, hash_route_value, link_url, user_agent
from src.Util.email.security import encrypt_render_payload
from src.Util.error_handler import AuthenticationError, ErrorCode, rate_limit_headers
from src.Util.patreon.client import PatreonClient
from src.Util.patreon.catalog import ensure_patreon_catalog_safely
from src.Util.patreon.config import PatreonConfigError, load_patreon_config
from src.Util.patreon.rate_limit import PatreonRateLimitExceeded, PatreonRateLimiter
from src.Util.patreon import sync as patreon_sync
from src.Util.patreon.security import (
    PATREON_PROOF_PURPOSE,
    fingerprint_from_digest,
    generate_patreon_proof_token,
    hash_patreon_email,
    hash_patreon_identifier,
    hash_patreon_proof_token,
    mask_patreon_email,
    normalize_patreon_email,
    parse_patreon_proof_token,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/patreon", tags=["Patreon Link"])
security = HTTPBearerOrCookie()

# Test/integration seams.  They intentionally default to ``None`` so importing
# this route has no provider, Redis, or DB side effects.
patreon_client = None
client = None
rate_limiter = None

_GENERIC_PROOF_MESSAGE = "If the Patreon link can be processed, a proof request has been accepted."
_GENERIC_CONFIRM_MESSAGE = "If the Patreon link can be confirmed, the request has been processed."
_GENERIC_STATUS_MESSAGE = "Patreon link status retrieved."
_GENERIC_UNLINK_MESSAGE = "If the Patreon link can be unlinked, the request has been processed."
_LINK_CONFIRMED_MESSAGE = "Patreon link confirmed."
_LINK_UNLINKED_MESSAGE = "Patreon link unlinked."
_LINK_ACTIVATION_SOURCE = "link_activation"
_UNLINK_REASON = "user_requested"
_SAFE_LINK_STATUS_VALUES = {"none", "pending", "linked", "unlinked", "revoked", "blocked"}
_PROOF_REQUEST_SURFACE = "proof_request"
_CONFIRM_SURFACE = "confirm"
_STATUS_SURFACE = "status"
_UNLINK_SURFACE = "unlink"
_ALLOWED_PHASE5_PATREON_ROUTES = frozenset(
    {
        "/auth/patreon/link/request",
        "/auth/patreon/link/confirm",
        "/auth/patreon/link/status",
        "/auth/patreon/link",
    }
)
_FORBIDDEN_PATREON_AUTH_ROUTES = frozenset(
    {
        "/auth/patreon/login",
        "/auth/patreon/authorize",
        "/auth/patreon/callback",
        "/auth/patreon/token",
    }
)
_FORBIDDEN_RESPONSE_KEYS_NORMALIZED = frozenset(
    str(field).lower().replace("-", "_") for field in PATREON_FORBIDDEN_RESPONSE_FIELD_NAMES
)
_SAFE_AUDIT_DETAIL_KEYS = frozenset(
    {
        "explicit_intent",
        "proof_delivery",
        "proof_consumed",
        "link_status",
        "rate_limit_bucket",
        "retry_after_seconds",
    }
)
_SAFE_PROOF_DELIVERY_VALUES = frozenset({"queued"})
_SAFE_RATE_LIMIT_BUCKET_VALUES = frozenset(
    {"link_request", "proof_request", "proof_consume", "unlink", "status"}
)
_FORBIDDEN_LOCAL_EMAIL_ACTIVATION_GLOBALS = frozenset(
    {
        "activate_user_email",
        "consume_email_activation_token",
        "add_user_email_and_enqueue",
        "resend_user_email_activation",
        "set_user_email_primary",
        "db_email",
        "user_email_link_tokens",
    }
)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _string_field(value: Any, name: str, default: str | None = None) -> str | None:
    if value is None:
        return default
    candidate = value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default)
    if candidate is None:
        return default
    text = str(candidate).strip()
    return text or default


def _bool_field(value: Any, name: str, default: bool = False) -> bool:
    candidate = value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default)
    if isinstance(candidate, bool):
        return candidate
    if candidate is None:
        return default
    return str(candidate).strip().lower() in {"1", "true", "yes", "y", "on"}


def _request_path(request: Request | None) -> str:
    if request is None:
        return "/auth/patreon/link"
    try:
        return request.url.path
    except Exception:
        return "/auth/patreon/link"


def _request_method(request: Request | None, default: str = "POST") -> str:
    if request is None:
        return default
    try:
        method = str(request.method or "").upper()
    except Exception:
        method = ""
    return method or default


def _safe_status_code(value: Any, default: int = 202) -> int:
    try:
        status_code = int(value)
    except (TypeError, ValueError):
        return default
    return status_code if 100 <= status_code <= 599 else default


def _safe_retry_after_seconds(value: Any) -> int | None:
    if value is None:
        return None
    try:
        retry_after = int(value)
    except (TypeError, ValueError):
        return None
    return max(1, retry_after)


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
        raise RuntimeError(f"Unsafe Patreon response fields would be serialized: {forbidden}")


def _safe_json_response_from_model(
    response_model: Any,
    *,
    status_code: int,
    retry_after_seconds: int | None = None,
) -> JSONResponse:
    """Serialize a Patreon public response through its explicit safe DTO only.

    FastAPI returns a ``JSONResponse`` directly as-is, so do not rely on
    ``response_model`` filtering here.  Every browser-visible Patreon route must
    call ``model_dump_safe()`` before creating the response.
    """

    model_dump_safe = getattr(response_model, "model_dump_safe", None)
    if not callable(model_dump_safe):
        raise RuntimeError("Patreon route attempted to serialize a non-safe response model")

    content = model_dump_safe(mode="json", exclude_none=True)
    if not isinstance(content, Mapping):
        raise RuntimeError("Patreon safe response serialization did not produce a mapping")
    _assert_safe_response_content(content)
    retry_after = _safe_retry_after_seconds(retry_after_seconds)
    return JSONResponse(
        status_code=_safe_status_code(status_code),
        content=dict(content),
        headers=rate_limit_headers(retry_after) if retry_after is not None else None,
    )


def _safe_audit_detail_value(key: str, value: Any) -> Any:
    if key == "explicit_intent" or key == "proof_consumed":
        return bool(value)
    if key == "retry_after_seconds":
        return _safe_retry_after_seconds(value)
    if key == "link_status":
        return _safe_link_status(value, constants.PATREON_LINK_STATUS_NONE)
    if key == "proof_delivery":
        candidate = str(value or "").strip().lower()
        return candidate if candidate in _SAFE_PROOF_DELIVERY_VALUES else None
    if key == "rate_limit_bucket":
        candidate = str(value or "").strip().lower()
        return candidate if candidate in _SAFE_RATE_LIMIT_BUCKET_VALUES else None
    return None


def _safe_patreon_event_metadata(
    *,
    event: str,
    outcome: str,
    request: Request | None,
    status_code: int,
    catalog_code: str | None = None,
    reason: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build route-local audit/activity metadata with Patreon internals removed.

    Keep this deliberately allow-list-shaped.  Do not add raw Patreon IDs, raw or
    masked email, proof tokens, hashes, hash prefixes, fingerprints, provider
    payloads, signatures, or audit rows here.  The API audit helper is still run
    as a second redaction pass before the activity helper persists anything.
    """

    metadata: dict[str, Any] = {
        "event": event,
        "outcome": outcome,
        "route": _request_path(request),
        "method": _request_method(request),
        "status_code": _safe_status_code(status_code),
    }
    if catalog_code:
        metadata["catalog_code"] = catalog_code
    if reason:
        metadata["reason"] = reason
    if details:
        for key, value in details.items():
            normalized_key = str(key).strip().lower().replace("-", "_")
            if normalized_key in metadata or normalized_key not in _SAFE_AUDIT_DETAIL_KEYS:
                continue
            safe_value = _safe_audit_detail_value(normalized_key, value)
            if safe_value is not None:
                metadata[normalized_key] = safe_value

    filtered = APIAuditLogger.filter_sensitive_data(metadata)
    return filtered if isinstance(filtered, dict) else metadata


async def capture_patreon_link_audit(
    event: str,
    *,
    details: Mapping[str, Any] | None = None,
    request: Request | None = None,
    status_code: int = 202,
    user_type: str | None = None,
) -> None:
    """Route-local audit seam with the same redaction/tag helpers as middleware.

    Durable API audit rows are owned by the API audit middleware once this router
    is registered in Phase 9.  This hook exists so link-lifecycle route code can
    consistently produce sanitized audit metadata and tests can patch a narrow
    seam without causing duplicate durable rows.
    """

    safe_metadata = _safe_patreon_event_metadata(
        event=event,
        outcome=str((details or {}).get("outcome") or event),
        request=request,
        status_code=status_code,
        details=details,
    )
    tags = APIAuditLogger.generate_tags(
        _request_path(request),
        _request_method(request),
        _safe_status_code(status_code),
        user_type=user_type,
    )
    security_event = APIAuditLogger.is_security_event(
        _request_path(request),
        _request_method(request),
        _safe_status_code(status_code),
        user_type=user_type,
    )
    _ = (safe_metadata, tags, security_event)


async def record_patreon_link_activity(
    activity_type: ActivityType,
    *,
    event: str,
    outcome: str,
    request: Request | None,
    user_id: str | None,
    status_code: int = 202,
    reason: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> None:
    """Persist a redacted Patreon link activity and route-local audit metadata."""

    try:
        from src.Util import activity_logger as activity_logger_module

        activity_logger_module.assert_patreon_activity_catalog_alignment()
        catalog_code = activity_logger_module.get_patreon_activity_catalog_code(activity_type)
        metadata = _safe_patreon_event_metadata(
            event=event,
            outcome=outcome,
            request=request,
            status_code=status_code,
            catalog_code=catalog_code,
            reason=reason,
            details=details,
        )
        activity_details = activity_logger_module.build_patreon_activity_details(event, **metadata)
        await _maybe_await(
            capture_patreon_link_audit(
                event,
                details=metadata,
                request=request,
                status_code=status_code,
            )
        )
        activity_logger_module.log_patreon_activity(
            activity_type,
            activity_details,
            user_id=user_id,
            ip_address=client_ip(request) if request is not None else None,
            user_agent=APIAuditLogger.sanitize_sensitive_text(user_agent(request)) if request is not None else None,
        )
    except Exception:
        # Audit/activity failures must not change the generic public Patreon link
        # posture or leak provider/link/proof state through error responses.
        logger.debug("Patreon link activity logging failed", exc_info=True)


async def _record_patreon_link_rejection(
    *,
    request: Request,
    user_id: str,
    event: str,
    reason: str,
    status_code: int = 202,
    outcome: str = "rejected",
    details: Mapping[str, Any] | None = None,
) -> None:
    await record_patreon_link_activity(
        ActivityType.PATREON_LINK_REJECTED,
        event=event,
        outcome=outcome,
        request=request,
        user_id=user_id,
        status_code=status_code,
        reason=reason,
        details=details,
    )


def _generic_public_response(
    surface: str,
    *,
    status_code: int | None = None,
    message: str | None = None,
    link_status: str | None = None,
    entitlement: PatreonSafeEntitlement | None = None,
    retry_after_seconds: int | None = None,
) -> JSONResponse:
    """Central generic public response posture for Phase 5 link routes."""

    if surface == _PROOF_REQUEST_SURFACE:
        response = PatreonProofRequestResponse(
            success=True,
            accepted=True,
            message=message or _GENERIC_PROOF_MESSAGE,
            retry_after_seconds=_safe_retry_after_seconds(retry_after_seconds),
        )
        return _safe_json_response_from_model(
            response,
            status_code=status_code or 202,
            retry_after_seconds=retry_after_seconds,
        )

    if surface in {_CONFIRM_SURFACE, _STATUS_SURFACE}:
        default_message = _GENERIC_STATUS_MESSAGE if surface == _STATUS_SURFACE else _GENERIC_CONFIRM_MESSAGE
        response = PatreonLinkStatusResponse(
            success=True,
            message=message or default_message,
            link_status=_safe_link_status(link_status, constants.PATREON_LINK_STATUS_PENDING),
            entitlement=entitlement,
            retry_after_seconds=_safe_retry_after_seconds(retry_after_seconds),
        )
        return _safe_json_response_from_model(
            response,
            status_code=status_code or (200 if surface == _STATUS_SURFACE else 202),
            retry_after_seconds=retry_after_seconds,
        )

    if surface == _UNLINK_SURFACE:
        safe_link_status = _safe_link_status(link_status, constants.PATREON_LINK_STATUS_UNLINKED)
        response = PatreonUnlinkResponse(
            success=True,
            message=message or _GENERIC_UNLINK_MESSAGE,
            link_status=safe_link_status,
            entitlement=entitlement or _default_status_entitlement(link_status=safe_link_status),
        )
        return _safe_json_response_from_model(
            response,
            status_code=status_code or 200,
            retry_after_seconds=retry_after_seconds,
        )

    raise RuntimeError(f"Unsupported Patreon public response surface: {surface}")


def _proof_request_response(
    *,
    status_code: int = 202,
    retry_after_seconds: int | None = None,
) -> JSONResponse:
    return _generic_public_response(
        _PROOF_REQUEST_SURFACE,
        status_code=status_code,
        retry_after_seconds=retry_after_seconds,
    )


def _safe_link_status(value: Any, default: str = constants.PATREON_LINK_STATUS_PENDING) -> str:
    status = str(value or "").strip().lower()
    return status if status in _SAFE_LINK_STATUS_VALUES else default


def _link_status_response(
    *,
    status_code: int = 202,
    message: str = _GENERIC_CONFIRM_MESSAGE,
    link_status: str = constants.PATREON_LINK_STATUS_PENDING,
    entitlement: PatreonSafeEntitlement | None = None,
    retry_after_seconds: int | None = None,
) -> JSONResponse:
    surface = _STATUS_SURFACE if message == _GENERIC_STATUS_MESSAGE else _CONFIRM_SURFACE
    return _generic_public_response(
        surface,
        status_code=status_code,
        message=message,
        link_status=link_status,
        entitlement=entitlement,
        retry_after_seconds=retry_after_seconds,
    )


def _unlink_response(
    *,
    status_code: int = 200,
    message: str = _GENERIC_UNLINK_MESSAGE,
    link_status: str = constants.PATREON_LINK_STATUS_UNLINKED,
    entitlement: PatreonSafeEntitlement | None = None,
    retry_after_seconds: int | None = None,
) -> JSONResponse:
    return _generic_public_response(
        _UNLINK_SURFACE,
        status_code=status_code,
        message=message,
        link_status=link_status,
        entitlement=entitlement,
        retry_after_seconds=retry_after_seconds,
    )


def _generic_confirm_response(
    *,
    status_code: int = 202,
    retry_after_seconds: int | None = None,
) -> JSONResponse:
    return _link_status_response(
        status_code=status_code,
        message=_GENERIC_CONFIRM_MESSAGE,
        link_status=constants.PATREON_LINK_STATUS_PENDING,
        retry_after_seconds=retry_after_seconds,
    )


def _retry_after_from_rate_limit(exc: PatreonRateLimitExceeded) -> int:
    return _safe_retry_after_seconds(getattr(exc, "retry_after", None)) or 1


def _rate_limited_public_response(surface: str, exc: PatreonRateLimitExceeded) -> JSONResponse:
    retry_after = _retry_after_from_rate_limit(exc)
    if surface == _PROOF_REQUEST_SURFACE:
        return _proof_request_response(status_code=429, retry_after_seconds=retry_after)
    if surface == _CONFIRM_SURFACE:
        return _generic_confirm_response(status_code=429, retry_after_seconds=retry_after)
    if surface == _STATUS_SURFACE:
        return _link_status_response(
            status_code=429,
            message=_GENERIC_STATUS_MESSAGE,
            link_status=constants.PATREON_LINK_STATUS_NONE,
            entitlement=_default_status_entitlement(),
            retry_after_seconds=retry_after,
        )
    if surface == _UNLINK_SURFACE:
        return _unlink_response(
            status_code=429,
            message=_GENERIC_UNLINK_MESSAGE,
            link_status=constants.PATREON_LINK_STATUS_NONE,
            entitlement=_default_status_entitlement(),
            retry_after_seconds=retry_after,
        )
    raise RuntimeError(f"Unsupported Patreon rate-limit response surface: {surface}")


def _session_id_from_login_data(login_data: Any) -> str | None:
    """The session id OAuth reauth markers are keyed by: the access token's ``session_id`` claim."""
    access_token = _string_field(login_data, "access_token")
    return _string_field(login_data, "session_id") or access_token_session_id(access_token) or access_token


def _load_current_session(credentials: HTTPAuthorizationCredentials) -> Any:
    return validate_access_session(credentials.credentials)


def _require_local_user(login_data: Any) -> str:
    user_id = _string_field(login_data, "user_id")
    if not user_id:
        raise AuthenticationError(
            message="Authentication required",
            error_code=ErrorCode.SESSION_INVALID,
        )
    return user_id


def _feature_ready_for_link_request(config: Any) -> bool:
    """Link requests need every secret the confirm path will use plus a tier map.

    Matches ``validate_patreon_readiness`` for the linking surface: without the ID
    HMAC secret or a configured campaign, a proof could be emailed that can never
    be confirmed.
    """

    if config is None or not _bool_field(config, "linking_enabled"):
        return False
    required = (
        _string_field(config, "creator_access_token"),
        _string_field(config, "provider_sub_pepper"),
        _string_field(config, "email_hash_pepper"),
        _string_field(config, "proof_token_pepper"),
        _string_field(config, "id_hmac_secret"),
    )
    return all(required) and bool(_configured_campaign_ids(config))


def _load_config_or_none() -> Any:
    """Load Patreon config; malformed config degrades to "not ready" instead of a 500."""

    try:
        return load_patreon_config()
    except PatreonConfigError:
        logger.warning("Patreon configuration is invalid; linking is treated as not ready")
        return None


def _is_consumer_session(login_data: Any) -> bool:
    """Patreon entitlements attach to consumer accounts only (the SQL enforces it too)."""

    user_type = (_string_field(login_data, "user_type") or "consumer").lower()
    return user_type == "consumer"


def _feature_ready_for_link_confirm(config: Any) -> bool:
    return bool(
        config is not None
        and _bool_field(config, "linking_enabled")
        and _string_field(config, "proof_token_pepper")
    )


def _current_rate_limiter() -> PatreonRateLimiter:
    return rate_limiter or PatreonRateLimiter()


async def _check_link_request_rate_limit(
    *,
    request: Request,
    user_id: str,
    email_hint: str | None,
) -> JSONResponse | None:
    try:
        await _maybe_await(
            _current_rate_limiter().check_link_request(
                user_id=user_id,
                ip_address=client_ip(request),
                email_hint=email_hint,
                request_scope="auth_patreon_link_request",
            )
        )
        return None
    except PatreonRateLimitExceeded as exc:
        return _rate_limited_public_response(_PROOF_REQUEST_SURFACE, exc)


async def _check_proof_request_rate_limit(
    *,
    request: Request,
    user_id: str,
    email_hint: str | None,
) -> JSONResponse | None:
    """Spend the proof-send budget on EVERY link request, before Patreon is called.

    A member only matches when the hint equals the Patreon email, so keying on the
    hint limits emails to that recipient exactly as keying on the recipient would,
    while keeping the budget independent of whether the hint belongs to a patron.
    """

    recipient = normalize_patreon_email(email_hint) if email_hint else None
    try:
        await _maybe_await(
            _current_rate_limiter().check_proof_request(
                user_id=user_id,
                ip_address=client_ip(request),
                proof_email_hash=hashlib.sha256(recipient.encode("utf-8")).hexdigest() if recipient else None,
                pending_link_id=None,
            )
        )
        return None
    except PatreonRateLimitExceeded as exc:
        return _rate_limited_public_response(_PROOF_REQUEST_SURFACE, exc)


async def _check_proof_consume_rate_limit(
    *,
    request: Request,
    user_id: str,
    lookup_id: str | None,
) -> JSONResponse | None:
    try:
        await _maybe_await(
            _current_rate_limiter().check_proof_consume(
                ip_address=client_ip(request),
                lookup_id=lookup_id,
                pending_link_id=None,
                user_id=user_id,
            )
        )
        return None
    except PatreonRateLimitExceeded as exc:
        return _rate_limited_public_response(_CONFIRM_SURFACE, exc)


def _default_status_entitlement(
    *,
    link_status: str = constants.PATREON_LINK_STATUS_NONE,
) -> PatreonSafeEntitlement:
    safe_link_status = _safe_link_status(link_status, constants.PATREON_LINK_STATUS_NONE)
    return PatreonSafeEntitlement(
        external_source=None,
        status=constants.PATREON_ENTITLEMENT_STATUS_FREE,
        plan_code="free",
        link_status=safe_link_status,
    )


async def _check_status_rate_limit(
    *,
    request: Request,
    user_id: str,
) -> JSONResponse | None:
    try:
        await _maybe_await(
            _current_rate_limiter().check_status(
                user_id=user_id,
                ip_address=client_ip(request),
            )
        )
        return None
    except PatreonRateLimitExceeded as exc:
        return _rate_limited_public_response(_STATUS_SURFACE, exc)


async def _check_unlink_rate_limit(
    *,
    request: Request,
    user_id: str,
) -> JSONResponse | None:
    try:
        await _maybe_await(
            _current_rate_limiter().check_unlink(
                user_id=user_id,
                ip_address=client_ip(request),
            )
        )
        return None
    except PatreonRateLimitExceeded as exc:
        return _rate_limited_public_response(_UNLINK_SURFACE, exc)


def _plain_status_mapping(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
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
    return None


def _safe_entitlement_from_status_payload(payload: Any) -> PatreonSafeEntitlement:
    if isinstance(payload, PatreonSafeEntitlement):
        return payload
    row = _plain_status_mapping(payload) or {}
    safe_payload = {key: value for key, value in row.items() if key in PatreonSafeEntitlement.safe_fields}
    return PatreonSafeEntitlement(**safe_payload)


def _status_components_from_row(row: Any) -> tuple[str, PatreonSafeEntitlement]:
    safe_row = _plain_status_mapping(row)
    if safe_row is None:
        entitlement = _default_status_entitlement()
        return entitlement.link_status, entitlement

    nested_entitlement = safe_row.get("entitlement")
    if nested_entitlement is not None:
        try:
            entitlement = _safe_entitlement_from_status_payload(nested_entitlement)
        except Exception:
            entitlement = _default_status_entitlement()
        link_status = _safe_link_status(
            safe_row.get("link_status") or entitlement.link_status,
            constants.PATREON_LINK_STATUS_NONE,
        )
        return link_status, entitlement

    entitlement = patreon_sync.db_entitlement_row_to_safe_entitlement(
        safe_row,
        now=datetime.now(timezone.utc).replace(microsecond=0),
    )
    return _safe_link_status(entitlement.link_status, constants.PATREON_LINK_STATUS_NONE), entitlement


def _safe_unlink_entitlement_from_row(row: Any) -> tuple[str, PatreonSafeEntitlement]:
    """Collapse any DB/client unlink result to the no-paid-grant safe DTO.

    Unlink results may come from the real SQL wrapper, older integration seams,
    or no-op/error paths.  In every case the browser-visible response is forced
    through `PatreonSafeEntitlement` and cannot preserve a paid plan/tier after
    the unlink operation.
    """

    safe_row = _plain_status_mapping(row) or {}
    link_status = _safe_link_status(
        safe_row.get("link_status"),
        constants.PATREON_LINK_STATUS_UNLINKED,
    )
    if link_status not in {constants.PATREON_LINK_STATUS_UNLINKED, constants.PATREON_LINK_STATUS_REVOKED}:
        link_status = constants.PATREON_LINK_STATUS_UNLINKED

    nested_entitlement = safe_row.get("entitlement")
    source_entitlement: PatreonSafeEntitlement | None = None
    if nested_entitlement is not None:
        try:
            source_entitlement = _safe_entitlement_from_status_payload(nested_entitlement)
        except Exception:
            source_entitlement = None
    elif safe_row:
        try:
            source_entitlement = patreon_sync.db_entitlement_row_to_safe_entitlement(
                safe_row,
                now=datetime.now(timezone.utc).replace(microsecond=0),
            )
        except Exception:
            source_entitlement = None

    entitlement = PatreonSafeEntitlement(
        external_source=None,
        status=(
            constants.PATREON_ENTITLEMENT_STATUS_REVOKED
            if link_status == constants.PATREON_LINK_STATUS_REVOKED
            else constants.PATREON_ENTITLEMENT_STATUS_FREE
        ),
        plan_code="free",
        tier_code=None,
        tier_name=None,
        link_status=link_status,
        last_synced_at=getattr(source_entitlement, "last_synced_at", None),
        classification_version=getattr(
            source_entitlement,
            "classification_version",
            constants.PATREON_DEFAULT_CONTRACT_VERSION,
        ),
    )
    return link_status, entitlement


async def _call_db_get_link_status(*, user_hash: str | None) -> Any:
    if not user_hash:
        return None
    return await _maybe_await(db_patreon.get_entitlement_by_user_hash(user_hash))


def _configured_campaign_ids(config: Any) -> tuple[str, ...]:
    direct = getattr(config, "campaign_ids", None)
    if isinstance(direct, (list, tuple, set)):
        return tuple(str(item).strip() for item in direct if str(item).strip())
    entries = getattr(config, "campaign_tier_maps", None) or getattr(config, "tier_map_entries", None)
    values: list[str] = []
    if isinstance(entries, (list, tuple, set)):
        for entry in entries:
            raw = _string_field(entry, "campaign_id")
            if raw and raw not in values:
                values.append(raw)
    return tuple(values)


def _patreon_client_from_config(config: Any) -> tuple[Any, bool]:
    if patreon_client is not None:
        return patreon_client, False
    if client is not None:
        return client, False
    if isinstance(PatreonClient, type) and "from_config" in PatreonClient.__dict__:
        return PatreonClient.from_config(config), True
    return PatreonClient(  # type: ignore[operator]
        access_token=_string_field(config, "creator_access_token"),
        user_agent=_string_field(config, "user_agent"),
        base_url=_string_field(config, "api_base_url"),
        timeout_seconds=getattr(config, "api_timeout_seconds", None),
        connect_timeout_seconds=getattr(config, "api_connect_timeout_seconds", None),
        page_size=getattr(config, "api_page_size", None),
        max_pages_per_sync=getattr(config, "api_max_pages_per_sync", None),
    ), True


def _iter_members(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, Mapping)]
    if isinstance(data, Mapping):
        return [data]
    if payload.get("type") == "member":
        return [payload]
    return []


def _included_lookup(payload: Any) -> dict[tuple[str, str], Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        return {}
    included = payload.get("included")
    if not isinstance(included, list):
        return {}
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for item in included:
        if not isinstance(item, Mapping):
            continue
        item_type = _string_field(item, "type")
        item_id = _string_field(item, "id")
        if item_type and item_id:
            result[(item_type, item_id)] = item
    return result


def _relationship_id(member: Mapping[str, Any], name: str) -> str | None:
    relationships = member.get("relationships")
    if not isinstance(relationships, Mapping):
        return None
    relationship = relationships.get(name)
    if not isinstance(relationship, Mapping):
        return None
    data = relationship.get("data")
    if isinstance(data, list):
        return None
    if isinstance(data, Mapping):
        return _string_field(data, "id")
    return None


def _member_email(member: Mapping[str, Any], payload: Any) -> str | None:
    attributes = member.get("attributes")
    if isinstance(attributes, Mapping):
        email = _string_field(attributes, "email")
        if email:
            return email
    user_id = _relationship_id(member, "user")
    included_user = _included_lookup(payload).get(("user", user_id or ""))
    if included_user:
        included_attrs = included_user.get("attributes")
        if isinstance(included_attrs, Mapping):
            return _string_field(included_attrs, "email")
    return None


def _select_member_from_payload(
    payload: Any,
    *,
    email_hint: str | None,
    allow_first: bool,
) -> Mapping[str, Any] | None:
    members = _iter_members(payload)
    if not members:
        return None
    normalized_hint = normalize_patreon_email(email_hint or "") if email_hint else ""
    if normalized_hint:
        for member in members:
            member_email = _member_email(member, payload)
            if member_email and normalize_patreon_email(member_email) == normalized_hint:
                return member
    return members[0] if allow_first else None


async def _discover_member_for_link(
    *,
    provider_client: Any,
    config: Any,
    email_hint: str | None,
) -> tuple[Any, Mapping[str, Any] | None, str | None]:
    """Find the campaign member whose Patreon email equals the hint.

    Returns ``(payload, member, raw_campaign_id)``; the campaign is the configured
    one the member was found in, used when the member omits its campaign
    relationship. Email equality only selects the member: ownership is proven by
    the emailed proof.
    """

    if not email_hint:
        return {}, None, None

    for campaign_id in _configured_campaign_ids(config):
        payload = await _fetch_campaign_payload(provider_client, campaign_id)
        member = _select_member_from_payload(payload, email_hint=email_hint, allow_first=False)
        if member is not None:
            return payload, member, campaign_id
    return {}, None, None


def _hmac_identifier_or_none(
    *,
    raw_id: str | None,
    kind: str,
    pepper: str | None,
) -> tuple[bytes | None, str | None]:
    if not raw_id or not pepper:
        return None, None
    digest = hash_patreon_identifier(raw_id=raw_id, kind=kind, pepper=pepper)
    return digest, fingerprint_from_digest(digest)


def _campaign_db_id(raw_campaign_id: str | None, config: Any) -> str | None:
    pepper = _string_field(config, "id_hmac_secret") or _string_field(config, "provider_sub_pepper")
    digest, fingerprint = _hmac_identifier_or_none(raw_id=raw_campaign_id, kind="campaign", pepper=pepper)
    if digest is None or fingerprint is None:
        return None
    return f"pcamp-{fingerprint}"


def _proof_render_payload(
    *,
    request: Request,
    proof_token: str,
    lookup_id: str,
    recipient_masked: str,
    expires_at: Any,
) -> dict[str, Any]:
    return {
        "purpose": PATREON_PROOF_PURPOSE,
        "patreon_link_proof_url": link_url(request, "/auth/patreon/link/confirm", proof_token),
        "proof_token": proof_token,
        "lookup_id": lookup_id,
        "recipient_masked": recipient_masked,
        "expires_at": expires_at.isoformat() if hasattr(expires_at, "isoformat") else str(expires_at),
    }


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _value_field(value: Any, name: str, default: Any = None) -> Any:
    if value is None:
        return default
    return value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default)


def _bytes_field(value: Any, *names: str) -> bytes | None:
    for name in names:
        candidate = _value_field(value, name)
        if candidate is None:
            continue
        if isinstance(candidate, bytes):
            return candidate
        if isinstance(candidate, bytearray):
            return bytes(candidate)
        if isinstance(candidate, memoryview):
            return candidate.tobytes()
        if isinstance(candidate, str):
            text = candidate.strip()
            if not text:
                continue
            try:
                if len(text) == 64:
                    return bytes.fromhex(text)
            except ValueError:
                pass
            return text.encode("utf-8")
    return None


def _proof_parts_from_request(confirm_request: PatreonProofConfirmRequest) -> tuple[str, str] | None:
    if confirm_request.token:
        return parse_patreon_proof_token(confirm_request.token)
    if confirm_request.lookup_id and confirm_request.secret:
        return confirm_request.lookup_id, confirm_request.secret
    return None


def _route_hashes_for_consume(request: Request) -> tuple[bytes | None, bytes | None]:
    try:
        email_config = load_email_config(validate_real_send_guard=False)
    except Exception:
        return None, None
    return hash_route_value(client_ip(request), email_config), hash_route_value(user_agent(request), email_config)


def _call_db_consume_proof(*, kwargs: dict[str, Any]) -> Any:
    # The user binding (``user_id``) is always passed: the SQL only consumes a proof
    # requested by the same local user. Never pass raw token material to logs.
    method = getattr(db_patreon, "consume_patreon_proof", None)
    if not callable(method):
        raise RuntimeError("Patreon proof consume DB wrapper is not available")
    return method(**kwargs)


def _consume_status(row: Any) -> str:
    return (_string_field(row, "consume_status") or _string_field(row, "status") or "").lower()


def _proof_context_from_consume(row: Any) -> dict[str, Any]:
    campaign_id = _string_field(row, "campaign_id") or _string_field(row, "patreon_campaign_id")
    member_fingerprint = _string_field(row, "member_id_fingerprint") or _string_field(
        row,
        "patreon_member_id_fingerprint",
    )
    membership_id = _string_field(row, "membership_id")
    if not membership_id and campaign_id and member_fingerprint:
        membership_id = f"pmem-{campaign_id.removeprefix('pcamp-')}-{member_fingerprint}"

    return {
        "proof_id": _string_field(row, "proof_id"),
        "user_id": _string_field(row, "user_id"),
        "campaign_id": campaign_id,
        "provider_sub_hash": _bytes_field(row, "provider_sub_hash", "patreon_user_id_hash"),
        "provider_sub_fingerprint": _string_field(
            row,
            "provider_sub_fingerprint",
        ) or _string_field(row, "patreon_user_id_fingerprint"),
        "member_id_hash": _bytes_field(row, "member_id_hash", "patreon_member_id_hash"),
        "member_id_fingerprint": member_fingerprint,
        "provider_email_hash": _bytes_field(row, "provider_email_hash", "proof_email_hash"),
        "provider_email_masked": _string_field(row, "provider_email_masked") or _string_field(
            row,
            "proof_email_masked",
        ),
        "external_account_id": _string_field(row, "external_account_id"),
        "membership_id": membership_id,
    }


def _proof_context_complete(context: Mapping[str, Any]) -> bool:
    return bool(
        context.get("proof_id")
        and context.get("campaign_id")
        and context.get("provider_sub_hash")
        and context.get("provider_sub_fingerprint")
        and context.get("member_id_hash")
        and context.get("member_id_fingerprint")
        and context.get("membership_id")
    )


def _call_db_check_conflict(*, user_id: str, provider_sub_hash: bytes) -> Any:
    method = getattr(db_patreon, "check_patreon_link_conflict", None)
    if not callable(method):
        raise RuntimeError("Patreon link conflict DB wrapper is not available")
    return method(user_id=user_id, provider_sub_hash=provider_sub_hash)


def _conflict_clear(row: Any) -> bool:
    status = (_string_field(row, "conflict_status") or _string_field(row, "status") or "clear").lower()
    return status in {"", "clear", "none", "ok"}


def _conflict_activity_outcome(row: Any) -> tuple[str, str]:
    status = (_string_field(row, "conflict_status") or _string_field(row, "status") or "conflict").lower()
    if status == "same_user_already_linked":
        return "relink_required", "active_patreon_link_exists"
    if status == "linked_to_other_user":
        return "conflict", "provider_identity_unavailable"
    return "conflict", "link_conflict"


def _call_db_link_account(*, user_id: str, context: Mapping[str, Any]) -> Any:
    method = getattr(db_patreon, "link_patreon_account", None)
    if not callable(method):
        raise RuntimeError("Patreon link account DB wrapper is not available")
    return method(
        external_account_id=_string_field(context, "external_account_id") or _new_id("uea"),
        user_id=user_id,
        provider_sub_hash=context["provider_sub_hash"],
        provider_sub_fingerprint=str(context["provider_sub_fingerprint"]),
        provider_email_hash=context.get("provider_email_hash"),
        provider_email_masked=context.get("provider_email_masked"),
        linked_by=user_id,
        proof_id=str(context["proof_id"]),
        campaign_id=str(context["campaign_id"]),
        membership_id=str(context["membership_id"]),
        member_id_hash=context.get("member_id_hash"),
        member_id_fingerprint=str(context["member_id_fingerprint"]),
        metadata={"source": "auth_patreon_link_confirm", "purpose": PATREON_PROOF_PURPOSE},
    )


def _call_db_unlink_account(*, user_id: str) -> Any:
    method_names = (
        ("unlink_patreon_account", "unlink_account")
        if isinstance(db_patreon, type(inspect))
        else ("unlink_account", "unlink_patreon_account")
    )
    history_id = _new_id("peh")
    attempts = (
        {
            "user_id": user_id,
            "unlinked_by": user_id,
            "reason": _UNLINK_REASON,
            "history_id": history_id,
        },
        {
            "user_id": user_id,
            "unlinked_by": user_id,
            "reason": _UNLINK_REASON,
        },
        {"user_id": user_id},
    )
    for method_name in method_names:
        method = getattr(db_patreon, method_name, None)
        if not callable(method):
            continue
        last_type_error: TypeError | None = None
        for kwargs in attempts:
            try:
                return method(**kwargs)
            except TypeError as exc:
                last_type_error = exc
                continue
        if last_type_error is not None:
            raise last_type_error
    raise RuntimeError("Patreon unlink DB wrapper is not available")


def _payload_for_single_member(payload: Any, member: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"data": [member]}
    included = payload.get("included") if isinstance(payload, Mapping) else None
    if isinstance(included, list):
        result["included"] = included
    return result


def _hash_matches(candidate: bytes | None, expected: bytes | None) -> bool:
    return bool(candidate and expected and hmac.compare_digest(candidate, expected))


async def _fetch_campaign_payload(provider_client: Any, campaign_id: str) -> Any:
    return await _maybe_await(provider_client.fetch_campaign_members(campaign_id))


async def _member_payload_for_consumed_proof(
    *,
    provider_client: Any,
    config: Any,
    context: Mapping[str, Any],
) -> dict[str, Any] | None:
    id_pepper = _string_field(config, "id_hmac_secret") or _string_field(config, "provider_sub_pepper")
    provider_pepper = _string_field(config, "provider_sub_pepper")
    expected_member_hash = context.get("member_id_hash")
    expected_provider_hash = context.get("provider_sub_hash")
    if not id_pepper or not expected_member_hash:
        return None

    for raw_campaign_id in _configured_campaign_ids(config):
        expected_campaign_id = _string_field(context, "campaign_id")
        if expected_campaign_id and _campaign_db_id(raw_campaign_id, config) != expected_campaign_id:
            continue
        payload = await _fetch_campaign_payload(provider_client, raw_campaign_id)
        for member in _iter_members(payload):
            raw_member_id = _string_field(member, "id")
            if not raw_member_id:
                continue
            try:
                member_hash = hash_patreon_identifier(raw_id=raw_member_id, kind="member", pepper=id_pepper)
            except Exception:
                continue
            if not _hash_matches(member_hash, expected_member_hash):
                continue

            raw_user_id = _relationship_id(member, "user")
            if expected_provider_hash and provider_pepper and raw_user_id:
                try:
                    provider_hash = hash_patreon_identifier(raw_id=raw_user_id, kind="user", pepper=provider_pepper)
                except Exception:
                    continue
                if not _hash_matches(provider_hash, expected_provider_hash):
                    continue
            return _payload_for_single_member(payload, member)
    return None


def _parse_datetime_or_none(value: Any) -> datetime | None:
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


def _pending_link_activation_result(config: Any) -> Any:
    return patreon_sync.classify_member_payload(
        None,
        config=config,
        now=datetime.now(timezone.utc).replace(microsecond=0),
        source=_LINK_ACTIVATION_SOURCE,
        is_complete=False,
        current_snapshot={
            "external_source": constants.PATREON_PROVIDER_NAME,
            "status": constants.PATREON_ENTITLEMENT_STATUS_PENDING,
            "plan_code": "free",
            "link_status": constants.PATREON_LINK_STATUS_LINKED,
        },
    )


def _persist_pending_initial_snapshot(
    *,
    user_id: str,
    external_account_id: str,
    membership_id: str,
    context: Mapping[str, Any],
    result: Any,
) -> None:
    method = getattr(db_patreon, "upsert_patreon_entitlement_snapshot", None)
    if not callable(method):
        raise RuntimeError("Patreon entitlement snapshot DB wrapper is not available")
    classification = result.classification
    method(
        snapshot_id=_new_id("psnap"),
        history_id=None,
        current_id=None,
        user_id=user_id,
        external_account_id=external_account_id,
        membership_id=membership_id,
        observed_at=datetime.now(timezone.utc).replace(microsecond=0),
        sync_source=_LINK_ACTIVATION_SOURCE,
        patron_status_normalized="unknown",
        tier_hashes_json=[],
        last_charge_status_normalized=None,
        next_charge_at=None,
        payload_hash=None,
        is_complete=False,
        requires_resync=True,
        entitlement_status=classification.status,
        link_status=_safe_link_status(classification.link_status, constants.PATREON_LINK_STATUS_LINKED),
        plan_code=classification.plan_code,
        tier_code=classification.tier_code,
        tier_name=classification.tier_name,
        next_renewal_at=_parse_datetime_or_none(classification.next_renewal_at),
        grace_period_until=_parse_datetime_or_none(classification.grace_period_until),
        stale_after=_parse_datetime_or_none(classification.stale_after),
        reason="link_activation_pending_source_of_truth",
        safe_metadata={
            "source": "auth_patreon_link_confirm",
            "reason": "pending_initial_snapshot",
            "proof_consumed": True,
            "campaign_linked": bool(context.get("campaign_id")),
        },
    )


async def _classify_and_persist_initial_entitlement(
    *,
    config: Any,
    context: Mapping[str, Any],
    link_result: Any,
    user_id: str,
) -> PatreonSafeEntitlement:
    external_account_id = _string_field(link_result, "external_account_id") or _string_field(
        context,
        "external_account_id",
    )
    # The procedure returns the membership row it actually used: a relink gets a new
    # row, so the id derived from the proof is only a fallback.
    membership_id = _string_field(link_result, "membership_id") or _string_field(context, "membership_id")
    if not external_account_id or not membership_id:
        raise RuntimeError("Patreon link result is missing server-side IDs")

    payload = None
    should_close = False
    provider_client = None
    if _string_field(config, "creator_access_token"):
        try:
            provider_client, should_close = _patreon_client_from_config(config)
            payload = await _member_payload_for_consumed_proof(
                provider_client=provider_client,
                config=config,
                context=context,
            )
        except Exception:
            logger.warning("Patreon confirm could not refresh member evidence; falling back to pending snapshot")
            payload = None
        finally:
            if should_close and provider_client is not None and hasattr(provider_client, "close"):
                await _maybe_await(provider_client.close())

    id_secret = _string_field(config, "id_hmac_secret") or _string_field(config, "provider_sub_pepper")
    if payload is not None and id_secret:
        persistence = patreon_sync.PatreonMemberPersistenceContext(
            user_id=user_id,
            external_account_id=external_account_id,
            membership_id=membership_id,
            campaign_db_id=str(context["campaign_id"]),
            id_hmac_secret=id_secret,
            safe_metadata={"source": "auth_patreon_link_confirm", "proof_consumed": True},
        )
        result = patreon_sync.classify_and_maybe_persist_member_payload(
            payload,
            config=config,
            persistence=persistence,
            db_module=db_patreon,
            now=datetime.now(timezone.utc).replace(microsecond=0),
            source=_LINK_ACTIVATION_SOURCE,
            is_complete=True,
        )
        if result.persisted:
            return result.entitlement

    result = _pending_link_activation_result(config)
    _persist_pending_initial_snapshot(
        user_id=user_id,
        external_account_id=external_account_id,
        membership_id=membership_id,
        context=context,
        result=result,
    )
    return result.entitlement


async def _initial_entitlement_after_link(
    *,
    config: Any,
    context: Mapping[str, Any],
    link_result: Any,
    user_id: str,
    user_hash: str | None,
) -> PatreonSafeEntitlement:
    """First entitlement for a just-committed link; never undoes or hides the link.

    If the member read or snapshot write fails, the user still gets ``linked`` with
    a pending entitlement, and a source-of-truth resync is queued to fill it in.
    """

    try:
        return await _classify_and_persist_initial_entitlement(
            config=config,
            context=context,
            link_result=link_result,
            user_id=user_id,
        )
    except Exception:
        logger.warning("Patreon initial entitlement could not be stored after link; queueing resync")
    try:
        patreon_sync.enqueue_member_resync(
            user_id=user_id,
            user_hash=user_hash,
            job_type=patreon_sync.JOB_TYPE_USER_MEMBER,
            priority=1,
            source="link_activation",
            sanitized_metadata={"reason": "initial_entitlement_retry", "source": "auth_patreon_link_confirm"},
        )
    except Exception:
        logger.warning("Patreon post-link resync could not be queued")
    return _pending_link_activation_result(config).entitlement


def _call_db_create_proof(*, kwargs: dict[str, Any]) -> Any:
    method = getattr(db_patreon, "create_patreon_proof", None)
    if not callable(method):
        raise RuntimeError("Patreon proof DB wrapper is not available")
    return method(**kwargs)


async def _create_link_proof(
    *,
    request: Request,
    config: Any,
    email_config: Any,
    user_id: str,
    payload: Any,
    member: Mapping[str, Any],
    proof_email: str,
    searched_campaign_id: str | None,
) -> bool:
    """Create the proof row and queue its email; ``False`` when nothing was sent."""

    raw_member_id = _string_field(member, "id")
    raw_user_id = _relationship_id(member, "user")
    raw_campaign_id = _relationship_id(member, "campaign") or searched_campaign_id
    if not raw_member_id or not raw_user_id or not raw_campaign_id:
        return False
    if raw_campaign_id not in _configured_campaign_ids(config):
        return False

    id_pepper = _string_field(config, "id_hmac_secret")
    provider_pepper = _string_field(config, "provider_sub_pepper")
    email_pepper = _string_field(config, "email_hash_pepper")
    proof_pepper = _string_field(config, "proof_token_pepper")
    if not id_pepper or not provider_pepper or not email_pepper or not proof_pepper:
        return False

    # The membership row created at confirm references its campaign row.
    if not ensure_patreon_catalog_safely(config):
        return False

    patreon_user_hash, patreon_user_fingerprint = _hmac_identifier_or_none(
        raw_id=raw_user_id,
        kind="user",
        pepper=provider_pepper,
    )
    member_hash, member_fingerprint = _hmac_identifier_or_none(
        raw_id=raw_member_id,
        kind="member",
        pepper=id_pepper,
    )
    proof_email_hash = hash_patreon_email(email=proof_email, pepper=email_pepper)
    proof_email_masked = mask_patreon_email(proof_email)

    generated = generate_patreon_proof_token(
        ttl_seconds=int(getattr(config, "proof_token_ttl_seconds", 900) or 900),
        pepper=proof_pepper,
    )
    render_payload = _proof_render_payload(
        request=request,
        proof_token=generated.token,
        lookup_id=generated.lookup_id,
        recipient_masked=proof_email_masked,
        expires_at=generated.expires_at,
    )
    render_payload_ciphertext = encrypt_render_payload(render_payload, key=email_config.payload_key)

    kwargs = {
        "proof_id": f"plp-{secrets.token_hex(16)}",
        "user_id": user_id,
        "campaign_id": _campaign_db_id(raw_campaign_id, config),
        "patreon_user_id_hash": patreon_user_hash,
        "patreon_user_id_fingerprint": patreon_user_fingerprint,
        "member_id_hash": member_hash,
        "member_id_fingerprint": member_fingerprint,
        "proof_email_hash": proof_email_hash,
        "proof_email_masked": proof_email_masked,
        "lookup_id": generated.lookup_id,
        "token_hash": generated.token_hash,
        "token_fingerprint": generated.token_fingerprint,
        "expires_at": generated.expires_at,
        "email_message_id": f"em-{secrets.token_hex(16)}",
        "recipient_email": normalize_patreon_email(proof_email),
        "provider": getattr(email_config, "provider", "fake"),
        "provider_idempotency_key": f"patreon-link-proof-{generated.lookup_id}",
        "render_payload_ciphertext": render_payload_ciphertext,
        "created_ip_hash": hash_route_value(client_ip(request), email_config),
        "created_user_agent_hash": hash_route_value(user_agent(request), email_config),
        "metadata": {"source": "auth_patreon_link_request", "purpose": PATREON_PROOF_PURPOSE},
    }
    _ = payload  # Keep payload server-only and out of durable metadata/logs.
    await _maybe_await(_call_db_create_proof(kwargs=kwargs))
    return True


_PATREON_429_RESPONSE = {
    "description": (
        "Rate limited. The body keeps the same neutral shape plus `retry_after_seconds`; "
        "the `Retry-After` header is set."
    ),
}


@router.post(
    "/link/request",
    response_model=PatreonProofRequestResponse,
    status_code=202,
    response_description="Neutral accepted body, identical for every outcome.",
    responses={429: _PATREON_429_RESPONSE},
)
async def request_patreon_link(
    link_request: PatreonLinkRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> JSONResponse:
    """Start linking the signed-in user's Patreon membership by emailing a one-time proof link to the Patreon member's email.

    Patreon linking only proves membership for entitlements; it never signs anyone in
    or issues local tokens or cookies.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token`
    cookie) plus recent authentication: a sign-in, or an OAuth reauth of this session,
    within the recent-reauthentication window (refreshing the session does not renew
    it); otherwise `401` (`AUTH_1008`).

    **Request:** `application/json` `PatreonLinkRequest`. `explicit_user_intent` must be
    `true` and `patreon_email_hint` must be the email on the user's Patreon account;
    without either, nothing is sent. `confirm_email_match` is accepted but not used.
    Unknown fields are rejected with `400`.

    **Responses:**
    - `202` — the same neutral body for every outcome (proof emailed, no matching
      member, hidden email, feature disabled or provider error), so membership is never
      revealed.
    - `400` — body validation failed.
    - `401` — missing/invalid access token, or no recent authentication (`AUTH_1008`).
    - `429` — rate limited; `Retry-After` is set.

    \f
    Never returns proof, email, campaign, tier, provider, or local auth token material.
    """

    login_data = _load_current_session(credentials)
    user_id = _require_local_user(login_data)

    try:
        require_recent_reauthentication(
            user_id=user_id,
            access_token=credentials.credentials,
            session_id=_session_id_from_login_data(login_data),
            operation="patreon_link_request",
        )
    except Exception:
        await _record_patreon_link_rejection(
            request=request,
            user_id=user_id,
            event="proof_request_rejected",
            reason="recent_reauth_required",
            status_code=401,
        )
        raise

    rate_limited = await _check_link_request_rate_limit(
        request=request,
        user_id=user_id,
        email_hint=link_request.patreon_email_hint,
    )
    if rate_limited is not None:
        await _record_patreon_link_rejection(
            request=request,
            user_id=user_id,
            event="proof_request_rate_limited",
            reason="rate_limited",
            status_code=429,
        )
        return rate_limited

    # Spent on every request, before Patreon is contacted, so neither the budget nor
    # the timing depends on whether the hint belongs to a patron.
    rate_limited = await _check_proof_request_rate_limit(
        request=request,
        user_id=user_id,
        email_hint=link_request.patreon_email_hint,
    )
    if rate_limited is not None:
        await _record_patreon_link_rejection(
            request=request,
            user_id=user_id,
            event="proof_request_rate_limited",
            reason="rate_limited",
            status_code=429,
        )
        return rate_limited

    config = _load_config_or_none()
    if not link_request.explicit_user_intent or not _feature_ready_for_link_request(config):
        await _record_patreon_link_rejection(
            request=request,
            user_id=user_id,
            event="proof_request_rejected",
            reason="explicit_intent_or_feature_not_ready",
            details={"explicit_intent": bool(link_request.explicit_user_intent)},
        )
        return _proof_request_response()

    if not _is_consumer_session(login_data):
        await _record_patreon_link_rejection(
            request=request,
            user_id=user_id,
            event="proof_request_rejected",
            reason="non_consumer_account",
        )
        return _proof_request_response()

    provider_client = None
    should_close = False
    try:
        provider_client, should_close = _patreon_client_from_config(config)
        payload, member, searched_campaign_id = await _discover_member_for_link(
            provider_client=provider_client,
            config=config,
            email_hint=link_request.patreon_email_hint,
        )
        if member is None:
            await _record_patreon_link_rejection(
                request=request,
                user_id=user_id,
                event="proof_request_rejected",
                reason="member_not_available",
            )
            return _proof_request_response()

        proof_email = _member_email(member, payload)
        if not proof_email:
            await _record_patreon_link_rejection(
                request=request,
                user_id=user_id,
                event="proof_request_blocked_hidden_email",
                outcome="blocked_hidden_email",
                reason="patreon_email_hidden_or_null",
            )
            return _proof_request_response()

        email_config = load_email_config(validate_real_send_guard=True)
        created = await _create_link_proof(
            request=request,
            config=config,
            email_config=email_config,
            user_id=user_id,
            payload=payload,
            member=member,
            proof_email=proof_email,
            searched_campaign_id=searched_campaign_id,
        )
        if not created:
            await _record_patreon_link_rejection(
                request=request,
                user_id=user_id,
                event="proof_request_rejected",
                reason="member_context_incomplete",
            )
            return _proof_request_response()
        await record_patreon_link_activity(
            ActivityType.PATREON_LINK_PROOF_REQUESTED,
            event="proof_requested",
            outcome="proof_requested",
            request=request,
            user_id=user_id,
            status_code=202,
            reason="email_loop_proof_enqueued",
            details={"proof_delivery": "queued"},
        )
        return _proof_request_response()
    except PatreonRateLimitExceeded as exc:
        await _record_patreon_link_rejection(
            request=request,
            user_id=user_id,
            event="proof_request_rate_limited",
            reason="rate_limited",
            status_code=429,
            details={
                "rate_limit_bucket": getattr(exc, "bucket", "link_request"),
                "retry_after_seconds": _retry_after_from_rate_limit(exc),
            },
        )
        return _rate_limited_public_response(_PROOF_REQUEST_SURFACE, exc)
    except Exception:
        # Provider, config, and DB failures must not reveal membership, email,
        # proof, campaign/tier, credential, or link state to the caller.
        logger.warning("Patreon link proof request was not completed; returning generic response")
        await _record_patreon_link_rejection(
            request=request,
            user_id=user_id,
            event="proof_request_rejected",
            reason="proof_request_failed",
        )
        return _proof_request_response()
    finally:
        if should_close and provider_client is not None and hasattr(provider_client, "close"):
            await _maybe_await(provider_client.close())


@router.post(
    "/link/confirm",
    response_model=PatreonLinkStatusResponse,
    status_code=202,
    response_description="Neutral result (`link_status: pending`): nothing was linked.",
    responses={
        200: {
            "model": PatreonLinkStatusResponse,
            "description": "Proof consumed and membership linked: `link_status` is `linked` and `entitlement` is set.",
        },
        429: _PATREON_429_RESPONSE,
    },
)
async def confirm_patreon_link(
    confirm_request: PatreonProofConfirmRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> JSONResponse:
    """Consume the emailed Patreon proof and link that membership to the signed-in user.

    This is not a login or OAuth callback and issues no local tokens or cookies.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token`
    cookie) plus recent authentication (a sign-in, or an OAuth reauth of this
    session, within the recent-reauthentication window; refreshing the session does not renew it); otherwise `401`
    (`AUTH_1008`). The proof must have been requested by the same user.

    **Request:** `application/json` `PatreonProofConfirmRequest` with `token`
    (`<lookup_id>.<secret>` from the emailed link) or `lookup_id` + `secret`.
    `explicit_user_intent` is accepted but not checked. Unknown fields are rejected with
    `400`.

    **Responses:**
    - `200` — linked; `link_status: linked` plus the safe `entitlement` summary.
    - `202` — neutral `link_status: pending` for every unsuccessful outcome (malformed,
      unknown, expired or reused proof, another user's proof, conflicting link, feature
      disabled).
    - `400` — body validation failed.
    - `401` — missing/invalid access token, or no recent authentication (`AUTH_1008`).
    - `429` — rate limited; `Retry-After` is set.
    """

    login_data = _load_current_session(credentials)
    user_id = _require_local_user(login_data)

    try:
        require_recent_reauthentication(
            user_id=user_id,
            access_token=credentials.credentials,
            session_id=_session_id_from_login_data(login_data),
            operation="patreon_link_confirm",
        )
    except Exception:
        await _record_patreon_link_rejection(
            request=request,
            user_id=user_id,
            event="proof_confirm_rejected",
            reason="recent_reauth_required",
            status_code=401,
        )
        raise

    parts = _proof_parts_from_request(confirm_request)
    lookup_id = parts[0] if parts else confirm_request.lookup_id
    rate_limited = await _check_proof_consume_rate_limit(
        request=request,
        user_id=user_id,
        lookup_id=lookup_id,
    )
    if rate_limited is not None:
        await _record_patreon_link_rejection(
            request=request,
            user_id=user_id,
            event="proof_consume_rate_limited",
            reason="rate_limited",
            status_code=429,
        )
        return rate_limited

    config = _load_config_or_none()
    if parts is None or not _feature_ready_for_link_confirm(config):
        await _record_patreon_link_rejection(
            request=request,
            user_id=user_id,
            event="proof_confirm_rejected",
            reason="malformed_or_feature_not_ready",
        )
        return _generic_confirm_response()

    lookup_id, secret = parts
    proof_pepper = _string_field(config, "proof_token_pepper")
    if not proof_pepper:
        await _record_patreon_link_rejection(
            request=request,
            user_id=user_id,
            event="proof_confirm_rejected",
            reason="feature_not_ready",
        )
        return _generic_confirm_response()

    try:
        token_hash = hash_patreon_proof_token(
            lookup_id=lookup_id,
            secret=secret,
            pepper=proof_pepper,
            purpose=PATREON_PROOF_PURPOSE,
        )
        consumed_ip_hash, consumed_user_agent_hash = _route_hashes_for_consume(request)
        consumed = await _maybe_await(
            _call_db_consume_proof(
                kwargs={
                    "lookup_id": lookup_id,
                    "token_hash": token_hash,
                    "consumed_ip_hash": consumed_ip_hash,
                    "consumed_user_agent_hash": consumed_user_agent_hash,
                    "user_id": user_id,
                }
            )
        )
        if _consume_status(consumed) != "consumed":
            await _record_patreon_link_rejection(
                request=request,
                user_id=user_id,
                event="proof_confirm_rejected",
                reason="proof_not_consumed",
            )
            return _generic_confirm_response()

        await record_patreon_link_activity(
            ActivityType.PATREON_LINK_PROOF_CONSUMED,
            event="proof_consumed",
            outcome="proof_consumed",
            request=request,
            user_id=user_id,
            status_code=202,
            reason="proof_consumed_once",
            details={"proof_consumed": True},
        )

        context = _proof_context_from_consume(consumed)
        if not _proof_context_complete(context):
            await _record_patreon_link_rejection(
                request=request,
                user_id=user_id,
                event="proof_confirm_rejected",
                reason="proof_context_incomplete",
            )
            return _generic_confirm_response()

        conflict = await _maybe_await(
            _call_db_check_conflict(
                user_id=user_id,
                provider_sub_hash=context["provider_sub_hash"],
            )
        )
        if not _conflict_clear(conflict):
            outcome, reason = _conflict_activity_outcome(conflict)
            await _record_patreon_link_rejection(
                request=request,
                user_id=user_id,
                event=outcome,
                outcome=outcome,
                reason=reason,
            )
            return _generic_confirm_response()

        link_result = await _maybe_await(_call_db_link_account(user_id=user_id, context=context))
        # From here on the link is committed: report it as linked even if the first
        # entitlement read fails (that read is retried by a queued resync).
        entitlement = await _initial_entitlement_after_link(
            config=config,
            context=context,
            link_result=link_result,
            user_id=user_id,
            user_hash=_string_field(login_data, "user_hash"),
        )
        await record_patreon_link_activity(
            ActivityType.PATREON_LINKED,
            event="linked",
            outcome="linked",
            request=request,
            user_id=user_id,
            status_code=200,
            reason="proof_confirmed_and_linked",
            details={"link_status": constants.PATREON_LINK_STATUS_LINKED},
        )
        return _link_status_response(
            status_code=200,
            message=_LINK_CONFIRMED_MESSAGE,
            link_status=constants.PATREON_LINK_STATUS_LINKED,
            entitlement=entitlement,
        )
    except PatreonRateLimitExceeded as exc:
        await _record_patreon_link_rejection(
            request=request,
            user_id=user_id,
            event="proof_consume_rate_limited",
            reason="rate_limited",
            status_code=429,
            details={
                "rate_limit_bucket": getattr(exc, "bucket", "proof_consume"),
                "retry_after_seconds": _retry_after_from_rate_limit(exc),
            },
        )
        return _rate_limited_public_response(_CONFIRM_SURFACE, exc)
    except Exception:
        # Keep provider/link/proof state opaque. Never log raw token, email,
        # provider IDs, HMAC material, fingerprints, or another user's state.
        logger.warning("Patreon link proof confirm was not completed; returning generic response")
        await _record_patreon_link_rejection(
            request=request,
            user_id=user_id,
            event="proof_confirm_rejected",
            reason="confirm_failed",
        )
        return _generic_confirm_response()


@router.get(
    "/link/status",
    response_model=PatreonLinkStatusResponse,
    status_code=200,
    responses={429: _PATREON_429_RESPONSE},
)
async def get_patreon_link_status(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> JSONResponse:
    """Return the signed-in user's Patreon link status and safe entitlement summary.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token`
    cookie); no recent authentication needed. Only the caller's own state is readable.

    **Responses:**
    - `200` — `link_status` (`none`, `pending`, `linked`, `unlinked`, `revoked` or
      `blocked`) and `entitlement`. If the status cannot be read, it degrades to `none`
      with the free entitlement instead of failing.
    - `401` — missing or invalid access token.
    - `429` — rate limited; `Retry-After` is set.

    \f
    DB rows are normalized through the safe DTO mapper and serialized with
    ``model_dump_safe()``.
    """

    login_data = _load_current_session(credentials)
    user_id = _require_local_user(login_data)

    rate_limited = await _check_status_rate_limit(request=request, user_id=user_id)
    if rate_limited is not None:
        return rate_limited

    try:
        row = await _call_db_get_link_status(
            user_hash=_string_field(login_data, "user_hash"),
        )
        link_status, entitlement = _status_components_from_row(row)
        return _link_status_response(
            status_code=200,
            message=_GENERIC_STATUS_MESSAGE,
            link_status=link_status,
            entitlement=entitlement,
        )
    except PatreonRateLimitExceeded as exc:
        return _rate_limited_public_response(_STATUS_SURFACE, exc)
    except Exception:
        # Keep link/provider state opaque and do not log DB rows, provider IDs,
        # emails, fingerprints, hash prefixes, or audit details.
        logger.warning("Patreon link status read was not completed; returning safe response")
        entitlement = _default_status_entitlement()
        return _link_status_response(
            status_code=200,
            message=_GENERIC_STATUS_MESSAGE,
            link_status=entitlement.link_status,
            entitlement=entitlement,
        )


@router.delete(
    "/link",
    response_model=PatreonUnlinkResponse,
    status_code=200,
    responses={
        202: {
            "model": PatreonUnlinkResponse,
            "description": "The unlink could not be completed; neutral body with `link_status: none`.",
        },
        429: _PATREON_429_RESPONSE,
    },
)
async def unlink_patreon_link(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> JSONResponse:
    """Soft-unlink the signed-in user's Patreon membership.

    Local sessions, tokens, cookies and API keys are not affected.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token`
    cookie) plus recent authentication (a sign-in, or an OAuth reauth of this
    session, within the recent-reauthentication window; refreshing the session does not renew it); otherwise `401`
    (`AUTH_1008`). Only the caller's own link can be removed.

    **Request:** no body.

    **Responses:**
    - `200` — unlinked; resulting `link_status` and `entitlement`.
    - `202` — the unlink could not be completed; neutral body.
    - `401` — missing/invalid access token, or no recent authentication (`AUTH_1008`).
    - `429` — rate limited; `Retry-After` is set.
    """

    login_data = _load_current_session(credentials)
    user_id = _require_local_user(login_data)

    try:
        require_recent_reauthentication(
            user_id=user_id,
            access_token=credentials.credentials,
            session_id=_session_id_from_login_data(login_data),
            operation="patreon_unlink",
        )
    except Exception:
        await _record_patreon_link_rejection(
            request=request,
            user_id=user_id,
            event="unlink_rejected",
            reason="recent_reauth_required",
            status_code=401,
        )
        raise

    rate_limited = await _check_unlink_rate_limit(request=request, user_id=user_id)
    if rate_limited is not None:
        await _record_patreon_link_rejection(
            request=request,
            user_id=user_id,
            event="unlink_rate_limited",
            reason="rate_limited",
            status_code=429,
        )
        return rate_limited

    try:
        result = await _maybe_await(_call_db_unlink_account(user_id=user_id))
        link_status, entitlement = _safe_unlink_entitlement_from_row(result)
        await record_patreon_link_activity(
            ActivityType.PATREON_UNLINKED,
            event="unlinked",
            outcome="unlinked",
            request=request,
            user_id=user_id,
            status_code=200,
            reason="user_requested_unlink",
            details={"link_status": link_status},
        )
        return _unlink_response(
            status_code=200,
            message=_LINK_UNLINKED_MESSAGE,
            link_status=link_status,
            entitlement=entitlement,
        )
    except PatreonRateLimitExceeded as exc:
        await _record_patreon_link_rejection(
            request=request,
            user_id=user_id,
            event="unlink_rate_limited",
            reason="rate_limited",
            status_code=429,
            details={
                "rate_limit_bucket": getattr(exc, "bucket", "unlink"),
                "retry_after_seconds": _retry_after_from_rate_limit(exc),
            },
        )
        return _rate_limited_public_response(_UNLINK_SURFACE, exc)
    except Exception:
        # Keep provider/link state opaque and do not log DB rows, provider IDs,
        # emails, fingerprints, hash prefixes, audit details, or session data.
        logger.warning("Patreon unlink was not completed; returning generic response")
        await _record_patreon_link_rejection(
            request=request,
            user_id=user_id,
            event="unlink_rejected",
            reason="unlink_failed",
        )
        entitlement = _default_status_entitlement()
        return _unlink_response(
            status_code=202,
            message=_GENERIC_UNLINK_MESSAGE,
            link_status=entitlement.link_status,
            entitlement=entitlement,
        )


def _route_path_with_prefix(path: Any) -> str:
    route_path = str(path or "").rstrip("/") or "/"
    prefix = str(getattr(router, "prefix", "") or "").rstrip("/")
    if prefix and not route_path.startswith(prefix):
        route_path = f"{prefix}{route_path if route_path.startswith('/') else '/' + route_path}"
    return route_path.rstrip("/") or "/"


def _assert_phase5_route_hardening() -> None:
    """Fail fast if this link-only router drifts into login or unsafe DTOs."""

    assert_patreon_response_model_allow_lists()

    registered_paths = {
        _route_path_with_prefix(getattr(route, "path", ""))
        for route in getattr(router, "routes", [])
    }
    forbidden_paths = sorted(registered_paths & _FORBIDDEN_PATREON_AUTH_ROUTES)
    if forbidden_paths:
        raise RuntimeError(f"Patreon login/OAuth routes are forbidden: {forbidden_paths}")

    unexpected_paths = sorted(
        path
        for path in registered_paths
        if path.startswith("/auth/patreon/") and path not in _ALLOWED_PHASE5_PATREON_ROUTES
    )
    if unexpected_paths:
        raise RuntimeError(f"Unexpected Patreon auth routes in Phase 5 router: {unexpected_paths}")

    for route in getattr(router, "routes", []):
        response_model = getattr(route, "response_model", None)
        if response_model is None:
            continue
        safe_fields = frozenset(getattr(response_model, "safe_fields", frozenset()))
        if not safe_fields:
            raise RuntimeError(f"{response_model.__name__} is missing Patreon safe_fields")
        model_fields = frozenset(getattr(response_model, "model_fields", frozenset()))
        forbidden_model_fields = sorted(
            str(field).lower().replace("-", "_")
            for field in model_fields
            if str(field).lower().replace("-", "_") in _FORBIDDEN_RESPONSE_KEYS_NORMALIZED
        )
        if forbidden_model_fields:
            raise RuntimeError(
                f"{response_model.__name__} exposes forbidden Patreon response fields: {forbidden_model_fields}"
            )

    forbidden_email_activation_globals = sorted(
        name for name in _FORBIDDEN_LOCAL_EMAIL_ACTIVATION_GLOBALS if name in globals()
    )
    if forbidden_email_activation_globals:
        raise RuntimeError(
            "Patreon link routes must not import or call local email activation seams: "
            f"{forbidden_email_activation_globals}"
        )


_assert_phase5_route_hardening()


__all__ = [
    "router",
    "capture_patreon_link_audit",
    "record_patreon_link_activity",
    "request_patreon_link",
    "confirm_patreon_link",
    "get_patreon_link_status",
    "unlink_patreon_link",
]
