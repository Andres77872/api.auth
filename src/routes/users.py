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

from src.Util.db import (
    validate_session, get_user_by_hash, update_user,
    get_user_accessible_projects, get_user_groups_for_user
)
from src.Util.Models import (
    UserProfileResponse, UpdateProfileResponse, AccessSummaryResponse,
    UserInfo, ProjectInfo, UserUpdateRequest
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