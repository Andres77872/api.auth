"""
Permission Assignment API Endpoints

This module implements REST API endpoints for the permission assignment system where:
- Permission groups can be assigned to USER GROUPS (organizational scale)
- Permission groups can be assigned to USERS directly (individual overrides)
- Project catalogs are METADATA ONLY (not used for authorization)
- All permissions are GLOBAL (not project-specific)
"""

import logging
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Query, Path, Form
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.db import (
    validate_session, 
    get_user_by_hash, 
    get_user_group_by_hash,
    get_project_by_hash,
    # Permission assignment functions
    assign_permission_group_to_user_group,
    remove_permission_group_from_user_group,
    get_user_group_permission_groups,
    get_user_groups_with_permission_group,
    assign_permission_group_to_user,
    remove_permission_group_from_user,
    get_user_permission_groups,
    get_users_with_permission_group,
    add_permission_group_to_project_catalog,
    remove_permission_group_from_project_catalog,
    get_project_cataloged_permission_groups,
    get_permission_group_cataloged_projects,
    get_user_all_permissions,
    check_user_has_permission_extended,
    get_user_permission_sources
)
from src.Util.db import db_global_roles as global_roles
from src.Util.error_handler import (
    AuthenticationError, AuthorizationError, ValidationError,
    NotFoundError, ConflictError, InternalError, ErrorCode
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/permissions", tags=["Permission Assignments"])
security = HTTPBearerOrCookie()


# Note: All endpoints use Form data instead of JSON/Pydantic models for consistency


# =================== AUTHENTICATION DEPENDENCIES ===================

async def require_valid_session(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Ensure user has valid session"""
    session_data = validate_session(credentials.credentials)
    if not session_data:
        raise AuthenticationError(
            message="Invalid session",
            error_code=ErrorCode.SESSION_INVALID
        )
    return session_data


async def require_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Ensure user has admin permissions"""
    session_data = validate_session(credentials.credentials)
    if not session_data:
        raise AuthenticationError(
            message="Invalid session",
            error_code=ErrorCode.SESSION_INVALID
        )
    
    user_data = get_user_by_hash(session_data.user_hash)
    if user_data.user_type not in ['root', 'admin']:
        # Check if user has manage_roles permission
        has_permission = check_user_has_permission_extended(user_data.id, 'manage_roles')
        if not has_permission:
            raise AuthorizationError(
                message="Admin permission required",
                error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
                details={"required_permission": "manage_roles"}
            )
    
    return session_data


# =============================================================================
# USER GROUP PERMISSION GROUP ASSIGNMENTS
# =============================================================================

@router.post("/admin/user-groups/{group_hash}/permission-groups", status_code=200)
async def assign_permission_group_to_group(
    group_hash: str = Path(..., description="User group hash"),
    permission_group_hash: str = Form(..., description="Permission group hash to assign"),
    session_data=Depends(require_admin)
):
    """
    Assign permission group to user group (PRIMARY assignment model).
    All members of the user group will inherit the permission group.
    """
    user_data = get_user_by_hash(session_data.user_hash)
    
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    
    # Get permission group
    permission_group = global_roles.get_permission_group_by_hash(permission_group_hash)
    if not permission_group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"permission_group_hash": permission_group_hash}
        )
    
    # Assign permission group to user group
    success = assign_permission_group_to_user_group(
        user_group.id,
        permission_group['id'],
        user_data.id
    )
    
    if not success:
        raise InternalError(
            message="Failed to assign permission group to user group",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "assign_permission_group_to_user_group"}
        )
    
    return {
        "message": "Permission group assigned to user group successfully",
        "user_group": {
            "hash": user_group.group_hash,
            "name": user_group.group_name
        },
        "permission_group": {
            "hash": permission_group['group_hash'],
            "name": permission_group['group_name']
        }
    }
    
@router.delete("/admin/user-groups/{group_hash}/permission-groups/{pg_hash}", status_code=200)
async def remove_permission_group_from_group(
    group_hash: str = Path(..., description="User group hash"),
    pg_hash: str = Path(..., description="Permission group hash"),
    session_data=Depends(require_admin)
):
    """Remove permission group from user group"""
    user_data = get_user_by_hash(session_data.user_hash)
    
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    
    # Get permission group
    permission_group = global_roles.get_permission_group_by_hash(pg_hash)
    if not permission_group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"permission_group_hash": pg_hash}
        )
    
    # Remove permission group from user group
    success = remove_permission_group_from_user_group(
        user_group.id,
        permission_group['id'],
        user_data.id
    )
    
    if not success:
        raise InternalError(
            message="Failed to remove permission group from user group",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "remove_permission_group_from_user_group"}
        )
    
    return {
        "message": "Permission group removed from user group successfully",
        "user_group": {
            "hash": user_group.group_hash,
            "name": user_group.group_name
        },
        "permission_group": {
            "hash": permission_group['group_hash'],
            "name": permission_group['group_name']
        }
    }
    
