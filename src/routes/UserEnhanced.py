"""
Multi-Project Authentication API Routes

This module provides REST API endpoints for the group-based authentication system where:
- Users belong to User Groups (global)
- User Groups define project access
- Projects belong to Project Groups  
- Project Groups define permissions

All endpoints follow RESTful conventions and provide comprehensive error handling.
"""

import secrets
import json
import logging
from typing import List, Optional
from fastapi import APIRouter, Form, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Import the authentication system functions
from src.Util.db import (
    # Core authentication
    enhanced_login, enhanced_register, validate_session, check_username_email_available,
    
    # Project management
    create_project, get_project_by_hash, get_project_by_id, list_all_projects, 
    update_project, delete_project, search_projects, get_project_stats,
    
    # User management
    create_user, get_user_by_id, get_user_by_hash, update_user, delete_user,
    list_users, count_users, search_users,
    
    # User-project access
    grant_user_project_access, get_user_project_access, get_user_projects,
    revoke_user_project_access,
    
    # Group management
    get_user_groups_in_project, get_user_permissions_in_project,
    assign_user_to_group, remove_user_from_group,
    
    # Project group management
    get_project_groups, create_project_group, update_project_group,
    delete_project_group, create_default_groups,
    
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
# AUTHENTICATION ENDPOINTS
# ============================================================================

@router.post("/user/login")
async def login(
    username: str = Form(..., alias="usern"),
    password: str = Form(..., alias="pass"),
    project_hash: str = Form(..., alias="project_hash")
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


@router.post("/user/register")
async def register(
    username: str = Form(..., alias="usern"),
    password: str = Form(..., alias="pass"),
    email: str = Form(..., alias="email"),
    project_hash: str = Form(..., alias="project_hash")
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


@router.get("/user/validate")
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
            "message": "Session valid",
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


@router.post("/user/logout")
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


# ============================================================================
# USER MANAGEMENT ENDPOINTS
# ============================================================================

@router.get("/user/profile")
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
        user_projects = get_user_projects(user_data.id)
        
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


@router.get("/user/access-summary")
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
        
        # Get comprehensive access information
        user_projects = get_user_projects(user_data.id)
        
        # Build access summary
        access_summary = {
            "user": {
                "user_hash": user_data.user_hash,
                "username": user_data.username,
                "email": user_data.email
            },
            "group_memberships": session_data.user_groups if hasattr(session_data, 'user_groups') else [],
            "accessible_projects": [],
            "current_session": {
                "project_hash": session_data.project_hash,
                "project_name": session_data.project_name,
                "permissions": session_data.permissions if hasattr(session_data, 'permissions') else [],
                "expires_at": session_data.expires_at if hasattr(session_data, 'expires_at') else None
            }
        }
        
        # Add project details with permissions
        if user_projects:
            for project in user_projects:
                project_groups = get_project_groups(project.get('project_id', 0))
                access_summary["accessible_projects"].append({
                    "project_hash": project.get('project_hash'),
                    "project_name": project.get('project_name'),
                    "granted_at": project.get('granted_at'),
                    "project_groups": project_groups or []
                })
        
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
# PROJECT MANAGEMENT ENDPOINTS
# ============================================================================

@router.post("/projects/create")
async def create_new_project(
    project_name: str = Form(...),
    project_description: str = Form(None),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Create new project with default groups and assign creator as admin.
    
    Args:
        project_name: Name of the new project
        project_description: Optional project description
        
    Returns:
        Created project information with groups
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        # Check if user has permission to create projects
        user_permissions = session_data.permissions if hasattr(session_data, 'permissions') else []
        if 'admin' not in user_permissions and 'create_projects' not in user_permissions:
            raise HTTPException(status_code=403, detail="Insufficient permissions to create projects")
        
        # Create project
        new_project = create_project(project_name, project_description)
        
        if not new_project:
            raise HTTPException(status_code=400, detail="Project creation failed")
        
        # Create default groups for the project
        create_default_groups(new_project.id)
        
        username = session_data.username if hasattr(session_data, 'username') else "user"
        logger.info(f"Project created: {project_name} by user: {username}")
        
        return {
            "success": True,
            "message": "Project created successfully",
            "project": {
                "project_hash": new_project.project_hash,
                "project_name": new_project.project_name,
                "project_description": new_project.project_description,
                "created_at": new_project.created_at if hasattr(new_project, 'created_at') else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project creation error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project creation error")


@router.get("/projects/list")
async def list_projects(
    page: int = 1,
    limit: int = 50,
    search: str = None,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    List accessible projects with group information.
    
    Args:
        page: Page number for pagination
        limit: Number of projects per page
        search: Optional search term
        
    Returns:
        List of accessible projects with groups and permissions
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        user_data = get_user_by_hash(session_data.user_hash)
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get user's accessible projects
        if search:
            # If search term provided, search within accessible projects
            all_projects = search_projects(search, limit, (page - 1) * limit)
            # Filter to only projects user has access to
            user_projects = get_user_projects(user_data.id)
            user_project_hashes = {p.get('project_hash') for p in (user_projects or [])}
            accessible_projects = [p for p in all_projects if hasattr(p, 'project_hash') and p.project_hash in user_project_hashes]
        else:
            # Get user's projects directly
            user_projects = get_user_projects(user_data.id)
            accessible_projects = user_projects or []
            
        # Add group information to each project
        projects_with_groups = []
        for project in accessible_projects:
            project_id = project.get('project_id', 0) if isinstance(project, dict) else getattr(project, 'id', 0)
            project_groups = get_project_groups(project_id)
            
            project_data = {
                "project_hash": project.get('project_hash') if isinstance(project, dict) else getattr(project, 'project_hash', ''),
                "project_name": project.get('project_name') if isinstance(project, dict) else getattr(project, 'project_name', ''),
                "project_description": project.get('project_description') if isinstance(project, dict) else getattr(project, 'project_description', ''),
                "created_at": project.get('created_at') if isinstance(project, dict) else getattr(project, 'created_at', None),
                "groups": project_groups or []
            }
            projects_with_groups.append(project_data)
        
        return {
            "success": True,
            "projects": projects_with_groups,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": len(projects_with_groups),
                "has_more": len(projects_with_groups) == limit
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project listing error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project listing error")


@router.get("/projects/{project_hash}")
async def get_project_details(
    project_hash: str,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Get detailed project information including groups and user permissions.
    
    Args:
        project_hash: Project identifier
        
    Returns:
        Detailed project information with groups and user's permissions
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
        
        # Check if user has access to this project
        user_data = get_user_by_hash(session_data.user_hash)
        user_projects = get_user_projects(user_data.id)
        user_project_hashes = {p.get('project_hash') for p in (user_projects or [])}
        
        if project_hash not in user_project_hashes:
            raise HTTPException(status_code=403, detail="Access denied to this project")
        
        # Get project groups and user's permissions
        project_groups = get_project_groups(project.id)
        user_permissions = get_user_permissions_in_project(user_data.id, project.id)
        
        # Get project statistics
        project_stats = get_project_stats(project.id)
        
        return {
            "success": True,
            "project": {
                "project_hash": project.project_hash,
                "project_name": project.project_name,
                "project_description": project.project_description,
                "created_at": project.created_at if hasattr(project, 'created_at') else None,
                "groups": project_groups or [],
                "statistics": project_stats or {}
            },
            "user_permissions": user_permissions or [],
            "access_level": "read-write" if user_permissions and "write" in user_permissions else "read-only"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project details error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project details error")


# ============================================================================
# GROUP MANAGEMENT ENDPOINTS
# ============================================================================

@router.get("/projects/{project_hash}/groups")
async def get_project_group_info(
    project_hash: str,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Get group information for a specific project.
    
    Args:
        project_hash: Project identifier
        
    Returns:
        Project groups with permissions and member counts
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        # Get project and verify access
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Verify user has access to this project
        user_data = get_user_by_hash(session_data.user_hash)
        user_projects = get_user_projects(user_data.id)
        user_project_hashes = {p.get('project_hash') for p in (user_projects or [])}
        
        if project_hash not in user_project_hashes:
            raise HTTPException(status_code=403, detail="Access denied to this project")
        
        # Get project groups
        project_groups = get_project_groups(project.id)
        
        return {
            "success": True,
            "project": {
                "project_hash": project.project_hash,
                "project_name": project.project_name
            },
            "groups": project_groups or []
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project groups error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project groups error")


# ============================================================================
# SYSTEM INFORMATION ENDPOINTS
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
        
        return {
            "success": True,
            "system": {
                "name": "Group-Based Multi-Project Authentication API",
                "version": "2.0.0",
                "architecture": "group-based",
                "status": "operational"
            },
            "statistics": {
                "total_users": total_users,
                "total_projects": total_projects,
                "authentication_type": "group-based-jwt"
            },
            "features": [
                "group-based-access-control",
                "multi-project-support",
                "hierarchical-permissions",
                "session-management",
                "audit-trail"
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
                "architecture": "group-based",
                "status": "operational"
            }
        }


@router.get("/ping")
async def ping():
    """
    Health check endpoint.
    
    Returns:
        Simple health status
    """
    return {"success": True, "message": "Group-based authentication API is running"}


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Dependency to get current authenticated user from session token.
    
    Returns:
        Current user session data
    """
    session_token = credentials.credentials
    session_data = validate_session(session_token)
    
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    return session_data


# Export router
__all__ = ['router'] 