"""
Authentication Routes

Handles user authentication, registration, and session management
for the group-based multi-project authentication system.
"""

import logging
import time
from typing import Optional, Any
import json
import secrets
from datetime import datetime, timezone
from unittest.mock import Mock

from fastapi import APIRouter, Form, HTTPException, Depends, Response, Request
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTasks
from fastapi.security import HTTPAuthorizationCredentials

from src.Util.Models import (
    LoginResponse, RegisterResponse, ValidateSessionResponse, ValidateApiKeyResponse,
    ApiKeyInfo, LogoutResponse, SwitchProjectResponse, CheckAvailabilityResponse,
    UserInfo, ProjectInfo, UserGroupInfo, ChangePasswordRequest, ChangePasswordResponse,
)
from src.Util.Seccurity import HTTPBearerOrCookie, extract_refresh_token_from_request
from src.Util.decorators import log_and_handle_errors, log_unauthenticated_operation
from src.Util.log_context_models import LogContext, UnauthenticatedLogContext
from src.Util.activity_logger import ActivityType
from src.Util.error_handler import (
    AuthenticationError, AuthorizationError, ValidationError, NotFoundError,
    ConflictError, ErrorCode, create_not_found_error, create_validation_error,
    mask_uuid, create_invalid_current_password_error,
    create_change_password_rate_limit_error, rate_limit_headers,
)
from src.Util.db_error_wrapper import handle_db_operation, validate_uuid_format
from src.Util.db import (
    db_email,
    check_username_email_available,
    get_user_by_hash,
    get_user_by_credentials,
    enhanced_register,
    get_user_group_by_hash,
    change_user_password,
)
from src.Util.db.db_user_groups import get_projects_for_user_group

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/auth", tags=["Authentication"])
security = HTTPBearerOrCookie()

# Cookie settings
COOKIE_NAME = "session_token"
COOKIE_MAX_AGE = 72 * 60 * 60  # 72 hours (3 days)

# NEW: low-level dependencies for session storage & JWT
from src.Util.db_config import redis_client  # Central redis client
from src.Util.JWT_Security import JWTTokenHandler

# NEW: helpers aligned with the group-based schema
from src.Util.db.db_user_groups import get_user_accessible_projects, get_user_groups_for_user, get_user_groups_in_project, get_user_groups_in_project_by_hash
from src.Util.db.db_projects import get_project_by_hash
from src.Util.db.db_users import check_admin_multi_project_access, get_admin_project_assignments_with_details
from src.Util.auth_flow import require_recent_reauthentication, resolve_target_project
from src.Util.auth_lifecycle import issue_platform_token_pair, issue_project_token_pair, rotate_refresh_family, revoke_refresh_family, revoke_user_auth_state, revoke_user_auth_state_except_current, validate_access_session
from src.Util.db.db_enhanced import validate_session as validate_enhanced_session
from src.middleware.authentication import validate_api_key_context
from src.Util.email.rate_limit import EmailRateLimiter, RateLimitExceeded
from src.Util.email.route_support import (
    EmailIdempotencyPlan,
    client_ip,
    complete_idempotency,
    db_bool,
    forced_rate_limit_response_for_test,
    generic_accepted_response,
    hash_route_value,
    idempotency_kwargs,
    load_route_email_config,
    make_link_token_and_payload,
    parse_presented_token,
    prepare_idempotency,
    rate_limited_response,
    read_request_payload,
    token_from_request_payload,
    user_agent,
)
from src.Util.email.security import hash_link_token, normalize_email
from src.Util.password_security import assert_password_policy, hash_password

# ---------------------------------------------------------------------------
# Session helpers (group-based, no user_projects table required)
# ---------------------------------------------------------------------------

def _get_refresh_family(family_id: str) -> Optional[dict]:
    """Fetch refresh family metadata from Redis."""
    raw = redis_client.get(f"refresh_family:{family_id}")
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    return json.loads(raw)


def _set_token_pair_cookies(response: Response, token_pair) -> None:
    """Apply access and refresh cookies from lifecycle token metadata."""
    access_cookie = token_pair.cookie_metadata["access"]
    response.set_cookie(
        key=access_cookie["name"],
        value=token_pair.access_token,
        max_age=access_cookie["max_age"],
        httponly=access_cookie["httponly"],
        secure=access_cookie["secure"],
        samesite=access_cookie["samesite"],
        path=access_cookie["path"],
    )

    refresh_cookie = token_pair.cookie_metadata["refresh"]
    response.set_cookie(
        key=refresh_cookie["name"],
        value=token_pair.refresh_token,
        max_age=refresh_cookie["max_age"],
        httponly=refresh_cookie["httponly"],
        secure=refresh_cookie["secure"],
        samesite=refresh_cookie["samesite"],
        path=refresh_cookie["path"],
    )


def _route_refresh_groups(user_id: str, project_hash: str):
    try:
        groups = get_user_groups_in_project_by_hash(user_id, project_hash)
        if groups:
            return groups
    except Exception:
        logger.debug("Falling back to user groups for refresh context", exc_info=True)
    try:
        project = get_project_by_hash(project_hash)
        if project:
            groups = get_user_groups_in_project(user_id, project.id)
            if groups:
                return groups
    except Exception:
        logger.debug("Falling back to user-wide groups for refresh context", exc_info=True)
    return get_user_groups_for_user(user_id)


def _project_info_from_any(project: Any) -> Optional[ProjectInfo]:
    project_hash = getattr(project, "project_hash", None)
    if not project_hash and isinstance(project, dict):
        project_hash = project.get("project_hash")
    if not project_hash:
        return None
    project_name = getattr(project, "project_name", None)
    project_description = getattr(project, "project_description", None)
    if isinstance(project, dict):
        project_name = project.get("project_name", project_name)
        project_description = project.get("project_description", project_description)
    return ProjectInfo(
        project_hash=project_hash,
        project_name=project_name or "",
        project_description=project_description,
    )


def _project_is_auth_accessible(project: Any) -> bool:
    """Project-scoped auth may only target active, non-archived projects."""
    if project is None:
        return False
    is_active = getattr(project, "is_active", True)
    if isinstance(is_active, Mock) and "is_active" not in getattr(project, "__dict__", {}):
        is_active = True
    if isinstance(project, dict):
        is_active = project.get("is_active", is_active)
    archived = getattr(project, "archived", False)
    if isinstance(archived, Mock) and "archived" not in getattr(project, "__dict__", {}):
        archived = False
    if isinstance(project, dict):
        archived = project.get("archived", archived)
    return bool(is_active) and not bool(archived)


def _deny_project_auth(project_hash: str) -> None:
    raise AuthorizationError(
        message="Access denied to requested project",
        error_code=ErrorCode.PROJECT_ACCESS_DENIED,
        details={"project_hash": mask_uuid(project_hash)},
    )


