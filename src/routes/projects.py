"""
Project Management Routes

Handles project CRUD operations and project-related queries
for the group-based multi-project authentication system.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Query, Path, Form, Body
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from src.Util.Models import (
    ListProjectsResponse, CreateProjectResponse, ProjectDetailsResponse,
    UpdateProjectResponse, DeleteProjectResponse, ProjectAccessInfo,
    ProjectInfo, PaginationInfo, ListUserGroupsResponse, UserGroupInfo
)
from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.error_handler import (
    AuthenticationError, AuthorizationError, ValidationError,
    NotFoundError, InternalError, FeatureNotImplementedError, ErrorCode, create_not_found_error
)
from src.Util.activity_logger import ActivityLogger, ActivityType, get_recent_activity, count_activity_logs
from src.Util.db import (
    validate_session, get_user_by_hash,
    create_project, get_project_by_hash, list_all_projects,
    update_project, delete_project, search_projects,
    get_project_stats, get_user_accessible_projects,
    get_project_members_page,
    get_user_groups_for_user,
    # Group-project management
    get_user_groups_for_project,
    # Project groups for groups-of-groups architecture
    get_permission_groups_for_project,
    get_admin_project_assignments_with_details
)
from src.Util.admin_scope import AdminScope, resolve_admin_scope, require_project_in_scope

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/projects", tags=["Project Management"])
security = HTTPBearerOrCookie()


# Note: All request endpoints use Form data instead of JSON/Pydantic models for consistency
# Response models below use Pydantic for type safety

class ProjectMembersResponse(BaseModel):
    """Response model for project members"""
    success: bool
    message: Optional[str] = None
    project: Optional[ProjectInfo] = None
    members: List[Dict[str, Any]] = []
    pagination: Optional[PaginationInfo] = None
    statistics: Optional[Dict[str, Any]] = None


class AddMemberToProjectResponse(BaseModel):
    """Response model for adding member to project"""
    success: bool
    message: Optional[str] = None
    member: Optional[Dict[str, Any]] = None
    project: Optional[ProjectInfo] = None


def _require_admin_caller(session_data, message: str) -> AdminScope:
    """Resolve the caller's project admin scope, rejecting callers that have none.

    Only root users (every project) and admin users (their assigned projects) have one.
    Session permission names do not count: a consumer holding ``admin`` or
    ``manage_users`` through a global role is refused here.
    """
    scope = resolve_admin_scope(session_data.user_id)
    if not scope.is_admin:
        raise AuthorizationError(
            message=message,
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_user_types": ["root", "admin"]}
        )
    return scope


def _assigned_project_rows(user_id: str, search: Optional[str]) -> List[Any]:
    """An admin user's assigned projects, optionally filtered like ``search_projects``."""
    rows = [
        ProjectInfo(
            project_hash=row.get("project_hash"),
            project_name=row.get("project_name") or "",
            project_description=row.get("project_description"),
        )
        for row in get_admin_project_assignments_with_details(user_id) or []
        if row.get("project_hash")
    ]
    if search is None:
        return rows
    needle = search.strip().lower()
    return [
        row for row in rows
        if needle in (row.project_name or "").lower() or needle in (row.project_description or "").lower()
    ]


