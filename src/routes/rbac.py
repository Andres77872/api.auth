"""
RBAC (Role-Based Access Control) Management Routes

Handles comprehensive RBAC operations including permissions, roles, 
user assignments, and audit trails for the group-based multi-project 
authentication system.
"""

import logging
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Query, Path, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from src.Util.db import (
    validate_session, get_user_by_hash, get_project_by_hash,
    # RBAC Permission functions
    create_permission, get_project_permissions, check_user_permission,
    create_default_project_permissions,
    # RBAC Permission Group functions
    create_permission_group, assign_user_to_permission_group,
    # RBAC Initialization
    initialize_project_rbac,
    # Existing functions for project and user management
    list_all_projects, get_user_by_id
)

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/rbac", tags=["RBAC Management"])
security = HTTPBearer()

# Pydantic models
class PermissionCreate(BaseModel):
    permission_name: str
    category: str = "general"
    description: str = None

class PermissionUpdate(BaseModel):
    permission_name: str = None
    category: str = None
    description: str = None

class PermissionGroupCreate(BaseModel):
    group_name: str
    priority: int = 50
    description: str = None
    permissions: List[str] = []

class PermissionGroupUpdate(BaseModel):
    group_name: str = None
    priority: int = None
    description: str = None

class UserRoleAssignment(BaseModel):
    user_hash: str
    permission_group_id: int

class RolePermissionAssignment(BaseModel):
    permission_id: int

