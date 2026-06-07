"""
Authentication Routes

Handles user authentication, registration, and session management
for the group-based multi-project authentication system.
"""

import logging
import time
from typing import Optional, Any
import json
import secrets
from datetime import timedelta

from fastapi import APIRouter, Form, HTTPException, Depends, Response, Request
from starlette.background import BackgroundTasks
from fastapi.security import HTTPAuthorizationCredentials

from src.Util.Models import (
    LoginResponse, RegisterResponse, ValidateSessionResponse, LogoutResponse,
    SwitchProjectResponse, CheckAvailabilityResponse, UserInfo, ProjectInfo, UserGroupInfo
)
from src.Util.Seccurity import HTTPBearerOrCookie, extract_refresh_token_from_request
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
    get_user_group_by_hash,
)
from src.Util.db.db_user_groups import get_projects_for_user_group

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/auth", tags=["Authentication"])
security = HTTPBearerOrCookie()
PLATFORM_SCOPE = "platform"

# Cookie settings
COOKIE_NAME = "session_token"
COOKIE_MAX_AGE = 72 * 60 * 60  # 72 hours (3 days)

# NEW: low-level dependencies for session storage & JWT
from src.Util.db_config import redis_client  # Central redis client
from src.Util.JWT_Security import JWTTokenHandler

# NEW: helpers aligned with the group-based schema
from src.Util.db.db_user_groups import get_user_accessible_projects, get_user_groups_for_user, get_user_groups_in_project, get_user_groups_in_project_by_hash
from src.Util.db.db_projects import get_project_by_hash
from src.Util.auth_flow import resolve_target_project
from src.Util.auth_lifecycle import issue_platform_token_pair, issue_project_token_pair, rotate_refresh_family, revoke_refresh_family, validate_access_session
from src.Util.db.db_enhanced import validate_session as validate_enhanced_session

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
    """Remove session payload from Redis (logout / refresh). Also removes full-session cache."""
    pipe = redis_client.pipeline()
    pipe.delete(f"session:{token}")
    pipe.delete(f"session_full:{token}")  # Phase 2.1c: also invalidate full-session cache
    pipe.execute()

def _get_session(token: str) -> Optional[dict]:
    """Fetch session payload from Redis."""
    raw = redis_client.get(f"session:{token}")
    if not raw:
        return None
    # Handle both bytes (default Redis) and str (decode_responses=True)
    if isinstance(raw, bytes):
        raw = raw.decode()
    return json.loads(raw)

def _create_session(user: Any, project: Optional[Any] = None) -> tuple[str, int]:
    """Generate JWT & persist session payload. Returns (token, ttl_seconds)."""
    session_id = secrets.randbelow(2 ** 31)

    collection = project.project_hash if project else ""
    token = JWTTokenHandler.create_access_token(
        session_id=session_id,
        user_hash=user.user_hash,
        collection=collection,
        expires_delta=timedelta(hours=SESSION_EXPIRE_HOURS),
    )

    # Get user groups for caching in session (groups-of-groups architecture)
    user_groups = get_user_groups_for_user(user.id) if user.user_type != "root" else []
    user_group_ids = [str(g.id) for g in user_groups]
    user_group_names = [g.group_name for g in user_groups]

    payload = {
        "session_id": session_id,
        "user_id": user.id,
        "user_hash": user.user_hash,
        "user_type": user.user_type,
        "project_id": getattr(project, "id", None),
        "project_hash": getattr(project, "project_hash", ""),
        "project_name": getattr(project, "project_name", None) if project else None,
        "user_group_ids": user_group_ids,
        "user_group_names": user_group_names,
        # Fix 1: Add canonical 'groups' key matching what validate_session() reads
        "groups": user_group_names,
        # Fix 1: Add username for downstream decorator use
        "username": user.username,
    }

    # Persist
    _store_session(token, payload)
    return token, SESSION_EXPIRE_HOURS * 3600


