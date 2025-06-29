"""
Authentication Routes

Handles user authentication, registration, and session management
for the group-based multi-project authentication system.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Depends, Response
from fastapi.security import HTTPAuthorizationCredentials

from src.Util.Models import (
    LoginResponse, RegisterResponse, ValidateSessionResponse, LogoutResponse,
    SwitchProjectResponse, CheckAvailabilityResponse, UserInfo, ProjectInfo
)
from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.db import (
    enhanced_login, enhanced_register, validate_session,
    check_username_email_available, invalidate_session,
    get_user_by_hash
)
from src.Util.db import get_user_by_credentials, get_user_type

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/auth", tags=["Authentication"])
security = HTTPBearerOrCookie()

# Cookie settings
COOKIE_NAME = "session_token"
COOKIE_MAX_AGE = 72 * 60 * 60  # 72 hours (3 days)


@router.post("/login", response_model=LoginResponse)
async def login(
        response: Response,
        username: str = Form(...),
        password: str = Form(...),
        project_hash: str = Form(None)
) -> LoginResponse:
    """
    Authenticate user and return session token with group context.
    Sets HTTP-only cookie with JWT token.
    
    For root users: project_hash is optional (they have global access)
    For other users: project_hash is required
    
    Args:
        username: User's username or email
        password: User's password
        project_hash: Project to authenticate against - optional for root users
        
    Returns:
        User session data with group information and accessible projects
    """
    try:
        auth_username = username
        auth_password = password
        auth_project_hash = project_hash

        if not auth_username or not auth_password:
            raise HTTPException(status_code=400, detail="Username and password are required")

        logger.info(f"Login attempt for user: {auth_username}")

        # Verify credentials without project context first
        user_check = get_user_by_credentials(auth_username, auth_password)
        if not user_check:
            logger.warning(f"Failed login attempt for user: {auth_username}")
            raise HTTPException(status_code=401, detail="Invalid credentials")

        user_type = get_user_type(user_check.id)

        # For root users, project_hash is optional
        if user_type == "root":
            if not auth_project_hash:
                # Root user login without project - create a global session
                logger.info(f"Root user global login: {auth_username}")

                # Create a special global session for root users
                from src.Util.db.db_enhanced import create_root_session
                root_session = create_root_session(auth_username, auth_password)

                if not root_session:
                    raise HTTPException(status_code=401, detail="Root session creation failed")

                user_info = UserInfo(
                    user_hash=user_check.user_hash,
                    username=user_check.username,
                    email=user_check.email,
                    user_type="root"
                )

                # Set HTTP-only cookie with JWT token
                response.set_cookie(
                    key=COOKIE_NAME,
                    value=root_session['session_token'],
                    max_age=COOKIE_MAX_AGE,
                    httponly=True,
                    secure=True,
                    samesite="strict"
                )

                # Root users have global access - no specific project
                return LoginResponse(
                    success=True,
                    message="Root user login successful - global access granted",
                    session_token=root_session['session_token'],
                    user=user_info,
                    project=None,  # No specific project for global root access
                    accessible_projects=[],  # Root users can access all projects
                    expires_at=None
                )
            else:
                # Root user wants to login to a specific project
                logger.info(f"Root user project-specific login: {auth_username} in project: {auth_project_hash}")
        else:
            # Non-root users must provide project_hash
            if not auth_project_hash:
                raise HTTPException(status_code=400, detail="Project hash is required for non-root users")

        # Standard login flow for non-root users or root users with project context
        login_result = enhanced_login(auth_username, auth_password, auth_project_hash)

        if not login_result:
            logger.warning(f"Failed enhanced login for user: {auth_username}")
            raise HTTPException(status_code=401, detail="Invalid credentials or project access denied")

        logger.info(f"Successful login for user: {auth_username}")

        # Set HTTP-only cookie with JWT token
        response.set_cookie(
            key=COOKIE_NAME,
            value=login_result.session_token,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            secure=True,
            samesite="strict"
        )

        # Build user info
        user_info = UserInfo(
            user_hash=login_result.user_hash,
            username=getattr(login_result, 'username', auth_username),
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
        logger.error(f"Login error for user {auth_username if 'auth_username' in locals() else 'unknown'}: {str(e)}")
        raise HTTPException(status_code=500, detail="Authentication error")


@router.post("/register", response_model=RegisterResponse)
async def register(
        response: Response,
        username: str = Form(...),
        password: str = Form(...),
        email: str = Form(...),
        project_hash: str = Form(...)
) -> RegisterResponse:
    """
    Register new user with automatic group assignment.
    Sets HTTP-only cookie with JWT token.
    
    Args:
        username: Desired username
        password: User's password
        email: User's email address
        project_hash: Project to register for
        
    Returns:
        Registration result with user information
    """
    try:
        reg_username = username
        reg_password = password
        reg_email = email
        reg_project_hash = project_hash

        if not reg_username or not reg_password or not reg_email or not reg_project_hash:
            raise HTTPException(status_code=400, detail="Username, password, email, and project_hash are required")

        logger.info(f"Registration attempt for user: {reg_username} in project: {reg_project_hash}")

        # Check if username/email is available
        if not check_username_email_available(reg_username):
            raise HTTPException(status_code=409, detail="Username already exists")
        if reg_email and not check_username_email_available(reg_email):
            raise HTTPException(status_code=409, detail="Email already exists")

        # Register user with group assignment
        register_result = enhanced_register(reg_username, reg_password, reg_email, reg_project_hash)

        if not register_result:
            raise HTTPException(status_code=400, detail="Registration failed")

        logger.info(f"Successful registration for user: {reg_username}")

        # Set HTTP-only cookie with JWT token
        response.set_cookie(
            key=COOKIE_NAME,
            value=register_result.session_token,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            secure=True,
            samesite="strict"
        )

        user_info = UserInfo(
            user_hash=register_result.user_hash,
            username=getattr(register_result, 'username', reg_username),
            email=getattr(register_result, 'email', reg_email),
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
        logger.error(
            f"Registration error for user {reg_username if 'reg_username' in locals() else 'unknown'}: {str(e)}")
        raise HTTPException(status_code=500, detail="Registration error")


@router.get("/validate", response_model=ValidateSessionResponse)
async def validate_user_session(
        credentials: HTTPAuthorizationCredentials = Depends(security)) -> ValidateSessionResponse:
    """
    Validate session token and return user information with group context.
    Supports global root sessions without project context.
    
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

        # Handle global root sessions (no specific project)
        if (session_data.user_type == 'root' and
                session_data.project_hash == "" and
                session_data.project_name == "Global Root Access"):
            project_info = ProjectInfo(
                project_hash="",
                project_name="Global Root Access",
                project_description="Unrestricted global access for root user"
            )
        else:
            # Regular project-based session
            project_info = ProjectInfo(
                project_hash=session_data.project_hash,
                project_name=session_data.project_name
            )

        session_info = {
            "expires_at": getattr(session_data, 'expires_at', None),
            "created_at": getattr(session_data, 'created_at', None),
            "is_global_session": session_data.user_type == 'root' and session_data.project_hash == ""
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
async def logout(
        response: Response,
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> LogoutResponse:
    """
    Logout user and invalidate session.
    Clears the session cookie.
    
    Returns:
        Logout confirmation
    """
    try:
        session_token = credentials.credentials

        # Invalidate session
        if invalidate_session(session_token):
            # Clear the session cookie
            response.delete_cookie(key=COOKIE_NAME)
            return LogoutResponse(success=True, message="Logged out successfully")
        else:
            raise HTTPException(status_code=400, detail="Logout failed")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        raise HTTPException(status_code=500, detail="Logout error")


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(
        response: Response,
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> LoginResponse:
    """
    Refresh JWT token and extend session.
    Creates a new token with updated expiration while maintaining the same session context.
    
    Returns:
        New session token with same user and project context
    """
    try:
        session_token = credentials.credentials

        # Validate current session
        session_data = validate_session(session_token)
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid or expired session")

        # Get user data
        user_data = get_user_by_hash(session_data.user_hash)
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")

        # Create new session token with same context
        from src.Util.db import create_session, get_project_by_hash

        # Handle global root sessions differently
        if (session_data.user_type == 'root' and
                session_data.project_hash == "" and
                session_data.project_name == "Global Root Access"):

            # Create new global root session
            from src.Util.db.db_enhanced import create_root_session
            root_session = create_root_session(user_data.username, "")  # No password needed for refresh

            if not root_session:
                raise HTTPException(status_code=500, detail="Failed to refresh root session")

            new_session_token = root_session['session_token']

            # Build response for global root session
            user_info = UserInfo(
                user_hash=user_data.user_hash,
                username=user_data.username,
                email=user_data.email,
                user_type="root"
            )

            project_info = ProjectInfo(
                project_hash="",
                project_name="Global Root Access",
                project_description="Unrestricted global access for root user"
            )

        else:
            # Regular project-based session refresh
            project = get_project_by_hash(session_data.project_hash)
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")

            # Create new session with same project context
            new_session_token = create_session(
                user_data.id,
                project.id,
                getattr(session_data, 'user_project_id', None)
            )

            if not new_session_token:
                raise HTTPException(status_code=500, detail="Failed to create new session")

            user_info = UserInfo(
                user_hash=user_data.user_hash,
                username=user_data.username,
                email=user_data.email,
                user_type=getattr(session_data, 'user_type', 'consumer')
            )

            project_info = ProjectInfo(
                project_hash=project.project_hash,
                project_name=project.project_name
            )

        # Invalidate old session
        invalidate_session(session_token)

        # Set new session cookie
        response.set_cookie(
            key=COOKIE_NAME,
            value=new_session_token,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            secure=True,
            samesite="strict"
        )

        logger.info(f"Token refreshed for user: {user_data.username}")

        return LoginResponse(
            success=True,
            message="Token refreshed successfully",
            session_token=new_session_token,
            user=user_info,
            project=project_info,
            accessible_projects=[],  # Can be populated if needed
            expires_at=None
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh error: {str(e)}")
        raise HTTPException(status_code=500, detail="Token refresh error")


@router.post("/switch-project", response_model=SwitchProjectResponse)
async def switch_project(
        response: Response,
        project_hash: str = Form(...),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> SwitchProjectResponse:
    """
    Switch to a different project that the user's group has access to.
    Updates the session cookie with new JWT token.
    
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

        target_project_hash = project_hash

        if not target_project_hash:
            raise HTTPException(status_code=400, detail="Project hash is required")

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
        new_project = get_project_by_hash(target_project_hash)
        if not new_project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Check if user has access to the new project through their groups
        accessible_projects = get_user_accessible_projects(user_data.id)

        if not any(p.project_hash == target_project_hash for p in accessible_projects):
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

        # Update the session cookie with new JWT token
        response.set_cookie(
            key=COOKIE_NAME,
            value=new_session_token,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            secure=True,
            samesite="strict"
        )

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
        username: Optional[str] = Form(None),
        email: Optional[str] = Form(None)
) -> CheckAvailabilityResponse:
    """
    Check if username or email is available globally.
    
    Args:
        username: Username to check
        email: Email to check
        
    Returns:
        Availability status for username and email
    """
    try:
        check_username = username
        check_email = email

        if not check_username and not check_email:
            raise HTTPException(status_code=400, detail="Username or email required")

        username_available = None
        email_available = None

        if check_username:
            username_available = check_username_email_available(check_username)

        if check_email:
            email_available = check_username_email_available(check_email)

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
