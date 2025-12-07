"""
User Management Routes

Handles user profile management, updates, and access information
for the group-based multi-project authentication system.

Endpoints:
- GET /profile - Get current user's profile
- PUT /profile - Update current user's profile
- GET /access-summary - Get user's hierarchical access summary
- GET /list - List all users with filters (admin only)
- GET /search/query - Search users by username/email (admin only)
- GET /{user_hash} - Get user details
- PUT /{user_hash}/status - Update user active status
- POST /{user_hash}/reset-password - Reset user password (admin only)
- DELETE /{user_hash} - Delete user (soft delete, admin only)
- PATCH /{user_hash}/type - Change user type (root only)
"""

import logging
import json
from datetime import datetime
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, Form
from fastapi.security import HTTPAuthorizationCredentials

from src.Util.Models import (
    UserProfileResponse, UpdateProfileResponse, AccessSummaryResponse,
    ListUsersResponse, GetUserDetailsResponse, UpdateUserStatusResponse,
    ChangeUserTypeResponse, UserInfo, ProjectInfo, PaginationInfo, UpdateUserResponse
)
from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.decorators import log_and_handle_errors, log_operation_details
from src.Util.log_context_models import LogContext, OperationMetadata
from src.Util.activity_logger import ActivityType
from src.Util.error_handler import (
    AuthorizationError, ValidationError, NotFoundError, InternalError,
    ErrorCode, mask_uuid
)
from src.Util.db_error_wrapper import handle_db_operation
from src.Util.db import (
    get_user_by_hash, update_user,
    get_user_accessible_projects, get_user_groups_for_user,
    list_users_with_access, count_users,
    is_root_user, get_user_groups_in_project_by_hash, get_user_effective_permissions,
    get_user_group_membership, get_user_type_info,
    get_user_type, get_project_by_hash, get_projects_for_user_group,
    update_user_type, get_project_by_id
)
from src.Util.password_generator import create_password_reset_data

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/users", tags=["User Management"])
security = HTTPBearerOrCookie()


@router.get("/profile", response_model=UserProfileResponse)
@log_and_handle_errors(
    operation_name="get_user_profile",
    activity_type=ActivityType.USER_LOGIN,
    log_success=False
)
async def get_user_profile(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None
) -> UserProfileResponse:
    """Get the current user's profile

    Returns the current user's profile information including
    their group memberships, hierarchical access structure, and accessible projects.
    """
    # Get user data
    user_data = handle_db_operation(
        lambda: get_user_by_hash(log_context.user_hash),
        error_context="user profile retrieval",
        not_found_message=f"User not found: {mask_uuid(log_context.user_hash)}"
    )
        
    # Get user type information (includes role assignments)
    user_type_info = get_user_type_info(user_data.id)

    # Get user's groups
    user_groups = get_user_groups_for_user(user_data.id)
    
    # Get user's accessible projects through group memberships
    user_projects = get_user_accessible_projects(user_data.id)
    
    # Format groups for response
    groups = []
    for group in user_groups:
        # Get membership details for this user in this group
        membership = get_user_group_membership(user_data.id, group.id)
        groups.append({
            "group_hash": group.group_hash,
            "group_name": group.group_name,
            "group_description": group.group_description,
            "assigned_at": membership.assigned_at if membership else None,
            "assigned_by": membership.assigned_by if membership else None
        })
    
    # Format projects for response
    projects = []
    for project in user_projects:
        # Get effective permissions for this user in this project
        effective_permissions = get_user_effective_permissions(user_data.id, project.id)
        permission_names = effective_permissions if effective_permissions else []
        
        projects.append(ProjectInfo(
            project_hash=project.project_hash,
            project_name=project.project_name,
            project_description=project.project_description,
            project_group=getattr(project, 'project_group_name', None),
            permissions=permission_names
        ))

    # Build the response with enhanced information
    return UserProfileResponse(
        user_hash=user_data.user_hash,
        username=user_data.username,
        email=user_data.email,
        user_type=user_data.user_type,
        user_type_info=user_type_info,  # Include detailed user type information
        created_at=user_data.created_at,
        updated_at=user_data.updated_at,
        last_login=user_data.last_login,
        is_active=user_data.is_active,
        groups=groups,  # Include group memberships
        projects=projects
    )


