"""
RBAC (Role-Based Access Control) Management Routes

Handles comprehensive RBAC operations including permissions, roles, 
user assignments, and audit trails for the group-based multi-project 
authentication system.
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Query, Path, Form
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from src.Util.Models import (
    ListPermissionsResponse, CreatePermissionResponse, ListRolesResponse, CreateRoleResponse,
    AssignUserToRoleResponse, ListUserRolesResponse, UserEffectivePermissionsResponse,
    CheckPermissionResponse, InitializeRBACResponse, ProjectAuditLogResponse, RBACProjectSummaryResponse,
    UserInfo, ProjectInfo, PermissionInfo, RoleInfo, PaginationInfo
)
from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.activity_logger import log_activity, ActivityType
from src.Util.db import (
    validate_session, get_user_by_hash, get_project_by_hash,
    # RBAC Permission functions
    create_permission, get_rbac_project_permissions as get_project_permissions, check_user_permission,
    # RBAC Permission Group functions
    create_permission_group, assign_user_to_permission_group,
    # RBAC Initialization
    initialize_project_rbac,
    # Existing functions for project and user management
)

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/rbac", tags=["RBAC Management"])
security = HTTPBearerOrCookie()


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

    # Get user information
    user_data = get_user_by_hash(session_data.user_hash)
    
    # Root users have access to all projects
    if user_data.user_type == "root":
        return session_data, project
        
    # Admin users have access to their associated projects
    if user_data.user_type == "admin" and user_data.assigned_project_id == project.id:
        return session_data, project
        
    # Otherwise check specific permissions for this project
    if not check_user_permission(user_data.id, project.id, "admin") and \
            not check_user_permission(user_data.id, project.id, "manage_roles"):
        raise HTTPException(status_code=403, detail="Project admin permission required")

    return session_data, project


# =============================================================================
# PERMISSION MANAGEMENT ENDPOINTS
# =============================================================================

@router.get("/projects/{project_hash}/permissions", response_model=ListPermissionsResponse)
async def list_project_permissions(
        project_hash: str = Path(...),
        category: Optional[str] = Query(None),
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        session_data=Depends(require_valid_session)
) -> ListPermissionsResponse:
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

        project_info = ProjectInfo(
            project_hash=project.project_hash,
            project_name=project.project_name
        )

        permission_list = [
            PermissionInfo(
                id=perm.id,
                permission_name=perm.permission_name,
                category=perm.permission_category,
                description=perm.permission_description,
                created_at=perm.created_at
            ) for perm in paginated_permissions
        ]

        pagination = PaginationInfo(
            limit=limit,
            offset=offset,
            total=len(permissions)
        )

        return ListPermissionsResponse(
            success=True,
            project=project_info,
            permissions=permission_list,
            pagination=pagination
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"List project permissions error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list permissions")


@router.post("/projects/{project_hash}/permissions", response_model=CreatePermissionResponse)
async def create_project_permission(
        project_hash: str = Path(...),
        permission_name: str = Form(...),
        category: str = Form("general"),
        description: Optional[str] = Form(None),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> CreatePermissionResponse:
    """
    Create a new permission for a project.
    
    Args:
        project_hash: Project identifier
        permission_name: Permission name
        category: Permission category
        description: Permission description
        
    Returns:
        Created permission information
    """
    try:
        # Check authentication and permissions
        session_data, project = await require_project_admin(project_hash, credentials)

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
            permission_description=perm_description,
            created_by=user_data.id
        )

        if not new_permission:
            raise HTTPException(status_code=400, detail="Permission creation failed")

        permission_info = PermissionInfo(
            id=new_permission.id,
            permission_name=new_permission.permission_name,
            category=new_permission.permission_category,
            description=new_permission.permission_description,
            created_at=new_permission.created_at
        )

        return CreatePermissionResponse(
            success=True,
            message=f"Permission '{perm_name}' created successfully",
            permission=permission_info
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create permission error: {str(e)}")
        raise HTTPException(status_code=500, detail="Permission creation error")


# =============================================================================
# PERMISSION GROUP (ROLE) MANAGEMENT ENDPOINTS
# =============================================================================

@router.get("/projects/{project_hash}/roles", response_model=ListRolesResponse)
async def list_project_roles(
        project_hash: str = Path(...),
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        session_data=Depends(require_valid_session)
) -> ListRolesResponse:
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

        project_info = ProjectInfo(
            project_hash=project.project_hash,
            project_name=project.project_name
        )

        role_list = [
            RoleInfo(
                id=role.id,
                group_name=role.group_name,
                priority=role.group_priority,
                description=role.group_description,
                created_at=role.created_at,
                is_active=role.is_active
            ) for role in paginated_roles
        ]

        pagination = PaginationInfo(
            limit=limit,
            offset=offset,
            total=len(roles)
        )

        return ListRolesResponse(
            success=True,
            project=project_info,
            roles=role_list,
            pagination=pagination
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"List project roles error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list roles")


@router.post("/projects/{project_hash}/roles", response_model=CreateRoleResponse)
async def create_project_role(
        project_hash: str = Path(...),
        group_name: str = Form(...),
        priority: int = Form(50),
        description: Optional[str] = Form(None),
        permissions: List[str] = Form([]),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> CreateRoleResponse:
    """
    Create a new permission group (role) for a project.
    
    Args:
        project_hash: Project identifier
        group_name: Role name
        priority: Role priority
        description: Role description
        permissions: Permissions list
        
    Returns:
        Created role information
    """
    try:
        # Check authentication and permissions
        session_data, project = await require_project_admin(project_hash, credentials)

        role_name = group_name
        role_priority = priority
        role_description = description
        role_permissions = permissions

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

        role_details = {
            "id": new_role.id,
            "group_name": new_role.group_name,
            "priority": new_role.group_priority,
            "description": new_role.group_description,
            "project_hash": project.project_hash,
            "assigned_permissions": assigned_permissions,
            "created_at": new_role.created_at
        }

        return CreateRoleResponse(
            success=True,
            message=f"Role '{role_name}' created successfully",
            role=role_details
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create role error: {str(e)}")
        raise HTTPException(status_code=500, detail="Role creation error")


# =============================================================================
# USER-ROLE ASSIGNMENT ENDPOINTS
# =============================================================================

@router.post("/users/{user_hash}/projects/{project_hash}/roles", response_model=AssignUserToRoleResponse)
async def assign_user_to_role(
        user_hash: str = Path(...),
        project_hash: str = Path(...),
        role_id: int = Form(...),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> AssignUserToRoleResponse:
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

        assignment_role_id = role_id

        # Get current user for audit trail
        current_user = get_user_by_hash(session_data.user_hash)

        # Assign user to permission group
        assignment = assign_user_to_permission_group(
            user_id=target_user.id,
            project_id=project.id,
            permission_group_id=assignment_role_id,
            assigned_by=current_user.id
        )

        if not assignment:
            raise HTTPException(status_code=400, detail="Role assignment failed")

        assignment_details = {
            "user_hash": user_hash,
            "project_hash": project_hash,
            "role_id": assignment_role_id,
            "assigned_by": current_user.username,
            "assigned_at": assignment.assigned_at
        }

        return AssignUserToRoleResponse(
            success=True,
            message=f"User '{target_user.username}' assigned to role in project '{project.project_name}'",
            assignment=assignment_details
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User role assignment error: {str(e)}")
        raise HTTPException(status_code=500, detail="Role assignment error")


@router.get("/users/{user_hash}/projects/{project_hash}/roles", response_model=ListUserRolesResponse)
async def list_user_roles_in_project(
        user_hash: str = Path(...),
        project_hash: str = Path(...),
        session_data=Depends(require_valid_session)
) -> ListUserRolesResponse:
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

        user_info = UserInfo(
            user_hash=user_hash,
            username=target_user.username
        )

        project_info = ProjectInfo(
            project_hash=project_hash,
            project_name=project.project_name
        )

        role_list = [
            RoleInfo(
                id=role.id,
                group_name=role.group_name,
                priority=role.group_priority,
                description=role.group_description,
                created_at=role.assigned_at
            ) for role in user_roles
        ]

        return ListUserRolesResponse(
            success=True,
            user=user_info,
            project=project_info,
            roles=role_list
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"List user roles error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list user roles")


# =============================================================================
# PERMISSION CHECKING ENDPOINTS
# =============================================================================

@router.get("/users/{user_hash}/projects/{project_hash}/permissions", response_model=UserEffectivePermissionsResponse)
async def get_user_effective_permissions(
        user_hash: str = Path(...),
        project_hash: str = Path(...),
        session_data=Depends(require_valid_session)
) -> UserEffectivePermissionsResponse:
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

        user_info = UserInfo(
            user_hash=user_hash,
            username=target_user.username
        )

        project_info = ProjectInfo(
            project_hash=project_hash,
            project_name=project.project_name
        )

        permissions_list = [
            {
                "permission_name": perm.permission_name,
                "category": perm.permission_category,
                "description": perm.permission_description,
                "granted_through_role": perm.granted_through_role if hasattr(perm, 'granted_through_role') else None
            } for perm in effective_permissions
        ]

        summary_info = {
            "total_permissions": len(effective_permissions),
            "categories": list(set(perm.permission_category for perm in effective_permissions))
        }

        return UserEffectivePermissionsResponse(
            success=True,
            user=user_info,
            project=project_info,
            effective_permissions=permissions_list,
            summary=summary_info
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get user permissions error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get user permissions")


@router.get("/users/{user_hash}/projects/{project_hash}/check/{permission_name}",
            response_model=CheckPermissionResponse)
async def check_user_specific_permission(
        user_hash: str = Path(...),
        project_hash: str = Path(...),
        permission_name: str = Path(...),
        session_data=Depends(require_valid_session)
) -> CheckPermissionResponse:
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

        user_info = UserInfo(
            user_hash=user_hash,
            username=target_user.username
        )

        project_info = ProjectInfo(
            project_hash=project_hash,
            project_name=project.project_name
        )

        permission_check_info = {
            "permission_name": permission_name,
            "has_permission": has_permission,
            "checked_at": datetime.utcnow().isoformat()
        }

        return CheckPermissionResponse(
            success=True,
            user=user_info,
            project=project_info,
            permission_check=permission_check_info
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Check user permission error: {str(e)}")
        raise HTTPException(status_code=500, detail="Permission check error")


# =============================================================================
# RBAC INITIALIZATION ENDPOINTS
# =============================================================================

@router.post("/projects/{project_hash}/initialize", response_model=InitializeRBACResponse)
async def initialize_project_rbac_endpoint(
        project_hash: str = Path(...),
        create_default_permissions: bool = Query(True),
        create_default_roles: bool = Query(True),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> InitializeRBACResponse:
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

        project_info = ProjectInfo(
            project_hash=project_hash,
            project_name=project.project_name
        )

        initialization_summary = {
            "permissions_created": len(permissions),
            "roles_created": len(roles),
            "default_permissions": create_default_permissions,
            "default_roles": create_default_roles,
            "initialized_by": user_data.username,
            "initialized_at": datetime.utcnow().isoformat()
        }

        created_permissions = [perm.permission_name for perm in permissions] if permissions else []
        created_roles = [role.group_name for role in roles] if roles else []

        return InitializeRBACResponse(
            success=True,
            message=f"RBAC system initialized for project '{project.project_name}'",
            project=project_info,
            initialization_summary=initialization_summary,
            created_permissions=created_permissions,
            created_roles=created_roles
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"RBAC initialization error: {str(e)}")
        raise HTTPException(status_code=500, detail="RBAC initialization error")


# =============================================================================
# AUDIT AND REPORTING ENDPOINTS
# =============================================================================

@router.get("/projects/{project_hash}/audit", response_model=ProjectAuditLogResponse)
async def get_project_audit_log(
        project_hash: str = Path(...),
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        action_type: Optional[str] = Query(None),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> ProjectAuditLogResponse:
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

        project_info = ProjectInfo(
            project_hash=project_hash,
            project_name=project.project_name
        )

        pagination = PaginationInfo(
            limit=limit,
            offset=offset
        )

        return ProjectAuditLogResponse(
            success=True,
            project=project_info,
            audit_log=audit_entries,
            pagination=pagination
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get audit log error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get audit log")


@router.get("/projects/{project_hash}/summary", response_model=RBACProjectSummaryResponse)
async def get_project_rbac_summary(
        project_hash: str = Path(...),
        session_data=Depends(require_valid_session)
) -> RBACProjectSummaryResponse:
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

        project_info = ProjectInfo(
            project_hash=project_hash,
            project_name=project.project_name
        )

        rbac_summary = {
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

        return RBACProjectSummaryResponse(
            success=True,
            project=project_info,
            rbac_summary=rbac_summary
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get RBAC summary error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get RBAC summary")


@router.delete("/users/{user_hash}/projects/{project_hash}/roles/{role_id}")
async def remove_user_from_role(
        user_hash: str = Path(...),
        project_hash: str = Path(...),
        role_id: int = Path(...),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Remove user from role in a project.
    
    **Phase 2 Implementation**: Remove user from role
    
    Args:
        user_hash: User identifier
        project_hash: Project identifier
        role_id: Role (permission group) ID to remove user from
        
    Returns:
        Removal confirmation
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

        # Remove user from role
        from src.Util.db.db_rbac_permissions import remove_user_from_permission_group
        success = remove_user_from_permission_group(
            user_id=target_user.id,
            project_id=project.id,
            permission_group_id=role_id,
            removed_by=current_user.id
        )

        if not success:
            raise HTTPException(status_code=400, detail="Failed to remove user from role")

        # Log the activity
        log_activity(
            user_id=current_user.id,
            activity_type=ActivityType.ROLE_REMOVED,
            details=f"Removed user {target_user.username} from role {role_id} in project {project.project_name}",
            target_user_id=target_user.id,
            project_id=project.id
        )

        logger.info(
            f"User {target_user.username} removed from role {role_id} in project {project.project_name} by {current_user.username}")

        return {
            "success": True,
            "message": f"User {target_user.username} removed from role successfully",
            "user": {
                "user_hash": target_user.user_hash,
                "username": target_user.username
            },
            "project": {
                "project_hash": project.project_hash,
                "project_name": project.project_name
            },
            "role_id": role_id,
            "removed_by": current_user.username,
            "removed_at": datetime.utcnow().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Remove user from role error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to remove user from role")


@router.post("/projects/{project_hash}/bulk-assign")
async def bulk_assign_roles(
        project_hash: str = Path(...),
        user_hashes: List[str] = Form(...),
        role_ids: List[int] = Form(...),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Bulk assign roles to users in a project.
    
    **Phase 2 Implementation**: Bulk role assignments
    
    Args:
        project_hash: Project identifier
        user_hashes: List of user hashes to assign roles to
        role_ids: List of role IDs to assign
        
    Returns:
        Bulk assignment results
    """
    try:
        # Check authentication and permissions
        session_data, project = await require_project_admin(project_hash, credentials)

        # Get current user for audit trail
        current_user = get_user_by_hash(session_data.user_hash)

        # Validate input
        if not user_hashes or not role_ids:
            raise HTTPException(status_code=400, detail="User hashes and role IDs are required")

        if len(user_hashes) > 100:
            raise HTTPException(status_code=400, detail="Maximum 100 users can be assigned at once")

        # Perform bulk assignment
        results = []
        success_count = 0
        error_count = 0
        errors = []

        for user_hash in user_hashes:
            try:
                # Get target user
                target_user = get_user_by_hash(user_hash)
                if not target_user:
                    errors.append(f"User not found: {user_hash}")
                    error_count += 1
                    continue

                user_success_count = 0
                user_errors = []

                # Assign all roles to this user
                for role_id in role_ids:
                    try:
                        assignment = assign_user_to_permission_group(
                            user_id=target_user.id,
                            project_id=project.id,
                            permission_group_id=role_id,
                            assigned_by=current_user.id
                        )

                        if assignment:
                            user_success_count += 1
                        else:
                            user_errors.append(f"Failed to assign role {role_id}")

                    except Exception as e:
                        user_errors.append(f"Role {role_id}: {str(e)}")

                results.append({
                    "user_hash": user_hash,
                    "username": target_user.username,
                    "roles_assigned": user_success_count,
                    "roles_failed": len(user_errors),
                    "errors": user_errors,
                    "status": "success" if user_success_count > 0 else "error"
                })

                if user_success_count > 0:
                    success_count += 1
                else:
                    error_count += 1

            except Exception as e:
                results.append({
                    "user_hash": user_hash,
                    "status": "error",
                    "message": str(e)
                })
                error_count += 1

        # Log the activity
        log_activity(
            user_id=current_user.id,
            activity_type=ActivityType.BULK_ROLE_ASSIGNMENT,
            details=f"Bulk assigned roles to {success_count} users in project {project.project_name}",
            project_id=project.id
        )

        logger.info(
            f"Bulk role assignment by {current_user.username} in project {project.project_name}: {success_count} users succeeded")

        return {
            "success": True,
            "message": f"Bulk role assignment completed: {success_count} users succeeded, {error_count} failed",
            "project": {
                "project_hash": project.project_hash,
                "project_name": project.project_name
            },
            "roles_assigned": role_ids,
            "summary": {
                "total_users": len(user_hashes),
                "success_count": success_count,
                "error_count": error_count
            },
            "results": results,
            "errors": errors,
            "performed_by": current_user.username,
            "performed_at": datetime.utcnow().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bulk role assignment error: {str(e)}")
        raise HTTPException(status_code=500, detail="Bulk role assignment failed")


@router.get("/projects/{project_hash}/matrix")
async def get_permission_matrix(
        project_hash: str = Path(...),
        session_data=Depends(require_valid_session)
) -> Dict[str, Any]:
    """
    Get permission matrix view for a project.
    
    **Phase 2 Implementation**: Permission matrix view
    
    Args:
        project_hash: Project identifier
        
    Returns:
        Comprehensive role-permission-user matrix
    """
    try:
        # Get project
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Check if user has access to this project
        current_user = get_user_by_hash(session_data.user_hash)
        if not check_user_permission(current_user.id, project.id, "admin") and \
                not check_user_permission(current_user.id, project.id, "view_permissions"):
            raise HTTPException(status_code=403, detail="Permission denied")

        # Get project permissions
        permissions = get_project_permissions(project.id)

        # Get project roles
        from src.Util.db.db_rbac_permissions import get_project_permission_groups, get_group_permissions, \
            get_group_users
        roles = get_project_permission_groups(project.id)

        # Build permission matrix
        matrix = {
            "project": {
                "project_hash": project.project_hash,
                "project_name": project.project_name
            },
            "permissions": [
                {
                    "id": perm.id,
                    "name": perm.permission_name,
                    "category": perm.permission_category,
                    "description": perm.permission_description
                } for perm in permissions
            ],
            "roles": [],
            "users": []
        }

        # Build roles with their permissions and users
        for role in roles:
            # TODO: Implement get_group_permissions and get_group_users functions
            role_permissions = []  # get_group_permissions(role.id)
            role_users = []  # get_group_users(role.id)

            role_data = {
                "id": role.id,
                "name": role.group_name,
                "description": role.group_description,
                "priority": role.group_priority,
                "permissions": [],  # Placeholder
                "users": []  # Placeholder
            }
            matrix["roles"].append(role_data)

        # Get all users with permissions in this project
        # TODO: Implement get_project_users_with_permissions function
        project_users = []  # get_project_users_with_permissions(project.id)

        for user in project_users:
            user_permissions = []
            user_roles = []

            # Get user's effective permissions
            # TODO: Implement get_user_permissions_in_project function
            user_perms = []  # get_user_permissions_in_project(user.id, project.id)

            for perm in user_perms:
                user_permissions.append({
                    "id": perm.id,
                    "name": perm.permission_name,
                    "category": perm.permission_category
                })

            # Get user's roles
            # TODO: Implement get_user_roles_in_project function
            user_role_assignments = []  # get_user_roles_in_project(user.id, project.id)

            for role_assignment in user_role_assignments:
                user_roles.append({
                    "id": role_assignment.id,
                    "name": role_assignment.group_name,
                    "assigned_at": role_assignment.assigned_at
                })

            user_data = {
                "user_hash": user.user_hash,
                "username": user.username,
                "email": user.email,
                "user_type": getattr(user, 'user_type', 'consumer'),
                "roles": user_roles,
                "permissions": user_permissions
            }
            matrix["users"].append(user_data)

        return {
            "success": True,
            "matrix": matrix,
            "statistics": {
                "total_permissions": len(permissions),
                "total_roles": len(roles),
                "total_users": len(project_users)
            },
            "generated_at": datetime.utcnow().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Permission matrix error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to generate permission matrix")


@router.get("/users/{user_hash}/projects/{project_hash}/history")
async def get_role_assignment_history(
        user_hash: str = Path(...),
        project_hash: str = Path(...),
        limit: int = Query(50, ge=1, le=100, description="Number of history entries to return"),
        offset: int = Query(0, ge=0, description="Number of entries to skip"),
        session_data=Depends(require_valid_session)
) -> Dict[str, Any]:
    """
    Get role assignment history for a user in a project.
    
    **Phase 2 Implementation**: Role assignment history
    
    Args:
        user_hash: User identifier
        project_hash: Project identifier
        limit: Number of history entries to return
        offset: Number of entries to skip
        
    Returns:
        Role assignment history with audit trail
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
                not check_user_permission(current_user.id, project.id, "view_audit_logs")):
            raise HTTPException(status_code=403, detail="Permission denied")

        # Get role assignment history
        # TODO: Implement get_user_role_assignment_history function
        history = []  # get_user_role_assignment_history(target_user.id, project.id, limit, offset)

        # Format history data
        history_data = []
        for entry in history:
            history_entry = {
                "id": entry.id,
                "action": entry.action,  # 'assigned', 'removed', 'modified'
                "role": {
                    "id": entry.role_id,
                    "name": entry.role_name,
                    "description": entry.role_description
                },
                "performed_by": {
                    "user_hash": entry.performed_by_hash,
                    "username": entry.performed_by_username
                },
                "performed_at": entry.performed_at,
                "details": entry.details,
                "is_active": entry.is_active
            }
            history_data.append(history_entry)

        # Get total count for pagination
        # TODO: Implement count_user_role_assignment_history function
        total_count = 0  # count_user_role_assignment_history(target_user.id, project.id)

        return {
            "success": True,
            "user": {
                "user_hash": target_user.user_hash,
                "username": target_user.username,
                "email": target_user.email
            },
            "project": {
                "project_hash": project.project_hash,
                "project_name": project.project_name
            },
            "history": history_data,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total": total_count,
                "has_more": offset + limit < total_count,
                "next_offset": offset + limit if offset + limit < total_count else None
            },
            "generated_at": datetime.utcnow().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Role assignment history error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve role assignment history")
