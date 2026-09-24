"""
User Management Routes

Handles user profile management, updates, and access information
for the group-based multi-project authentication system.

Endpoints:
- GET /profile - Get current user's profile
- PUT /profile - Update current user's profile
- GET /access-summary - Get user's hierarchical access summary
- GET /list - List all users with filters (root/admin)
- GET /me/emails, POST /me/emails - List / add the caller's email addresses
- POST /me/emails/{email_id}/resend - Resend activation for the caller's pending email
- DELETE /me/emails/{email_id} - Remove one of the caller's email addresses
- POST /me/emails/{email_id}/primary - Make an activated email the primary one
- GET /{user_hash}/emails - Admin view of a user's email addresses (root/admin)
- POST /{user_hash}/emails/{email_id}/resend - Admin activation resend (root/admin)
- GET /search/query - Search users by username/email (root/admin)
- GET /{user_hash} - Get user details
- PUT /{user_hash}/status - Update user active status (root/admin)
- POST /{user_hash}/reset-password - Queue a password reset link (root/admin)
- DELETE /{user_hash} - Delete user (soft delete, root/admin)
- DELETE /{user_hash}/hard - Permanently hard delete a user (root only, deep clean)
- PATCH /{user_hash}/type - Change user type (root only)
- PUT /{user_hash} - Update user details (root/admin)

Route order matters: literal paths (/profile, /list, /me/...) are registered
before the /{user_hash} catch-alls, and main.py registers the /users/api-keys
router before this one.
"""

import logging
import json
import secrets
from datetime import datetime, timezone
from typing import Annotated, Optional, Dict, Any, List

from fastapi import APIRouter, Depends, Form, Path, Query, Request
from fastapi.security import HTTPAuthorizationCredentials

from src.Util.Models import (
    UserProfileResponse, UpdateProfileResponse, AccessSummaryResponse,
    ListUsersResponse, GetUserDetailsResponse, UpdateUserStatusResponse,
    ChangeUserTypeResponse, UserInfo, ProjectInfo, PaginationInfo, UpdateUserResponse
)
from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.decorators import log_and_handle_errors, log_operation_details
from src.Util.log_context_models import LogContext, OperationMetadata
from src.Util.activity_logger import ActivityType
from src.Util.error_handler import (
    AuthorizationError, ValidationError, NotFoundError, InternalError,
    ErrorCode, mask_uuid, create_profile_password_rejection_error
)
from src.Util.db_error_wrapper import handle_db_operation
from src.Util.admin_scope import AdminScope, require_user_in_scope, resolve_admin_scope, user_in_scope
from src.Util.db import (
    db_email,
    get_user_by_hash, update_user,
    get_user_accessible_projects, get_user_groups_for_user,
    list_users_with_access, count_users,
    is_root_user, get_user_groups_in_project_by_hash, get_user_effective_permissions,
    get_user_group_membership, get_user_type_info,
    get_user_type, get_project_by_hash, get_projects_for_user_group,
    update_user_type, get_project_by_id
)
from src.Util.auth_constants import EMAIL_RESEND_COOLDOWN_SECONDS
from src.Util.auth_lifecycle import revoke_user_auth_state, revoke_user_auth_state_except_current
from src.Util.email.rate_limit import EmailRateLimiter, RateLimitExceeded
from src.Util.email.route_support import (
    EmailIdempotencyPlan,
    client_ip,
    complete_idempotency,
    generic_accepted_response,
    hash_route_value,
    idempotency_kwargs,
    load_route_email_config,
    make_link_token_and_payload,
    prepare_idempotency,
    rate_limited_response,
    read_request_payload,
    user_agent,
)
from src.Util.email.security import hash_email, mask_email, normalize_email

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/users", tags=["User Management"])
security = HTTPBearerOrCookie()

# OpenAPI fragments for routes that read headers/bodies themselves.
_USER_HASH_DESCRIPTION = "Hash of the target user."
_EMAIL_ID_DESCRIPTION = "Email address row ID (`id` from the email list)."
_IDEMPOTENCY_KEY_HEADER_PARAMETER = {
    "name": "Idempotency-Key",
    "in": "header",
    "required": False,
    "schema": {"type": "string", "maxLength": 128, "pattern": "^[A-Za-z0-9._:-]{1,128}$"},
    "description": (
        "Optional client key. A repeat with the same key replays the stored `202` "
        "response without sending another email; malformed keys are ignored."
    ),
}
_ACCEPTED_202_RESPONSE = {
    "description": (
        "Neutral accepted body (`success`, `message`). The same body is returned for "
        "every outcome so callers cannot learn whether the address or row exists."
    ),
}
_EMAIL_RATE_LIMITED_429_RESPONSE = {
    "description": "Rate limited or resend cooldown active (`INT_7005`); see the `Retry-After` header.",
}
_ADD_EMAIL_SCHEMA = {
    "type": "object",
    "required": ["email"],
    "properties": {
        "email": {
            "type": "string",
            "format": "email",
            "description": "Address to add; trimmed and lower-cased before use.",
        },
    },
}

_PROFILE_PASSWORD_MUTATION_FIELDS = {
    "password",
    "current_password",
    "new_password",
    "password_confirmation",
    "password_hash",
}


def _submitted_profile_password_field(payload: Dict[str, Any], password: Optional[str]) -> Optional[str]:
    if password is not None:
        return "password"
    for field in _PROFILE_PASSWORD_MUTATION_FIELDS:
        if field in payload:
            return field
    return None


def _valid_email_address(value: str) -> bool:
    normalized = normalize_email(value)
    if not normalized or "@" not in normalized:
        return False
    local, domain = normalized.rsplit("@", 1)
    return bool(local and domain and "." in domain)


def _safe_prepare_email_idempotency(
    *,
    raw_key: str | None,
    scope: str,
    user_id: str | None,
    recipient_hash: bytes | None,
    body: dict[str, Any],
    config,
) -> EmailIdempotencyPlan:
    try:
        return prepare_idempotency(
            raw_key=raw_key,
            scope=scope,
            user_id=user_id,
            recipient_hash=recipient_hash,
            body=body,
            config=config,
        )
    except Exception:
        logger.warning("Email idempotency begin failed; continuing with generic route posture", exc_info=True)
        return EmailIdempotencyPlan(raw_key=None, scope=scope)


def _safe_complete_email_idempotency(plan: EmailIdempotencyPlan, *, email_message_id: str | None = None) -> None:
    try:
        complete_idempotency(plan, email_message_id=email_message_id)
    except Exception:
        logger.warning("Email idempotency complete failed", exc_info=True)


def _new_email_token_id() -> str:
    return f"elt-{secrets.token_hex(16)}"


def _new_email_message_id() -> str:
    return f"em-{secrets.token_hex(16)}"


def _check_email_send_rate_limit(*, request: Request, purpose: str, recipient_hash_hex_value: str, user_id: str | None = None):
    try:
        EmailRateLimiter().check_send_request(
            purpose=purpose,
            recipient_hash=recipient_hash_hex_value,
            user_id=user_id,
            ip_address=client_ip(request),
        )
    except RateLimitExceeded as exc:
        return rate_limited_response(exc)
    return None


def _check_resend_cooldown(*, recipient_hash_hex_value: str, purpose: str):
    try:
        EmailRateLimiter().check_resend_cooldown(recipient_hash_hex_value, purpose)
    except RateLimitExceeded as exc:
        return rate_limited_response(exc)
    return None


def _mark_resend_sent(*, recipient_hash_hex_value: str, purpose: str) -> None:
    try:
        EmailRateLimiter().mark_resend_sent(recipient_hash_hex_value, purpose)
    except Exception:
        logger.debug("Unable to mark email resend cooldown", exc_info=True)


def _safe_log_email_activity(
    *,
    user_id: str | None,
    activity_type: ActivityType,
    details: dict[str, Any],
    request: Request | None,
    target_user_id: str | None = None,
) -> None:
    try:
        from src.Util.activity_logger import ActivityLogger

        ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=activity_type.value,
            details=details,
            target_user_id=target_user_id,
            ip_address=client_ip(request),
            user_agent=user_agent(request),
        )
    except Exception:
        logger.debug("Email activity log failed", exc_info=True)


def _current_user_from_context(log_context: LogContext):
    return handle_db_operation(
        lambda: get_user_by_hash(log_context.user_hash),
        error_context="current user lookup",
        not_found_message=f"Current user not found: {mask_uuid(log_context.user_hash)}",
    )


def _require_admin_or_root(current_user) -> AdminScope:
    """The caller's admin scope; refuses callers that are neither root nor admin users.

    Pair it with ``require_user_in_scope`` once the target user is known: admin users
    may only manage themselves and users who reach one of their assigned projects.
    """
    scope = resolve_admin_scope(current_user.id)
    if not scope.is_admin:
        raise AuthorizationError(
            message="Admin or root access required",
            error_code=ErrorCode.ACCESS_DENIED,
        )
    return scope


