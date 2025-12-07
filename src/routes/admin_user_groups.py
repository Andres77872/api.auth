"""
Admin User Group Management Routes

Handles global user group administration including creation, management,
and access control for the group-based multi-project authentication system.
"""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, Query, Path, Form, Body
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from src.Util.Models import (
    ListUserGroupsResponse, CreateUserGroupResponse, UserGroupDetailsResponse,
    UpdateUserGroupResponse, DeleteUserGroupResponse, AssignUserToGroupResponse,
    RemoveUserFromGroupResponse, UserInfo, UserGroupInfo, ProjectInfo, PaginationInfo, 
    GroupMembersPaginatedResponse, BulkAddUsersToGroupRequest, BulkAddUsersToGroupResponse, 
    UserGroupsForUserResponse,
    # Groups-of-Groups Architecture models
    GrantUserGroupProjectGroupAccessResponse, RevokeUserGroupProjectGroupAccessResponse,
    ListProjectGroupsForUserGroupResponse
)
from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.activity_logger import ActivityLogger, ActivityType
from src.Util.db import (
    validate_session, get_user_by_hash,
    create_user_group, get_user_group_by_hash,
    list_all_user_groups, update_user_group,
    delete_user_group, assign_user_to_user_group,
    remove_user_from_user_group, get_users_in_group,
    get_projects_for_user_group, get_user_groups_for_user,
    get_total_user_groups_count,
    # Groups-of-Groups Architecture functions
    grant_user_group_project_group_access, revoke_user_group_project_group_access,
    get_project_groups_for_user_group,
    # Project group functions
    get_project_permission_group_by_hash
)
from src.Util.error_handler import (
    AuthenticationError, AuthorizationError, ValidationError,
    NotFoundError, ConflictError, InternalError, ErrorCode
)

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/admin/user-groups", tags=["Admin - User Groups"])
security = HTTPBearerOrCookie()


# Note: All endpoints use Form data instead of JSON/Pydantic models for consistency


# Helper function to check admin permissions
async def require_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Ensure user has admin permissions"""
    session_data = validate_session(credentials.credentials)
    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    user_permissions = session_data.permissions if hasattr(session_data, 'permissions') else []
    if 'admin' not in user_permissions and 'manage_users' not in user_permissions:
        raise AuthorizationError(
            message="Admin or manage_users permission required",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_permissions": ["admin", "manage_users"]}
        )

    return session_data


@router.get("", response_model=ListUserGroupsResponse)
async def list_user_groups(
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        sort_by: str = Query('group_name', description="Field to sort by (group_name, created_at, updated_at, id)"),
        sort_order: str = Query('asc', description="Sort direction (asc or desc)"),
        search: str = Query(None, description="Search term to filter group names"),
        session_data=Depends(require_admin)
) -> ListUserGroupsResponse:
    """
    List all global user groups (admin only).
    
    Args:
        limit: Number of groups to return
        offset: Number of groups to skip
        sort_by: Field to sort by
        sort_order: Sort direction (asc or desc)
        search: Search term to filter group names
        
    Returns:
        List of user groups with member counts
    """
    # Get all user groups with sorting parameters
    user_groups = list_all_user_groups(limit, offset, sort_by, sort_order, search)

    # Add member counts
    groups_with_counts = []
    for group in user_groups:
        members = get_users_in_group(group.id)
        group_info = UserGroupInfo(
            group_hash=group.group_hash,
            group_name=group.group_name,
            description=group.group_description,
            member_count=len(members),
            created_at=group.created_at
        )
        groups_with_counts.append(group_info)

    # Get total count for pagination
    total_count = get_total_user_groups_count()
    
    pagination = PaginationInfo(
        limit=limit,
        offset=offset,
        total=total_count
    )

    return ListUserGroupsResponse(
        success=True,
        user_groups=groups_with_counts,
        pagination=pagination
    )

@router.post("", response_model=CreateUserGroupResponse)
async def create_user_group_endpoint(
        group_name: str = Form(...),
        description: Optional[str] = Form(None),
        session_data=Depends(require_admin)
) -> CreateUserGroupResponse:
    """
    Create a new global user group (admin only).
    
    Args:
        group_name: Group name
        description: Group description
        
    Returns:
        Created user group information
    """
    # Get current user for audit trail
    user_data = get_user_by_hash(session_data.user_hash)

    if not group_name:
        raise ValidationError(
            message="Group name is required",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"field": "group_name"}
        )

    # Create user group - db layer converts IntegrityError to ConflictError automatically
    new_group = create_user_group(
        group_name,
        description,
        created_by=user_data.id
    )

    if not new_group:
        raise InternalError(
            message="User group creation failed",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "create_user_group"}
        )

    group_info = UserGroupInfo(
        group_hash=new_group.group_hash,
        group_name=new_group.group_name,
        description=new_group.group_description,
        created_at=new_group.created_at
    )

    return CreateUserGroupResponse(
        success=True,
        message=f"User group \"{group_name}\" created successfully",
        user_group=group_info
    )


@router.get("/{group_hash}", response_model=UserGroupDetailsResponse)
async def get_user_group_details(
        group_hash: str = Path(...),
        session_data=Depends(require_admin)
) -> UserGroupDetailsResponse:
    """
    Get detailed user group information (admin only).
    
    Includes both legacy direct project access AND groups-of-groups architecture data.
    
    Args:
        group_hash: User group identifier
        
    Returns:
        User group details with members, project access, and project groups
    """
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.USER_GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )

    # Get members
    members = get_users_in_group(user_group.id)

    # Get directly accessible projects (legacy)
    accessible_projects = get_projects_for_user_group(user_group.id)

    # Get project groups (groups-of-groups architecture)
    project_groups = get_project_groups_for_user_group(user_group.id)

    group_info = UserGroupInfo(
        group_hash=user_group.group_hash,
        group_name=user_group.group_name,
        description=user_group.group_description,
        created_at=user_group.created_at
    )

    member_list = [
        UserInfo(
            user_hash=member.user_hash,
            username=member.username,
            email=member.email
        ) for member in members
    ]

    # Legacy direct project access
    project_list = [
        ProjectInfo(
            project_hash=project[1],
            project_name=project[2]
        ) for project in accessible_projects
    ]

    # Note: project_count is not available from the stored procedure
    # total_derived_projects would require a separate query to count projects in each project group
    statistics_info = {
        "total_members": len(members),
        "total_projects": len(accessible_projects),
        "total_project_groups": len(project_groups),
        "total_derived_projects": 0  # Would require separate query to calculate
    }

    return UserGroupDetailsResponse(
        success=True,
        user_group=group_info,
        members=member_list,
        accessible_projects=project_list,
        accessible_project_groups=project_groups,
        derived_projects=[],  # Could be populated with actual derived projects if needed
        statistics=statistics_info
    )

@router.put("/{group_hash}", response_model=UpdateUserGroupResponse)
async def update_user_group_endpoint(
        group_hash: str = Path(...),
        group_name: Optional[str] = Form(None),
        description: Optional[str] = Form(None),
        session_data=Depends(require_admin)
) -> UpdateUserGroupResponse:
    """
    Update user group information (admin only).
    
    Args:
        group_hash: User group identifier
        group_name: Group name
        description: Group description
        
    Returns:
        Updated user group information
    """
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )

    update_name = group_name
    update_description = description

    # Update group
    updated_group = update_user_group(
        user_group.id,
        group_name=update_name,
        group_description=update_description
    )

    if not updated_group:
        raise InternalError(
            message="Update failed",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "update_user_group"}
        )

    group_info = UserGroupInfo(
        group_hash=updated_group.group_hash,
        group_name=updated_group.group_name,
        description=updated_group.group_description
    )

    return UpdateUserGroupResponse(
        success=True,
        message="User group updated successfully",
        user_group=group_info
    )

@router.delete("/{group_hash}", response_model=DeleteUserGroupResponse)
async def delete_user_group_endpoint(
        group_hash: str = Path(...),
        session_data=Depends(require_admin)
) -> DeleteUserGroupResponse:
    """
    Delete a user group (admin only).
    
    Args:
        group_hash: User group identifier
        
    Returns:
        Deletion confirmation
    """
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )

    # Get current user for audit trail
    user_data = get_user_by_hash(session_data.user_hash)

    # Delete group
    if delete_user_group(user_group.id, deleted_by=user_data.id):
        return DeleteUserGroupResponse(
            success=True,
            message=f"User group \"{user_group.group_name}\" deleted successfully",
            warning="All user memberships and project access have been revoked"
        )
    else:
        raise InternalError(
            message="Delete failed",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "delete_user_group"}
        )

@router.post("/{group_hash}/members", response_model=AssignUserToGroupResponse)
async def assign_user_to_group_endpoint(
        group_hash: str = Path(...),
        user_hash: str = Form(...),
        session_data=Depends(require_admin)
) -> AssignUserToGroupResponse:
    """
    Assign a user to a user group (admin only).
    
    Args:
        group_hash: User group identifier
        user_hash: User hash
        
    Returns:
        Assignment confirmation
    """
    target_user_hash = user_hash

    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )

    # Get target user
    target_user = get_user_by_hash(target_user_hash)
    if not target_user:
        raise NotFoundError(
            message="Target user not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": target_user_hash}
        )

    # Get current user for audit trail
    current_user = get_user_by_hash(session_data.user_hash)

    # Assign user to group
    assignment_result = assign_user_to_user_group(
        target_user.id,
        user_group.id,
        assigned_by=current_user.id
    )

    if not assignment_result:
        raise InternalError(
            message="Assignment failed",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "assign_user_to_user_group"}
        )

    assignment_info = {
        "user": {
            "user_hash": target_user.user_hash,
            "username": target_user.username
        },
        "group": {
            "group_hash": user_group.group_hash,
            "group_name": user_group.group_name
        },
        "assigned_by": current_user.username
    }

    return AssignUserToGroupResponse(
        success=True,
        message=f"User \"{target_user.username}\" assigned to group \"{user_group.group_name}\"",
        assignment=assignment_info
    )

@router.delete("/{group_hash}/members/{user_hash}", response_model=RemoveUserFromGroupResponse)
async def remove_user_from_group_endpoint(
        group_hash: str = Path(...),
        user_hash: str = Path(...),
        session_data=Depends(require_admin)
) -> RemoveUserFromGroupResponse:
    """
    Remove a user from a user group (admin only).
    
    Args:
        group_hash: User group identifier
        user_hash: User identifier
        
    Returns:
        Removal confirmation
    """
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )

    # Get target user
    target_user = get_user_by_hash(user_hash)
    if not target_user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": user_hash}
        )

    # Get current user for audit trail
    current_user = get_user_by_hash(session_data.user_hash)

    # Remove user from group
    if remove_user_from_user_group(target_user.id, user_group.id, removed_by=current_user.id):
        return RemoveUserFromGroupResponse(
            success=True,
            message=f"User \"{target_user.username}\" removed from group \"{user_group.group_name}\""
        )
    else:
        raise InternalError(
            message="Removal failed",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "remove_user_from_user_group"}
        )

# =================== GROUPS-OF-GROUPS ARCHITECTURE ENDPOINTS ===================
# These endpoints follow the correct architecture: USER → USER_GROUP → PROJECT_GROUP → PROJECT

@router.post("/{group_hash}/project-groups", response_model=GrantUserGroupProjectGroupAccessResponse)
async def grant_user_group_project_group_access_endpoint(
        group_hash: str = Path(...),
        project_group_hash: str = Form(...),
        session_data=Depends(require_admin)
) -> GrantUserGroupProjectGroupAccessResponse:
    """
    Grant a user group access to a project group (admin only).
    
    **Correct Architecture**: This endpoint follows the groups-of-groups pattern:
    USER → USER_GROUP → PROJECT_GROUP → PROJECT
    
    All users in the user_group will gain access to all projects in the project_group.
    
    Args:
        group_hash: User group identifier
        project_group_hash: Project group identifier
        
    Returns:
        Access grant confirmation with details
    """
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )

    # Get project group
    project_group = get_project_permission_group_by_hash(project_group_hash)
    if not project_group:
        raise NotFoundError(
            message="Project group not found",
            error_code=ErrorCode.NOT_FOUND,
            details={"project_group_hash": project_group_hash}
        )

    # Get current user for audit trail
    current_user = get_user_by_hash(session_data.user_hash)

    # Grant access via groups-of-groups architecture
    access_result = grant_user_group_project_group_access(
        user_group.id,
        project_group.id,
        granted_by=current_user.id
    )

    if not access_result:
        raise InternalError(
            message="Access grant failed",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "grant_user_group_project_group_access"}
        )

    return GrantUserGroupProjectGroupAccessResponse(
        success=True,
        message=f"User group \"{user_group.group_name}\" granted access to project group \"{project_group.group_name}\"",
        access_details=access_result,
        user_group={
            "group_hash": user_group.group_hash,
            "group_name": user_group.group_name
        },
        project_group={
            "group_hash": project_group.group_hash,
            "group_name": project_group.group_name
        }
    )


@router.delete("/{group_hash}/project-groups/{project_group_hash}", response_model=RevokeUserGroupProjectGroupAccessResponse)
async def revoke_user_group_project_group_access_endpoint(
        group_hash: str = Path(...),
        project_group_hash: str = Path(...),
        session_data=Depends(require_admin)
) -> RevokeUserGroupProjectGroupAccessResponse:
    """
    Revoke a user group's access to a project group (admin only).
    
    **Correct Architecture**: This endpoint follows the groups-of-groups pattern.
    All users in the user_group will lose access to all projects in the project_group
    (unless they have access through another user_group → project_group link).
    
    Args:
        group_hash: User group identifier
        project_group_hash: Project group identifier
        
    Returns:
        Revocation confirmation
    """
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )

    # Get project group
    project_group = get_project_permission_group_by_hash(project_group_hash)
    if not project_group:
        raise NotFoundError(
            message="Project group not found",
            error_code=ErrorCode.NOT_FOUND,
            details={"project_group_hash": project_group_hash}
        )

    # Get current user for audit trail
    current_user = get_user_by_hash(session_data.user_hash)

    # Revoke access
    if revoke_user_group_project_group_access(user_group.id, project_group.id, revoked_by=current_user.id):
        return RevokeUserGroupProjectGroupAccessResponse(
            success=True,
            message=f"User group \"{user_group.group_name}\" access to project group \"{project_group.group_name}\" revoked"
        )
    else:
        raise InternalError(
            message="Revocation failed",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "revoke_user_group_project_group_access"}
        )


@router.get("/{group_hash}/project-groups", response_model=ListProjectGroupsForUserGroupResponse)
async def list_project_groups_for_user_group(
        group_hash: str = Path(...),
        session_data=Depends(require_admin)
) -> ListProjectGroupsForUserGroupResponse:
    """
    List all project groups that a user group has access to (admin only).
    
    **Correct Architecture**: Shows the groups-of-groups structure:
    USER_GROUP → [PROJECT_GROUPS] → [PROJECTS]
    
    Args:
        group_hash: User group identifier
        
    Returns:
        List of project groups with their project counts
    """
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.USER_GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )

    # Get project groups for this user group
    project_groups = get_project_groups_for_user_group(user_group.id)

    user_group_info = UserGroupInfo(
        group_hash=user_group.group_hash,
        group_name=user_group.group_name,
        description=user_group.group_description
    )

    return ListProjectGroupsForUserGroupResponse(
        success=True,
        user_group=user_group_info,
        project_groups=project_groups,
        total_project_groups=len(project_groups),
        total_derived_projects=0  # Would require separate query to calculate
    )


@router.get("/{group_hash}/members", response_model=GroupMembersPaginatedResponse)
async def get_group_members_with_pagination(
        group_hash: str = Path(...),
        limit: int = Query(50, ge=1, le=100, description="Number of members to return"),
        offset: int = Query(0, ge=0, description="Number of members to skip"),
        session_data=Depends(require_admin)
) -> GroupMembersPaginatedResponse:
    """
    List group members with pagination.
    
    **Phase 2 Implementation**: List group members with pagination
    
    Args:
        group_hash: User group identifier
        limit: Number of members to return
        offset: Number of members to skip
        
    Returns:
        Paginated list of group members
    """
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.USER_GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )

    # Get all members first for total count
    all_members = get_users_in_group(user_group.id)
    total_count = len(all_members)

    # Apply pagination
    paginated_members = all_members[offset:offset + limit]

    # Format member data
    members_data = []
    for member in paginated_members:
        # Use assigned_at from the membership record as joined_at
        # This is set by get_users_in_group from sp_get_users_in_group stored procedure
        joined_date = getattr(member, 'assigned_at', None)
        member_info = {
            "user_hash": member.user_hash,
            "username": member.username,
            "email": member.email,
            "user_type": getattr(member, 'user_type', 'consumer'),
            "is_active": getattr(member, 'is_active', True),
            "joined_at": (joined_date.isoformat() + "Z") if joined_date else None  # API uses joined_at for membership date
        }
        members_data.append(member_info)

    pagination_info = PaginationInfo(
        limit=limit,
        offset=offset,
        total=total_count,
        has_more=offset + limit < total_count
    )

    user_group_info = UserGroupInfo(
        group_hash=user_group.group_hash,
        group_name=user_group.group_name,
        description=user_group.group_description
    )

    return GroupMembersPaginatedResponse(
        success=True,
        user_group=user_group_info,
        members=members_data,
        pagination=pagination_info,
        statistics={
            "total_members": total_count,
            "members_shown": len(members_data)
        },
        generated_at=datetime.utcnow().isoformat() + "Z"
    )

@router.post("/{group_hash}/members/bulk", response_model=BulkAddUsersToGroupResponse)
async def bulk_add_users_to_group(
        group_hash: str = Path(...),
        request: BulkAddUsersToGroupRequest = Body(...),
        session_data=Depends(require_admin)
) -> BulkAddUsersToGroupResponse:
    """
    Bulk add users to group.
    
    **Phase 2 Implementation**: Bulk add users to group
    
    **Note**: This endpoint uses JSON body (not Form data) to properly handle the list of user hashes.
    
    Args:
        group_hash: User group identifier
        request: Request body containing list of user hashes
        
    Returns:
        Bulk assignment results
    """
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )

    # Get current user for audit trail
    current_user = get_user_by_hash(session_data.user_hash)

    # Get user hashes from request
    user_hashes = request.user_hashes

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

            # Assign user to group
            assignment_result = assign_user_to_user_group(
                target_user.id,
                user_group.id,
                assigned_by=current_user.id
            )

            if assignment_result:
                results.append({
                    "user_hash": user_hash,
                    "username": target_user.username,
                    "status": "success",
                    "message": "Added to group successfully"
                })
                success_count += 1
            else:
                results.append({
                    "user_hash": user_hash,
                    "username": target_user.username,
                    "status": "error",
                    "message": "Assignment failed - user may already be in group"
                })
                error_count += 1

        except Exception as e:
            results.append({
                "user_hash": user_hash,
                "status": "error",
                "message": str(e)
            })
            error_count += 1

    # Log the activity
    ActivityLogger.log_bulk_group_assignment(
        current_user.id,
        count=success_count,
        user_group_id=user_group.id
    )

    logger.info(
        f"Bulk group assignment by {current_user.username}: {success_count} succeeded, {error_count} failed")

    return BulkAddUsersToGroupResponse(
        success=True,
        message=f"Bulk assignment completed: {success_count} succeeded, {error_count} failed",
        user_group={
            "group_hash": user_group.group_hash,
            "group_name": user_group.group_name
        },
        summary={
            "total_requested": len(user_hashes),
            "success_count": success_count,
            "error_count": error_count
        },
        results=results,
        errors=errors,
        performed_by=current_user.username,
        performed_at=datetime.utcnow().isoformat() + "Z"
    )

@router.get("/users/{user_hash}/groups", response_model=UserGroupsForUserResponse)
async def get_user_groups(
        user_hash: str = Path(...),
        session_data=Depends(require_admin)
) -> UserGroupsForUserResponse:
    """
    Get groups for specific user.
    
    **Phase 2 Implementation**: Get groups for specific user
    
    Args:
        user_hash: User identifier
        
    Returns:
        List of groups the user belongs to
    """
    # Get target user
    target_user = get_user_by_hash(user_hash)
    if not target_user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": user_hash}
        )

    # Get user's groups
    user_groups = get_user_groups_for_user(target_user.id)

    # Format group data
    groups_data = []
    for group in user_groups:
        # Use joined_at from membership record (set by get_user_groups_for_user)
        joined_date = getattr(group, 'joined_at', None)
        group_info = {
            "group_hash": group.group_hash,
            "group_name": group.group_name,
            "description": group.group_description,
            "joined_at": (joined_date.isoformat() + "Z") if joined_date else None
        }
        groups_data.append(group_info)

    return UserGroupsForUserResponse(
        success=True,
        user={
            "user_hash": target_user.user_hash,
            "username": target_user.username,
            "email": target_user.email,
            "user_type": getattr(target_user, 'user_type', 'consumer')
        },
        groups=groups_data,
        statistics={
            "total_groups": len(groups_data)
        },
        generated_at=datetime.utcnow().isoformat() + "Z"
    )
