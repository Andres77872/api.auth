"""
Admin User Group Management Routes

Handles global user group administration including creation, management,
and access control for the group-based multi-project authentication system.
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, Query, Path, Form, Body
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from src.Util.Models import (
    ListUserGroupsResponse, CreateUserGroupResponse, UserGroupDetailsResponse,
    UpdateUserGroupResponse, DeleteUserGroupResponse, AssignUserToGroupResponse,
    RemoveUserFromGroupResponse, UserInfo, UserGroupInfo, ProjectInfo, PaginationInfo, 
    GroupMembersPaginatedResponse, BulkAddUsersToGroupRequest, BulkAddUsersToGroupResponse, 
    UserGroupsForUserResponse,
    # Groups-of-Groups Architecture models
    GrantUserGroupProjectGroupAccessResponse, RevokeUserGroupProjectGroupAccessResponse,
    ListProjectGroupsForUserGroupResponse
)
from src.Util.security import HTTPBearerOrCookie
from src.Util.activity_logger import ActivityLogger, ActivityType
from src.Util.db import (
    validate_session, get_user_by_hash,
    create_user_group, get_user_group_by_hash,
    list_all_user_groups, update_user_group,
    delete_user_group, assign_user_to_user_group,
    remove_user_from_user_group, get_users_in_group,
    get_projects_for_user_group, get_user_groups_for_user,
    get_total_user_groups_count,
    # Groups-of-Groups Architecture functions
    grant_user_group_project_group_access, revoke_user_group_project_group_access,
    get_project_groups_for_user_group,
    # Project group functions
    get_project_group_by_hash
)
from src.Util.admin_scope import is_project_admin_group_name
from src.Util.db import is_root_user
from src.Util.error_handler import (
    AuthenticationError, AuthorizationError, ValidationError,
    NotFoundError, ConflictError, InternalError, ErrorCode
)
from src.Util.auth_lifecycle import revoke_project_sessions_losing_access
from src.Util.db.db_project_groups import get_projects_in_group

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/admin/user-groups", tags=["Admin - User Groups"])
security = HTTPBearerOrCookie()


# Note: Write endpoints take Form data, except POST /{group_hash}/members/bulk which takes a JSON body.


# Helper function to check admin permissions
async def require_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Ensure user has admin permissions.

    Checks ``'admin'`` OR ``'manage_users'`` in session permissions.
    Differs from ``global_roles.py:require_admin()`` because user group
    management uses the ``manage_users`` delegated permission — consumers
    with ``manage_roles`` should NOT manage user groups.  This is
    intentional least-privilege.
    """
    session_data = validate_session(credentials.credentials)
    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    user_permissions = session_data.permissions if hasattr(session_data, 'permissions') else []
    if 'admin' not in user_permissions and 'manage_users' not in user_permissions:
        raise AuthorizationError(
            message="Admin or manage_users permission required",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_permissions": ["admin", "manage_users"]}
        )

    return session_data


def _require_root_for_admin_group(session_data, *group_names) -> None:
    """Only root may change a group that can hold project admin assignments.

    ``sp_get_admin_assigned_projects`` treats membership of ``admin_<project_id>`` (granted
    the project's project group) as admin assignment, compared the MySQL collation's way.
    Letting any admin edit such a group -- members, project-group grants, name, or the group
    itself -- would let it assign itself to any project; assignments are root's to make
    (``PUT /user-types/admin/{user_hash}/projects``).
    """
    if any(is_project_admin_group_name(name) for name in group_names) and not is_root_user(session_data.user_id):
        raise AuthorizationError(
            message="Only root users may change project admin groups",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_user_type": "root"}
        )