def _owner_email_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "email": row.get("email_normalized"),
        "email_masked": row.get("email_masked") or mask_email(row.get("email_normalized") or ""),
        "status": row.get("status"),
        "is_primary": bool(row.get("is_primary")),
        "added_at": row.get("added_at"),
        "activated_at": row.get("activated_at"),
        "removed_at": row.get("removed_at"),
        "last_activation_sent_at": row.get("last_activation_sent_at"),
        "updated_at": row.get("updated_at"),
    }


def _admin_email_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "user_id": row.get("user_id"),
        "email_hash": row.get("email_hash"),
        "email_masked": row.get("email_masked"),
        "status": row.get("status"),
        "is_primary": bool(row.get("is_primary")),
        "added_at": row.get("added_at"),
        "activated_at": row.get("activated_at"),
        "removed_at": row.get("removed_at"),
        "last_activation_sent_at": row.get("last_activation_sent_at"),
        "updated_at": row.get("updated_at"),
    }


def _revoke_other_sessions_for_email_change(user_id: str, credentials: HTTPAuthorizationCredentials, reason: str) -> None:
    try:
        revoke_user_auth_state_except_current(
            user_id,
            current_access_token=credentials.credentials if credentials else None,
            reason=reason,
        )
    except Exception:
        logger.warning("Email identity session revocation failed", exc_info=True)


@router.get("/profile", response_model=UserProfileResponse)
@log_and_handle_errors(
    operation_name="get_user_profile",
    activity_type=ActivityType.USER_LOGIN,
    log_success=False
)
async def get_user_profile(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None
) -> UserProfileResponse:
    """Return the caller's own profile.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie); any user type.

    **Responses:** `200` with account fields, `user_type_info`, group
    memberships, and accessible projects with the caller's effective
    permissions in each; `401` when the access token is missing, invalid, or
    expired.
    """
    # Get user data
    user_data = handle_db_operation(
        lambda: get_user_by_hash(log_context.user_hash),
        error_context="user profile retrieval",
        not_found_message=f"User not found: {mask_uuid(log_context.user_hash)}"
    )
        
    # Get user type information (includes role assignments)
    user_type_info = get_user_type_info(user_data.id)

    # Get user's groups
    user_groups = get_user_groups_for_user(user_data.id)
    
    # Get user's accessible projects through group memberships
    user_projects = get_user_accessible_projects(user_data.id)
    
    # Format groups for response
    groups = []
    for group in user_groups:
        # Get membership details for this user in this group
        membership = get_user_group_membership(user_data.id, group.id)
        groups.append({
            "group_hash": group.group_hash,
            "group_name": group.group_name,
            "group_description": group.group_description,
            "assigned_at": membership.assigned_at if membership else None,
            "assigned_by": membership.assigned_by if membership else None
        })
    
    # Format projects for response
    projects = []
    for project in user_projects:
        # Get effective permissions for this user in this project
        effective_permissions = get_user_effective_permissions(user_data.id, project.id)
        permission_names = effective_permissions if effective_permissions else []
        
        projects.append(ProjectInfo(
            project_hash=project.project_hash,
            project_name=project.project_name,
            project_description=project.project_description,
            project_group=getattr(project, 'project_group_name', None),
            permissions=permission_names
        ))

    # Build the response with enhanced information
    return UserProfileResponse(
        user_hash=user_data.user_hash,
        username=user_data.username,
        email=user_data.email,
        user_type=user_data.user_type,
        user_type_info=user_type_info,  # Include detailed user type information
        created_at=user_data.created_at,
        updated_at=user_data.updated_at,
        last_login=user_data.last_login,
        is_active=user_data.is_active,
        groups=groups,  # Include group memberships
        projects=projects
    )


@router.put("/profile", response_model=UpdateProfileResponse)
@log_and_handle_errors(
    operation_name="update_user_profile",
    activity_type=ActivityType.USER_UPDATE,
    log_success=True
)
async def update_user_profile(
        request: Request,
        username: Optional[str] = Form(None, description="New username (must be unique)."),
        email: Optional[str] = Form(
            None,
            description="New value for the account's legacy `email` field (not verified; not a login identifier).",
        ),
        password: Optional[str] = Form(
            None,
            description="Not supported: any value is rejected with `400`; use `POST /auth/password/change`.",
        ),
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> UpdateProfileResponse:
    """
    Update the caller's own `username` and/or legacy `email` field.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie); any user type.

    **Request:** form fields (`application/x-www-form-urlencoded` or
    `multipart/form-data`); send at least one of `username`, `email`. `email`
    overwrites the account's compatibility `email` field directly: it is not
    verified, is not used for sign-in, and does not touch the addresses managed
    under `/users/me/emails`.

    **Responses:**
    - `200` — the updated user.
    - `400` — no field provided, or a password field was submitted
      (`password`, `current_password`, `new_password`, `password_confirmation`,
      `password_hash`); password changes must use `POST /auth/password/change`.
    - `409` — username already taken (`CONF_5004`).
    """
    payload = await read_request_payload(request)
    password_field = _submitted_profile_password_field(payload, password)
    if password_field is not None:
        raise create_profile_password_rejection_error(password_field)

    # Get current user
    current_user = handle_db_operation(
        lambda: get_user_by_hash(log_context.user_hash),
        error_context="user lookup",
        not_found_message=f"User not found: {mask_uuid(log_context.user_hash)}"
    )

    # Track changes
    changes = {}
    if username: changes['username'] = username
    if email: changes['email'] = email

    # Update user
    updated_user = handle_db_operation(
        lambda: update_user(
            current_user.id,
            username=username,
            email=email,
            password=None
        ),
        error_context="user profile update"
    )

    if not updated_user:
        from src.Util.error_handler import InternalError
        raise InternalError(
            message="Failed to update user profile",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "update_profile"}
        )

    # Log detailed changes
    if changes:
        log_operation_details(
            user_id=log_context.user_id,
            operation=OperationMetadata(
                operation_name="update_profile",
                target_resource=log_context.user_hash,
                target_resource_type="user",
                changes=changes
            ),
            log_context=log_context
        )

    # Build updated user info
    user_info = UserInfo(
        user_hash=updated_user.user_hash,
        username=updated_user.username,
        email=updated_user.email,
        user_type=getattr(updated_user, 'user_type', 'consumer'),
        created_at=updated_user.created_at,
        updated_at=updated_user.updated_at
    )

    return UpdateProfileResponse(
        success=True,
        message="Profile updated successfully",
        user=user_info
    )