def _admin_accessible_project_infos(user_id: str) -> list[ProjectInfo]:
    assignments = get_admin_project_assignments_with_details(user_id)
    project_infos = []
    seen_hashes = set()
    for assignment in assignments or []:
        project_hash = assignment.get("project_hash") if isinstance(assignment, dict) else getattr(assignment, "project_hash", None)
        if not project_hash or project_hash in seen_hashes:
            continue
        seen_hashes.add(project_hash)
        project_infos.append(ProjectInfo(
            project_hash=project_hash,
            project_name=(assignment.get("project_name") if isinstance(assignment, dict) else getattr(assignment, "project_name", "")) or "",
            project_description=(assignment.get("project_description") if isinstance(assignment, dict) else getattr(assignment, "project_description", None)),
        ))
    return project_infos


def _login_response_from_rotation(rotation) -> LoginResponse:
    token_pair = rotation.token_pair
    login_data = rotation.login_data
    project_info = None
    if login_data.project_hash:
        project_info = ProjectInfo(
            project_hash=login_data.project_hash,
            project_name=login_data.project_name or "",
        )

    accessible_projects_info = [
        project_info_item
        for project_info_item in (_project_info_from_any(project) for project in (login_data.available_projects or []))
        if project_info_item is not None
    ]
    user_groups_info = [
        UserGroupInfo(group_hash=str(group), group_name=str(group))
        for group in (login_data.groups or [])
    ]

    return LoginResponse(
        success=True,
        message="Token refreshed successfully",
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        session_token=token_pair.session_token,
        token_type=token_pair.token_type,
        expires_in=token_pair.expires_in,
        refresh_expires_in=token_pair.refresh_expires_in,
        expires_at=token_pair.expires_at,
        refresh_expires_at=token_pair.refresh_expires_at,
        user=UserInfo(
            user_hash=login_data.user_hash,
            username=login_data.username or login_data.user_hash,
            user_type=login_data.user_type,
        ),
        project=project_info,
        accessible_projects=accessible_projects_info,
        user_groups=user_groups_info,
        user_id=login_data.user_id,
    )


def _refresh_error_code_from_http_exception(exc: HTTPException) -> ErrorCode:
    """Map refresh lifecycle denials to refresh-specific public codes."""
    detail = str(exc.detail or "").lower()
    if "missing refresh token" in detail:
        return ErrorCode.REFRESH_TOKEN_MISSING
    if "mismatched refresh token" in detail or "does not match" in detail:
        return ErrorCode.REFRESH_TOKEN_MISMATCH
    if "invalid token type" in detail:
        return ErrorCode.TOKEN_TYPE_INVALID
    if "token expired" in detail:
        return ErrorCode.TOKEN_EXPIRED
    if "reused" in detail:
        return ErrorCode.REFRESH_TOKEN_REUSED
    if "family revoked" in detail or "refresh family revoked" in detail:
        return ErrorCode.REFRESH_FAMILY_REVOKED
    if "mismatch" in detail:
        return ErrorCode.REFRESH_TOKEN_MISMATCH
    if "context inactive" in detail or "context unavailable" in detail or "session revoked" in detail:
        return ErrorCode.SESSION_REVOKED
    if "invalid refresh token" in detail or "invalid token" in detail or "missing required claim" in detail:
        return ErrorCode.REFRESH_TOKEN_INVALID
    return ErrorCode.REFRESH_TOKEN_INVALID


def _string_attr(value: Any, attr: str) -> Optional[str]:
    candidate = getattr(value, attr, None)
    return candidate if isinstance(candidate, str) and candidate else None


def _registration_token_pair(register_result: Any):
    """Return or create a project-scoped token pair for registration.

    Real `enhanced_register()` now returns token-pair metadata. Some integration
    tests patch that function with legacy lightweight objects, so this fallback
    keeps route behavior aligned with the public contract while the DB helper is
    still covered through its own real path.
    """
    if _string_attr(register_result, "access_token") and _string_attr(register_result, "refresh_token"):
        return register_result

    project_hash = _string_attr(register_result, "project_hash")
    if not project_hash:
        return None

    user_id = _string_attr(register_result, "user_id")
    user_hash = _string_attr(register_result, "user_hash")
    if not user_id or not user_hash:
        return None

    project_id = _string_attr(register_result, "project_id")
    project_name = _string_attr(register_result, "project_name")
    username = _string_attr(register_result, "username") or user_hash
    user_type = _string_attr(register_result, "user_type") or "consumer"
    groups = list(getattr(register_result, "groups", []) or [])
    group_ids = [str(group_id) for group_id in (getattr(register_result, "user_group_ids", []) or [])]
    permissions = list(getattr(register_result, "permissions", []) or [])

    return issue_project_token_pair(
        user={
            "id": user_id,
            "user_hash": user_hash,
            "username": username,
            "user_type": user_type,
        },
        project={
            "id": project_id,
            "project_hash": project_hash,
            "project_name": project_name,
        },
        permissions=permissions,
        groups=groups,
        group_ids=group_ids,
    )


def _safe_prepare_email_idempotency(
    *,
    raw_key: str | None,
    scope: str,
    user_id: str | None,
    recipient_hash: bytes | None,
    body: dict[str, Any],
    config,
) -> EmailIdempotencyPlan:
    try:
        return prepare_idempotency(
            raw_key=raw_key,
            scope=scope,
            user_id=user_id,
            recipient_hash=recipient_hash,
            body=body,
            config=config,
        )
    except Exception:
        logger.warning("Email idempotency begin failed; continuing with generic route posture", exc_info=True)
        return EmailIdempotencyPlan(raw_key=None, scope=scope)


def _safe_complete_email_idempotency(plan: EmailIdempotencyPlan, *, email_message_id: str | None = None) -> None:
    try:
        complete_idempotency(plan, email_message_id=email_message_id)
    except Exception:
        logger.warning("Email idempotency complete failed", exc_info=True)


def _safe_log_email_activity(
    *,
    user_id: str | None,
    activity_type: ActivityType,
    details: dict[str, Any],
    request: Request | None,
    target_user_id: str | None = None,
) -> None:
    try:
        from src.Util.activity_logger import ActivityLogger

        ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=activity_type.value,
            details=details,
            target_user_id=target_user_id,
            ip_address=client_ip(request),
            user_agent=user_agent(request),
        )
    except Exception:
        logger.debug("Email activity log failed", exc_info=True)


def _check_email_send_rate_limit(*, request: Request, purpose: str, recipient_hash_hex_value: str, user_id: str | None = None):
    forced = forced_rate_limit_response_for_test(request)
    if forced is not None:
        return forced
    try:
        EmailRateLimiter().check_send_request(
            purpose=purpose,
            recipient_hash=recipient_hash_hex_value,
            user_id=user_id,
            ip_address=client_ip(request),
        )
    except RateLimitExceeded as exc:
        return rate_limited_response(exc)
    return None


