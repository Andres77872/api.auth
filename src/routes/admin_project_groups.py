"""
Admin Project Group Management Routes

Handles project group (permission group) administration including creation,
management, and permission control for the group-based multi-project authentication system.
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
from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.db import (
    validate_session, get_user_by_hash, get_project_by_hash,
    create_project_permission_group, get_project_permission_group_by_hash, list_all_project_permission_groups,
    update_project_permission_group,
    delete_project_permission_group, assign_project_to_permission_group, remove_project_from_permission_group,
    get_projects_in_permission_group
)
from src.Util.error_handler import (
    AuthenticationError, AuthorizationError, ValidationError,
    NotFoundError, ConflictError, InternalError, ErrorCode, mask_uuid
)
from src.Util.db_error_wrapper import handle_db_operation

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/admin/project-groups", tags=["Admin - Project Groups"])
security = HTTPBearerOrCookie()


# Note: All endpoints use Form data instead of JSON/Pydantic models for consistency


# Helper function to check admin permissions
async def require_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Ensure user has admin permissions"""
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
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        session_data=Depends(require_admin)
) -> ListProjectGroupsResponse:
    """
    List all project permission groups (admin only).
    
    Returns:
        List of project groups with project counts
    """
    # Get all project groups
    project_groups = handle_db_operation(
        lambda: list_all_project_permission_groups(limit, offset),
        error_context="list project permission groups"
    )

    # Add project counts
    groups_with_counts = []
    for group in project_groups:
        projects = handle_db_operation(
            lambda g=group: get_projects_in_permission_group(g.id),
            error_context=f"get projects in group {mask_uuid(group.group_hash)}",
            default_return=[]
        )
        group_info = ProjectGroupInfo(
            group_hash=group.group_hash,
            group_name=group.group_name,
            description=group.description,
            permissions=group.permissions,
            project_count=len(projects),
            created_at=group.created_at
        )
        groups_with_counts.append(group_info)

    pagination = PaginationInfo(
        limit=limit,
        offset=offset,
        total=len(groups_with_counts)
    )

    return ListProjectGroupsResponse(
        success=True,
        project_groups=groups_with_counts,
        pagination=pagination
    )


@router.post("", response_model=CreateProjectGroupResponse)
async def create_project_group_endpoint(
        group_name: str = Form(...),
        permissions: List[str] = Form(None),
        description: Optional[str] = Form(None),
        session_data=Depends(require_admin)
) -> CreateProjectGroupResponse:
    """
    Create a new project permission group (admin only).
    
    Args:
        group_name: Group name
        permissions: Permissions list
        description: Group description
        
    Returns:
        Created project group information
    """
    # Get current user for audit trail
    user_data = handle_db_operation(
        lambda: get_user_by_hash(session_data.user_hash),
        error_context="get user for project group creation",
        not_found_message=f"User not found: {mask_uuid(session_data.user_hash)}"
    )

    create_name = group_name
    create_permissions = permissions or []
    create_description = description

    if not create_name:
        raise ValidationError(
            message="Group name is required",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"field": "group_name"}
        )

    # Create project group
    new_group = handle_db_operation(
        lambda: create_project_permission_group(
            create_name,
            create_permissions,
            create_description,
            created_by=user_data.id
        ),
        error_context="create project permission group"
    )

    if not new_group:
        raise InternalError(
            message="Project group creation failed",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "create_project_permission_group"}
        )

    group_info = ProjectGroupInfo(
        group_hash=new_group.group_hash,
        group_name=new_group.group_name,
        description=new_group.description,
        permissions=new_group.permissions,
        created_at=new_group.created_at
    )

    return CreateProjectGroupResponse(
        success=True,
        message=f"Project group \"{create_name}\" created successfully",
        project_group=group_info
    )


@router.get("/{group_hash}", response_model=ProjectGroupDetailsResponse)
async def get_project_group_details(
        group_hash: str = Path(...),
        session_data=Depends(require_admin)
) -> ProjectGroupDetailsResponse:
    """
    Get detailed project group information (admin only).
    
    Args:
        group_hash: Project group identifier
        
    Returns:
        Project group details with assigned projects
    """
    # Get project group
    project_group = handle_db_operation(
        lambda: get_project_permission_group_by_hash(group_hash),
        error_context="get project permission group by hash",
        not_found_message=f"Project group not found: {mask_uuid(group_hash)}"
    )

    # Get assigned projects
    assigned_projects = handle_db_operation(
        lambda: get_projects_in_permission_group(project_group.id),
        error_context="get projects in permission group",
        default_return=[]
    )

    group_info = ProjectGroupInfo(
        group_hash=project_group.group_hash,
        group_name=project_group.group_name,
        description=project_group.description,
        permissions=project_group.permissions,
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
        "total_projects": len(assigned_projects),
        "total_permissions": len(project_group.permissions)
    }

    return ProjectGroupDetailsResponse(
        success=True,
        project_group=group_info,
        assigned_projects=project_list,
        statistics=statistics_info
    )