@router.get("/admin/user-groups/{group_hash}/permission-groups", status_code=200)
async def get_group_permission_groups(
    group_hash: str = Path(..., description="User group hash"),
    session_data=Depends(require_admin)
):
    """Get permission groups assigned to a user group"""
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    
    # Get permission groups
    permission_groups = get_user_group_permission_groups(user_group.id)
    
    return {
        "user_group": {
            "hash": user_group.group_hash,
            "name": user_group.group_name
        },
        "permission_groups": permission_groups,
        "count": len(permission_groups)
    }
    
@router.post("/admin/user-groups/{group_hash}/permission-groups/bulk", status_code=200)
async def bulk_assign_permission_groups_to_group(
    group_hash: str = Path(..., description="User group hash"),
    permission_group_hashes: List[str] = Form(..., description="List of permission group hashes"),
    session_data=Depends(require_admin)
):
    """Bulk assign multiple permission groups to a user group"""
    user_data = get_user_by_hash(session_data.user_hash)
    
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    
    results = []
    for pg_hash in permission_group_hashes:
        try:
            permission_group = global_roles.get_permission_group_by_hash(pg_hash)
            if not permission_group:
                results.append({
                    "permission_group_hash": pg_hash,
                    "success": False,
                    "error": "Permission group not found"
                })
                continue
            
            success = assign_permission_group_to_user_group(
                user_group.id,
                permission_group['id'],
                user_data.id
            )
            
            results.append({
                "permission_group_hash": pg_hash,
                "permission_group_name": permission_group['group_name'],
                "success": success
            })
        except Exception as e:
            results.append({
                "permission_group_hash": pg_hash,
                "success": False,
                "error": str(e)
            })
    
    success_count = sum(1 for r in results if r['success'])
    
    return {
        "message": f"Bulk assignment completed: {success_count}/{len(permission_group_hashes)} successful",
        "user_group": {
            "hash": user_group.group_hash,
            "name": user_group.group_name
        },
        "results": results,
        "success_count": success_count,
        "total_count": len(permission_group_hashes)
    }
    
# =============================================================================
# DIRECT USER PERMISSION GROUP ASSIGNMENTS (SECONDARY MODEL)
# =============================================================================

@router.post("/users/{user_hash}/permission-groups", status_code=200)
async def assign_permission_group_to_user_direct(
    user_hash: str = Path(..., description="User hash"),
    permission_group_hash: str = Form(..., description="Permission group hash to assign"),
    notes: Optional[str] = Form(None, description="Reason for direct assignment"),
    session_data=Depends(require_admin)
):
    """
    Assign permission group directly to user (SECONDARY assignment model).
    Use for individual overrides, temporary access, or special cases.
    """
    admin_data = get_user_by_hash(session_data.user_hash)
    
    # Get target user
    target_user = get_user_by_hash(user_hash)
    if not target_user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": user_hash}
        )
    
    # Get permission group
    permission_group = global_roles.get_permission_group_by_hash(permission_group_hash)
    if not permission_group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"permission_group_hash": permission_group_hash}
        )
    
    # Assign permission group to user
    success = assign_permission_group_to_user(
        target_user.id,
        permission_group['id'],
        admin_data.id,
        notes
    )
    
    if not success:
        raise InternalError(
            message="Failed to assign permission group to user",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "assign_permission_group_to_user"}
        )
    
    return {
        "message": "Permission group assigned to user successfully",
        "user": {
            "hash": target_user.user_hash,
            "username": target_user.username
        },
        "permission_group": {
            "hash": permission_group['group_hash'],
            "name": permission_group['group_name']
        },
        "notes": notes
    }
    
@router.delete("/users/{user_hash}/permission-groups/{pg_hash}", status_code=200)
async def remove_permission_group_from_user_direct(
    user_hash: str = Path(..., description="User hash"),
    pg_hash: str = Path(..., description="Permission group hash"),
    session_data=Depends(require_admin)
):
    """Remove permission group from user"""
    admin_data = get_user_by_hash(session_data.user_hash)
    
    # Get target user
    target_user = get_user_by_hash(user_hash)
    if not target_user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": user_hash}
        )
    
    # Get permission group
    permission_group = global_roles.get_permission_group_by_hash(pg_hash)
    if not permission_group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"permission_group_hash": pg_hash}
        )
    
    # Remove permission group from user
    success = remove_permission_group_from_user(
        target_user.id,
        permission_group['id'],
        admin_data.id
    )
    
    if not success:
        raise InternalError(
            message="Failed to remove permission group from user",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "remove_permission_group_from_user"}
        )
    
    return {
        "message": "Permission group removed from user successfully",
        "user": {
            "hash": target_user.user_hash,
            "username": target_user.username
        },
        "permission_group": {
            "hash": permission_group['group_hash'],
            "name": permission_group['group_name']
        }
    }
    