@router.get("", response_model=ListProjectsResponse)
async def list_projects(
        limit: int = Query(10, ge=1, le=500, description="Maximum number of projects to return (1-500)."),
        offset: int = Query(0, ge=0, description="Number of projects to skip. Ignored for root callers when `search` is set."),
        search: str = Query(None, description=(
            "Root and admin callers only: case-insensitive substring match on project name or description "
            "(whitespace-only values return 400). Ignored for other callers."
        )),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> ListProjectsResponse:
    """
    List the projects the caller can see, with pagination.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly cookie); any user type.
    - Root users see all active, non-archived projects, newest first (`user_access_level: "admin"`,
      `access_level: "admin_access"`). With `search`, matches are sorted by name and `offset` is ignored.
    - Admin users see only the active, non-archived projects they are assigned to administer, sorted by name
      (`user_access_level: "admin"`, `access_level: "admin_access"`).
    - Everyone else, including consumers whose global role grants the `admin` permission, sees only the
      active, non-archived projects reachable through their user groups (user → user group → project group →
      project), sorted by name (`access_level: "group_access"`).

    **Pagination:** for admin and group-access callers `pagination.total` is the full count. For root callers
    `total` is only the number of rows on this page, so `has_more` is always `false`; keep paging until a page
    has fewer than `limit` rows.

    **Responses:** 400 whitespace-only `search` (root and admin callers); 401 missing, invalid or expired access
    token; 404 caller's user record not found.
    """
    session_token = credentials.credentials
    session_data = validate_session(session_token)

    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    user_data = get_user_by_hash(session_data.user_hash)
    if not user_data:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": session_data.user_hash}
        )

    # Root sees every project and admin users their assigned ones; session permission
    # names (a consumer's global role may carry `admin`) grant no admin view.
    scope = resolve_admin_scope(user_data.id)
    is_admin = scope.is_admin

    if scope.is_root:
        if search:
            projects = search_projects(search, limit)
        else:
            projects = list_all_projects(limit, offset)
    elif is_admin:
        if search and not search.strip():
            raise ValidationError(
                message="Search term cannot be empty",
                error_code=ErrorCode.MISSING_REQUIRED_FIELD,
                details={"field": "search_term"}
            )
        assigned_projects = _assigned_project_rows(user_data.id, search or None)
        total_accessible = len(assigned_projects)
        projects = assigned_projects[offset:offset + limit]
    else:
        # Regular users see only accessible projects
        accessible_projects = get_user_accessible_projects(user_data.id)
        total_accessible = len(accessible_projects)
        projects = accessible_projects[offset:offset + limit] if accessible_projects else []

    # Add access level information
    projects_with_access = []
    for project in projects:
        project_hash = getattr(project, 'project_hash', '')

        if is_admin:
            access_level = "admin_access"
            access_through = "admin_access"
        else:
            # Non-admin users access projects via groups-of-groups chain.
            # get_user_project_permissions() returns GLOBAL permissions, not
            # project-scoped ones, so we report honest group-based access.
            access_level = "group_access"
            access_through = "user_group"

        project_access = ProjectAccessInfo(
            project_hash=project_hash,
            project_name=getattr(project, 'project_name', ''),
            project_description=getattr(project, 'project_description', None),
            access_level=access_level,
            access_through=access_through
        )
        projects_with_access.append(project_access)

    # Pagination: the root path uses DB-level pagination so total is the page size;
    # the other paths track the full count before slicing.
    if scope.is_root:
        total_count = len(projects_with_access)
    else:
        total_count = total_accessible

    pagination = PaginationInfo(
        limit=limit,
        offset=offset,
        total=total_count,
        has_more=offset + limit < total_count
    )

    return ListProjectsResponse(
        success=True,
        projects=projects_with_access,
        pagination=pagination,
        user_access_level="admin" if is_admin else "user"
    )