@router.get("", response_model=ListUserGroupsResponse)
async def list_user_groups(
        limit: int = Query(50, ge=1, le=1000, description="Maximum number of groups to return (1-1000)."),
        offset: int = Query(0, ge=0, description="Number of groups to skip."),
        sort_by: str = Query('group_name', description=(
            "Sort field: `group_name` (default), `created_at` or `updated_at`. Any other value sorts by `group_name`."
        )),
        sort_order: str = Query('asc', description="`desc` (case-insensitive) for descending; any other value sorts ascending."),
        search: str = Query(None, description="Case-insensitive substring match on the group name."),
        session_data=Depends(require_admin)
) -> ListUserGroupsResponse:
    """
    List active user groups with their member counts.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly cookie); the
    session must carry `admin` or `manage_users` (every root/admin session does; consumers only through a
    global role).

    **Pagination:** `pagination.total` counts all active groups and ignores `search`; `has_more` is not
    populated (`null`).

    **Responses:** 401 missing, invalid or expired access token; 403 missing permission.
    """
    # Get all user groups with sorting parameters
    user_groups = list_all_user_groups(limit, offset, sort_by, sort_order, search)

    # Add member counts
    groups_with_counts = []
    for group in user_groups:
        members = get_users_in_group(group.id)
        group_info = UserGroupInfo(
            group_hash=group.group_hash,
            group_name=group.group_name,
            description=group.group_description,
            member_count=len(members),
            created_at=group.created_at
        )
        groups_with_counts.append(group_info)

    # Get total count for pagination
    total_count = get_total_user_groups_count()
    
    pagination = PaginationInfo(
        limit=limit,
        offset=offset,
        total=total_count
    )

    return ListUserGroupsResponse(
        success=True,
        user_groups=groups_with_counts,
        pagination=pagination
    )

@router.post("", response_model=CreateUserGroupResponse)
async def create_user_group_endpoint(
        group_name: str = Form(..., description="Unique group name (required, non-empty)."),
        description: Optional[str] = Form(None, description="Optional group description."),
        session_data=Depends(require_admin)
) -> CreateUserGroupResponse:
    """
    Create a global user group.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly cookie); the
    session must carry `admin` or `manage_users`.
    Only root users may change groups whose name starts with `admin_` (they hold project admin
    assignments); other callers get 403.

    **Request:** form fields `group_name` (required) and optional `description`. The group starts with no
    members and no project-group grants.

    **Responses:** 400 missing or empty `group_name`; 401 missing, invalid or expired access token; 403 missing
    permission; 409 name already in use (names of deleted groups stay reserved).
    """
    # Get current user for audit trail
    user_data = get_user_by_hash(session_data.user_hash)

    if not group_name:
        raise ValidationError(
            message="Group name is required",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"field": "group_name"}
        )
    _require_root_for_admin_group(session_data, group_name)

    # Create user group - db layer converts IntegrityError to ConflictError automatically
    new_group = create_user_group(
        group_name,
        description,
        created_by=user_data.id
    )

    if not new_group:
        raise InternalError(
            message="User group creation failed",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "create_user_group"}
        )

    group_info = UserGroupInfo(
        group_hash=new_group.group_hash,
        group_name=new_group.group_name,
        description=new_group.group_description,
        created_at=new_group.created_at
    )

    return CreateUserGroupResponse(
        success=True,
        message=f"User group \"{group_name}\" created successfully",
        user_group=group_info
    )


