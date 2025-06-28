"""
User Management Routes

Handles user profile management, updates, and access information
for the group-based multi-project authentication system.
"""

import logging
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from src.Util.db import (
    validate_session, get_user_by_hash, update_user,
    get_user_accessible_projects, get_user_groups_for_user
)

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/users", tags=["User Management"])
security = HTTPBearer()

# Pydantic models
class UserUpdate(BaseModel):
    username: str = None
    email: str = None
    password: str = None


@router.get("/profile")
async def get_user_profile(credentials: HTTPAuthorizationCredentials = Depends(security)):
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
        
        return {
            "success": True,
            "user": {
                "user_hash": user_data.user_hash,
                "username": user_data.username,
                "email": user_data.email,
                "created_at": user_data.created_at,
                "user_groups": session_data.user_groups if hasattr(session_data, 'user_groups') else []
            },
            "accessible_projects": user_projects or [],
            "current_project": {
                "project_hash": session_data.project_hash,
                "project_name": session_data.project_name,
                "permissions": session_data.permissions if hasattr(session_data, 'permissions') else []
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Profile retrieval error: {str(e)}")
        raise HTTPException(status_code=500, detail="Profile retrieval error")


@router.put("/profile")
async def update_user_profile(
    user_data: UserUpdate,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Update current user's profile information.
    
    Args:
        user_data: User update data
        
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
        
        # Update user
        updated_user = update_user(
            current_user.id,
            username=user_data.username,
            email=user_data.email,
            password=user_data.password
        )
        
        if not updated_user:
            raise HTTPException(status_code=400, detail="Update failed")
        
        return {
            "success": True,
            "message": "Profile updated successfully",
            "user": {
                "user_hash": updated_user.user_hash,
                "username": updated_user.username,
                "email": updated_user.email,
                "updated_at": updated_user.updated_at if hasattr(updated_user, 'updated_at') else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Profile update error: {str(e)}")
        raise HTTPException(status_code=500, detail="Profile update error")


@router.get("/access-summary")
async def get_user_access_summary(credentials: HTTPAuthorizationCredentials = Depends(security)):
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
        
        # Build access summary
        access_summary = {
            "user": {
                "user_hash": user_data.user_hash,
                "username": user_data.username,
                "email": user_data.email
            },
            "user_groups": [{"group_name": group.group_name, "description": group.description} for group in user_groups],
            "accessible_projects": accessible_projects,
            "current_session": {
                "project_hash": session_data.project_hash,
                "project_name": session_data.project_name,
                "permissions": session_data.permissions if hasattr(session_data, 'permissions') else [],
                "expires_at": session_data.expires_at if hasattr(session_data, 'expires_at') else None
            },
            "summary": {
                "total_groups": len(user_groups),
                "total_projects": len(accessible_projects),
                "is_admin": "admin" in (session_data.permissions if hasattr(session_data, 'permissions') else [])
            }
        }
        
        return {
            "success": True,
            "access_summary": access_summary
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Access summary error: {str(e)}")
        raise HTTPException(status_code=500, detail="Access summary error") 