@router.get("/access-summary", response_model=AccessSummaryResponse)
@log_and_handle_errors(
    operation_name="get_access_summary",
    activity_type=ActivityType.USER_LOGIN,
    log_success=False
)
async def get_user_access_summary(
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> AccessSummaryResponse:
    """
    Summarize the caller's group memberships, accessible projects, and effective permissions.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie); any user type.

    **Responses:** `200` with `access_summary`: `user`, `user_groups` (with
    per-group `projects_count`), `accessible_projects` (access groups and
    `effective_permissions` per project), `current_session`, and `summary`.
    `current_session` only carries the session's `project_hash` (other fields
    are `null`/empty) and `summary.is_admin` is always `false`.
    """
    user_data = get_user_by_hash(log_context.user_hash)
    if not user_data:
        raise NotFoundError(
            message=f"User not found: {mask_uuid(log_context.user_hash)}",
            error_code=ErrorCode.USER_NOT_FOUND
        )
        
    # Get user type information with role assignments
    user_type_info = get_user_type_info(user_data.id)

    # Get user's group memberships with hierarchical information
    user_groups = get_user_groups_for_user(user_data.id)

    # Get comprehensive access information through group-based access control
    accessible_projects = get_user_accessible_projects(user_data.id)

    # Build user groups list with membership details
    group_list = []
    for group in user_groups:
        # Get membership details for this user in this group
        membership = get_user_group_membership(user_data.id, group.id)
        
        # Get projects accessible through this group
        group_projects = get_projects_for_user_group(group.id)
        
        group_list.append({
            "group_hash": group.group_hash,
            "group_name": group.group_name,
            "group_description": group.group_description,
            "assigned_at": membership.assigned_at if membership else None,
            "assigned_by": membership.assigned_by if membership else None,
            "projects_count": len(group_projects) if group_projects else 0
        })

    # Build accessible projects list with effective permissions
    project_list = []
    for proj in accessible_projects:
        # Get user's effective permissions for this project
        effective_permissions = get_user_effective_permissions(user_data.id, proj.id)
        permission_names = effective_permissions if effective_permissions else []
        
        # Get user's group memberships for this project
        user_project_groups = get_user_groups_in_project_by_hash(user_data.id, proj.project_hash)
        
        project_groups = []
        for pg in user_project_groups:
            project_groups.append({
                "group_hash": pg.group_hash if hasattr(pg, 'group_hash') else '',
                "group_name": pg.group_name,
                "permissions": pg.permissions if hasattr(pg, 'permissions') else []
            })
        
        project_list.append({
            "project_hash": proj.project_hash,
            "project_name": proj.project_name,
            "project_description": proj.project_description,
            "access_groups": project_groups,
            "effective_permissions": permission_names
        })

    # Build comprehensive access summary
    access_summary = {
        "user": {
            "user_hash": user_data.user_hash,
            "username": user_data.username,
            "user_type": user_data.user_type,
            "user_type_details": user_type_info,
            "email": user_data.email
        },
        "user_groups": group_list,
        "accessible_projects": project_list,
        "current_session": {
            "project_hash": log_context.project_hash,
            "project_name": None,
            "permissions": [],
            "expires_at": None
        },
        "summary": {
            "total_groups": len(user_groups),
            "total_projects": len(accessible_projects) if accessible_projects else 0,
            "is_admin": False
        }
    }

    return AccessSummaryResponse(
        success=True,
        access_summary=access_summary
    )


@router.get("/list", response_model=ListUsersResponse)
@log_and_handle_errors(
    operation_name="list_users",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False
)
async def list_all_users(
        limit: Annotated[int, Query(description="Maximum number of users to fetch for this page.")] = 100,
        offset: Annotated[int, Query(description="Number of users to skip.")] = 0,
        sort_by: Annotated[str, Query(
            description="`username` (default), `created_at`, `email`, `user_type`, or `last_login`; other values sort by username.",
        )] = 'username',
        sort_order: Annotated[str, Query(description="`asc` (default) or `desc`; other values sort ascending.")] = 'asc',
        search: Annotated[Optional[str], Query(description="Substring match on username or email.")] = None,
        user_type_filter: Annotated[Optional[str], Query(description="Only this user type: `root`, `admin`, or `consumer`.")] = None,
        group_filter: Annotated[Optional[str], Query(description="Only members of this user group (group name or hash).")] = None,
        project_filter: Annotated[Optional[str], Query(description="Only users with access to this project (project name or hash).")] = None,
        include_inactive: Annotated[bool, Query(description="Also return deactivated users.")] = False,
        include_group_info: Annotated[bool, Query(description="Include each user's `groups`.")] = True,
        include_project_access: Annotated[bool, Query(
            description="Include each user's `projects` with effective permissions.",
        )] = True,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None) -> ListUsersResponse:
    """
    List users with filtering, sorting, and pagination.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root or admin user; consumers get `403`. Root
    sees all users; admins see themselves plus users who share at least one
    accessible project with them.

    **Responses:** `200` with `users`, `pagination`, and the applied `filters`.
    `pagination.total` counts only by `user_type_filter` and `include_inactive`
    (not `search`, group/project filters, or admin scoping), and admin
    scoping is applied after the page is fetched, so an admin's page can hold
    fewer than `limit` users.
    """
    # Check if user has permission to list users (root or admin)
    current_user = handle_db_operation(
        lambda: get_user_by_hash(log_context.user_hash),
        error_context="user lookup",
        not_found_message=f"User not found: {mask_uuid(log_context.user_hash)}"
    )

    # Only root users can see all users across projects
    # Admin users can only see users in their assigned projects
    is_root = is_root_user(current_user.id)
    if not is_root:
        user_type = get_user_type(current_user.id)
        if user_type != 'admin':
            raise AuthorizationError(
                message="Access denied: Admin privileges required",
                error_code=ErrorCode.ACCESS_DENIED
            )
        
        # If admin, we'll filter users based on their assigned projects later
        # For now, we get their assigned projects
        admin_projects = get_user_accessible_projects(current_user.id)
        admin_project_ids = [proj.id for proj in admin_projects] if admin_projects else []

    # Fetch users using stored procedure with aggregated group/project data
    all_users = handle_db_operation(
        lambda: list_users_with_access(
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_order=sort_order,
            search=search,
            user_type_filter=user_type_filter,
            group_filter=group_filter,
            project_filter=project_filter,
            include_inactive=include_inactive
        ),
        error_context="user list retrieval"
    )

    # Total count (basic, does not yet include group/project filters)
    total_count = handle_db_operation(
        lambda: count_users(
            user_type=user_type_filter,
            search=search,
            include_inactive=include_inactive
        ),
        error_context="user count"
    )

    users_list: List[Dict[str, Any]] = []
    for user in all_users:
        user_id = user["id"]

        # Skip users not in admin's projects if current user is admin
        if not is_root and user_id != current_user.id:
            user_projects_check = get_user_accessible_projects(user_id)
            user_project_ids = [proj.id for proj in user_projects_check] if user_projects_check else []
            if not any(pid in admin_project_ids for pid in user_project_ids):
                continue

        user_type_info = get_user_type_info(user_id)

        # Parse groups JSON returned from SP
        parsed_groups = []
        if include_group_info and user.get("groups_json"):
            parsed_groups = json.loads(user["groups_json"]) if isinstance(user["groups_json"], str) else user["groups_json"]

        # Parse projects JSON and add effective permissions if requested
        parsed_projects = []
        if include_project_access and user.get("projects_json"):
            raw_projects = json.loads(user["projects_json"]) if isinstance(user["projects_json"], str) else user["projects_json"]
            for proj in raw_projects:
                # Get project_id from project_hash for permission check
                project_data = get_project_by_hash(proj["project_hash"])
                if project_data:
                    effective_permissions = get_user_effective_permissions(user_id, project_data.id)
                    proj["permissions"] = effective_permissions if effective_permissions else []
                else:
                    proj["permissions"] = []
                parsed_projects.append(proj)

        users_list.append({
            "user_hash": user["user_hash"],
            "username": user["username"],
            "email": user["email"],
            "user_type": user["user_type"],
            "user_type_info": user_type_info,
            "created_at": user["created_at"],
            "last_login": user.get("last_login"),
            "is_active": user["is_active"],
            "groups": parsed_groups if include_group_info else [],
            "projects": parsed_projects if include_project_access else []
        })

    # Pagination info
    pagination = PaginationInfo(
        total=total_count,
        limit=limit,
        offset=offset,
        has_more=(offset + len(users_list)) < total_count
    )

    filters_info = {
        "user_type_filter": user_type_filter,
        "group_filter": group_filter,
        "project_filter": project_filter,
        "search": search,
        "include_inactive": include_inactive
    }

    return ListUsersResponse(
        success=True,
        users=users_list,
        pagination=pagination,
        filters=filters_info
    )


@router.get("/me/emails")
@log_and_handle_errors(
    operation_name="list_current_user_emails",
    activity_type=None,
    log_success=False,
)
async def list_current_user_emails(
        request: Request,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context = None,
) -> Dict[str, Any]:
    """List the caller's email addresses and their lifecycle state.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie); any user type.

    **Responses:** `200` with `emails`; each row has `id`, the full `email`,
    `email_masked`, `status` (`pending`, `activated`, or `suppressed`),
    `is_primary`, and timestamps. Removed addresses are omitted and the primary
    address comes first. Only `activated` addresses can be used to sign in.
    """

    rows = db_email.list_user_emails(log_context.user_id)
    return {
        "success": True,
        "emails": [_owner_email_row(row) for row in rows],
    }


@router.post(
    "/me/emails",
    responses={202: _ACCEPTED_202_RESPONSE, 429: _EMAIL_RATE_LIMITED_429_RESPONSE},
    openapi_extra={
        "parameters": [_IDEMPOTENCY_KEY_HEADER_PARAMETER],
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": _ADD_EMAIL_SCHEMA},
                "application/x-www-form-urlencoded": {"schema": _ADD_EMAIL_SCHEMA},
                "multipart/form-data": {"schema": _ADD_EMAIL_SCHEMA},
            },
        },
    },
)
@log_and_handle_errors(
    operation_name="add_current_user_email",
    activity_type=ActivityType.USER_EMAIL_ACTIVATION_REQUESTED,
    log_success=True,
)
async def add_current_user_email(
        request: Request,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context = None,
):
    """Add an email address to the caller's account and email it an activation link.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie); any user type.

    **Request:** `email` in a JSON body or as a form field
    (`application/x-www-form-urlencoded` or `multipart/form-data`). Optional
    `Idempotency-Key` header.

    **Responses:**
    - `202` — neutral body for every accepted outcome: new address (a fresh
      link is sent), already pending (earlier links are replaced), already
      activated or suppressed on this account (nothing is sent), or refused
      (e.g. the account already has five pending/activated addresses). The
      address stays `pending` until the emailed token is submitted to
      `POST /auth/email/verify`.
    - `400` — missing or malformed `email`.
    - `429` — rate limited; `Retry-After` is set.
    \f
    Link origin: the configured public base URL, else an allow-listed
    `X-Public-Base-Url` header relayed by a BFF, else the request origin.
    """

    payload = await read_request_payload(request)
    raw_email = str(payload.get("email") or "").strip()
    if not _valid_email_address(raw_email):
        raise ValidationError(
            message="A valid email is required",
            error_code=ErrorCode.INVALID_INPUT,
            details={"field": "email"},
        )

    config = load_route_email_config()
    normalized = normalize_email(raw_email)
    recipient_hash = hash_email(normalized, pepper=config.hash_pepper_bytes)
    recipient_hash_hex_value = recipient_hash.hex()

    limited = _check_email_send_rate_limit(
        request=request,
        purpose="email_activation",
        recipient_hash_hex_value=recipient_hash_hex_value,
        user_id=log_context.user_id,
    )
    if limited is not None:
        return limited

    plan = _safe_prepare_email_idempotency(
        raw_key=request.headers.get("idempotency-key"),
        scope="users.me.emails.add",
        user_id=log_context.user_id,
        recipient_hash=recipient_hash,
        body={"email": normalized, "purpose": "email_activation"},
        config=config,
    )
    if plan.replay_response is not None:
        return plan.replay_response

    generated, render_payload = make_link_token_and_payload(
        purpose="email_activation",
        config=config,
        request=request,
        recipient_email=normalized,
        recipient_masked=mask_email(normalized),
    )
    email_message_id = _new_email_message_id()
    row = None
    try:
        row = db_email.add_user_email_and_enqueue(
            user_email_id=f"uem-{secrets.token_hex(16)}",
            user_id=log_context.user_id,
            email_normalized=normalized,
            email_hash=recipient_hash,
            email_masked=mask_email(normalized),
            token_id=_new_email_token_id(),
            lookup_id=generated.lookup_id,
            token_hash=generated.token_hash,
            token_fingerprint=generated.token_fingerprint,
            token_expires_at=generated.expires_at,
            email_message_id=email_message_id,
            provider=config.provider,
            provider_idempotency_key=f"email-activation-{generated.lookup_id}",
            render_payload_ciphertext=render_payload,
            created_by=log_context.user_id,
            created_ip_hash=hash_route_value(client_ip(request), config),
            **idempotency_kwargs(plan),
        )
    except Exception:
        logger.warning("Add user email enqueue failed; returning generic accepted response", exc_info=True)

    _safe_complete_email_idempotency(
        plan,
        email_message_id=(row or {}).get("email_message_id") or email_message_id,
    )
    return generic_accepted_response()