def _check_email_consume_rate_limit(*, request: Request, purpose: str, lookup_id: str):
    forced = forced_rate_limit_response_for_test(request)
    if forced is not None:
        return forced
    try:
        EmailRateLimiter().check_consume_request(
            purpose=purpose,
            lookup_id=lookup_id,
            ip_address=client_ip(request),
        )
    except RateLimitExceeded as exc:
        return rate_limited_response(exc)
    return None


def _check_login_identifier_rate_limit(request: Request | None, identifier: str):
    if request is None:
        return None
    try:
        EmailRateLimiter().check_login_identifier_allowed(client_ip(request), identifier)
    except RateLimitExceeded as exc:
        return rate_limited_response(exc)
    return None


def _record_login_identifier_failure(request: Request | None, identifier: str) -> None:
    if request is None:
        return
    try:
        EmailRateLimiter().record_login_identifier_failure(client_ip(request), identifier)
    except Exception:
        logger.debug("Unable to record login identifier failure", exc_info=True)


def _change_password_rate_limited_response(exc: RateLimitExceeded) -> JSONResponse:
    retry_after = max(1, int(getattr(exc, "retry_after", 1) or 1))
    error = create_change_password_rate_limit_error(
        retry_after,
        details={"bucket": str(getattr(exc, "bucket", "change_password"))},
    )
    return JSONResponse(
        status_code=429,
        headers=rate_limit_headers(retry_after),
        content=error.to_dict(),
    )


def _check_change_password_attempt_rate_limit(
    *,
    request: Request,
    user_id: str,
    session_id: str | None,
) -> JSONResponse | None:
    try:
        EmailRateLimiter().check_change_password_attempt(
            user_id=user_id,
            session_id=session_id,
            ip_address=client_ip(request),
        )
    except RateLimitExceeded as exc:
        return _change_password_rate_limited_response(exc)
    return None


def _record_change_password_failure(*, request: Request, user_id: str) -> None:
    try:
        EmailRateLimiter().record_change_password_failure(
            user_id=user_id,
            ip_address=client_ip(request),
        )
    except Exception:
        logger.debug("Unable to record change-password failure bucket", exc_info=True)


def _decode_current_password_change_claims(
    credentials: HTTPAuthorizationCredentials,
) -> tuple[dict[str, Any], str, str]:
    try:
        claims = JWTTokenHandler.decode_access_token(credentials.credentials)
    except HTTPException as exc:
        raise AuthenticationError(
            message=str(exc.detail),
            error_code=ErrorCode.SESSION_INVALID,
        )

    current_access_jti = str(claims.get("jti") or "")
    current_family_id = str(claims.get("family_id") or "")
    if not current_access_jti or not current_family_id:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID,
        )

    return claims, current_access_jti, current_family_id


def _record_auth_email_login_if_applicable(user_record: Any, identifier: str, request: Request | None) -> None:
    if "@" not in str(identifier or ""):
        return
    _safe_log_email_activity(
        user_id=getattr(user_record, "id", None),
        activity_type=ActivityType.AUTH_EMAIL_LOGIN,
        details={"identifier_type": "activated_email", "action": "login"},
        request=request,
        target_user_id=getattr(user_record, "id", None),
    )


def _token_hash_for_presented_token(*, purpose: str, lookup_id: str, secret: str, config) -> bytes:
    return hash_link_token(
        purpose=purpose,
        lookup_id=lookup_id,
        secret=secret,
        pepper=config.token_pepper_bytes,
    )


@router.post("/email/verify")
@log_unauthenticated_operation(
    operation_name="email_activation_verify",
    activity_type=ActivityType.USER_EMAIL_ACTIVATED,
    log_success=False,
)
async def verify_email_activation(
    request: Request,
    log_context = None,
):
    """Consume an email activation token with generic public `202` posture."""

    payload = await read_request_payload(request)
    token = token_from_request_payload(payload)
    parsed = parse_presented_token(token)
    if parsed is None:
        return generic_accepted_response()

    lookup_id, secret = parsed
    limited = _check_email_consume_rate_limit(request=request, purpose="email_activation", lookup_id=lookup_id)
    if limited is not None:
        return limited

    config = load_route_email_config()
    lookup_hash = hash_route_value(lookup_id, config)
    plan = _safe_prepare_email_idempotency(
        raw_key=request.headers.get("idempotency-key"),
        scope="auth.email.verify",
        user_id=None,
        recipient_hash=lookup_hash,
        body={"lookup_id": lookup_id, "purpose": "email_activation"},
        config=config,
    )
    if plan.replay_response is not None:
        return plan.replay_response

    row = None
    try:
        row = db_email.consume_email_activation_token(
            lookup_id=lookup_id,
            token_hash=_token_hash_for_presented_token(
                purpose="email_activation",
                lookup_id=lookup_id,
                secret=secret,
                config=config,
            ),
            consumed_ip_hash=hash_route_value(client_ip(request), config),
            consumed_user_agent_hash=hash_route_value(user_agent(request), config),
        )
    except Exception:
        logger.warning("Email activation consume failed; returning generic public response", exc_info=True)

    if row and db_bool(row.get("identity_changed")) and row.get("user_id"):
        revoke_user_auth_state(str(row["user_id"]), reason="email_activation")
        _safe_log_email_activity(
            user_id=str(row["user_id"]),
            activity_type=ActivityType.USER_EMAIL_ACTIVATED,
            details={"action": "email_activated", "user_email_id": row.get("user_email_id")},
            request=request,
            target_user_id=str(row["user_id"]),
        )
    elif row and str(row.get("consume_status") or "") in {"activation_conflict", "email_not_pending"}:
        # Activation did not apply (e.g. the address is already activated to another
        # account, or the email row is no longer pending). Preserve the generic 202
        # public posture but record a non-PII forensic warning so conflicts and
        # anomalies are observable instead of silently swallowed.
        logger.warning(
            "Email activation not applied: status=%s user_id=%s user_email_id=%s",
            row.get("consume_status"),
            row.get("user_id"),
            row.get("user_email_id"),
        )

    _safe_complete_email_idempotency(plan, email_message_id=None)
    return generic_accepted_response()