@router.put("/{group_hash}", response_model=UpdateProjectGroupResponse)
async def update_project_group_endpoint(
        group_hash: str = Path(...),
        group_name: Optional[str] = Form(None),
        permissions: Optional[List[str]] = Form(None),
        description: Optional[str] = Form(None),
        session_data=Depends(require_admin)
) -> UpdateProjectGroupResponse:
    """
    Update project group information (admin only).
    
    Args:
        group_hash: Project group identifier
        group_name: Group name
        permissions: Permissions list
        description: Group description
        
    Returns:
        Updated project group information
    """
    # Get project group
    project_group = handle_db_operation(
        lambda: get_project_permission_group_by_hash(group_hash),
        error_context="get project permission group by hash",
        not_found_message=f"Project group not found: {mask_uuid(group_hash)}"
    )

    update_name = group_name
    update_permissions = permissions
    update_description = description

    # Update group
    updated_group = handle_db_operation(
        lambda: update_project_permission_group(
            project_group.id,
            group_name=update_name,
            group_description=update_description,
            permissions=update_permissions
        ),
        error_context="update project permission group"
    )

    if not updated_group:
        raise InternalError(
            message="Update failed",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "update_project_permission_group"}
        )

    group_info = ProjectGroupInfo(
        group_hash=updated_group.group_hash,
        group_name=updated_group.group_name,
        description=updated_group.description,
        permissions=updated_group.permissions
    )

    return UpdateProjectGroupResponse(
        success=True,
        message="Project group updated successfully",
        project_group=group_info
    )


@router.delete("/{group_hash}", response_model=DeleteProjectGroupResponse)
async def delete_project_group_endpoint(
        group_hash: str = Path(...),
        session_data=Depends(require_admin)
) -> DeleteProjectGroupResponse:
    """
    Delete a project group (admin only).
    
    Args:
        group_hash: Project group identifier
        
    Returns:
        Deletion confirmation
    """
    # Get project group
    project_group = handle_db_operation(
        lambda: get_project_permission_group_by_hash(group_hash),
        error_context="get project permission group by hash",
        not_found_message=f"Project group not found: {mask_uuid(group_hash)}"
    )

    # Get current user for audit trail
    user_data = handle_db_operation(
        lambda: get_user_by_hash(session_data.user_hash),
        error_context="get user for project group deletion",
        not_found_message=f"User not found: {mask_uuid(session_data.user_hash)}"
    )

    # Delete group
    success = handle_db_operation(
        lambda: delete_project_permission_group(project_group.id, deleted_by=user_data.id),
        error_context="delete project permission group"
    )
    
    if success:
        return DeleteProjectGroupResponse(
            success=True,
            message=f"Project group \"{project_group.group_name}\" deleted successfully",
            warning="All project assignments have been removed"
        )
    else:
        raise InternalError(
            message="Delete failed",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "delete_project_permission_group"}
        )


@router.post("/{group_hash}/projects", response_model=AssignProjectToGroupResponse)
async def assign_project_to_group_endpoint(
        group_hash: str = Path(...),
        project_hash: str = Form(...),
        session_data=Depends(require_admin)
) -> AssignProjectToGroupResponse:
    """
    Assign a project to a project group (admin only).
    
    Args:
        group_hash: Project group identifier
        project_hash: Project hash
        
    Returns:
        Assignment confirmation
    """
    target_project_hash = project_hash

    # Get project group
    project_group = handle_db_operation(
        lambda: get_project_permission_group_by_hash(group_hash),
        error_context="get project permission group by hash",
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
        lambda: assign_project_to_permission_group(
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
            details={"operation": "assign_project_to_permission_group"}
        )

    assignment_info = {
        "project": {
            "project_hash": target_project.project_hash,
            "project_name": target_project.project_name
        },
        "group": {
            "group_hash": project_group.group_hash,
            "group_name": project_group.group_name,
            "permissions": project_group.permissions
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
        group_hash: str = Path(...),
        project_hash: str = Path(...),
        session_data=Depends(require_admin)
) -> RemoveProjectFromGroupResponse:
    """
    Remove a project from a project group (admin only).
    
    Args:
        group_hash: Project group identifier
        project_hash: Project identifier
        
    Returns:
        Removal confirmation
    """
    # Get project group
    project_group = handle_db_operation(
        lambda: get_project_permission_group_by_hash(group_hash),
        error_context="get project permission group by hash",
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

    # Remove project from group
    success = handle_db_operation(
        lambda: remove_project_from_permission_group(project.id, project_group.id, removed_by=current_user.id),
        error_context="remove project from permission group"
    )
    
    if success:
        return RemoveProjectFromGroupResponse(
            success=True,
            message=f"Project \"{project.project_name}\" removed from group \"{project_group.group_name}\""
        )
    else:
        raise InternalError(
            message="Removal failed",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "remove_project_from_permission_group"}
        )
