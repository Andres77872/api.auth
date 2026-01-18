"""
Project Management Routes

Handles project CRUD operations and project-related queries
for the group-based multi-project authentication system.
"""

import logging
from datetime import datetime
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
    NotFoundError, InternalError, ErrorCode, create_not_found_error
)
from src.Util.activity_logger import ActivityLogger, ActivityType, get_recent_activity
from src.Util.db import (
    validate_session, get_user_by_hash,
    create_project, get_project_by_hash, list_all_projects,
    update_project, delete_project, search_projects,
    get_project_stats, get_user_accessible_projects,
    get_user_project_permissions, get_user_groups_for_user,
    # Group-project management
    get_user_groups_for_project,
    # Project groups for groups-of-groups architecture
    get_permission_groups_for_project
)

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


@router.get("", response_model=ListProjectsResponse)
async def list_projects(
        limit: int = Query(10, ge=1, le=500),
        offset: int = Query(0, ge=0),
        search: str = Query(None),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> ListProjectsResponse:
    """
    List projects based on user's access level.
    
    Args:
        limit: Number of projects to return
        offset: Number of projects to skip
        search: Optional search term
        
    Returns:
        List of accessible projects with access information
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

    # Check if user is admin (can see all projects)
    user_permissions = getattr(session_data, 'permissions', [])
    is_admin = 'admin' in user_permissions

    if is_admin:
        # Admin sees all projects
        if search:
            projects = search_projects(search, limit)
        else:
            projects = list_all_projects(limit, offset)
    else:
        # Regular users see only accessible projects
        accessible_projects = get_user_accessible_projects(user_data.id)
        projects = accessible_projects[offset:offset + limit] if accessible_projects else []

    # Add access level information
    projects_with_access = []
    for project in projects:
        project_hash = getattr(project, 'project_hash', '')
        project_id = getattr(project, 'id', 0)
        project_permissions = get_user_project_permissions(user_data.id, project_id)

        access_level = "admin" if "admin" in project_permissions else (
            "read-write" if "write" in project_permissions else "read-only")
        access_through = "admin_access" if is_admin else "user_group"

        project_access = ProjectAccessInfo(
            project_hash=project_hash,
            project_name=getattr(project, 'project_name', ''),
            project_description=getattr(project, 'project_description', None),
            access_level=access_level,
            access_through=access_through
        )
        projects_with_access.append(project_access)

    pagination = PaginationInfo(
        limit=limit,
        offset=offset,
        total=len(projects_with_access),
        has_more=len(projects_with_access) == limit
    )

    return ListProjectsResponse(
        success=True,
        projects=projects_with_access,
        pagination=pagination,
        user_access_level="admin" if is_admin else "user"
    )

@router.post("", response_model=CreateProjectResponse)
async def create_new_project(
        project_name: str = Form(...),
        project_description: Optional[str] = Form(None),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> CreateProjectResponse:
    """
    Create new project and assign it to default project group.
    
    Args:
        project_name: Project name
        project_description: Project description
        
    Returns:
        Created project information
    """
    session_token = credentials.credentials
    session_data = validate_session(session_token)

    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    # Check if user has permission to create projects
    user_permissions = getattr(session_data, 'permissions', [])
    if 'admin' not in user_permissions:
        raise AuthorizationError(
            message="Admin permission required to create projects",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_permission": "admin"}
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
        project_hash: str = Path(...),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> ProjectDetailsResponse:
    """
    Get detailed project information with user's access context.
    
    Args:
        project_hash: Project identifier
        
    Returns:
        Detailed project information with user's permissions
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

    # Check if user has access to this project
    user_permissions = get_user_project_permissions(user_data.id, project.id)
    session_permissions = getattr(session_data, 'permissions', [])

    if not user_permissions and 'admin' not in session_permissions:
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
        "permissions": user_permissions,
        "access_level": "admin" if "admin" in user_permissions else (
            "read-write" if "write" in user_permissions else "read-only"),
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
        project_hash: str = Path(...),
        project_name: Optional[str] = Form(None),
        project_description: Optional[str] = Form(None),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> UpdateProjectResponse:
    """
    Update project information (admin only).
    
    Args:
        project_hash: Project identifier
        project_name: Project name
        project_description: Project description
        
    Returns:
        Updated project information
    """
    session_token = credentials.credentials
    session_data = validate_session(session_token)

    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    # Check admin permission
    user_permissions = getattr(session_data, 'permissions', [])
    if 'admin' not in user_permissions:
        raise AuthorizationError(
            message="Admin permission required",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_permission": "admin"}
        )

    # Get project
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )

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
        project_hash: str = Path(...),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> DeleteProjectResponse:
    """
    Delete a project and revoke all access (admin only).
    
    Args:
        project_hash: Project identifier
        
    Returns:
        Deletion confirmation
    """
    session_token = credentials.credentials
    session_data = validate_session(session_token)

    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    # Check admin permission
    user_permissions = getattr(session_data, 'permissions', [])
    if 'admin' not in user_permissions:
        raise AuthorizationError(
            message="Admin permission required",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_permission": "admin"}
        )

    # Get project
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )

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
        project_hash: str = Path(...),
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        user_type: Optional[str] = Query(None),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> ProjectMembersResponse:
    """
    List all members of a project with their access details.
    
    **Admin access required**: Only admin users can list project members.
    
    Args:
        project_hash: Project identifier
        limit: Number of members to return
        offset: Number of members to skip
        user_type: Filter by user type (admin, consumer)
        
    Returns:
        List of project members with their roles and permissions
    """
    session_token = credentials.credentials
    session_data = validate_session(session_token)

    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    # Check admin permissions
    user_permissions = getattr(session_data, 'permissions', [])
    if 'admin' not in user_permissions and 'manage_users' not in user_permissions:
        raise AuthorizationError(
            message="Admin permission required to list project members",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_permission": "admin or manage_users"}
        )

    # Get project
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )

    # Get project members
    from src.Util.db_config import get_connection

    with get_connection() as con:
        cur = con.cursor()

        # Query to get all users with access to this project (group-based schema)
        query = (
            """
                SELECT DISTINCT u.id,
                                u.user_hash,
                                u.username,
                                u.email,
                                u.user_type,
                                u.is_active,
                                u.created_at,
                                vupa.access_granted_at,
                                NULL AS granted_by
                FROM users u
                         INNER JOIN v_user_project_access vupa
                                    ON u.id = vupa.user_id
                WHERE u.is_active = 1
                  AND vupa.project_id = %s
            """
        )

        params: list[Any] = [project.id]

        if user_type:
            query += " AND u.user_type = %s"
            params.append(user_type)

        query += " ORDER BY u.user_type, u.username LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        cur.execute(query, params)
        results = cur.fetchall()

        # Get total count (group-based schema)
        count_query = (
            """
                      SELECT COUNT(DISTINCT u.id)
                      FROM users u
                               INNER JOIN v_user_project_access vupa
                                          ON u.id = vupa.user_id
                      WHERE u.is_active = 1
                        AND vupa.project_id = %s
            """
        )

        count_params: list[Any] = [project.id]
        if user_type:
            count_query += " AND u.user_type = %s"
            count_params.append(user_type)

        cur.execute(count_query, count_params)
        total_count = cur.fetchone()[0]

    # Build members list
    members = []
    for row in results:
        user_id, user_hash, username, email, user_type_val, is_active, created_at, granted_at, granted_by = row

        # Get user's permissions in this project
        permissions = get_user_project_permissions(user_id, project.id)

        # Get user groups for consumer users
        groups = []
        if user_type_val == 'consumer':
            user_groups = get_user_groups_for_user(user_id)
            groups = [g.group_name for g in user_groups]

        member_info = {
            "user_hash": user_hash,
            "username": username,
            "email": email,
            "user_type": user_type_val,
            "is_active": is_active,
            "permissions": permissions,
            "groups": groups,
            "access_level": "admin" if "admin" in permissions else (
                "read-write" if "write" in permissions else "read-only"),
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
#   2. Grant group access to project: POST /projects/{project_hash}/groups
#
# The following endpoints have been removed to enforce group-based access:
#   - POST /projects/{project_hash}/members (add user directly)
#   - DELETE /projects/{project_hash}/members/{user_hash} (remove user directly)
#
# Use the admin user-groups endpoints instead for proper group-based access control.


@router.get("/{project_hash}/activity")
async def get_project_activity(
        project_hash: str = Path(...),
        limit: int = Query(50, ge=1, le=100, description="Number of activities to return"),
        offset: int = Query(0, ge=0, description="Number of activities to skip"),
        activity_type: Optional[str] = Query(None, description="Filter by activity type"),
        days: int = Query(30, ge=1, le=365, description="Days to look back"),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Get project-specific activity feed.
    
    **Phase 2 Implementation**: Project-specific activity feed
    
    Args:
        project_hash: Project identifier
        limit: Number of activities to return
        offset: Number of activities to skip
        activity_type: Filter by activity type
        days: Days to look back
        
    Returns:
        Project activity feed with pagination
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
    user_permissions = get_user_project_permissions(current_user.id, project.id)
    session_permissions = getattr(session_data, 'permissions', [])

    if not user_permissions and 'admin' not in session_permissions:
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

    # Format response to match expected structure
    activities = {
        "activities": activities,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "total": len(activities)
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
        "generated_at": datetime.utcnow().isoformat() + "Z"
    }

@router.get("/{project_hash}/stats")
async def get_detailed_project_stats(
        project_hash: str = Path(...),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Get detailed project statistics.
    
    **Phase 2 Implementation**: Detailed project statistics
    
    Args:
        project_hash: Project identifier
        
    Returns:
        Member counts, activity metrics, health scores
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
    user_permissions = get_user_project_permissions(current_user.id, project.id)
    session_permissions = getattr(session_data, 'permissions', [])

    if not user_permissions and 'admin' not in session_permissions:
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
        "generated_at": datetime.utcnow().isoformat() + "Z"
    }

@router.patch("/{project_hash}/owner")
async def transfer_project_ownership(
        project_hash: str = Path(...),
        new_owner_hash: str = Form(...),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Transfer project ownership.
    
    **Admin access required**: Only admin users can transfer project ownership.
    **Phase 2 Implementation**: Transfer project ownership
    
    Args:
        project_hash: Project identifier
        new_owner_hash: Hash of the new owner
        
    Returns:
        Ownership transfer confirmation
    """
    session_token = credentials.credentials
    session_data = validate_session(session_token)

    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    # Check admin permissions
    user_permissions = getattr(session_data, 'permissions', [])
    if 'admin' not in user_permissions:
        raise AuthorizationError(
            message="Admin permission required to transfer project ownership",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_permission": "admin"}
        )

    # Get project and users
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )

    new_owner = get_user_by_hash(new_owner_hash)
    if not new_owner:
        raise NotFoundError(
            message="New owner not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": new_owner_hash}
        )

    current_user = get_user_by_hash(session_data.user_hash)

    # Transfer ownership (placeholder implementation)
    # TODO: Implement actual ownership transfer logic
    success = True  # For now, just return success

    if not success:
        raise InternalError(
            message="Failed to transfer project ownership",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "transfer_ownership", "project_hash": project_hash}
        )

    # Log the activity
    ActivityLogger.log_project_ownership_transferred(
        current_user.id, project.id, new_owner.id
    )

    logger.info(
        f"Project ownership transferred: {project.project_name} -> {new_owner.username} by {current_user.username}")

    return {
        "success": True,
        "message": f"Project ownership transferred to {new_owner.username}",
        "project": {
            "project_hash": project.project_hash,
            "project_name": project.project_name
        },
        "new_owner": {
            "user_hash": new_owner.user_hash,
            "username": new_owner.username,
            "email": new_owner.email
        },
        "transferred_by": {
            "user_hash": current_user.user_hash,
            "username": current_user.username
        },
        "transferred_at": datetime.utcnow().isoformat() + "Z"
    }

@router.patch("/{project_hash}/archive")
async def archive_unarchive_project(
        project_hash: str = Path(...),
        archived: bool = Form(...),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Archive or unarchive a project.
    
    **Admin access required**: Only admin users can archive/unarchive projects.
    **Phase 2 Implementation**: Archive/unarchive projects
    
    Args:
        project_hash: Project identifier
        archived: Whether to archive (true) or unarchive (false) the project
        
    Returns:
        Archive status change confirmation
    """
    session_token = credentials.credentials
    session_data = validate_session(session_token)

    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    # Check admin permissions
    user_permissions = getattr(session_data, 'permissions', [])
    if 'admin' not in user_permissions:
        raise AuthorizationError(
            message="Admin permission required to archive/unarchive projects",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_permission": "admin"}
        )

    # Get project
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )

    current_user = get_user_by_hash(session_data.user_hash)

    # Archive/unarchive project (placeholder implementation)
    # TODO: Implement actual archive/unarchive logic
    success = True  # For now, just return success

    if not success:
        raise InternalError(
            message=f"Failed to {'archive' if archived else 'unarchive'} project",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "archive_project", "archived": archived}
        )

    # Log the activity
    action = "archived" if archived else "unarchived"
    if archived:
        ActivityLogger.log_project_archived(current_user.id, project.id)
    else:
        ActivityLogger.log_project_unarchived(current_user.id, project.id)

    logger.info(f"Project {action}: {project.project_name} by {current_user.username}")

    return {
        "success": True,
        "message": f"Project {project.project_name} {'archived' if archived else 'unarchived'} successfully",
        "project": {
            "project_hash": project.project_hash,
            "project_name": project.project_name,
            "archived": archived
        },
        "action_details": {
            "action": "archive" if archived else "unarchive",
            "performed_by": current_user.username,
            "performed_at": datetime.utcnow().isoformat() + "Z"
        }
    }

# =================== NEW GROUP-PROJECT ENDPOINTS ===================

@router.get("/{project_hash}/groups", response_model=ListUserGroupsResponse)
async def list_project_user_groups(
        project_hash: str = Path(..., description="Project identifier"),
        limit: int = Query(100, ge=1, le=500, description="Max groups to return"),
        offset: int = Query(0, ge=0, description="Offset for pagination"),
        credentials: HTTPAuthorizationCredentials = Depends(security)) -> ListUserGroupsResponse:
    """List all user groups that have access to the specified project (admin only)."""

    # Validate session
    session_token = credentials.credentials
    session_data = validate_session(session_token)
    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    # Admin permission check
    user_permissions = getattr(session_data, 'permissions', [])
    if 'admin' not in user_permissions and 'manage_users' not in user_permissions:
        raise AuthorizationError(
            message="Admin permission required to list project groups",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_permission": "admin or manage_users"}
        )

    # Resolve project
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )

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