@router.post("", response_model=CreateProjectResponse)
async def create_new_project(
        project_name: str = Form(..., description="Project name (required, non-empty; names do not have to be unique)."),
        project_description: Optional[str] = Form(None, description="Optional free-text project description."),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> CreateProjectResponse:
    """
    Create a project and bootstrap its default group chain.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly cookie) of a
    root user. Creating a project is a platform operation: admin users (who administer only the projects root
    assigns them) and consumers get 403 whatever permissions their session carries.

    **Request:** form fields (`application/x-www-form-urlencoded` or `multipart/form-data`): `project_name`
    (required) and optional `project_description`.

    **Effects:** the caller is recorded as creator and owner. A dedicated project group containing the new
    project is created, plus three user groups (`admin_…`, `user_…`, `readonly_…`, suffixed with the internal
    project id) that are granted that project group. No users are added to those groups; assign admin users
    with `PUT /user-types/admin/{user_hash}/projects`.

    **Responses:** 200 with the new `project.project_hash`; 400 missing or empty `project_name`;
    401 missing, invalid or expired access token; 403 caller is not a root user.
    """
    session_token = credentials.credentials
    session_data = validate_session(session_token)

    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    # Creating a tenant is a platform operation: root only. Admin users administer the
    # projects root assigns them, and session permission names grant nothing here.
    if not resolve_admin_scope(session_data.user_id).is_root:
        raise AuthorizationError(
            message="Root user access required to create projects",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_user_type": "root"}
        )

    # Get current user for audit trail
    user_data = get_user_by_hash(session_data.user_hash)

    if not project_name:
        raise ValidationError(
            message="Project name is required",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"field": "project_name"}
        )

    # Create project - db layer handles errors
    new_project = create_project(project_name, project_description, created_by=user_data.id, owner_id=user_data.id)

    if not new_project:
        raise InternalError(
            message="Failed to create project",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"project_name": project_name}
        )

    logger.info(f"Project created: {project_name} by user: {user_data.username}")

    project_info = ProjectInfo(
        project_hash=new_project.project_hash,
        project_name=new_project.project_name,
        project_description=new_project.project_description,
        created_at=getattr(new_project, 'project_created', None)
    )

    return CreateProjectResponse(
        success=True,
        message=f"Project \"{project_name}\" created successfully",
        project=project_info
    )


@router.get("/{project_hash}", response_model=ProjectDetailsResponse)
async def get_project_details(
        project_hash: str = Path(..., description="Project hash."),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> ProjectDetailsResponse:
    """
    Get one project's details, statistics and the project groups it belongs to.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly cookie).
    Root users can read any active project, archived ones included; admin users can read the active,
    non-archived projects they are assigned to administer. Other callers (including consumers whose global role
    grants the `admin` permission, and admins on projects they are not assigned) need access through their
    user groups; archived projects are never reachable that way.

    **Response notes:**
    - `user_access.permissions` holds the caller's session permissions when the caller administers the project
      (`access_level: "admin_access"`) and `[]` otherwise.
    - `user_access.user_groups` lists all of the caller's user groups, not only those that grant this project.
    - `project_groups` lists the active project groups that contain the project.

    **Responses:** 401 missing, invalid or expired access token; 403 no access to this project;
    404 unknown or deleted project.
    `statistics` reports group-based access counts; `active_sessions` is null because
    the statistics procedure does not measure sessions.
    """
    session_token = credentials.credentials
    session_data = validate_session(session_token)

    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    # Get project details
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )

    # Get user data
    user_data = get_user_by_hash(session_data.user_hash)

    # Check if user has access to this project.
    # Admin users always have access. Non-admin users must have group-based
    # access (verified via accessible projects list). We do NOT use
    # get_user_project_permissions() here because it returns GLOBAL permissions,
    # not project-scoped ones — a consumer with no global permissions but valid
    # group access would be incorrectly denied.
    session_permissions = getattr(session_data, 'permissions', [])
    # The admin view covers only projects the caller administers (root: all; admin
    # users: assigned). Everyone else, whatever their session permissions, needs
    # group access to the project.
    is_admin = resolve_admin_scope(session_data.user_id).allows_project(project.id)

    if not is_admin:
        accessible = get_user_accessible_projects(user_data.id)
        has_access = any(p.id == project.id for p in accessible)
        if not has_access:
            raise AuthorizationError(
                message="Access denied to this project",
                error_code=ErrorCode.PROJECT_ACCESS_DENIED,
                details={"project_hash": project_hash}
            )

    # Get project statistics
    project_stats = get_project_stats(project.id)

    # Get user groups that have access to this project
    user_groups = get_user_groups_for_user(user_data.id)

    # Get project_groups this project belongs to (groups-of-groups architecture)
    project_groups = get_permission_groups_for_project(project.id)
    project_groups_info = [
        {
            "group_hash": pg.group_hash,
            "group_name": pg.group_name,
            "description": getattr(pg, 'group_description', None)
        }
        for pg in project_groups
    ]

    project_info = ProjectInfo(
        project_hash=project.project_hash,
        project_name=project.project_name,
        project_description=project.project_description,
        created_at=getattr(project, 'project_created', None)
    )

    user_access = {
        "permissions": session_permissions if is_admin else [],
        "access_level": "admin_access" if is_admin else "group_access",
        "user_groups": [group.group_name for group in user_groups]
    }

    return ProjectDetailsResponse(
        success=True,
        project=project_info,
        user_access=user_access,
        statistics=project_stats or {},
        project_groups=project_groups_info
    )