@router.get("/{group_hash}", response_model=UserGroupDetailsResponse)
async def get_user_group_details(
        group_hash: str = Path(..., description="User group hash."),
        session_data=Depends(require_admin)
) -> UserGroupDetailsResponse:
    """
    Get a user group with its members, granted project groups and reachable projects.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly cookie); the
    session must carry `admin` or `manage_users`.

    - `members`: active users in the group.
    - `accessible_project_groups`: active project groups granted to this group.
    - `accessible_projects`: active, non-archived projects reachable through those project groups
      (there is no direct user group → project access).
    - `derived_projects` is always empty and `statistics.total_derived_projects` is always 0.

    **Responses:** 401 missing, invalid or expired access token; 403 missing permission;
    404 unknown or deleted group.
    """
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )

    # Get members
    members = get_users_in_group(user_group.id)

    # Projects reachable through this group's project groups (active, non-archived)
    accessible_projects = get_projects_for_user_group(user_group.id)

    # Get project groups (groups-of-groups architecture)
    project_groups = get_project_groups_for_user_group(user_group.id)

    group_info = UserGroupInfo(
        group_hash=user_group.group_hash,
        group_name=user_group.group_name,
        description=user_group.group_description,
        created_at=user_group.created_at
    )

    member_list = [
        UserInfo(
            user_hash=member.user_hash,
            username=member.username,
            email=member.email
        ) for member in members
    ]

    # Projects derived via project groups (rows: id, project_hash, project_name, project_description)
    project_list = [
        ProjectInfo(
            project_hash=project[1],
            project_name=project[2]
        ) for project in accessible_projects
    ]

    # Note: project_count is not available from the stored procedure
    # total_derived_projects would require a separate query to count projects in each project group
    statistics_info = {
        "total_members": len(members),
        "total_projects": len(accessible_projects),
        "total_project_groups": len(project_groups),
        "total_derived_projects": 0  # Would require separate query to calculate
    }

    return UserGroupDetailsResponse(
        success=True,
        user_group=group_info,
        members=member_list,
        accessible_projects=project_list,
        accessible_project_groups=project_groups,
        derived_projects=[],  # Could be populated with actual derived projects if needed
        statistics=statistics_info
    )

@router.put("/{group_hash}", response_model=UpdateUserGroupResponse)
async def update_user_group_endpoint(
        group_hash: str = Path(..., description="User group hash."),
        group_name: Optional[str] = Form(None, description="New unique group name. Omitted or empty keeps the current name."),
        description: Optional[str] = Form(None, description=(
            "New description. Omitted or empty keeps the current description (it cannot be cleared)."
        )),
        session_data=Depends(require_admin)
) -> UpdateUserGroupResponse:
    """
    Rename a user group and/or change its description.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly cookie); the
    session must carry `admin` or `manage_users`.
    Only root users may change groups whose name starts with `admin_` (they hold project admin
    assignments); other callers get 403.

    **Request:** form fields `group_name` and/or `description`; at least one must be non-empty.

    **Responses:** 400 nothing to update; 401 missing, invalid or expired access token; 403 missing permission;
    404 unknown or deleted group; 409 name already in use.
    """
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    _require_root_for_admin_group(session_data, user_group.group_name, group_name)

    update_name = group_name
    update_description = description

    # Update group
    updated_group = update_user_group(
        user_group.id,
        group_name=update_name,
        group_description=update_description
    )

    if not updated_group:
        raise InternalError(
            message="Update failed",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "update_user_group"}
        )

    group_info = UserGroupInfo(
        group_hash=updated_group.group_hash,
        group_name=updated_group.group_name,
        description=updated_group.group_description
    )

    return UpdateUserGroupResponse(
        success=True,
        message="User group updated successfully",
        user_group=group_info
    )

@router.delete("/{group_hash}", response_model=DeleteUserGroupResponse)
async def delete_user_group_endpoint(
        group_hash: str = Path(..., description="User group hash."),
        session_data=Depends(require_admin)
) -> DeleteUserGroupResponse:
    """
    Soft-delete a user group.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly cookie); the
    session must carry `admin` or `manage_users`.
    Only root users may change groups whose name starts with `admin_` (they hold project admin
    assignments); other callers get 403.

    **Effects:** the group, all of its memberships and all of its project-group grants are deactivated. Active
    project-scoped sessions (and their refresh-token families) of former members are then revoked for projects
    they can no longer reach through another group. The group name stays reserved.

    **Responses:** 401 missing, invalid or expired access token; 403 missing permission;
    404 unknown or already deleted group.
    """
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    _require_root_for_admin_group(session_data, user_group.group_name)

    # Get current user for audit trail
    user_data = get_user_by_hash(session_data.user_hash)

    affected_user_ids = [user.id for user in get_users_in_group(user_group.id)]
    affected_project_ids = [project[0] for project in get_projects_for_user_group(user_group.id)]

    # Delete group
    if delete_user_group(user_group.id, deleted_by=user_data.id):
        revoke_project_sessions_losing_access(
            user_ids=affected_user_ids,
            project_ids=affected_project_ids,
            reason="user_group_deleted",
        )
        return DeleteUserGroupResponse(
            success=True,
            message=f"User group \"{user_group.group_name}\" deleted successfully",
            warning="All user memberships and project access have been revoked"
        )
    else:
        raise InternalError(
            message="Delete failed",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "delete_user_group"}
        )

