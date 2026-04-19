"""
User-Managed API Key Routes

Endpoints for authenticated users to create, list, update, and revoke
their own API keys. Users can only manage keys they own.

All endpoints require session authentication (verify_session dependency).
Users can only create keys for projects they have access to.

Prefix: /users/api-keys
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, Query
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


# =============================================================================
# POST /users/api-keys — Create own API key
# =============================================================================

@router.post("")
@log_and_handle_errors(
    operation_name="user_create_api_key",
    activity_type=ActivityType.USER_LOGIN,
    log_success=True,
)
async def user_create_api_key(
    project_hash: str = Form(..., description="Project hash to scope the key to"),
    name: Optional[str] = Form(None, description="Human-readable label for the key"),
    description: Optional[str] = Form(None, description="Optional description"),
    expires_at: Optional[str] = Form(None, description="ISO 8601 expiration timestamp"),
    current_user: dict = Depends(verify_session),
    log_context: LogContext = None,
) -> dict:
    """Create an API key for the authenticated user's own account.

    The user can only create keys for projects they have access to.
    The stored procedure sp_create_api_key validates project access via
    the group chain (including root bypass).
    """
    current_user_id = current_user.get("user_id")

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
    project_hash: Optional[str] = Query(None, description="Filter by project hash"),
    active_only: bool = Query(False, description="Only return active keys"),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    current_user: dict = Depends(verify_session),
    log_context: LogContext = None,
) -> dict:
    """List the authenticated user's own API keys.

    Optionally filter by project hash.
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

@router.get("/{key_id}")
@log_and_handle_errors(
    operation_name="user_get_api_key",
    activity_type=ActivityType.USER_LOGIN,
    log_success=False,
)
async def user_get_api_key(
    key_id: str,
    current_user: dict = Depends(verify_session),
    log_context: LogContext = None,
) -> dict:
    """Get details of the authenticated user's own API key.

    Never returns the secret_hash or full token.
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

@router.put("/{key_id}")
@log_and_handle_errors(
    operation_name="user_update_api_key",
    activity_type=ActivityType.USER_LOGIN,
    log_success=True,
)
async def user_update_api_key(
    key_id: str,
    name: Optional[str] = Form(None, description="New name for the key"),
    description: Optional[str] = Form(None, description="New description"),
    expires_at: Optional[str] = Form(None, description="New expiration (ISO 8601)"),
    current_user: dict = Depends(verify_session),
    log_context: LogContext = None,
) -> dict:
    """Update the authenticated user's own API key.

    Can update name, description, and/or expires_at.
    Extending expires_at past NOW() on an expired key reactivates it.
    """
    current_user_id = current_user.get("user_id")

    # Look up the key first to check ownership and get public_id
    key_data = get_api_key_by_public_id(key_id)
    if not key_data:
        raise NotFoundError(
            message="API key not found",
            error_code=ErrorCode.API_KEY_NOT_FOUND,
        )

    # Assert ownership
    _assert_key_ownership(key_data, current_user_id)

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

@router.delete("/{key_id}")
@log_and_handle_errors(
    operation_name="user_revoke_api_key",
    activity_type=ActivityType.USER_LOGIN,
    log_success=True,
)
async def user_revoke_api_key(
    key_id: str,
    current_user: dict = Depends(verify_session),
    log_context: LogContext = None,
) -> dict:
    """Revoke the authenticated user's own API key.

    Immediately invalidates the Redis cache entry.
    The key cannot be used for authentication after revocation.
    """
    current_user_id = current_user.get("user_id")

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
