"""
Bulk Operations Routes - Phase 2 Implementation

Handles bulk operations for users, projects, and other entities
for efficient mass management in the authentication system.
"""

import logging
from datetime import datetime, timezone
from typing import Annotated, Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Form, Path
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.activity_logger import ActivityLogger, ActivityType
from src.Util.auth_lifecycle import revoke_user_auth_state
from src.Util.bulk_operations import (
    bulk_update_users, bulk_delete_users,
    bulk_assign_roles, bulk_add_users_to_group
)
from src.Util.db import validate_session, get_user_by_hash, get_user_group_by_name, is_root_user
from src.Util.db import db_global_roles
from src.Util.admin_scope import (
    RESERVED_PERMISSION_NAMES, require_admin_scope, resolve_admin_scope, role_grants_reserved_permission,
)
from src.Util.error_handler import (
    AuthenticationError, AuthorizationError, ValidationError,
    NotFoundError, InternalError, ErrorCode, mask_uuid,
    create_unsupported_password_control_error,
)
from src.Util.db_error_wrapper import handle_db_operation

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/admin", tags=["Bulk Operations"])
security = HTTPBearerOrCookie()


# Note: All endpoints use Form data instead of JSON/Pydantic models for consistency


def _revoke_bulk_deactivated_auth_state(result: Dict[str, Any]) -> None:
    """Revoke auth lifecycle state for users successfully deactivated in bulk."""
    for item in result.get("results", []):
        if not item.get("success"):
            continue
        user_id = item.get("user_id")
        if user_id is None:
            continue
        revoke_user_auth_state(str(user_id), reason="bulk_user_deactivated")


