"""
Admin-Managed API Key Routes

Endpoints for root and admin users to create, list, update, and revoke
API keys on behalf of other users within their administrative scope.

All endpoints require an access token of a root or admin user
(verify_admin_access dependency); API keys are not accepted here.
Create/update/revoke also require recent authentication. Root users have
unrestricted access; admin users are limited to projects they administer and
need the manage_users permission to create keys for other users.

Prefix: /api-keys
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
    list_project_api_keys,
    update_api_key,
    get_user_by_hash,
    get_project_by_hash,
    is_root_user,
    get_user_type,
    get_user_effective_permissions,
)
from src.Util.db_error_wrapper import handle_db_operation
from src.Util.decorators import log_and_handle_errors
from src.Util.admin_scope import AdminScope, require_admin_scope, resolve_admin_scope, user_in_scope
from src.Util.auth_flow import access_token_session_id, require_recent_reauthentication
from src.Util.error_handler import (
    AuthorizationError,
    ValidationError,
    NotFoundError,
    ErrorCode,
    mask_uuid,
)
from src.Util.log_context_models import LogContext
from src.middleware.authentication import verify_admin_access

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api-keys", tags=["API Keys - Admin"])
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
_ADMIN_SCOPE_403_RESPONSE = {
    "description": "Caller is not root/admin, or the target is outside the admin's scope.",
}


# =============================================================================
# Helpers
# =============================================================================

def _resolve_user_by_hash(user_hash: str):
    """Resolve a user hash to a user record, raising NotFoundError if missing."""
    user = handle_db_operation(
        lambda: get_user_by_hash(user_hash),
        error_context=f"user lookup for hash {mask_uuid(user_hash)}",
        not_found_message=f"User not found: {mask_uuid(user_hash)}",
    )
    return user


def _resolve_project_by_hash(project_hash: str):
    """Resolve a project hash to a project record, raising NotFoundError if missing."""
    project = handle_db_operation(
        lambda: get_project_by_hash(project_hash),
        error_context=f"project lookup for hash {mask_uuid(project_hash)}",
        not_found_message=f"Project not found: {mask_uuid(project_hash)}",
    )
    return project


def _assert_admin_scope_for_project(current_user_id: str, project_id: str, is_root: bool):
    """Assert that the current admin has access to the given project.

    Root users bypass this check. Admin users must have project access.
    """
    if is_root:
        return
    from src.Util.db import check_admin_project_access
    if not check_admin_project_access(current_user_id, project_id):
        raise AuthorizationError(
            message="Access denied: project not in your administrative scope",
            error_code=ErrorCode.ACCESS_DENIED,
            details={"project_id": mask_uuid(str(project_id))},
        )


def _listing_scope(current_user: dict) -> AdminScope:
    """Admin scope for key listings: root sees every project, admin users their assigned ones.

    ``verify_admin_access`` also admits consumers whose session carries the ``admin``
    permission (a global role can grant it); they have no administrative scope here.
    """
    return require_admin_scope(resolve_admin_scope(current_user.get("user_id")))


def _all_user_keys(owner_user_id: str) -> list:
    """Every key a user owns, newest first, paged through ``list_user_api_keys``."""
    keys: list = []
    offset, page_size = 0, 200
    while True:
        page, total = list_user_api_keys(owner_user_id=owner_user_id, limit=page_size, offset=offset)
        keys.extend(page)
        offset += page_size
        if len(page) < page_size or offset >= total:
            return keys


def _scoped_user_keys(owner_user_id: str, scope: AdminScope, *, project_id=None, limit: int, offset: int):
    """A page of a user's keys restricted to ``scope`` (and to ``project_id`` when given).

    ``total`` counts every matching key, not only this page.
    """
    keys = [
        key for key in _all_user_keys(owner_user_id)
        if scope.allows_project(key.get("project_id"))
        and (project_id is None or str(key.get("project_id")) == str(project_id))
    ]
    return keys[offset:offset + limit], len(keys)


def _assert_manage_users_or_self(
    current_user_id: str,
    target_user_id: str,
    project_id: str,
    is_root: bool,
):
    """Assert that the admin can manage keys for the target user.

    Root users bypass. Self-service is always allowed.
    For other users, the admin needs manage_users effective permission.
    """
    if is_root:
        return
    if current_user_id == target_user_id:
        return  # Self-service allowed

    # Check manage_users permission
    permissions = get_user_effective_permissions(current_user_id, project_id)
    if not permissions or "manage_users" not in permissions:
        raise AuthorizationError(
            message="Access denied: manage_users permission required to create keys for other users",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_permission": "manage_users"},
        )


def _parse_expires_at(expires_at_str: Optional[str]) -> Optional[datetime]:
    """Parse an ISO 8601 expires_at string into a datetime object.

    Returns None if not provided. Raises ValidationError for past dates.
    """
    if not expires_at_str:
        return None

    try:
        # Handle both with and without timezone info
        dt = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        # If naive, assume UTC
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


def _require_recent_reauth_for_admin_api_key_mutation(current_user: dict, operation: str) -> None:
    require_recent_reauthentication(
        user_id=str(current_user.get("user_id") or ""),
        session_token=current_user.get("session_token"),
        session_id=access_token_session_id(current_user.get("session_token")),
        operation=operation,
    )


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
    # Pass through enrichment columns the list/detail stored procedures JOIN in
    # (project name, owner identity) so the dashboard can show per-token context.
    # Only included when present so the create/reveal response shape is unchanged.
    for enrichment_key in (
        "project_name",
        "project_hash",
        "owner_username",
        "owner_user_hash",
        "owner_user_type",
    ):
        if enrichment_key in key_data:
            response[enrichment_key] = key_data.get(enrichment_key)
    if include_token and token:
        response["api_key"] = token
    return response


# =============================================================================
# POST /api-keys — Create API key for a user (admin scope)
# =============================================================================

@router.post(
    "",
    responses={
        401: _RECENT_AUTH_401_RESPONSE,
        403: _ADMIN_SCOPE_403_RESPONSE,
        404: {"description": "Unknown `user_hash` or `project_hash`."},
    },
)
@log_and_handle_errors(
    operation_name="admin_create_api_key",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True,
)
async def admin_create_api_key(
    user_hash: str = Form(..., description="Hash of the user who will own the key."),
    project_hash: str = Form(..., description="Hash of the project the key is scoped to."),
    name: Optional[str] = Form(
        None,
        description="Human-readable label. Defaults to `API Key - <owner username>`.",
    ),
    description: Optional[str] = Form(None, description="Optional free-text description."),
    expires_at: Optional[str] = Form(
        None,
        description=(
            "Optional expiry as ISO 8601 (e.g. `2027-01-01T00:00:00Z`); must be in the future. "
            "Values without a timezone are treated as UTC. Omit for a key that never expires."
        ),
    ),
    current_user: dict = Depends(verify_admin_access),
    log_context: LogContext = None,
) -> dict:
    """Create an API key owned by a given user and scoped to one project.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root or admin user, plus recent authentication
    (a sign-in, or an OAuth reauth of this session, within the
    recent-auth window, 5 minutes by default; refreshing the session does not renew it).
    Root: any user and project. Admin: only projects they administer, and a key
    for another user also needs the `manage_users` permission in that project.

    **Request:** form fields (`application/x-www-form-urlencoded` or
    `multipart/form-data`).

    **Responses:**
    - `200` — `data.api_key` is the full `sk_{public_id}.{secret}` token,
      returned only in this response (the server keeps an HMAC-SHA-256 hash).
    - `400` — malformed or past `expires_at`.
    - `401` — missing/invalid access token, or recent authentication required
      (`AUTH_1008`).
    - `403` — not root/admin, project outside the admin's scope, or
      `manage_users` missing.
    - `404` — unknown `user_hash` or `project_hash`.
    - `409` (`CONF_5005`) — for non-root callers, the owner is inactive or has
      no access to the project, so the database refuses the key.
    """
    current_user_id = current_user.get("user_id")
    _require_recent_reauth_for_admin_api_key_mutation(current_user, "admin_create_api_key")
    is_root = is_root_user(current_user_id)

    # Resolve target user
    target_user = _resolve_user_by_hash(user_hash)

    # Resolve project
    project = _resolve_project_by_hash(project_hash)

    # Assert admin scope for the project
    _assert_admin_scope_for_project(current_user_id, project.id, is_root)

    # Assert manage_users or self-service
    _assert_manage_users_or_self(current_user_id, target_user.id, project.id, is_root)

    # Parse expiration
    expires_at_dt = _parse_expires_at(expires_at)

    # Auto-generate name if not provided
    if not name:
        name = f"API Key - {target_user.username}"

    # Generate the token (Python side)
    token_data = generate_api_key_token()

    # Create the key via stored procedure (which validates project access)
    key_result = create_api_key(
        key_id=token_data["public_id"],  # Use public_id as the VARCHAR(64) key
        public_id=token_data["public_id"],
        project_id=project.id,
        owner_user_id=target_user.id,
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
        from src.Util.error_handler import InternalError
        raise InternalError(
            message="Failed to create API key",
            error_code=ErrorCode.INTERNAL_ERROR,
        )

    return {
        "success": True,
        "message": "API key created successfully",
        "data": _format_key_response(key_result, include_token=True, token=token_data["token"]),
    }


# =============================================================================
# GET /api-keys — List keys within admin's scope
# =============================================================================

@router.get("")
@log_and_handle_errors(
    operation_name="admin_list_api_keys",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False,
)
async def admin_list_api_keys(
    user_hash: Optional[str] = Query(
        None,
        description="List this user's keys. Admins only see the keys in projects they administer.",
    ),
    project_hash: Optional[str] = Query(
        None,
        description="List this project's keys. With `user_hash`, only that user's keys in this project.",
    ),
    active_only: bool = Query(
        False,
        description="Only active keys. Honoured for project listings only, not for `user_hash` listings.",
    ),
    limit: int = Query(50, ge=1, le=200, description="Page size (1-200)."),
    offset: int = Query(0, ge=0, description="Number of keys to skip."),
    current_user: dict = Depends(verify_admin_access),
    log_context: LogContext = None,
) -> dict:
    """List API keys (metadata only) by user or project within the caller's scope.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root or admin user. Consumers get `403`, even
    when their global role grants the `admin` permission.

    **Behavior:**
    - `user_hash` and `project_hash`: that user's keys in that project.
      Admins must administer the project.
    - Only `user_hash`: that user's keys; for admins only the keys in projects
      they administer, and the user must reach at least one of those projects.
    - Only `project_hash`: that project's keys; admins must administer it.
    - Root with neither filter: `400`.
    - Admin with neither filter: keys from every project the admin administers
      (each project paged with the same `limit`/`offset`, concatenated, cut to
      `limit`; `total` is the sum).
    - `active_only` applies to project listings only; `user_hash` listings
      always include revoked and expired keys. For `user_hash` listings
      `total` counts every matching key.

    **Responses:** `200` with `data.keys`, `data.total`, `data.limit`,
    `data.offset`; `400` as above; `403` outside the admin's scope; `404` for an
    unknown `user_hash` or `project_hash`.
    """
    current_user_id = current_user.get("user_id")
    scope = _listing_scope(current_user)
    is_root = scope.is_root

    # If project_hash filter provided, resolve and check scope
    target_project_id = None
    if project_hash:
        project = _resolve_project_by_hash(project_hash)
        _assert_admin_scope_for_project(current_user_id, project.id, is_root)
        target_project_id = project.id

    # A user filter lists that user's keys, narrowed to the project filter and,
    # for admins, to the projects they administer.
    if user_hash:
        target_user = _resolve_user_by_hash(user_hash)
        if target_project_id is None and not user_in_scope(scope, target_user.id):
            raise AuthorizationError(
                message="Access denied: user not in your administrative scope",
                error_code=ErrorCode.ACCESS_DENIED,
            )
        keys, total = _scoped_user_keys(
            target_user.id, scope, project_id=target_project_id, limit=limit, offset=offset,
        )
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

    if target_project_id is None and not is_root:
        # Admin without filters: every project the admin administers
        admin_project_ids = sorted(scope.project_ids)
        if not admin_project_ids:
            return {
                "success": True,
                "message": "No keys found",
                "data": {
                    "keys": [],
                    "total": 0,
                    "limit": limit,
                    "offset": offset,
                },
            }
        # For admin without project filter, we list per-project
        # Aggregate results across all admin projects
        all_keys = []
        total = 0
        for admin_project_id in admin_project_ids:
            keys, count = list_project_api_keys(
                project_id=admin_project_id,
                limit=limit,
                offset=offset,
                active_only=active_only,
            )
            all_keys.extend(keys)
            total += count
        return {
            "success": True,
            "message": "API keys retrieved successfully",
            "data": {
                "keys": [_format_key_response(k) for k in all_keys[:limit]],
                "total": total,
                "limit": limit,
                "offset": offset,
            },
        }

    # Root or admin with specific project filter
    if target_project_id:
        keys, total = list_project_api_keys(
            project_id=target_project_id,
            limit=limit,
            offset=offset,
            active_only=active_only,
        )
    else:
        # There is no "list all keys" procedure: root must name a user or project.
        raise ValidationError(
            message="Root users must provide at least user_hash or project_hash filter",
            error_code=ErrorCode.INVALID_INPUT,
            details={"required": "user_hash or project_hash"},
        )

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
# GET /api-keys/{key_id} — Get key details
# =============================================================================

@router.get("/{key_id}")
@log_and_handle_errors(
    operation_name="admin_get_api_key",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False,
)
async def admin_get_api_key(
    key_id: Annotated[str, Path(description=_KEY_ID_DESCRIPTION)],
    current_user: dict = Depends(verify_admin_access),
    log_context: LogContext = None,
) -> dict:
    """Get metadata for any API key in the caller's scope (never the secret or its hash).

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root or admin user. Admins must administer the
    key's project.

    **Responses:** `200` with key metadata in `data`, including project and
    owner details; `403` when the key's project is outside the admin's scope;
    `404` for an unknown key.
    """
    current_user_id = current_user.get("user_id")
    is_root = is_root_user(current_user_id)

    # Look up the key
    key_data = get_api_key_by_public_id(key_id)
    if not key_data:
        raise NotFoundError(
            message=f"API key not found: {mask_uuid(key_id)}",
            error_code=ErrorCode.API_KEY_NOT_FOUND,
        )

    # Assert admin scope for the key's project
    _assert_admin_scope_for_project(current_user_id, key_data["project_id"], is_root)

    return {
        "success": True,
        "message": "API key retrieved successfully",
        "data": _format_key_response(key_data),
    }


# =============================================================================
# PUT /api-keys/{key_id} — Update key
# =============================================================================

@router.put(
    "/{key_id}",
    responses={401: _RECENT_AUTH_401_RESPONSE, 403: _ADMIN_SCOPE_403_RESPONSE},
)
@log_and_handle_errors(
    operation_name="admin_update_api_key",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True,
)
async def admin_update_api_key(
    key_id: Annotated[str, Path(description=_KEY_ID_DESCRIPTION)],
    name: Optional[str] = Form(None, description="New label for the key."),
    description: Optional[str] = Form(None, description="New description."),
    expires_at: Optional[str] = Form(
        None,
        description="New expiry as ISO 8601; must be in the future. Values without a timezone are treated as UTC.",
    ),
    current_user: dict = Depends(verify_admin_access),
    log_context: LogContext = None,
) -> dict:
    """Update the name, description, or expiry of any API key in the caller's scope.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root or admin user, plus recent authentication
    (a sign-in, or an OAuth reauth of this session, within the
    recent-auth window, 5 minutes by default; refreshing the session does not renew it).
    Admins must administer the key's project; no `manage_users` check applies.

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
    - `403` — not root/admin, or key's project outside the admin's scope.
    - `404` — unknown key.
    """
    current_user_id = current_user.get("user_id")
    _require_recent_reauth_for_admin_api_key_mutation(current_user, "admin_update_api_key")
    is_root = is_root_user(current_user_id)

    # Look up the key first to check scope and get public_id for cache invalidation
    key_data = get_api_key_by_public_id(key_id)
    if not key_data:
        raise NotFoundError(
            message=f"API key not found: {mask_uuid(key_id)}",
            error_code=ErrorCode.API_KEY_NOT_FOUND,
        )

    # Assert admin scope
    _assert_admin_scope_for_project(current_user_id, key_data["project_id"], is_root)
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
            message=f"API key not found: {mask_uuid(key_id)}",
            error_code=ErrorCode.API_KEY_NOT_FOUND,
        )

    return {
        "success": True,
        "message": "API key updated successfully",
        "data": _format_key_response(updated),
    }


# =============================================================================
# DELETE /api-keys/{key_id} — Revoke key
# =============================================================================

@router.delete(
    "/{key_id}",
    responses={401: _RECENT_AUTH_401_RESPONSE, 403: _ADMIN_SCOPE_403_RESPONSE},
)
@log_and_handle_errors(
    operation_name="admin_revoke_api_key",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True,
)
async def admin_revoke_api_key(
    key_id: Annotated[str, Path(description=_KEY_ID_DESCRIPTION)],
    revoke_reason: Optional[str] = Form(
        None,
        description="Optional reason stored with the revocation (max 255 characters).",
    ),
    current_user: dict = Depends(verify_admin_access),
    log_context: LogContext = None,
) -> dict:
    """Revoke any API key in the caller's scope.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root or admin user, plus recent authentication
    (a sign-in, or an OAuth reauth of this session, within the
    recent-auth window, 5 minutes by default; refreshing the session does not renew it).
    Admins must administer the key's project.

    **Request:** optional form body with `revoke_reason`; the request may also
    be sent without a body.

    **Responses:**
    - `200` — revoked (`data.key_id`, `data.revoked_at`). The cached validation
      entry is dropped, so the key stops authenticating immediately.
    - `401` — missing/invalid access token, or recent authentication required
      (`AUTH_1008`).
    - `403` — not root/admin, or key's project outside the admin's scope.
    - `404` — unknown key.
    - `400` (`AUTH_1012`) — the key is already inactive (revoked, or
      deactivated after expiring).
    """
    current_user_id = current_user.get("user_id")
    _require_recent_reauth_for_admin_api_key_mutation(current_user, "admin_revoke_api_key")
    is_root = is_root_user(current_user_id)

    # Look up the key first to check scope and get public_id
    key_data = get_api_key_by_public_id(key_id)
    if not key_data:
        raise NotFoundError(
            message=f"API key not found: {mask_uuid(key_id)}",
            error_code=ErrorCode.API_KEY_NOT_FOUND,
        )

    # Assert admin scope
    _assert_admin_scope_for_project(current_user_id, key_data["project_id"], is_root)

    # Revoke with cache invalidation
    result = revoke_api_key_with_cache_invalidation(
        key_id=key_id,
        public_id=key_data["public_id"],
        revoked_by=current_user_id,
        revoke_reason=revoke_reason,
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


# =============================================================================
# GET /api-keys/users/{user_hash} — List all keys for a specific user
# =============================================================================

@router.get("/users/{user_hash}")
@log_and_handle_errors(
    operation_name="admin_list_user_api_keys",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False,
)
async def admin_list_user_api_keys(
    user_hash: Annotated[str, Path(description="Hash of the key owner.")],
    active_only: bool = Query(
        False,
        description="Accepted but currently ignored: revoked and expired keys are always included.",
    ),
    limit: int = Query(50, ge=1, le=200, description="Page size (1-200)."),
    offset: int = Query(0, ge=0, description="Number of keys to skip."),
    current_user: dict = Depends(verify_admin_access),
    log_context: LogContext = None,
) -> dict:
    """List the API keys (metadata only) owned by one user.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root or admin user; consumers get `403` even
    when their global role grants the `admin` permission. Admins need the user
    to reach at least one project they administer, and only see keys scoped to
    projects they administer.

    **Responses:** `200` with `data.user_hash`, `data.username`, `data.keys`,
    `data.total`, `data.limit`, `data.offset` (`total` counts every key visible
    to the caller); `403` when the user shares no administered project with the
    admin; `404` for an unknown `user_hash`.
    """
    scope = _listing_scope(current_user)

    # Resolve target user
    target_user = _resolve_user_by_hash(user_hash)

    # For non-root, verify the user is in admin's scope
    if not user_in_scope(scope, target_user.id):
        raise AuthorizationError(
            message="Access denied: user not in your administrative scope",
            error_code=ErrorCode.ACCESS_DENIED,
        )

    keys, total = _scoped_user_keys(target_user.id, scope, limit=limit, offset=offset)

    return {
        "success": True,
        "message": "API keys retrieved successfully",
        "data": {
            "user_hash": target_user.user_hash,
            "username": target_user.username,
            "keys": [_format_key_response(k) for k in keys],
            "total": total,
            "limit": limit,
            "offset": offset,
        },
    }


# =============================================================================
# GET /api-keys/projects/{project_hash} — List all keys for a specific project
# =============================================================================

@router.get("/projects/{project_hash}")
@log_and_handle_errors(
    operation_name="admin_list_project_api_keys",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False,
)
async def admin_list_project_api_keys(
    project_hash: Annotated[str, Path(description="Hash of the project whose keys to list.")],
    active_only: bool = Query(False, description="Only return active keys."),
    limit: int = Query(50, ge=1, le=200, description="Page size (1-200)."),
    offset: int = Query(0, ge=0, description="Number of keys to skip."),
    current_user: dict = Depends(verify_admin_access),
    log_context: LogContext = None,
) -> dict:
    """List the API keys (metadata only) scoped to one project.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root or admin user. Admins must administer the
    project.

    **Responses:** `200` with `data.project_hash`, `data.project_name`,
    `data.keys` (with owner details), `data.total`, `data.limit`,
    `data.offset`; `403` when the project is outside the admin's scope; `404`
    for an unknown `project_hash`.
    """
    current_user_id = current_user.get("user_id")
    is_root = is_root_user(current_user_id)

    # Resolve project and check scope
    project = _resolve_project_by_hash(project_hash)
    _assert_admin_scope_for_project(current_user_id, project.id, is_root)

    keys, total = list_project_api_keys(
        project_id=project.id,
        limit=limit,
        offset=offset,
        active_only=active_only,
    )

    return {
        "success": True,
        "message": "API keys retrieved successfully",
        "data": {
            "project_hash": project.project_hash,
            "project_name": project.project_name,
            "keys": [_format_key_response(k) for k in keys],
            "total": total,
            "limit": limit,
            "offset": offset,
        },
    }