@router.post(
    "/me/emails/{email_id}/resend",
    responses={202: _ACCEPTED_202_RESPONSE, 429: _EMAIL_RATE_LIMITED_429_RESPONSE},
    openapi_extra={"parameters": [_IDEMPOTENCY_KEY_HEADER_PARAMETER]},
)
@log_and_handle_errors(
    operation_name="resend_current_user_email_activation",
    activity_type=ActivityType.USER_EMAIL_ACTIVATION_RESENT,
    log_success=True,
)
async def resend_current_user_email_activation(
        email_id: Annotated[str, Path(description=_EMAIL_ID_DESCRIPTION)],
        request: Request,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context = None,
):
    """Resend the activation link for one of the caller's pending email addresses.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie); any user type.

    **Request:** no body. Optional `Idempotency-Key` header.

    **Responses:**
    - `202` — neutral body, also when `email_id` is unknown, not the caller's,
      or no longer pending; nothing is sent in those cases.
    - `429` — rate limited, or an activation email for this address was sent
      within the resend cooldown; `Retry-After` is set.
    """

    config = load_route_email_config()
    recipient_hash = hash_route_value(f"{log_context.user_id}:{email_id}", config)
    recipient_hash_hex_value = recipient_hash.hex() if recipient_hash else "unknown"
    limited = _check_email_send_rate_limit(
        request=request,
        purpose="email_activation",
        recipient_hash_hex_value=recipient_hash_hex_value,
        user_id=log_context.user_id,
    )
    if limited is not None:
        return limited
    cooldown = _check_resend_cooldown(
        recipient_hash_hex_value=recipient_hash_hex_value,
        purpose="email_activation",
    )
    if cooldown is not None:
        return cooldown

    plan = _safe_prepare_email_idempotency(
        raw_key=request.headers.get("idempotency-key"),
        scope="users.me.emails.resend",
        user_id=log_context.user_id,
        recipient_hash=recipient_hash,
        body={"email_id": email_id, "purpose": "email_activation"},
        config=config,
    )
    if plan.replay_response is not None:
        return plan.replay_response

    generated, render_payload = make_link_token_and_payload(
        purpose="email_activation",
        config=config,
        request=request,
    )
    email_message_id = _new_email_message_id()
    row = None
    try:
        row = db_email.resend_user_email_activation(
            user_id=log_context.user_id,
            user_email_id=email_id,
            token_id=_new_email_token_id(),
            lookup_id=generated.lookup_id,
            token_hash=generated.token_hash,
            token_fingerprint=generated.token_fingerprint,
            token_expires_at=generated.expires_at,
            email_message_id=email_message_id,
            provider=config.provider,
            provider_idempotency_key=f"email-activation-resend-{generated.lookup_id}",
            render_payload_ciphertext=render_payload,
            created_ip_hash=hash_route_value(client_ip(request), config),
            cooldown_seconds=EMAIL_RESEND_COOLDOWN_SECONDS,
            **idempotency_kwargs(plan),
        )
    except Exception:
        logger.warning("Resend activation enqueue failed; returning generic accepted response", exc_info=True)

    if row and row.get("email_message_id"):
        _mark_resend_sent(recipient_hash_hex_value=recipient_hash_hex_value, purpose="email_activation")
    _safe_complete_email_idempotency(
        plan,
        email_message_id=(row or {}).get("email_message_id") or email_message_id,
    )
    return generic_accepted_response()


@router.delete("/me/emails/{email_id}")
@log_and_handle_errors(
    operation_name="remove_current_user_email",
    activity_type=ActivityType.USER_EMAIL_REMOVED,
    log_success=True,
)
async def remove_current_user_email(
        email_id: Annotated[str, Path(description=_EMAIL_ID_DESCRIPTION)],
        request: Request,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context = None,
) -> Dict[str, Any]:
    """Remove one of the caller's email addresses.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie); any user type.

    **Request:** no body.

    **Effects:** unused activation links for the address are revoked. If it
    was the primary address, the earliest-activated remaining address becomes
    primary (or the account is left without one). All of the caller's other
    sessions and refresh tokens are revoked; the current session stays valid.

    **Responses:** `200` with `email_id` and `new_primary_email_id` (or
    `null`); `404` (`NF_4004`) when `email_id` is not one of the caller's
    current addresses, in which case nothing is removed or revoked.
    """
    row = db_email.remove_user_email(
        user_id=log_context.user_id,
        user_email_id=email_id,
        removed_by=log_context.user_id,
    )
    _revoke_other_sessions_for_email_change(log_context.user_id, credentials, "email_removed")
    return {
        "success": True,
        "message": "Email removed successfully",
        "email_id": email_id,
        "new_primary_email_id": (row or {}).get("new_primary_email_id"),
    }


@router.post("/me/emails/{email_id}/primary")
@log_and_handle_errors(
    operation_name="set_current_user_primary_email",
    activity_type=ActivityType.USER_EMAIL_PRIMARY_CHANGED,
    log_success=True,
)
async def set_current_user_primary_email(
        email_id: Annotated[str, Path(description=_EMAIL_ID_DESCRIPTION)],
        request: Request,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context = None,
) -> Dict[str, Any]:
    """Make one of the caller's activated email addresses the primary address.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie); any user type.

    **Request:** no body.

    **Effects:** the account's `email` field becomes this address, and all of
    the caller's other sessions and refresh tokens are revoked; the current
    session stays valid.

    **Responses:** `200` with `email_id` and `status` (`primary_changed`);
    `409` (`CONF_5005`) when the address is not `activated`, has been removed,
    or is not owned by the caller, in which case no session is revoked.
    """
    row = db_email.set_primary_user_email(
        user_id=log_context.user_id,
        user_email_id=email_id,
    )
    _revoke_other_sessions_for_email_change(log_context.user_id, credentials, "email_primary_changed")
    return {
        "success": True,
        "message": "Primary email updated successfully",
        "email_id": email_id,
        "status": (row or {}).get("lifecycle_status", "primary_changed"),
    }


@router.get("/{user_hash}/emails")
@log_and_handle_errors(
    operation_name="admin_list_user_emails",
    activity_type=None,
    log_success=False,
)
async def admin_list_user_emails(
        user_hash: Annotated[str, Path(description=_USER_HASH_DESCRIPTION)],
        request: Request,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context = None,
) -> Dict[str, Any]:
    """List a user's email addresses for administration, with addresses masked.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root or admin user; others get `403`. Admins
    may only view themselves and users who reach one of the projects they are
    assigned to administer; other users return `403`.

    **Responses:** `200` with `user_hash` and `emails`; each row has `id`,
    `user_id`, `email_masked`, `email_hash` (hex), `status`, `is_primary`, and
    timestamps. Removed addresses are included; plain addresses are never
    returned. `404` for an unknown or inactive `user_hash`.
    """
    current_user = _current_user_from_context(log_context)
    scope = _require_admin_or_root(current_user)
    target_user = handle_db_operation(
        lambda: get_user_by_hash(user_hash),
        error_context="target user email lookup",
        not_found_message=f"User not found: {mask_uuid(user_hash)}",
    )
    require_user_in_scope(scope, target_user)
    rows = db_email.list_admin_user_emails(target_user.id)
    return {
        "success": True,
        "user_hash": target_user.user_hash,
        "emails": [_admin_email_row(row) for row in rows],
    }


