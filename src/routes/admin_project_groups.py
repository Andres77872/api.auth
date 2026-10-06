"""
Admin Project Group Management Routes

Handles project group administration including creation, management,
and project membership for the group-based multi-project authentication system.

Project groups are containers that group projects together. Users gain access
to projects through the groups-of-groups architecture:

    USER → USER_GROUP → PROJECT_GROUP → PROJECT

Note: Project groups do NOT have permissions attached to them directly.
Permissions are managed through global_permission_groups and user_group assignments.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, Query, Path, Form
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from src.Util.Models import (
    ListProjectGroupsResponse, CreateProjectGroupResponse, ProjectGroupDetailsResponse,
    UpdateProjectGroupResponse, DeleteProjectGroupResponse, AssignProjectToGroupResponse,
    RemoveProjectFromGroupResponse,
    ProjectInfo, ProjectGroupInfo, PaginationInfo
)
from src.Util.security import HTTPBearerOrCookie
from src.Util.db import (
    validate_session, get_user_by_hash, get_project_by_hash,
    create_project_group, get_project_group_by_hash, list_all_project_groups,
    update_project_group,
    delete_project_group, assign_project_to_group, remove_project_from_group,
    get_projects_in_group, count_project_groups
)
from src.Util.error_handler import (
    AuthenticationError, AuthorizationError, ValidationError,
    NotFoundError, ConflictError, InternalError, ErrorCode, mask_uuid
)
from src.Util.db_error_wrapper import handle_db_operation
from src.Util.auth_lifecycle import revoke_project_sessions_losing_access
from src.Util.db.db_project_groups import get_users_with_access_to_project_group

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/admin/project-groups", tags=["Admin - Project Groups"])
security = HTTPBearerOrCookie()


# Note: All endpoints use Form data instead of JSON/Pydantic models for consistency


# Helper function to check admin permissions
async def require_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Ensure user has admin permissions.

    Checks ``'admin'`` OR ``'manage_roles'`` in session permissions.
    Project groups relate to role assignments, hence the ``manage_roles``
    scope.  Consistent with the ``global_roles.py`` pattern for
    ``manage_roles``-protected surfaces.
    """
    session_data = validate_session(credentials.credentials)
    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    user_permissions = session_data.permissions if hasattr(session_data, 'permissions') else []
    if 'admin' not in user_permissions and 'manage_roles' not in user_permissions:
        raise AuthorizationError(
            message="Admin or manage_roles permission required",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_permissions": ["admin", "manage_roles"]}
        )

    return session_data


@router.get("", response_model=ListProjectGroupsResponse)
async def list_project_groups(
        limit: int = Query(50, ge=1, le=1000, description="Maximum number of project groups to return (1-1000)."),
        offset: int = Query(0, ge=0, description="Number of project groups to skip."),
        sort_by: str = Query('group_name', description=(
            "Sort field: `group_name` (default), `created_at` or `updated_at`. Any other value sorts by `group_name`."
        )),
        sort_order: str = Query('ASC', description="`DESC` (case-insensitive) for descending; any other value sorts ascending."),
        search: str = Query(None, description="Case-insensitive substring match on the project group name."),
        session_data=Depends(require_admin)
) -> ListProjectGroupsResponse:
    """
    List active project groups with their project counts.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly cookie); the
    session must carry `admin` or `manage_roles` (every root/admin session has `admin`; consumers only through
    a global role).

    `project_count` counts active, non-archived projects. The list includes the dedicated project group created
    automatically for each new project. `pagination.total` respects `search`.

    **Responses:** 401 missing, invalid or expired access token; 403 missing permission.
    """
    # Get all project groups
    project_groups = handle_db_operation(
        lambda: list_all_project_groups(limit, offset, sort_by, sort_order, search),
        error_context="list project groups"
    )

    # Add project counts
    groups_with_counts = []
    for group in project_groups:
        projects = handle_db_operation(
            lambda g=group: get_projects_in_group(g.id),
            error_context=f"get projects in group {mask_uuid(group.group_hash)}",
            default_return=[]
        )
        group_info = ProjectGroupInfo(
            group_hash=group.group_hash,
            group_name=group.group_name,
            description=group.group_description,
            project_count=len(projects),
            created_at=group.created_at
        )
        groups_with_counts.append(group_info)

    total_count = handle_db_operation(
        lambda: count_project_groups(search),
        error_context="count project groups"
    )

    has_more = offset + limit < total_count

    pagination = PaginationInfo(
        limit=limit,
        offset=offset,
        total=total_count,
        has_more=has_more
    )

    return ListProjectGroupsResponse(
        success=True,
        project_groups=groups_with_counts,
        pagination=pagination
    )


