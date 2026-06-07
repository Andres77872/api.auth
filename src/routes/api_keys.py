"""
Admin-Managed API Key Routes

Endpoints for root and admin users to create, list, update, and revoke
API keys on behalf of other users within their administrative scope.

All endpoints require admin access (verify_admin_access dependency).
Root users have unrestricted access; admin users are limited to projects
they administer and need manage_users permission for other users' keys.

Prefix: /api-keys
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
    list_project_api_keys,
    update_api_key,
    get_user_by_hash,
    get_project_by_hash,
    get_user_accessible_projects,
    is_root_user,
    get_user_type,
    get_user_effective_permissions,
)
from src.Util.db_error_wrapper import handle_db_operation
from src.Util.decorators import log_and_handle_errors
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

@router.post("")
@log_and_handle_errors(
    operation_name="admin_create_api_key",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True,
)
async def admin_create_api_key(
    user_hash: str = Form(..., description="Target user hash (key owner)"),
    project_hash: str = Form(..., description="Project hash to scope the key to"),
    name: Optional[str] = Form(None, description="Human-readable label for the key"),
    description: Optional[str] = Form(None, description="Optional description"),
    expires_at: Optional[str] = Form(None, description="ISO 8601 expiration timestamp"),
    current_user: dict = Depends(verify_admin_access),
    log_context: LogContext = None,
) -> dict:
    """Create an API key for a user within admin scope.

    Root: can create for any user/project.
    Admin: limited to projects they administer; needs manage_users for other users.
    """
    current_user_id = current_user.get("user_id")
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
    user_hash: Optional[str] = Query(None, description="Filter by user hash"),
    project_hash: Optional[str] = Query(None, description="Filter by project hash"),
    active_only: bool = Query(False, description="Only return active keys"),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    current_user: dict = Depends(verify_admin_access),
    log_context: LogContext = None,
) -> dict:
    """List API keys within the admin's project scope.

    Root: can list all keys with optional filters.
    Admin: only keys for projects they administer.
    """
    current_user_id = current_user.get("user_id")
    is_root = is_root_user(current_user_id)

    # If project_hash filter provided, resolve and check scope
    target_project_id = None
    if project_hash:
        project = _resolve_project_by_hash(project_hash)
        _assert_admin_scope_for_project(current_user_id, project.id, is_root)
        target_project_id = project.id
    elif not is_root:
        # Admin without project filter: get all their projects
        admin_projects = get_user_accessible_projects(current_user_id)
        if not admin_projects:
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
        for proj in admin_projects:
            keys, count = list_project_api_keys(
                project_id=proj.id,
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
        # Root with no project filter — list all keys (use a broad query)
        # Since there's no "list all keys" SP, we return empty and require filters for root
        # Actually, let's use list_project_api_keys with no filter — but the SP requires project_id
        # For root listing all, we need to iterate or use a different approach
        # For now, require at least one filter for root
        if not user_hash:
            raise ValidationError(
                message="Root users must provide at least user_hash or project_hash filter",
                error_code=ErrorCode.INVALID_INPUT,
                details={"required": "user_hash or project_hash"},
            )
        # Fall through to user-based listing below
        keys, total = [], 0

    # If user_hash filter provided, resolve and list by user
    if user_hash:
        target_user = _resolve_user_by_hash(user_hash)
        keys, total = list_user_api_keys(
            owner_user_id=target_user.id,
            limit=limit,
            offset=offset,
        )
        # For non-root, verify the user is in admin's scope
        if not is_root:
            user_projects = get_user_accessible_projects(target_user.id)
            admin_projects = get_user_accessible_projects(current_user_id)
            admin_project_ids = {p.id for p in admin_projects}
            user_project_ids = {p.id for p in user_projects}
            if not admin_project_ids & user_project_ids:
                raise AuthorizationError(
                    message="Access denied: user not in your administrative scope",
                    error_code=ErrorCode.ACCESS_DENIED,
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
    key_id: str,
    current_user: dict = Depends(verify_admin_access),
    log_context: LogContext = None,
) -> dict:
    """Get API key details (no secret_hash).

    Admin must have scope over the key's project.
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

@router.put("/{key_id}")
@log_and_handle_errors(
    operation_name="admin_update_api_key",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True,
)
async def admin_update_api_key(
    key_id: str,
    name: Optional[str] = Form(None, description="New name for the key"),
    description: Optional[str] = Form(None, description="New description"),
    expires_at: Optional[str] = Form(None, description="New expiration (ISO 8601)"),
    current_user: dict = Depends(verify_admin_access),
    log_context: LogContext = None,
) -> dict:
    """Update an API key's name, description, or expiration.

    Admin must have scope over the key's project.
    Extending expires_at past NOW() on an expired key reactivates it.
    """
    current_user_id = current_user.get("user_id")
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

@router.delete("/{key_id}")
@log_and_handle_errors(
    operation_name="admin_revoke_api_key",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True,
)
async def admin_revoke_api_key(
    key_id: str,
    revoke_reason: Optional[str] = Form(None, description="Optional reason for revocation"),
    current_user: dict = Depends(verify_admin_access),
    log_context: LogContext = None,
) -> dict:
    """Revoke an API key.

    Admin must have scope over the key's project.
    Immediately invalidates the Redis cache entry.
    """
    current_user_id = current_user.get("user_id")
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
    user_hash: str,
    active_only: bool = Query(False, description="Only return active keys"),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    current_user: dict = Depends(verify_admin_access),
    log_context: LogContext = None,
) -> dict:
    """List all API keys for a specific user.

    Admin must have at least one project in common with the target user.
    """
    current_user_id = current_user.get("user_id")
    is_root = is_root_user(current_user_id)

    # Resolve target user
    target_user = _resolve_user_by_hash(user_hash)

    # For non-root, verify the user is in admin's scope
    if not is_root:
        user_projects = get_user_accessible_projects(target_user.id)
        admin_projects = get_user_accessible_projects(current_user_id)
        admin_project_ids = {p.id for p in admin_projects}
        user_project_ids = {p.id for p in user_projects}
        if not admin_project_ids & user_project_ids:
            raise AuthorizationError(
                message="Access denied: user not in your administrative scope",
                error_code=ErrorCode.ACCESS_DENIED,
            )

    keys, total = list_user_api_keys(
        owner_user_id=target_user.id,
        limit=limit,
        offset=offset,
    )

    # For non-root, filter keys to only those in admin's projects
    if not is_root:
        admin_projects = get_user_accessible_projects(current_user_id)
        admin_project_ids = {p.id for p in admin_projects}
        keys = [k for k in keys if k.get("project_id") in admin_project_ids]
        total = len(keys)

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
    project_hash: str,
    active_only: bool = Query(False, description="Only return active keys"),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    current_user: dict = Depends(verify_admin_access),
    log_context: LogContext = None,
) -> dict:
    """List all API keys scoped to a specific project.

    Admin must administer the project.
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