@router.post(
    "/{user_hash}/emails/{email_id}/resend",
    responses={202: _ACCEPTED_202_RESPONSE, 429: _EMAIL_RATE_LIMITED_429_RESPONSE},
)
@log_and_handle_errors(
    operation_name="admin_resend_user_email_activation",
    activity_type=ActivityType.USER_EMAIL_ACTIVATION_RESENT,
    log_success=True,
)
async def admin_resend_user_email_activation(
        user_hash: Annotated[str, Path(description=_USER_HASH_DESCRIPTION)],
        email_id: Annotated[str, Path(description=_EMAIL_ID_DESCRIPTION)],
        request: Request,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context = None,
):
    """Resend the activation link for a user's pending email address, as an administrator.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root or admin user; others get `403`. Admins
    may only act on themselves and users who reach one of the projects they are
    assigned to administer; other users return `403`.

    **Request:** no body; `Idempotency-Key` is not supported on this route.

    **Responses:**
    - `202` — neutral body, also when `email_id` is unknown, belongs to
      another user, or is no longer pending; nothing is sent in those cases.
    - `403` — not root/admin, or the user is outside the admin's projects.
    - `404` — unknown or inactive `user_hash`.
    - `429` — rate limited, or an activation email for this address was sent
      within the resend cooldown; `Retry-After` is set.
    """
    current_user = _current_user_from_context(log_context)
    scope = _require_admin_or_root(current_user)
    target_user = handle_db_operation(
        lambda: get_user_by_hash(user_hash),
        error_context="target user email resend lookup",
        not_found_message=f"User not found: {mask_uuid(user_hash)}",
    )
    require_user_in_scope(scope, target_user)

    config = load_route_email_config()
    recipient_hash = hash_route_value(f"{target_user.id}:{email_id}", config)
    recipient_hash_hex_value = recipient_hash.hex() if recipient_hash else "unknown"
    limited = _check_email_send_rate_limit(
        request=request,
        purpose="email_activation",
        recipient_hash_hex_value=recipient_hash_hex_value,
        user_id=current_user.id,
    )
    if limited is not None:
        return limited
    cooldown = _check_resend_cooldown(
        recipient_hash_hex_value=recipient_hash_hex_value,
        purpose="email_activation",
    )
    if cooldown is not None:
        return cooldown

    generated, render_payload = make_link_token_and_payload(
        purpose="email_activation",
        config=config,
        request=request,
    )
    row = None
    try:
        row = db_email.resend_user_email_activation(
            user_id=target_user.id,
            user_email_id=email_id,
            token_id=_new_email_token_id(),
            lookup_id=generated.lookup_id,
            token_hash=generated.token_hash,
            token_fingerprint=generated.token_fingerprint,
            token_expires_at=generated.expires_at,
            email_message_id=_new_email_message_id(),
            provider=config.provider,
            provider_idempotency_key=f"admin-email-resend-{generated.lookup_id}",
            render_payload_ciphertext=render_payload,
            created_ip_hash=hash_route_value(client_ip(request), config),
            cooldown_seconds=EMAIL_RESEND_COOLDOWN_SECONDS,
        )
    except Exception:
        logger.warning("Admin email activation resend failed; returning generic accepted response", exc_info=True)

    if row and row.get("email_message_id"):
        _mark_resend_sent(recipient_hash_hex_value=recipient_hash_hex_value, purpose="email_activation")
    return generic_accepted_response()


@router.get("/{user_hash}", response_model=GetUserDetailsResponse)
@log_and_handle_errors(
    operation_name="get_user_details",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False
)
async def get_user_details(
        user_hash: Annotated[str, Path(description=_USER_HASH_DESCRIPTION)],
        include_group_hierarchy: Annotated[bool, Query(description="Add `projects_count` to each group.")] = True,
        include_permission_details: Annotated[bool, Query(
            description="Add `effective_permissions` and `access_groups` to each project.",
        )] = True,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None) -> GetUserDetailsResponse:
    """
    Get a user's account fields, type info, group memberships, and accessible projects.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie). Any user may read their own record. Root may read
    any user; admins may read users who share at least one accessible project
    with them; everyone else gets `403`.

    **Responses:** `200` with `user`; `403` outside the caller's scope; `404`
    for an unknown or inactive `user_hash`.
    """
    # Get current user
    current_user = handle_db_operation(
        lambda: get_user_by_hash(log_context.user_hash),
        error_context="current user lookup",
        not_found_message=f"Current user not found: {mask_uuid(log_context.user_hash)}"
    )

    # Get requested user
    target_user = handle_db_operation(
        lambda: get_user_by_hash(user_hash),
        error_context="target user lookup",
        not_found_message=f"User not found: {mask_uuid(user_hash)}"
    )

    # Check access permissions based on user type
    is_root = is_root_user(current_user.id)
    is_own_profile = current_user.user_hash == target_user.user_hash
    
    if not is_own_profile and not is_root:
        # Admin users can only view users in their assigned projects
        user_type = get_user_type(current_user.id)
        if user_type != 'admin':
            raise AuthorizationError(
                message="Access denied",
                error_code=ErrorCode.ACCESS_DENIED
            )
        
        # Check if target user is in one of the admin's projects
        admin_projects = get_user_accessible_projects(current_user.id)
        target_user_projects = get_user_accessible_projects(target_user.id)
        
        admin_project_hashes = [p.project_hash for p in admin_projects]
        target_project_hashes = [p.project_hash for p in target_user_projects]
        
        if not any(ph in admin_project_hashes for ph in target_project_hashes):
            raise AuthorizationError(
                message="Access denied: User not in your projects",
                error_code=ErrorCode.ACCESS_DENIED,
                details={"target_user": mask_uuid(user_hash)}
            )

    # Get user type information with role assignments
    user_type_info = get_user_type_info(target_user.id)
    
    # Get user's group memberships with hierarchical information if requested
    user_groups = get_user_groups_for_user(target_user.id)

    # Get user's accessible projects through group-based access
    accessible_projects = get_user_accessible_projects(target_user.id)

    # Build user groups list with membership details
    group_list = []
    for group in user_groups:
        # Get membership details for this user in this group
        membership = get_user_group_membership(target_user.id, group.id)
        
        group_data = {
            "group_hash": group.group_hash,
            "group_name": group.group_name,
            "group_description": group.group_description,
            "assigned_at": membership.assigned_at if membership else None,
            "assigned_by": membership.assigned_by if membership else None
        }
        
        # Add hierarchical information if requested
        if include_group_hierarchy:
            # Get projects accessible through this group
            group_projects = get_projects_for_user_group(group.id)
            group_data["projects_count"] = len(group_projects) if group_projects else 0
            
            # If relevant, we could add parent/child group relationships here
            # This would require adding hierarchical group queries to the database module
            
        group_list.append(group_data)

    # Build accessible projects list with detailed permissions
    project_list = []
    for proj in accessible_projects:
        project_data = {
            "project_hash": proj.project_hash,
            "project_name": proj.project_name,
            "project_description": proj.project_description
        }
        
        # Get effective permissions for this project
        if include_permission_details:
            # Get user's effective permissions for this project
            effective_permissions = get_user_effective_permissions(target_user.id, proj.id)
            permission_names = effective_permissions if effective_permissions else []
            project_data["effective_permissions"] = permission_names
            
            # Get user's group memberships for this project
            user_project_groups = get_user_groups_in_project_by_hash(target_user.id, proj.project_hash)
            
            # Format project groups
            project_groups = []
            for pg in user_project_groups:
                project_groups.append({
                    "group_hash": pg.group_hash if hasattr(pg, 'group_hash') else '',
                    "group_name": pg.group_name,
                    "permissions": pg.permissions if hasattr(pg, 'permissions') else []
                })
                
            project_data["access_groups"] = project_groups
            
        project_list.append(project_data)

    # Format the response with comprehensive user details
    user_details = {
        "user_hash": target_user.user_hash,
        "username": target_user.username,
        "email": target_user.email,
        "user_type": target_user.user_type,
        "user_type_info": user_type_info,
        "created_at": target_user.created_at,
        "updated_at": target_user.updated_at,
        "last_login": target_user.last_login,
        "is_active": target_user.is_active,
        "groups": group_list,
        "projects": project_list
    }

    return GetUserDetailsResponse(success=True, user=user_details)


