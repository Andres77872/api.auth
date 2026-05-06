"""
Global Role System API Endpoints

This module implements REST API endpoints for the new global role system where:
- Roles are GLOBAL (not project-specific)
- Permissions are GLOBAL (not project-specific)
- Each user has ONE role assigned globally
- Catalog endpoints are for METADATA ONLY (not used for authorization)
"""

import logging
from typing import Optional, List
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends, Query, Path, Form
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.db import validate_session, get_user_by_hash, get_project_by_hash
from src.Util.db import db_global_roles as global_roles
from src.Util.error_handler import (
    AuthenticationError, AuthorizationError, NotFoundError,
    ValidationError, InternalError, ConflictError, DatabaseError, ErrorCode
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/roles", tags=["Global Role System"])
security = HTTPBearerOrCookie()


# Note: All endpoints use Form data instead of JSON/Pydantic models for consistency


# Authentication Dependencies
async def require_valid_session(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Ensure user has valid session"""
    session_data = validate_session(credentials.credentials)
    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )
    return session_data


async def require_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Ensure user has admin permissions.

    Checks ``user_type IN ['root','admin']`` OR
    ``check_user_has_permission('manage_roles')``.  Also verifies the user
    is active.

    Differs from ``admin_user_groups.py:require_admin()`` because role
    management CAN be delegated via the ``manage_roles`` permission.
    Intentional least-privilege — a consumer with ``manage_roles`` can
    manage roles but NOT user groups.
    """
    session_data = validate_session(credentials.credentials)
    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )
    
    # Check if user exists (including inactive)
    user_data = get_user_by_hash(session_data.user_hash, include_inactive=True)
    if not user_data:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": session_data.user_hash}
        )
    
    # Check if user is active
    if not user_data.is_active:
        raise AuthorizationError(
            message="User account is inactive",
            error_code=ErrorCode.ACCOUNT_INACTIVE
        )
    
    if user_data.user_type not in ['root', 'admin']:
        # Check if user has manage_roles permission
        has_permission = global_roles.check_user_has_permission(user_data.id, 'manage_roles')
        if not has_permission:
            raise AuthorizationError(
                message="Admin permission required",
                error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
                details={"required_permission": "manage_roles"}
            )
    
    return session_data


# =============================================================================
# ROLE MANAGEMENT ENDPOINTS
# =============================================================================

@router.post("/roles", status_code=201)
async def create_role(
    role_name: str = Form(..., description="Unique role name"),
    role_display_name: str = Form(..., description="Display name"),
    role_description: Optional[str] = Form(None, description="Description"),
    role_priority: int = Form(50, ge=0, le=100, description="Priority (0-100)"),
    session_data=Depends(require_admin)
):
    """Create a new global role"""
    user_data = get_user_by_hash(session_data.user_hash)
    if not user_data:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": session_data.user_hash}
        )
    
    # The database function now raises exceptions directly (ConflictError for duplicates)
    new_role = global_roles.create_role(
        role_name=role_name,
        role_display_name=role_display_name,
        role_description=role_description,
        role_priority=role_priority,
        created_by=user_data.id
    )
    
    return {
        "success": True,
        "message": f"Role '{new_role['role_name']}' created successfully",
        "role": new_role
    }


@router.get("/roles")
async def list_roles(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session_data=Depends(require_valid_session)
):
    """List all global roles"""
    roles = global_roles.list_roles(limit=limit, offset=offset)
    return {
        "success": True,
        "roles": roles,
        "pagination": {"limit": limit, "offset": offset, "total": len(roles)}
    }


@router.get("/roles/{role_hash}")
async def get_role(role_hash: str, session_data=Depends(require_valid_session)):
    """Get role by hash"""
    role = global_roles.get_role_by_hash(role_hash)
    if not role:
        raise NotFoundError(
            message="Role not found",
            error_code=ErrorCode.ROLE_NOT_FOUND,
            details={"role_hash": role_hash}
        )
    
    # Get permission groups for this role
    permission_groups = global_roles.get_role_permission_groups(role['id'])
    
    return {
        "success": True,
        "role": role,
        "permission_groups": permission_groups
    }