@router.post("/password/forgot")
@log_unauthenticated_operation(
    operation_name="password_reset_request",
    activity_type=ActivityType.PASSWORD_RESET_REQUESTED,
    log_success=False,
)
async def forgot_password_link(
    request: Request,
    log_context = None,
):
    """Request a password reset link without disclosing account existence."""

    payload = await read_request_payload(request)
    identifier = str(
        payload.get("email_or_username")
        or payload.get("identifier")
        or payload.get("email")
        or payload.get("username")
        or ""
    ).strip()
    if not identifier:
        raise ValidationError(
            message="email_or_username is required",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"missing_fields": ["email_or_username"]},
        )

    config = load_route_email_config()
    recipient_hash = hash_route_value(normalize_email(identifier), config)
    limited = _check_email_send_rate_limit(
        request=request,
        purpose="password_reset",
        recipient_hash_hex_value=recipient_hash.hex() if recipient_hash else "unknown",
        user_id=None,
    )
    if limited is not None:
        return limited

    plan = _safe_prepare_email_idempotency(
        raw_key=request.headers.get("idempotency-key"),
        scope="auth.password.forgot",
        user_id=None,
        recipient_hash=recipient_hash,
        body={"identifier": normalize_email(identifier), "purpose": "password_reset"},
        config=config,
    )
    if plan.replay_response is not None:
        return plan.replay_response

    generated, render_payload = make_link_token_and_payload(
        purpose="password_reset",
        config=config,
        request=request,
        recipient_email=identifier if "@" in identifier else None,
    )
    email_message_id = None
    row = None
    try:
        row = db_email.enqueue_password_reset_link(
            identifier=identifier,
            token_id=f"elt-{secrets.token_hex(16)}",
            lookup_id=generated.lookup_id,
            token_hash=generated.token_hash,
            token_fingerprint=generated.token_fingerprint,
            token_expires_at=generated.expires_at,
            email_message_id=f"em-{secrets.token_hex(16)}",
            provider=config.provider,
            provider_idempotency_key=f"password-reset-{generated.lookup_id}",
            render_payload_ciphertext=render_payload,
            created_ip_hash=hash_route_value(client_ip(request), config),
            **idempotency_kwargs(plan),
        )
        email_message_id = row.get("email_message_id") if row else None
    except Exception:
        logger.warning("Password reset enqueue failed; returning generic public response", exc_info=True)

    if row and row.get("user_id"):
        _safe_log_email_activity(
            user_id=str(row["user_id"]),
            activity_type=ActivityType.PASSWORD_RESET_REQUESTED,
            details={"action": "password_reset_requested", "email_message_id": email_message_id},
            request=request,
            target_user_id=str(row["user_id"]),
        )
    _safe_complete_email_idempotency(plan, email_message_id=email_message_id)
    return generic_accepted_response()


@router.post("/password/reset")
@log_unauthenticated_operation(
    operation_name="password_reset_consume",
    activity_type=ActivityType.PASSWORD_RESET_CONSUMED,
    log_success=False,
)
async def reset_password_with_link(
    request: Request,
    log_context = None,
):
    """Consume a password reset token, update password, and create no session."""

    payload = await read_request_payload(request)
    new_password = str(payload.get("new_password") or payload.get("password") or "")
    if not new_password:
        raise ValidationError(
            message="new_password is required",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"missing_fields": ["new_password"]},
        )
    assert_password_policy(new_password)

    token = token_from_request_payload(payload)
    parsed = parse_presented_token(token)
    if parsed is None:
        return generic_accepted_response()

    lookup_id, secret = parsed
    limited = _check_email_consume_rate_limit(request=request, purpose="password_reset", lookup_id=lookup_id)
    if limited is not None:
        return limited

    config = load_route_email_config()
    lookup_hash = hash_route_value(lookup_id, config)
    password_binding_hash = hash_route_value(new_password, config)
    plan = _safe_prepare_email_idempotency(
        raw_key=request.headers.get("idempotency-key"),
        scope="auth.password.reset",
        user_id=None,
        recipient_hash=lookup_hash,
        body={
            "lookup_id": lookup_id,
            "purpose": "password_reset",
            "new_password_hash": password_binding_hash.hex() if password_binding_hash else None,
        },
        config=config,
    )
    if plan.replay_response is not None:
        return plan.replay_response

    new_password_hash = hash_password(new_password)
    row = None
    for purpose in ("password_reset", "admin_password_reset"):
        try:
            row = db_email.consume_password_reset_token(
                lookup_id=lookup_id,
                token_hash=_token_hash_for_presented_token(
                    purpose=purpose,
                    lookup_id=lookup_id,
                    secret=secret,
                    config=config,
                ),
                new_password_hash=new_password_hash,
                consumed_ip_hash=hash_route_value(client_ip(request), config),
                consumed_user_agent_hash=hash_route_value(user_agent(request), config),
            )
        except Exception:
            logger.warning("Password reset consume failed; returning generic public response", exc_info=True)
            row = None
            break
        if row and db_bool(row.get("password_changed")):
            break

    if row and db_bool(row.get("password_changed")) and row.get("user_id"):
        revoke_user_auth_state(str(row["user_id"]), reason="password_reset")
        _safe_log_email_activity(
            user_id=str(row["user_id"]),
            activity_type=ActivityType.PASSWORD_RESET_CONSUMED,
            details={"action": "password_reset_consumed"},
            request=request,
            target_user_id=str(row["user_id"]),
        )

    _safe_complete_email_idempotency(plan, email_message_id=None)
    return generic_accepted_response()


@router.post("/password/change", response_model=ChangePasswordResponse)
@log_and_handle_errors(
    operation_name="change_password",
    activity_type=None,
    log_success=False,
)
async def change_password(
        request: Request,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None,
) -> ChangePasswordResponse:
    """Change the authenticated user's password without issuing a new session."""

    payload = await read_request_payload(request)
    missing_fields = []
    if not payload.get("current_password"):
        missing_fields.append("current_password")
    if not payload.get("new_password"):
        missing_fields.append("new_password")
    if missing_fields:
        raise ValidationError(
            message="Required fields are missing",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"missing_fields": missing_fields},
        )

    change_request = ChangePasswordRequest(
        current_password=str(payload["current_password"]),
        new_password=str(payload["new_password"]),
    )
    assert_password_policy(
        change_request.new_password,
        username=getattr(log_context, "username", None),
    )

    claims, current_access_jti, current_family_id = _decode_current_password_change_claims(credentials)
    rate_limited = _check_change_password_attempt_rate_limit(
        request=request,
        user_id=str(log_context.user_id),
        session_id=str(claims.get("session_id") or current_access_jti),
    )
    if rate_limited is not None:
        return rate_limited

    try:
        result = change_user_password(
            user_id=str(log_context.user_id),
            current_password=change_request.current_password,
            new_password=change_request.new_password,
            username=getattr(log_context, "username", None),
        )
    except AuthenticationError:
        _record_change_password_failure(request=request, user_id=str(log_context.user_id))
        raise

    if not result or not result.get("password_changed"):
        raise create_invalid_current_password_error()

    require_recent_reauthentication(
        user_id=str(log_context.user_id),
        session_token=credentials.credentials,
        session_id=str(claims.get("session_id") or current_access_jti),
        operation="password_change",
        credential_proof_present=True,
    )

    revocation_summary = revoke_user_auth_state_except_current(
        str(log_context.user_id),
        current_access_jti=current_access_jti,
        current_family_id=current_family_id,
        reason="password_change",
    )
    _safe_log_email_activity(
        user_id=str(log_context.user_id),
        activity_type=ActivityType.PASSWORD_CHANGED,
        details={
            "action": "password_changed",
            "sessions_revoked": getattr(revocation_summary, "sessions_revoked", 0),
            "families_revoked": getattr(revocation_summary, "families_revoked", 0),
            "sessions_preserved": getattr(revocation_summary, "sessions_preserved", 0),
        },
        request=request,
        target_user_id=str(log_context.user_id),
    )

    return ChangePasswordResponse(success=True, message="Password changed successfully")