@router.put("/{user_hash}/status", response_model=UpdateUserStatusResponse)
@log_and_handle_errors(
    operation_name="update_user_status",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True
)
async def update_user_status(
        user_hash: Annotated[str, Path(description=_USER_HASH_DESCRIPTION)],
        is_active: Annotated[bool, Query(description="`true` to activate, `false` to deactivate.")],
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> UpdateUserStatusResponse:
    """
    Activate or deactivate a user account.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root or admin user; consumers get `403`.
    Admins may only change users who share at least one accessible project with
    them, and may not deactivate root users.

    **Request:** `is_active` is a required query parameter; there is no body.

    **Effects:** deactivation revokes the user's sessions, refresh tokens, and
    cached auth state.

    **Responses:**
    - `200` — new status.
    - `400` — deactivating your own account.
    - `403` — not root/admin, target outside the admin's projects, or an admin
      deactivating a root user.
    - `404` — unknown or inactive `user_hash`. Inactive users are not found, so
      this endpoint cannot currently reactivate an account.
    """
    # Get current user
    current_user = handle_db_operation(
        lambda: get_user_by_hash(log_context.user_hash),
        error_context="current user lookup",
        not_found_message=f"Current user not found: {mask_uuid(log_context.user_hash)}"
    )
        
    # Get target user
    target_user = handle_db_operation(
        lambda: get_user_by_hash(user_hash),
        error_context="target user lookup",
        not_found_message=f"User not found: {mask_uuid(user_hash)}"
    )
        
    # Check permissions based on user type and hierarchical access
    is_root = is_root_user(current_user.id)
    
    if not is_root:
        # Only admin users can change user status
        user_type = get_user_type(current_user.id)
        if user_type != 'admin':
            raise AuthorizationError(
                message="Access denied: Admin privileges required",
                error_code=ErrorCode.ACCESS_DENIED
            )
            
        # Admin users can only manage users in their assigned projects
        admin_projects = get_user_accessible_projects(current_user.id)
        target_user_projects = get_user_accessible_projects(target_user.id)
        
        admin_project_hashes = [p.project_hash for p in admin_projects]
        target_project_hashes = [p.project_hash for p in target_user_projects]
        
        if not any(ph in admin_project_hashes for ph in target_project_hashes):
            raise AuthorizationError(
                message="Access denied: User not in your projects",
                error_code=ErrorCode.ACCESS_DENIED,
                details={"target_user": mask_uuid(user_hash)}
            )

    # Prevent root users from being deactivated by non-root users
    if target_user.user_type == 'root' and not is_active and not is_root:
        raise AuthorizationError(
            message="Cannot deactivate root users",
            error_code=ErrorCode.ACCESS_DENIED
        )
        
    # Prevent self-deactivation
    if current_user.user_hash == target_user.user_hash and not is_active:
        raise ValidationError(
            message="Cannot deactivate your own account",
            error_code=ErrorCode.INVALID_INPUT
        )

    # Update user status
    update_result = handle_db_operation(
        lambda: update_user(
            user_id=target_user.id,
            is_active=is_active
        ),
        error_context="user status update"
    )

    if not update_result:
        from src.Util.error_handler import InternalError
        raise InternalError(
            message="Failed to update user status",
            error_code=ErrorCode.INTERNAL_ERROR
        )
        
    # If deactivating user, handle cleaning up their active sessions and cache
    if not is_active:
        from src.Util.db import invalidate_user_sessions
        from src.Util.cache_manager import cache_manager
        
        # Invalidate sessions from Redis
        revoke_user_auth_state(target_user.id, reason="user_deactivated")
        invalidate_user_sessions(target_user.id)
        
        # Invalidate all cached data including cached sessions
        cache_manager.invalidate_user_cache(target_user.id)

    # Log the activity with enhanced details for audit trail
    log_operation_details(
        user_id=log_context.user_id,
        operation=OperationMetadata(
            operation_name="update_user_status",
            target_resource=user_hash,
            target_resource_type="user",
            changes={"is_active": is_active},
            additional_data={
                "target_username": target_user.username,
                "changed_by": current_user.username
            }
        ),
        log_context=log_context
    )

    return UpdateUserStatusResponse(
        success=True,
        message=f"User {target_user.username} has been {'activated' if is_active else 'deactivated'}",
        user_hash=target_user.user_hash,
        is_active=is_active
    )


@router.post(
    "/{user_hash}/reset-password",
    responses={429: {"description": "Rate limited (`INT_7005`); see the `Retry-After` header."}},
)
@log_and_handle_errors(
    operation_name="reset_user_password",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True
)
async def reset_user_password(
        user_hash: Annotated[str, Path(description=_USER_HASH_DESCRIPTION)],
        request: Request,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> Dict[str, Any]:
    """
    Queue a password-reset link to a user's activated email address.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root or admin user; consumers get `403`.
    Admins may only reset themselves and users who reach one of the projects
    they are assigned to administer.

    **Request:** no body. No password is set or returned: the user finishes
    the reset by submitting the emailed token to `POST /auth/password/reset`.
    The link goes to the primary activated address, else the earliest-activated
    one.

    **Responses:**
    - `200` — accepted. `reset_data.has_delivery_target` is `false` when the
      user has no activated address (nothing is sent). The response never
      includes the token, link, or full address.
    - `400` — the target is a root user.
    - `403` — not root/admin, or the user is outside the admin's projects.
    - `404` — unknown or inactive `user_hash`.
    - `429` — rate limited; `Retry-After` is set.
    """
    # Get current user
    current_user = handle_db_operation(
        lambda: get_user_by_hash(log_context.user_hash),
        error_context="current user lookup",
        not_found_message=f"Current user not found: {mask_uuid(log_context.user_hash)}"
    )

    # Check admin permissions
    scope = resolve_admin_scope(current_user.id)
    if not scope.is_admin:
        raise AuthorizationError(
            message="Admin permission required to reset passwords",
            error_code=ErrorCode.ACCESS_DENIED
        )

    # Get target user
    target_user = handle_db_operation(
        lambda: get_user_by_hash(user_hash),
        error_context="target user lookup",
        not_found_message=f"User not found: {mask_uuid(user_hash)}"
    )

    # Prevent resetting root user passwords
    if target_user.user_type == 'root':
        raise ValidationError(
            message="Cannot reset root user passwords",
            error_code=ErrorCode.INVALID_INPUT
        )

    # Admin users only manage users in the projects they are assigned to
    require_user_in_scope(scope, target_user)

    # The shared assert_password_policy(...) gate is enforced when this
    # admin_password_reset link is consumed by /auth/password/reset; this
    # request only queues a hash-only reset link and never sets a password.

    config = load_route_email_config()
    recipient_hash = hash_route_value(target_user.id, config)
    limited = _check_email_send_rate_limit(
        request=request,
        purpose="admin_password_reset",
        recipient_hash_hex_value=recipient_hash.hex() if recipient_hash else "unknown",
        user_id=current_user.id,
    )
    if limited is not None:
        return limited

    generated, render_payload = make_link_token_and_payload(
        purpose="admin_password_reset",
        config=config,
        request=request,
    )
    email_message_id = _new_email_message_id()
    row = db_email.enqueue_admin_password_reset_link(
        target_user_id=target_user.id,
        created_by=current_user.id,
        token_id=_new_email_token_id(),
        lookup_id=generated.lookup_id,
        token_hash=generated.token_hash,
        token_fingerprint=generated.token_fingerprint,
        token_expires_at=generated.expires_at,
        email_message_id=email_message_id,
        provider=config.provider,
        provider_idempotency_key=f"admin-password-reset-{generated.lookup_id}",
        render_payload_ciphertext=render_payload,
        created_ip_hash=hash_route_value(client_ip(request), config),
    )

    _safe_log_email_activity(
        user_id=current_user.id,
        activity_type=ActivityType.ADMIN_PASSWORD_RESET_REQUESTED,
        details={
            "action": "admin_password_reset_requested",
            "target_user_hash": target_user.user_hash,
            "email_message_id": (row or {}).get("email_message_id"),
            "has_delivery_target": bool((row or {}).get("user_email_id")),
        },
        request=request,
        target_user_id=target_user.id,
    )

    # Log the activity
    log_operation_details(
        user_id=log_context.user_id,
        operation=OperationMetadata(
            operation_name="reset_user_password",
            target_resource=user_hash,
            target_resource_type="user",
            additional_data={
                "target_username": target_user.username,
                "reset_by": current_user.username
            }
        ),
        log_context=log_context
    )

    return {
        "success": True,
        "message": "Password reset link request accepted",
        "user": {
            "user_hash": target_user.user_hash,
            "username": target_user.username,
        },
        "reset_data": {
            "expires_at": generated.expires_at.isoformat(),
            "delivery_status": "accepted",
            "has_delivery_target": bool((row or {}).get("user_email_id")),
        },
        "instructions": "If the target user has an activated email, a secure reset link was queued for delivery."
    }


@router.delete("/{user_hash}")
@log_and_handle_errors(
    operation_name="delete_user",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True
)
async def delete_user_endpoint(
        user_hash: Annotated[str, Path(description=_USER_HASH_DESCRIPTION)],
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> Dict[str, Any]:
    """
    Soft-delete a user: deactivate the account and its group memberships.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root or admin user; consumers get `403`.
    Root may delete any other user. Admins may delete non-root users who share
    at least one accessible project with them.

    **Request:** no body. The user row is kept (see `DELETE /users/{user_hash}/hard`
    for permanent removal); sessions, refresh tokens, and cached auth state are
    revoked.

    **Responses:**
    - `200` — deleted (`user_hash`, `username`, `deleted_at`).
    - `400` — deleting your own account.
    - `403` — not root/admin, admin targeting a root user, or target outside
      the admin's projects.
    - `404` — unknown or already inactive `user_hash`.
    - For a user with no active group memberships the request currently
      returns `500` even though the account is deactivated.
    """
    from src.Util.db import delete_user
    
    # Get current user
    current_user = handle_db_operation(
        lambda: get_user_by_hash(log_context.user_hash),
        error_context="current user lookup",
        not_found_message=f"Current user not found: {mask_uuid(log_context.user_hash)}"
    )

    # Check admin permissions
    is_root = is_root_user(current_user.id)
    user_type = get_user_type(current_user.id)
    
    if not is_root and user_type != 'admin':
        raise AuthorizationError(
            message="Admin permission required to delete users",
            error_code=ErrorCode.ACCESS_DENIED
        )

    # Get target user
    target_user = handle_db_operation(
        lambda: get_user_by_hash(user_hash),
        error_context="target user lookup",
        not_found_message=f"User not found: {mask_uuid(user_hash)}"
    )

    # Prevent self-deletion
    if current_user.user_hash == target_user.user_hash:
        raise ValidationError(
            message="Cannot delete your own account",
            error_code=ErrorCode.INVALID_INPUT
        )

    # Prevent deleting root users by non-root users
    if target_user.user_type == 'root' and not is_root:
        raise AuthorizationError(
            message="Cannot delete root users",
            error_code=ErrorCode.ACCESS_DENIED
        )

    # Admin users can only delete users in their assigned projects
    if not is_root:
        admin_projects = get_user_accessible_projects(current_user.id)
        target_user_projects = get_user_accessible_projects(target_user.id)
        
        admin_project_hashes = [p.project_hash for p in admin_projects]
        target_project_hashes = [p.project_hash for p in target_user_projects]
        
        if not any(ph in admin_project_hashes for ph in target_project_hashes):
            raise AuthorizationError(
                message="Access denied: User not in your projects",
                error_code=ErrorCode.ACCESS_DENIED,
                details={"target_user": mask_uuid(user_hash)}
            )

    # Perform soft delete
    success = handle_db_operation(
        lambda: delete_user(target_user.id, deleted_by=current_user.id),
        error_context="user deletion"
    )

    if not success:
        from src.Util.error_handler import InternalError
        raise InternalError(
            message="Failed to delete user",
            error_code=ErrorCode.INTERNAL_ERROR
        )

    # Invalidate user sessions and cache
    from src.Util.db import invalidate_user_sessions
    from src.Util.cache_manager import cache_manager
    
    revoke_user_auth_state(target_user.id, reason="user_deleted")
    invalidate_user_sessions(target_user.id)
    cache_manager.invalidate_user_cache(target_user.id)

    # Log the activity
    log_operation_details(
        user_id=log_context.user_id,
        operation=OperationMetadata(
            operation_name="delete_user",
            target_resource=user_hash,
            target_resource_type="user",
            additional_data={
                "target_username": target_user.username,
                "deleted_by": current_user.username
            }
        ),
        log_context=log_context
    )

    return {
        "success": True,
        "message": f"User '{target_user.username}' has been deleted",
        "user_hash": target_user.user_hash,
        "username": target_user.username,
        "deleted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }


@router.delete("/{user_hash}/hard")
@log_and_handle_errors(
    operation_name="hard_delete_user",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True
)
async def hard_delete_user_endpoint(
        user_hash: Annotated[str, Path(description="Hash of the user to delete permanently (active or inactive).")],
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> Dict[str, Any]:
    """
    Permanently delete a user account and everything it owns (irreversible).

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root user; others get `403`.

    **Request:** no body. Unlike `DELETE /users/{user_hash}`, the user row is
    removed; owned and identity data go with it through foreign-key cascades,
    and the user's email addresses are freed for re-registration. Shared
    resources the user created (projects, user groups) are kept with the
    ownership cleared. Works on already soft-deleted users, and any other user
    (including root) can be targeted. Sessions and cached auth state are
    revoked.

    **Responses:**
    - `200` — deleted, with a `removed` summary.
    - `400` — deleting your own account.
    - `403` — caller is not root.
    - `404` — unknown `user_hash`.
    """
    from src.Util.db import hard_delete_user, invalidate_user_sessions
    from src.Util.cache_manager import cache_manager

    # Get current user
    current_user = handle_db_operation(
        lambda: get_user_by_hash(log_context.user_hash),
        error_context="current user lookup",
        not_found_message=f"Current user not found: {mask_uuid(log_context.user_hash)}"
    )

    # ROOT only (stricter than the soft delete, which also allows admins)
    if not is_root_user(current_user.id):
        raise AuthorizationError(
            message="Root permission required to permanently delete users",
            error_code=ErrorCode.ACCESS_DENIED
        )

    # Get target user (include_inactive=True so soft-deleted users can also be purged)
    target_user = handle_db_operation(
        lambda: get_user_by_hash(user_hash, include_inactive=True),
        error_context="target user lookup",
        not_found_message=f"User not found: {mask_uuid(user_hash)}"
    )

    # Prevent self-deletion (only guard; any other target, including root, is allowed)
    if current_user.user_hash == target_user.user_hash:
        raise ValidationError(
            message="Cannot permanently delete your own account",
            error_code=ErrorCode.INVALID_INPUT
        )

    # Capture a pre-deletion snapshot for the audit log (rows are gone after delete)
    pre_username = target_user.username
    pre_user_type = target_user.user_type
    email_count = handle_db_operation(
        lambda: len(db_email.list_user_emails(target_user.id) or []),
        error_context="hard delete email snapshot",
        default_return=0
    )

    # Perform hard delete
    deleted = handle_db_operation(
        lambda: hard_delete_user(target_user.id, deleted_by=current_user.id),
        error_context="user hard deletion"
    )

    if not deleted:
        # Idempotency: the user disappeared between lookup and delete
        raise NotFoundError(
            message=f"User not found: {mask_uuid(user_hash)}",
            error_code=ErrorCode.USER_NOT_FOUND
        )

    # Revoke auth state, sessions, and cache (clears any lingering Redis/derived state)
    revoke_user_auth_state(target_user.id, reason="user_hard_deleted")
    invalidate_user_sessions(target_user.id)
    cache_manager.invalidate_user_cache(target_user.id)

    # Log the activity
    log_operation_details(
        user_id=log_context.user_id,
        operation=OperationMetadata(
            operation_name="hard_delete_user",
            target_resource=user_hash,
            target_resource_type="user",
            additional_data={
                "target_username": pre_username,
                "target_user_type": pre_user_type,
                "emails_unlinked": email_count,
                "deleted_by": current_user.username,
                "delete_mode": "hard"
            }
        ),
        log_context=log_context
    )

    return {
        "success": True,
        "message": f"User '{pre_username}' has been permanently deleted",
        "user_hash": user_hash,
        "username": pre_username,
        "removed": {
            "mode": "hard",
            "user_type": pre_user_type,
            "emails_unlinked": email_count,
            "owned_content": "cascade_deleted",
            "shared_resources": "preserved (ownership cleared)"
        },
        "deleted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }


@router.get("/search/query")
@log_and_handle_errors(
    operation_name="search_users",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False
)
async def search_users_endpoint(
        q: Annotated[str, Query(description="Search term matched against username and email.")],
        user_type_filter: Annotated[Optional[str], Query(
            description="Only this user type: `root`, `admin`, or `consumer`.",
        )] = None,
        limit: Annotated[int, Query(
            description="Maximum results; values above 100 are capped to 100 and values below 1 become 50.",
        )] = 50,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> Dict[str, Any]:
    """
    Search users by username or email.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root or admin user; consumers get `403`. Root
    searches every user. Admins only get themselves and users who reach one of
    the projects they are assigned to administer; that filter runs after the
    `limit` is applied, so an admin can receive fewer than `limit` results.

    **Responses:** `200` with `users`, `search_term`, `total_results` (the
    number of users returned), and `filters`; `400` for an invalid
    `user_type_filter`.
    """
    from src.Util.db import search_users
    
    # Get current user
    current_user = handle_db_operation(
        lambda: get_user_by_hash(log_context.user_hash),
        error_context="current user lookup",
        not_found_message=f"Current user not found: {mask_uuid(log_context.user_hash)}"
    )

    # Check admin permissions
    scope = resolve_admin_scope(current_user.id)
    if not scope.is_admin:
        raise AuthorizationError(
            message="Admin permission required to search users",
            error_code=ErrorCode.ACCESS_DENIED
        )

    # Validate and cap limit
    if limit > 100:
        limit = 100
    if limit < 1:
        limit = 50

    # Validate user type filter
    if user_type_filter and user_type_filter not in ['root', 'admin', 'consumer']:
        raise ValidationError(
            message="Invalid user type filter. Must be one of: root, admin, consumer",
            error_code=ErrorCode.INVALID_INPUT
        )

    # Perform search
    users = handle_db_operation(
        lambda: search_users(q, user_type=user_type_filter, limit=limit),
        error_context="user search"
    )

    # Build response data; admin users only see users in their assigned projects
    users_list = []
    for user in users:
        if not scope.is_root and not user_in_scope(scope, user.id):
            continue
        user_info = {
            "user_hash": user.user_hash,
            "username": user.username,
            "email": user.email,
            "user_type": user.user_type,
            "created_at": user.created_at,
            "last_login": user.last_login,
            "is_active": user.is_active
        }
        users_list.append(user_info)

    return {
        "success": True,
        "users": users_list,
        "search_term": q,
        "total_results": len(users_list),
        "filters": {
            "user_type_filter": user_type_filter,
            "limit": limit
        }
    }


@router.patch("/{user_hash}/type", response_model=ChangeUserTypeResponse)
@log_and_handle_errors(
    operation_name="change_user_type",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True
)
async def change_user_type_endpoint(
        user_hash: Annotated[str, Path(description=_USER_HASH_DESCRIPTION)],
        user_type: str = Form(..., description="New user type: `root`, `admin`, or `consumer`."),
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> ChangeUserTypeResponse:
    """
    Change a user's type (promote or demote).

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root user; others get `403` (`AUTHZ_2002`).

    **Request:** form field `user_type` (`application/x-www-form-urlencoded` or
    `multipart/form-data`). No project is assigned when promoting to `admin`;
    use `PUT /user-types/{user_hash}/type` to set one.

    **Responses:** `200` with `previous_type` and `new_type`; `400` for an
    invalid `user_type` (`VAL_3012`); `404` for an unknown or inactive
    `user_hash`.
    """
    # Get current user
    current_user = handle_db_operation(
        lambda: get_user_by_hash(log_context.user_hash),
        error_context="current user lookup",
        not_found_message=f"Current user not found: {mask_uuid(log_context.user_hash)}"
    )
    
    # Only root users can change user types
    if not is_root_user(current_user.id):
        raise AuthorizationError(
            message="Root user access required to change user types",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_user_type": "root"}
        )
    
    # Get target user
    target_user = handle_db_operation(
        lambda: get_user_by_hash(user_hash),
        error_context="target user lookup",
        not_found_message=f"User not found: {mask_uuid(user_hash)}"
    )
    
    # Validate user type
    if user_type not in ['root', 'admin', 'consumer']:
        raise ValidationError(
            message="Invalid user type. Must be 'root', 'admin', or 'consumer'",
            error_code=ErrorCode.INVALID_ENUM_VALUE,
            details={"field": "user_type", "allowed_values": ['root', 'admin', 'consumer']}
        )
    
    # Store previous type for response
    previous_type = target_user.user_type
    
    # Update user type
    success = handle_db_operation(
        lambda: update_user_type(
            user_id=target_user.id,
            new_user_type=user_type,
            updated_by=current_user.id
        ),
        error_context="user type update"
    )
    
    if not success:
        from src.Util.error_handler import InternalError
        raise InternalError(
            message="Failed to update user type",
            error_code=ErrorCode.INTERNAL_ERROR
        )
    
    # Log the activity
    log_operation_details(
        user_id=log_context.user_id,
        operation=OperationMetadata(
            operation_name="change_user_type",
            target_resource=user_hash,
            target_resource_type="user",
            changes={
                "previous_type": previous_type,
                "new_type": user_type
            },
            additional_data={
                "target_username": target_user.username,
                "changed_by": current_user.username
            }
        ),
        log_context=log_context
    )
    
    return ChangeUserTypeResponse(
        success=True,
        message=f"User type changed successfully",
        user_hash=target_user.user_hash,
        previous_type=previous_type,
        new_type=user_type
    )


@router.put("/{user_hash}", response_model=UpdateUserResponse)
@log_and_handle_errors(
    operation_name="update_user_details",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True
)
async def update_user_details_endpoint(
        user_hash: Annotated[str, Path(description=_USER_HASH_DESCRIPTION)],
        username: Optional[str] = Form(None, description="New username (must be unique)."),
        email: Optional[str] = Form(
            None,
            description="New value for the legacy `email` field (not verified; not a login identifier).",
        ),
        user_type: Optional[str] = Form(
            None,
            description="New user type (`root`, `admin`, `consumer`); root callers only.",
        ),
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> UpdateUserResponse:
    """
    Update another user's username, legacy `email` field, or user type.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root or admin user; consumers get `403`.
    Root may update any user, including `user_type`. Admins may update users
    who share at least one accessible project with them, but not `user_type`.

    **Request:** form fields (`application/x-www-form-urlencoded` or
    `multipart/form-data`); send at least one field. `email` only overwrites
    the compatibility `email` field; verified addresses live under the
    `/users/me/emails` lifecycle.

    **Responses:**
    - `200` — the updated user.
    - `400` — no field provided, or invalid `user_type` (`VAL_3012`).
    - `403` — not root/admin, admin sending `user_type` (`AUTHZ_2002`), or
      target outside the admin's projects.
    - `404` — unknown or inactive `user_hash`.
    - `409` — username already taken (`CONF_5004`).
    """
    # Get current user
    current_user = handle_db_operation(
        lambda: get_user_by_hash(log_context.user_hash),
        error_context="current user lookup",
        not_found_message=f"Current user not found: {mask_uuid(log_context.user_hash)}"
    )
    
    # Check permissions
    is_root = is_root_user(current_user.id)
    current_user_type = get_user_type(current_user.id)
    
    if not is_root and current_user_type != 'admin':
        raise AuthorizationError(
            message="Admin or root access required",
            error_code=ErrorCode.ACCESS_DENIED
        )
    
    # Get target user
    target_user = handle_db_operation(
        lambda: get_user_by_hash(user_hash),
        error_context="target user lookup",
        not_found_message=f"User not found: {mask_uuid(user_hash)}"
    )
    
    # Only root users can change user types
    if user_type and not is_root:
        raise AuthorizationError(
            message="Root user access required to change user types",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_user_type": "root"}
        )
    
    # Validate user type if provided
    if user_type and user_type not in ['root', 'admin', 'consumer']:
        raise ValidationError(
            message="Invalid user type. Must be 'root', 'admin', or 'consumer'",
            error_code=ErrorCode.INVALID_ENUM_VALUE,
            details={"field": "user_type", "allowed_values": ['root', 'admin', 'consumer']}
        )
    
    # Admin users can only update users in their projects
    if not is_root:
        admin_projects = get_user_accessible_projects(current_user.id)
        target_user_projects = get_user_accessible_projects(target_user.id)
        
        admin_project_hashes = [p.project_hash for p in admin_projects]
        target_project_hashes = [p.project_hash for p in target_user_projects]
        
        if not any(ph in admin_project_hashes for ph in target_project_hashes):
            raise AuthorizationError(
                message="Access denied: User not in your projects",
                error_code=ErrorCode.ACCESS_DENIED,
                details={"target_user": mask_uuid(user_hash)}
            )
    
    # Check if at least one field is provided
    if not any([username, email, user_type]):
        raise ValidationError(
            message="At least one field must be provided to update",
            error_code=ErrorCode.INVALID_INPUT,
            details={"required_fields": ["username", "email", "user_type"]}
        )
    
    # Track changes
    changes = {}
    if username:
        changes['username'] = username
    if email:
        changes['email'] = email
    if user_type:
        changes['user_type'] = user_type
    
    # Update user
    updated_user = handle_db_operation(
        lambda: update_user(
            target_user.id,
            username=username,
            email=email,
            user_type=user_type
        ),
        error_context="user update"
    )
    
    if not updated_user:
        from src.Util.error_handler import InternalError
        raise InternalError(
            message="Failed to update user",
            error_code=ErrorCode.INTERNAL_ERROR
        )
    
    # Log the activity
    log_operation_details(
        user_id=log_context.user_id,
        operation=OperationMetadata(
            operation_name="update_user_details",
            target_resource=user_hash,
            target_resource_type="user",
            changes=changes,
            additional_data={
                "target_username": target_user.username,
                "updated_by": current_user.username
            }
        ),
        log_context=log_context
    )
    
    # Build response
    user_info = UserInfo(
        user_hash=updated_user.user_hash,
        username=updated_user.username,
        email=updated_user.email,
        user_type=updated_user.user_type,
        created_at=updated_user.created_at,
        updated_at=updated_user.updated_at
    )
    
    return UpdateUserResponse(
        success=True,
        message="User updated successfully",
        user=user_info,
        updated_at=updated_user.updated_at
    )