@router.put("/roles/{role_hash}")
async def update_role(
    role_hash: str,
    role_display_name: Optional[str] = Form(None, description="Display name"),
    role_description: Optional[str] = Form(None, description="Description"),
    role_priority: Optional[int] = Form(None, ge=0, le=100, description="Priority (0-100)"),
    session_data=Depends(require_admin)
):
    """Update role information"""
    role = global_roles.get_role_by_hash(role_hash)
    if not role:
        raise NotFoundError(
            message="Role not found",
            error_code=ErrorCode.ROLE_NOT_FOUND,
            details={"role_hash": role_hash}
        )
    
    success = global_roles.update_role(
        role_id=role['id'],
        role_display_name=role_display_name,
        role_description=role_description,
        role_priority=role_priority
    )
    
    if not success:
        raise InternalError(
            message="Failed to update role",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "update_role", "role_hash": role_hash}
        )
    
    updated_role = global_roles.get_role_by_hash(role_hash)
    return {
        "success": True,
        "message": "Role updated successfully",
        "role": updated_role
    }


@router.delete("/roles/{role_hash}")
async def delete_role(role_hash: str, session_data=Depends(require_admin)):
    """Soft delete a role"""
    role = global_roles.get_role_by_hash(role_hash)
    if not role:
        raise NotFoundError(
            message="Role not found",
            error_code=ErrorCode.ROLE_NOT_FOUND,
            details={"role_hash": role_hash}
        )
    
    if role.get('is_system_role'):
        raise AuthorizationError(
            message="Cannot delete system roles",
            error_code=ErrorCode.OPERATION_NOT_ALLOWED,
            details={"role_hash": role_hash, "reason": "system_role"}
        )
    
    success = global_roles.delete_role(role['id'])
    if not success:
        raise InternalError(
            message="Failed to delete role",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "delete_role", "role_hash": role_hash}
        )
    
    return {"success": True, "message": "Role deleted successfully"}


# =============================================================================
# ROLE-PERMISSION GROUP MANAGEMENT
# =============================================================================

@router.post("/roles/{role_hash}/permission-groups/{group_hash}")
async def assign_permission_group_to_role(
    role_hash: str,
    group_hash: str,
    session_data=Depends(require_admin)
):
    """Assign a permission group to a role"""
    role = global_roles.get_role_by_hash(role_hash)
    if not role:
        raise NotFoundError(
            message="Role not found",
            error_code=ErrorCode.ROLE_NOT_FOUND,
            details={"role_hash": role_hash}
        )
    
    group = global_roles.get_permission_group_by_hash(group_hash)
    if not group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    
    user_data = get_user_by_hash(session_data.user_hash)
    if not user_data:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": session_data.user_hash}
        )
    
    success = global_roles.assign_permission_group_to_role(
        role_id=role['id'],
        permission_group_id=group['id'],
        assigned_by=user_data.id
    )
    
    if not success:
        raise InternalError(
            message="Failed to assign permission group",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "assign_permission_group"}
        )
    
    return {
        "success": True,
        "message": f"Permission group '{group['group_name']}' assigned to role '{role['role_name']}'"
    }


@router.get("/roles/{role_hash}/permission-groups")
async def get_role_permission_groups(role_hash: str, session_data=Depends(require_valid_session)):
    """Get all permission groups for a role"""
    role = global_roles.get_role_by_hash(role_hash)
    if not role:
        raise NotFoundError(
            message="Role not found",
            error_code=ErrorCode.ROLE_NOT_FOUND,
            details={"role_hash": role_hash}
        )
    
    groups = global_roles.get_role_permission_groups(role['id'])
    return {
        "success": True,
        "role": {"role_hash": role_hash, "role_name": role['role_name']},
        "permission_groups": groups
    }


@router.delete("/roles/{role_hash}/permission-groups/{group_hash}")
async def remove_permission_group_from_role(
    role_hash: str,
    group_hash: str,
    session_data=Depends(require_admin)
):
    """Remove a permission group from a role"""
    role = global_roles.get_role_by_hash(role_hash)
    if not role:
        raise NotFoundError(
            message="Role not found",
            error_code=ErrorCode.ROLE_NOT_FOUND,
            details={"role_hash": role_hash}
        )
    
    group = global_roles.get_permission_group_by_hash(group_hash)
    if not group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    
    success = global_roles.remove_permission_group_from_role(
        role_id=role['id'],
        permission_group_id=group['id']
    )
    
    if not success:
        raise NotFoundError(
            message="Permission group is not assigned to this role",
            error_code=ErrorCode.NOT_FOUND,
            details={"role_hash": role_hash, "group_hash": group_hash}
        )
    
    return {
        "success": True,
        "message": f"Permission group '{group['group_name']}' removed from role '{role['role_name']}'"
    }


# =============================================================================
# PERMISSION GROUP MANAGEMENT
# =============================================================================