@router.put("/{project_hash}", response_model=UpdateProjectResponse)
async def update_project_details(
        project_hash: str = Path(..., description="Project hash."),
        project_name: Optional[str] = Form(None, description="New project name. Omitted or empty keeps the current name."),
        project_description: Optional[str] = Form(None, description=(
            "New project description. Omitted or empty keeps the current description (it cannot be cleared)."
        )),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> UpdateProjectResponse:
    """
    Update a project's name and/or description.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly cookie) of a
    root user, or of an admin user assigned to administer the project. Consumers get 403 whatever
    permissions their session carries (including `admin` or `manage_users` from a global role). Root may update any active project (archived included); admin
    assignments never cover archived projects.

    **Request:** form fields `project_name` and/or `project_description`; at least one must be non-empty.

    **Responses:** 400 nothing to update; 401 missing, invalid or expired access token; 403 caller is not root
    or an admin user, or does not administer this project; 404 unknown or deleted project.
    """
    session_token = credentials.credentials
    session_data = validate_session(session_token)

    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    # Root administers every project and admin users their assigned ones; session
    # permission names (a consumer's global role may carry them) grant no scope.
    scope = _require_admin_caller(session_data, "Admin permission required")

    # Get project
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )
    require_project_in_scope(scope, project)

    # Get current user for audit trail
    user_data = get_user_by_hash(session_data.user_hash)

    update_name = project_name
    update_description = project_description

    # Update project
    updated_project = update_project(
        project.id,
        project_name=update_name,
        project_description=update_description,
        updated_by=user_data.id
    )

    if not updated_project:
        raise InternalError(
            message="Failed to update project",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"project_hash": project_hash}
        )

    project_info = ProjectInfo(
        project_hash=updated_project.project_hash,
        project_name=updated_project.project_name,
        project_description=updated_project.project_description
    )

    return UpdateProjectResponse(
        success=True,
        message="Project updated successfully",
        project=project_info
    )

@router.delete("/{project_hash}", response_model=DeleteProjectResponse)
async def delete_project_endpoint(
        project_hash: str = Path(..., description="Project hash."),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> DeleteProjectResponse:
    """
    Soft-delete a project.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly cookie) of a
    root user, or of an admin user assigned to administer the project. Consumers get 403 whatever
    permissions their session carries (including `admin` or `manage_users` from a global role).

    **Effects:** the project is marked inactive and removed from every project group, and its stored session
    records are deactivated. Access tokens scoped to the project fail validation (401) on their next use, and
    the project returns 404 on every endpoint afterwards. Its default user groups and project group are kept.

    **Responses:** 401 missing, invalid or expired access token; 403 caller is not root or an admin user, or does
    not administer this project; 404 unknown or already deleted project.
    """
    session_token = credentials.credentials
    session_data = validate_session(session_token)

    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    # Root administers every project and admin users their assigned ones; session
    # permission names (a consumer's global role may carry them) grant no scope.
    scope = _require_admin_caller(session_data, "Admin permission required")

    # Get project
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )
    require_project_in_scope(scope, project)

    # Get current user for audit trail
    user_data = get_user_by_hash(session_data.user_hash)

    # Delete project
    if delete_project(project.id, deleted_by=user_data.id):
        deleted_project_info = ProjectInfo(
            project_hash=project.project_hash,
            project_name=project.project_name,
            project_description=project.project_description
        )

        return DeleteProjectResponse(
            success=True,
            message=f"Project \"{project.project_name}\" deleted successfully",
            deleted_project=deleted_project_info,
            warning="All user group access to this project has been revoked"
        )
    else:
        raise InternalError(
            message="Failed to delete project",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"project_hash": project_hash}
        )