def _create_platform_session(user: Any) -> tuple[str, int]:
    """Generate JWT & persist a platform-scoped session for dashboard access."""
    session_id = secrets.randbelow(2 ** 31)

    token = JWTTokenHandler.create_access_token(
        session_id=session_id,
        user_hash=user.user_hash,
        collection="__platform__",
        expires_delta=timedelta(hours=SESSION_EXPIRE_HOURS),
        scope=PLATFORM_SCOPE,
    )

    if user.user_type == "root":
        permissions = ["admin", "global_admin", "manage_users", "manage_roles", "unrestricted_access"]
        groups = ["platform_root_users"]
    else:
        permissions = ["admin", "project_admin", "manage_users", "manage_roles", "manage_permissions"]
        groups = ["platform_admins"]

    payload = {
        "session_id": session_id,
        "user_id": user.id,
        "user_hash": user.user_hash,
        "user_type": user.user_type,
        "scope": PLATFORM_SCOPE,
        "project_id": None,
        "project_hash": None,
        "project_name": None,
        "permissions": permissions,
        "groups": groups,
        "user_group_ids": [],
        "user_group_names": [],
        "username": user.username,
        "assigned_project_id": getattr(user, "assigned_project_id", None),
    }

    _store_session(token, payload)
    return token, SESSION_EXPIRE_HOURS * 3600


def _set_token_pair_cookies(response: Response, token_pair) -> None:
    """Apply access and refresh cookies from lifecycle token metadata."""
    access_cookie = token_pair.cookie_metadata["access"]
    response.set_cookie(
        key=access_cookie["name"],
        value=token_pair.access_token,
        max_age=access_cookie["max_age"],
        httponly=access_cookie["httponly"],
        secure=access_cookie["secure"],
        samesite=access_cookie["samesite"],
        path=access_cookie["path"],
    )

    refresh_cookie = token_pair.cookie_metadata["refresh"]
    response.set_cookie(
        key=refresh_cookie["name"],
        value=token_pair.refresh_token,
        max_age=refresh_cookie["max_age"],
        httponly=refresh_cookie["httponly"],
        secure=refresh_cookie["secure"],
        samesite=refresh_cookie["samesite"],
        path=refresh_cookie["path"],
    )


def _route_refresh_groups(user_id: str, project_hash: str):
    try:
        groups = get_user_groups_in_project_by_hash(user_id, project_hash)
        if groups:
            return groups
    except Exception:
        logger.debug("Falling back to user groups for refresh context", exc_info=True)
    try:
        project = get_project_by_hash(project_hash)
        if project:
            groups = get_user_groups_in_project(user_id, project.id)
            if groups:
                return groups
    except Exception:
        logger.debug("Falling back to user-wide groups for refresh context", exc_info=True)
    return get_user_groups_for_user(user_id)


def _project_info_from_any(project: Any) -> Optional[ProjectInfo]:
    project_hash = getattr(project, "project_hash", None)
    if not project_hash and isinstance(project, dict):
        project_hash = project.get("project_hash")
    if not project_hash:
        return None
    project_name = getattr(project, "project_name", None)
    project_description = getattr(project, "project_description", None)
    if isinstance(project, dict):
        project_name = project.get("project_name", project_name)
        project_description = project.get("project_description", project_description)
    return ProjectInfo(
        project_hash=project_hash,
        project_name=project_name or "",
        project_description=project_description,
    )


def _login_response_from_rotation(rotation) -> LoginResponse:
    token_pair = rotation.token_pair
    login_data = rotation.login_data
    project_info = None
    if login_data.project_hash:
        project_info = ProjectInfo(
            project_hash=login_data.project_hash,
            project_name=login_data.project_name or "",
        )

    accessible_projects_info = [
        project_info_item
        for project_info_item in (_project_info_from_any(project) for project in (login_data.available_projects or []))
        if project_info_item is not None
    ]
    user_groups_info = [
        UserGroupInfo(group_hash=str(group), group_name=str(group))
        for group in (login_data.groups or [])
    ]

    return LoginResponse(
        success=True,
        message="Token refreshed successfully",
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        session_token=token_pair.session_token,
        token_type=token_pair.token_type,
        expires_in=token_pair.expires_in,
        refresh_expires_in=token_pair.refresh_expires_in,
        expires_at=token_pair.expires_at,
        refresh_expires_at=token_pair.refresh_expires_at,
        user=UserInfo(
            user_hash=login_data.user_hash,
            username=login_data.username or login_data.user_hash,
            user_type=login_data.user_type,
        ),
        project=project_info,
        accessible_projects=accessible_projects_info,
        user_groups=user_groups_info,
        user_id=login_data.user_id,
    )


def _string_attr(value: Any, attr: str) -> Optional[str]:
    candidate = getattr(value, attr, None)
    return candidate if isinstance(candidate, str) and candidate else None


