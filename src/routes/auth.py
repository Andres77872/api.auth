"""
Authentication Routes

Handles user authentication, registration, and session management
for the group-based multi-project authentication system.
"""

import logging
from typing import Optional
import json
import secrets
from datetime import timedelta

from fastapi import APIRouter, Form, HTTPException, Depends, Response, Request
from fastapi.security import HTTPAuthorizationCredentials

from src.Util.Models import (
    LoginResponse, RegisterResponse, ValidateSessionResponse, LogoutResponse,
    SwitchProjectResponse, CheckAvailabilityResponse, UserInfo, ProjectInfo
)
from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.decorators import log_and_handle_errors, log_unauthenticated_operation
from src.Util.log_context_models import LogContext, UnauthenticatedLogContext
from src.Util.activity_logger import ActivityType
from src.Util.error_handler import (
    AuthenticationError, AuthorizationError, ValidationError, NotFoundError,
    ConflictError, ErrorCode, create_not_found_error, create_validation_error,
    mask_uuid
)
from src.Util.db_error_wrapper import handle_db_operation, validate_uuid_format
from src.Util.db import (
    check_username_email_available,
    get_user_by_hash,
    get_user_by_credentials,
    enhanced_register,
)

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/auth", tags=["Authentication"])
security = HTTPBearerOrCookie()

# Cookie settings
COOKIE_NAME = "session_token"
COOKIE_MAX_AGE = 72 * 60 * 60  # 72 hours (3 days)

# NEW: low-level dependencies for session storage & JWT
from src.Util.db_config import redis_client  # Central redis client
from src.Util.JWT_Security import JWTTokenHandler

# NEW: helpers aligned with the group-based schema
from src.Util.db.db_user_groups import get_user_accessible_projects
from src.Util.db.db_projects import get_project_by_hash

# ---------------------------------------------------------------------------
# Session helpers (group-based, no user_projects table required)
# ---------------------------------------------------------------------------

SESSION_EXPIRE_HOURS = 72  # Default session lifetime (3 days)

def _store_session(token: str, data: dict, hours: int = SESSION_EXPIRE_HOURS) -> None:
    """Persist the session payload in Redis with appropriate TTL."""
    redis_client.set(
        f"session:{token}",
        json.dumps(data, default=str),
        ex=hours * 3600,
    )

def _delete_session(token: str) -> None:
    """Remove session payload from Redis (logout / refresh)."""
    redis_client.delete(f"session:{token}")

def _get_session(token: str) -> Optional[dict]:
    """Fetch session payload from Redis."""
    raw = redis_client.get(f"session:{token}")
    return json.loads(raw.decode()) if raw else None

def _create_session(user: "User", project: Optional["Project"] = None) -> tuple[str, int]:
    """Generate JWT & persist session payload. Returns (token, ttl_seconds)."""
    session_id = secrets.randbelow(2 ** 31)

    collection = project.project_hash if project else ""
    token = JWTTokenHandler.create_access_token(
        session_id=session_id,
        user_hash=user.user_hash,
        collection=collection,
        expires_delta=timedelta(hours=SESSION_EXPIRE_HOURS),
    )

    payload = {
        "session_id": session_id,
        "user_id": user.id,
        "user_hash": user.user_hash,
        "user_type": user.user_type,
        "project_id": getattr(project, "id", None),
        "project_hash": getattr(project, "project_hash", ""),
        "project_name": getattr(project, "project_name", "Global Root Access" if user.user_type == "root" else None),
    }

    # Persist
    _store_session(token, payload)
    return token, SESSION_EXPIRE_HOURS * 3600

# ---------------------------------------------------------------------------