@router.post("/permission-groups", status_code=201)
async def create_permission_group(
    group_name: str = Form(..., description="Unique group name"),
    group_display_name: str = Form(..., description="Display name"),
    group_description: Optional[str] = Form(None, description="Description"),
    group_category: str = Form("general", description="Category: general, admin, api, data"),
    session_data=Depends(require_admin)
):
    """Create a new global permission group"""
    user_data = get_user_by_hash(session_data.user_hash)
    if not user_data:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": session_data.user_hash}
        )
    
    # Database layer converts IntegrityError to ConflictError automatically
    new_group = global_roles.create_permission_group(
        group_name=group_name,
        group_display_name=group_display_name,
        group_description=group_description,
        group_category=group_category,
        created_by=user_data.id
    )
    
    if not new_group:
        raise InternalError(
            message="Failed to create permission group",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "create_permission_group"}
        )
    
    return {
        "success": True,
        "message": f"Permission group '{new_group['group_name']}' created successfully",
        "permission_group": new_group
    }


@router.get("/permission-groups")
async def list_permission_groups(
    category: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session_data=Depends(require_valid_session)
):
    """List all global permission groups"""
    # Database function uses handle_db_operation - errors propagate to middleware
    groups = global_roles.list_permission_groups(category=category, limit=limit, offset=offset)
    return {
        "success": True,
        "permission_groups": groups,
        "pagination": {"limit": limit, "offset": offset, "total": len(groups)}
    }


@router.get("/permission-groups/{group_hash}")
async def get_permission_group(group_hash: str, session_data=Depends(require_valid_session)):
    """Get permission group by hash"""
    group = global_roles.get_permission_group_by_hash(group_hash)
    if not group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    
    permissions = global_roles.get_permission_group_permissions(group['id'])
    
    return {
        "success": True,
        "permission_group": group,
        "permissions": permissions
    }


@router.put("/permission-groups/{group_hash}")
async def update_permission_group(
    group_hash: str,
    group_display_name: Optional[str] = Form(None, description="Display name"),
    group_description: Optional[str] = Form(None, description="Description"),
    group_category: Optional[str] = Form(None, description="Category: general, admin, api, data"),
    session_data=Depends(require_admin)
):
    """Update permission group information"""
    group = global_roles.get_permission_group_by_hash(group_hash)
    if not group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    
    success = global_roles.update_permission_group(
        group_id=group['id'],
        group_display_name=group_display_name,
        group_description=group_description,
        group_category=group_category
    )
    
    if not success:
        raise InternalError(
            message="Failed to update permission group",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "update_permission_group", "group_hash": group_hash}
        )
    
    updated_group = global_roles.get_permission_group_by_hash(group_hash)
    return {
        "success": True,
        "message": "Permission group updated successfully",
        "permission_group": updated_group
    }


@router.delete("/permission-groups/{group_hash}")
async def delete_permission_group(group_hash: str, session_data=Depends(require_admin)):
    """Soft delete a permission group"""
    group = global_roles.get_permission_group_by_hash(group_hash)
    if not group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    
    success = global_roles.delete_permission_group(group['id'])
    if not success:
        raise InternalError(
            message="Failed to delete permission group",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "delete_permission_group", "group_hash": group_hash}
        )
    
    return {
        "success": True,
        "message": f"Permission group '{group['group_name']}' deleted successfully"
    }


# =============================================================================
# PERMISSION GROUP-PERMISSION MANAGEMENT
# =============================================================================

@router.post("/permission-groups/{group_hash}/permissions/{permission_hash}")
async def assign_permission_to_group(
    group_hash: str,
    permission_hash: str,
    session_data=Depends(require_admin)
):
    """Assign a permission to a permission group"""
    group = global_roles.get_permission_group_by_hash(group_hash)
    if not group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    
    permission = global_roles.get_permission_by_hash(permission_hash)
    if not permission:
        raise NotFoundError(
            message="Permission not found",
            error_code=ErrorCode.PERMISSION_NOT_FOUND,
            details={"permission_hash": permission_hash}
        )
    
    user_data = get_user_by_hash(session_data.user_hash)
    if not user_data:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": session_data.user_hash}
        )
    
    success = global_roles.assign_permission_to_group(
        permission_group_id=group['id'],
        permission_id=permission['id'],
        granted_by=user_data.id
    )
    
    if not success:
        raise InternalError(
            message="Failed to assign permission",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "assign_permission"}
        )
    
    return {
        "success": True,
        "message": f"Permission '{permission['permission_name']}' assigned to group '{group['group_name']}'"
    }


