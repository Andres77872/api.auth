"""
Admin User Group Management Routes

Handles global user group administration including creation, management,
and access control for the group-based multi-project authentication system.
"""

import logging
from typing import List
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


@router.get("")
async def list_user_groups(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session_data = Depends(require_admin)
):
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
            groups_with_counts.append({
                "group_hash": group.group_hash,
                "group_name": group.group_name,
                "description": group.description,
                "member_count": len(members),
                "created_at": group.created_at,
                "is_active": group.is_active
            })
        
        return {
            "success": True,
            "user_groups": groups_with_counts,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total": len(groups_with_counts)
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User groups listing error: {str(e)}")
        raise HTTPException(status_code=500, detail="User groups listing error")


@router.post("")
async def create_user_group_endpoint(
    group_data: UserGroupCreate,
    session_data = Depends(require_admin)
):
    """
    Create a new global user group (admin only).
    
    Args:
        group_data: User group creation data
        
    Returns:
        Created user group information
    """
    try:
        # Get current user for audit trail
        user_data = get_user_by_hash(session_data.user_hash)
        
        # Create user group
        new_group = create_user_group(
            group_data.group_name,
            group_data.description,
            created_by=user_data.id
        )
        
        if not new_group:
            raise HTTPException(status_code=400, detail="User group creation failed")
        
        return {
            "success": True,
            "message": f"User group \"{group_data.group_name}\" created successfully",
            "user_group": {
                "group_hash": new_group.group_hash,
                "group_name": new_group.group_name,
                "description": new_group.description,
                "created_at": new_group.created_at
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User group creation error: {str(e)}")
        raise HTTPException(status_code=500, detail="User group creation error")


@router.get("/{group_hash}")
async def get_user_group_details(
    group_hash: str = Path(...),
    session_data = Depends(require_admin)
):
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
        
        return {
            "success": True,
            "user_group": {
                "group_hash": user_group.group_hash,
                "group_name": user_group.group_name,
                "description": user_group.description,
                "created_at": user_group.created_at,
                "is_active": user_group.is_active
            },
            "members": [
                {
                    "user_hash": member.user_hash,
                    "username": member.username,
                    "email": member.email
                } for member in members
            ],
            "accessible_projects": [
                {
                    "project_id": project[0],
                    "project_hash": project[1],
                    "project_name": project[2]
                } for project in accessible_projects
            ],
            "statistics": {
                "total_members": len(members),
                "total_projects": len(accessible_projects)
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User group details error: {str(e)}")
        raise HTTPException(status_code=500, detail="User group details error")


@router.put("/{group_hash}")
async def update_user_group_endpoint(
    group_hash: str = Path(...),
    group_data: UserGroupUpdate = None,
    session_data = Depends(require_admin)
):
    """
    Update user group information (admin only).
    
    Args:
        group_hash: User group identifier
        group_data: Update data
        
    Returns:
        Updated user group information
    """
    try:
        # Get user group
        user_group = get_user_group_by_hash(group_hash)
        if not user_group:
            raise HTTPException(status_code=404, detail="User group not found")
        
        # Update group
        updated_group = update_user_group(
            user_group.id,
            group_name=group_data.group_name if group_data else None,
            group_description=group_data.description if group_data else None
        )
        
        if not updated_group:
            raise HTTPException(status_code=400, detail="Update failed")
        
        return {
            "success": True,
            "message": "User group updated successfully",
            "user_group": {
                "group_hash": updated_group.group_hash,
                "group_name": updated_group.group_name,
                "description": updated_group.description
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User group update error: {str(e)}")
        raise HTTPException(status_code=500, detail="User group update error")


@router.delete("/{group_hash}")
async def delete_user_group_endpoint(
    group_hash: str = Path(...),
    session_data = Depends(require_admin)
):
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
            return {
                "success": True,
                "message": f"User group \"{user_group.group_name}\" deleted successfully",
                "warning": "All user memberships and project access have been revoked"
            }
        else:
            raise HTTPException(status_code=400, detail="Delete failed")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User group deletion error: {str(e)}")
        raise HTTPException(status_code=500, detail="User group deletion error")


@router.post("/{group_hash}/members")
async def assign_user_to_group_endpoint(
    group_hash: str = Path(...),
    assignment: GroupAssignment = None,
    user_hash: str = Form(None),
    session_data = Depends(require_admin)
):
    """
    Assign a user to a user group (admin only).
    
    Args:
        group_hash: User group identifier
        assignment: Group assignment data (JSON) or
        user_hash: User hash (form data)
        
    Returns:
        Assignment confirmation
    """
    try:
        # Get target user hash
        target_user_hash = assignment.user_hash if assignment else user_hash
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
        
        return {
            "success": True,
            "message": f"User \"{target_user.username}\" assigned to group \"{user_group.group_name}\"",
            "assignment": {
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
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User group assignment error: {str(e)}")
        raise HTTPException(status_code=500, detail="User group assignment error")


@router.delete("/{group_hash}/members/{user_hash}")
async def remove_user_from_group_endpoint(
    group_hash: str = Path(...),
    user_hash: str = Path(...),
    session_data = Depends(require_admin)
):
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
            return {
                "success": True,
                "message": f"User \"{target_user.username}\" removed from group \"{user_group.group_name}\""
            }
        else:
            raise HTTPException(status_code=400, detail="Removal failed")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User group removal error: {str(e)}")
        raise HTTPException(status_code=500, detail="User group removal error")


@router.post("/{group_hash}/projects")
async def grant_group_project_access_endpoint(
    group_hash: str = Path(...),
    project_access: ProjectAccess = None,
    project_hash: str = Form(None),
    session_data = Depends(require_admin)
):
    """
    Grant a user group access to a project (admin only).
    
    Args:
        group_hash: User group identifier
        project_access: Project access data (JSON) or
        project_hash: Project hash (form data)
        
    Returns:
        Access grant confirmation
    """
    try:
        # Get target project hash
        target_project_hash = project_access.project_hash if project_access else project_hash
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
        
        return {
            "success": True,
            "message": f"User group \"{user_group.group_name}\" granted access to project \"{target_project.project_name}\"",
            "access_details": {
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
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Group project access error: {str(e)}")
        raise HTTPException(status_code=500, detail="Group project access error")


@router.delete("/{group_hash}/projects/{project_hash}")
async def revoke_group_project_access_endpoint(
    group_hash: str = Path(...),
    project_hash: str = Path(...),
    session_data = Depends(require_admin)
):
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
            return {
                "success": True,
                "message": f"User group \"{user_group.group_name}\" access to project \"{project.project_name}\" revoked"
            }
        else:
            raise HTTPException(status_code=400, detail="Revocation failed")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Group project access revocation error: {str(e)}")
        raise HTTPException(status_code=500, detail="Group project access revocation error") 