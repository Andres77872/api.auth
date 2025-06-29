"""
User Type Management Routes - 3-Tier Authentication System

Handles user type management operations for the 3-tier user system:
- ROOT USERS: Super administrators with unrestricted global access
- ADMIN USERS: Project-specific administrators limited to assigned projects  
- CONSUMER USERS: End users with RBAC-based permissions through groups
"""

import logging
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional

from src.Util.db import (
    validate_session, get_user_by_hash, get_user_by_id,
    create_root_user, create_admin_user, create_consumer_user,
    get_user_type, get_admin_assigned_project,
    update_user_type, assign_admin_to_project,
    is_root_user, is_admin_user,
    get_user_type_info, list_users, count_users,
    get_project_by_id
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/user-types", tags=["User Type Management"])
security = HTTPBearer()

class CreateRootUser(BaseModel):
    username: str
    password: str
    email: str = None

class CreateAdminUser(BaseModel):
    username: str
    password: str
    email: str
    assigned_project_id: int

class UpdateUserType(BaseModel):
    user_type: str
    assigned_project_id: Optional[int] = None

def require_root_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Middleware to ensure only root users can access certain endpoints"""
    session_token = credentials.credentials
    session_data = validate_session(session_token)
    
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    user = get_user_by_hash(session_data.user_hash)
    if not user or not is_root_user(user.id):
        raise HTTPException(status_code=403, detail="Root user access required")
    
    return user


@router.post("/root")
async def create_root_user_endpoint(
    user_data: CreateRootUser,
    current_user = Depends(require_root_user)
):
    """Create a new root (super admin) user. Root users only."""
    try:
        new_root_user = create_root_user(
            username=user_data.username,
            password=user_data.password,
            email=user_data.email,
            created_by=current_user.id
        )
        
        return {
            "success": True,
            "message": f"Root user '{user_data.username}' created successfully",
            "user": {
                "user_hash": new_root_user.user_hash,
                "username": new_root_user.username,
                "email": new_root_user.email,
                "user_type": "root",
                "created_at": new_root_user.created_at
            }
        }
        
    except Exception as e:
        logger.error(f"Root user creation error: {str(e)}")
        if "Duplicate entry" in str(e):
            raise HTTPException(status_code=409, detail="Username or email already exists")
        raise HTTPException(status_code=500, detail="Root user creation failed")


@router.post("/admin")
async def create_admin_user_endpoint(
    user_data: CreateAdminUser,
    current_user = Depends(require_root_user)
):
    """Create a new admin user assigned to a specific project. Root users only."""
    try:
        # Verify project exists
        project = get_project_by_id(user_data.assigned_project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Assigned project not found")
        
        new_admin_user = create_admin_user(
            username=user_data.username,
            password=user_data.password,
            email=user_data.email,
            assigned_project_id=user_data.assigned_project_id,
            created_by=current_user.id
        )
        
        return {
            "success": True,
            "message": f"Admin user '{user_data.username}' created and assigned to project '{project.project_name}'",
            "user": {
                "user_hash": new_admin_user.user_hash,
                "username": new_admin_user.username,
                "email": new_admin_user.email,
                "user_type": "admin",
                "assigned_project_id": user_data.assigned_project_id,
                "assigned_project_name": project.project_name,
                "created_at": new_admin_user.created_at
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Admin user creation error: {str(e)}")
        if "Duplicate entry" in str(e):
            raise HTTPException(status_code=409, detail="Username or email already exists")
        raise HTTPException(status_code=500, detail="Admin user creation failed")


@router.get("/{user_hash}/info")
async def get_user_type_information(
    user_hash: str,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Get comprehensive user type information."""
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        target_user = get_user_by_hash(user_hash)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get comprehensive user type info
        user_type_info = get_user_type_info(target_user.id)
        
        # Add project information for admin users
        if user_type_info.get("user_type") == "admin":
            project_id = user_type_info.get("assigned_project_id")
            if project_id:
                project = get_project_by_id(project_id)
                if project:
                    user_type_info["assigned_project_name"] = project.project_name
                    user_type_info["assigned_project_hash"] = project.project_hash
        
        return {
            "success": True,
            "user_type_info": user_type_info
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get user type info error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get user type information")


@router.put("/{user_hash}/type")
async def update_user_type_endpoint(
    user_hash: str,
    type_data: UpdateUserType,
    current_user = Depends(require_root_user)
):
    """Update user type (promote/demote users). Root users only."""
    try:
        target_user = get_user_by_hash(user_hash)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Validate user type
        if type_data.user_type not in ['root', 'admin', 'consumer']:
            raise HTTPException(status_code=400, detail="Invalid user type")
        
        # Validate project assignment for admin users
        if type_data.user_type == 'admin' and not type_data.assigned_project_id:
            raise HTTPException(status_code=400, detail="Admin users must have an assigned project")
        
        # Update user type
        success = update_user_type(
            user_id=target_user.id,
            new_user_type=type_data.user_type,
            assigned_project_id=type_data.assigned_project_id,
            updated_by=current_user.id
        )
        
        if not success:
            raise HTTPException(status_code=400, detail="Failed to update user type")
        
        # Get updated user info
        updated_info = get_user_type_info(target_user.id)
        
        return {
            "success": True,
            "message": f"User '{target_user.username}' type updated to '{type_data.user_type}'",
            "user_type_info": updated_info
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update user type error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update user type")


@router.get("/users/{user_type}")
async def list_users_by_type(
    user_type: str,
    limit: int = 50,
    offset: int = 0,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """List users by user type."""
    try:
        # Validate user type
        if user_type not in ['root', 'admin', 'consumer']:
            raise HTTPException(status_code=400, detail="Invalid user type")
        
        # Limit constraints
        if limit > 100:
            limit = 100
        
        # Get users by type
        users = list_users(limit=limit, offset=offset, user_type=user_type)
        total_count = count_users(user_type=user_type)
        
        # Build response data
        user_list = []
        for user in users:
            user_info = {
                "user_hash": user.user_hash,
                "username": user.username,
                "email": user.email,
                "user_type": user.user_type,
                "created_at": user.created_at,
                "is_active": user.is_active
            }
            
            # Add project info for admin users
            if user.user_type == 'admin' and user.assigned_project_id:
                project = get_project_by_id(user.assigned_project_id)
                if project:
                    user_info["assigned_project"] = {
                        "project_id": project.id,
                        "project_hash": project.project_hash,
                        "project_name": project.project_name
                    }
            
            user_list.append(user_info)
        
        return {
            "success": True,
            "users": user_list,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total": total_count,
                "has_more": offset + limit < total_count
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"List users by type error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list users by type") 