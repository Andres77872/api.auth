"""
User-Managed API Key Routes

Endpoints for authenticated users to create, list, update, and revoke
their own API keys. Users can only manage keys they own.

All endpoints require an access token (verify_session dependency); API keys
are not accepted here. Create/update/revoke also require recent
authentication. Users can only create keys for projects they have access to.

Prefix: /users/api-keys
"""

import logging
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Form, Path, Query
from fastapi.security import HTTPAuthorizationCredentials

from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.activity_logger import ActivityType
from src.Util.api_key_security import generate_api_key_token
from src.Util.db import (
    create_api_key,
    get_api_key_by_public_id,
    revoke_api_key_with_cache_invalidation,
    list_user_api_keys,
    update_api_key,
    get_user_by_hash,
    get_project_by_hash,
    get_user_accessible_projects,
    get_user_by_id,
)
from src.Util.db_error_wrapper import handle_db_operation
from src.Util.decorators import log_and_handle_errors
from src.Util.auth_flow import access_token_session_id, require_recent_reauthentication
from src.Util.error_handler import (
    AuthorizationError,
    ValidationError,
    NotFoundError,
    InternalError,
    ErrorCode,
    mask_uuid,
)
from src.Util.log_context_models import LogContext
from src.middleware.authentication import verify_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users/api-keys", tags=["API Keys - User"])
security = HTTPBearerOrCookie()

_KEY_ID_DESCRIPTION = (
    "API key identifier: the `id` (equal to `public_id`) returned by create/list, "
    "i.e. the `{public_id}` part of `sk_{public_id}.{secret}`."
)

_RECENT_AUTH_401_RESPONSE = {
    "description": (
        "Missing, invalid, or expired access token, or recent authentication "
        "required (`AUTH_1008`)."
    ),
}
_KEY_NOT_FOUND_404_RESPONSE = {
    "description": "API key not found or not owned by the caller (`NF_4010`).",
}


# =============================================================================
# Helpers
# =============================================================================

def _parse_expires_at(expires_at_str: Optional[str]) -> Optional[datetime]:
    """Parse an ISO 8601 expires_at string into a datetime object.

    Returns None if not provided. Raises ValidationError for past dates.
    """
    if not expires_at_str:
        return None

    try:
        dt = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError) as e:
        raise ValidationError(
            message=f"Invalid expires_at format: {expires_at_str}. Use ISO 8601 format.",
            error_code=ErrorCode.INVALID_INPUT,
            details={"field": "expires_at", "error": str(e)},
        )

    if dt < datetime.now(timezone.utc):
        raise ValidationError(
            message="expires_at must be in the future",
            error_code=ErrorCode.INVALID_INPUT,
            details={"field": "expires_at", "value": expires_at_str},
        )

    return dt


def _format_key_response(key_data: dict, include_token: bool = False, token: Optional[str] = None) -> dict:
    """Format a key record for API response, never including secret_hash."""
    response = {
        "id": key_data.get("id"),
        "public_id": key_data.get("public_id"),
        "name": key_data.get("name"),
        "description": key_data.get("description"),
        "project_id": key_data.get("project_id"),
        "owner_user_id": key_data.get("owner_user_id"),
        "is_active": bool(key_data.get("is_active", True)),
        "expires_at": key_data.get("expires_at"),
        "last_used_at": key_data.get("last_used_at"),
        "created_at": key_data.get("created_at"),
        "updated_at": key_data.get("updated_at"),
        "revoked_at": key_data.get("revoked_at"),
        "revoke_reason": key_data.get("revoke_reason"),
        "fingerprint": key_data.get("fingerprint"),
        "secret_last4": key_data.get("secret_last4"),
        "hash_algorithm": key_data.get("hash_algorithm"),
    }
    if include_token and token:
        response["api_key"] = token
    return response


def _assert_key_ownership(key_data: dict, current_user_id: str):
    """Assert that the current user owns the given key."""
    if str(key_data.get("owner_user_id")) != str(current_user_id):
        raise NotFoundError(
            message="API key not found",
            error_code=ErrorCode.API_KEY_NOT_FOUND,
        )


def _require_recent_reauth_for_user_api_key_mutation(current_user: dict, operation: str) -> None:
    require_recent_reauthentication(
        user_id=str(current_user.get("user_id") or ""),
        session_token=current_user.get("session_token"),
        session_id=access_token_session_id(current_user.get("session_token")),
        operation=operation,
    )