@router.post("", response_model=CreateProjectGroupResponse)
async def create_project_group_endpoint(
        group_name: str = Form(..., description="Unique project group name (required, non-empty)."),
        description: Optional[str] = Form(None, description="Optional project group description."),
        session_data=Depends(require_admin)
) -> CreateProjectGroupResponse:
    """
    Create an empty project group.

    Project groups are containers of projects and carry no permissions; users reach projects through
    user → user group → project group → project.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly cookie); the
    session must carry `admin` or `manage_roles`.

    **Request:** form fields `group_name` (required) and optional `description`.

    **Responses:** 400 missing or empty `group_name`; 401 missing, invalid or expired access token; 403 missing
    permission; 409 name already in use (names of deleted groups stay reserved).
    """
    # Get current user for audit trail
    user_data = handle_db_operation(
        lambda: get_user_by_hash(session_data.user_hash),
        error_context="get user for project group creation",
        not_found_message=f"User not found: {mask_uuid(session_data.user_hash)}"
    )

    create_name = group_name
    create_description = description

    if not create_name:
        raise ValidationError(
            message="Group name is required",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"field": "group_name"}
        )

    # Create a project container.
    new_group = handle_db_operation(
        lambda: create_project_group(
            create_name,
            create_description,
            created_by=user_data.id
        ),
        error_context="create project group"
    )

    if not new_group:
        raise InternalError(
            message="Project group creation failed",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "create_project_group"}
        )

    group_info = ProjectGroupInfo(
        group_hash=new_group.group_hash,
        group_name=new_group.group_name,
        description=new_group.group_description,
        project_count=0,
        created_at=new_group.created_at
    )

    return CreateProjectGroupResponse(
        success=True,
        message=f"Project group \"{create_name}\" created successfully",
        project_group=group_info
    )


@router.get("/{group_hash}", response_model=ProjectGroupDetailsResponse)
async def get_project_group_details(
        group_hash: str = Path(..., description="Project group hash."),
        session_data=Depends(require_admin)
) -> ProjectGroupDetailsResponse:
    """
    Get a project group and the projects assigned to it.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly cookie); the
    session must carry `admin` or `manage_roles`.

    `assigned_projects`, `project_group.project_count` and `statistics.total_projects` include only active,
    non-archived projects, sorted by name.

    **Responses:** 401 missing, invalid or expired access token; 403 missing permission;
    404 unknown or deleted project group.
    """
    # Get project group
    project_group = handle_db_operation(
        lambda: get_project_group_by_hash(group_hash),
        error_context="get project group by hash",
        not_found_message=f"Project group not found: {mask_uuid(group_hash)}"
    )

    # Get assigned projects
    assigned_projects = handle_db_operation(
        lambda: get_projects_in_group(project_group.id),
        error_context="get projects in permission group",
        default_return=[]
    )

    group_info = ProjectGroupInfo(
        group_hash=project_group.group_hash,
        group_name=project_group.group_name,
        description=project_group.group_description,
        project_count=len(assigned_projects),
        created_at=project_group.created_at
    )

    project_list = [
        ProjectInfo(
            project_hash=project.project_hash,
            project_name=project.project_name,
            project_description=project.project_description
        ) for project in assigned_projects
    ]

    statistics_info = {
        "total_projects": len(assigned_projects)
    }

    return ProjectGroupDetailsResponse(
        success=True,
        project_group=group_info,
        assigned_projects=project_list,
        statistics=statistics_info
    )


