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

Note: Admin project management is now handled through the groups-of-groups architecture:
- Use POST /admin/user-groups/{group_hash}/members to assign users to groups
- Use POST /admin/user-groups/{group_hash}/project-groups to grant group access to project groups

Endpoints:
- POST /root - Create root user (root only)
- POST /admin - Create admin user with project assignment (root only)
- GET /{user_hash}/info - Get user type information (root/admin)
- PUT /{user_hash}/type - Update user type (root only)
- GET /users/{user_type} - List users by type (root/admin)
- GET /stats - User type statistics (root/admin)
- GET/PUT /admin/{user_hash}/projects - View/replace admin project assignments (root only)
- POST /admin/{user_hash}/projects/add - Add an admin to a project (root only)
- DELETE /admin/{user_hash}/projects/{project_id} - Remove an admin from a project (root only)
"""

import logging
import re
from typing import Annotated, Optional, List

from fastapi import APIRouter, Depends, Form, Path, Query
from fastapi.security import HTTPAuthorizationCredentials

from src.Util.Models import (
    CreateRootUserResponse, CreateAdminUserResponse, UserTypeInfoResponse,
    UpdateUserTypeResponse, ListUsersByTypeResponse, UserTypeStatsResponse,
    UserInfo, UserTypeInfo, PaginationInfo, AdminProjectInfo, AdminProjectsResponse,
    UpdateAdminProjectsResponse, AddAdminToProjectResponse, RemoveAdminFromProjectResponse
)
from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.db import (
    validate_session, get_user_by_hash, create_root_user, create_admin_user, get_user_type,
    get_admin_assigned_project, get_admin_project_assignments_with_details,
    update_user_type, is_root_user, is_admin_user, get_user_type_info, list_users, count_users,
    get_project_by_id, add_admin_to_project, remove_admin_from_project
)
from src.Util.admin_scope import resolve_admin_scope, user_in_scope
from src.Util.error_handler import (
    AuthenticationError, AuthorizationError, ValidationError,
    NotFoundError, ConflictError, InternalError, ErrorCode
)
from src.Util.password_security import assert_password_policy

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/user-types", tags=["User Type Management"])
security = HTTPBearerOrCookie()

_EMAIL_FORMAT_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_USER_HASH_DESCRIPTION = "Hash of the target user."
_ADMIN_HASH_DESCRIPTION = "Hash of the target user; must currently be an `admin` user."
_PROJECT_ID_DESCRIPTION = "Internal project ID (the project's `id`, e.g. `proj-...`), not its hash."


def _normalize_optional_email(value: Optional[str]) -> Optional[str]:
    if value is None or not str(value).strip():
        return None
    normalized = str(value).strip()
    if not _EMAIL_FORMAT_RE.match(normalized):
        raise ValidationError(
            message="Invalid email format",
            error_code=ErrorCode.INVALID_INPUT,
            details={"field": "email"},
        )
    return normalized


# Pydantic models for requests that aren't in Models.py
# Note: All endpoints use Form data instead of JSON/Pydantic models for consistency


def require_root_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Middleware to ensure only root users can access certain endpoints"""
    session_token = credentials.credentials
    session_data = validate_session(session_token)

    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    user = get_user_by_hash(session_data.user_hash)
    if not user or not is_root_user(user.id):
        raise AuthorizationError(
            message="Root user access required",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_user_type": "root"}
        )

    return user