# =============================================================================
# POST /users/api-keys — Create own API key
# =============================================================================

@router.post(
    "",
    responses={
        401: _RECENT_AUTH_401_RESPONSE,
        403: {"description": "The caller has no access to the project (`AUTHZ_2003`)."},
        404: {"description": "Unknown `project_hash`."},
    },
)
@log_and_handle_errors(
    operation_name="user_create_api_key",
    activity_type=ActivityType.USER_LOGIN,
    log_success=True,
)
async def user_create_api_key(
    project_hash: str = Form(
        ...,
        description="Hash of the project the key is scoped to; the caller must have access to it.",
    ),
    name: Optional[str] = Form(
        None,
        description="Human-readable label. Defaults to `API Key - YYYY-MM-DD` (UTC date).",
    ),
    description: Optional[str] = Form(None, description="Optional free-text description."),
    expires_at: Optional[str] = Form(
        None,
        description=(
            "Optional expiry as ISO 8601 (e.g. `2027-01-01T00:00:00Z`); must be in the future. "
            "Values without a timezone are treated as UTC. Omit for a key that never expires."
        ),
    ),
    current_user: dict = Depends(verify_session),
    log_context: LogContext = None,
) -> dict:
    """Create an API key owned by the caller and scoped to one project.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie), any user type, plus recent authentication: a
    sign-in, or an OAuth reauth of this session, within the recent-auth window
    (5 minutes by default; refreshing the session does not renew it). API keys (`X-API-Key`) are not accepted. The caller must have
    access to the project (root: any active project).

    **Request:** form fields (`application/x-www-form-urlencoded` or
    `multipart/form-data`).

    **Responses:**
    - `200` — `data.api_key` is the full `sk_{public_id}.{secret}` token. It is
      returned only in this response; the server keeps an HMAC-SHA-256 hash and
      cannot show it again. `data.id` (= `public_id`) identifies the key later.
    - `400` — malformed or past `expires_at`.
    - `401` — missing/invalid access token, or recent authentication required
      (`AUTH_1008`).
    - `403` — no access to the project (`AUTHZ_2003`).
    - `404` — unknown `project_hash`.
    \f
    sp_create_api_key re-validates owner project access via the group chain
    (root creators bypass it).
    """
    current_user_id = current_user.get("user_id")
    _require_recent_reauth_for_user_api_key_mutation(current_user, "user_create_api_key")

    # Resolve project
    project = handle_db_operation(
        lambda: get_project_by_hash(project_hash),
        error_context=f"project lookup for hash {mask_uuid(project_hash)}",
        not_found_message=f"Project not found: {mask_uuid(project_hash)}",
    )

    # Verify user has access to this project
    accessible_projects = get_user_accessible_projects(current_user_id)
    accessible_project_ids = {p.id for p in accessible_projects} if accessible_projects else set()

    if project.id not in accessible_project_ids:
        raise AuthorizationError(
            message="Access denied: you do not have access to this project",
            error_code=ErrorCode.PROJECT_ACCESS_DENIED,
            details={"project_hash": mask_uuid(project_hash)},
        )

    # Parse expiration
    expires_at_dt = _parse_expires_at(expires_at)

    # Auto-generate name if not provided
    if not name:
        name = f"API Key - {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"

    # Generate the token (Python side)
    token_data = generate_api_key_token()

    # Create the key via stored procedure (validates project access)
    key_result = create_api_key(
        key_id=token_data["public_id"],
        public_id=token_data["public_id"],
        project_id=project.id,
        owner_user_id=current_user_id,
        created_by=current_user_id,
        name=name,
        description=description,
        secret_hash=token_data["secret_hash"],
        hash_algorithm="hmac-sha256-v1",
        fingerprint=token_data["fingerprint"],
        secret_last4=token_data["secret_last4"],
        expires_at=expires_at_dt,
    )

    if not key_result:
        raise InternalError(
            message="Failed to create API key",
            error_code=ErrorCode.INTERNAL_ERROR,
        )

    return {
        "success": True,
        "message": "API key created successfully. Save this token — it will not be shown again.",
        "data": _format_key_response(key_result, include_token=True, token=token_data["token"]),
    }


# =============================================================================
# GET /users/api-keys — List own keys
# =============================================================================

