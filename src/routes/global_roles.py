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
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Query, Path, Form
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.db import validate_session, get_user_by_hash, get_project_by_hash
from src.Util.db import db_global_roles as global_roles

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/roles", tags=["Global Role System"])
security = HTTPBearerOrCookie()


# Pydantic Models
class RoleCreate(BaseModel):
    role_name: str = Field(..., description="Unique role name")
    role_display_name: str = Field(..., description="Display name")
    role_description: Optional[str] = Field(None, description="Description")
    role_priority: int = Field(50, ge=0, le=100, description="Priority (0-100)")


class RoleUpdate(BaseModel):
    role_display_name: Optional[str] = None
    role_description: Optional[str] = None
    role_priority: Optional[int] = Field(None, ge=0, le=100)


class PermissionGroupCreate(BaseModel):
    group_name: str = Field(..., description="Unique group name")
    group_display_name: str = Field(..., description="Display name")
    group_description: Optional[str] = None
    group_category: str = Field("general", description="Category: general, admin, api, data")


class PermissionCreate(BaseModel):
    permission_name: str = Field(..., description="Unique permission name")
    permission_display_name: str = Field(..., description="Display name")
    permission_description: Optional[str] = None
    permission_category: str = Field("general", description="Category")


class UserRoleAssignment(BaseModel):
    role_hash: str = Field(..., description="Role hash to assign")


class CatalogEntry(BaseModel):
    catalog_purpose: Optional[str] = Field(None, description="Purpose of this catalog entry")
    notes: Optional[str] = Field(None, description="Additional notes")