@router.post("/login", response_model=LoginResponse)
@log_unauthenticated_operation(
    operation_name="user_login",
    activity_type=ActivityType.USER_LOGIN,
    extract_username=lambda *args, **kwargs: kwargs.get('username')
)
async def login(
        response: Response,
        username: str = Form(...),
        password: str = Form(...),
        project_hash: Optional[str] = Form(None),
        request: Request = None,
        log_context: UnauthenticatedLogContext = None
) -> LoginResponse:
    """
    Authenticate user and return session token.

    The project context can be specified or auto-selected:
    • Root users receive a global session (no project binding required).
    • If project_hash is provided: Login to that specific project (if user has access).
    • If project_hash is NOT provided: Admin/consumer users are automatically placed 
      in the first accessible project.
    • The complete list of accessible projects is always returned so clients may 
      switch context later with the `/auth/switch-project` endpoint.
    """
    if not username or not password:
        raise ValidationError(
            message="Username and password are required",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"missing_fields": ["username", "password"]}
        )

    # Step 1: verify credentials (username or email)
    user_record = handle_db_operation(
        lambda: get_user_by_credentials(username, password),
        error_context="user authentication"
    )
    
    if not user_record:
        raise AuthenticationError(
            message="Invalid username or password",
            error_code=ErrorCode.INVALID_CREDENTIALS,
            details={"username": username}
        )

    # ------------------------------------------------------------------
    # Root users -> global session (no project context required)
    # ------------------------------------------------------------------
    if user_record.user_type == "root":
        session_token, _ = _create_session(user_record, None)

        # Persist cookie
        response.set_cookie(
            key=COOKIE_NAME,
            value=session_token,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            secure=True,
            samesite="strict",
        )

        # Even for root we still expose list of projects for UI convenience
        accessible_projects = get_user_accessible_projects(user_record.id)
        accessible_projects_info = [
            ProjectInfo(
                project_hash=p.project_hash,
                project_name=p.project_name,
                project_description=p.project_description,
            )
            for p in accessible_projects
        ]

        return LoginResponse(
            success=True,
            message="Root user login successful - global access granted",
            session_token=session_token,
            user=UserInfo(
                user_hash=user_record.user_hash,
                username=user_record.username,
                email=user_record.email,
                user_type="root",
            ),
            project=None,
            accessible_projects=accessible_projects_info,
            user_id=user_record.id
        )

    # ------------------------------------------------------------------
    # Non-root users → choose specific or default project
    # ------------------------------------------------------------------
    accessible = get_user_accessible_projects(user_record.id)
    if not accessible:
        raise AuthorizationError(
            message="User has no access to any project",
            error_code=ErrorCode.ACCESS_DENIED,
            details={"username": username}
        )

    # Determine which project to use
    if project_hash:
        # User specified a project - verify they have access to it
        accessible_hashes = [p.project_hash for p in accessible]
        if project_hash not in accessible_hashes:
            raise AuthorizationError(
                message=f"Access denied to project {mask_uuid(project_hash)}. User has access to {len(accessible)} project(s)",
                error_code=ErrorCode.PROJECT_ACCESS_DENIED,
                details={
                    "requested_project": mask_uuid(project_hash),
                    "accessible_projects_count": len(accessible)
                }
            )
        
        target_project = handle_db_operation(
            lambda: get_project_by_hash(project_hash),
            error_context="project lookup",
            not_found_message=f"Project not found: {mask_uuid(project_hash)}"
        )
    else:
        # No project specified - use first accessible project as default
        default_project_hash = accessible[0].project_hash
        target_project = handle_db_operation(
            lambda: get_project_by_hash(default_project_hash),
            error_context="default project resolution",
            not_found_message="Failed to resolve default project context"
        )

    # Build session & response
    session_token, _ = _create_session(user_record, target_project)

    # Set secure HTTP-only cookie
    response.set_cookie(
        key=COOKIE_NAME,
        value=session_token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="strict",
    )

    # Build project info object for the chosen default project
    project_info = ProjectInfo(
        project_hash=target_project.project_hash,
        project_name=target_project.project_name,
        project_description=target_project.project_description,
    )

    # Map all accessible projects into API schema
    accessible_projects_info = [
        ProjectInfo(
            project_hash=p.project_hash,
            project_name=p.project_name,
            project_description=p.project_description,
        )
        for p in accessible
    ]

    return LoginResponse(
        success=True,
        message="Login successful",
        session_token=session_token,
        user=UserInfo(
            user_hash=user_record.user_hash,
            username=user_record.username,
            email=user_record.email,
            user_type=user_record.user_type,
        ),
        project=project_info,
        accessible_projects=accessible_projects_info,
        user_id=user_record.id
    )