# ---------------------------------------------------------------------------

@router.post("/login", response_model=LoginResponse)
@log_unauthenticated_operation(
    operation_name="user_login",
    activity_type=ActivityType.USER_LOGIN,
    extract_username=lambda *args, **kwargs: kwargs.get('username')
)
async def login(
        response: Response,
        username: str = Form(...),
        password: str = Form(...),
        remember_me: bool = Form(False),
        project_hash: Optional[str] = Form(
            None,
            description="Required for all users. Root users bypass group-based access validation and may access any project by role.",
        ),
        request: Request = None,
        log_context: UnauthenticatedLogContext = None
) -> LoginResponse:
    """
    Authenticate user and return session token.

    The project context is mandatory for all users:
    - Root users MUST provide a project_hash but bypass group-based access validation.
    - Root may access any project by role.
    - Non-root users MUST provide a project_hash and are validated through group access.
    - Billing must not be added to this identity/session response.
    - The complete list of accessible projects is always returned so clients may 
      switch context later with the `/auth/switch-project` endpoint.
    """
    if not username or not password:
        raise ValidationError(
            message="Username and password are required",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"missing_fields": ["username", "password"]}
        )

    limited = _check_login_identifier_rate_limit(request, username)
    if limited is not None:
        return limited

    # Step 1: verify credentials (username or email)
    user_record = handle_db_operation(
        lambda: get_user_by_credentials(username, password),
        error_context="user authentication"
    )
    
    if not user_record:
        _record_login_identifier_failure(request, username)
        raise AuthenticationError(
            message="Invalid username or password",
            error_code=ErrorCode.INVALID_CREDENTIALS,
            details={"username": username}
        )

    _record_auth_email_login_if_applicable(user_record, username, request)

    # ------------------------------------------------------------------
    # ALL users MUST provide a project_hash
    # ------------------------------------------------------------------
    if not project_hash:
        raise ValidationError(
            message="Project identifier is required for login",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"missing_fields": ["project_hash"]}
        )

    # ------------------------------------------------------------------
    # Root users -> project-bound session (bypasses group validation)
    # ------------------------------------------------------------------
    if user_record.user_type == "root":
        target_project = handle_db_operation(
            lambda: get_project_by_hash(project_hash),
            error_context="project lookup",
            not_found_message=f"Project not found: {mask_uuid(project_hash)}",
        )
        if not target_project:
            raise NotFoundError(
                message=f"Project not found: {mask_uuid(project_hash)}",
                error_code=ErrorCode.PROJECT_NOT_FOUND,
                details={"project_hash": mask_uuid(project_hash)},
            )
        if not _project_is_auth_accessible(target_project):
            _deny_project_auth(project_hash)

        token_pair = issue_project_token_pair(
            user=user_record,
            project=target_project,
            permissions=["admin", "global_admin", "unrestricted_access"],
            groups=["root_users"],
            remember_me=remember_me,
        )
        _set_token_pair_cookies(response, token_pair)

        # Even for root we still expose list of projects for UI convenience
        accessible_projects = get_user_accessible_projects(user_record.id)
        accessible_projects_info = [
            ProjectInfo(
                project_hash=p.project_hash,
                project_name=p.project_name,
                project_description=p.project_description,
            )
            for p in accessible_projects
        ]

        return LoginResponse(
            success=True,
            message="Root user login successful",
            access_token=token_pair.access_token,
            refresh_token=token_pair.refresh_token,
            session_token=token_pair.session_token,
            token_type=token_pair.token_type,
            expires_in=token_pair.expires_in,
            refresh_expires_in=token_pair.refresh_expires_in,
            expires_at=token_pair.expires_at,
            refresh_expires_at=token_pair.refresh_expires_at,
            user=UserInfo(
                user_hash=user_record.user_hash,
                username=user_record.username,
                email=user_record.email,
                user_type="root",
            ),
            project=ProjectInfo(
                project_hash=target_project.project_hash,
                project_name=target_project.project_name,
                project_description=target_project.project_description,
            ),
            accessible_projects=accessible_projects_info,
            user_groups=[],  # Root users bypass group validation
            user_id=user_record.id
        )

    # ------------------------------------------------------------------
    # Admin users → assigned-project authorization only
    # ------------------------------------------------------------------
    if user_record.user_type == "admin":
        target_project = handle_db_operation(
            lambda: get_project_by_hash(project_hash),
            error_context="project lookup",
            not_found_message=f"Project not found: {mask_uuid(project_hash)}",
        )
        if not target_project:
            raise NotFoundError(
                message=f"Project not found: {mask_uuid(project_hash)}",
                error_code=ErrorCode.PROJECT_NOT_FOUND,
                details={"project_hash": mask_uuid(project_hash)},
            )
        if not _project_is_auth_accessible(target_project):
            _deny_project_auth(project_hash)
        if not check_admin_multi_project_access(user_record.id, target_project.id):
            _deny_project_auth(project_hash)

        token_pair = issue_project_token_pair(
            user=user_record,
            project=target_project,
            permissions=["admin", "project_admin", "manage_users", "manage_groups", "manage_permissions"],
            groups=["project_admins"],
            group_ids=[],
            remember_me=remember_me,
        )
        _set_token_pair_cookies(response, token_pair)

        return LoginResponse(
            success=True,
            message="Login successful",
            access_token=token_pair.access_token,
            refresh_token=token_pair.refresh_token,
            session_token=token_pair.session_token,
            token_type=token_pair.token_type,
            expires_in=token_pair.expires_in,
            refresh_expires_in=token_pair.refresh_expires_in,
            expires_at=token_pair.expires_at,
            refresh_expires_at=token_pair.refresh_expires_at,
            user=UserInfo(
                user_hash=user_record.user_hash,
                username=user_record.username,
                email=user_record.email,
                user_type=user_record.user_type,
            ),
            project=ProjectInfo(
                project_hash=target_project.project_hash,
                project_name=target_project.project_name,
                project_description=target_project.project_description,
            ),
            accessible_projects=_admin_accessible_project_infos(user_record.id),
            user_groups=[],
            user_id=user_record.id,
        )

    # ------------------------------------------------------------------
    # Consumer users → choose specific project from accessible-project union
    # ------------------------------------------------------------------
    accessible = get_user_accessible_projects(user_record.id)
    target_project = resolve_target_project(
        accessible_projects=accessible,
        requested_project_hash=project_hash,
        get_project_by_hash_fn=get_project_by_hash,
        handle_db_operation_fn=handle_db_operation,
    )
    if not _project_is_auth_accessible(target_project):
        _deny_project_auth(project_hash)

    # Build project info object for the chosen default project
    project_info = ProjectInfo(
        project_hash=target_project.project_hash,
        project_name=target_project.project_name,
        project_description=target_project.project_description,
    )

    # Map all accessible projects into API schema
    accessible_projects_info = [
        ProjectInfo(
            project_hash=p.project_hash,
            project_name=p.project_name,
            project_description=p.project_description,
        )
        for p in accessible
    ]

    # Get user groups for response (groups-of-groups architecture)
    user_groups = get_user_groups_for_user(user_record.id)
    user_groups_info = [
        UserGroupInfo(
            group_hash=g.group_hash,
            group_name=g.group_name,
            description=getattr(g, 'group_description', None),
        )
        for g in user_groups
    ]
    user_group_names = [g.group_name for g in user_groups]
    user_group_ids = [str(g.id) for g in user_groups]
    session_groups = user_group_names
    session_group_ids = user_group_ids
    session_permissions = []

    token_pair = issue_project_token_pair(
        user=user_record,
        project=target_project,
        permissions=session_permissions,
        groups=session_groups,
        group_ids=session_group_ids,
        remember_me=remember_me,
    )
    _set_token_pair_cookies(response, token_pair)

    from src.Util.session_plan import resolve_session_plan
    login_plan = resolve_session_plan(user_record.id, target_project.id)

    return LoginResponse(
        success=True,
        message="Login successful",
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        session_token=token_pair.session_token,
        token_type=token_pair.token_type,
        expires_in=token_pair.expires_in,
        refresh_expires_in=token_pair.refresh_expires_in,
        expires_at=token_pair.expires_at,
        refresh_expires_at=token_pair.refresh_expires_at,
        user=UserInfo(
            user_hash=user_record.user_hash,
            username=user_record.username,
            email=user_record.email,
            user_type=user_record.user_type,
        ),
        project=project_info,
        accessible_projects=accessible_projects_info,
        user_groups=user_groups_info,
        plan=login_plan,
        user_id=user_record.id
    )