# Authentication Dependencies
async def require_valid_session(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Ensure user has valid session"""
    session_data = validate_session(credentials.credentials)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    return session_data


async def require_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Ensure user has admin permissions"""
    session_data = validate_session(credentials.credentials)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    user_data = get_user_by_hash(session_data.user_hash)
    if user_data.user_type not in ['root', 'admin']:
        # Check if user has manage_roles permission
        has_permission = global_roles.check_user_has_permission(user_data.id, 'manage_roles')
        if not has_permission:
            raise HTTPException(status_code=403, detail="Admin permission required")
    
    return session_data


# =============================================================================
# ROLE MANAGEMENT ENDPOINTS
# =============================================================================

@router.post("/roles", status_code=201)
async def create_role(role: RoleCreate, session_data=Depends(require_admin)):
    """Create a new global role"""
    try:
        user_data = get_user_by_hash(session_data.user_hash)
        
        new_role = global_roles.create_role(
            role_name=role.role_name,
            role_display_name=role.role_display_name,
            role_description=role.role_description,
            role_priority=role.role_priority,
            created_by=user_data.id
        )
        
        if not new_role:
            raise HTTPException(status_code=400, detail="Failed to create role")
        
        return {
            "success": True,
            "message": f"Role '{role.role_name}' created successfully",
            "role": new_role
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating role: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create role")


@router.get("/roles")
async def list_roles(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session_data=Depends(require_valid_session)
):
    """List all global roles"""
    try:
        roles = global_roles.list_roles(limit=limit, offset=offset)
        return {
            "success": True,
            "roles": roles,
            "pagination": {"limit": limit, "offset": offset, "total": len(roles)}
        }
    except Exception as e:
        logger.error(f"Error listing roles: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list roles")


@router.get("/roles/{role_hash}")
async def get_role(role_hash: str, session_data=Depends(require_valid_session)):
    """Get role by hash"""
    try:
        role = global_roles.get_role_by_hash(role_hash)
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")
        
        # Get permission groups for this role
        permission_groups = global_roles.get_role_permission_groups(role['id'])
        
        return {
            "success": True,
            "role": role,
            "permission_groups": permission_groups
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting role: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get role")


@router.put("/roles/{role_hash}")
async def update_role(
    role_hash: str,
    role_update: RoleUpdate,
    session_data=Depends(require_admin)
):
    """Update role information"""
    try:
        role = global_roles.get_role_by_hash(role_hash)
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")
        
        success = global_roles.update_role(
            role_id=role['id'],
            role_display_name=role_update.role_display_name,
            role_description=role_update.role_description,
            role_priority=role_update.role_priority
        )
        
        if not success:
            raise HTTPException(status_code=400, detail="Failed to update role")
        
        updated_role = global_roles.get_role_by_hash(role_hash)
        return {
            "success": True,
            "message": "Role updated successfully",
            "role": updated_role
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating role: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update role")


@router.delete("/roles/{role_hash}")
async def delete_role(role_hash: str, session_data=Depends(require_admin)):
    """Soft delete a role"""
    try:
        role = global_roles.get_role_by_hash(role_hash)
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")
        
        if role.get('is_system_role'):
            raise HTTPException(status_code=403, detail="Cannot delete system roles")
        
        success = global_roles.delete_role(role['id'])
        if not success:
            raise HTTPException(status_code=400, detail="Failed to delete role")
        
        return {"success": True, "message": "Role deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting role: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete role")


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
    try:
        role = global_roles.get_role_by_hash(role_hash)
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")
        
        group = global_roles.get_permission_group_by_hash(group_hash)
        if not group:
            raise HTTPException(status_code=404, detail="Permission group not found")
        
        user_data = get_user_by_hash(session_data.user_hash)
        success = global_roles.assign_permission_group_to_role(
            role_id=role['id'],
            permission_group_id=group['id'],
            assigned_by=user_data.id
        )
        
        if not success:
            raise HTTPException(status_code=400, detail="Failed to assign permission group")
        
        return {
            "success": True,
            "message": f"Permission group '{group['group_name']}' assigned to role '{role['role_name']}'"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error assigning permission group: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to assign permission group")


@router.get("/roles/{role_hash}/permission-groups")
async def get_role_permission_groups(role_hash: str, session_data=Depends(require_valid_session)):
    """Get all permission groups for a role"""
    try:
        role = global_roles.get_role_by_hash(role_hash)
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")
        
        groups = global_roles.get_role_permission_groups(role['id'])
        return {
            "success": True,
            "role": {"role_hash": role_hash, "role_name": role['role_name']},
            "permission_groups": groups
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting role permission groups: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get permission groups")


# =============================================================================
# PERMISSION GROUP MANAGEMENT
# =============================================================================

@router.post("/permission-groups", status_code=201)
async def create_permission_group(group: PermissionGroupCreate, session_data=Depends(require_admin)):
    """Create a new global permission group"""
    try:
        user_data = get_user_by_hash(session_data.user_hash)
        
        new_group = global_roles.create_permission_group(
            group_name=group.group_name,
            group_display_name=group.group_display_name,
            group_description=group.group_description,
            group_category=group.group_category,
            created_by=user_data.id
        )
        
        if not new_group:
            raise HTTPException(status_code=400, detail="Failed to create permission group")
        
        return {
            "success": True,
            "message": f"Permission group '{group.group_name}' created successfully",
            "permission_group": new_group
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating permission group: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create permission group")


@router.get("/permission-groups")
async def list_permission_groups(
    category: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session_data=Depends(require_valid_session)
):
    """List all global permission groups"""
    try:
        groups = global_roles.list_permission_groups(category=category, limit=limit, offset=offset)
        return {
            "success": True,
            "permission_groups": groups,
            "pagination": {"limit": limit, "offset": offset, "total": len(groups)}
        }
    except Exception as e:
        logger.error(f"Error listing permission groups: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list permission groups")


@router.get("/permission-groups/{group_hash}")
async def get_permission_group(group_hash: str, session_data=Depends(require_valid_session)):
    """Get permission group by hash"""
    try:
        group = global_roles.get_permission_group_by_hash(group_hash)
        if not group:
            raise HTTPException(status_code=404, detail="Permission group not found")
        
        permissions = global_roles.get_permission_group_permissions(group['id'])
        
        return {
            "success": True,
            "permission_group": group,
            "permissions": permissions
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting permission group: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get permission group")


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
    try:
        group = global_roles.get_permission_group_by_hash(group_hash)
        if not group:
            raise HTTPException(status_code=404, detail="Permission group not found")
        
        permission = global_roles.get_permission_by_hash(permission_hash)
        if not permission:
            raise HTTPException(status_code=404, detail="Permission not found")
        
        user_data = get_user_by_hash(session_data.user_hash)
        success = global_roles.assign_permission_to_group(
            permission_group_id=group['id'],
            permission_id=permission['id'],
            granted_by=user_data.id
        )
        
        if not success:
            raise HTTPException(status_code=400, detail="Failed to assign permission")
        
        return {
            "success": True,
            "message": f"Permission '{permission['permission_name']}' assigned to group '{group['group_name']}'"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error assigning permission: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to assign permission")


@router.get("/permission-groups/{group_hash}/permissions")
async def get_permission_group_permissions(group_hash: str, session_data=Depends(require_valid_session)):
    """Get all permissions in a permission group"""
    try:
        group = global_roles.get_permission_group_by_hash(group_hash)
        if not group:
            raise HTTPException(status_code=404, detail="Permission group not found")
        
        permissions = global_roles.get_permission_group_permissions(group['id'])
        return {
            "success": True,
            "permission_group": {"group_hash": group_hash, "group_name": group['group_name']},
            "permissions": permissions
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting permissions: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get permissions")


# =============================================================================
# PERMISSION MANAGEMENT
# =============================================================================

@router.post("/permissions", status_code=201)
async def create_permission(permission: PermissionCreate, session_data=Depends(require_admin)):
    """Create a new global permission"""
    try:
        user_data = get_user_by_hash(session_data.user_hash)
        
        new_permission = global_roles.create_permission(
            permission_name=permission.permission_name,
            permission_display_name=permission.permission_display_name,
            permission_description=permission.permission_description,
            permission_category=permission.permission_category,
            created_by=user_data.id
        )
        
        if not new_permission:
            raise HTTPException(status_code=400, detail="Failed to create permission")
        
        return {
            "success": True,
            "message": f"Permission '{permission.permission_name}' created successfully",
            "permission": new_permission
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating permission: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create permission")


@router.get("/permissions")
async def list_permissions(
    category: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session_data=Depends(require_valid_session)
):
    """List all global permissions"""
    try:
        permissions = global_roles.list_permissions(category=category, limit=limit, offset=offset)
        return {
            "success": True,
            "permissions": permissions,
            "pagination": {"limit": limit, "offset": offset, "total": len(permissions)}
        }
    except Exception as e:
        logger.error(f"Error listing permissions: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list permissions")


@router.get("/permissions/{permission_hash}")
async def get_permission(permission_hash: str, session_data=Depends(require_valid_session)):
    """Get permission by hash"""
    try:
        permission = global_roles.get_permission_by_hash(permission_hash)
        if not permission:
            raise HTTPException(status_code=404, detail="Permission not found")
        
        return {"success": True, "permission": permission}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting permission: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get permission")


# =============================================================================
# USER ROLE ASSIGNMENT ENDPOINTS
# =============================================================================

@router.put("/users/{user_hash}/role")
async def assign_role_to_user(
    user_hash: str,
    assignment: UserRoleAssignment,
    session_data=Depends(require_admin)
):
    """Assign a role to a user"""
    try:
        user = get_user_by_hash(user_hash)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        role = global_roles.get_role_by_hash(assignment.role_hash)
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")
        
        success = global_roles.assign_role_to_user(user.id, role['id'])
        if not success:
            raise HTTPException(status_code=400, detail="Failed to assign role")
        
        return {
            "success": True,
            "message": f"Role '{role['role_name']}' assigned to user '{user.username}'",
            "user": {"user_hash": user_hash, "username": user.username},
            "role": {"role_hash": assignment.role_hash, "role_name": role['role_name']}
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error assigning role: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to assign role")


@router.get("/users/{user_hash}/role")
async def get_user_role(user_hash: str, session_data=Depends(require_valid_session)):
    """Get user's role"""
    try:
        user = get_user_by_hash(user_hash)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        role = global_roles.get_user_role(user.id)
        
        return {
            "success": True,
            "user": {"user_hash": user_hash, "username": user.username},
            "role": role
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user role: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get user role")


# =============================================================================
# USER PERMISSION QUERY ENDPOINTS (GLOBAL - NO PROJECT CONTEXT)
# =============================================================================

@router.get("/users/me/role")
async def get_my_role(session_data=Depends(require_valid_session)):
    """Get current user's role"""
    try:
        user = get_user_by_hash(session_data.user_hash)
        role = global_roles.get_user_role(user.id)
        
        return {
            "success": True,
            "user": {"user_hash": session_data.user_hash, "username": user.username},
            "role": role
        }
    except Exception as e:
        logger.error(f"Error getting my role: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get role")


@router.get("/users/me/permissions")
async def get_my_permissions(session_data=Depends(require_valid_session)):
    """Get current user's permissions (GLOBAL - works everywhere)"""
    try:
        user = get_user_by_hash(session_data.user_hash)
        
        # Root users have all permissions
        if user.user_type == 'root':
            return {
                "success": True,
                "user": {"user_hash": session_data.user_hash, "username": user.username},
                "permissions": ["*"],
                "note": "Root user has all permissions"
            }
        
        permissions = global_roles.get_user_permissions(user.id)
        
        return {
            "success": True,
            "user": {"user_hash": session_data.user_hash, "username": user.username},
            "permissions": permissions,
            "total": len(permissions)
        }
    except Exception as e:
        logger.error(f"Error getting my permissions: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get permissions")


@router.get("/users/me/permissions/check/{permission_name}")
async def check_my_permission(permission_name: str, session_data=Depends(require_valid_session)):
    """Check if current user has a specific permission"""
    try:
        user = get_user_by_hash(session_data.user_hash)
        
        # Root users have all permissions
        if user.user_type == 'root':
            return {
                "success": True,
                "permission": permission_name,
                "has_permission": True,
                "reason": "Root user",
                "checked_at": datetime.utcnow().isoformat()
            }
        
        has_permission = global_roles.check_user_has_permission(user.id, permission_name)
        
        return {
            "success": True,
            "permission": permission_name,
            "has_permission": has_permission,
            "checked_at": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Error checking permission: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to check permission")


# =============================================================================
# CATALOG ENDPOINTS (METADATA ONLY - NOT FOR AUTHORIZATION)
# =============================================================================

@router.post("/projects/{project_hash}/catalog/roles/{role_hash}")
async def add_role_to_project_catalog(
    project_hash: str,
    role_hash: str,
    catalog_entry: CatalogEntry,
    session_data=Depends(require_admin)
):
    """Add role to project catalog (METADATA ONLY - for UI suggestions)"""
    try:
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        role = global_roles.get_role_by_hash(role_hash)
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")
        
        user_data = get_user_by_hash(session_data.user_hash)
        success = global_roles.add_role_to_project_catalog(
            role_id=role['id'],
            project_id=project.id,
            catalog_purpose=catalog_entry.catalog_purpose,
            notes=catalog_entry.notes,
            added_by=user_data.id
        )
        
        if not success:
            raise HTTPException(status_code=400, detail="Failed to add to catalog")
        
        return {
            "success": True,
            "message": f"Role '{role['role_name']}' added to project catalog",
            "note": "This is METADATA ONLY - does not affect permissions"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding to catalog: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to add to catalog")


@router.get("/projects/{project_hash}/catalog/roles")
async def get_project_cataloged_roles(project_hash: str, session_data=Depends(require_valid_session)):
    """Get roles cataloged for a project (METADATA - for UI suggestions)"""
    try:
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        cataloged_roles = global_roles.get_project_cataloged_roles(project.id)
        
        return {
            "success": True,
            "project": {"project_hash": project_hash, "project_name": project.project_name},
            "cataloged_roles": cataloged_roles,
            "note": "These are suggestions only - any role can be used with this project"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting cataloged roles: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get cataloged roles")