@router.post("/{group_hash}/members", response_model=AssignUserToGroupResponse)
async def assign_user_to_group_endpoint(
        group_hash: str = Path(..., description="User group hash."),
        user_hash: str = Form(..., description="Hash of the active user to add."),
        session_data=Depends(require_admin)
) -> AssignUserToGroupResponse:
    """
    Add a user to a user group.

    The user gains access to every project reachable through the group's project groups.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly cookie); the
    session must carry `admin` or `manage_users`.
    Only root users may change groups whose name starts with `admin_` (they hold project admin
    assignments); other callers get 403.

    **Request:** form field `user_hash`. Idempotent: adding a current or previously removed member
    (re)activates the membership and returns 200.

    **Responses:** 400 missing `user_hash`; 401 missing, invalid or expired access token; 403 missing permission;
    404 unknown group or unknown/inactive user.
    """
    target_user_hash = user_hash

    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    _require_root_for_admin_group(session_data, user_group.group_name)

    # Get target user
    target_user = get_user_by_hash(target_user_hash)
    if not target_user:
        raise NotFoundError(
            message="Target user not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": target_user_hash}
        )

    # Get current user for audit trail
    current_user = get_user_by_hash(session_data.user_hash)

    # Assign user to group
    assignment_result = assign_user_to_user_group(
        target_user.id,
        user_group.id,
        assigned_by=current_user.id
    )

    if not assignment_result:
        raise InternalError(
            message="Assignment failed",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "assign_user_to_user_group"}
        )

    assignment_info = {
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

    return AssignUserToGroupResponse(
        success=True,
        message=f"User \"{target_user.username}\" assigned to group \"{user_group.group_name}\"",
        assignment=assignment_info
    )

@router.delete("/{group_hash}/members/{user_hash}", response_model=RemoveUserFromGroupResponse)
async def remove_user_from_group_endpoint(
        group_hash: str = Path(..., description="User group hash."),
        user_hash: str = Path(..., description="Hash of the active user to remove."),
        session_data=Depends(require_admin)
) -> RemoveUserFromGroupResponse:
    """
    Remove a user from a user group.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly cookie); the
    session must carry `admin` or `manage_users`.
    Only root users may change groups whose name starts with `admin_` (they hold project admin
    assignments); other callers get 403.

    Returns 200 even if the user was not a member. Sessions are not revoked here; a consumer access token for a
    project the user can no longer reach fails validation (401) on its next use.

    **Responses:** 401 missing, invalid or expired access token; 403 missing permission; 404 unknown group or
    unknown/inactive user.
    """
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    _require_root_for_admin_group(session_data, user_group.group_name)

    # Get target user
    target_user = get_user_by_hash(user_hash)
    if not target_user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": user_hash}
        )

    # Get current user for audit trail
    current_user = get_user_by_hash(session_data.user_hash)

    # Remove user from group
    if remove_user_from_user_group(target_user.id, user_group.id, removed_by=current_user.id):
        return RemoveUserFromGroupResponse(
            success=True,
            message=f"User \"{target_user.username}\" removed from group \"{user_group.group_name}\""
        )
    else:
        raise InternalError(
            message="Removal failed",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "remove_user_from_user_group"}
        )

# =================== GROUPS-OF-GROUPS ARCHITECTURE ENDPOINTS ===================
# These endpoints follow the correct architecture: USER → USER_GROUP → PROJECT_GROUP → PROJECT