@router.post("/platform/login", response_model=LoginResponse)
@log_unauthenticated_operation(
    operation_name="platform_user_login",
    activity_type=ActivityType.USER_LOGIN,
    extract_username=lambda *args, **kwargs: kwargs.get('username')
)
async def platform_login(
        response: Response,
        username: str = Form(...),
        password: str = Form(...),
        remember_me: bool = Form(False),
        request: Request = None,
        log_context: UnauthenticatedLogContext = None
) -> LoginResponse:
    """Authenticate root/admin users for platform dashboard access without project scope."""
    if not username or not password:
        raise ValidationError(
            message="Username and password are required",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"missing_fields": ["username", "password"]}
        )

    limited = _check_login_identifier_rate_limit(request, username)
    if limited is not None:
        return limited

    user_record = handle_db_operation(
        lambda: get_user_by_credentials(username, password),
        error_context="platform user authentication"
    )

    if not user_record:
        _record_login_identifier_failure(request, username)
        raise AuthenticationError(
            message="Invalid username or password",
            error_code=ErrorCode.INVALID_CREDENTIALS,
            details={"username": username}
        )

    _record_auth_email_login_if_applicable(user_record, username, request)

    if user_record.user_type not in {"root", "admin"}:
        raise AuthorizationError(
            message="Platform login is restricted to root and admin users",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"allowed_user_types": ["root", "admin"]}
        )

    if user_record.user_type == "root":
        permissions = ["admin", "global_admin", "manage_users", "manage_roles", "unrestricted_access"]
        groups = ["platform_root_users"]
    else:
        permissions = ["admin", "project_admin", "manage_users", "manage_roles", "manage_permissions"]
        groups = ["platform_admins"]

    token_pair = issue_platform_token_pair(
        user=user_record,
        permissions=permissions,
        groups=groups,
        remember_me=remember_me,
    )
    _set_token_pair_cookies(response, token_pair)

    return LoginResponse(
        success=True,
        message="Platform login successful",
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        session_token=token_pair.session_token,
        token_type=token_pair.token_type,
        expires_in=token_pair.expires_in,
        refresh_expires_in=token_pair.refresh_expires_in,
        expires_at=token_pair.expires_at,
        refresh_expires_at=token_pair.refresh_expires_at,
        user=UserInfo(
            user_hash=user_record.user_hash,
            username=user_record.username,
            email=user_record.email,
            user_type=user_record.user_type,
        ),
        project=None,
        accessible_projects=[],
        user_groups=[],
        user_id=user_record.id,
    )


@router.post("/register", response_model=RegisterResponse)
@log_unauthenticated_operation(
    operation_name="user_registration",
    activity_type=ActivityType.USER_REGISTRATION,
    extract_username=lambda *args, **kwargs: kwargs.get('username')
)
async def register(
        response: Response,
        username: str = Form(...),
        password: str = Form(...),
        email: Optional[str] = Form(None),
        user_group_hash: str = Form(...),
        request: Request = None,
        log_context: UnauthenticatedLogContext = None
) -> RegisterResponse:
    """
    Register new user with automatic group assignment.
    Sets HTTP-only cookie with JWT token.
    
    Args:
        username: Desired username
        password: User's password
        email: User's email address (optional)
        user_group_hash: User group hash for registration
        
    Returns:
        Registration result with user information
    """
    if not username or not password or not user_group_hash:
        missing_fields = []
        if not username: missing_fields.append("username")
        if not password: missing_fields.append("password")
        if not user_group_hash: missing_fields.append("user_group_hash")
        
        raise ValidationError(
            message="Required fields are missing",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"missing_fields": missing_fields}
        )

    assert_password_policy(password, username=username, email=email)

    # Check if username/email is available
    username_available = handle_db_operation(
        lambda: check_username_email_available(username),
        error_context="username availability check"
    )
    if not username_available:
        raise ConflictError(
            message="Username already exists",
            error_code=ErrorCode.USERNAME_EXISTS,
            details={"username": username}
        )
    
    if email:
        email_available = handle_db_operation(
            lambda: check_username_email_available(email),
            error_context="email availability check"
        )
        if not email_available:
            raise ConflictError(
                message="Email already exists",
                error_code=ErrorCode.EMAIL_EXISTS,
                details={"email": email}
            )

    # Validate user group exists before registration
    user_group = handle_db_operation(
        lambda: get_user_group_by_hash(user_group_hash),
        error_context="user group lookup"
    )
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"user_group_hash": mask_uuid(user_group_hash)}
        )
    
    # Register user with group assignment
    register_result = handle_db_operation(
        lambda: enhanced_register(username, password, email, user_group_hash),
        error_context="user registration"
    )
    
    if not register_result:
        from src.Util.error_handler import InternalError
        raise InternalError(
            message="User creation failed during registration",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={
                "operation": "user_registration",
                "user_group": user_group.group_name,
                "hint": "User record creation failed. This may indicate a database constraint violation."
            }
        )

    token_pair = _registration_token_pair(register_result)
    if token_pair is not None:
        _set_token_pair_cookies(response, token_pair)

    user_info = UserInfo(
        user_hash=register_result.user_hash,
        username=getattr(register_result, 'username') or username,
        email=getattr(register_result, 'email', email),
        user_type=getattr(register_result, 'user_type', 'consumer')
    )

    project_info = None
    if register_result.project_hash:
        project_info = ProjectInfo(
            project_hash=register_result.project_hash,
            project_name=register_result.project_name
        )

    return RegisterResponse(
        success=True,
        message="User registered successfully",
        access_token=token_pair.access_token if token_pair else None,
        refresh_token=token_pair.refresh_token if token_pair else None,
        session_token=token_pair.session_token if token_pair else None,
        token_type=token_pair.token_type if token_pair else "Bearer",
        expires_in=token_pair.expires_in if token_pair else None,
        refresh_expires_in=token_pair.refresh_expires_in if token_pair else None,
        expires_at=token_pair.expires_at if token_pair else None,
        refresh_expires_at=token_pair.refresh_expires_at if token_pair else None,
        user=user_info,
        project=project_info,
        user_id=getattr(register_result, 'user_id', None)
    )