def require_root_or_admin_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Middleware to ensure only root or admin users can access certain endpoints"""
    session_token = credentials.credentials
    session_data = validate_session(session_token)

    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    user = get_user_by_hash(session_data.user_hash)
    if not user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": session_data.user_hash}
        )

    user_type = get_user_type(user.id)
    if user_type not in ['root', 'admin']:
        raise AuthorizationError(
            message="Root or admin user access required",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_user_types": ["root", "admin"]}
        )

    return user


@router.post(
    "/root",
    response_model=CreateRootUserResponse,
    responses={409: {"description": "Username already exists (`CONF_5004`)."}},
)
async def create_root_user_endpoint(
        username: str = Form(..., description="Unique username for the new root user."),
        password: str = Form(..., description="Initial password; must satisfy the password policy."),
        email: Optional[str] = Form(
            None,
            description="Optional email address (format-checked only; not verified and no activation email is sent).",
        ),
        current_user=Depends(require_root_user)
) -> CreateRootUserResponse:
    """
    Create a new root (super-admin) user.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root user; other users get `403`
    (`AUTHZ_2002`).

    **Request:** form fields (`application/x-www-form-urlencoded` or
    `multipart/form-data`).

    **Responses:**
    - `200` — the created user (`user.user_type` is `root`).
    - `400` — missing field, malformed `email`, or weak password (`VAL_3007`
      with `reason_codes`).
    - `409` — username already exists.
    """
    logger.info(f"Root user creation attempt by user: {current_user.username}")

    if not username or not password:
        raise ValidationError(
            message="Username and password are required",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"required_fields": ["username", "password"]}
        )
    email = _normalize_optional_email(email)
    assert_password_policy(password, username=username, email=email)

    # Create root user - db layer converts IntegrityError to ConflictError automatically
    new_root_user = create_root_user(
        username=username,
        password=password,
        email=email,
        created_by=current_user.id
    )

    logger.info(f"Root user created: {new_root_user.username}")

    user_info = UserInfo(
        user_hash=new_root_user.user_hash,
        username=new_root_user.username,
        email=new_root_user.email,
        user_type="root",
        created_at=new_root_user.created_at
    )

    return CreateRootUserResponse(
        success=True,
        message=f"Root user '{username}' created successfully",
        user=user_info
    )


@router.post(
    "/admin",
    response_model=CreateAdminUserResponse,
    responses={409: {"description": "Username already exists (`CONF_5004`)."}},
)
async def create_admin_user_endpoint(
        username: str = Form(..., description="Unique username for the new admin user."),
        password: str = Form(..., description="Initial password; must satisfy the password policy."),
        email: Optional[str] = Form(
            None,
            description="Optional email address (format-checked only; not verified and no activation email is sent).",
        ),
        assigned_project_id: Optional[str] = Form(
            None,
            description="Single internal project ID to administer. Ignored when `assigned_project_ids` is sent.",
        ),
        assigned_project_ids: Optional[List[str]] = Form(
            None,
            description="Internal project IDs to administer (repeat the field once per project). The first is the primary project.",
        ),
        current_user=Depends(require_root_user)
) -> CreateAdminUserResponse:
    """
    Create a new admin user who administers one or more projects.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root user; other users get `403`
    (`AUTHZ_2002`).

    **Request:** form fields (`application/x-www-form-urlencoded` or
    `multipart/form-data`). At least one of `assigned_project_id` /
    `assigned_project_ids` is required; values are internal project IDs, not
    project hashes. The admin joins each project's admin group; a project
    without an admin group is skipped silently.

    **Responses:**
    - `200` — the created admin with `assigned_projects` and
      `primary_project_id`.
    - `400` — missing field or project, malformed `email`, or weak password
      (`VAL_3007`).
    - `404` — a project ID does not exist (`NF_4002`).
    - `409` — username already exists.
    """
    logger.info(f"Admin user creation attempt by user: {current_user.username}")

    if not username or not password:
        raise ValidationError(
            message="Username and password are required",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"required_fields": ["username", "password"]}
        )
    email = _normalize_optional_email(email)
    assert_password_policy(password, username=username, email=email)

    # Handle both single and multiple project assignments
    project_ids = []
    if assigned_project_ids:
        project_ids = assigned_project_ids
    elif assigned_project_id:
        project_ids = [assigned_project_id]
    else:
        raise ValidationError(
            message="At least one project assignment is required",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"required_fields": ["assigned_project_id", "assigned_project_ids"]}
        )

    # Verify all projects exist
    projects = []
    for project_id in project_ids:
        project = get_project_by_id(project_id)
        if not project:
            raise NotFoundError(
                message=f"Project with ID {project_id} not found",
                error_code=ErrorCode.PROJECT_NOT_FOUND,
                details={"project_id": project_id}
            )
        projects.append(project)

    # Create admin user - db layer converts IntegrityError to ConflictError automatically
    new_admin_user = create_admin_user(
        username=username,
        password=password,
        email=email,
        assigned_project_id=project_ids[0],  # Primary project for backwards compatibility
        assigned_project_ids=project_ids,  # All assigned projects
        created_by=current_user.id
    )

    project_names = [p.project_name for p in projects]
    logger.info(f"Admin user created: {new_admin_user.username} for projects: {', '.join(project_names)}")

    user_data_dict = {
        "user_hash": new_admin_user.user_hash,
        "username": new_admin_user.username,
        "email": new_admin_user.email,
        "user_type": "admin",
        "assigned_project_ids": project_ids,
        "assigned_projects": [
            {
                "project_id": p.id,
                "project_hash": p.project_hash,
                "project_name": p.project_name
            } for p in projects
        ],
        "primary_project_id": project_ids[0],  # For backwards compatibility
        "created_at": new_admin_user.created_at,
        "created_by": current_user.username
    }

    return CreateAdminUserResponse(
        success=True,
        message=f"Admin user '{username}' created and assigned to {len(projects)} project(s)",
        user=user_data_dict
    )


@router.get("/{user_hash}/info", response_model=UserTypeInfoResponse)
async def get_user_type_information(
        user_hash: Annotated[str, Path(description=_USER_HASH_DESCRIPTION)],
        current_user=Depends(require_root_or_admin_user)
) -> UserTypeInfoResponse:
    """
    Get a user's type, capabilities, and (for admins) assigned projects.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root or admin user; consumers get `403`
    (`AUTHZ_2002`). Root may read any user. Admins may read themselves and
    users of any type who reach at least one of the projects the admin is
    assigned to administer.

    **Responses:** `200` with `user_type_info` (`user_type`, `capabilities`,
    and for admin targets `assigned_projects` plus the primary
    `assigned_project_id`); `403` outside the admin's scope (`AUTHZ_2001`);
    `404` for an unknown or inactive `user_hash`.
    """
    target_user = get_user_by_hash(user_hash)
    if not target_user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": user_hash}
        )

    # Access control: root reads anyone; admin users read themselves and users who
    # reach one of their assigned projects (whatever the target's user type).
    if not user_in_scope(resolve_admin_scope(current_user.id), target_user.id):
        raise AuthorizationError(
            message="Access denied to user outside your project",
            error_code=ErrorCode.ACCESS_DENIED,
            details={"user_hash": user_hash}
        )

    # Get comprehensive user type info
    user_type_info_dict = get_user_type_info(target_user.id)

    # Add project information for admin users
    if user_type_info_dict.get("user_type") == "admin":
        # Get all assigned projects for multi-project admin support
        assigned_projects = get_admin_project_assignments_with_details(target_user.id)
        user_type_info_dict["assigned_projects"] = assigned_projects
        user_type_info_dict["total_assigned_projects"] = len(assigned_projects)

        # Legacy compatibility - primary project
        if assigned_projects:
            primary_project = assigned_projects[0]
            user_type_info_dict["assigned_project_id"] = primary_project["project_id"]
            user_type_info_dict["assigned_project_name"] = primary_project["project_name"]
            user_type_info_dict["assigned_project_hash"] = primary_project["project_hash"]

    # Build UserTypeInfo model
    user_type_info = UserTypeInfo(
        user_id=user_type_info_dict.get("user_id", target_user.id),
        user_hash=user_type_info_dict.get("user_hash", target_user.user_hash),
        username=user_type_info_dict.get("username", target_user.username),
        user_type=user_type_info_dict.get("user_type", "consumer"),
        capabilities=user_type_info_dict.get("capabilities", []),
        assigned_project_id=user_type_info_dict.get("assigned_project_id"),
        assigned_projects=user_type_info_dict.get("assigned_projects")
    )

    return UserTypeInfoResponse(
        success=True,
        user_type_info=user_type_info
    )


@router.put("/{user_hash}/type", response_model=UpdateUserTypeResponse)
async def update_user_type_endpoint(
        user_hash: Annotated[str, Path(description=_USER_HASH_DESCRIPTION)],
        user_type: str = Form(..., description="New user type: `root`, `admin`, or `consumer`."),
        assigned_project_id: Optional[str] = Form(
            None,
            description="Internal project ID to administer; required when `user_type` is `admin`.",
        ),
        current_user=Depends(require_root_user)
) -> UpdateUserTypeResponse:
    """
    Change a user's type (promote or demote), optionally assigning an admin project.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root user; other users get `403`
    (`AUTHZ_2002`).

    **Request:** form fields (`application/x-www-form-urlencoded` or
    `multipart/form-data`). `PATCH /users/{user_hash}/type` does the same
    without the admin project assignment.

    **Responses:**
    - `200` — the updated `user_type_info`.
    - `400` — invalid `user_type`, or `admin` without `assigned_project_id`.
    - `404` — unknown or inactive `user_hash`, or unknown project ID.
    """
    target_user = get_user_by_hash(user_hash)
    if not target_user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": user_hash}
        )

    new_user_type = user_type
    new_assigned_project_id = assigned_project_id

    if not new_user_type:
        raise ValidationError(
            message="User type is required",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"field": "user_type"}
        )

    # Validate user type
    if new_user_type not in ['root', 'admin', 'consumer']:
        raise ValidationError(
            message="Invalid user type. Must be 'root', 'admin', or 'consumer'",
            error_code=ErrorCode.INVALID_ENUM_VALUE,
            details={"field": "user_type", "allowed_values": ['root', 'admin', 'consumer']}
        )

    # Validate project assignment for admin users
    if new_user_type == 'admin':
        if not new_assigned_project_id:
            raise ValidationError(
                message="Admin users must have an assigned project",
                error_code=ErrorCode.MISSING_REQUIRED_FIELD,
                details={"field": "assigned_project_id"}
            )

        project = get_project_by_id(new_assigned_project_id)
        if not project:
            raise NotFoundError(
                message="Assigned project not found",
                error_code=ErrorCode.PROJECT_NOT_FOUND,
                details={"project_id": new_assigned_project_id}
            )

    # Update user type
    success = update_user_type(
        user_id=target_user.id,
        new_user_type=new_user_type,
        project_id=new_assigned_project_id,
        updated_by=current_user.id
    )

    if not success:
        raise InternalError(
            message="Failed to update user type",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "update_user_type"}
        )

    # Get updated user info
    updated_info_dict = get_user_type_info(target_user.id)

    # Build UserTypeInfo model
    updated_info = UserTypeInfo(
        user_id=updated_info_dict.get("user_id", target_user.id),
        user_hash=updated_info_dict.get("user_hash", target_user.user_hash),
        username=updated_info_dict.get("username", target_user.username),
        user_type=updated_info_dict.get("user_type", new_user_type),
        capabilities=updated_info_dict.get("capabilities", []),
        assigned_project_id=updated_info_dict.get("assigned_project_id"),
        assigned_projects=updated_info_dict.get("assigned_projects")
    )

    logger.info(f"User type updated: {target_user.username} -> {new_user_type} by {current_user.username}")

    return UpdateUserTypeResponse(
        success=True,
        message=f"User '{target_user.username}' type updated to '{new_user_type}'",
        user_type_info=updated_info
    )


def _users_of_type_in_projects(user_type: str, project_hashes: List[str]) -> list:
    """Active users of ``user_type`` reaching any of ``project_hashes``, deduplicated, by username."""
    page_size = 500
    found = {}
    for project_hash in project_hashes:
        offset = 0
        while True:
            page = list_users(limit=page_size, offset=offset, user_type=user_type, project_filter=project_hash)
            for user in page:
                found.setdefault(user.user_hash, user)
            if len(page) < page_size:
                break
            offset += page_size
    return sorted(found.values(), key=lambda user: (user.username or "").lower())


@router.get("/users/{user_type}", response_model=ListUsersByTypeResponse)
async def list_users_by_type(
        user_type: Annotated[str, Path(description="User type to list: `root`, `admin`, or `consumer`.")],
        limit: Annotated[int, Query(description="Page size; values above 100 are capped to 100.")] = 50,
        offset: Annotated[int, Query(description="Number of users to skip.")] = 0,
        current_user=Depends(require_root_or_admin_user)
) -> ListUsersByTypeResponse:
    """
    List active users of one user type, with pagination.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root or admin user; consumers get `403`
    (`AUTHZ_2002`). Root sees every user of the type. Admins get `403` for
    `root`; for `admin`/`consumer` they only see users who reach one of the
    projects they are assigned to administer (an admin with no assignment sees
    none).

    **Responses:** `200` with `users`, `pagination`, and `filter`. For admins
    `filter.project_filter` lists the hashes of the projects the result is
    restricted to (`null` for root), and `pagination.total` / `has_more` use the
    restricted count; for root they use the global count for the type. Admin
    results are sorted by username. `400` for an unknown `user_type`
    (`VAL_3012`).
    """
    # Validate user type
    if user_type not in ['root', 'admin', 'consumer']:
        raise ValidationError(
            message="Invalid user type. Must be 'root', 'admin', or 'consumer'",
            error_code=ErrorCode.INVALID_ENUM_VALUE,
            details={"field": "user_type", "allowed_values": ['root', 'admin', 'consumer']}
        )

    # Limit constraints
    if limit > 100:
        limit = 100

    # Access control for admin users
    project_filter = None
    if not is_root_user(current_user.id) and is_admin_user(current_user.id):
        if user_type == 'root':
            raise AuthorizationError(
                message="Admin users cannot list root users",
                error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
                details={"required_user_type": "root"}
            )

        # Admin users only see users who reach one of their assigned projects. The list
        # procedure filters on a project name or hash (not an id), one project at a time.
        project_filter = [
            assignment["project_hash"]
            for assignment in get_admin_project_assignments_with_details(current_user.id) or []
            if assignment.get("project_hash")
        ]
        scoped_users = _users_of_type_in_projects(user_type, project_filter)
        users = scoped_users[offset:offset + limit]
        total_count = len(scoped_users)
    else:
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

    pagination = PaginationInfo(
        limit=limit,
        offset=offset,
        total=total_count,
        has_more=offset + limit < total_count
    )

    filter_info = {
        "user_type": user_type,
        "project_filter": project_filter
    }

    return ListUsersByTypeResponse(
        success=True,
        users=user_list,
        pagination=pagination,
        filter=filter_info
    )


@router.get("/stats", response_model=UserTypeStatsResponse)
async def get_user_type_statistics(
        current_user=Depends(require_root_or_admin_user)
) -> UserTypeStatsResponse:
    """
    Get counts and percentages of active users per user type.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root or admin user; consumers get `403`
    (`AUTHZ_2002`).

    **Responses:** `200` with `statistics`: `total_users`, per-type `count`
    and `percentage`, static `system_info`, and `scope`. Counts are always
    system-wide, also for admins; for admin callers `scope` only names their
    primary assigned project (`type: project_admin`), for root it is
    `global_root`.
    """
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

    return UserTypeStatsResponse(
        success=True,
        statistics=stats
    )


# =================== ADMIN PROJECT MANAGEMENT ===================

@router.get("/admin/{user_hash}/projects", response_model=AdminProjectsResponse)
async def get_admin_projects(
        user_hash: Annotated[str, Path(description=_ADMIN_HASH_DESCRIPTION)],
        current_user=Depends(require_root_user)
) -> AdminProjectsResponse:
    """
    List the projects an admin user administers.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root user; other users get `403`
    (`AUTHZ_2002`).

    **Responses:** `200` with `assigned_projects` (ID, hash, name,
    description, assignment metadata); `400` when the target is not an
    `admin` user; `404` for an unknown or inactive `user_hash`.
    """
    target_user = get_user_by_hash(user_hash)
    if not target_user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": user_hash}
        )
    
    # Verify target user is an admin
    target_user_type = get_user_type(target_user.id)
    if target_user_type != 'admin':
        raise ValidationError(
            message="User is not an admin user",
            error_code=ErrorCode.INVALID_INPUT,
            details={"user_type": target_user_type, "expected": "admin"}
        )
    
    # Get assigned projects
    assigned_projects = get_admin_project_assignments_with_details(target_user.id)
    
    # Format response
    project_list = []
    for proj in assigned_projects:
        project_list.append(AdminProjectInfo(
            project_id=str(proj['project_id']),
            project_hash=proj['project_hash'],
            project_name=proj['project_name'],
            project_description=proj.get('project_description'),
            assigned_at=proj.get('assigned_at'),
            assigned_by=proj.get('assigned_by')
        ))
    
    return AdminProjectsResponse(
        success=True,
        user_hash=user_hash,
        assigned_projects=project_list
    )


@router.put("/admin/{user_hash}/projects", response_model=UpdateAdminProjectsResponse)
async def update_admin_projects(
        user_hash: Annotated[str, Path(description=_ADMIN_HASH_DESCRIPTION)],
        assigned_project_ids: List[str] = Form(
            ...,
            description="Complete new set of internal project IDs (repeat the field once per project).",
        ),
        current_user=Depends(require_root_user)
) -> UpdateAdminProjectsResponse:
    """
    Replace the full set of projects an admin user administers.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root user; other users get `403`
    (`AUTHZ_2002`).

    **Request:** form fields; projects missing from `assigned_project_ids`
    are removed and new ones are added.

    **Responses:**
    - `200` — `assigned_projects` after the change. If some add/remove steps
      failed, the status is still `200` but `success` is `false` and
      `message` lists the failed project IDs.
    - `400` — the target is not an `admin` user.
    - `404` — unknown or inactive `user_hash`, or an unknown project ID
      (checked before anything changes).
    """
    target_user = get_user_by_hash(user_hash)
    if not target_user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": user_hash}
        )
    
    # Verify target user is an admin
    target_user_type = get_user_type(target_user.id)
    if target_user_type != 'admin':
        raise ValidationError(
            message="User is not an admin user",
            error_code=ErrorCode.INVALID_INPUT,
            details={"user_type": target_user_type, "expected": "admin"}
        )
    
    # Validate all projects exist
    projects = []
    for project_id in assigned_project_ids:
        project = get_project_by_id(project_id)
        if not project:
            raise NotFoundError(
                message=f"Project with ID {project_id} not found",
                error_code=ErrorCode.PROJECT_NOT_FOUND,
                details={"project_id": project_id}
            )
        projects.append(project)
    
    # Get current assignments to remove
    current_assignments = get_admin_project_assignments_with_details(target_user.id)
    current_project_ids = [str(a['project_id']) for a in current_assignments]
    
    # Track per-project failures so a partial reassignment does not report success.
    failures = []

    # Remove from projects not in the new list
    for old_project_id in current_project_ids:
        if old_project_id not in assigned_project_ids:
            try:
                remove_admin_from_project(target_user.id, old_project_id, removed_by=current_user.id)
            except Exception as e:
                failures.append({"op": "remove", "project_id": old_project_id, "error": str(e)})

    # Add to new projects
    for project_id in assigned_project_ids:
        if project_id not in current_project_ids:
            try:
                add_admin_to_project(target_user.id, project_id, assigned_by=current_user.id)
            except Exception as e:
                failures.append({"op": "add", "project_id": project_id, "error": str(e)})

    # Get updated assignments
    updated_assignments = get_admin_project_assignments_with_details(target_user.id)
    
    # Format response
    project_list = []
    for proj in updated_assignments:
        project_list.append(AdminProjectInfo(
            project_id=str(proj['project_id']),
            project_hash=proj['project_hash'],
            project_name=proj['project_name'],
            project_description=proj.get('project_description'),
            assigned_at=proj.get('assigned_at'),
            assigned_by=proj.get('assigned_by')
        ))
    
    logger.info(f"Updated admin {target_user.username} projects to {len(project_list)} projects by {current_user.username}")

    if failures:
        failed_ids = [f["project_id"] for f in failures]
        logger.warning(
            f"Admin project reassignment for {target_user.username} had {len(failures)} failed operations: {failures}"
        )
        return UpdateAdminProjectsResponse(
            success=False,
            message=f"Admin projects partially updated; failed operations for project ids: {failed_ids}",
            user_hash=user_hash,
            assigned_projects=project_list,
            total_projects=len(project_list)
        )

    return UpdateAdminProjectsResponse(
        success=True,
        message=f"Admin projects updated",
        user_hash=user_hash,
        assigned_projects=project_list,
        total_projects=len(project_list)
    )


@router.post("/admin/{user_hash}/projects/add", response_model=AddAdminToProjectResponse)
async def add_admin_to_project_endpoint(
        user_hash: Annotated[str, Path(description=_ADMIN_HASH_DESCRIPTION)],
        project_id: str = Form(..., description=_PROJECT_ID_DESCRIPTION),
        current_user=Depends(require_root_user)
) -> AddAdminToProjectResponse:
    """
    Make an admin user an administrator of one more project.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root user; other users get `403`
    (`AUTHZ_2002`).

    **Request:** form field `project_id` (internal project ID).

    **Responses:** `200` with the project's ID, hash, and name; `400` when the
    target is not an `admin` user; `404` for an unknown user or project, or
    when the project has no admin group (`NF_4003`).
    """
    target_user = get_user_by_hash(user_hash)
    if not target_user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": user_hash}
        )
    
    # Verify target user is an admin
    target_user_type = get_user_type(target_user.id)
    if target_user_type != 'admin':
        raise ValidationError(
            message="User is not an admin user",
            error_code=ErrorCode.INVALID_INPUT,
            details={"user_type": target_user_type, "expected": "admin"}
        )
    
    # Verify project exists
    project = get_project_by_id(project_id)
    if not project:
        raise NotFoundError(
            message=f"Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_id": project_id}
        )
    
    # Add admin to project
    try:
        success = add_admin_to_project(target_user.id, project_id, assigned_by=current_user.id)
        if not success:
            raise InternalError(
                message="Failed to add admin to project",
                error_code=ErrorCode.INTERNAL_ERROR
            )
    except NotFoundError:
        raise NotFoundError(
            message="No admin group found for project",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"project_id": project_id}
        )
    
    logger.info(f"Added admin {target_user.username} to project {project.project_name} by {current_user.username}")
    
    return AddAdminToProjectResponse(
        success=True,
        message=f"Admin added to project",
        user_hash=user_hash,
        project_id=project_id,
        project_hash=project.project_hash,
        project_name=project.project_name
    )


@router.delete("/admin/{user_hash}/projects/{project_id}", response_model=RemoveAdminFromProjectResponse)
async def remove_admin_from_project_endpoint(
        user_hash: Annotated[str, Path(description=_ADMIN_HASH_DESCRIPTION)],
        project_id: Annotated[str, Path(description=_PROJECT_ID_DESCRIPTION)],
        current_user=Depends(require_root_user)
) -> RemoveAdminFromProjectResponse:
    """
    Stop an admin user from administering a project.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the
    `session_token` cookie) of a root user; other users get `403`
    (`AUTHZ_2002`).

    **Request:** no body.

    **Responses:** `200` on removal; `400` when the target is not an `admin`
    user; `404` for an unknown user or when the admin is not assigned to that
    project.
    """
    target_user = get_user_by_hash(user_hash)
    if not target_user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": user_hash}
        )
    
    # Verify target user is an admin
    target_user_type = get_user_type(target_user.id)
    if target_user_type != 'admin':
        raise ValidationError(
            message="User is not an admin user",
            error_code=ErrorCode.INVALID_INPUT,
            details={"user_type": target_user_type, "expected": "admin"}
        )
    
    # Remove admin from project
    try:
        success = remove_admin_from_project(target_user.id, project_id, removed_by=current_user.id)
        if not success:
            raise NotFoundError(
                message="Admin is not assigned to this project",
                error_code=ErrorCode.RESOURCE_NOT_FOUND,
                details={"project_id": project_id}
            )
    except NotFoundError as e:
        raise e
    
    logger.info(f"Removed admin {target_user.username} from project {project_id} by {current_user.username}")
    
    return RemoveAdminFromProjectResponse(
        success=True,
        message=f"Admin removed from project",
        user_hash=user_hash,
        project_id=project_id
    )