@router.get("/users/{user_hash}/permission-groups", status_code=200)
async def get_user_direct_permission_groups(
    user_hash: str = Path(..., description="User hash"),
    session_data=Depends(require_admin)
):
    """Get permission groups directly assigned to a user"""
    # Get user
    user = get_user_by_hash(user_hash)
    if not user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": user_hash}
        )
    
    # Get permission groups
    permission_groups = get_user_permission_groups(user.id)
    
    return {
        "user": {
            "hash": user.user_hash,
            "username": user.username
        },
        "direct_permission_groups": permission_groups,
        "count": len(permission_groups)
    }


# =============================================================================
# CURRENT USER PERMISSION QUERIES
# =============================================================================

@router.get("/users/me/permissions", status_code=200)
async def get_my_permissions(session_data=Depends(require_valid_session)):
    """Get all permissions for the current user (from all sources: role, user groups, direct)"""
    user_data = get_user_by_hash(session_data.user_hash)
    
    # Get all permissions from all sources
    permissions = get_user_all_permissions(user_data.id)
    
    return {
        "user": {
            "hash": user_data.user_hash,
            "username": user_data.username
        },
        "permissions": permissions,
        "count": len(permissions)
    }


@router.get("/users/me/permissions/check/{permission_name}", status_code=200)
async def check_my_permission(
    permission_name: str = Path(..., description="Permission name to check"),
    session_data=Depends(require_valid_session)
):
    """Check if current user has a specific permission"""
    user_data = get_user_by_hash(session_data.user_hash)
    
    # Check permission from all sources
    has_permission = check_user_has_permission_extended(user_data.id, permission_name)
    
    return {
        "user": {
            "hash": user_data.user_hash,
            "username": user_data.username
        },
        "permission": permission_name,
        "has_permission": has_permission
    }


@router.get("/users/me/permission-groups", status_code=200)
async def get_my_permission_groups(session_data=Depends(require_valid_session)):
    """Get all permission groups for current user (direct assignments only)"""
    user_data = get_user_by_hash(session_data.user_hash)
    
    # Get direct permission groups
    permission_groups = get_user_permission_groups(user_data.id)
    
    return {
        "user": {
            "hash": user_data.user_hash,
            "username": user_data.username
        },
        "direct_permission_groups": permission_groups,
        "count": len(permission_groups)
    }


@router.get("/users/me/permission-sources", status_code=200)
async def get_my_permission_sources(session_data=Depends(require_valid_session)):
    """Get detailed breakdown of permission sources for current user"""
    user_data = get_user_by_hash(session_data.user_hash)
    
    # Get permission sources
    sources = get_user_permission_sources(user_data.id)
    
    # Group by source type
    by_role = [s for s in sources if s['source_type'] == 'role']
    by_user_group = [s for s in sources if s['source_type'] == 'user_group']
    by_direct = [s for s in sources if s['source_type'] == 'direct']
    
    return {
        "user": {
            "hash": user_data.user_hash,
            "username": user_data.username
        },
        "sources": {
            "from_role": by_role,
            "from_user_groups": by_user_group,
            "from_direct_assignment": by_direct
        },
        "summary": {
            "role_count": len(by_role),
            "user_group_count": len(by_user_group),
            "direct_count": len(by_direct),
            "total_permission_groups": len(sources)
        }
    }


# =============================================================================
# PERMISSION GROUP PROJECT CATALOG (METADATA ONLY - NOT FOR AUTHORIZATION)
# =============================================================================

@router.post("/projects/{project_hash}/permission-group-catalog/{pg_hash}", status_code=200)
async def add_permission_group_to_catalog(
    project_hash: str = Path(..., description="Project hash"),
    pg_hash: str = Path(..., description="Permission group hash"),
    catalog_purpose: Optional[str] = Form(None, description="Purpose of this catalog entry"),
    notes: Optional[str] = Form(None, description="Additional notes"),
    session_data=Depends(require_admin)
):
    """
    Add permission group to project catalog (METADATA ONLY).
    This is for UI suggestions and organization, NOT used for authorization.
    """
    user_data = get_user_by_hash(session_data.user_hash)
    
    # Get project
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )
    
    # Get permission group
    permission_group = global_roles.get_permission_group_by_hash(pg_hash)
    if not permission_group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"permission_group_hash": pg_hash}
        )
    
    # Add to catalog
    success = add_permission_group_to_project_catalog(
        permission_group['id'],
        project.id,
        catalog_purpose,
        notes,
        user_data.id
    )
    
    if not success:
        raise InternalError(
            message="Failed to add to catalog",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "add_permission_group_to_project_catalog"}
        )
    
    return {
        "message": "Permission group added to project catalog successfully",
        "note": "This is METADATA ONLY - not used for authorization",
        "project": {
            "hash": project.project_hash,
            "name": project.project_name
        },
        "permission_group": {
            "hash": permission_group['group_hash'],
            "name": permission_group['group_name']
        },
        "catalog_purpose": catalog_purpose
    }
    