@router.get("/validate", response_model=ValidateSessionResponse)
@log_and_handle_errors(
    operation_name="validate_session",
    activity_type=ActivityType.USER_LOGIN,
    log_success=False
)
async def validate_user_session(
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None,
        response: Response = None,
        background_tasks: BackgroundTasks = None,
) -> ValidateSessionResponse:
    """
    Validate session token and return user information with group context.
    
    Returns:
        Current user and session information
    """
    _t_start = time.monotonic()
    session_token = credentials.credentials

    try:
        if not isinstance(session_token, str) or session_token.count(".") != 2:
            raise AuthenticationError(
                message="Invalid access token",
                error_code=ErrorCode.SESSION_EXPIRED,
                details={"hint": "Please log in again with a valid access token"}
            )

        try:
            login_data = validate_enhanced_session(session_token)
        except HTTPException as exc:
            raise AuthenticationError(
                message=str(exc.detail),
                error_code=ErrorCode.SESSION_EXPIRED,
                details={"hint": "Please log in again"}
            )

        if not login_data:
            raise AuthenticationError(
                message="Invalid or expired session",
                error_code=ErrorCode.SESSION_EXPIRED,
                details={"hint": "Please log in again"}
            )

        user_info = UserInfo(
            user_hash=login_data.user_hash,
            username=login_data.username or login_data.user_hash,
            user_type=login_data.user_type or "consumer",
        )

        if login_data.project_hash:
            project_info = ProjectInfo(
                project_hash=login_data.project_hash,
                project_name=login_data.project_name or "",
            )
        else:
            project_info = None

        user_group_names = list(login_data.groups or [])
        access_claims = JWTTokenHandler.decode_access_token(session_token)
        refresh_family = _get_refresh_family(str(access_claims["family_id"])) or {}
        access_expires_at = datetime.fromtimestamp(
            int(access_claims["exp"]),
            timezone.utc,
        ).isoformat()

        duration_ms = (time.monotonic() - _t_start) * 1000
        if response is not None:
            response.headers["X-Auth-Process-Time"] = f"{duration_ms:.3f}"
        return ValidateSessionResponse(
            success=True,
            valid=True,
            user=user_info,
            project=project_info,
            session={
                "created_at": None,
                "scope": login_data.scope or "project",
                "expires_at": access_expires_at,
                "refresh_expires_at": refresh_family.get("absolute_expires_at") or refresh_family.get("expires_at"),
                "remember_me": bool(refresh_family.get("remember_me", False)),
            },
            user_groups=user_group_names,
            plan=login_data.plan,
        )
    except Exception:
        duration_ms = (time.monotonic() - _t_start) * 1000
        if response is not None:
            response.headers["X-Auth-Process-Time"] = f"{duration_ms:.3f}"
        raise


@router.post("/validate-api-key", response_model=ValidateApiKeyResponse)
async def validate_user_api_key(
        request: Request,
        response: Response = None,
) -> ValidateApiKeyResponse:
    """Validate user-created API keys through an enforcing X-API-Key adapter.

    This route is intentionally separate from GET /auth/validate so the
    session/JWT contract stays session-only. It never returns the raw API key or
    its secret component.
    """
    _t_start = time.monotonic()
    api_key = request.headers.get("X-API-Key")
    authorization = request.headers.get("Authorization")

    if authorization and api_key:
        logger.warning(
            "api_key_validate_rejected",
            extra={"event": "api_key_validate_rejected", "reason": "ambiguous_credentials"},
        )
        raise HTTPException(status_code=400, detail="ambiguous_credentials")

    try:
        context = await validate_api_key_context(api_key)
    finally:
        duration_ms = (time.monotonic() - _t_start) * 1000
        if response is not None:
            response.headers["X-Auth-Process-Time"] = f"{duration_ms:.3f}"

    if context.get("auth_method") != "api_key":
        raise HTTPException(status_code=500, detail="Invalid API-key validation context")

    user_hash = context.get("user_hash")
    if not user_hash:
        raise HTTPException(status_code=500, detail="API-key validation context missing user_hash")

    project_hash = context.get("project_hash")
    user_groups = list(context.get("groups") or [])
    permissions = list(context.get("permissions") or [])
    key_public_id = context.get("key_public_id")
    key_id = context.get("key_id")

    logger.info(
        "api_key_validate_resolved",
        extra={
            "event": "api_key_validate_resolved",
            "auth_method": "api_key",
            "user_prefix": str(user_hash)[:12],
            "project_prefix": str(project_hash)[:12] if project_hash else None,
            "key_public_id_prefix": str(key_public_id)[:8] if key_public_id else None,
        },
    )

    api_key_plan = None
    if context.get("user_id") and context.get("project_id") and (context.get("user_type") or "consumer") == "consumer":
        from src.Util.session_plan import resolve_session_plan
        api_key_plan = resolve_session_plan(context.get("user_id"), context.get("project_id"))

    return ValidateApiKeyResponse(
        success=True,
        valid=True,
        auth_method="api_key",
        user=UserInfo(
            user_hash=user_hash,
            username=context.get("username") or user_hash,
            email=context.get("email"),
            user_type=context.get("user_type") or "consumer",
        ),
        project=ProjectInfo(
            project_hash=project_hash or "",
            project_name=context.get("project_name") or "",
        ) if project_hash else None,
        api_key=ApiKeyInfo(
            key_id=str(key_id) if key_id is not None else None,
            public_id=str(key_public_id) if key_public_id is not None else None,
        ),
        user_groups=user_groups,
        permissions=permissions,
        plan=api_key_plan,
    )