@router.get("/permission-groups/{group_hash}/permissions")
async def get_permission_group_permissions(group_hash: str, session_data=Depends(require_valid_session)):
    """Get all permissions in a permission group"""
    group = global_roles.get_permission_group_by_hash(group_hash)
    if not group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    
    permissions = global_roles.get_permission_group_permissions(group['id'])
    return {
        "success": True,
        "permission_group": {"group_hash": group_hash, "group_name": group['group_name']},
        "permissions": permissions
    }


@router.delete("/permission-groups/{group_hash}/permissions/{permission_hash}")
async def remove_permission_from_group(
    group_hash: str,
    permission_hash: str,
    session_data=Depends(require_admin)
):
    """Remove a permission from a permission group"""
    group = global_roles.get_permission_group_by_hash(group_hash)
    if not group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    
    permission = global_roles.get_permission_by_hash(permission_hash)
    if not permission:
        raise NotFoundError(
            message="Permission not found",
            error_code=ErrorCode.PERMISSION_NOT_FOUND,
            details={"permission_hash": permission_hash}
        )
    
    success = global_roles.remove_permission_from_group(
        permission_group_id=group['id'],
        permission_id=permission['id']
    )
    
    if not success:
        raise NotFoundError(
            message="Permission is not assigned to this group",
            error_code=ErrorCode.NOT_FOUND,
            details={"group_hash": group_hash, "permission_hash": permission_hash}
        )
    
    return {
        "success": True,
        "message": f"Permission '{permission['permission_name']}' removed from group '{group['group_name']}'"
    }


# =============================================================================
# PERMISSION MANAGEMENT
# =============================================================================

@router.post("/permissions", status_code=201)
async def create_permission(
    permission_name: str = Form(..., description="Unique permission name"),
    permission_display_name: str = Form(..., description="Display name"),
    permission_description: Optional[str] = Form(None, description="Description"),
    permission_category: str = Form("general", description="Category"),
    session_data=Depends(require_admin)
):
    """Create a new global permission"""
    user_data = get_user_by_hash(session_data.user_hash)
    if not user_data:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": session_data.user_hash}
        )
    
    # Database layer converts IntegrityError to ConflictError automatically
    new_permission = global_roles.create_permission(
        permission_name=permission_name,
        permission_display_name=permission_display_name,
        permission_description=permission_description,
        permission_category=permission_category,
        created_by=user_data.id
    )
    
    if not new_permission:
        raise InternalError(
            message="Failed to create permission",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "create_permission"}
        )
    
    return {
        "success": True,
        "message": f"Permission '{new_permission['permission_name']}' created successfully",
        "permission": new_permission
    }


@router.get("/permissions")
async def list_permissions(
    category: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session_data=Depends(require_valid_session)
):
    """List all global permissions"""
    # Database function uses handle_db_operation - errors propagate to middleware
    permissions = global_roles.list_permissions(category=category, limit=limit, offset=offset)
    return {
        "success": True,
        "permissions": permissions,
        "pagination": {"limit": limit, "offset": offset, "total": len(permissions)}
    }


@router.get("/permissions/{permission_hash}")
async def get_permission(permission_hash: str, session_data=Depends(require_valid_session)):
    """Get permission by hash"""
    permission = global_roles.get_permission_by_hash(permission_hash)
    if not permission:
        raise NotFoundError(
            message="Permission not found",
            error_code=ErrorCode.PERMISSION_NOT_FOUND,
            details={"permission_hash": permission_hash}
        )
    
    return {"success": True, "permission": permission}


@router.put("/permissions/{permission_hash}")
async def update_permission(
    permission_hash: str,
    permission_display_name: Optional[str] = Form(None, description="Display name"),
    permission_description: Optional[str] = Form(None, description="Description"),
    permission_category: Optional[str] = Form(None, description="Category"),
    session_data=Depends(require_admin)
):
    """Update permission information"""
    permission = global_roles.get_permission_by_hash(permission_hash)
    if not permission:
        raise NotFoundError(
            message="Permission not found",
            error_code=ErrorCode.PERMISSION_NOT_FOUND,
            details={"permission_hash": permission_hash}
        )
    
    success = global_roles.update_permission(
        permission_id=permission['id'],
        permission_display_name=permission_display_name,
        permission_description=permission_description,
        permission_category=permission_category
    )
    
    if not success:
        raise InternalError(
            message="Failed to update permission",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "update_permission", "permission_hash": permission_hash}
        )
    
    updated_permission = global_roles.get_permission_by_hash(permission_hash)
    return {
        "success": True,
        "message": "Permission updated successfully",
        "permission": updated_permission
    }