@router.get("/{project_hash}/members", response_model=ProjectMembersResponse)
async def list_project_members(
        project_hash: str = Path(..., description="Project hash."),
        limit: int = Query(50, ge=1, le=100, description="Maximum number of members to return (1-100)."),
        offset: int = Query(0, ge=0, description="Number of members to skip."),
        user_type: Optional[str] = Query(None, description=(
            "Only return members of this exact user type: `root`, `admin` or `consumer`. Omit for all types."
        )),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> ProjectMembersResponse:
    """
    List the users who can access a project, with pagination.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly cookie) of a
    root user, or of an admin user assigned to administer the project. Consumers get 403 whatever
    permissions their session carries (including `admin` or `manage_users` from a global role).

    Members are active users who reach the project through the group chain, plus every active root user.
    Archived projects therefore return no members. Results are ordered by user type, then username.
    - `joined_at` is the earliest group grant (project creation time for root users); `granted_by` is always `null`.
    - `groups` is filled only for consumers and lists all of their user groups, not only those granting this project.
    - `statistics.total_members` is the full count; the per-type and `active_members` counts cover only this page.

    **Responses:** 401 missing, invalid or expired access token; 403 caller is not root or an admin user, or does
    not administer this project; 404 unknown or deleted project.
    """
    session_token = credentials.credentials
    session_data = validate_session(session_token)

    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    # Root administers every project and admin users their assigned ones; session
    # permission names (a consumer's global role may carry them) grant no scope.
    scope = _require_admin_caller(session_data, "Admin permission required to list project members")

    # Get project
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )
    require_project_in_scope(scope, project)

    results, total_count = get_project_members_page(
        project_id=project.id,
        limit=limit,
        offset=offset,
        user_type=user_type,
    )

    # Build members list
    members = []
    for row in results:
        user_id = row["user_id"]
        user_hash = row["user_hash"]
        username = row["username"]
        email = row["email"]
        user_type_val = row["user_type"]
        is_active = row["is_active"]
        created_at = row["created_at"]
        granted_at = row["granted_at"]
        granted_by = row["granted_by"]

        # Get user groups for consumer users.
        # We do NOT call get_user_project_permissions() per-member because it
        # returns GLOBAL permissions (ignores project_id), making per-member
        # access_level labels misleading and causing N+1 DB round-trips.
        groups = []
        if user_type_val == 'consumer':
            user_groups = get_user_groups_for_user(user_id)
            groups = [g.group_name for g in user_groups]

        # access_level reflects the user's type within this project context,
        # not their global permissions.
        if user_type_val == 'root':
            member_access_level = "root_access"
        elif user_type_val == 'admin':
            member_access_level = "admin_access"
        else:
            member_access_level = "group_access"

        member_info = {
            "user_hash": user_hash,
            "username": username,
            "email": email,
            "user_type": user_type_val,
            "is_active": is_active,
            "groups": groups,
            "access_level": member_access_level,
            "joined_at": granted_at,
            "granted_by": granted_by,
            "created_at": created_at
        }

        members.append(member_info)

    project_info = ProjectInfo(
        project_hash=project.project_hash,
        project_name=project.project_name,
        project_description=project.project_description
    )

    pagination = PaginationInfo(
        limit=limit,
        offset=offset,
        total=total_count,
        has_more=offset + limit < total_count
    )

    # Build statistics
    stats = {
        "total_members": total_count,
        "root_users": len([m for m in members if m["user_type"] == "root"]),
        "admin_users": len([m for m in members if m["user_type"] == "admin"]),
        "consumer_users": len([m for m in members if m["user_type"] == "consumer"]),
        "active_members": len([m for m in members if m["is_active"]])
    }

    return ProjectMembersResponse(
        success=True,
        project=project_info,
        members=members,
        pagination=pagination,
        statistics=stats
    )