@router.get("")
@log_and_handle_errors(
    operation_name="user_list_api_keys",
    activity_type=ActivityType.USER_LOGIN,
    log_success=False,
)
async def user_list_api_keys(
    project_hash: Optional[str] = Query(
        None,
        description="Keep only keys for this project hash (applied to the fetched page).",
    ),
    active_only: bool = Query(
        False,
        description="Keep only keys with `is_active=true` (applied to the fetched page).",
    ),
    limit: int = Query(50, ge=1, le=200, description="Page size (1-200)."),
    offset: int = Query(0, ge=0, description="Number of keys to skip."),
    current_user: dict = Depends(verify_session),
    log_context: LogContext = None,
) -> dict:
    """List the caller's own API keys (metadata only, never the secret).

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie), any user type. No recent authentication needed.

    **Responses:**
    - `200` — `data.keys`, `data.total`, `data.limit`, `data.offset`. Revoked
      and expired keys are included unless `active_only=true`.
    - `404` — unknown `project_hash`.

    Filters are applied after the `limit`/`offset` page is fetched, so a
    filtered page may hold fewer than `limit` keys and `total` then counts only
    the filtered page.
    """
    current_user_id = current_user.get("user_id")

    keys, total = list_user_api_keys(
        owner_user_id=current_user_id,
        limit=limit,
        offset=offset,
    )

    # If project_hash filter provided, filter results
    if project_hash:
        project = handle_db_operation(
            lambda: get_project_by_hash(project_hash),
            error_context=f"project lookup for hash {mask_uuid(project_hash)}",
            not_found_message=f"Project not found: {mask_uuid(project_hash)}",
        )
        keys = [k for k in keys if str(k.get("project_id")) == str(project.id)]
        total = len(keys)

    # If active_only filter, filter results
    if active_only:
        keys = [k for k in keys if k.get("is_active")]
        total = len(keys)

    return {
        "success": True,
        "message": "API keys retrieved successfully",
        "data": {
            "keys": [_format_key_response(k) for k in keys],
            "total": total,
            "limit": limit,
            "offset": offset,
        },
    }


# =============================================================================
# GET /users/api-keys/{key_id} — Get own key details
# =============================================================================

@router.get("/{key_id}", responses={404: _KEY_NOT_FOUND_404_RESPONSE})
@log_and_handle_errors(
    operation_name="user_get_api_key",
    activity_type=ActivityType.USER_LOGIN,
    log_success=False,
)
async def user_get_api_key(
    key_id: Annotated[str, Path(description=_KEY_ID_DESCRIPTION)],
    current_user: dict = Depends(verify_session),
    log_context: LogContext = None,
) -> dict:
    """Get metadata for one of the caller's API keys (never the secret or its hash).

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie), any user type.

    **Responses:** `404` when the key does not exist or belongs to someone else
    (ownership is not disclosed).
    """
    current_user_id = current_user.get("user_id")

    # Look up the key
    key_data = get_api_key_by_public_id(key_id)
    if not key_data:
        raise NotFoundError(
            message="API key not found",
            error_code=ErrorCode.API_KEY_NOT_FOUND,
        )

    # Assert ownership
    _assert_key_ownership(key_data, current_user_id)

    return {
        "success": True,
        "message": "API key retrieved successfully",
        "data": _format_key_response(key_data),
    }


# =============================================================================
# PUT /users/api-keys/{key_id} — Update own key
# =============================================================================