@router.post("/register", response_model=RegisterResponse)
@log_unauthenticated_operation(
    operation_name="user_registration",
    activity_type=ActivityType.USER_REGISTRATION,
    extract_username=lambda *args, **kwargs: kwargs.get('username')
)
async def register(
        response: Response,
        username: str = Form(...),
        password: str = Form(...),
        email: Optional[str] = Form(None),
        user_group_hash: str = Form(...),
        request: Request = None,
        log_context: UnauthenticatedLogContext = None
) -> RegisterResponse:
    """
    Register new user with automatic group assignment.
    Sets HTTP-only cookie with JWT token.
    
    Args:
        username: Desired username
        password: User's password
        email: User's email address (optional)
        user_group_hash: User group hash for registration
        
    Returns:
        Registration result with user information
    """
    if not username or not password or not user_group_hash:
        missing_fields = []
        if not username: missing_fields.append("username")
        if not password: missing_fields.append("password")
        if not user_group_hash: missing_fields.append("user_group_hash")
        
        raise ValidationError(
            message="Required fields are missing",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"missing_fields": missing_fields}
        )

    # Check if username/email is available
    username_available = handle_db_operation(
        lambda: check_username_email_available(username),
        error_context="username availability check"
    )
    if not username_available:
        raise ConflictError(
            message="Username already exists",
            error_code=ErrorCode.USERNAME_EXISTS,
            details={"username": username}
        )
    
    if email:
        email_available = handle_db_operation(
            lambda: check_username_email_available(email),
            error_context="email availability check"
        )
        if not email_available:
            raise ConflictError(
                message="Email already exists",
                error_code=ErrorCode.EMAIL_EXISTS,
                details={"email": email}
            )

    # Register user with group assignment
    register_result = handle_db_operation(
        lambda: enhanced_register(username, password, email, user_group_hash),
        error_context="user registration"
    )
    
    if not register_result:
        from src.Util.error_handler import InternalError
        raise InternalError(
            message="Registration failed due to internal error",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "user_registration"}
        )

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
        project=project_info,
        user_id=getattr(register_result, 'user_id', None)
    )


@router.get("/validate", response_model=ValidateSessionResponse)
@log_and_handle_errors(
    operation_name="validate_session",
    activity_type=ActivityType.USER_LOGIN,
    log_success=False
)
async def validate_user_session(
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> ValidateSessionResponse:
    """
    Validate session token and return user information with group context.
    Supports global root sessions without project context.
    
    Returns:
        Current user and session information
    """
    session_token = credentials.credentials

    raw = handle_db_operation(
        lambda: _get_session(session_token),
        error_context="session validation"
    )
    
    if not raw:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_EXPIRED,
            details={"hint": "Please log in again"}
        )

    user_info = UserInfo(
        user_hash=raw["user_hash"],
        username=raw.get("username", "user"),
        user_type=raw.get("user_type", "consumer"),
    )

    if raw.get("project_hash"):
        project_info = ProjectInfo(
            project_hash=raw["project_hash"],
            project_name=raw.get("project_name", ""),
        )
    else:
        project_info = ProjectInfo(
            project_hash="",
            project_name="Global Root Access",
            project_description="Unrestricted global access for root user",
        )

    return ValidateSessionResponse(
        success=True,
        valid=True,
        user=user_info,
        project=project_info,
        session={"created_at": None, "is_global_session": raw.get("project_hash") == ""},
    )


