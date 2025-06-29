"""
Authentication Routes

Handles user authentication, registration, and session management
for the group-based multi-project authentication system.
"""

import secrets
import logging
from datetime import datetime
from fastapi import APIRouter, Form, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.Util.db import (
    enhanced_login, enhanced_register, validate_session, 
    check_username_email_available, invalidate_session,
    get_user_by_hash, get_user_accessible_projects
)

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/auth", tags=["Authentication"])
security = HTTPBearer()


@router.post("/login")
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


@router.post("/register")
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
        if not check_username_email_available(username):
            raise HTTPException(status_code=409, detail="Username already exists")
        if email and not check_username_email_available(email):
            raise HTTPException(status_code=409, detail="Email already exists")
        
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


@router.get("/validate")
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


@router.post("/logout")
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


@router.post("/switch-project")
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
        
        # For project switching, we create a new session without re-validating password
        # This is secure because we already have a valid session
        from src.Util.db import (
            create_session, get_project_by_hash, get_user_accessible_projects,
            get_user_project_access, get_user_permissions_in_project
        )
        
        # Get the new project
        new_project = get_project_by_hash(project_hash)
        if not new_project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Check if user has access to the new project through their groups
        accessible_projects = get_user_accessible_projects(user_data.id)
        
        if not any(p.project_hash == project_hash for p in accessible_projects):
            raise HTTPException(status_code=403, detail="Access denied to requested project")
        
        # Create new session for the new project
        user_project = get_user_project_access(user_data.id, new_project.id)
        if not user_project:
            raise HTTPException(status_code=403, detail="No access to this project")
        
        new_session_token = create_session(user_data.id, new_project.id, user_project.id)
        
        if not new_session_token:
            raise HTTPException(status_code=403, detail="Failed to create new session")
        
        # Invalidate old session
        invalidate_session(session_token)
        
        # Get updated permissions for the new project
        permissions = get_user_permissions_in_project(user_data.id, new_project.id)
        
        return {
            "success": True,
            "message": f"Successfully switched to project: {new_project.name}",
            "session_token": new_session_token,
            "project": {
                "project_hash": new_project.project_hash,
                "project_name": new_project.name,
                "permissions": permissions
            },
            "user_groups": current_session.user_groups if hasattr(current_session, 'user_groups') else []
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project switch error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project switch error")


@router.post("/check-availability")
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