@router.put(
    "/{key_id}",
    responses={401: _RECENT_AUTH_401_RESPONSE, 404: _KEY_NOT_FOUND_404_RESPONSE},
)
@log_and_handle_errors(
    operation_name="user_update_api_key",
    activity_type=ActivityType.USER_LOGIN,
    log_success=True,
)
async def user_update_api_key(
    key_id: Annotated[str, Path(description=_KEY_ID_DESCRIPTION)],
    name: Optional[str] = Form(None, description="New label for the key."),
    description: Optional[str] = Form(None, description="New description."),
    expires_at: Optional[str] = Form(
        None,
        description="New expiry as ISO 8601; must be in the future. Values without a timezone are treated as UTC.",
    ),
    current_user: dict = Depends(verify_session),
    log_context: LogContext = None,
) -> dict:
    """Update the name, description, or expiry of one of the caller's API keys.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) plus recent authentication (a sign-in, or an OAuth reauth of this session, within the
    recent-auth window, 5 minutes by default; refreshing the session does not renew it).

    **Request:** form fields; send at least one of `name`, `description`,
    `expires_at`. Empty values count as absent, so fields cannot be cleared.
    A future `expires_at` on a key that was deactivated after expiring
    reactivates it. Revoked keys cannot be changed or reactivated.

    **Responses:**
    - `200` — updated key metadata in `data`.
    - `400` — no field provided, or malformed/past `expires_at`; `AUTH_1012`
      when the key has been revoked.
    - `401` — missing/invalid access token, or recent authentication required
      (`AUTH_1008`).
    - `404` — key not found or not owned by the caller.
    """
    current_user_id = current_user.get("user_id")
    _require_recent_reauth_for_user_api_key_mutation(current_user, "user_update_api_key")

    # Look up the key first to check ownership and get public_id
    key_data = get_api_key_by_public_id(key_id)
    if not key_data:
        raise NotFoundError(
            message="API key not found",
            error_code=ErrorCode.API_KEY_NOT_FOUND,
        )

    # Assert ownership
    _assert_key_ownership(key_data, current_user_id)
    # Revocation is permanent: a revoked key is never edited, so a future
    # expires_at cannot bring it back (sp_update_api_key refuses it too).
    if key_data.get("revoked_at"):
        raise ValidationError(
            message="API key has been revoked and cannot be modified",
            error_code=ErrorCode.API_KEY_REVOKED,
        )

    # Validate at least one field
    if not any([name, description, expires_at]):
        raise ValidationError(
            message="At least one field must be provided to update",
            error_code=ErrorCode.INVALID_INPUT,
            details={"fields": ["name", "description", "expires_at"]},
        )

    # Parse expiration if provided
    expires_at_dt = _parse_expires_at(expires_at)

    # Update the key
    updated = update_api_key(
        key_id=key_id,
        name=name,
        description=description,
        expires_at=expires_at_dt,
        public_id=key_data.get("public_id"),
    )

    if not updated:
        raise NotFoundError(
            message="API key not found",
            error_code=ErrorCode.API_KEY_NOT_FOUND,
        )

    return {
        "success": True,
        "message": "API key updated successfully",
        "data": _format_key_response(updated),
    }


# =============================================================================
# DELETE /users/api-keys/{key_id} — Revoke own key
# =============================================================================

@router.delete(
    "/{key_id}",
    responses={401: _RECENT_AUTH_401_RESPONSE, 404: _KEY_NOT_FOUND_404_RESPONSE},
)
@log_and_handle_errors(
    operation_name="user_revoke_api_key",
    activity_type=ActivityType.USER_LOGIN,
    log_success=True,
)
async def user_revoke_api_key(
    key_id: Annotated[str, Path(description=_KEY_ID_DESCRIPTION)],
    current_user: dict = Depends(verify_session),
    log_context: LogContext = None,
) -> dict:
    """Revoke one of the caller's API keys.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) plus recent authentication (a sign-in, or an OAuth reauth of this session, within the
    recent-auth window, 5 minutes by default; refreshing the session does not renew it).

    **Request:** no body.

    **Responses:**
    - `200` — revoked (`data.key_id`, `data.revoked_at`). The cached validation
      entry is dropped, so the key stops authenticating immediately.
    - `401` — missing/invalid access token, or recent authentication required
      (`AUTH_1008`).
    - `404` — key not found or not owned by the caller.
    - `400` (`AUTH_1012`) — the key is already inactive (revoked, or
      deactivated after expiring).
    """
    current_user_id = current_user.get("user_id")
    _require_recent_reauth_for_user_api_key_mutation(current_user, "user_revoke_api_key")

    # Look up the key first to check ownership and get public_id
    key_data = get_api_key_by_public_id(key_id)
    if not key_data:
        raise NotFoundError(
            message="API key not found",
            error_code=ErrorCode.API_KEY_NOT_FOUND,
        )

    # Assert ownership
    _assert_key_ownership(key_data, current_user_id)

    # Revoke with cache invalidation
    result = revoke_api_key_with_cache_invalidation(
        key_id=key_id,
        public_id=key_data["public_id"],
        revoked_by=current_user_id,
    )

    if not result:
        raise ValidationError(
            message="API key is already revoked or does not exist",
            error_code=ErrorCode.API_KEY_REVOKED,
        )

    return {
        "success": True,
        "message": "API key revoked successfully",
        "data": {"key_id": key_id, "revoked_at": datetime.now(timezone.utc).isoformat()},
    }