@router.delete("/permissions/{permission_hash}")
async def delete_permission(permission_hash: str, session_data=Depends(require_admin)):
    """Soft delete a permission"""
    permission = global_roles.get_permission_by_hash(permission_hash)
    if not permission:
        raise NotFoundError(
            message="Permission not found",
            error_code=ErrorCode.PERMISSION_NOT_FOUND,
            details={"permission_hash": permission_hash}
        )
    
    success = global_roles.delete_permission(permission['id'])
    if not success:
        raise InternalError(
            message="Failed to delete permission",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "delete_permission", "permission_hash": permission_hash}
        )
    
    return {
        "success": True,
        "message": f"Permission '{permission['permission_name']}' deleted successfully"
    }


# =============================================================================
# USER PERMISSION QUERY ENDPOINTS (GLOBAL - NO PROJECT CONTEXT)
# NOTE: /users/me/* routes MUST come BEFORE /users/{user_hash}/* routes
# =============================================================================

@router.get("/users/me/role")
async def get_my_role(session_data=Depends(require_valid_session)):
    """Get current user's role"""
    # Check if user exists (including inactive)
    user = get_user_by_hash(session_data.user_hash, include_inactive=True)
    if not user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": session_data.user_hash}
        )
    
    # Check if user is active
    if not user.is_active:
        raise AuthorizationError(
            message="User account is inactive",
            error_code=ErrorCode.ACCOUNT_INACTIVE,
            details={"user_hash": session_data.user_hash}
        )
    
    role = global_roles.get_user_role(user.id)
    
    return {
        "success": True,
        "user": {"user_hash": session_data.user_hash, "username": user.username},
        "role": role
    }


# NOTE: /users/me/permissions and /users/me/permissions/check/{name} routes
# have been moved to permission_assignments.py which uses the extended
# permission checking function (check_user_has_permission_extended).
# These duplicate routes were removed to eliminate shadowing.

# =============================================================================
# USER ROLE ASSIGNMENT ENDPOINTS
# =============================================================================

@router.put("/users/{user_hash}/role")
async def assign_role_to_user(
    user_hash: str,
    role_hash: str = Form(..., description="Role hash to assign"),
    session_data=Depends(require_admin)
):
    """Assign a role to a user"""
    # Check if user exists (including inactive)
    user = get_user_by_hash(user_hash, include_inactive=True)
    if not user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": user_hash}
        )
    
    # Check if user is active
    if not user.is_active:
        raise AuthorizationError(
            message="Cannot assign role to inactive user",
            error_code=ErrorCode.ACCOUNT_INACTIVE,
            details={"user_hash": user_hash}
        )
    
    role = global_roles.get_role_by_hash(role_hash)
    if not role:
        raise NotFoundError(
            message="Role not found",
            error_code=ErrorCode.ROLE_NOT_FOUND,
            details={"role_hash": role_hash}
        )
    
    success = global_roles.assign_role_to_user(user.id, role['id'])
    if not success:
        raise InternalError(
            message="Failed to assign role",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "assign_role_to_user"}
        )
    
    return {
        "success": True,
        "message": f"Role '{role['role_name']}' assigned to user '{user.username}'",
        "user": {"user_hash": user_hash, "username": user.username},
        "role": {"role_hash": role_hash, "role_name": role['role_name']}
    }


@router.get("/users/{user_hash}/role")
async def get_user_role(user_hash: str, session_data=Depends(require_valid_session)):
    """Get user's role"""
    # Check if user exists (including inactive)
    user = get_user_by_hash(user_hash, include_inactive=True)
    if not user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": user_hash}
        )
    
    # Check if user is active
    if not user.is_active:
        raise AuthorizationError(
            message="User account is inactive",
            error_code=ErrorCode.ACCOUNT_INACTIVE,
            details={"user_hash": user_hash}
        )
    
    role = global_roles.get_user_role(user.id)
    
    return {
        "success": True,
        "user": {"user_hash": user_hash, "username": user.username},
        "role": role
    }