@router.post("/{group_hash}/project-groups", response_model=GrantUserGroupProjectGroupAccessResponse)
async def grant_user_group_project_group_access_endpoint(
        group_hash: str = Path(..., description="User group hash."),
        project_group_hash: str = Form(..., description="Hash of the project group to grant."),
        session_data=Depends(require_admin)
) -> GrantUserGroupProjectGroupAccessResponse:
    """
    Grant a user group access to a project group.

    Every member of the user group gains access to every active, non-archived project in the project group
    (user → user group → project group → project). This is the only way to give a user group project access.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly cookie); the
    session must carry `admin` or `manage_users`.
    Only root users may change groups whose name starts with `admin_` (they hold project admin
    assignments); other callers get 403.

    **Request:** form field `project_group_hash`. Idempotent: re-granting reactivates the existing link and
    returns 200, but `access_details.access_id` is freshly generated and may not match the stored link.

    **Responses:** 400 missing `project_group_hash`; 401 missing, invalid or expired access token; 403 missing
    permission; 404 unknown user group or project group.
    """
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    _require_root_for_admin_group(session_data, user_group.group_name)

    # Get project group
    project_group = get_project_group_by_hash(project_group_hash)
    if not project_group:
        raise NotFoundError(
            message="Project group not found",
            error_code=ErrorCode.RESOURCE_NOT_FOUND,
            details={"project_group_hash": project_group_hash}
        )

    # Get current user for audit trail
    current_user = get_user_by_hash(session_data.user_hash)

    # Grant access via groups-of-groups architecture
    access_result = grant_user_group_project_group_access(
        user_group.id,
        project_group.id,
        granted_by=current_user.id
    )

    if not access_result:
        raise InternalError(
            message="Access grant failed",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "grant_user_group_project_group_access"}
        )

    return GrantUserGroupProjectGroupAccessResponse(
        success=True,
        message=f"User group \"{user_group.group_name}\" granted access to project group \"{project_group.group_name}\"",
        access_details=access_result,
        user_group={
            "group_hash": user_group.group_hash,
            "group_name": user_group.group_name
        },
        project_group={
            "group_hash": project_group.group_hash,
            "group_name": project_group.group_name
        }
    )


@router.delete("/{group_hash}/project-groups/{project_group_hash}", response_model=RevokeUserGroupProjectGroupAccessResponse)
async def revoke_user_group_project_group_access_endpoint(
        group_hash: str = Path(..., description="User group hash."),
        project_group_hash: str = Path(..., description="Hash of the project group whose grant is revoked."),
        session_data=Depends(require_admin)
) -> RevokeUserGroupProjectGroupAccessResponse:
    """
    Revoke a user group's access to a project group.

    Members lose access to the project group's projects unless another user group → project group link still
    grants them. Their active project-scoped sessions (and refresh-token families) for projects they can no
    longer reach are revoked.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly cookie); the
    session must carry `admin` or `manage_users`.
    Only root users may change groups whose name starts with `admin_` (they hold project admin
    assignments); other callers get 403.

    **Responses:** 401 missing, invalid or expired access token; 403 missing permission; 404 unknown user group
    or project group; 500 when no active grant exists between the two groups.
    """
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    _require_root_for_admin_group(session_data, user_group.group_name)

    # Get project group
    project_group = get_project_group_by_hash(project_group_hash)
    if not project_group:
        raise NotFoundError(
            message="Project group not found",
            error_code=ErrorCode.RESOURCE_NOT_FOUND,
            details={"project_group_hash": project_group_hash}
        )

    # Get current user for audit trail
    current_user = get_user_by_hash(session_data.user_hash)

    affected_user_ids = [user.id for user in get_users_in_group(user_group.id)]
    affected_project_ids = [project.id for project in get_projects_in_group(project_group.id)]

    # Revoke access
    if revoke_user_group_project_group_access(user_group.id, project_group.id, revoked_by=current_user.id):
        revoke_project_sessions_losing_access(
            user_ids=affected_user_ids,
            project_ids=affected_project_ids,
            reason="user_group_project_group_access_revoked",
        )
        return RevokeUserGroupProjectGroupAccessResponse(
            success=True,
            message=f"User group \"{user_group.group_name}\" access to project group \"{project_group.group_name}\" revoked"
        )
    else:
        raise InternalError(
            message="Revocation failed",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "revoke_user_group_project_group_access"}
        )