def _registration_token_pair(register_result: Any):
    """Return or create a project-scoped token pair for registration.

    Real `enhanced_register()` now returns token-pair metadata. Some integration
    tests patch that function with legacy lightweight objects, so this fallback
    keeps route behavior aligned with the public contract while the DB helper is
    still covered through its own real path.
    """
    if _string_attr(register_result, "access_token") and _string_attr(register_result, "refresh_token"):
        return register_result

    project_hash = _string_attr(register_result, "project_hash")
    if not project_hash:
        return None

    user_id = _string_attr(register_result, "user_id")
    user_hash = _string_attr(register_result, "user_hash")
    if not user_id or not user_hash:
        return None

    project_id = _string_attr(register_result, "project_id")
    project_name = _string_attr(register_result, "project_name")
    username = _string_attr(register_result, "username") or user_hash
    user_type = _string_attr(register_result, "user_type") or "consumer"
    groups = list(getattr(register_result, "groups", []) or [])
    group_ids = [str(group_id) for group_id in (getattr(register_result, "user_group_ids", []) or [])]
    permissions = list(getattr(register_result, "permissions", []) or [])

    return issue_project_token_pair(
        user={
            "id": user_id,
            "user_hash": user_hash,
            "username": username,
            "user_type": user_type,
        },
        project={
            "id": project_id,
            "project_hash": project_hash,
            "project_name": project_name,
        },
        permissions=permissions,
        groups=groups,
        group_ids=group_ids,
    )

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
        project_hash: Optional[str] = Form(
            None,
            description="Required for all users. Root users bypass group-based access validation and may access any project by role.",
        ),
        request: Request = None,
        log_context: UnauthenticatedLogContext = None
) -> LoginResponse:
    """
    Authenticate user and return session token.

    The project context is mandatory for all users:
    - Root users MUST provide a project_hash but bypass group-based access validation.
    - Root may access any project by role.
    - Non-root users MUST provide a project_hash and are validated through group membership.
    - The complete list of accessible projects is always returned so clients may 
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
    # ALL users MUST provide a project_hash
    # ------------------------------------------------------------------
    if not project_hash:
        raise ValidationError(
            message="Project identifier is required for login",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"missing_fields": ["project_hash"]}
        )

    # ------------------------------------------------------------------
    # Root users -> project-bound session (bypasses group validation)
    # ------------------------------------------------------------------
    if user_record.user_type == "root":
        target_project = handle_db_operation(
            lambda: get_project_by_hash(project_hash),
            error_context="project lookup",
            not_found_message=f"Project not found: {mask_uuid(project_hash)}",
        )
        if not target_project:
            raise NotFoundError(
                message=f"Project not found: {mask_uuid(project_hash)}",
                error_code=ErrorCode.PROJECT_NOT_FOUND,
                details={"project_hash": mask_uuid(project_hash)},
            )

        token_pair = issue_project_token_pair(
            user=user_record,
            project=target_project,
            permissions=["admin", "global_admin", "unrestricted_access"],
            groups=["root_users"],
        )
        _set_token_pair_cookies(response, token_pair)

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
            message="Root user login successful",
            access_token=token_pair.access_token,
            refresh_token=token_pair.refresh_token,
            session_token=token_pair.session_token,
            token_type=token_pair.token_type,
            expires_in=token_pair.expires_in,
            refresh_expires_in=token_pair.refresh_expires_in,
            expires_at=token_pair.expires_at,
            refresh_expires_at=token_pair.refresh_expires_at,
            user=UserInfo(
                user_hash=user_record.user_hash,
                username=user_record.username,
                email=user_record.email,
                user_type="root",
            ),
            project=ProjectInfo(
                project_hash=target_project.project_hash,
                project_name=target_project.project_name,
                project_description=target_project.project_description,
            ),
            accessible_projects=accessible_projects_info,
            user_groups=[],  # Root users bypass group validation
            user_id=user_record.id
        )

    # ------------------------------------------------------------------
    # Non-root users → choose specific or default project
    # ------------------------------------------------------------------
    accessible = get_user_accessible_projects(user_record.id)
    target_project = resolve_target_project(
        accessible_projects=accessible,
        requested_project_hash=project_hash,
        get_project_by_hash_fn=get_project_by_hash,
        handle_db_operation_fn=handle_db_operation,
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

    # Get user groups for response (groups-of-groups architecture)
    user_groups = get_user_groups_for_user(user_record.id)
    user_groups_info = [
        UserGroupInfo(
            group_hash=g.group_hash,
            group_name=g.group_name,
            description=getattr(g, 'group_description', None),
        )
        for g in user_groups
    ]
    user_group_names = [g.group_name for g in user_groups]
    user_group_ids = [str(g.id) for g in user_groups]
    if user_record.user_type == "admin":
        session_groups = ["project_admins"]
        session_group_ids = []
        session_permissions = ["admin", "project_admin", "manage_users", "manage_groups", "manage_permissions"]
    else:
        session_groups = user_group_names
        session_group_ids = user_group_ids
        session_permissions = []

    token_pair = issue_project_token_pair(
        user=user_record,
        project=target_project,
        permissions=session_permissions,
        groups=session_groups,
        group_ids=session_group_ids,
    )
    _set_token_pair_cookies(response, token_pair)

    return LoginResponse(
        success=True,
        message="Login successful",
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        session_token=token_pair.session_token,
        token_type=token_pair.token_type,
        expires_in=token_pair.expires_in,
        refresh_expires_in=token_pair.refresh_expires_in,
        expires_at=token_pair.expires_at,
        refresh_expires_at=token_pair.refresh_expires_at,
        user=UserInfo(
            user_hash=user_record.user_hash,
            username=user_record.username,
            email=user_record.email,
            user_type=user_record.user_type,
        ),
        project=project_info,
        accessible_projects=accessible_projects_info,
        user_groups=user_groups_info,
        user_id=user_record.id
    )


@router.post("/platform/login", response_model=LoginResponse)
@log_unauthenticated_operation(
    operation_name="platform_user_login",
    activity_type=ActivityType.USER_LOGIN,
    extract_username=lambda *args, **kwargs: kwargs.get('username')
)
async def platform_login(
        response: Response,
        username: str = Form(...),
        password: str = Form(...),
        request: Request = None,
        log_context: UnauthenticatedLogContext = None
) -> LoginResponse:
    """Authenticate root/admin users for platform dashboard access without project scope."""
    if not username or not password:
        raise ValidationError(
            message="Username and password are required",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"missing_fields": ["username", "password"]}
        )

    user_record = handle_db_operation(
        lambda: get_user_by_credentials(username, password),
        error_context="platform user authentication"
    )

    if not user_record:
        raise AuthenticationError(
            message="Invalid username or password",
            error_code=ErrorCode.INVALID_CREDENTIALS,
            details={"username": username}
        )

    if user_record.user_type not in {"root", "admin"}:
        raise AuthorizationError(
            message="Platform login is restricted to root and admin users",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"allowed_user_types": ["root", "admin"]}
        )

    if user_record.user_type == "root":
        permissions = ["admin", "global_admin", "manage_users", "manage_roles", "unrestricted_access"]
        groups = ["platform_root_users"]
    else:
        permissions = ["admin", "project_admin", "manage_users", "manage_roles", "manage_permissions"]
        groups = ["platform_admins"]

    token_pair = issue_platform_token_pair(
        user=user_record,
        permissions=permissions,
        groups=groups,
    )
    _set_token_pair_cookies(response, token_pair)

    return LoginResponse(
        success=True,
        message="Platform login successful",
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        session_token=token_pair.session_token,
        token_type=token_pair.token_type,
        expires_in=token_pair.expires_in,
        refresh_expires_in=token_pair.refresh_expires_in,
        expires_at=token_pair.expires_at,
        refresh_expires_at=token_pair.refresh_expires_at,
        user=UserInfo(
            user_hash=user_record.user_hash,
            username=user_record.username,
            email=user_record.email,
            user_type=user_record.user_type,
        ),
        project=None,
        accessible_projects=[],
        user_groups=[],
        user_id=user_record.id,
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

    # Validate user group exists before registration
    user_group = handle_db_operation(
        lambda: get_user_group_by_hash(user_group_hash),
        error_context="user group lookup"
    )
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"user_group_hash": mask_uuid(user_group_hash)}
        )
    
    # Register user with group assignment
    register_result = handle_db_operation(
        lambda: enhanced_register(username, password, email, user_group_hash),
        error_context="user registration"
    )
    
    if not register_result:
        from src.Util.error_handler import InternalError
        raise InternalError(
            message="User creation failed during registration",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={
                "operation": "user_registration",
                "user_group": user_group.group_name,
                "hint": "User record creation failed. This may indicate a database constraint violation."
            }
        )

    token_pair = _registration_token_pair(register_result)
    if token_pair is not None:
        _set_token_pair_cookies(response, token_pair)

    user_info = UserInfo(
        user_hash=register_result.user_hash,
        username=getattr(register_result, 'username') or username,
        email=getattr(register_result, 'email', email),
        user_type=getattr(register_result, 'user_type', 'consumer')
    )

    project_info = None
    if register_result.project_hash:
        project_info = ProjectInfo(
            project_hash=register_result.project_hash,
            project_name=register_result.project_name
        )

    return RegisterResponse(
        success=True,
        message="User registered successfully",
        access_token=token_pair.access_token if token_pair else None,
        refresh_token=token_pair.refresh_token if token_pair else None,
        session_token=token_pair.session_token if token_pair else None,
        token_type=token_pair.token_type if token_pair else "Bearer",
        expires_in=token_pair.expires_in if token_pair else None,
        refresh_expires_in=token_pair.refresh_expires_in if token_pair else None,
        expires_at=token_pair.expires_at if token_pair else None,
        refresh_expires_at=token_pair.refresh_expires_at if token_pair else None,
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
        log_context: LogContext = None,
        response: Response = None,
        background_tasks: BackgroundTasks = None,
) -> ValidateSessionResponse:
    """
    Validate session token and return user information with group context.
    
    Returns:
        Current user and session information
    """
    _t_start = time.monotonic()
    session_token = credentials.credentials

    try:
        if not isinstance(session_token, str) or session_token.count(".") != 2:
            raise AuthenticationError(
                message="Invalid access token",
                error_code=ErrorCode.SESSION_EXPIRED,
                details={"hint": "Please log in again with a valid access token"}
            )

        try:
            login_data = validate_enhanced_session(session_token)
        except HTTPException as exc:
            raise AuthenticationError(
                message=str(exc.detail),
                error_code=ErrorCode.SESSION_EXPIRED,
                details={"hint": "Please log in again"}
            )

        if not login_data:
            raise AuthenticationError(
                message="Invalid or expired session",
                error_code=ErrorCode.SESSION_EXPIRED,
                details={"hint": "Please log in again"}
            )

        user_info = UserInfo(
            user_hash=login_data.user_hash,
            username=login_data.username or login_data.user_hash,
            user_type=login_data.user_type or "consumer",
        )

        if login_data.project_hash:
            project_info = ProjectInfo(
                project_hash=login_data.project_hash,
                project_name=login_data.project_name or "",
            )
        else:
            project_info = None

        user_group_names = list(login_data.groups or [])

        duration_ms = (time.monotonic() - _t_start) * 1000
        if response is not None:
            response.headers["X-Auth-Process-Time"] = f"{duration_ms:.3f}"
        return ValidateSessionResponse(
            success=True,
            valid=True,
            user=user_info,
            project=project_info,
            session={"created_at": None, "scope": login_data.scope or "project"},
            user_groups=user_group_names,
        )
    except Exception:
        duration_ms = (time.monotonic() - _t_start) * 1000
        if response is not None:
            response.headers["X-Auth-Process-Time"] = f"{duration_ms:.3f}"
        raise


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

    try:
        claims = JWTTokenHandler.decode_access_token(session_token)
        validate_enhanced_session(session_token)
        revoke_refresh_family(str(claims["family_id"]), reason="logout")
    except HTTPException as exc:
        raise AuthenticationError(
            message=str(exc.detail),
            error_code=ErrorCode.SESSION_EXPIRED,
        )

    # Clear access and refresh cookies with matching security attributes.
    response.delete_cookie(key=COOKIE_NAME, path="/", httponly=True, secure=True, samesite="strict")
    response.delete_cookie(key="refresh_token", path="/auth", httponly=True, secure=True, samesite="strict")
    return LogoutResponse(success=True, message="Logged out successfully")


@router.post("/refresh", response_model=LoginResponse)
@log_and_handle_errors(
    operation_name="refresh_token",
    activity_type=ActivityType.USER_LOGIN,
    log_success=False
)
async def refresh_token(
        response: Response,
        request: Request,
        refresh_token_value: Optional[str] = Form(None, alias="refresh_token"),
        log_context: LogContext = None
) -> LoginResponse:
    """
    Refresh JWT token and extend session.
    Creates a new token with updated expiration while maintaining the same session context.
    
    Returns:
        New session token with same user and project context
    """
    try:
        presented_refresh_token = extract_refresh_token_from_request(request, refresh_token_value)
        rotation = rotate_refresh_family(
            presented_refresh_token,
            get_user_by_hash_fn=get_user_by_hash,
            get_project_by_hash_fn=get_project_by_hash,
            get_user_groups_in_project_by_hash_fn=_route_refresh_groups,
            get_user_accessible_projects_fn=get_user_accessible_projects,
        )
    except HTTPException as exc:
        raise AuthenticationError(
            message=str(exc.detail),
            error_code=ErrorCode.SESSION_EXPIRED,
        )
    _set_token_pair_cookies(response, rotation.token_pair)
    return _login_response_from_rotation(rotation)


@router.post("/switch-project", response_model=SwitchProjectResponse)
@log_and_handle_errors(
    operation_name="switch_project",
    activity_type=ActivityType.USER_LOGIN,
    log_success=True
)
async def switch_project(
        response: Response,
        request: Request,
        project_hash: str = Form(...),
        refresh_token_value: Optional[str] = Form(None, alias="refresh_token"),
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
    try:
        access_claims = JWTTokenHandler.decode_access_token(session_token)
        current_session = validate_access_session(
            session_token,
            get_user_by_hash_fn=get_user_by_hash,
            get_project_by_hash_fn=get_project_by_hash,
            get_user_groups_in_project_by_hash_fn=_route_refresh_groups,
            get_user_accessible_projects_fn=get_user_accessible_projects,
        )
    except HTTPException as exc:
        raise AuthenticationError(
            message=str(exc.detail),
            error_code=ErrorCode.SESSION_INVALID
        )

    # Validate desired project exists & user has access
    new_project = get_project_by_hash(project_hash)
    if not new_project:
        raise NotFoundError(
            message=f"Project not found: {mask_uuid(project_hash)}",
            error_code=ErrorCode.PROJECT_NOT_FOUND
        )

    accessible = get_user_accessible_projects(current_session.user_id)
    if not any(p.project_hash == project_hash for p in accessible):
        raise AuthorizationError(
            message="Access denied to requested project",
            error_code=ErrorCode.PROJECT_ACCESS_DENIED,
            details={"project_hash": mask_uuid(project_hash)}
        )

    try:
        presented_refresh_token = extract_refresh_token_from_request(request, refresh_token_value)
        refresh_claims = JWTTokenHandler.decode_refresh_token(presented_refresh_token)
        if str(refresh_claims.get("family_id")) != str(access_claims.get("family_id")):
            raise HTTPException(status_code=401, detail="Refresh token does not match access token family")

        rotation = rotate_refresh_family(
            presented_refresh_token,
            target_project=new_project,
            get_user_by_hash_fn=get_user_by_hash,
            get_project_by_hash_fn=get_project_by_hash,
            get_user_groups_in_project_by_hash_fn=lambda user_id, _project_hash: get_user_groups_in_project(user_id, new_project.id),
            get_user_accessible_projects_fn=get_user_accessible_projects,
        )
    except HTTPException as exc:
        raise AuthenticationError(
            message=str(exc.detail),
            error_code=ErrorCode.SESSION_INVALID,
        )

    _set_token_pair_cookies(response, rotation.token_pair)

    project_info = ProjectInfo(
        project_hash=new_project.project_hash,
        project_name=new_project.project_name,
        project_description=new_project.project_description,
    )

    user_group_names = list(rotation.login_data.groups or [])

    return SwitchProjectResponse(
        success=True,
        message=f"Successfully switched to project: {new_project.project_name}",
        access_token=rotation.token_pair.access_token,
        refresh_token=rotation.token_pair.refresh_token,
        session_token=rotation.token_pair.session_token,
        token_type=rotation.token_pair.token_type,
        expires_in=rotation.token_pair.expires_in,
        refresh_expires_in=rotation.token_pair.refresh_expires_in,
        expires_at=rotation.token_pair.expires_at,
        refresh_expires_at=rotation.token_pair.refresh_expires_at,
        project=project_info,
        user_groups=user_group_names,
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
    check_username = username
    check_email = email

    if not check_username and not check_email:
        raise ValidationError(
            message="Username or email required",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"required_fields": ["username", "email"]}
        )

    username_available = None
    email_available = None

    if check_username:
        username_available = handle_db_operation(
            lambda: check_username_email_available(check_username),
            error_context="username availability check"
        )

    if check_email:
        email_available = handle_db_operation(
            lambda: check_username_email_available(check_email),
            error_context="email availability check"
        )

    return CheckAvailabilityResponse(
        success=True,
        username_available=username_available,
        email_available=email_available
    )