# REMOVED: Direct user-to-project assignment endpoints
# Users can ONLY access projects through user groups.
# To add users to a project:
#   1. Add user to a user group: POST /admin/user-groups/{group_hash}/members
#   2. Put the project in a project group: POST /admin/project-groups/{group_hash}/projects
#   3. Grant the user group that project group: POST /admin/user-groups/{group_hash}/project-groups
#
# The following endpoints have been removed to enforce group-based access:
#   - POST /projects/{project_hash}/members (add user directly)
#   - DELETE /projects/{project_hash}/members/{user_hash} (remove user directly)
#
# Use the admin user-groups endpoints instead for proper group-based access control.


@router.get("/{project_hash}/activity")
async def get_project_activity(
        project_hash: str = Path(..., description="Project hash."),
        limit: int = Query(50, ge=1, le=100, description="Maximum number of activity entries to return (1-100)."),
        offset: int = Query(0, ge=0, description="Number of activity entries to skip."),
        activity_type: Optional[str] = Query(None, description=(
            "Only return entries with this exact activity type code (for example `user_login`)."
        )),
        days: int = Query(30, ge=1, le=365, description="Look-back window in days (1-365)."),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Get a project's activity-log feed, newest first, with pagination.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly cookie).
    Root users can read any active project and admin users the projects they are assigned to administer; other
    callers (including consumers whose global role grants the `admin` permission) need access through their
    user groups (never granted for archived projects).

    Entries are filtered by `activity_type` and the `days` window; `pagination.total` is the real filtered
    count. Each entry includes the acting user, IP address, user agent and metadata.

    **Responses:** 401 missing, invalid or expired access token; 403 no access to this project;
    404 unknown or deleted project.
    """
    session_token = credentials.credentials
    session_data = validate_session(session_token)

    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    # Get project
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )

    # Check user access to project
    current_user = get_user_by_hash(session_data.user_hash)
    # The admin view covers only projects the caller administers (root: all; admin
    # users: assigned). Everyone else, whatever their session permissions, needs
    # group access to the project.
    is_admin = resolve_admin_scope(session_data.user_id).allows_project(project.id)

    if not is_admin:
        accessible = get_user_accessible_projects(current_user.id)
        has_access = any(p.id == project.id for p in accessible)
        if not has_access:
            raise AuthorizationError(
                message="Access denied to this project",
                error_code=ErrorCode.PROJECT_ACCESS_DENIED,
                details={"project_hash": project_hash}
            )

    # Get project activities
    activities = get_recent_activity(
        limit=limit,
        offset=offset,
        project_id=project.id,
        activity_type=activity_type,
        days=days
    )

    # Get total count for honest pagination
    total_count = count_activity_logs(
        project_id=project.id,
        activity_type=activity_type,
        days=days
    )

    # Format response to match expected structure
    activities = {
        "activities": activities,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "total": total_count,
            "has_more": offset + limit < total_count
        }
    }

    return {
        "success": True,
        "project": {
            "project_hash": project.project_hash,
            "project_name": project.project_name
        },
        "activities": activities["activities"],
        "pagination": activities["pagination"],
        "filters": {
            "activity_type": activity_type,
            "days": days
        },
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }

@router.get("/{project_hash}/stats")
async def get_detailed_project_stats(
        project_hash: str = Path(..., description="Project hash."),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Get a project's summary and access statistics.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly cookie).
    Root users can read any active project and admin users the projects they are assigned to administer; other
    callers (including consumers whose global role grants the `admin` permission) need access through their
    user groups (never granted for archived projects).

    Returns the project's hash, name and description, the same `statistics` object embedded in the project
    details response, and a `generated_at` timestamp. No activity metrics or health scores are computed.

    **Responses:** 401 missing, invalid or expired access token; 403 no access to this project;
    404 unknown or deleted project.
    `statistics` reports group-based access counts; `active_sessions` is null because
    the statistics procedure does not measure sessions.
    """
    session_token = credentials.credentials
    session_data = validate_session(session_token)

    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    # Get project
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )

    # Check user access to project
    current_user = get_user_by_hash(session_data.user_hash)
    # The admin view covers only projects the caller administers (root: all; admin
    # users: assigned). Everyone else, whatever their session permissions, needs
    # group access to the project.
    is_admin = resolve_admin_scope(session_data.user_id).allows_project(project.id)

    if not is_admin:
        accessible = get_user_accessible_projects(current_user.id)
        has_access = any(p.id == project.id for p in accessible)
        if not has_access:
            raise AuthorizationError(
                message="Access denied to this project",
                error_code=ErrorCode.PROJECT_ACCESS_DENIED,
                details={"project_hash": project_hash}
            )

    # Get detailed project statistics
    stats = get_project_stats(project.id) or {}

    return {
        "success": True,
        "project": {
            "project_hash": project.project_hash,
            "project_name": project.project_name,
            "project_description": project.project_description
        },
        "statistics": stats,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }

