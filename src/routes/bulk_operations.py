"""
Bulk Operations Routes - Phase 2 Implementation

Handles bulk operations for users, projects, and other entities
for efficient mass management in the authentication system.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Form
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.activity_logger import ActivityLogger, ActivityType
from src.Util.auth_lifecycle import revoke_user_auth_state
from src.Util.bulk_operations import (
    bulk_update_users, bulk_delete_users,
    bulk_assign_roles, bulk_add_users_to_group
)
from src.Util.db import validate_session, get_user_by_hash
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
        user_hashes: List[str] = Form(...),
        is_active: Optional[bool] = Form(None),
        user_type: Optional[str] = Form(None),
        force_password_reset: Optional[bool] = Form(None),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Update multiple users at once.
    
    **Admin access required**: Only admin users can perform bulk updates.
    **Phase 2 Implementation**: Bulk user updates with transaction support
    
    Args:
        user_hashes: List of user hashes to update
        is_active: Set active status for all users
        user_type: Set user type for all users
        force_password_reset: Unsupported compatibility field; rejected when present
        
    Returns:
        Success/error count with details
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
        lambda: bulk_update_users(user_updates, updated_by=str(current_user.id)),
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
        user_hashes: List[str] = Form(...),
        confirm_deletion: bool = Form(False),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Delete multiple users.
    
    **Admin access required**: Only admin users can perform bulk deletions.  
    **Phase 2 Implementation**: Bulk user deletions with safety checks
    
    Args:
        user_hashes: List of user hashes to delete
        confirm_deletion: Explicit confirmation required for deletion
        
    Returns:
        Deletion count and any errors
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
        lambda: bulk_delete_users(user_hashes, current_user.id),
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
        project_hash: str,
        user_hashes: List[str] = Form(...),
        role_names: List[str] = Form(...),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Bulk assign roles to users in a project.
    
    **Admin access required**: Only admin users can perform bulk role assignments.
    **Phase 2 Implementation**: Bulk role assignments with validation
    
    Args:
        project_hash: Project identifier
        user_hashes: List of user hashes to assign roles to
        role_names: List of role names to assign
        
    Returns:
        Assignment results with success/error counts
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

    # Perform bulk role assignment
    role_assignments = [{"user_hash": user_hash, "role_name": role_name} for user_hash in user_hashes for role_name
                        in role_names]
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
        user_hashes: List[str] = Form(...),
        group_names: List[str] = Form(...),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Bulk assign users to user groups.
    
    **Admin access required**: Only admin users can perform bulk group assignments.
    **Phase 2 Implementation**: Bulk user group assignments
    
    Args:
        user_hashes: List of user hashes to assign to groups
        group_names: List of group names to assign users to
        
    Returns:
        Assignment results with success/error counts
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

    # Perform bulk group assignment
    result = {}
    for group_name in group_names:
        group_result = handle_db_operation(
            lambda: bulk_add_users_to_group(group_name, user_hashes, current_user.id),
            error_context=f"bulk assignment to group {group_name}"
        )
        if not result:
            result = group_result
        else:
            result['success_count'] += group_result.get('success_count', 0)
            result['error_count'] += group_result.get('error_count', 0)

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
