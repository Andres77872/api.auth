"""
User Management Routes

Handles user profile management, updates, and access information
for the group-based multi-project authentication system.
"""

import logging
from fastapi import APIRouter, HTTPException, Depends, Form
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from src.Util.db import (
    validate_session, get_user_by_hash, update_user,
    get_user_accessible_projects, get_user_groups_for_user,
    list_users, count_users, get_user_permissions_in_project,
    get_user_by_id, is_root_user, is_admin_user
)
from src.Util.Models import (
    UserProfileResponse, UpdateProfileResponse, AccessSummaryResponse,
    ListUsersResponse, GetUserDetailsResponse, UpdateUserStatusResponse,
    UserInfo, ProjectInfo, UserUpdateRequest, PaginationInfo
)
from src.Util.Seccurity import HTTPBearerOrCookie

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/users", tags=["User Management"])
security = HTTPBearerOrCookie()


@router.get("/profile", response_model=UserProfileResponse)
async def get_user_profile(credentials: HTTPAuthorizationCredentials = Depends(security)) -> UserProfileResponse:
    """
    Get current user's profile information including groups and project access.
    
    Returns:
        User profile with group memberships and accessible projects
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        # Get user's complete profile with groups
        user_data = get_user_by_hash(session_data.user_hash)
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get user's accessible projects
        user_projects = get_user_accessible_projects(user_data.id)
        
        # Build user info
        user_info = UserInfo(
            user_hash=user_data.user_hash,
            username=user_data.username,
            email=user_data.email,
            user_type=getattr(user_data, 'user_type', 'consumer'),
            created_at=user_data.created_at
        )
        
        # Build accessible projects list
        accessible_projects = []
        if user_projects:
            for proj in user_projects:
                accessible_projects.append(ProjectInfo(
                    project_hash=getattr(proj, 'project_hash', ''),
                    project_name=getattr(proj, 'project_name', ''),
                    project_description=getattr(proj, 'project_description', None)
                ))
        
        # Build current project info
        current_project = ProjectInfo(
            project_hash=session_data.project_hash,
            project_name=session_data.project_name
        )
        
        return UserProfileResponse(
            success=True,
            user=user_info,
            accessible_projects=accessible_projects,
            current_project=current_project
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Profile retrieval error: {str(e)}")
        raise HTTPException(status_code=500, detail="Profile retrieval error")


@router.put("/profile", response_model=UpdateProfileResponse)
async def update_user_profile(
    username: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    password: Optional[str] = Form(None),
    credentials: HTTPAuthorizationCredentials = Depends(security)
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
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        # Get current user
        current_user = get_user_by_hash(session_data.user_hash)
        if not current_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        update_username = username
        update_email = email
        update_password = password
        
        # Update user
        updated_user = update_user(
            current_user.id,
            username=update_username,
            email=update_email,
            password=update_password
        )
        
        if not updated_user:
            raise HTTPException(status_code=400, detail="Update failed")
        
        # Build updated user info
        user_info = UserInfo(
            user_hash=updated_user.user_hash,
            username=updated_user.username,
            email=updated_user.email,
            user_type=getattr(updated_user, 'user_type', 'consumer')
        )
        
        return UpdateProfileResponse(
            success=True,
            message="Profile updated successfully",
            user=user_info
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Profile update error: {str(e)}")
        raise HTTPException(status_code=500, detail="Profile update error")


@router.get("/access-summary", response_model=AccessSummaryResponse)
async def get_user_access_summary(credentials: HTTPAuthorizationCredentials = Depends(security)) -> AccessSummaryResponse:
    """
    Get summary of user's group memberships and project access.
    
    Returns:
        Comprehensive access summary with groups and permissions
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        user_data = get_user_by_hash(session_data.user_hash)
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get user's group memberships
        user_groups = get_user_groups_for_user(user_data.id)
        
        # Get comprehensive access information
        accessible_projects = get_user_accessible_projects(user_data.id)
        
        # Build user groups list
        group_list = []
        for group in user_groups:
            group_list.append({
                "group_name": group.group_name,
                "description": group.description if hasattr(group, 'description') else group.group_description
            })
        
        # Build accessible projects list
        project_list = []
        if accessible_projects:
            for proj in accessible_projects:
                project_list.append({
                    "project_hash": getattr(proj, 'project_hash', ''),
                    "project_name": getattr(proj, 'project_name', ''),
                    "project_description": getattr(proj, 'project_description', None)
                })
        
        # Build access summary
        access_summary = {
            "user": {
                "user_hash": user_data.user_hash,
                "username": user_data.username,
                "email": user_data.email
            },
            "user_groups": group_list,
            "accessible_projects": project_list,
            "current_session": {
                "project_hash": session_data.project_hash,
                "project_name": session_data.project_name,
                "permissions": getattr(session_data, 'permissions', []),
                "expires_at": getattr(session_data, 'expires_at', None)
            },
            "summary": {
                "total_groups": len(user_groups),
                "total_projects": len(accessible_projects) if accessible_projects else 0,
                "is_admin": "admin" in getattr(session_data, 'permissions', [])
            }
        }
        
        return AccessSummaryResponse(
            success=True,
            access_summary=access_summary
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Access summary error: {str(e)}")
        raise HTTPException(status_code=500, detail="Access summary error")


@router.get("", response_model=ListUsersResponse)
async def list_all_users(
    limit: int = 50,
    offset: int = 0,
    user_type: Optional[str] = None,
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> ListUsersResponse:
    """
    List all users with filtering options.
    
    **Admin access required**: Only root and admin users can list users.
    
    Args:
        limit: Number of users to return (max 100)
        offset: Number of users to skip
        user_type: Filter by user type (root, admin, consumer)
        search: Search term for username or email
        is_active: Filter by active status
        
    Returns:
        List of users with pagination
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        # Check admin permissions
        current_user = get_user_by_hash(session_data.user_hash)
        if not current_user:
            raise HTTPException(status_code=404, detail="Current user not found")
        
        user_permissions = getattr(session_data, 'permissions', [])
        if 'admin' not in user_permissions and 'manage_users' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required to list users")
        
        # Limit constraints
        if limit > 100:
            limit = 100
        
        # Get users with filtering
        if search:
            from src.Util.db import search_users
            users = search_users(search, user_type, limit)
        else:
            users = list_users(limit=limit, offset=offset, user_type=user_type)
        
        # Apply is_active filter if specified
        if is_active is not None:
            users = [u for u in users if u.is_active == is_active]
        
        total_count = count_users(user_type=user_type)
        
        # Build response data
        user_list = []
        for user in users:
            user_info = {
                "user_hash": user.user_hash,
                "username": user.username,
                "email": user.email,
                "user_type": user.user_type,
                "is_active": user.is_active,
                "created_at": user.created_at,
                "updated_at": user.updated_at
            }
            
            # Add project info for admin users
            if user.user_type == 'admin' and user.assigned_project_id:
                from src.Util.db import get_project_by_id
                project = get_project_by_id(user.assigned_project_id)
                if project:
                    user_info["assigned_project"] = {
                        "project_id": project.id,
                        "project_hash": project.project_hash,
                        "project_name": project.project_name
                    }
            
            user_list.append(user_info)
        
        pagination = PaginationInfo(
            limit=limit,
            offset=offset,
            total=total_count,
            has_more=offset + limit < total_count
        )
        
        filters_info = {
            "user_type": user_type,
            "search": search,
            "is_active": is_active
        }
        
        return ListUsersResponse(
            success=True,
            users=user_list,
            pagination=pagination,
            filters=filters_info
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"List users error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list users")


@router.get("/{user_hash}", response_model=GetUserDetailsResponse)
async def get_user_details(
    user_hash: str,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> GetUserDetailsResponse:
    """
    Get detailed information about a specific user.
    
    **Admin access or own profile**: Admin users can view any user, regular users can only view their own profile.
    
    Args:
        user_hash: Hash of the user to get details for
        
    Returns:
        Detailed user information including permissions and groups
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        # Get target user
        target_user = get_user_by_hash(user_hash)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get current user
        current_user = get_user_by_hash(session_data.user_hash)
        user_permissions = getattr(session_data, 'permissions', [])
        
        # Access control: Admin users can view anyone, regular users only themselves
        if current_user.id != target_user.id:
            if 'admin' not in user_permissions and 'manage_users' not in user_permissions:
                raise HTTPException(status_code=403, detail="Permission denied")
        
        # Get user's groups and permissions
        user_groups = get_user_groups_for_user(target_user.id)
        accessible_projects = get_user_accessible_projects(target_user.id)
        
        # Get permissions in current project if available
        permissions = []
        if hasattr(session_data, 'project_id') and session_data.project_id:
            permissions = get_user_permissions_in_project(target_user.id, session_data.project_id)
        
        # Build user details
        user_details = {
            "user_hash": target_user.user_hash,
            "username": target_user.username,
            "email": target_user.email,
            "user_type": target_user.user_type,
            "is_active": target_user.is_active,
            "created_at": target_user.created_at,
            "updated_at": target_user.updated_at
        }
        
        # Add admin-specific info
        if target_user.user_type == 'admin':
            from src.Util.db import get_admin_project_assignments_with_details
            assignments = get_admin_project_assignments_with_details(target_user.id)
            user_details["project_assignments"] = assignments
            user_details["total_assigned_projects"] = len(assignments)
        
        # Build groups list
        groups_list = [group.group_name for group in user_groups]
        
        # Build accessible projects list
        projects_list = []
        if accessible_projects:
            for proj in accessible_projects:
                projects_list.append(ProjectInfo(
                    project_hash=getattr(proj, 'project_hash', ''),
                    project_name=getattr(proj, 'project_name', ''),
                    project_description=getattr(proj, 'project_description', None)
                ))
        
        # Build statistics
        statistics = {
            "total_groups": len(user_groups),
            "total_accessible_projects": len(accessible_projects) if accessible_projects else 0,
            "total_permissions": len(permissions),
            "account_age_days": (datetime.utcnow() - target_user.created_at).days if target_user.created_at else 0
        }
        
        return GetUserDetailsResponse(
            success=True,
            user=user_details,
            permissions=permissions,
            groups=groups_list,
            accessible_projects=projects_list,
            statistics=statistics
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get user details error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get user details")


@router.patch("/{user_hash}/status", response_model=UpdateUserStatusResponse)
async def update_user_status(
    user_hash: str,
    is_active: bool = Form(...),
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> UpdateUserStatusResponse:
    """
    Update user's active status (activate/deactivate).
    
    **Admin access required**: Only admin users can change user status.
    
    Args:
        user_hash: Hash of the user to update
        is_active: Whether the user should be active
        
    Returns:
        Updated user status information
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        # Check admin permissions
        current_user = get_user_by_hash(session_data.user_hash)
        user_permissions = getattr(session_data, 'permissions', [])
        
        if 'admin' not in user_permissions and 'manage_users' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required to update user status")
        
        # Get target user
        target_user = get_user_by_hash(user_hash)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Prevent deactivating root users
        if target_user.user_type == 'root' and not is_active:
            raise HTTPException(status_code=400, detail="Cannot deactivate root users")
        
        # Prevent users from deactivating themselves
        if current_user.id == target_user.id:
            raise HTTPException(status_code=400, detail="Cannot change your own status")
        
        # Update user status using the update_user function with a custom is_active field
        # Note: We need to implement this in the database layer if not already present
        try:
            # First, let's try to update using the existing update_user function
            from src.Util.db_config import get_connection
            
            with get_connection() as con:
                cur = con.cursor()
                cur.execute("""
                    UPDATE users 
                    SET is_active = %s, updated_at = NOW()
                    WHERE user_hash = %s
                """, [is_active, user_hash])
                
                if cur.rowcount == 0:
                    raise HTTPException(status_code=404, detail="User not found or update failed")
                
                con.commit()
            
            # Get updated user
            updated_user = get_user_by_hash(user_hash)
            
            # Build user info
            user_info = UserInfo(
                user_hash=updated_user.user_hash,
                username=updated_user.username,
                email=updated_user.email,
                user_type=updated_user.user_type,
                created_at=updated_user.created_at
            )
            
            status_change = {
                "previous_status": target_user.is_active,
                "new_status": is_active,
                "changed_by": current_user.username,
                "changed_at": datetime.utcnow().isoformat(),
                "action": "activated" if is_active else "deactivated"
            }
            
            logger.info(f"User status updated: {target_user.username} -> {'activated' if is_active else 'deactivated'} by {current_user.username}")
            
            return UpdateUserStatusResponse(
                success=True,
                message=f"User '{target_user.username}' has been {'activated' if is_active else 'deactivated'}",
                user=user_info,
                status_change=status_change
            )
            
        except Exception as db_error:
            logger.error(f"Database error updating user status: {str(db_error)}")
            raise HTTPException(status_code=500, detail="Failed to update user status")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update user status error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update user status") 