@router.put("/profile", response_model=UpdateProfileResponse)
@log_and_handle_errors(
    operation_name="update_user_profile",
    activity_type=ActivityType.USER_UPDATE,
    log_success=True
)
async def update_user_profile(
        username: Optional[str] = Form(None),
        email: Optional[str] = Form(None),
        password: Optional[str] = Form(None),
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> UpdateProfileResponse:
    """
    Update current user's profile information.
    
    Args:
        username: Username
        email: Email
        password: Password
        
    Returns:
        Updated user profile
    """
    # Get current user
    current_user = handle_db_operation(
        lambda: get_user_by_hash(log_context.user_hash),
        error_context="user lookup",
        not_found_message=f"User not found: {mask_uuid(log_context.user_hash)}"
    )

    # Track changes
    changes = {}
    if username: changes['username'] = username
    if email: changes['email'] = email
    if password: changes['password'] = '***'

    # Update user
    updated_user = handle_db_operation(
        lambda: update_user(
            current_user.id,
            username=username,
            email=email,
            password=password
        ),
        error_context="user profile update"
    )

    if not updated_user:
        from src.Util.error_handler import InternalError
        raise InternalError(
            message="Failed to update user profile",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "update_profile"}
        )

    # Log detailed changes
    if changes:
        log_operation_details(
            user_id=log_context.user_id,
            operation=OperationMetadata(
                operation_name="update_profile",
                target_resource=log_context.user_hash,
                target_resource_type="user",
                changes=changes
            ),
            log_context=log_context
        )

    # Build updated user info
    user_info = UserInfo(
        user_hash=updated_user.user_hash,
        username=updated_user.username,
        email=updated_user.email,
        user_type=getattr(updated_user, 'user_type', 'consumer'),
        created_at=updated_user.created_at,
        updated_at=updated_user.updated_at
    )

    return UpdateProfileResponse(
        success=True,
        message="Profile updated successfully",
        user=user_info
    )