@router.post("/users/bulk-update")
async def bulk_update_users_endpoint(
        user_hashes: List[str] = Form(..., description="Public hashes of the users to update (1-100; repeat the field)."),
        is_active: Optional[bool] = Form(None, description="Set every listed user active (`true`) or inactive (`false`)."),
        user_type: Optional[str] = Form(
            None, description="Set every listed user's type: `root`, `admin` or `consumer`. Root callers only."
        ),
        force_password_reset: Optional[bool] = Form(
            None, description="Unsupported; any value is rejected with 400. Use reset-link password recovery instead."
        ),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Apply the same `is_active` and/or `user_type` change to up to 100 users.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root or admin user whose session permissions include `admin` or
    `manage_users`; otherwise 403. Root and admin sessions carry these permissions by
    default. Changing `user_type` additionally requires a root user.

    **Request:** form fields (`application/x-www-form-urlencoded` or `multipart/form-data`);
    list fields are sent by repeating the field, e.g. `user_hashes=a&user_hashes=b`.
    At least one of `is_active` or `user_type` is required.

    **Effect:** users are processed one by one. Nobody may deactivate their own account,
    and admins may only change non-root users who reach one of their assigned projects;
    other users fail individually and are left unchanged. Deactivated users have their
    sessions and refresh families revoked, and a changed `user_type` signs the user out.

    **Responses:** 200 even when some users fail: see `summary`, per-user `results` and
    `errors`. 400 for an empty or oversized list, no update field, an invalid
    `user_type`, or `force_password_reset`.
    """
    session_token = credentials.credentials
    session_data = handle_db_operation(
        lambda: validate_session(session_token),
        error_context="session validation for bulk update"
    )

    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    # Check admin permissions
    current_user = handle_db_operation(
        lambda: get_user_by_hash(session_data.user_hash),
        error_context="get current user for bulk update",
        not_found_message=f"User not found: {mask_uuid(session_data.user_hash)}"
    )
    user_permissions = getattr(session_data, 'permissions', [])

    if 'admin' not in user_permissions and 'manage_users' not in user_permissions:
        raise AuthorizationError(
            message="Admin permission required for bulk operations",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_permission": "admin or manage_users"}
        )
    # Session permissions alone are not enough: like the single-user routes, only root
    # and admin users manage users, and admins only inside their scope.
    scope = require_admin_scope(resolve_admin_scope(current_user.id))

    # Only root users may change user_type via bulk update — mirrors the
    # root-only guard on PATCH /users/{user_hash}/type and prevents privilege
    # escalation (e.g. setting user_type='root') by non-root admins.
    if user_type is not None and not scope.is_root:
        raise AuthorizationError(
            message="Root user access required to change user types",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_user_type": "root"}
        )

    # Validate input
    if not user_hashes:
        raise ValidationError(
            message="At least one user hash is required",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"field": "user_hashes"}
        )

    if len(user_hashes) > 100:
        raise ValidationError(
            message="Maximum 100 users can be updated at once",
            error_code=ErrorCode.INVALID_LENGTH,
            details={"max_length": 100, "provided_length": len(user_hashes)}
        )

    # Validate user type if provided
    if user_type and user_type not in ['root', 'admin', 'consumer']:
        raise ValidationError(
            message="Invalid user type",
            error_code=ErrorCode.INVALID_ENUM_VALUE,
            details={"field": "user_type", "allowed_values": ["root", "admin", "consumer"]}
        )

    if force_password_reset is not None:
        raise create_unsupported_password_control_error("force_password_reset")

    # Build updates dictionary
    updates = {}
    if is_active is not None:
        updates['is_active'] = is_active
    if user_type:
        updates['user_type'] = user_type

    if not updates:
        raise ValidationError(
            message="At least one update field is required",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"required_fields": ["is_active", "user_type"]}
        )

    user_updates = [
        {"user_hash": user_hash, "updates": dict(updates)}
        for user_hash in user_hashes
    ]

    # Perform bulk update
    result = handle_db_operation(
        lambda: bulk_update_users(user_updates, updated_by=str(current_user.id), scope=scope),
        error_context="bulk user update operation"
    )

    if updates.get('is_active') is False:
        handle_db_operation(
            lambda: _revoke_bulk_deactivated_auth_state(result),
            error_context="bulk user auth revocation"
        )

    # Log the activity
    ActivityLogger.log_bulk_user_update(
        current_user.id,
        count=result['success_count'],
        project_id=getattr(session_data, 'project_id', None)
    )

    logger.info(
        f"Bulk user update by {current_user.username}: {result['success_count']} succeeded, {result['error_count']} failed")

    return {
        "success": True,
        "message": f"Bulk update completed: {result['success_count']} succeeded, {result['error_count']} failed",
        "summary": {
            "total_requested": len(user_hashes),
            "success_count": result['success_count'],
            "error_count": result['error_count'],
            "skipped_count": result.get('skipped_count', 0)
        },
        "updates_applied": updates,
        "results": result['results'],
        "errors": result.get('errors', []),
        "performed_by": current_user.username,
        "performed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }


@router.post("/users/bulk-delete")
async def bulk_delete_users_endpoint(
        user_hashes: List[str] = Form(..., description="Public hashes of the users to delete (1-50; repeat the field)."),
        confirm_deletion: bool = Form(False, description="Must be `true`; otherwise the request is rejected with 400."),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Delete up to 50 users in one request.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root or admin user whose session permissions include `admin` or
    `manage_users`; otherwise 403. Root and admin sessions carry these permissions by
    default.

    **Request:** form fields (`application/x-www-form-urlencoded` or `multipart/form-data`);
    list fields are sent by repeating the field, e.g. `user_hashes=a&user_hashes=b`.
    `confirm_deletion=true` is required.

    **Effect:** users are soft-deleted one by one and have their sessions and refresh
    families revoked. Root users are never deleted and are reported as errors instead;
    nobody may delete their own account, and admins may only delete users who reach one
    of their assigned projects.

    **Responses:** 200 with `summary` (`success_count`, `error_count`, and
    `protected_count` for root users skipped), per-user `results`, `errors` and
    `warnings` (a user was deleted but their session revocation failed), even when some
    deletions fail. 400 without confirmation or for an empty or oversized list.
    """
    session_token = credentials.credentials
    session_data = handle_db_operation(
        lambda: validate_session(session_token),
        error_context="session validation for bulk delete"
    )

    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    # Check admin permissions
    current_user = handle_db_operation(
        lambda: get_user_by_hash(session_data.user_hash),
        error_context="get current user for bulk delete",
        not_found_message=f"User not found: {mask_uuid(session_data.user_hash)}"
    )
    user_permissions = getattr(session_data, 'permissions', [])

    if 'admin' not in user_permissions and 'manage_users' not in user_permissions:
        raise AuthorizationError(
            message="Admin permission required for bulk operations",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_permission": "admin or manage_users"}
        )
    scope = require_admin_scope(resolve_admin_scope(current_user.id))

    # Safety checks
    if not confirm_deletion:
        raise ValidationError(
            message="Deletion must be explicitly confirmed",
            error_code=ErrorCode.INVALID_INPUT,
            details={"field": "confirm_deletion", "required_value": True}
        )

    if not user_hashes:
        raise ValidationError(
            message="At least one user hash is required",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"field": "user_hashes"}
        )

    if len(user_hashes) > 50:
        raise ValidationError(
            message="Maximum 50 users can be deleted at once",
            error_code=ErrorCode.INVALID_LENGTH,
            details={"max_length": 50, "provided_length": len(user_hashes)}
        )

    # Perform bulk deletion
    result = handle_db_operation(
        lambda: bulk_delete_users(user_hashes, current_user.id, scope=scope),
        error_context="bulk user deletion operation"
    )

    # Log the activity
    ActivityLogger.log_bulk_user_delete(
        current_user.id,
        count=result['success_count'],
        project_id=getattr(session_data, 'project_id', None)
    )

    logger.info(
        f"Bulk user deletion by {current_user.username}: {result['success_count']} succeeded, {result['error_count']} failed")

    return {
        "success": True,
        "message": f"Bulk deletion completed: {result['success_count']} deleted, {result['error_count']} failed",
        "summary": {
            "total_requested": len(user_hashes),
            "success_count": result['success_count'],
            "error_count": result['error_count'],
            "protected_count": result.get('protected_count', 0)
        },
        "results": result['results'],
        "errors": result.get('errors', []),
        "warnings": result.get('warnings', []),
        "performed_by": current_user.username,
        "performed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }


@router.post("/projects/{project_hash}/bulk-assign-roles")
async def bulk_assign_roles_to_project_users(
        project_hash: Annotated[str, Path(description="Public hash of the project the request is scoped to.")],
        user_hashes: List[str] = Form(..., description="Public hashes of the users to update (1-100; repeat the field)."),
        role_names: List[str] = Form(
            ..., description="Names of the roles to grant to every listed user (repeat the field)."
        ),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Grant the listed roles, by name, to each listed user, recorded against a project.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) whose session permissions include `admin`; otherwise 403. Root and
    admin sessions carry this permission by default.

    **Request:** form fields (`application/x-www-form-urlencoded` or `multipart/form-data`);
    list fields are sent by repeating the field, e.g. `user_hashes=a&user_hashes=b`.

    **Effect:** roles belong to the global role system, so a grant is not limited to the
    project; the project is used for validation and the audit trail. A user holds a single
    global role, so when several roles are listed each user ends up with the last one.

    Only root may assign a role whose permission groups contain a reserved permission name
    (`admin`, `manage_users`, ...; see `POST /roles/permissions`) or replace such a role that a
    listed user currently holds (`details.user_hashes`), and non-root callers may not list
    themselves; any of these returns 403 and nothing is assigned.

    **Responses:** 200 with `summary`, per-assignment `results` and `errors`. 400 for
    missing lists or more than 100 users; 403 as above; 404 if the project does not exist or
    any role name is unknown (`NF_4007`, `details.role_names`), in which case nothing is
    assigned.
    """
    session_token = credentials.credentials
    session_data = handle_db_operation(
        lambda: validate_session(session_token),
        error_context="session validation for bulk role assignment"
    )

    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    # Check admin permissions
    current_user = handle_db_operation(
        lambda: get_user_by_hash(session_data.user_hash),
        error_context="get current user for bulk role assignment",
        not_found_message=f"User not found: {mask_uuid(session_data.user_hash)}"
    )
    user_permissions = getattr(session_data, 'permissions', [])

    if 'admin' not in user_permissions:
        raise AuthorizationError(
            message="Admin permission required for bulk role assignments",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_permission": "admin"}
        )

    # Validate input
    if not user_hashes or not role_names:
        raise ValidationError(
            message="User hashes and role names are required",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"required_fields": ["user_hashes", "role_names"]}
        )

    if len(user_hashes) > 100:
        raise ValidationError(
            message="Maximum 100 users can be assigned at once",
            error_code=ErrorCode.INVALID_LENGTH,
            details={"max_length": 100, "provided_length": len(user_hashes)}
        )

    # Get project
    from src.Util.db import get_project_by_hash
    project = handle_db_operation(
        lambda: get_project_by_hash(project_hash),
        error_context="get project for bulk role assignment",
        not_found_message=f"Project not found: {mask_uuid(project_hash)}"
    )

    # Roles are requested by name; the helper assigns by id. Resolve every name before
    # writing so an unknown role fails the request instead of part of it.
    roles = {role_name: db_global_roles.get_role_by_name(role_name) for role_name in dict.fromkeys(role_names)}
    unknown_roles = [role_name for role_name, role in roles.items() if not role]
    if unknown_roles:
        raise NotFoundError(
            message="Role not found",
            error_code=ErrorCode.ROLE_NOT_FOUND,
            details={"role_names": unknown_roles}
        )

    # Same rules as PUT /roles/users/{user_hash}/role: routers trust reserved permission
    # names in session permissions, so only root may hand out a role granting one, and
    # non-root callers may not change their own role.
    if not is_root_user(current_user.id):
        reserved_roles = [name for name, role in roles.items() if role_grants_reserved_permission(db_global_roles, role)]
        if reserved_roles:
            raise AuthorizationError(
                message="Only root users may assign roles granting reserved permissions",
                error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
                details={"role_names": reserved_roles, "reserved_permissions": sorted(RESERVED_PERMISSION_NAMES)}
            )
        if current_user.user_hash in user_hashes:
            raise AuthorizationError(
                message="You cannot change your own role",
                error_code=ErrorCode.OPERATION_NOT_ALLOWED,
                details={"reason": "own_role"}
            )
        # Replacing a role that grants a reserved name is root-only too (a demotion path).
        reserved_by_role_id: Dict[Any, bool] = {}

        def current_role_grants_reserved(user_hash: str) -> bool:
            target = get_user_by_hash(user_hash)
            current_role = db_global_roles.get_user_role(target.id) if target else None
            if not current_role:
                return False
            if current_role["id"] not in reserved_by_role_id:
                reserved_by_role_id[current_role["id"]] = role_grants_reserved_permission(db_global_roles, current_role)
            return reserved_by_role_id[current_role["id"]]

        protected_users = [user_hash for user_hash in dict.fromkeys(user_hashes) if current_role_grants_reserved(user_hash)]
        if protected_users:
            raise AuthorizationError(
                message="Only root users may replace a role granting reserved permissions",
                error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
                details={"user_hashes": protected_users, "reserved_permissions": sorted(RESERVED_PERMISSION_NAMES)}
            )

    # Perform bulk role assignment
    role_assignments = [
        {"user_hash": user_hash, "role_id": roles[role_name]["id"], "role_name": role_name}
        for user_hash in user_hashes
        for role_name in role_names
    ]
    result = handle_db_operation(
        lambda: bulk_assign_roles(project.project_hash, role_assignments, current_user.id),
        error_context="bulk role assignment operation"
    )

    # Log the activity
    ActivityLogger.log_bulk_role_assignment(
        current_user.id,
        count=result['success_count'],
        project_id=project.id
    )

    logger.info(
        f"Bulk role assignment by {current_user.username} in project {project.project_name}: {result['success_count']} succeeded")

    return {
        "success": True,
        "message": f"Bulk role assignment completed: {result['success_count']} succeeded, {result['error_count']} failed",
        "project": {
            "project_hash": project.project_hash,
            "project_name": project.project_name
        },
        "roles_assigned": role_names,
        "summary": {
            "total_requested": len(user_hashes),
            "success_count": result['success_count'],
            "error_count": result['error_count']
        },
        "results": result['results'],
        "errors": result.get('errors', []),
        "performed_by": current_user.username,
        "performed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }


@router.post("/user-groups/bulk-assign")
async def bulk_assign_users_to_groups(
        user_hashes: List[str] = Form(..., description="Public hashes of the users to add (1-100; repeat the field)."),
        group_names: List[str] = Form(
            ...,
            description="Names of the user groups to add the users to (repeat the field).",
        ),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Add every listed user to every listed user group.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) whose session permissions include `admin`; otherwise 403. Root and
    admin sessions carry this permission by default.

    **Request:** form fields (`application/x-www-form-urlencoded` or `multipart/form-data`);
    list fields are sent by repeating the field, e.g. `user_hashes=a&user_hashes=b`.

    **Responses:** 200 with `summary`, per-user-per-group `results` and `errors`, even
    when some assignments fail. 400 for missing lists or more than 100 users; 404 if any
    group name is unknown or inactive (`NF_4003`, `details.group_names`), in which case
    nothing is assigned.
    """
    session_token = credentials.credentials
    session_data = handle_db_operation(
        lambda: validate_session(session_token),
        error_context="session validation for bulk group assignment"
    )

    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    # Check admin permissions
    current_user = handle_db_operation(
        lambda: get_user_by_hash(session_data.user_hash),
        error_context="get current user for bulk group assignment",
        not_found_message=f"User not found: {mask_uuid(session_data.user_hash)}"
    )
    user_permissions = getattr(session_data, 'permissions', [])

    if 'admin' not in user_permissions:
        raise AuthorizationError(
            message="Admin permission required for bulk group assignments",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_permission": "admin"}
        )

    # Validate input
    if not user_hashes or not group_names:
        raise ValidationError(
            message="User hashes and group names are required",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"required_fields": ["user_hashes", "group_names"]}
        )

    if len(user_hashes) > 100:
        raise ValidationError(
            message="Maximum 100 users can be assigned at once",
            error_code=ErrorCode.INVALID_LENGTH,
            details={"max_length": 100, "provided_length": len(user_hashes)}
        )

    # Groups are requested by name; the helper looks them up by hash. Resolve every
    # name before writing so an unknown group fails the request instead of part of it.
    groups = {group_name: get_user_group_by_name(group_name) for group_name in dict.fromkeys(group_names)}
    unknown_groups = [group_name for group_name, group in groups.items() if not group]
    if unknown_groups:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_names": unknown_groups}
        )

    # Perform bulk group assignment
    result = {"success_count": 0, "error_count": 0, "results": [], "errors": []}
    for group in groups.values():
        group_result = handle_db_operation(
            lambda: bulk_add_users_to_group(group.group_hash, user_hashes, current_user.id),
            error_context=f"bulk assignment to group {group.group_name}"
        )
        result['success_count'] += group_result.get('success_count', 0)
        result['error_count'] += group_result.get('error_count', 0)
        result['results'].extend(group_result.get('results', []))
        result['errors'].extend(group_result.get('errors', []))

    # Log the activity
    ActivityLogger.log_bulk_group_assignment(
        current_user.id,
        count=result['success_count'],
        project_id=getattr(session_data, 'project_id', None)
    )

    logger.info(
        f"Bulk group assignment by {current_user.username}: {result['success_count']} users assigned to groups")

    return {
        "success": True,
        "message": f"Bulk group assignment completed: {result['success_count']} succeeded, {result['error_count']} failed",
        "groups_assigned": group_names,
        "summary": {
            "total_requested": len(user_hashes),
            "success_count": result['success_count'],
            "error_count": result['error_count']
        },
        "results": result['results'],
        "errors": result.get('errors', []),
        "performed_by": current_user.username,
        "performed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }
