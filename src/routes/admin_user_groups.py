"""
Admin User Group Management Routes

Handles global user group administration including creation, management,
and access control for the group-based multi-project authentication system.
"""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, Query, Path, Form
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from src.Util.Models import (
    ListUserGroupsResponse, CreateUserGroupResponse, UserGroupDetailsResponse,
    UpdateUserGroupResponse, DeleteUserGroupResponse, AssignUserToGroupResponse,
    RemoveUserFromGroupResponse, GrantGroupProjectAccessResponse, RevokeGroupProjectAccessResponse,
    UserInfo, UserGroupInfo, ProjectInfo, PaginationInfo, GroupMembersPaginatedResponse,
    BulkAddUsersToGroupResponse, UserGroupsForUserResponse
)
from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.activity_logger import ActivityLogger, ActivityType
from src.Util.db import (
    validate_session, get_user_by_hash,
    create_user_group, get_user_group_by_hash,
    list_all_user_groups, update_user_group,
    delete_user_group, assign_user_to_user_group,
    remove_user_from_user_group, get_users_in_group,
    grant_group_project_access, revoke_group_project_access,
    get_projects_for_user_group, get_project_by_hash, get_user_groups_for_user,
    get_total_user_groups_count
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
    
    Args:
        group_hash: User group identifier
        
    Returns:
        User group details with members and project access
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

    # Get accessible projects
    accessible_projects = get_projects_for_user_group(user_group.id)

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

    project_list = [
        ProjectInfo(
            project_hash=project[1],
            project_name=project[2]
        ) for project in accessible_projects
    ]

    statistics_info = {
        "total_members": len(members),
        "total_projects": len(accessible_projects)
    }

    return UserGroupDetailsResponse(
        success=True,
        user_group=group_info,
        members=member_list,
        accessible_projects=project_list,
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

@router.post("/{group_hash}/projects", response_model=GrantGroupProjectAccessResponse)
async def grant_group_project_access_endpoint(
        group_hash: str = Path(...),
        project_hash: str = Form(...),
        session_data=Depends(require_admin)
) -> GrantGroupProjectAccessResponse:
    """
    Grant a user group access to a project (admin only).
    
    Args:
        group_hash: User group identifier
        project_hash: Project hash
        
    Returns:
        Access grant confirmation
    """
    target_project_hash = project_hash

    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )

    # Get target project
    target_project = get_project_by_hash(target_project_hash)
    if not target_project:
        raise NotFoundError(
            message="Target project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": target_project_hash}
        )

    # Get current user for audit trail
    current_user = get_user_by_hash(session_data.user_hash)

    # Grant access
    access_result = grant_group_project_access(
        user_group.id,
        target_project.id,
        granted_by=current_user.id
    )

    if not access_result:
        raise InternalError(
            message="Access grant failed",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "grant_group_project_access"}
        )

    access_details = {
        "user_group": {
            "group_hash": user_group.group_hash,
            "group_name": user_group.group_name
        },
        "project": {
            "project_hash": target_project.project_hash,
            "project_name": target_project.project_name
        },
        "granted_by": current_user.username
    }

    return GrantGroupProjectAccessResponse(
        success=True,
        message=f"User group \"{user_group.group_name}\" granted access to project \"{target_project.project_name}\"",
        access_details=access_details
    )

@router.delete("/{group_hash}/projects/{project_hash}", response_model=RevokeGroupProjectAccessResponse)
async def revoke_group_project_access_endpoint(
        group_hash: str = Path(...),
        project_hash: str = Path(...),
        session_data=Depends(require_admin)
) -> RevokeGroupProjectAccessResponse:
    """
    Revoke a user group's access to a project (admin only).
    
    Args:
        group_hash: User group identifier
        project_hash: Project identifier
        
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

    # Get project
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )

    # Get current user for audit trail
    current_user = get_user_by_hash(session_data.user_hash)

    # Revoke access
    if revoke_group_project_access(user_group.id, project.id, revoked_by=current_user.id):
        return RevokeGroupProjectAccessResponse(
            success=True,
            message=f"User group \"{user_group.group_name}\" access to project \"{project.project_name}\" revoked"
        )
    else:
        raise InternalError(
            message="Revocation failed",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "revoke_group_project_access"}
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
        member_info = {
            "user_hash": member.user_hash,
            "username": member.username,
            "email": member.email,
            "user_type": getattr(member, 'user_type', 'consumer'),
            "is_active": getattr(member, 'is_active', True),
            "joined_group_at": getattr(member, 'created_at', None)
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
        generated_at=datetime.utcnow().isoformat()
    )

@router.post("/{group_hash}/members/bulk", response_model=BulkAddUsersToGroupResponse)
async def bulk_add_users_to_group(
        group_hash: str = Path(...),
        user_hashes: List[str] = Form(...),
        session_data=Depends(require_admin)
) -> BulkAddUsersToGroupResponse:
    """
    Bulk add users to group.
    
    **Phase 2 Implementation**: Bulk add users to group
    
    Args:
        group_hash: User group identifier
        user_hashes: List of user hashes to add to group
        
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

    # Validate input
    if not user_hashes:
        raise ValidationError(
            message="At least one user hash is required",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"field": "user_hashes"}
        )

    if len(user_hashes) > 100:
        raise ValidationError(
            message="Maximum 100 users can be assigned at once",
            error_code=ErrorCode.INVALID_LENGTH,
            details={"max_length": 100, "provided_length": len(user_hashes)}
        )

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
        performed_at=datetime.utcnow().isoformat()
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
        group_info = {
            "group_hash": group.group_hash,
            "group_name": group.group_name,
            "description": group.group_description,
            "joined_at": getattr(group, 'created_at', None)
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
        generated_at=datetime.utcnow().isoformat()
    )