@router.delete("/users/{user_hash}/role")
async def remove_role_from_user(user_hash: str, session_data=Depends(require_admin)):
    """Remove/unassign role from a user"""
    # Check if user exists (including inactive)
    user = get_user_by_hash(user_hash, include_inactive=True)
    if not user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": user_hash}
        )
    
    # Check if user is active
    if not user.is_active:
        raise AuthorizationError(
            message="Cannot modify role of inactive user",
            error_code=ErrorCode.ACCOUNT_INACTIVE,
            details={"user_hash": user_hash}
        )
    
    # Get current role before removing
    current_role = global_roles.get_user_role(user.id)
    
    success = global_roles.remove_role_from_user(user.id)
    if not success:
        raise InternalError(
            message="Failed to remove role from user",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "remove_role_from_user", "user_hash": user_hash}
        )
    
    return {
        "success": True,
        "message": f"Role removed from user '{user.username}'",
        "user": {"user_hash": user_hash, "username": user.username},
        "previous_role": current_role
    }


# =============================================================================
# CATALOG ENDPOINTS (METADATA ONLY - NOT FOR AUTHORIZATION)
# =============================================================================

@router.post("/projects/{project_hash}/catalog/roles/{role_hash}")
async def add_role_to_project_catalog(
    project_hash: str,
    role_hash: str,
    catalog_purpose: Optional[str] = Form(None, description="Purpose of this catalog entry"),
    notes: Optional[str] = Form(None, description="Additional notes"),
    session_data=Depends(require_admin)
):
    """
    Add role to project catalog (METADATA ONLY - for UI suggestions).
    This is for organizational purposes, NOT used for authorization.
    """
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )
    
    role = global_roles.get_role_by_hash(role_hash)
    if not role:
        raise NotFoundError(
            message="Role not found",
            error_code=ErrorCode.ROLE_NOT_FOUND,
            details={"role_hash": role_hash}
        )
    
    user_data = get_user_by_hash(session_data.user_hash)
    if not user_data:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": session_data.user_hash}
        )
    
    success = global_roles.add_role_to_project_catalog(
        role_id=role['id'],
        project_id=project.id,
        catalog_purpose=catalog_purpose,
        notes=notes,
        added_by=user_data.id
    )
    
    if not success:
        raise ConflictError(
            message="Role is already in the project catalog",
            error_code=ErrorCode.ALREADY_EXISTS,
            details={"role_hash": role_hash, "project_hash": project_hash}
        )
    
    return {
        "success": True,
        "message": "Role added to project catalog successfully",
        "note": "This is METADATA ONLY - not used for authorization",
        "project": {
            "hash": project.project_hash,
            "name": project.project_name
        },
        "role": {
            "role_hash": role['role_hash'],
            "role_name": role['role_name'],
            "role_display_name": role['role_display_name']
        },
        "catalog_purpose": catalog_purpose
    }


@router.get("/projects/{project_hash}/catalog/roles")
async def get_project_cataloged_roles(project_hash: str, session_data=Depends(require_valid_session)):
    """
    Get roles cataloged for a project (METADATA - for UI suggestions).
    This does NOT restrict which roles can be used.
    """
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )
    
    cataloged_roles = global_roles.get_project_cataloged_roles(project.id)
    
    return {
        "success": True,
        "project": {
            "hash": project.project_hash,
            "name": project.project_name
        },
        "cataloged_roles": cataloged_roles,
        "count": len(cataloged_roles),
        "note": "This is METADATA ONLY - any role can be assigned to users"
    }


@router.delete("/projects/{project_hash}/catalog/roles/{role_hash}")
async def remove_role_from_project_catalog(
    project_hash: str,
    role_hash: str,
    session_data=Depends(require_admin)
):
    """
    Remove role from project catalog (METADATA ONLY).
    This removes the role suggestion, NOT any actual role assignments.
    """
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )
    
    role = global_roles.get_role_by_hash(role_hash)
    if not role:
        raise NotFoundError(
            message="Role not found",
            error_code=ErrorCode.ROLE_NOT_FOUND,
            details={"role_hash": role_hash}
        )
    
    user_data = get_user_by_hash(session_data.user_hash)
    if not user_data:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": session_data.user_hash}
        )
    
    success = global_roles.remove_role_from_project_catalog(
        role_id=role['id'],
        project_id=project.id,
        removed_by=user_data.id
    )
    
    if not success:
        raise NotFoundError(
            message="Role is not in the project catalog",
            error_code=ErrorCode.NOT_FOUND,
            details={"role_hash": role_hash, "project_hash": project_hash}
        )
    
    return {
        "success": True,
        "message": "Role removed from project catalog successfully",
        "project": {
            "hash": project.project_hash,
            "name": project.project_name
        },
        "role": {
            "role_hash": role['role_hash'],
            "role_name": role['role_name']
        }
    }