@router.put("/{group_hash}", response_model=UpdateProjectGroupResponse)
async def update_project_group_endpoint(
        group_hash: str = Path(..., description="Project group hash."),
        group_name: Optional[str] = Form(None, description="New unique name. Omitted or empty keeps the current name."),
        description: Optional[str] = Form(None, description=(
            "New description. Omitted or empty keeps the current description (it cannot be cleared)."
        )),
        session_data=Depends(require_admin)
) -> UpdateProjectGroupResponse:
    """
    Rename a project group and/or change its description.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly cookie); the
    session must carry `admin` or `manage_roles`.

    **Request:** form fields `group_name` and/or `description`.

    **Responses:** 401 missing, invalid or expired access token; 403 missing permission; 404 unknown or deleted
    project group; 409 name already in use; 500 when neither field has a value.

    """
    # Get project group
    project_group = handle_db_operation(
        lambda: get_project_group_by_hash(group_hash),
        error_context="get project group by hash",
        not_found_message=f"Project group not found: {mask_uuid(group_hash)}"
    )

    update_name = group_name
    update_description = description

    # Update group (permissions parameter omitted - project_groups are containers)
    updated_group = handle_db_operation(
        lambda: update_project_group(
            project_group.id,
            group_name=update_name,
            group_description=update_description
        ),
        error_context="update project group"
    )

    if not updated_group:
        raise InternalError(
            message="Update failed",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "update_project_group"}
        )

    group_info = ProjectGroupInfo(
        group_hash=updated_group.group_hash,
        group_name=updated_group.group_name,
        description=updated_group.group_description
    )

    return UpdateProjectGroupResponse(
        success=True,
        message="Project group updated successfully",
        project_group=group_info
    )


@router.delete("/{group_hash}", response_model=DeleteProjectGroupResponse)
async def delete_project_group_endpoint(
        group_hash: str = Path(..., description="Project group hash."),
        session_data=Depends(require_admin)
) -> DeleteProjectGroupResponse:
    """
    Soft-delete a project group.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly cookie); the
    session must carry `admin` or `manage_roles`.

    **Effects:** the group, its project assignments and every user-group grant to it are deactivated (projects
    themselves are untouched). Active project-scoped sessions (and refresh-token families) of users who can no
    longer reach an affected project through another chain are revoked. The group name stays reserved.

    **Responses:** 401 missing, invalid or expired access token; 403 missing permission;
    404 unknown or already deleted project group.
    """
    # Get project group
    project_group = handle_db_operation(
        lambda: get_project_group_by_hash(group_hash),
        error_context="get project group by hash",
        not_found_message=f"Project group not found: {mask_uuid(group_hash)}"
    )

    # Get current user for audit trail
    user_data = handle_db_operation(
        lambda: get_user_by_hash(session_data.user_hash),
        error_context="get user for project group deletion",
        not_found_message=f"User not found: {mask_uuid(session_data.user_hash)}"
    )

    affected_users = handle_db_operation(
        lambda: get_users_with_access_to_project_group(project_group.id),
        error_context="get users with access to project group",
        default_return=[]
    )
    affected_projects = handle_db_operation(
        lambda: get_projects_in_group(project_group.id),
        error_context="get projects in permission group before delete",
        default_return=[]
    )
    affected_user_ids = [user.id for user in affected_users]
    affected_project_ids = [project.id for project in affected_projects]

    # Delete group
    success = handle_db_operation(
        lambda: delete_project_group(project_group.id, deleted_by=user_data.id),
        error_context="delete project group"
    )
    
    if success:
        revoke_project_sessions_losing_access(
            user_ids=affected_user_ids,
            project_ids=affected_project_ids,
            reason="project_group_deleted",
        )
        return DeleteProjectGroupResponse(
            success=True,
            message=f"Project group \"{project_group.group_name}\" deleted successfully",
            warning="All project assignments have been removed"
        )
    else:
        raise InternalError(
            message="Delete failed",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "delete_project_group"}
        )