@router.patch(
    "/{project_hash}/owner",
    responses={501: {"description": "Not implemented: returned for every request that passes validation."}},
)
async def transfer_project_ownership(
        project_hash: str = Path(..., description="Project hash."),
        new_owner_hash: str = Form(..., description="User hash of the proposed new owner (must be an active user)."),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Not implemented: validates a project ownership transfer request, then always returns 501.

    Ownership is never changed; the route is reserved for a future implementation.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly cookie) of a
    root user, or of an admin user assigned to administer the project. Consumers get 403 whatever
    permissions their session carries (including `admin` or `manage_users` from a global role).

    **Request:** form field `new_owner_hash`.

    **Responses:** 400 missing `new_owner_hash`; 401 missing, invalid or expired access token; 403 caller is not
    root or an admin user, or does not administer this project; 404 unknown project or new owner; otherwise 501 with error code `FEATURE_NOT_IMPLEMENTED`.
    """
    session_token = credentials.credentials
    session_data = validate_session(session_token)

    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    # Root administers every project and admin users their assigned ones; session
    # permission names (a consumer's global role may carry them) grant no scope.
    scope = _require_admin_caller(session_data, "Admin permission required to transfer project ownership")

    # Get project and users
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )
    require_project_in_scope(scope, project)

    new_owner = get_user_by_hash(new_owner_hash)
    if not new_owner:
        raise NotFoundError(
            message="New owner not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": new_owner_hash}
        )

    current_user = get_user_by_hash(session_data.user_hash)

    # Ownership transfer not yet implemented — return 501 Not Implemented
    raise FeatureNotImplementedError(
        message="Project ownership transfer is not yet implemented",
        error_code=ErrorCode.FEATURE_NOT_IMPLEMENTED,
        details={
            "operation": "transfer_ownership",
            "project_hash": project_hash,
            "status": "planned",
            "note": "This endpoint is reserved for future implementation"
        }
    )

@router.patch(
    "/{project_hash}/archive",
    responses={501: {"description": "Not implemented: returned for every request that passes validation."}},
)
async def archive_unarchive_project(
        project_hash: str = Path(..., description="Project hash."),
        archived: bool = Form(..., description="`true` to archive, `false` to unarchive (currently has no effect)."),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Not implemented: validates a project archive/unarchive request, then always returns 501.

    The archive flag is never changed through the API. Projects whose archive flag is set in the database are
    excluded from project listings, group-based access, member lists, login project selection and access-token
    validation.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly cookie) of a
    root user, or of an admin user assigned to administer the project. Consumers get 403 whatever
    permissions their session carries (including `admin` or `manage_users` from a global role).

    **Request:** form field `archived` (boolean).

    **Responses:** 400 missing or non-boolean `archived`; 401 missing, invalid or expired access token; 403
    caller is not root or an admin user, or does not administer this project; 404 unknown project; otherwise 501 with error code `FEATURE_NOT_IMPLEMENTED`.
    """
    session_token = credentials.credentials
    session_data = validate_session(session_token)

    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    # Root administers every project and admin users their assigned ones; session
    # permission names (a consumer's global role may carry them) grant no scope.
    scope = _require_admin_caller(session_data, "Admin permission required to archive/unarchive projects")

    # Get project
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )
    require_project_in_scope(scope, project)

    current_user = get_user_by_hash(session_data.user_hash)

    # Archive/unarchive not yet implemented — return 501 Not Implemented
    raise FeatureNotImplementedError(
        message="Project archive/unarchive is not yet implemented",
        error_code=ErrorCode.FEATURE_NOT_IMPLEMENTED,
        details={
            "operation": "archive_project",
            "project_hash": project_hash,
            "archived": archived,
            "status": "planned",
            "note": "This endpoint is reserved for future implementation"
        }
    )