@router.delete("/projects/{project_hash}/permission-group-catalog/{pg_hash}", status_code=200)
async def remove_permission_group_from_catalog(
    project_hash: str = Path(..., description="Project hash"),
    pg_hash: str = Path(..., description="Permission group hash"),
    session_data=Depends(require_admin)
):
    """Remove permission group from project catalog"""
    user_data = get_user_by_hash(session_data.user_hash)
    
    # Get project
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )
    
    # Get permission group
    permission_group = global_roles.get_permission_group_by_hash(pg_hash)
    if not permission_group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"permission_group_hash": pg_hash}
        )
    
    # Remove from catalog
    success = remove_permission_group_from_project_catalog(
        permission_group['id'],
        project.id,
        user_data.id
    )
    
    if not success:
        raise InternalError(
            message="Failed to remove from catalog",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "remove_permission_group_from_project_catalog"}
        )
    
    return {
        "message": "Permission group removed from project catalog successfully",
        "project": {
            "hash": project.project_hash,
            "name": project.project_name
        },
        "permission_group": {
            "hash": permission_group['group_hash'],
            "name": permission_group['group_name']
        }
    }
    
@router.get("/projects/{project_hash}/permission-group-catalog", status_code=200)
async def get_project_catalog(
    project_hash: str = Path(..., description="Project hash"),
    session_data=Depends(require_valid_session)
):
    """
    Get permission groups cataloged for a project (METADATA for UI suggestions).
    This does NOT restrict which permission groups can be used.
    """
    # Get project
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )
    
    # Get cataloged permission groups
    cataloged = get_project_cataloged_permission_groups(project.id)
    
    return {
        "project": {
            "hash": project.project_hash,
            "name": project.project_name
        },
        "cataloged_permission_groups": cataloged,
        "count": len(cataloged),
        "note": "This is METADATA ONLY - any permission group can be used"
    }
    
@router.get("/permissions/groups/{pg_hash}/project-catalog", status_code=200)
async def get_permission_group_catalog(
    pg_hash: str = Path(..., description="Permission group hash"),
    session_data=Depends(require_valid_session)
):
    """Get projects that catalog a specific permission group"""
    # Get permission group
    permission_group = global_roles.get_permission_group_by_hash(pg_hash)
    if not permission_group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"permission_group_hash": pg_hash}
        )
    
    # Get cataloged projects
    cataloged = get_permission_group_cataloged_projects(permission_group['id'])
    
    return {
        "permission_group": {
            "hash": permission_group['group_hash'],
            "name": permission_group['group_name']
        },
        "cataloged_in_projects": cataloged,
        "count": len(cataloged),
        "note": "This permission group works in ALL projects, not just cataloged ones"
    }
    
# =============================================================================
# PERMISSION GROUP USAGE QUERIES
# =============================================================================

@router.get("/permissions/groups/{pg_hash}/user-groups", status_code=200)
async def get_user_groups_using_permission_group(
    pg_hash: str = Path(..., description="Permission group hash"),
    session_data=Depends(require_admin)
):
    """Get user groups that have a specific permission group assigned"""
    # Get permission group
    permission_group = global_roles.get_permission_group_by_hash(pg_hash)
    if not permission_group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"permission_group_hash": pg_hash}
        )
    
    # Get user groups
    user_groups = get_user_groups_with_permission_group(permission_group['id'])
    
    return {
        "permission_group": {
            "hash": permission_group['group_hash'],
            "name": permission_group['group_name']
        },
        "user_groups": user_groups,
        "count": len(user_groups)
    }
    
@router.get("/permissions/groups/{pg_hash}/users", status_code=200)
async def get_users_using_permission_group(
    pg_hash: str = Path(..., description="Permission group hash"),
    session_data=Depends(require_admin)
):
    """Get users that have a specific permission group directly assigned"""
    # Get permission group
    permission_group = global_roles.get_permission_group_by_hash(pg_hash)
    if not permission_group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"permission_group_hash": pg_hash}
        )
    
    # Get users
    users = get_users_with_permission_group(permission_group['id'])
    
    return {
        "permission_group": {
            "hash": permission_group['group_hash'],
            "name": permission_group['group_name']
        },
        "users_with_direct_assignment": users,
        "count": len(users)
    }
    