@router.post("/{group_hash}/projects", response_model=AssignProjectToGroupResponse)
async def assign_project_to_group_endpoint(
        group_hash: str = Path(..., description="Project group hash."),
        project_hash: str = Form(..., description="Hash of the project to add (any non-deleted project)."),
        session_data=Depends(require_admin)
) -> AssignProjectToGroupResponse:
    """
    Add a project to a project group.

    Members of every user group granted this project group gain access to the project (unless it is archived).

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly cookie); the
    session must carry `admin` or `manage_roles`.

    **Request:** form field `project_hash`. Idempotent: re-adding a current or previously removed project
    (re)activates the assignment and returns 200.

    **Responses:** 400 missing `project_hash`; 401 missing, invalid or expired access token; 403 missing
    permission; 404 unknown project group or project.
    """
    target_project_hash = project_hash

    # Get project group
    project_group = handle_db_operation(
        lambda: get_project_group_by_hash(group_hash),
        error_context="get project group by hash",
        not_found_message=f"Project group not found: {mask_uuid(group_hash)}"
    )

    # Get target project
    target_project = handle_db_operation(
        lambda: get_project_by_hash(target_project_hash),
        error_context="get project by hash",
        not_found_message=f"Target project not found: {mask_uuid(target_project_hash)}"
    )

    # Get current user for audit trail
    current_user = handle_db_operation(
        lambda: get_user_by_hash(session_data.user_hash),
        error_context="get user for assignment",
        not_found_message=f"User not found: {mask_uuid(session_data.user_hash)}"
    )

    # Assign project to group
    assignment_result = handle_db_operation(
        lambda: assign_project_to_group(
            target_project.id,
            project_group.id,
            assigned_by=current_user.id
        ),
        error_context="assign project to permission group"
    )

    if not assignment_result:
        raise InternalError(
            message="Assignment failed",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "assign_project_to_group"}
        )

    assignment_info = {
        "project": {
            "project_hash": target_project.project_hash,
            "project_name": target_project.project_name
        },
        "group": {
            "group_hash": project_group.group_hash,
            "group_name": project_group.group_name
        },
        "assigned_by": current_user.username
    }

    return AssignProjectToGroupResponse(
        success=True,
        message=f"Project \"{target_project.project_name}\" assigned to group \"{project_group.group_name}\"",
        assignment=assignment_info
    )


@router.delete("/{group_hash}/projects/{project_hash}", response_model=RemoveProjectFromGroupResponse)
async def remove_project_from_group_endpoint(
        group_hash: str = Path(..., description="Project group hash."),
        project_hash: str = Path(..., description="Hash of the project to remove from the group."),
        session_data=Depends(require_admin)
) -> RemoveProjectFromGroupResponse:
    """
    Remove a project from a project group.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly cookie); the
    session must carry `admin` or `manage_roles`.

    Returns 200 even if the project was not in the group. Active sessions scoped to this project are then
    revoked (with their refresh-token families) for users of the group who can no longer reach it through
    another chain.

    **Responses:** 401 missing, invalid or expired access token; 403 missing permission; 404 unknown project
    group or project.
    """
    # Get project group
    project_group = handle_db_operation(
        lambda: get_project_group_by_hash(group_hash),
        error_context="get project group by hash",
        not_found_message=f"Project group not found: {mask_uuid(group_hash)}"
    )

    # Get project
    project = handle_db_operation(
        lambda: get_project_by_hash(project_hash),
        error_context="get project by hash",
        not_found_message=f"Project not found: {mask_uuid(project_hash)}"
    )

    # Get current user for audit trail
    current_user = handle_db_operation(
        lambda: get_user_by_hash(session_data.user_hash),
        error_context="get user for removal",
        not_found_message=f"User not found: {mask_uuid(session_data.user_hash)}"
    )

    affected_users = handle_db_operation(
        lambda: get_users_with_access_to_project_group(project_group.id),
        error_context="get users with access to project group before project removal",
        default_return=[]
    )
    affected_user_ids = [user.id for user in affected_users]

    # Remove project from group
    success = handle_db_operation(
        lambda: remove_project_from_group(project.id, project_group.id, removed_by=current_user.id),
        error_context="remove project from permission group"
    )
    
    if success:
        revoke_project_sessions_losing_access(
            user_ids=affected_user_ids,
            project_ids=[project.id],
            reason="project_removed_from_group",
        )
        return RemoveProjectFromGroupResponse(
            success=True,
            message=f"Project \"{project.project_name}\" removed from group \"{project_group.group_name}\""
        )
    else:
        raise InternalError(
            message="Removal failed",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "remove_project_from_group"}
        )