@router.get("/{group_hash}/project-groups", response_model=ListProjectGroupsForUserGroupResponse)
async def list_project_groups_for_user_group(
        group_hash: str = Path(..., description="User group hash."),
        session_data=Depends(require_admin)
) -> ListProjectGroupsForUserGroupResponse:
    """
    List the active project groups granted to a user group.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly cookie); the
    session must carry `admin` or `manage_users`.

    Entries are sorted by name and carry `group_id`, `group_hash`, `group_name`, `group_description`,
    `created_at`, `is_active`, `granted_at` and `granted_by`. No per-group project counts are returned, and
    `total_derived_projects` is always 0.

    **Responses:** 401 missing, invalid or expired access token; 403 missing permission;
    404 unknown or deleted user group.
    """
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )

    # Get project groups for this user group
    project_groups = get_project_groups_for_user_group(user_group.id)

    user_group_info = UserGroupInfo(
        group_hash=user_group.group_hash,
        group_name=user_group.group_name,
        description=user_group.group_description
    )

    return ListProjectGroupsForUserGroupResponse(
        success=True,
        user_group=user_group_info,
        project_groups=project_groups,
        total_project_groups=len(project_groups),
        total_derived_projects=0  # Would require separate query to calculate
    )


@router.get("/{group_hash}/members", response_model=GroupMembersPaginatedResponse)
async def get_group_members_with_pagination(
        group_hash: str = Path(..., description="User group hash."),
        limit: int = Query(50, ge=1, le=100, description="Maximum number of members to return (1-100)."),
        offset: int = Query(0, ge=0, description="Number of members to skip."),
        session_data=Depends(require_admin)
) -> GroupMembersPaginatedResponse:
    """
    List a user group's active members, with pagination.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly cookie); the
    session must carry `admin` or `manage_users`.

    Members are sorted by username; inactive users are excluded. `joined_at` is when the membership was last
    (re)activated. `pagination.total` and `statistics.total_members` are the full member count.

    **Responses:** 401 missing, invalid or expired access token; 403 missing permission;
    404 unknown or deleted group.
    """
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )

    # Get all members first for total count
    all_members = get_users_in_group(user_group.id)
    total_count = len(all_members)

    # Apply pagination
    paginated_members = all_members[offset:offset + limit]

    # Format member data
    members_data = []
    for member in paginated_members:
        # Use assigned_at from the membership record as joined_at
        # This is set by get_users_in_group from sp_get_users_in_group stored procedure
        joined_date = getattr(member, 'assigned_at', None)
        member_info = {
            "user_hash": member.user_hash,
            "username": member.username,
            "email": member.email,
            "user_type": getattr(member, 'user_type', 'consumer'),
            "is_active": getattr(member, 'is_active', True),
            "joined_at": (joined_date.isoformat() + "Z") if joined_date else None  # API uses joined_at for membership date
        }
        members_data.append(member_info)

    pagination_info = PaginationInfo(
        limit=limit,
        offset=offset,
        total=total_count,
        has_more=offset + limit < total_count
    )

    user_group_info = UserGroupInfo(
        group_hash=user_group.group_hash,
        group_name=user_group.group_name,
        description=user_group.group_description
    )

    return GroupMembersPaginatedResponse(
        success=True,
        user_group=user_group_info,
        members=members_data,
        pagination=pagination_info,
        statistics={
            "total_members": total_count,
            "members_shown": len(members_data)
        },
        generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )

@router.post("/{group_hash}/members/bulk", response_model=BulkAddUsersToGroupResponse)
async def bulk_add_users_to_group(
        group_hash: str = Path(..., description="User group hash."),
        request: BulkAddUsersToGroupRequest = Body(..., description="JSON object with `user_hashes` (1-100 user hashes)."),
        session_data=Depends(require_admin)
) -> BulkAddUsersToGroupResponse:
    """
    Add up to 100 users to a user group in one request.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly cookie); the
    session must carry `admin` or `manage_users`.
    Only root users may change groups whose name starts with `admin_` (they hold project admin
    assignments); other callers get 403.

    **Request:** JSON body (`application/json`, not form data): `{"user_hashes": ["<user hash>", ...]}`.

    Once the group is found the response is 200 with `success: true` even if some or all users fail. Unknown or
    inactive users are listed in `errors`; every other user gets a `results` entry (existing members are
    reactivated and count as successes); `summary` holds the requested/success/error counts. One
    `bulk_group_assignment` activity entry is logged.

    **Responses:** 400 malformed body, empty list or more than 100 hashes; 401 missing, invalid or expired
    access token; 403 missing permission; 404 unknown or deleted group.
    """
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    _require_root_for_admin_group(session_data, user_group.group_name)

    # Get current user for audit trail
    current_user = get_user_by_hash(session_data.user_hash)

    # Get user hashes from request
    user_hashes = request.user_hashes

    # Perform bulk assignment
    results = []
    success_count = 0
    error_count = 0
    errors = []

    for user_hash in user_hashes:
        try:
            # Get target user
            target_user = get_user_by_hash(user_hash)
            if not target_user:
                errors.append(f"User not found: {user_hash}")
                error_count += 1
                continue

            # Assign user to group
            assignment_result = assign_user_to_user_group(
                target_user.id,
                user_group.id,
                assigned_by=current_user.id
            )

            if assignment_result:
                results.append({
                    "user_hash": user_hash,
                    "username": target_user.username,
                    "status": "success",
                    "message": "Added to group successfully"
                })
                success_count += 1
            else:
                results.append({
                    "user_hash": user_hash,
                    "username": target_user.username,
                    "status": "error",
                    "message": "Assignment failed - user may already be in group"
                })
                error_count += 1

        except Exception as e:
            results.append({
                "user_hash": user_hash,
                "status": "error",
                "message": str(e)
            })
            error_count += 1

    # Log the activity
    ActivityLogger.log_bulk_group_assignment(
        current_user.id,
        count=success_count,
        user_group_id=user_group.id
    )

    logger.info(
        f"Bulk group assignment by {current_user.username}: {success_count} succeeded, {error_count} failed")

    return BulkAddUsersToGroupResponse(
        success=True,
        message=f"Bulk assignment completed: {success_count} succeeded, {error_count} failed",
        user_group={
            "group_hash": user_group.group_hash,
            "group_name": user_group.group_name
        },
        summary={
            "total_requested": len(user_hashes),
            "success_count": success_count,
            "error_count": error_count
        },
        results=results,
        errors=errors,
        performed_by=current_user.username,
        performed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )

@router.get("/users/{user_hash}/groups", response_model=UserGroupsForUserResponse)
async def get_user_groups(
        user_hash: str = Path(..., description="Hash of the active user whose groups are listed."),
        session_data=Depends(require_admin)
) -> UserGroupsForUserResponse:
    """
    List the active user groups a user belongs to.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly cookie); the
    session must carry `admin` or `manage_users`.

    Groups are sorted by name; each includes `joined_at` (when the membership was last (re)activated).

    **Responses:** 401 missing, invalid or expired access token; 403 missing permission;
    404 unknown or inactive user.
    """
    # Get target user
    target_user = get_user_by_hash(user_hash)
    if not target_user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": user_hash}
        )

    # Get user's groups
    user_groups = get_user_groups_for_user(target_user.id)

    # Format group data
    groups_data = []
    for group in user_groups:
        # Use joined_at from membership record (set by get_user_groups_for_user)
        joined_date = getattr(group, 'joined_at', None)
        group_info = {
            "group_hash": group.group_hash,
            "group_name": group.group_name,
            "description": group.group_description,
            "joined_at": (joined_date.isoformat() + "Z") if joined_date else None
        }
        groups_data.append(group_info)

    return UserGroupsForUserResponse(
        success=True,
        user={
            "user_hash": target_user.user_hash,
            "username": target_user.username,
            "email": target_user.email,
            "user_type": getattr(target_user, 'user_type', 'consumer')
        },
        groups=groups_data,
        statistics={
            "total_groups": len(groups_data)
        },
        generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