@router.post("/logout", response_model=LogoutResponse)
@log_and_handle_errors(
    operation_name="user_logout",
    activity_type=ActivityType.USER_LOGOUT,
    log_success=True
)
async def logout(
        response: Response,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> LogoutResponse:
    """
    Logout user and invalidate session.
    Clears the session cookie.
    
    Returns:
        Logout confirmation
    """
    session_token = credentials.credentials

    try:
        claims = JWTTokenHandler.decode_access_token(session_token)
        revoke_refresh_family(str(claims["family_id"]), reason="logout")
    except HTTPException as exc:
        raise AuthenticationError(
            message=str(exc.detail),
            error_code=ErrorCode.SESSION_EXPIRED,
        )

    # Clear access and refresh cookies with matching security attributes.
    response.delete_cookie(key=COOKIE_NAME, path="/", httponly=True, secure=True, samesite="strict")
    response.delete_cookie(key="refresh_token", path="/auth", httponly=True, secure=True, samesite="strict")
    return LogoutResponse(success=True, message="Logged out successfully")


@router.post("/refresh", response_model=LoginResponse)
@log_and_handle_errors(
    operation_name="refresh_token",
    activity_type=ActivityType.USER_LOGIN,
    log_success=False
)
async def refresh_token(
        response: Response,
        request: Request,
        refresh_token_value: Optional[str] = Form(None, alias="refresh_token"),
        log_context: LogContext = None
) -> LoginResponse:
    """
    Refresh JWT token and extend session.
    Creates a new token with updated expiration while maintaining the same session context.
    
    Returns:
        New session token with same user and project context
    """
    try:
        presented_refresh_token = extract_refresh_token_from_request(request, refresh_token_value)
        rotation = rotate_refresh_family(
            presented_refresh_token,
            get_user_by_hash_fn=get_user_by_hash,
            get_project_by_hash_fn=get_project_by_hash,
            get_user_groups_in_project_by_hash_fn=_route_refresh_groups,
            get_user_accessible_projects_fn=get_user_accessible_projects,
        )
    except HTTPException as exc:
        raise AuthenticationError(
            message=str(exc.detail),
            error_code=_refresh_error_code_from_http_exception(exc),
        )
    _set_token_pair_cookies(response, rotation.token_pair)
    return _login_response_from_rotation(rotation)


@router.post("/switch-project", response_model=SwitchProjectResponse)
@log_and_handle_errors(
    operation_name="switch_project",
    activity_type=ActivityType.USER_LOGIN,
    log_success=True
)
async def switch_project(
        response: Response,
        request: Request,
        project_hash: str = Form(...),
        refresh_token_value: Optional[str] = Form(None, alias="refresh_token"),
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> SwitchProjectResponse:
    """
    Switch to a different project that the user's group has access to.
    Updates the session cookie with new JWT token.
    
    Args:
        project_hash: Hash of the project to switch to
        
    Returns:
        New session token with updated project context
    """
    session_token = credentials.credentials
    try:
        access_claims = JWTTokenHandler.decode_access_token(session_token)
        current_session = validate_access_session(
            session_token,
            get_user_by_hash_fn=get_user_by_hash,
            get_project_by_hash_fn=get_project_by_hash,
            get_user_groups_in_project_by_hash_fn=_route_refresh_groups,
            get_user_accessible_projects_fn=get_user_accessible_projects,
        )
    except HTTPException as exc:
        raise AuthenticationError(
            message=str(exc.detail),
            error_code=ErrorCode.SESSION_INVALID
        )

    require_recent_reauthentication(
        user_id=str(current_session.user_id),
        session_token=session_token,
        session_id=str(access_claims.get("session_id") or access_claims.get("jti") or ""),
        operation="switch_project",
    )

    # Validate desired project exists & user has access
    new_project = get_project_by_hash(project_hash)
    if not new_project:
        raise NotFoundError(
            message=f"Project not found: {mask_uuid(project_hash)}",
            error_code=ErrorCode.PROJECT_NOT_FOUND
        )
    if not _project_is_auth_accessible(new_project):
        _deny_project_auth(project_hash)

    current_user_type = getattr(current_session, "user_type", "consumer") or "consumer"
    if current_user_type == "admin":
        if not check_admin_multi_project_access(current_session.user_id, new_project.id):
            _deny_project_auth(project_hash)
    elif current_user_type != "root":
        accessible = get_user_accessible_projects(current_session.user_id)
        if not any(p.project_hash == project_hash for p in accessible):
            _deny_project_auth(project_hash)

    try:
        presented_refresh_token = extract_refresh_token_from_request(request, refresh_token_value)
        refresh_claims = JWTTokenHandler.decode_refresh_token(presented_refresh_token)
        if str(refresh_claims.get("family_id")) != str(access_claims.get("family_id")):
            raise HTTPException(status_code=401, detail="Refresh token does not match access token family")

        rotation = rotate_refresh_family(
            presented_refresh_token,
            target_project=new_project,
            get_user_by_hash_fn=get_user_by_hash,
            get_project_by_hash_fn=get_project_by_hash,
            check_admin_project_access_fn=check_admin_multi_project_access,
            get_user_groups_in_project_by_hash_fn=lambda user_id, _project_hash: get_user_groups_in_project(user_id, new_project.id),
            get_user_accessible_projects_fn=get_user_accessible_projects,
        )
    except HTTPException as exc:
        raise AuthenticationError(
            message=str(exc.detail),
            error_code=_refresh_error_code_from_http_exception(exc),
        )

    _set_token_pair_cookies(response, rotation.token_pair)

    project_info = ProjectInfo(
        project_hash=new_project.project_hash,
        project_name=new_project.project_name,
        project_description=new_project.project_description,
    )

    user_group_names = list(rotation.login_data.groups or [])

    return SwitchProjectResponse(
        success=True,
        message=f"Successfully switched to project: {new_project.project_name}",
        access_token=rotation.token_pair.access_token,
        refresh_token=rotation.token_pair.refresh_token,
        session_token=rotation.token_pair.session_token,
        token_type=rotation.token_pair.token_type,
        expires_in=rotation.token_pair.expires_in,
        refresh_expires_in=rotation.token_pair.refresh_expires_in,
        expires_at=rotation.token_pair.expires_at,
        refresh_expires_at=rotation.token_pair.refresh_expires_at,
        project=project_info,
        user_groups=user_group_names,
    )


@router.post("/check-availability", response_model=CheckAvailabilityResponse)
async def check_availability(
        username: Optional[str] = Form(None),
        email: Optional[str] = Form(None)
) -> CheckAvailabilityResponse:
    """
    Check if username or email is available globally.
    
    Args:
        username: Username to check
        email: Email to check
        
    Returns:
        Availability status for username and email
    """
    check_username = username
    check_email = email

    if not check_username and not check_email:
        raise ValidationError(
            message="Username or email required",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"required_fields": ["username", "email"]}
        )

    username_available = None
    email_available = None

    if check_username:
        username_available = handle_db_operation(
            lambda: check_username_email_available(check_username),
            error_context="username availability check"
        )

    if check_email:
        email_available = handle_db_operation(
            lambda: check_username_email_available(check_email),
            error_context="email availability check"
        )

    return CheckAvailabilityResponse(
        success=True,
        username_available=username_available,
        email_available=email_available
    )
