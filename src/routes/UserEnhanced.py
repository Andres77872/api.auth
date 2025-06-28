"""
Group-Based Multi-Project Authentication API Routes

This module provides comprehensive REST API endpoints for the group-based authentication system:

🔐 Authentication (/auth/*):
- Login, register, logout, validate sessions
- Project switching through user groups

👤 User Management (/users/*):
- Profile management and access summary
- Availability checking

📊 Project Management (/projects/*):
- CRUD operations for projects
- Project group and user management

👥 Admin User Groups (/admin/user-groups/*):
- Global user group management
- User assignments and project access

🛡️ Admin Project Groups (/admin/project-groups/*):
- Permission group management
- Project assignments and permissions

🔧 System (/system/*):
- Health checks and system information

All endpoints follow RESTful conventions with comprehensive error handling and group-based access control.
"""

import secrets
import json
import logging
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Form, HTTPException, Depends, Query, Path
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

# Import the complete database functions
from src.Util.db import (
    # Core authentication
    enhanced_login, enhanced_register, validate_session, check_username_email_available,
    
    # User management
    create_user, get_user_by_id, get_user_by_hash, update_user, delete_user,
    list_users, count_users, search_users,
    
    # Project management
    create_project, get_project_by_hash, get_project_by_id, list_all_projects, 
    update_project, delete_project, search_projects, get_project_stats,
    
    # User group management (global)
    create_user_group, get_user_group_by_id, get_user_group_by_hash, get_user_group_by_name,
    list_all_user_groups, update_user_group, delete_user_group, count_user_groups,
    assign_user_to_user_group, remove_user_from_user_group, get_user_groups_for_user,
    get_users_in_group, grant_group_project_access, revoke_group_project_access,
    get_projects_for_user_group, get_user_accessible_projects,
    
    # Project group management (permissions)
    create_project_permission_group, get_project_permission_group_by_id, 
    get_project_permission_group_by_hash, get_project_permission_group_by_name,
    list_all_project_permission_groups, update_project_permission_group, 
    delete_project_permission_group, assign_project_to_permission_group,
    remove_project_from_permission_group, get_permission_groups_for_project,
    get_projects_in_permission_group, get_user_project_permissions,
    check_user_project_permission,
    
    # User-project access
    grant_user_project_access, get_user_project_access, get_user_projects,
    revoke_user_project_access,
    
    # Legacy group management (project-scoped)
    get_user_groups_in_project, get_user_permissions_in_project,
    assign_user_to_group, remove_user_from_group,
    
    # Session management
    create_session, invalidate_session
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter()
security = HTTPBearer()

# ============================================================================
# PYDANTIC MODELS FOR REQUEST/RESPONSE
# ============================================================================

class UserGroupCreate(BaseModel):
    group_name: str
    description: str = None

class UserGroupUpdate(BaseModel):
    group_name: str = None
    description: str = None

class ProjectGroupCreate(BaseModel):
    group_name: str
    permissions: List[str]
    description: str = None

class ProjectGroupUpdate(BaseModel):
    group_name: str = None
    permissions: List[str] = None
    description: str = None

class ProjectCreate(BaseModel):
    project_name: str
    project_description: str = None

class ProjectUpdate(BaseModel):
    project_name: str = None
    project_description: str = None

class UserUpdate(BaseModel):
    username: str = None
    email: str = None
    password: str = None

class GroupAssignment(BaseModel):
    user_hash: str
    group_hash: str

class ProjectAccess(BaseModel):
    user_group_hash: str
    project_hash: str

# ============================================================================
# AUTHENTICATION ENDPOINTS (/auth/*)
# ============================================================================

@router.post("/auth/login")
async def login(
    username: str = Form(...),
    password: str = Form(...),
    project_hash: str = Form(...)
):
    """
    Authenticate user and return session token with group context.
    
    Args:
        username: User's username or email
        password: User's password
        project_hash: Project to authenticate against
        
    Returns:
        User session data with group information and accessible projects
    """
    try:
        logger.info(f"Login attempt for user: {username} in project: {project_hash}")
        
        # Authenticate user with group-based login
        login_result = enhanced_login(username, password, project_hash)
        
        if not login_result:
            logger.warning(f"Failed login attempt for user: {username}")
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        logger.info(f"Successful login for user: {username}")
        
        # Return comprehensive group-based response
        return {
            "success": True,
            "message": "Login successful",
            "session_token": login_result.session_token,
            "user": {
                "user_hash": login_result.user_hash,
                "username": login_result.username if hasattr(login_result, 'username') else username,
                "email": login_result.email if hasattr(login_result, 'email') else None,
                "user_groups": login_result.user_groups if hasattr(login_result, 'user_groups') else []
            },
            "project": {
                "project_hash": login_result.project_hash,
                "project_name": login_result.project_name,
                "permissions": login_result.permissions if hasattr(login_result, 'permissions') else []
            },
            "accessible_projects": login_result.available_projects if hasattr(login_result, 'available_projects') else [],
            "expires_at": login_result.expires_at if hasattr(login_result, 'expires_at') else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error for user {username}: {str(e)}")
        raise HTTPException(status_code=500, detail="Authentication error")


@router.post("/auth/register")
async def register(
    username: str = Form(...),
    password: str = Form(...),
    email: str = Form(...),
    project_hash: str = Form(...)
):
    """
    Register new user with automatic group assignment.
    
    Args:
        username: Desired username
        password: User's password
        email: User's email address
        project_hash: Project to register for
        
    Returns:
        Registration result with user information
    """
    try:
        logger.info(f"Registration attempt for user: {username} in project: {project_hash}")
        
        # Check if username/email is available
        if not check_username_email_available(username, email):
            raise HTTPException(status_code=409, detail="Username or email already exists")
        
        # Register user with group assignment
        register_result = enhanced_register(username, password, email, project_hash)
        
        if not register_result:
            raise HTTPException(status_code=400, detail="Registration failed")
        
        logger.info(f"Successful registration for user: {username}")
        
        return {
            "success": True,
            "message": "User registered successfully",
            "user": {
                "user_hash": register_result.user_hash,
                "username": register_result.username if hasattr(register_result, 'username') else username,
                "email": register_result.email if hasattr(register_result, 'email') else email,
                "user_groups": register_result.user_groups if hasattr(register_result, 'user_groups') else []
            },
            "project": {
                "project_hash": register_result.project_hash,
                "project_name": register_result.project_name
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Registration error for user {username}: {str(e)}")
        raise HTTPException(status_code=500, detail="Registration error")


@router.get("/auth/validate")
async def validate_user_session(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Validate session token and return user information with group context.
    
    Returns:
        Current user and session information
    """
    try:
        session_token = credentials.credentials
        
        # Validate session with group context
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid or expired session")
        
        return {
            "success": True,
            "valid": True,
            "user": {
                "user_hash": session_data.user_hash,
                "username": session_data.username if hasattr(session_data, 'username') else "user",
                "email": session_data.email if hasattr(session_data, 'email') else None,
                "user_groups": session_data.user_groups if hasattr(session_data, 'user_groups') else []
            },
            "project": {
                "project_hash": session_data.project_hash,
                "project_name": session_data.project_name,
                "permissions": session_data.permissions if hasattr(session_data, 'permissions') else []
            },
            "session": {
                "expires_at": session_data.expires_at if hasattr(session_data, 'expires_at') else None,
                "created_at": session_data.created_at if hasattr(session_data, 'created_at') else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Session validation error: {str(e)}")
        raise HTTPException(status_code=500, detail="Session validation error")


@router.post("/auth/logout")
async def logout(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Logout user and invalidate session.
    
    Returns:
        Logout confirmation
    """
    try:
        session_token = credentials.credentials
        
        # Invalidate session
        if invalidate_session(session_token):
            return {"success": True, "message": "Logged out successfully"}
        else:
            raise HTTPException(status_code=400, detail="Logout failed")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        raise HTTPException(status_code=500, detail="Logout error")


@router.post("/auth/switch-project")
async def switch_project(
    project_hash: str = Form(...),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Switch to a different project that the user's group has access to.
    
    Args:
        project_hash: Hash of the project to switch to
        
    Returns:
        New session token with updated project context
    """
    try:
        session_token = credentials.credentials
        current_session = validate_session(session_token)
        
        if not current_session:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        # Get user data
        user_data = get_user_by_hash(current_session.user_hash)
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Attempt login with new project
        new_login = enhanced_login(user_data.username, "", project_hash)  # Password not needed for switch
        
        if not new_login:
            raise HTTPException(status_code=403, detail="Access denied to requested project")
        
        # Invalidate old session
        invalidate_session(session_token)
        
        return {
            "success": True,
            "message": f"Successfully switched to project: {new_login.project_name}",
            "session_token": new_login.session_token,
            "project": {
                "project_hash": new_login.project_hash,
                "project_name": new_login.project_name,
                "permissions": new_login.permissions if hasattr(new_login, 'permissions') else []
            },
            "user_groups": new_login.user_groups if hasattr(new_login, 'user_groups') else []
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project switch error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project switch error")


# ============================================================================
# USER MANAGEMENT ENDPOINTS (/users/*)
# ============================================================================

@router.post("/users/check-availability")
async def check_availability(
    username: str = Form(None),
    email: str = Form(None)
):
    """
    Check if username or email is available globally.
    
    Args:
        username: Username to check (optional)
        email: Email to check (optional)
        
    Returns:
        Availability status for username and email
    """
    try:
        if not username and not email:
            raise HTTPException(status_code=400, detail="Username or email required")
        
        result = {
            "success": True
        }
        
        if username:
            result["username_available"] = check_username_email_available(username)
        
        if email:
            result["email_available"] = check_username_email_available(email)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Availability check error: {str(e)}")
        raise HTTPException(status_code=500, detail="Availability check error")


@router.get("/users/profile")
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


@router.put("/users/profile")
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


@router.get("/users/access-summary")
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


# ============================================================================
# PROJECT MANAGEMENT ENDPOINTS (/projects/*)
# ============================================================================

@router.get("/projects")
async def list_projects(
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: str = Query(None),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    List projects based on user's access level.
    
    Args:
        limit: Number of projects to return
        offset: Number of projects to skip
        search: Optional search term
        
    Returns:
        List of accessible projects with access information
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        user_data = get_user_by_hash(session_data.user_hash)
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Check if user is admin (can see all projects)
        user_permissions = session_data.permissions if hasattr(session_data, 'permissions') else []
        is_admin = 'admin' in user_permissions
        
        if is_admin:
            # Admin sees all projects
            if search:
                projects = search_projects(search, limit)
            else:
                projects = list_all_projects(limit, offset)
        else:
            # Regular users see only accessible projects
            accessible_projects = get_user_accessible_projects(user_data.id)
            projects = accessible_projects[offset:offset+limit] if accessible_projects else []
        
        # Add access level information
        projects_with_access = []
        for project in projects:
            project_hash = project.project_hash if hasattr(project, 'project_hash') else project.get('project_hash')
            project_permissions = get_user_project_permissions(user_data.id, project.id if hasattr(project, 'id') else project.get('project_id'))
            
            project_data = {
                "project_hash": project_hash,
                "project_name": project.project_name if hasattr(project, 'project_name') else project.get('project_name'),
                "project_description": project.project_description if hasattr(project, 'project_description') else project.get('project_description'),
                "access_level": "admin" if "admin" in project_permissions else ("read-write" if "write" in project_permissions else "read-only"),
                "access_through": "admin_access" if is_admin else "user_group"
            }
            projects_with_access.append(project_data)
        
        return {
            "success": True,
            "projects": projects_with_access,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total_count": len(projects_with_access),
                "has_more": len(projects_with_access) == limit
            },
            "user_access_level": "admin" if is_admin else "user"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project listing error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project listing error")


@router.post("/projects")
async def create_new_project(
    project_data: ProjectCreate,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Create new project and assign it to default project group.
    
    Args:
        project_data: Project creation data
        
    Returns:
        Created project information
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        # Check if user has permission to create projects
        user_permissions = session_data.permissions if hasattr(session_data, 'permissions') else []
        if 'admin' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required to create projects")
        
        # Get current user for audit trail
        user_data = get_user_by_hash(session_data.user_hash)
        
        # Create project
        new_project = create_project(project_data.project_name, project_data.project_description)
        
        if not new_project:
            raise HTTPException(status_code=400, detail="Project creation failed")
        
        logger.info(f"Project created: {project_data.project_name} by user: {user_data.username}")
        
        return {
            "success": True,
            "message": f"Project \"{project_data.project_name}\" created successfully",
            "project": {
                "project_hash": new_project.project_hash,
                "project_name": new_project.project_name,
                "project_description": new_project.project_description,
                "created_at": new_project.project_created if hasattr(new_project, 'project_created') else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project creation error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project creation error")


@router.get("/projects/{project_hash}")
async def get_project_details(
    project_hash: str = Path(...),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Get detailed project information with user's access context.
    
    Args:
        project_hash: Project identifier
        
    Returns:
        Detailed project information with user's permissions
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        # Get project details
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Get user data
        user_data = get_user_by_hash(session_data.user_hash)
        
        # Check if user has access to this project
        user_permissions = get_user_project_permissions(user_data.id, project.id)
        if not user_permissions and 'admin' not in (session_data.permissions if hasattr(session_data, 'permissions') else []):
            raise HTTPException(status_code=403, detail="Access denied to this project")
        
        # Get project statistics
        project_stats = get_project_stats(project.id)
        
        # Get user groups that have access to this project
        user_groups = get_user_groups_for_user(user_data.id)
        
        return {
            "success": True,
            "project": {
                "project_id": project.id,
                "project_hash": project.project_hash,
                "project_name": project.project_name,
                "project_description": project.project_description,
                "created_at": project.project_created if hasattr(project, 'project_created') else None,
                "is_active": project.is_active if hasattr(project, 'is_active') else True
            },
            "user_access": {
                "permissions": user_permissions,
                "access_level": "admin" if "admin" in user_permissions else ("read-write" if "write" in user_permissions else "read-only"),
                "user_groups": [group.group_name for group in user_groups]
            },
            "statistics": project_stats or {}
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project details error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project details error")


@router.put("/projects/{project_hash}")
async def update_project_details(
    project_hash: str = Path(...),
    project_data: ProjectUpdate = None,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Update project information (admin only).
    
    Args:
        project_hash: Project identifier
        project_data: Project update data
        
    Returns:
        Updated project information
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        # Check admin permission
        user_permissions = session_data.permissions if hasattr(session_data, 'permissions') else []
        if 'admin' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required")
        
        # Get project
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Get current user for audit trail
        user_data = get_user_by_hash(session_data.user_hash)
        
        # Update project
        updated_project = update_project(
            project.id,
            project_name=project_data.project_name if project_data else None,
            project_description=project_data.project_description if project_data else None,
            updated_by=user_data.id
        )
        
        if not updated_project:
            raise HTTPException(status_code=400, detail="Update failed")
        
        return {
            "success": True,
            "message": "Project updated successfully",
            "project": {
                "project_id": updated_project.id,
                "project_hash": updated_project.project_hash,
                "project_name": updated_project.project_name,
                "project_description": updated_project.project_description,
                "updated_by": user_data.id
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project update error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project update error")


@router.delete("/projects/{project_hash}")
async def delete_project_endpoint(
    project_hash: str = Path(...),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Delete a project and revoke all access (admin only).
    
    Args:
        project_hash: Project identifier
        
    Returns:
        Deletion confirmation
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        # Check admin permission
        user_permissions = session_data.permissions if hasattr(session_data, 'permissions') else []
        if 'admin' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required")
        
        # Get project
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Get current user for audit trail
        user_data = get_user_by_hash(session_data.user_hash)
        
        # Delete project
        if delete_project(project.id, deleted_by=user_data.id):
            return {
                "success": True,
                "message": f"Project \"{project.project_name}\" deleted successfully",
                "deleted_project": {
                    "project_hash": project.project_hash,
                    "project_name": project.project_name,
                    "deleted_by": user_data.id
                },
                "warning": "All user group access to this project has been revoked"
            }
        else:
            raise HTTPException(status_code=400, detail="Delete failed")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project deletion error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project deletion error")


# ============================================================================
# ADMIN USER GROUP MANAGEMENT (/admin/user-groups/*)
# ============================================================================

@router.get("/admin/user-groups")
async def list_user_groups(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    List all global user groups (admin only).
    
    Returns:
        List of user groups with member counts
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        # Check admin permission
        user_permissions = session_data.permissions if hasattr(session_data, 'permissions') else []
        if 'admin' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required")
        
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


@router.post("/admin/user-groups")
async def create_user_group_endpoint(
    group_data: UserGroupCreate,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Create a new global user group (admin only).
    
    Args:
        group_data: User group creation data
        
    Returns:
        Created user group information
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        # Check admin permission
        user_permissions = session_data.permissions if hasattr(session_data, 'permissions') else []
        if 'admin' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required")
        
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


@router.get("/admin/user-groups/{group_hash}")
async def get_user_group_details(
    group_hash: str = Path(...),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Get detailed user group information (admin only).
    
    Args:
        group_hash: User group identifier
        
    Returns:
        User group details with members and project access
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        # Check admin permission
        user_permissions = session_data.permissions if hasattr(session_data, 'permissions') else []
        if 'admin' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required")
        
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


@router.post("/admin/user-groups/{group_hash}/members")
async def assign_user_to_group_endpoint(
    group_hash: str = Path(...),
    assignment: GroupAssignment = None,
    user_hash: str = Form(None),
    credentials: HTTPAuthorizationCredentials = Depends(security)
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
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        # Check admin permission
        user_permissions = session_data.permissions if hasattr(session_data, 'permissions') else []
        if 'admin' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required")
        
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


@router.post("/admin/user-groups/{group_hash}/projects")
async def grant_group_project_access_endpoint(
    group_hash: str = Path(...),
    project_access: ProjectAccess = None,
    project_hash: str = Form(None),
    credentials: HTTPAuthorizationCredentials = Depends(security)
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
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        # Check admin permission
        user_permissions = session_data.permissions if hasattr(session_data, 'permissions') else []
        if 'admin' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required")
        
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


# ============================================================================
# ADMIN PROJECT GROUP MANAGEMENT (/admin/project-groups/*)
# ============================================================================

@router.get("/admin/project-groups")
async def list_project_groups(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    List all project permission groups (admin only).
    
    Returns:
        List of project groups with project counts
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        # Check admin permission
        user_permissions = session_data.permissions if hasattr(session_data, 'permissions') else []
        if 'admin' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required")
        
        # Get all project groups
        project_groups = list_all_project_permission_groups(limit, offset)
        
        # Add project counts
        groups_with_counts = []
        for group in project_groups:
            projects = get_projects_in_permission_group(group.id)
            groups_with_counts.append({
                "group_hash": group.group_hash,
                "group_name": group.group_name,
                "description": group.description,
                "permissions": group.permissions,
                "project_count": len(projects),
                "created_at": group.created_at,
                "is_active": group.is_active
            })
        
        return {
            "success": True,
            "project_groups": groups_with_counts,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total": len(groups_with_counts)
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project groups listing error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project groups listing error")


@router.post("/admin/project-groups")
async def create_project_group_endpoint(
    group_data: ProjectGroupCreate,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Create a new project permission group (admin only).
    
    Args:
        group_data: Project group creation data
        
    Returns:
        Created project group information
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        # Check admin permission
        user_permissions = session_data.permissions if hasattr(session_data, 'permissions') else []
        if 'admin' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required")
        
        # Get current user for audit trail
        user_data = get_user_by_hash(session_data.user_hash)
        
        # Create project group
        new_group = create_project_permission_group(
            group_data.group_name,
            group_data.permissions,
            group_data.description,
            created_by=user_data.id
        )
        
        if not new_group:
            raise HTTPException(status_code=400, detail="Project group creation failed")
        
        return {
            "success": True,
            "message": f"Project group \"{group_data.group_name}\" created successfully",
            "project_group": {
                "group_hash": new_group.group_hash,
                "group_name": new_group.group_name,
                "description": new_group.description,
                "permissions": new_group.permissions,
                "created_at": new_group.created_at
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project group creation error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project group creation error")


# ============================================================================
# SYSTEM INFORMATION ENDPOINTS (/system/*)
# ============================================================================

@router.get("/system/info")
async def get_system_info():
    """
    Get system information and health status.
    
    Returns:
        System status and configuration information
    """
    try:
        # Get basic system statistics (safely)
        try:
            total_users = count_users()
        except:
            total_users = 0
            
        try:
            total_projects = count_projects()
        except:
            total_projects = 0
            
        try:
            total_user_groups = count_user_groups()
        except:
            total_user_groups = 0
            
        try:
            total_project_groups = count_project_permission_groups()
        except:
            total_project_groups = 0
        
        return {
            "success": True,
            "system": {
                "name": "Group-Based Multi-Project Authentication API",
                "version": "2.0.0",
                "architecture": "hierarchical-group-based",
                "status": "operational"
            },
            "statistics": {
                "total_users": total_users,
                "total_projects": total_projects,
                "total_user_groups": total_user_groups,
                "total_project_groups": total_project_groups,
                "authentication_type": "group-based-jwt"
            },
            "features": [
                "hierarchical-group-access-control",
                "global-user-groups",
                "project-permission-groups",
                "multi-project-support",
                "session-management-with-group-context",
                "comprehensive-audit-trail",
                "restful-admin-api"
            ]
        }
        
    except Exception as e:
        logger.error(f"System info error: {str(e)}")
        return {
            "success": False,
            "error": "System information temporarily unavailable",
            "system": {
                "name": "Group-Based Multi-Project Authentication API",
                "version": "2.0.0",
                "architecture": "hierarchical-group-based",
                "status": "operational"
            }
        }


@router.get("/system/health")
async def system_health():
    """
    Comprehensive system health check.
    
    Returns:
        Detailed health status of all system components
    """
    try:
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "components": {}
        }
        
        # Check database connectivity
        try:
            count_users()
            health_status["components"]["database"] = {"status": "healthy", "message": "Database accessible"}
        except Exception as e:
            health_status["components"]["database"] = {"status": "unhealthy", "message": f"Database error: {str(e)}"}
            health_status["status"] = "degraded"
        
        # Check Redis connectivity
        try:
            from src.Util.db import client
            client.ping()
            health_status["components"]["redis"] = {"status": "healthy", "message": "Redis accessible"}
        except Exception as e:
            health_status["components"]["redis"] = {"status": "unhealthy", "message": f"Redis error: {str(e)}"}
            health_status["status"] = "degraded"
        
        # Check group system
        try:
            user_groups = list_all_user_groups(1, 0)
            project_groups = list_all_project_permission_groups(1, 0)
            health_status["components"]["group_system"] = {
                "status": "healthy", 
                "message": f"Group system operational: {len(user_groups)} user groups, {len(project_groups)} project groups"
            }
        except Exception as e:
            health_status["components"]["group_system"] = {"status": "unhealthy", "message": f"Group system error: {str(e)}"}
            health_status["status"] = "degraded"
        
        return health_status
        
    except Exception as e:
        logger.error(f"Health check error: {str(e)}")
        return {
            "status": "unhealthy",
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }


@router.get("/ping")
async def ping():
    """
    Simple health check endpoint.
    
    Returns:
        Basic health status
    """
    return {"success": True, "message": "Group-based authentication API is running", "timestamp": datetime.now().isoformat()}


@router.head("/access")
async def validate_access(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Validate session token and check permissions (middleware endpoint).
    
    Returns:
        HTTP status only (for middleware use)
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid or expired session")
        
        # Return 200 for valid sessions
        return {"valid": True}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Access validation error: {str(e)}")
        raise HTTPException(status_code=500, detail="Access validation error")


# ============================================================================
# UTILITY FUNCTIONS AND DEPENDENCIES
# ============================================================================

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Dependency to get current authenticated user from session token.
    
    Returns:
        Current user session data with group context
    """
    session_token = credentials.credentials
    session_data = validate_session(session_token)
    
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    return session_data


async def require_admin_permission(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Dependency to ensure user has admin permissions.
    
    Returns:
        Current user session data (if admin)
    """
    session_data = await get_current_user(credentials)
    
    user_permissions = session_data.permissions if hasattr(session_data, 'permissions') else []
    if 'admin' not in user_permissions:
        raise HTTPException(status_code=403, detail="Admin permission required")
    
    return session_data


def count_projects_safe():
    """Helper function to count projects safely"""
    try:
        return count_projects()
    except:
        return 0


# Export router
__all__ = ['router'] 