"""
Admin User Group Management Routes

Handles global user group administration including creation, management,
and access control for the group-based multi-project authentication system.
"""

import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query, Path, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from src.Util.db import (
    validate_session, get_user_by_hash,
    create_user_group, get_user_group_by_id, get_user_group_by_hash,
    get_user_group_by_name, list_all_user_groups, update_user_group,
    delete_user_group, count_user_groups, assign_user_to_user_group,
    remove_user_from_user_group, get_users_in_group,
    grant_group_project_access, revoke_group_project_access,
    get_projects_for_user_group, get_project_by_hash
)
from src.Util.Models import (
    ListUserGroupsResponse, CreateUserGroupResponse, UserGroupDetailsResponse,
    UpdateUserGroupResponse, DeleteUserGroupResponse, AssignUserToGroupResponse,
    RemoveUserFromGroupResponse, GrantGroupProjectAccessResponse, RevokeGroupProjectAccessResponse,
    UserInfo, UserGroupInfo, ProjectInfo, PaginationInfo
)

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/admin/user-groups", tags=["Admin - User Groups"])
security = HTTPBearer()

# Pydantic models
class UserGroupCreate(BaseModel):
    group_name: str
    description: str = None

class UserGroupUpdate(BaseModel):
    group_name: str = None
    description: str = None

class GroupAssignment(BaseModel):
    user_hash: str
    group_hash: str = None

class ProjectAccess(BaseModel):
    user_group_hash: str = None
    project_hash: str