# =================== NEW GROUP-PROJECT ENDPOINTS ===================

@router.get("/{project_hash}/groups", response_model=ListUserGroupsResponse)
async def list_project_user_groups(
        project_hash: str = Path(..., description="Project hash."),
        limit: int = Query(100, ge=1, le=500, description="Maximum number of user groups to return (1-500)."),
        offset: int = Query(0, ge=0, description="Number of user groups to skip."),
        credentials: HTTPAuthorizationCredentials = Depends(security)) -> ListUserGroupsResponse:
    """
    List the user groups that can access a project through its project groups.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly cookie) of a
    root user, or of an admin user assigned to administer the project. Consumers get 403 whatever
    permissions their session carries (including `admin` or `manage_users` from a global role).

    Groups are sorted by name and include their active `member_count`; `pagination.total` is the full count.
    Read-only: grant access by adding the project to a project group
    (`POST /admin/project-groups/{group_hash}/projects`) and granting a user group that project group
    (`POST /admin/user-groups/{group_hash}/project-groups`).

    **Responses:** 401 missing, invalid or expired access token; 403 caller is not root or an admin user, or does
    not administer this project; 404 unknown or deleted project.
    """

    # Validate session
    session_token = credentials.credentials
    session_data = validate_session(session_token)
    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    # Root administers every project and admin users their assigned ones; session
    # permission names (a consumer's global role may carry them) grant no scope.
    scope = _require_admin_caller(session_data, "Admin permission required to list project groups")

    # Resolve project
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )
    require_project_in_scope(scope, project)

    # Fetch groups
    groups_all = get_user_groups_for_project(project.id)
    groups_paginated = groups_all[offset:offset + limit]

    user_groups_info = []
    for grp in groups_paginated:
        user_groups_info.append(UserGroupInfo(
            group_hash=grp.group_hash,
            group_name=grp.group_name,
            description=grp.group_description,
            member_count=grp.member_count,
            created_at=grp.created_at,
            updated_at=grp.updated_at
        ))

    pagination = PaginationInfo(
        limit=limit,
        offset=offset,
        total=len(groups_all),
        has_more=(offset + limit) < len(groups_all)
    )

    return ListUserGroupsResponse(
        success=True,
        user_groups=user_groups_info,
        pagination=pagination
    )


# ===================================================================================
# GROUPS-OF-GROUPS ARCHITECTURE NOTE
# ===================================================================================
# Direct user group → project assignment is NOT supported.
# The system uses GROUPS-OF-GROUPS architecture:
#
#   USER → USER_GROUP → PROJECT_GROUP → PROJECT
#
# To grant a user group access to a project:
#   1. Create/use a Project Group: POST /admin/project-groups
#   2. Add project to Project Group: POST /admin/project-groups/{hash}/projects
#   3. Grant User Group access to Project Group: POST /admin/user-groups/{hash}/project-groups
#
# This ensures proper access control hierarchy and scalability.
# ===================================================================================
