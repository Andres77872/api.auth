"""
User Type Management Routes - 3-Tier Authentication System

Handles user type management operations for the 3-tier user system:
- ROOT USERS: Super administrators with unrestricted global access
- ADMIN USERS: Project-specific administrators limited to assigned projects  
- CONSUMER USERS: End users with RBAC-based permissions through groups

This module provides APIs for:
- Creating root users (root-only)
- Creating admin users with project assignment
- Converting user types
- Managing user type information
- Admin user project assignment management
"""

import logging
from fastapi import APIRouter, HTTPException, Depends, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional, List

from src.Util.db import (
    validate_session, get_user_by_hash, get_user_by_id,
    create_root_user, create_admin_user, create_consumer_user,
    get_user_type, get_admin_assigned_project,
    update_user_type, assign_admin_to_project,
    is_root_user, is_admin_user, check_admin_project_access,
    get_user_type_info, list_users, count_users,
    get_project_by_id
)

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/user-types", tags=["User Type Management"])
security = HTTPBearer()

# Pydantic models
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
    user_type: str  # 'root', 'admin', 'consumer'
    assigned_project_id: Optional[int] = None

class UpdateAdminProject(BaseModel):
    assigned_project_id: int


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


def require_root_or_admin_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Middleware to ensure only root or admin users can access certain endpoints"""
    session_token = credentials.credentials
    session_data = validate_session(session_token)
    
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    user = get_user_by_hash(session_data.user_hash)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user_type = get_user_type(user.id)
    if user_type not in ['root', 'admin']:
        raise HTTPException(status_code=403, detail="Root or admin user access required")
    
    return user


@router.post("/root")
async def create_root_user_endpoint(
    user_data: CreateRootUser,
    current_user = Depends(require_root_user)
):
    """
    Create a new root (super admin) user.
    
    **Root users only**: Only existing root users can create new root users.
    
    Args:
        user_data: Root user creation data
        
    Returns:
        Created root user information
    """
    try:
        logger.info(f"Root user creation attempt by user: {current_user.username}")
        
        # Create root user
        new_root_user = create_root_user(
            username=user_data.username,
            password=user_data.password,
            email=user_data.email,
            created_by=current_user.id
        )
        
        logger.info(f"Root user created: {new_root_user.username}")
        
        return {
            "success": True,
            "message": f"Root user '{user_data.username}' created successfully",
            "user": {
                "user_hash": new_root_user.user_hash,
                "username": new_root_user.username,
                "email": new_root_user.email,
                "user_type": "root",
                "created_at": new_root_user.created_at,
                "created_by": current_user.username
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
    """
    Create a new admin user assigned to a specific project.
    
    **Root users only**: Only root users can create admin users.
    
    Args:
        user_data: Admin user creation data with project assignment
        
    Returns:
        Created admin user information with project assignment
    """
    try:
        logger.info(f"Admin user creation attempt by user: {current_user.username}")
        
        # Verify project exists
        project = get_project_by_id(user_data.assigned_project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Assigned project not found")
        
        # Create admin user
        new_admin_user = create_admin_user(
            username=user_data.username,
            password=user_data.password,
            email=user_data.email,
            assigned_project_id=user_data.assigned_project_id,
            created_by=current_user.id
        )
        
        logger.info(f"Admin user created: {new_admin_user.username} for project: {project.project_name}")
        
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
                "created_at": new_admin_user.created_at,
                "created_by": current_user.username
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
    current_user = Depends(require_root_or_admin_user)
):
    """
    Get comprehensive user type information.
    
    **Root/Admin access**: Root users can access any user, admin users can access users in their project.
    
    Args:
        user_hash: Hash of the user to get information for
        
    Returns:
        Comprehensive user type information including capabilities
    """
    try:
        target_user = get_user_by_hash(user_hash)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Access control: Root users can access anyone, admin users only their project users
        if not is_root_user(current_user.id):
            if is_admin_user(current_user.id):
                current_user_project = get_admin_assigned_project(current_user.id)
                target_user_project = get_admin_assigned_project(target_user.id)
                
                # Admin users can only access users in their project or other project admins in same project
                if target_user_project != current_user_project and get_user_type(target_user.id) != 'consumer':
                    raise HTTPException(status_code=403, detail="Access denied to user outside your project")
        
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
    """
    Update user type (promote/demote users).
    
    **Root users only**: Only root users can change user types.
    
    Args:
        user_hash: Hash of the user to update
        type_data: New user type and optional project assignment
        
    Returns:
        Updated user type information
    """
    try:
        target_user = get_user_by_hash(user_hash)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Validate user type
        if type_data.user_type not in ['root', 'admin', 'consumer']:
            raise HTTPException(status_code=400, detail="Invalid user type. Must be 'root', 'admin', or 'consumer'")
        
        # Validate project assignment for admin users
        if type_data.user_type == 'admin':
            if not type_data.assigned_project_id:
                raise HTTPException(status_code=400, detail="Admin users must have an assigned project")
            
            project = get_project_by_id(type_data.assigned_project_id)
            if not project:
                raise HTTPException(status_code=404, detail="Assigned project not found")
        
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
        
        logger.info(f"User type updated: {target_user.username} -> {type_data.user_type} by {current_user.username}")
        
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


@router.put("/admin/{user_hash}/project")
async def update_admin_project_assignment(
    user_hash: str,
    project_data: UpdateAdminProject,
    current_user = Depends(require_root_user)
):
    """
    Update admin user's project assignment.
    
    **Root users only**: Only root users can reassign admin users to different projects.
    
    Args:
        user_hash: Hash of the admin user to update
        project_data: New project assignment
        
    Returns:
        Updated project assignment information
    """
    try:
        target_user = get_user_by_hash(user_hash)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Verify user is admin
        if get_user_type(target_user.id) != 'admin':
            raise HTTPException(status_code=400, detail="User is not an admin user")
        
        # Verify new project exists
        new_project = get_project_by_id(project_data.assigned_project_id)
        if not new_project:
            raise HTTPException(status_code=404, detail="Target project not found")
        
        # Get old project for logging
        old_project_id = get_admin_assigned_project(target_user.id)
        old_project = get_project_by_id(old_project_id) if old_project_id else None
        
        # Update project assignment
        success = assign_admin_to_project(
            user_id=target_user.id,
            project_id=project_data.assigned_project_id,
            assigned_by=current_user.id
        )
        
        if not success:
            raise HTTPException(status_code=400, detail="Failed to update project assignment")
        
        logger.info(f"Admin project assignment updated: {target_user.username} "
                   f"from {old_project.project_name if old_project else 'None'} "
                   f"to {new_project.project_name}")
        
        return {
            "success": True,
            "message": f"Admin user '{target_user.username}' reassigned to project '{new_project.project_name}'",
            "assignment": {
                "user_hash": target_user.user_hash,
                "username": target_user.username,
                "previous_project": old_project.project_name if old_project else None,
                "new_project": new_project.project_name,
                "new_project_id": new_project.id,
                "new_project_hash": new_project.project_hash,
                "assigned_by": current_user.username
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update admin project assignment error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update project assignment")


@router.get("/users/{user_type}")
async def list_users_by_type(
    user_type: str,
    limit: int = 50,
    offset: int = 0,
    current_user = Depends(require_root_or_admin_user)
):
    """
    List users by user type.
    
    **Root/Admin access**: Root users see all users, admin users see users in their project scope.
    
    Args:
        user_type: Type of users to list ('root', 'admin', 'consumer')
        limit: Number of users to return (max 100)
        offset: Number of users to skip
        
    Returns:
        List of users with the specified type
    """
    try:
        # Validate user type
        if user_type not in ['root', 'admin', 'consumer']:
            raise HTTPException(status_code=400, detail="Invalid user type. Must be 'root', 'admin', or 'consumer'")
        
        # Limit constraints
        if limit > 100:
            limit = 100
        
        # Access control for admin users
        project_filter = None
        if not is_root_user(current_user.id) and is_admin_user(current_user.id):
            # Admin users can only see users in their project (for consumer users)
            # or other admin users assigned to the same project
            if user_type == 'root':
                raise HTTPException(status_code=403, detail="Admin users cannot list root users")
            
            if user_type in ['admin', 'consumer']:
                project_filter = get_admin_assigned_project(current_user.id)
        
        # Get users by type
        users = list_users(limit=limit, offset=offset, user_type=user_type, project_id=project_filter)
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
            },
            "filter": {
                "user_type": user_type,
                "project_filter": project_filter
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"List users by type error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list users by type")


@router.get("/stats")
async def get_user_type_statistics(
    current_user = Depends(require_root_or_admin_user)
):
    """
    Get user type statistics and distribution.
    
    **Root/Admin access**: Root users see global stats, admin users see project-scoped stats.
    
    Returns:
        User type statistics and system information
    """
    try:
        # Get basic counts
        total_users = count_users()
        root_count = count_users(user_type='root')
        admin_count = count_users(user_type='admin')
        consumer_count = count_users(user_type='consumer')
        
        stats = {
            "total_users": total_users,
            "user_types": {
                "root": {
                    "count": root_count,
                    "percentage": round((root_count / total_users * 100), 2) if total_users > 0 else 0
                },
                "admin": {
                    "count": admin_count,
                    "percentage": round((admin_count / total_users * 100), 2) if total_users > 0 else 0
                },
                "consumer": {
                    "count": consumer_count,
                    "percentage": round((consumer_count / total_users * 100), 2) if total_users > 0 else 0
                }
            },
            "system_info": {
                "user_type_system": "3-tier (root, admin, consumer)",
                "access_model": "hierarchical",
                "features": [
                    "global-root-access",
                    "project-scoped-admin",
                    "rbac-consumer-users"
                ]
            }
        }
        
        # Add project scope info for admin users
        if not is_root_user(current_user.id) and is_admin_user(current_user.id):
            project_id = get_admin_assigned_project(current_user.id)
            project = get_project_by_id(project_id) if project_id else None
            stats["scope"] = {
                "type": "project_admin",
                "project_id": project_id,
                "project_name": project.project_name if project else None
            }
        else:
            stats["scope"] = {
                "type": "global_root",
                "access": "unrestricted"
            }
        
        return {
            "success": True,
            "statistics": stats
        }
        
    except Exception as e:
        logger.error(f"Get user type statistics error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get user type statistics") 