@router.get("/access-summary", response_model=AccessSummaryResponse)
@log_and_handle_errors(
    operation_name="get_access_summary",
    activity_type=ActivityType.USER_LOGIN,
    log_success=False
)
async def get_user_access_summary(
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> AccessSummaryResponse:
    """
    Get comprehensive summary of user's hierarchical group memberships, project access, and effective permissions.
    
    Returns:
        Detailed access summary with hierarchical groups, projects, and effective permissions
    """
    user_data = get_user_by_hash(log_context.user_hash)
    if not user_data:
        raise NotFoundError(
            message=f"User not found: {mask_uuid(log_context.user_hash)}",
            error_code=ErrorCode.USER_NOT_FOUND
        )
        
    # Get user type information with role assignments
    user_type_info = get_user_type_info(user_data.id)

    # Get user's group memberships with hierarchical information
    user_groups = get_user_groups_for_user(user_data.id)

    # Get comprehensive access information through group-based access control
    accessible_projects = get_user_accessible_projects(user_data.id)

    # Build user groups list with membership details
    group_list = []
    for group in user_groups:
        # Get membership details for this user in this group
        membership = get_user_group_membership(user_data.id, group.id)
        
        # Get projects accessible through this group
        group_projects = get_projects_for_user_group(group.id)
        
        group_list.append({
            "group_hash": group.group_hash,
            "group_name": group.group_name,
            "group_description": group.group_description,
            "assigned_at": membership.assigned_at if membership else None,
            "assigned_by": membership.assigned_by if membership else None,
            "projects_count": len(group_projects) if group_projects else 0
        })

    # Build accessible projects list with effective permissions
    project_list = []
    for proj in accessible_projects:
        # Get user's effective permissions for this project
        effective_permissions = get_user_effective_permissions(user_data.id, proj.id)
        permission_names = effective_permissions if effective_permissions else []
        
        # Get user's group memberships for this project
        user_project_groups = get_user_groups_in_project_by_hash(user_data.id, proj.project_hash)
        
        project_groups = []
        for pg in user_project_groups:
            project_groups.append({
                "group_hash": pg.group_hash if hasattr(pg, 'group_hash') else '',
                "group_name": pg.group_name,
                "permissions": pg.permissions if hasattr(pg, 'permissions') else []
            })
        
        project_list.append({
            "project_hash": proj.project_hash,
            "project_name": proj.project_name,
            "project_description": proj.project_description,
            "access_groups": project_groups,
            "effective_permissions": permission_names
        })

    # Build comprehensive access summary
    access_summary = {
        "user": {
            "user_hash": user_data.user_hash,
            "username": user_data.username,
            "user_type": user_data.user_type,
            "user_type_details": user_type_info,
            "email": user_data.email
        },
        "user_groups": group_list,
        "accessible_projects": project_list,
        "current_session": {
            "project_hash": log_context.project_hash,
            "project_name": None,
            "permissions": [],
            "expires_at": None
        },
        "summary": {
            "total_groups": len(user_groups),
            "total_projects": len(accessible_projects) if accessible_projects else 0,
            "is_admin": False
        }
    }

    return AccessSummaryResponse(
        success=True,
        access_summary=access_summary
    )


@router.get("/list", response_model=ListUsersResponse)
@log_and_handle_errors(
    operation_name="list_users",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False
)
async def list_all_users(
        limit: int = 100,
        offset: int = 0,
        sort_by: str = 'username',
        sort_order: str = 'asc',
        search: Optional[str] = None,
        user_type_filter: Optional[str] = None,
        group_filter: Optional[str] = None,
        project_filter: Optional[str] = None,
        include_inactive: bool = False,
        include_group_info: bool = True,
        include_project_access: bool = True,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None) -> ListUsersResponse:
    """
    List all users with optional filters, group/project info, and pagination.
    
    Args:
        limit: Maximum number of users to return
        offset: Offset for pagination
        sort_by: Field to sort by
        sort_order: Sort order (asc or desc)
        search: Search term for username or email
        user_type_filter: Filter by user type (root, admin, consumer)
        group_filter: Filter by user group (by hash or name)
        project_filter: Filter by project access (by hash or name) 
        include_inactive: Include inactive users
        include_group_info: Include group membership information
        include_project_access: Include project access information
        
    Returns:
        List of users matching the filters with their group memberships and project access
    """
    # Check if user has permission to list users (root or admin)
    current_user = handle_db_operation(
        lambda: get_user_by_hash(log_context.user_hash),
        error_context="user lookup",
        not_found_message=f"User not found: {mask_uuid(log_context.user_hash)}"
    )

    # Only root users can see all users across projects
    # Admin users can only see users in their assigned projects
    is_root = is_root_user(current_user.id)
    if not is_root:
        user_type = get_user_type(current_user.id)
        if user_type != 'admin':
            raise AuthorizationError(
                message="Access denied: Admin privileges required",
                error_code=ErrorCode.ACCESS_DENIED
            )
        
        # If admin, we'll filter users based on their assigned projects later
        # For now, we get their assigned projects
        admin_projects = get_user_accessible_projects(current_user.id)
        admin_project_ids = [proj.id for proj in admin_projects] if admin_projects else []

    # Fetch users using stored procedure with aggregated group/project data
    all_users = handle_db_operation(
        lambda: list_users_with_access(
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_order=sort_order,
            search=search,
            user_type_filter=user_type_filter,
            group_filter=group_filter,
            project_filter=project_filter,
            include_inactive=include_inactive
        ),
        error_context="user list retrieval"
    )

    # Total count (basic, does not yet include group/project filters)
    total_count = handle_db_operation(
        lambda: count_users(
            user_type=user_type_filter,
            search=search,
            include_inactive=include_inactive
        ),
        error_context="user count"
    )

    users_list: List[Dict[str, Any]] = []
    for user in all_users:
        user_id = user["id"]

        # Skip users not in admin's projects if current user is admin
        if not is_root and user_id != current_user.id:
            user_projects_check = get_user_accessible_projects(user_id)
            user_project_ids = [proj.id for proj in user_projects_check] if user_projects_check else []
            if not any(pid in admin_project_ids for pid in user_project_ids):
                continue

        user_type_info = get_user_type_info(user_id)

        # Parse groups JSON returned from SP
        parsed_groups = []
        if include_group_info and user.get("groups_json"):
            parsed_groups = json.loads(user["groups_json"]) if isinstance(user["groups_json"], str) else user["groups_json"]

        # Parse projects JSON and add effective permissions if requested
        parsed_projects = []
        if include_project_access and user.get("projects_json"):
            raw_projects = json.loads(user["projects_json"]) if isinstance(user["projects_json"], str) else user["projects_json"]
            for proj in raw_projects:
                # Get project_id from project_hash for permission check
                project_data = get_project_by_hash(proj["project_hash"])
                if project_data:
                    effective_permissions = get_user_effective_permissions(user_id, project_data.id)
                    proj["permissions"] = effective_permissions if effective_permissions else []
                else:
                    proj["permissions"] = []
                parsed_projects.append(proj)

        users_list.append({
            "user_hash": user["user_hash"],
            "username": user["username"],
            "email": user["email"],
            "user_type": user["user_type"],
            "user_type_info": user_type_info,
            "created_at": user["created_at"],
            "last_login": user.get("last_login"),
            "is_active": user["is_active"],
            "groups": parsed_groups if include_group_info else [],
            "projects": parsed_projects if include_project_access else []
        })

    # Pagination info
    pagination = PaginationInfo(
        total=total_count,
        limit=limit,
        offset=offset,
        has_more=(offset + len(users_list)) < total_count
    )

    filters_info = {
        "user_type_filter": user_type_filter,
        "group_filter": group_filter,
        "project_filter": project_filter,
        "search": search,
        "include_inactive": include_inactive
    }

    return ListUsersResponse(
        success=True,
        users=users_list,
        pagination=pagination,
        filters=filters_info
    )


@router.get("/{user_hash}", response_model=GetUserDetailsResponse)
@log_and_handle_errors(
    operation_name="get_user_details",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False
)
async def get_user_details(
        user_hash: str,
        include_group_hierarchy: bool = True,
        include_permission_details: bool = True,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None) -> GetUserDetailsResponse:
    """
    Get detailed information about a specific user including hierarchical group memberships and permissions.
    
    Admin users can view details of any user in their assigned projects.
    Root users can view details of any user.
    Regular users can only view their own details.
    
    Args:
        user_hash: The user hash to get details for
        include_group_hierarchy: Whether to include hierarchical group information
        include_permission_details: Whether to include detailed permission information
        
    Returns:
        Comprehensive user information including hierarchical groups, permissions, and projects
    """
    # Get current user
    current_user = handle_db_operation(
        lambda: get_user_by_hash(log_context.user_hash),
        error_context="current user lookup",
        not_found_message=f"Current user not found: {mask_uuid(log_context.user_hash)}"
    )

    # Get requested user
    target_user = handle_db_operation(
        lambda: get_user_by_hash(user_hash),
        error_context="target user lookup",
        not_found_message=f"User not found: {mask_uuid(user_hash)}"
    )

    # Check access permissions based on user type
    is_root = is_root_user(current_user.id)
    is_own_profile = current_user.user_hash == target_user.user_hash
    
    if not is_own_profile and not is_root:
        # Admin users can only view users in their assigned projects
        user_type = get_user_type(current_user.id)
        if user_type != 'admin':
            raise AuthorizationError(
                message="Access denied",
                error_code=ErrorCode.ACCESS_DENIED
            )
        
        # Check if target user is in one of the admin's projects
        admin_projects = get_user_accessible_projects(current_user.id)
        target_user_projects = get_user_accessible_projects(target_user.id)
        
        admin_project_hashes = [p.project_hash for p in admin_projects]
        target_project_hashes = [p.project_hash for p in target_user_projects]
        
        if not any(ph in admin_project_hashes for ph in target_project_hashes):
            raise AuthorizationError(
                message="Access denied: User not in your projects",
                error_code=ErrorCode.ACCESS_DENIED,
                details={"target_user": mask_uuid(user_hash)}
            )

    # Get user type information with role assignments
    user_type_info = get_user_type_info(target_user.id)
    
    # Get user's group memberships with hierarchical information if requested
    user_groups = get_user_groups_for_user(target_user.id)

    # Get user's accessible projects through group-based access
    accessible_projects = get_user_accessible_projects(target_user.id)

    # Build user groups list with membership details
    group_list = []
    for group in user_groups:
        # Get membership details for this user in this group
        membership = get_user_group_membership(target_user.id, group.id)
        
        group_data = {
            "group_hash": group.group_hash,
            "group_name": group.group_name,
            "group_description": group.group_description,
            "assigned_at": membership.assigned_at if membership else None,
            "assigned_by": membership.assigned_by if membership else None
        }
        
        # Add hierarchical information if requested
        if include_group_hierarchy:
            # Get projects accessible through this group
            group_projects = get_projects_for_user_group(group.id)
            group_data["projects_count"] = len(group_projects) if group_projects else 0
            
            # If relevant, we could add parent/child group relationships here
            # This would require adding hierarchical group queries to the database module
            
        group_list.append(group_data)

    # Build accessible projects list with detailed permissions
    project_list = []
    for proj in accessible_projects:
        project_data = {
            "project_hash": proj.project_hash,
            "project_name": proj.project_name,
            "project_description": proj.project_description
        }
        
        # Get effective permissions for this project
        if include_permission_details:
            # Get user's effective permissions for this project
            effective_permissions = get_user_effective_permissions(target_user.id, proj.id)
            permission_names = effective_permissions if effective_permissions else []
            project_data["effective_permissions"] = permission_names
            
            # Get user's group memberships for this project
            user_project_groups = get_user_groups_in_project_by_hash(target_user.id, proj.project_hash)
            
            # Format project groups
            project_groups = []
            for pg in user_project_groups:
                project_groups.append({
                    "group_hash": pg.group_hash if hasattr(pg, 'group_hash') else '',
                    "group_name": pg.group_name,
                    "permissions": pg.permissions if hasattr(pg, 'permissions') else []
                })
                
            project_data["access_groups"] = project_groups
            
        project_list.append(project_data)

    # Format the response with comprehensive user details
    user_details = {
        "user_hash": target_user.user_hash,
        "username": target_user.username,
        "email": target_user.email,
        "user_type": target_user.user_type,
        "user_type_info": user_type_info,
        "created_at": target_user.created_at,
        "updated_at": target_user.updated_at,
        "last_login": target_user.last_login,
        "is_active": target_user.is_active,
        "groups": group_list,
        "projects": project_list
    }

    return GetUserDetailsResponse(success=True, user=user_details)


@router.put("/{user_hash}/status", response_model=UpdateUserStatusResponse)
@log_and_handle_errors(
    operation_name="update_user_status",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True
)
async def update_user_status(
        user_hash: str,
        is_active: bool,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> UpdateUserStatusResponse:
    """
    Activate or deactivate a user account based on hierarchical permissions.
    
    Root users can change status of any user.
    Admin users can only change status of users within their assigned projects.
    
    Args:
        user_hash: Hash of the user to update
        is_active: New status (true=active, false=inactive)
        
    Returns:
        Updated user status with confirmation message
    """
    # Get current user
    current_user = handle_db_operation(
        lambda: get_user_by_hash(log_context.user_hash),
        error_context="current user lookup",
        not_found_message=f"Current user not found: {mask_uuid(log_context.user_hash)}"
    )
        
    # Get target user
    target_user = handle_db_operation(
        lambda: get_user_by_hash(user_hash),
        error_context="target user lookup",
        not_found_message=f"User not found: {mask_uuid(user_hash)}"
    )
        
    # Check permissions based on user type and hierarchical access
    is_root = is_root_user(current_user.id)
    
    if not is_root:
        # Only admin users can change user status
        user_type = get_user_type(current_user.id)
        if user_type != 'admin':
            raise AuthorizationError(
                message="Access denied: Admin privileges required",
                error_code=ErrorCode.ACCESS_DENIED
            )
            
        # Admin users can only manage users in their assigned projects
        admin_projects = get_user_accessible_projects(current_user.id)
        target_user_projects = get_user_accessible_projects(target_user.id)
        
        admin_project_hashes = [p.project_hash for p in admin_projects]
        target_project_hashes = [p.project_hash for p in target_user_projects]
        
        if not any(ph in admin_project_hashes for ph in target_project_hashes):
            raise AuthorizationError(
                message="Access denied: User not in your projects",
                error_code=ErrorCode.ACCESS_DENIED,
                details={"target_user": mask_uuid(user_hash)}
            )

    # Prevent root users from being deactivated by non-root users
    if target_user.user_type == 'root' and not is_active and not is_root:
        raise AuthorizationError(
            message="Cannot deactivate root users",
            error_code=ErrorCode.ACCESS_DENIED
        )
        
    # Prevent self-deactivation
    if current_user.user_hash == target_user.user_hash and not is_active:
        raise ValidationError(
            message="Cannot deactivate your own account",
            error_code=ErrorCode.INVALID_INPUT
        )

    # Update user status
    update_result = handle_db_operation(
        lambda: update_user(
            user_id=target_user.id,
            is_active=is_active
        ),
        error_context="user status update"
    )

    if not update_result:
        from src.Util.error_handler import InternalError
        raise InternalError(
            message="Failed to update user status",
            error_code=ErrorCode.INTERNAL_ERROR
        )
        
    # If deactivating user, handle cleaning up their active sessions and cache
    if not is_active:
        from src.Util.db import invalidate_user_sessions
        from src.Util.cache_manager import cache_manager
        
        # Invalidate sessions from Redis
        invalidate_user_sessions(target_user.id)
        
        # Invalidate all cached data including cached sessions
        cache_manager.invalidate_user_cache(target_user.id)

    # Log the activity with enhanced details for audit trail
    log_operation_details(
        user_id=log_context.user_id,
        operation=OperationMetadata(
            operation_name="update_user_status",
            target_resource=user_hash,
            target_resource_type="user",
            changes={"is_active": is_active},
            additional_data={
                "target_username": target_user.username,
                "changed_by": current_user.username
            }
        ),
        log_context=log_context
    )

    return UpdateUserStatusResponse(
        success=True,
        message=f"User {target_user.username} has been {'activated' if is_active else 'deactivated'}",
        user_hash=target_user.user_hash,
        is_active=is_active
    )


@router.post("/{user_hash}/reset-password")
@log_and_handle_errors(
    operation_name="reset_user_password",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True
)
async def reset_user_password(
        user_hash: str,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> Dict[str, Any]:
    """
    Reset user's password and generate temporary password.
    
    **Admin access required**: Only admin users can reset passwords.
    **Phase 2 Implementation**: Admin password reset functionality
    
    Args:
        user_hash: Hash of the user whose password to reset
        
    Returns:
        Temporary password and reset instructions
    """
    # Get current user
    current_user = handle_db_operation(
        lambda: get_user_by_hash(log_context.user_hash),
        error_context="current user lookup",
        not_found_message=f"Current user not found: {mask_uuid(log_context.user_hash)}"
    )

    # Check admin permissions
    user_type = get_user_type(current_user.id)
    is_root = is_root_user(current_user.id)
    
    if not is_root and user_type != 'admin':
        raise AuthorizationError(
            message="Admin permission required to reset passwords",
            error_code=ErrorCode.ACCESS_DENIED
        )

    # Get target user
    target_user = handle_db_operation(
        lambda: get_user_by_hash(user_hash),
        error_context="target user lookup",
        not_found_message=f"User not found: {mask_uuid(user_hash)}"
    )

    # Prevent resetting root user passwords
    if target_user.user_type == 'root':
        raise ValidationError(
            message="Cannot reset root user passwords",
            error_code=ErrorCode.INVALID_INPUT
        )

    # Generate password reset data (includes temporary password)
    reset_data = create_password_reset_data(target_user.id)
    temp_password = reset_data["temporary_password"]

    # Update user's password in database
    success = handle_db_operation(
        lambda: update_user(target_user.id, password=temp_password),
        error_context="password reset"
    )

    if not success:
        from src.Util.error_handler import InternalError
        raise InternalError(
            message="Failed to reset password",
            error_code=ErrorCode.INTERNAL_ERROR
        )

    # Log the activity
    log_operation_details(
        user_id=log_context.user_id,
        operation=OperationMetadata(
            operation_name="reset_user_password",
            target_resource=user_hash,
            target_resource_type="user",
            additional_data={
                "target_username": target_user.username,
                "reset_by": current_user.username
            }
        ),
        log_context=log_context
    )

    return {
        "success": True,
        "message": "Password reset successfully",
        "user": {
            "user_hash": target_user.user_hash,
            "username": target_user.username,
            "email": target_user.email
        },
        "reset_data": {
            "temporary_password": temp_password,
            "expires_at": reset_data["expires_at"],
            "must_change_on_login": True
        },
        "instructions": "User must change password on next login"
    }


@router.delete("/{user_hash}")
@log_and_handle_errors(
    operation_name="delete_user",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True
)
async def delete_user_endpoint(
        user_hash: str,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> Dict[str, Any]:
    """
    Soft delete a user account (deactivates user).
    
    **Admin access required**: Only root or admin users can delete users.
    Root users can delete any user except themselves.
    Admin users can only delete users in their assigned projects.
    
    Args:
        user_hash: Hash of the user to delete
        
    Returns:
        Deletion confirmation with user details
    """
    from src.Util.db import delete_user
    
    # Get current user
    current_user = handle_db_operation(
        lambda: get_user_by_hash(log_context.user_hash),
        error_context="current user lookup",
        not_found_message=f"Current user not found: {mask_uuid(log_context.user_hash)}"
    )

    # Check admin permissions
    is_root = is_root_user(current_user.id)
    user_type = get_user_type(current_user.id)
    
    if not is_root and user_type != 'admin':
        raise AuthorizationError(
            message="Admin permission required to delete users",
            error_code=ErrorCode.ACCESS_DENIED
        )

    # Get target user
    target_user = handle_db_operation(
        lambda: get_user_by_hash(user_hash),
        error_context="target user lookup",
        not_found_message=f"User not found: {mask_uuid(user_hash)}"
    )

    # Prevent self-deletion
    if current_user.user_hash == target_user.user_hash:
        raise ValidationError(
            message="Cannot delete your own account",
            error_code=ErrorCode.INVALID_INPUT
        )

    # Prevent deleting root users by non-root users
    if target_user.user_type == 'root' and not is_root:
        raise AuthorizationError(
            message="Cannot delete root users",
            error_code=ErrorCode.ACCESS_DENIED
        )

    # Admin users can only delete users in their assigned projects
    if not is_root:
        admin_projects = get_user_accessible_projects(current_user.id)
        target_user_projects = get_user_accessible_projects(target_user.id)
        
        admin_project_hashes = [p.project_hash for p in admin_projects]
        target_project_hashes = [p.project_hash for p in target_user_projects]
        
        if not any(ph in admin_project_hashes for ph in target_project_hashes):
            raise AuthorizationError(
                message="Access denied: User not in your projects",
                error_code=ErrorCode.ACCESS_DENIED,
                details={"target_user": mask_uuid(user_hash)}
            )

    # Perform soft delete
    success = handle_db_operation(
        lambda: delete_user(target_user.id, deleted_by=current_user.id),
        error_context="user deletion"
    )

    if not success:
        from src.Util.error_handler import InternalError
        raise InternalError(
            message="Failed to delete user",
            error_code=ErrorCode.INTERNAL_ERROR
        )

    # Invalidate user sessions and cache
    from src.Util.db import invalidate_user_sessions
    from src.Util.cache_manager import cache_manager
    
    invalidate_user_sessions(target_user.id)
    cache_manager.invalidate_user_cache(target_user.id)

    # Log the activity
    log_operation_details(
        user_id=log_context.user_id,
        operation=OperationMetadata(
            operation_name="delete_user",
            target_resource=user_hash,
            target_resource_type="user",
            additional_data={
                "target_username": target_user.username,
                "deleted_by": current_user.username
            }
        ),
        log_context=log_context
    )

    return {
        "success": True,
        "message": f"User '{target_user.username}' has been deleted",
        "user_hash": target_user.user_hash,
        "username": target_user.username,
        "deleted_at": datetime.utcnow().isoformat()
    }


@router.get("/search/query")
@log_and_handle_errors(
    operation_name="search_users",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False
)
async def search_users_endpoint(
        q: str,
        user_type_filter: Optional[str] = None,
        limit: int = 50,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> Dict[str, Any]:
    """
    Search users by username or email.
    
    **Admin access required**: Only root or admin users can search users.
    
    Args:
        q: Search term (searches username and email)
        user_type_filter: Optional filter by user type (root, admin, consumer)
        limit: Maximum results to return (default 50, max 100)
        
    Returns:
        List of users matching the search criteria
    """
    from src.Util.db import search_users
    
    # Get current user
    current_user = handle_db_operation(
        lambda: get_user_by_hash(log_context.user_hash),
        error_context="current user lookup",
        not_found_message=f"Current user not found: {mask_uuid(log_context.user_hash)}"
    )

    # Check admin permissions
    is_root = is_root_user(current_user.id)
    user_type = get_user_type(current_user.id)
    
    if not is_root and user_type != 'admin':
        raise AuthorizationError(
            message="Admin permission required to search users",
            error_code=ErrorCode.ACCESS_DENIED
        )

    # Validate and cap limit
    if limit > 100:
        limit = 100
    if limit < 1:
        limit = 50

    # Validate user type filter
    if user_type_filter and user_type_filter not in ['root', 'admin', 'consumer']:
        raise ValidationError(
            message="Invalid user type filter. Must be one of: root, admin, consumer",
            error_code=ErrorCode.INVALID_INPUT
        )

    # Perform search
    users = handle_db_operation(
        lambda: search_users(q, user_type=user_type_filter, limit=limit),
        error_context="user search"
    )

    # Build response
    users_list = []
    for user in users:
        user_info = {
            "user_hash": user.user_hash,
            "username": user.username,
            "email": user.email,
            "user_type": user.user_type,
            "created_at": user.created_at,
            "last_login": user.last_login,
            "is_active": user.is_active
        }
        users_list.append(user_info)

    return {
        "success": True,
        "users": users_list,
        "search_term": q,
        "total_results": len(users_list),
        "filters": {
            "user_type_filter": user_type_filter,
            "limit": limit
        }
    }


@router.patch("/{user_hash}/type", response_model=ChangeUserTypeResponse)
@log_and_handle_errors(
    operation_name="change_user_type",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True
)
async def change_user_type_endpoint(
        user_hash: str,
        user_type: str = Form(...),
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> ChangeUserTypeResponse:
    """
    Change a user's type (promote/demote users).
    
    **Root users only**: Only root users can change user types.
    This is a sensitive operation that changes user privileges.
    
    Args:
        user_hash: Hash of the user to update
        user_type: New user type (root, admin, consumer)
        
    Returns:
        Updated user type information
    """
    # Get current user
    current_user = handle_db_operation(
        lambda: get_user_by_hash(log_context.user_hash),
        error_context="current user lookup",
        not_found_message=f"Current user not found: {mask_uuid(log_context.user_hash)}"
    )
    
    # Only root users can change user types
    if not is_root_user(current_user.id):
        raise AuthorizationError(
            message="Root user access required to change user types",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_user_type": "root"}
        )
    
    # Get target user
    target_user = handle_db_operation(
        lambda: get_user_by_hash(user_hash),
        error_context="target user lookup",
        not_found_message=f"User not found: {mask_uuid(user_hash)}"
    )
    
    # Validate user type
    if user_type not in ['root', 'admin', 'consumer']:
        raise ValidationError(
            message="Invalid user type. Must be 'root', 'admin', or 'consumer'",
            error_code=ErrorCode.INVALID_ENUM_VALUE,
            details={"field": "user_type", "allowed_values": ['root', 'admin', 'consumer']}
        )
    
    # Store previous type for response
    previous_type = target_user.user_type
    
    # Update user type
    success = handle_db_operation(
        lambda: update_user_type(
            user_id=target_user.id,
            new_user_type=user_type,
            updated_by=current_user.id
        ),
        error_context="user type update"
    )
    
    if not success:
        from src.Util.error_handler import InternalError
        raise InternalError(
            message="Failed to update user type",
            error_code=ErrorCode.INTERNAL_ERROR
        )
    
    # Log the activity
    log_operation_details(
        user_id=log_context.user_id,
        operation=OperationMetadata(
            operation_name="change_user_type",
            target_resource=user_hash,
            target_resource_type="user",
            changes={
                "previous_type": previous_type,
                "new_type": user_type
            },
            additional_data={
                "target_username": target_user.username,
                "changed_by": current_user.username
            }
        ),
        log_context=log_context
    )
    
    return ChangeUserTypeResponse(
        success=True,
        message=f"User type changed successfully",
        user_hash=target_user.user_hash,
        previous_type=previous_type,
        new_type=user_type
    )


@router.put("/{user_hash}", response_model=UpdateUserResponse)
@log_and_handle_errors(
    operation_name="update_user_details",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True
)
async def update_user_details_endpoint(
        user_hash: str,
        username: Optional[str] = Form(None),
        email: Optional[str] = Form(None),
        user_type: Optional[str] = Form(None),
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> UpdateUserResponse:
    """
    Update user details (admin/root operation).
    
    **Root/Admin access required**:
    - Root users can update any user including user_type changes
    - Admin users can update users in their projects (except user_type)
    
    Args:
        user_hash: Hash of the user to update
        username: New username (optional)
        email: New email (optional)
        user_type: New user type (optional, ROOT only)
        
    Returns:
        Updated user information
    """
    # Get current user
    current_user = handle_db_operation(
        lambda: get_user_by_hash(log_context.user_hash),
        error_context="current user lookup",
        not_found_message=f"Current user not found: {mask_uuid(log_context.user_hash)}"
    )
    
    # Check permissions
    is_root = is_root_user(current_user.id)
    current_user_type = get_user_type(current_user.id)
    
    if not is_root and current_user_type != 'admin':
        raise AuthorizationError(
            message="Admin or root access required",
            error_code=ErrorCode.ACCESS_DENIED
        )
    
    # Get target user
    target_user = handle_db_operation(
        lambda: get_user_by_hash(user_hash),
        error_context="target user lookup",
        not_found_message=f"User not found: {mask_uuid(user_hash)}"
    )
    
    # Only root users can change user types
    if user_type and not is_root:
        raise AuthorizationError(
            message="Root user access required to change user types",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_user_type": "root"}
        )
    
    # Validate user type if provided
    if user_type and user_type not in ['root', 'admin', 'consumer']:
        raise ValidationError(
            message="Invalid user type. Must be 'root', 'admin', or 'consumer'",
            error_code=ErrorCode.INVALID_ENUM_VALUE,
            details={"field": "user_type", "allowed_values": ['root', 'admin', 'consumer']}
        )
    
    # Admin users can only update users in their projects
    if not is_root:
        admin_projects = get_user_accessible_projects(current_user.id)
        target_user_projects = get_user_accessible_projects(target_user.id)
        
        admin_project_hashes = [p.project_hash for p in admin_projects]
        target_project_hashes = [p.project_hash for p in target_user_projects]
        
        if not any(ph in admin_project_hashes for ph in target_project_hashes):
            raise AuthorizationError(
                message="Access denied: User not in your projects",
                error_code=ErrorCode.ACCESS_DENIED,
                details={"target_user": mask_uuid(user_hash)}
            )
    
    # Check if at least one field is provided
    if not any([username, email, user_type]):
        raise ValidationError(
            message="At least one field must be provided to update",
            error_code=ErrorCode.INVALID_INPUT,
            details={"required_fields": ["username", "email", "user_type"]}
        )
    
    # Track changes
    changes = {}
    if username:
        changes['username'] = username
    if email:
        changes['email'] = email
    if user_type:
        changes['user_type'] = user_type
    
    # Update user
    updated_user = handle_db_operation(
        lambda: update_user(
            target_user.id,
            username=username,
            email=email,
            user_type=user_type
        ),
        error_context="user update"
    )
    
    if not updated_user:
        from src.Util.error_handler import InternalError
        raise InternalError(
            message="Failed to update user",
            error_code=ErrorCode.INTERNAL_ERROR
        )
    
    # Log the activity
    log_operation_details(
        user_id=log_context.user_id,
        operation=OperationMetadata(
            operation_name="update_user_details",
            target_resource=user_hash,
            target_resource_type="user",
            changes=changes,
            additional_data={
                "target_username": target_user.username,
                "updated_by": current_user.username
            }
        ),
        log_context=log_context
    )
    
    # Build response
    user_info = UserInfo(
        user_hash=updated_user.user_hash,
        username=updated_user.username,
        email=updated_user.email,
        user_type=updated_user.user_type,
        created_at=updated_user.created_at,
        updated_at=updated_user.updated_at
    )
    
    return UpdateUserResponse(
        success=True,
        message="User updated successfully",
        user=user_info,
        updated_at=updated_user.updated_at
    )