# Helper functions for authentication and authorization
async def require_valid_session(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Ensure user has a valid session"""
    session_data = validate_session(credentials.credentials)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    return session_data

async def require_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Ensure user has admin permissions"""
    session_data = validate_session(credentials.credentials)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    user_permissions = session_data.permissions if hasattr(session_data, 'permissions') else []
    if 'admin' not in user_permissions and 'manage_roles' not in user_permissions:
        raise HTTPException(status_code=403, detail="Admin permission required")
    
    return session_data

async def require_project_admin(project_hash: str, credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Ensure user has admin permissions for specific project"""
    session_data = validate_session(credentials.credentials)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    # Get project
    project = get_project_by_hash(project_hash)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Check if user has admin permission in this project
    user_data = get_user_by_hash(session_data.user_hash)
    if not check_user_permission(user_data.id, project.id, "admin") and \
       not check_user_permission(user_data.id, project.id, "manage_roles"):
        raise HTTPException(status_code=403, detail="Project admin permission required")
    
    return session_data, project

# =============================================================================
# PERMISSION MANAGEMENT ENDPOINTS
# =============================================================================

@router.get("/projects/{project_hash}/permissions")
async def list_project_permissions(
    project_hash: str = Path(...),
    category: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session_data = Depends(require_valid_session)
):
    """
    List all permissions for a specific project.
    
    Args:
        project_hash: Project identifier
        category: Optional filter by permission category
        limit: Maximum number of results
        offset: Number of results to skip
        
    Returns:
        List of permissions for the project
    """
    try:
        # Get project
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Get permissions
        permissions = get_project_permissions(project.id, category)
        
        # Apply pagination
        paginated_permissions = permissions[offset:offset + limit]
        
        return {
            "success": True,
            "project": {
                "project_hash": project.project_hash,
                "project_name": project.project_name
            },
            "permissions": [
                {
                    "id": perm.id,
                    "permission_name": perm.permission_name,
                    "category": perm.permission_category,
                    "description": perm.permission_description,
                    "created_at": perm.created_at
                } for perm in paginated_permissions
            ],
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total": len(permissions),
                "filtered_by_category": category
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"List project permissions error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list permissions")

@router.post("/projects/{project_hash}/permissions")
async def create_project_permission(
    project_hash: str = Path(...),
    permission_data: PermissionCreate = None,
    permission_name: str = Form(None),
    category: str = Form("general"),
    description: str = Form(None),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Create a new permission for a project.
    
    Args:
        project_hash: Project identifier
        permission_data: Permission creation data (JSON) or form fields
        
    Returns:
        Created permission information
    """
    try:
        # Check authentication and permissions
        session_data, project = await require_project_admin(project_hash, credentials)
        
        # Get permission data from either JSON or form
        if permission_data:
            perm_name = permission_data.permission_name
            perm_category = permission_data.category
            perm_description = permission_data.description
        else:
            perm_name = permission_name
            perm_category = category
            perm_description = description
        
        if not perm_name:
            raise HTTPException(status_code=400, detail="Permission name is required")
        
        # Get current user for audit trail
        user_data = get_user_by_hash(session_data.user_hash)
        
        # Create permission
        new_permission = create_permission(
            project_id=project.id,
            permission_name=perm_name,
            category=perm_category,
            description=perm_description,
            created_by=user_data.id
        )
        
        if not new_permission:
            raise HTTPException(status_code=400, detail="Permission creation failed")
        
        return {
            "success": True,
            "message": f"Permission '{perm_name}' created successfully",
            "permission": {
                "id": new_permission.id,
                "permission_name": new_permission.permission_name,
                "category": new_permission.permission_category,
                "description": new_permission.permission_description,
                "project_hash": project.project_hash,
                "created_at": new_permission.created_at
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create permission error: {str(e)}")
        raise HTTPException(status_code=500, detail="Permission creation error")

# =============================================================================
# PERMISSION GROUP (ROLE) MANAGEMENT ENDPOINTS
# =============================================================================

@router.get("/projects/{project_hash}/roles")
async def list_project_roles(
    project_hash: str = Path(...),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session_data = Depends(require_valid_session)
):
    """
    List all permission groups (roles) for a specific project.
    
    Args:
        project_hash: Project identifier
        limit: Maximum number of results
        offset: Number of results to skip
        
    Returns:
        List of roles for the project
    """
    try:
        # Get project
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Import the specific function we need
        from src.Util.db.db_rbac_permissions import get_project_permission_groups
        
        # Get permission groups
        roles = get_project_permission_groups(project.id)
        
        # Apply pagination
        paginated_roles = roles[offset:offset + limit]
        
        return {
            "success": True,
            "project": {
                "project_hash": project.project_hash,
                "project_name": project.project_name
            },
            "roles": [
                {
                    "id": role.id,
                    "group_name": role.group_name,
                    "priority": role.group_priority,
                    "description": role.group_description,
                    "created_at": role.created_at,
                    "is_active": role.is_active
                } for role in paginated_roles
            ],
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total": len(roles)
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"List project roles error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list roles")

@router.post("/projects/{project_hash}/roles")
async def create_project_role(
    project_hash: str = Path(...),
    role_data: PermissionGroupCreate = None,
    group_name: str = Form(None),
    priority: int = Form(50),
    description: str = Form(None),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Create a new permission group (role) for a project.
    
    Args:
        project_hash: Project identifier
        role_data: Role creation data (JSON) or form fields
        
    Returns:
        Created role information
    """
    try:
        # Check authentication and permissions
        session_data, project = await require_project_admin(project_hash, credentials)
        
        # Get role data from either JSON or form
        if role_data:
            role_name = role_data.group_name
            role_priority = role_data.priority
            role_description = role_data.description
            role_permissions = role_data.permissions
        else:
            role_name = group_name
            role_priority = priority
            role_description = description
            role_permissions = []
        
        if not role_name:
            raise HTTPException(status_code=400, detail="Role name is required")
        
        # Get current user for audit trail
        user_data = get_user_by_hash(session_data.user_hash)
        
        # Create permission group
        new_role = create_permission_group(
            project_id=project.id,
            group_name=role_name,
            priority=role_priority,
            description=role_description,
            created_by=user_data.id
        )
        
        if not new_role:
            raise HTTPException(status_code=400, detail="Role creation failed")
        
        # Assign permissions if specified
        assigned_permissions = []
        if role_permissions:
            from src.Util.db.db_rbac_permissions import assign_permission_to_group
            for perm_name in role_permissions:
                # Get permission by name
                project_permissions = get_project_permissions(project.id)
                permission = next((p for p in project_permissions if p.permission_name == perm_name), None)
                if permission:
                    assign_permission_to_group(new_role.id, permission.id, user_data.id)
                    assigned_permissions.append(perm_name)
        
        return {
            "success": True,
            "message": f"Role '{role_name}' created successfully",
            "role": {
                "id": new_role.id,
                "group_name": new_role.group_name,
                "priority": new_role.group_priority,
                "description": new_role.group_description,
                "project_hash": project.project_hash,
                "assigned_permissions": assigned_permissions,
                "created_at": new_role.created_at
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create role error: {str(e)}")
        raise HTTPException(status_code=500, detail="Role creation error")

# =============================================================================
# USER-ROLE ASSIGNMENT ENDPOINTS
# =============================================================================

@router.post("/users/{user_hash}/projects/{project_hash}/roles")
async def assign_user_to_role(
    user_hash: str = Path(...),
    project_hash: str = Path(...),
    role_id: int = Form(...),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Assign a user to a role in a specific project.
    
    Args:
        user_hash: User identifier
        project_hash: Project identifier
        role_id: Permission group (role) ID
        
    Returns:
        Assignment confirmation
    """
    try:
        # Check authentication and permissions
        session_data, project = await require_project_admin(project_hash, credentials)
        
        # Get target user
        target_user = get_user_by_hash(user_hash)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get current user for audit trail
        current_user = get_user_by_hash(session_data.user_hash)
        
        # Assign user to permission group
        assignment = assign_user_to_permission_group(
            user_id=target_user.id,
            project_id=project.id,
            permission_group_id=role_id,
            assigned_by=current_user.id
        )
        
        if not assignment:
            raise HTTPException(status_code=400, detail="Role assignment failed")
        
        return {
            "success": True,
            "message": f"User '{target_user.username}' assigned to role in project '{project.project_name}'",
            "assignment": {
                "user_hash": user_hash,
                "project_hash": project_hash,
                "role_id": role_id,
                "assigned_by": current_user.username,
                "assigned_at": assignment.assigned_at
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User role assignment error: {str(e)}")
        raise HTTPException(status_code=500, detail="Role assignment error")

@router.get("/users/{user_hash}/projects/{project_hash}/roles")
async def list_user_roles_in_project(
    user_hash: str = Path(...),
    project_hash: str = Path(...),
    session_data = Depends(require_valid_session)
):
    """
    List all roles assigned to a user in a specific project.
    
    Args:
        user_hash: User identifier
        project_hash: Project identifier
        
    Returns:
        List of user's roles in the project
    """
    try:
        # Get project
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Get target user
        target_user = get_user_by_hash(user_hash)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Check if current user can view this information
        current_user = get_user_by_hash(session_data.user_hash)
        if (current_user.id != target_user.id and 
            not check_user_permission(current_user.id, project.id, "admin") and
            not check_user_permission(current_user.id, project.id, "manage_users")):
            raise HTTPException(status_code=403, detail="Permission denied")
        
        # Get user's roles in project
        from src.Util.db.db_rbac_permissions import get_user_permission_groups_in_project
        user_roles = get_user_permission_groups_in_project(target_user.id, project.id)
        
        return {
            "success": True,
            "user": {
                "user_hash": user_hash,
                "username": target_user.username
            },
            "project": {
                "project_hash": project_hash,
                "project_name": project.project_name
            },
            "roles": [
                {
                    "id": role.id,
                    "group_name": role.group_name,
                    "priority": role.group_priority,
                    "description": role.group_description,
                    "assigned_at": role.assigned_at
                } for role in user_roles
            ]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"List user roles error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list user roles")

# =============================================================================
# PERMISSION CHECKING ENDPOINTS
# =============================================================================

@router.get("/users/{user_hash}/projects/{project_hash}/permissions")
async def get_user_effective_permissions(
    user_hash: str = Path(...),
    project_hash: str = Path(...),
    session_data = Depends(require_valid_session)
):
    """
    Get all effective permissions for a user in a specific project.
    
    Args:
        user_hash: User identifier
        project_hash: Project identifier
        
    Returns:
        User's effective permissions in the project
    """
    try:
        # Get project
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Get target user
        target_user = get_user_by_hash(user_hash)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Check if current user can view this information
        current_user = get_user_by_hash(session_data.user_hash)
        if (current_user.id != target_user.id and 
            not check_user_permission(current_user.id, project.id, "admin") and
            not check_user_permission(current_user.id, project.id, "manage_users")):
            raise HTTPException(status_code=403, detail="Permission denied")
        
        # Get user's effective permissions
        from src.Util.db.db_rbac_permissions import get_user_effective_permissions
        effective_permissions = get_user_effective_permissions(target_user.id, project.id)
        
        return {
            "success": True,
            "user": {
                "user_hash": user_hash,
                "username": target_user.username
            },
            "project": {
                "project_hash": project_hash,
                "project_name": project.project_name
            },
            "effective_permissions": [
                {
                    "permission_name": perm.permission_name,
                    "category": perm.permission_category,
                    "description": perm.permission_description,
                    "granted_through_role": perm.granted_through_role if hasattr(perm, 'granted_through_role') else None
                } for perm in effective_permissions
            ],
            "summary": {
                "total_permissions": len(effective_permissions),
                "categories": list(set(perm.permission_category for perm in effective_permissions))
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get user permissions error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get user permissions")

@router.get("/users/{user_hash}/projects/{project_hash}/check/{permission_name}")
async def check_user_specific_permission(
    user_hash: str = Path(...),
    project_hash: str = Path(...),
    permission_name: str = Path(...),
    session_data = Depends(require_valid_session)
):
    """
    Check if a user has a specific permission in a project.
    
    Args:
        user_hash: User identifier
        project_hash: Project identifier
        permission_name: Name of the permission to check
        
    Returns:
        Permission check result
    """
    try:
        # Get project
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Get target user
        target_user = get_user_by_hash(user_hash)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Check permission
        has_permission = check_user_permission(target_user.id, project.id, permission_name)
        
        return {
            "success": True,
            "user": {
                "user_hash": user_hash,
                "username": target_user.username
            },
            "project": {
                "project_hash": project_hash,
                "project_name": project.project_name
            },
            "permission_check": {
                "permission_name": permission_name,
                "has_permission": has_permission,
                "checked_at": datetime.utcnow().isoformat()
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Check user permission error: {str(e)}")
        raise HTTPException(status_code=500, detail="Permission check error")

# =============================================================================
# RBAC INITIALIZATION ENDPOINTS
# =============================================================================

@router.post("/projects/{project_hash}/initialize")
async def initialize_project_rbac_endpoint(
    project_hash: str = Path(...),
    create_default_permissions: bool = Query(True),
    create_default_roles: bool = Query(True),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Initialize RBAC system for a project with default permissions and roles.
    
    Args:
        project_hash: Project identifier
        create_default_permissions: Whether to create default permissions
        create_default_roles: Whether to create default roles
        
    Returns:
        Initialization result
    """
    try:
        # Check authentication and permissions
        session_data, project = await require_project_admin(project_hash, credentials)
        
        # Get current user for audit trail
        user_data = get_user_by_hash(session_data.user_hash)
        
        # Initialize RBAC
        initialization_result = initialize_project_rbac(
            project_id=project.id,
            create_defaults=create_default_permissions,
            create_roles=create_default_roles,
            created_by=user_data.id
        )
        
        if not initialization_result:
            raise HTTPException(status_code=400, detail="RBAC initialization failed")
        
        # Get summary of what was created
        permissions = get_project_permissions(project.id) if create_default_permissions else []
        
        from src.Util.db.db_rbac_permissions import get_project_permission_groups
        roles = get_project_permission_groups(project.id) if create_default_roles else []
        
        return {
            "success": True,
            "message": f"RBAC system initialized for project '{project.project_name}'",
            "project": {
                "project_hash": project_hash,
                "project_name": project.project_name
            },
            "initialization_summary": {
                "permissions_created": len(permissions),
                "roles_created": len(roles),
                "default_permissions": create_default_permissions,
                "default_roles": create_default_roles,
                "initialized_by": user_data.username,
                "initialized_at": datetime.utcnow().isoformat()
            },
            "created_permissions": [perm.permission_name for perm in permissions] if permissions else [],
            "created_roles": [role.group_name for role in roles] if roles else []
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"RBAC initialization error: {str(e)}")
        raise HTTPException(status_code=500, detail="RBAC initialization error")

# =============================================================================
# AUDIT AND REPORTING ENDPOINTS
# =============================================================================

@router.get("/projects/{project_hash}/audit")
async def get_project_audit_log(
    project_hash: str = Path(...),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    action_type: Optional[str] = Query(None),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Get audit log for RBAC operations in a project.
    
    Args:
        project_hash: Project identifier
        limit: Maximum number of results
        offset: Number of results to skip
        action_type: Optional filter by action type
        
    Returns:
        Audit log entries
    """
    try:
        # Check authentication and permissions
        session_data, project = await require_project_admin(project_hash, credentials)
        
        # Get audit log
        from src.Util.db.db_rbac_permissions import get_project_audit_log
        audit_entries = get_project_audit_log(
            project_id=project.id,
            action_type=action_type,
            limit=limit,
            offset=offset
        )
        
        return {
            "success": True,
            "project": {
                "project_hash": project_hash,
                "project_name": project.project_name
            },
            "audit_log": audit_entries,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "filtered_by_action": action_type
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get audit log error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get audit log")

@router.get("/projects/{project_hash}/summary")
async def get_project_rbac_summary(
    project_hash: str = Path(...),
    session_data = Depends(require_valid_session)
):
    """
    Get comprehensive RBAC summary for a project.
    
    Args:
        project_hash: Project identifier
        
    Returns:
        RBAC summary including permissions, roles, and assignments
    """
    try:
        # Get project
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Get RBAC data
        permissions = get_project_permissions(project.id)
        
        from src.Util.db.db_rbac_permissions import (
            get_project_permission_groups, 
            get_project_user_assignments
        )
        roles = get_project_permission_groups(project.id)
        user_assignments = get_project_user_assignments(project.id)
        
        # Group permissions by category
        permissions_by_category = {}
        for perm in permissions:
            if perm.permission_category not in permissions_by_category:
                permissions_by_category[perm.permission_category] = []
            permissions_by_category[perm.permission_category].append(perm.permission_name)
        
        return {
            "success": True,
            "project": {
                "project_hash": project_hash,
                "project_name": project.project_name
            },
            "rbac_summary": {
                "total_permissions": len(permissions),
                "total_roles": len(roles),
                "total_user_assignments": user_assignments.get('total_assignments', 0),
                "permissions_by_category": permissions_by_category,
                "roles_by_priority": [
                    {
                        "group_name": role.group_name,
                        "priority": role.group_priority,
                        "is_active": role.is_active
                    } for role in sorted(roles, key=lambda r: r.group_priority, reverse=True)
                ],
                "active_roles": len([r for r in roles if r.is_active]),
                "categories": list(permissions_by_category.keys())
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get RBAC summary error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get RBAC summary") 