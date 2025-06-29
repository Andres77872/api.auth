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
from src.Util.Models import (
    LoginResponse, RegisterResponse, ValidateSessionResponse, LogoutResponse,
    SwitchProjectResponse, CheckAvailabilityResponse, UserInfo, ProjectInfo
)

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/auth", tags=["Authentication"])
security = HTTPBearer()


@router.post("/login", response_model=LoginResponse)
async def login(
    username: str = Form(...),
    password: str = Form(...),
    project_hash: str = Form(...)
) -> LoginResponse:
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
        
        # Build user info
        user_info = UserInfo(
            user_hash=login_result.user_hash,
            username=getattr(login_result, 'username', username),
            email=getattr(login_result, 'email', None),
            user_type=getattr(login_result, 'user_type', 'consumer')
        )
        
        # Build project info
        project_info = ProjectInfo(
            project_hash=login_result.project_hash,
            project_name=login_result.project_name
        )
        
        # Build accessible projects list
        accessible_projects = []
        if hasattr(login_result, 'available_projects') and login_result.available_projects:
            for proj in login_result.available_projects:
                accessible_projects.append(ProjectInfo(
                    project_hash=getattr(proj, 'project_hash', ''),
                    project_name=getattr(proj, 'project_name', ''),
                    project_description=getattr(proj, 'project_description', None)
                ))
        
        return LoginResponse(
            success=True,
            message="Login successful",
            session_token=login_result.session_token,
            user=user_info,
            project=project_info,
            accessible_projects=accessible_projects,
            expires_at=getattr(login_result, 'expires_at', None)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error for user {username}: {str(e)}")
        raise HTTPException(status_code=500, detail="Authentication error")


@router.post("/register", response_model=RegisterResponse)
async def register(
    username: str = Form(...),
    password: str = Form(...),
    email: str = Form(...),
    project_hash: str = Form(...)
) -> RegisterResponse:
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
        
        user_info = UserInfo(
            user_hash=register_result.user_hash,
            username=getattr(register_result, 'username', username),
            email=getattr(register_result, 'email', email),
            user_type=getattr(register_result, 'user_type', 'consumer')
        )
        
        project_info = ProjectInfo(
            project_hash=register_result.project_hash,
            project_name=register_result.project_name
        )
        
        return RegisterResponse(
            success=True,
            message="User registered successfully",
            user=user_info,
            project=project_info
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Registration error for user {username}: {str(e)}")
        raise HTTPException(status_code=500, detail="Registration error")


@router.get("/validate", response_model=ValidateSessionResponse)
async def validate_user_session(credentials: HTTPAuthorizationCredentials = Depends(security)) -> ValidateSessionResponse:
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
        
        user_info = UserInfo(
            user_hash=session_data.user_hash,
            username=getattr(session_data, 'username', 'user'),
            email=getattr(session_data, 'email', None),
            user_type=getattr(session_data, 'user_type', 'consumer')
        )
        
        project_info = ProjectInfo(
            project_hash=session_data.project_hash,
            project_name=session_data.project_name
        )
        
        session_info = {
            "expires_at": getattr(session_data, 'expires_at', None),
            "created_at": getattr(session_data, 'created_at', None)
        }
        
        return ValidateSessionResponse(
            success=True,
            valid=True,
            user=user_info,
            project=project_info,
            session=session_info
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Session validation error: {str(e)}")
        raise HTTPException(status_code=500, detail="Session validation error")


@router.post("/logout", response_model=LogoutResponse)
async def logout(credentials: HTTPAuthorizationCredentials = Depends(security)) -> LogoutResponse:
    """
    Logout user and invalidate session.
    
    Returns:
        Logout confirmation
    """
    try:
        session_token = credentials.credentials
        
        # Invalidate session
        if invalidate_session(session_token):
            return LogoutResponse(success=True, message="Logged out successfully")
        else:
            raise HTTPException(status_code=400, detail="Logout failed")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        raise HTTPException(status_code=500, detail="Logout error")


@router.post("/switch-project", response_model=SwitchProjectResponse)
async def switch_project(
    project_hash: str = Form(...),
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> SwitchProjectResponse:
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
        
        project_info = ProjectInfo(
            project_hash=new_project.project_hash,
            project_name=new_project.project_name
        )
        
        user_groups = getattr(current_session, 'user_groups', [])
        if hasattr(current_session, 'groups'):
            user_groups = current_session.groups
        
        return SwitchProjectResponse(
            success=True,
            message=f"Successfully switched to project: {new_project.project_name}",
            session_token=new_session_token,
            project=project_info,
            user_groups=user_groups
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project switch error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project switch error")


@router.post("/check-availability", response_model=CheckAvailabilityResponse)
async def check_availability(
    username: str = Form(None),
    email: str = Form(None)
) -> CheckAvailabilityResponse:
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
        
        username_available = None
        email_available = None
        
        if username:
            username_available = check_username_email_available(username)
        
        if email:
            email_available = check_username_email_available(email)
        
        return CheckAvailabilityResponse(
            success=True,
            username_available=username_available,
            email_available=email_available
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Availability check error: {str(e)}")
        raise HTTPException(status_code=500, detail="Availability check error") 