@router.post("/logout", response_model=LogoutResponse)
@log_and_handle_errors(
    operation_name="user_logout",
    activity_type=ActivityType.USER_LOGOUT,
    log_success=True
)
async def logout(
        response: Response,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> LogoutResponse:
    """
    Logout user and invalidate session.
    Clears the session cookie.
    
    Returns:
        Logout confirmation
    """
    session_token = credentials.credentials

    _delete_session(session_token)
    # Clear the session cookie
    response.delete_cookie(key=COOKIE_NAME)
    return LogoutResponse(success=True, message="Logged out successfully")


@router.post("/refresh", response_model=LoginResponse)
@log_and_handle_errors(
    operation_name="refresh_token",
    activity_type=ActivityType.USER_LOGIN,
    log_success=False
)
async def refresh_token(
        response: Response,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> LoginResponse:
    """
    Refresh JWT token and extend session.
    Creates a new token with updated expiration while maintaining the same session context.
    
    Returns:
        New session token with same user and project context
    """
    session_token = credentials.credentials

    raw = _get_session(session_token)
    if not raw:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_EXPIRED
        )

    # Fetch fresh user & project records
    user_data = get_user_by_hash(raw["user_hash"])
    if not user_data:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND
        )

    current_project = None
    if raw.get("project_hash"):
        current_project = get_project_by_hash(raw["project_hash"])
        if not current_project:
            raise NotFoundError(
                message="Project not found",
                error_code=ErrorCode.PROJECT_NOT_FOUND
            )

    # Create brand-new session with same context
    new_token, _ = _create_session(user_data, current_project)

    # Delete old session & set cookie
    _delete_session(session_token)
    response.set_cookie(
        key=COOKIE_NAME,
        value=new_token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="strict",
    )

    project_info = None
    if current_project:
        project_info = ProjectInfo(
            project_hash=current_project.project_hash,
            project_name=current_project.project_name,
            project_description=current_project.project_description,
        )

    return LoginResponse(
        success=True,
        message="Token refreshed successfully",
        session_token=new_token,
        user=UserInfo(
            user_hash=user_data.user_hash,
            username=user_data.username,
            email=user_data.email,
            user_type=user_data.user_type,
        ),
        project=project_info,
        accessible_projects=[],
    )


@router.post("/switch-project", response_model=SwitchProjectResponse)
@log_and_handle_errors(
    operation_name="switch_project",
    activity_type=ActivityType.USER_LOGIN,
    log_success=True
)
async def switch_project(
        response: Response,
        project_hash: str = Form(...),
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> SwitchProjectResponse:
    """
    Switch to a different project that the user's group has access to.
    Updates the session cookie with new JWT token.
    
    Args:
        project_hash: Hash of the project to switch to
        
    Returns:
        New session token with updated project context
    """
    session_token = credentials.credentials
    current_raw = _get_session(session_token)
    if not current_raw:
        raise AuthenticationError(
            message="Invalid session",
            error_code=ErrorCode.SESSION_INVALID
        )

    user_data = get_user_by_hash(current_raw["user_hash"])
    if not user_data:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND
        )

    # Validate desired project exists & user has access
    new_project = get_project_by_hash(project_hash)
    if not new_project:
        raise NotFoundError(
            message=f"Project not found: {mask_uuid(project_hash)}",
            error_code=ErrorCode.PROJECT_NOT_FOUND
        )

    accessible = get_user_accessible_projects(user_data.id)
    if not any(p.project_hash == project_hash for p in accessible):
        raise AuthorizationError(
            message="Access denied to requested project",
            error_code=ErrorCode.PROJECT_ACCESS_DENIED,
            details={"project_hash": mask_uuid(project_hash)}
        )

    # Create new session and update cookie
    new_token, _ = _create_session(user_data, new_project)
    _delete_session(session_token)

    response.set_cookie(
        key=COOKIE_NAME,
        value=new_token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="strict",
    )

    project_info = ProjectInfo(
        project_hash=new_project.project_hash,
        project_name=new_project.project_name,
        project_description=new_project.project_description,
    )

    return SwitchProjectResponse(
        success=True,
        message=f"Successfully switched to project: {new_project.project_name}",
        session_token=new_token,
        project=project_info,
        user_groups=[],
    )


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