# Helper function to check admin permissions
async def require_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Ensure user has admin permissions"""
    session_data = validate_session(credentials.credentials)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    user_permissions = session_data.permissions if hasattr(session_data, 'permissions') else []
    if 'admin' not in user_permissions and 'manage_users' not in user_permissions:
        raise HTTPException(status_code=403, detail="Admin or manage_users permission required")
    
    return session_data


@router.get("", response_model=ListUserGroupsResponse)
async def list_user_groups(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session_data = Depends(require_admin)
) -> ListUserGroupsResponse:
    """
    List all global user groups (admin only).
    
    Returns:
        List of user groups with member counts
    """
    try:
        # Get all user groups
        user_groups = list_all_user_groups(limit, offset)
        
        # Add member counts
        groups_with_counts = []
        for group in user_groups:
            members = get_users_in_group(group.id)
            group_info = UserGroupInfo(
                group_hash=group.group_hash,
                group_name=group.group_name,
                description=group.description,
                member_count=len(members),
                created_at=group.created_at
            )
            groups_with_counts.append(group_info)
        
        pagination = PaginationInfo(
            limit=limit,
            offset=offset,
            total=len(groups_with_counts)
        )
        
        return ListUserGroupsResponse(
            success=True,
            user_groups=groups_with_counts,
            pagination=pagination
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User groups listing error: {str(e)}")
        raise HTTPException(status_code=500, detail="User groups listing error")


@router.post("", response_model=CreateUserGroupResponse)
async def create_user_group_endpoint(
    group_data: UserGroupCreate = None,
    group_name: str = Form(None),
    description: Optional[str] = Form(None),
    session_data = Depends(require_admin)
) -> CreateUserGroupResponse:
    """
    Create a new global user group (admin only).
    
    Accepts both JSON and form data:
    - JSON: Send UserGroupCreate object directly
    - Form: Send individual fields as form data
    
    Args:
        group_data: User group creation data (JSON)
        group_name: Group name (form)
        description: Group description (form)
        
    Returns:
        Created user group information
    """
    try:
        # Get current user for audit trail
        user_data = get_user_by_hash(session_data.user_hash)
        
        # Use JSON data if available, otherwise use form data
        if group_data:
            create_name = group_data.group_name
            create_description = group_data.description
        else:
            create_name = group_name
            create_description = description
        
        if not create_name:
            raise HTTPException(status_code=400, detail="Group name is required")
        
        # Create user group
        new_group = create_user_group(
            create_name,
            create_description,
            created_by=user_data.id
        )
        
        if not new_group:
            raise HTTPException(status_code=400, detail="User group creation failed")
        
        group_info = UserGroupInfo(
            group_hash=new_group.group_hash,
            group_name=new_group.group_name,
            description=new_group.description,
            created_at=new_group.created_at
        )
        
        return CreateUserGroupResponse(
            success=True,
            message=f"User group \"{create_name}\" created successfully",
            user_group=group_info
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User group creation error: {str(e)}")
        raise HTTPException(status_code=500, detail="User group creation error")


@router.get("/{group_hash}", response_model=UserGroupDetailsResponse)
async def get_user_group_details(
    group_hash: str = Path(...),
    session_data = Depends(require_admin)
) -> UserGroupDetailsResponse:
    """
    Get detailed user group information (admin only).
    
    Args:
        group_hash: User group identifier
        
    Returns:
        User group details with members and project access
    """
    try:
        # Get user group
        user_group = get_user_group_by_hash(group_hash)
        if not user_group:
            raise HTTPException(status_code=404, detail="User group not found")
        
        # Get members
        members = get_users_in_group(user_group.id)
        
        # Get accessible projects
        accessible_projects = get_projects_for_user_group(user_group.id)
        
        group_info = UserGroupInfo(
            group_hash=user_group.group_hash,
            group_name=user_group.group_name,
            description=user_group.description,
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
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User group details error: {str(e)}")
        raise HTTPException(status_code=500, detail="User group details error")


@router.put("/{group_hash}", response_model=UpdateUserGroupResponse)
async def update_user_group_endpoint(
    group_hash: str = Path(...),
    group_data: UserGroupUpdate = None,
    group_name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    session_data = Depends(require_admin)
) -> UpdateUserGroupResponse:
    """
    Update user group information (admin only).
    
    Accepts both JSON and form data:
    - JSON: Send UserGroupUpdate object directly
    - Form: Send individual fields as form data
    
    Args:
        group_hash: User group identifier
        group_data: Update data (JSON)
        group_name: Group name (form)
        description: Group description (form)
        
    Returns:
        Updated user group information
    """
    try:
        # Get user group
        user_group = get_user_group_by_hash(group_hash)
        if not user_group:
            raise HTTPException(status_code=404, detail="User group not found")
        
        # Use JSON data if available, otherwise use form data
        if group_data:
            update_name = group_data.group_name
            update_description = group_data.description
        else:
            update_name = group_name
            update_description = description
        
        # Update group
        updated_group = update_user_group(
            user_group.id,
            group_name=update_name,
            group_description=update_description
        )
        
        if not updated_group:
            raise HTTPException(status_code=400, detail="Update failed")
        
        group_info = UserGroupInfo(
            group_hash=updated_group.group_hash,
            group_name=updated_group.group_name,
            description=updated_group.description
        )
        
        return UpdateUserGroupResponse(
            success=True,
            message="User group updated successfully",
            user_group=group_info
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User group update error: {str(e)}")
        raise HTTPException(status_code=500, detail="User group update error")


@router.delete("/{group_hash}", response_model=DeleteUserGroupResponse)
async def delete_user_group_endpoint(
    group_hash: str = Path(...),
    session_data = Depends(require_admin)
) -> DeleteUserGroupResponse:
    """
    Delete a user group (admin only).
    
    Args:
        group_hash: User group identifier
        
    Returns:
        Deletion confirmation
    """
    try:
        # Get user group
        user_group = get_user_group_by_hash(group_hash)
        if not user_group:
            raise HTTPException(status_code=404, detail="User group not found")
        
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
            raise HTTPException(status_code=400, detail="Delete failed")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User group deletion error: {str(e)}")
        raise HTTPException(status_code=500, detail="User group deletion error")


@router.post("/{group_hash}/members", response_model=AssignUserToGroupResponse)
async def assign_user_to_group_endpoint(
    group_hash: str = Path(...),
    assignment: GroupAssignment = None,
    user_hash: str = Form(None),
    session_data = Depends(require_admin)
) -> AssignUserToGroupResponse:
    """
    Assign a user to a user group (admin only).
    
    Accepts both JSON and form data:
    - JSON: Send GroupAssignment object directly
    - Form: Send user_hash as form data
    
    Args:
        group_hash: User group identifier
        assignment: Group assignment data (JSON)
        user_hash: User hash (form)
        
    Returns:
        Assignment confirmation
    """
    try:
        # Get target user hash
        if assignment:
            target_user_hash = assignment.user_hash
        else:
            target_user_hash = user_hash
            
        if not target_user_hash:
            raise HTTPException(status_code=400, detail="User hash required")
        
        # Get user group
        user_group = get_user_group_by_hash(group_hash)
        if not user_group:
            raise HTTPException(status_code=404, detail="User group not found")
        
        # Get target user
        target_user = get_user_by_hash(target_user_hash)
        if not target_user:
            raise HTTPException(status_code=404, detail="Target user not found")
        
        # Get current user for audit trail
        current_user = get_user_by_hash(session_data.user_hash)
        
        # Assign user to group
        assignment_result = assign_user_to_user_group(
            target_user.id,
            user_group.id,
            assigned_by=current_user.id
        )
        
        if not assignment_result:
            raise HTTPException(status_code=400, detail="Assignment failed")
        
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
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User group assignment error: {str(e)}")
        raise HTTPException(status_code=500, detail="User group assignment error")


@router.delete("/{group_hash}/members/{user_hash}", response_model=RemoveUserFromGroupResponse)
async def remove_user_from_group_endpoint(
    group_hash: str = Path(...),
    user_hash: str = Path(...),
    session_data = Depends(require_admin)
) -> RemoveUserFromGroupResponse:
    """
    Remove a user from a user group (admin only).
    
    Args:
        group_hash: User group identifier
        user_hash: User identifier
        
    Returns:
        Removal confirmation
    """
    try:
        # Get user group
        user_group = get_user_group_by_hash(group_hash)
        if not user_group:
            raise HTTPException(status_code=404, detail="User group not found")
        
        # Get target user
        target_user = get_user_by_hash(user_hash)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get current user for audit trail
        current_user = get_user_by_hash(session_data.user_hash)
        
        # Remove user from group
        if remove_user_from_user_group(target_user.id, user_group.id, removed_by=current_user.id):
            return RemoveUserFromGroupResponse(
                success=True,
                message=f"User \"{target_user.username}\" removed from group \"{user_group.group_name}\""
            )
        else:
            raise HTTPException(status_code=400, detail="Removal failed")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User group removal error: {str(e)}")
        raise HTTPException(status_code=500, detail="User group removal error")


@router.post("/{group_hash}/projects", response_model=GrantGroupProjectAccessResponse)
async def grant_group_project_access_endpoint(
    group_hash: str = Path(...),
    project_access: ProjectAccess = None,
    project_hash: str = Form(None),
    session_data = Depends(require_admin)
) -> GrantGroupProjectAccessResponse:
    """
    Grant a user group access to a project (admin only).
    
    Accepts both JSON and form data:
    - JSON: Send ProjectAccess object directly
    - Form: Send project_hash as form data
    
    Args:
        group_hash: User group identifier
        project_access: Project access data (JSON)
        project_hash: Project hash (form)
        
    Returns:
        Access grant confirmation
    """
    try:
        # Get target project hash
        if project_access:
            target_project_hash = project_access.project_hash
        else:
            target_project_hash = project_hash
            
        if not target_project_hash:
            raise HTTPException(status_code=400, detail="Project hash required")
        
        # Get user group
        user_group = get_user_group_by_hash(group_hash)
        if not user_group:
            raise HTTPException(status_code=404, detail="User group not found")
        
        # Get target project
        target_project = get_project_by_hash(target_project_hash)
        if not target_project:
            raise HTTPException(status_code=404, detail="Target project not found")
        
        # Get current user for audit trail
        current_user = get_user_by_hash(session_data.user_hash)
        
        # Grant access
        access_result = grant_group_project_access(
            user_group.id,
            target_project.id,
            granted_by=current_user.id
        )
        
        if not access_result:
            raise HTTPException(status_code=400, detail="Access grant failed")
        
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
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Group project access error: {str(e)}")
        raise HTTPException(status_code=500, detail="Group project access error")


@router.delete("/{group_hash}/projects/{project_hash}", response_model=RevokeGroupProjectAccessResponse)
async def revoke_group_project_access_endpoint(
    group_hash: str = Path(...),
    project_hash: str = Path(...),
    session_data = Depends(require_admin)
) -> RevokeGroupProjectAccessResponse:
    """
    Revoke a user group's access to a project (admin only).
    
    Args:
        group_hash: User group identifier
        project_hash: Project identifier
        
    Returns:
        Revocation confirmation
    """
    try:
        # Get user group
        user_group = get_user_group_by_hash(group_hash)
        if not user_group:
            raise HTTPException(status_code=404, detail="User group not found")
        
        # Get project
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Get current user for audit trail
        current_user = get_user_by_hash(session_data.user_hash)
        
        # Revoke access
        if revoke_group_project_access(user_group.id, project.id, revoked_by=current_user.id):
            return RevokeGroupProjectAccessResponse(
                success=True,
                message=f"User group \"{user_group.group_name}\" access to project \"{project.project_name}\" revoked"
            )
        else:
            raise HTTPException(status_code=400, detail="Revocation failed")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Group project access revocation error: {str(e)}")
        raise HTTPException(status_code=500, detail="Group project access revocation error") 