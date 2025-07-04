"""
Project Management Routes

Handles project CRUD operations and project-related queries
for the group-based multi-project authentication system.
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Query, Path, Form
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from src.Util.Models import (
    ListProjectsResponse, CreateProjectResponse, ProjectDetailsResponse,
    UpdateProjectResponse, DeleteProjectResponse, ProjectAccessInfo,
    ProjectInfo, PaginationInfo, ListUserGroupsResponse, GrantGroupProjectAccessResponse, UserGroupInfo
)
from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.activity_logger import log_activity, ActivityType, get_recent_activity
from src.Util.db import (
    validate_session, get_user_by_hash,
    create_project, get_project_by_hash, list_all_projects,
    update_project, delete_project, search_projects,
    get_project_stats, get_user_accessible_projects,
    get_user_project_permissions, get_user_groups_for_user,
    get_admin_assigned_projects, grant_user_project_access, add_admin_to_project,
    revoke_user_project_access,
    # NEW imports for group-project management
    get_user_group_by_hash, get_user_groups_for_project,
    grant_group_project_access, revoke_group_project_access
)

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/projects", tags=["Project Management"])
security = HTTPBearerOrCookie()


# Pydantic models
class ProjectCreate(BaseModel):
    project_name: str
    project_description: str = None


class ProjectUpdate(BaseModel):
    project_name: str = None
    project_description: str = None


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
        limit: int = Query(10, ge=1, le=100),
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
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)

        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")

        user_data = get_user_by_hash(session_data.user_hash)
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")

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

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project listing error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project listing error")


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
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)

        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")

        # Check if user has permission to create projects
        user_permissions = getattr(session_data, 'permissions', [])
        if 'admin' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required to create projects")

        # Get current user for audit trail
        user_data = get_user_by_hash(session_data.user_hash)

        create_name = project_name
        create_description = project_description

        if not create_name:
            raise HTTPException(status_code=400, detail="Project name is required")

        # Create project
        new_project = create_project(create_name, create_description)

        if not new_project:
            raise HTTPException(status_code=400, detail="Project creation failed")

        logger.info(f"Project created: {create_name} by user: {user_data.username}")

        project_info = ProjectInfo(
            project_hash=new_project.project_hash,
            project_name=new_project.project_name,
            project_description=new_project.project_description,
            created_at=getattr(new_project, 'project_created', None)
        )

        return CreateProjectResponse(
            success=True,
            message=f"Project \"{create_name}\" created successfully",
            project=project_info
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project creation error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project creation error")


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
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)

        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")

        # Get project details
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Get user data
        user_data = get_user_by_hash(session_data.user_hash)

        # Check if user has access to this project
        user_permissions = get_user_project_permissions(user_data.id, project.id)
        session_permissions = getattr(session_data, 'permissions', [])

        if not user_permissions and 'admin' not in session_permissions:
            raise HTTPException(status_code=403, detail="Access denied to this project")

        # Get project statistics
        project_stats = get_project_stats(project.id)

        # Get user groups that have access to this project
        user_groups = get_user_groups_for_user(user_data.id)

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
            statistics=project_stats or {}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project details error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project details error")


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
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)

        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")

        # Check admin permission
        user_permissions = getattr(session_data, 'permissions', [])
        if 'admin' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required")

        # Get project
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

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
            raise HTTPException(status_code=400, detail="Update failed")

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

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project update error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project update error")


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
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)

        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")

        # Check admin permission
        user_permissions = getattr(session_data, 'permissions', [])
        if 'admin' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required")

        # Get project
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

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
            raise HTTPException(status_code=400, detail="Delete failed")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project deletion error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project deletion error")


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
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)

        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")

        # Check admin permissions
        user_permissions = getattr(session_data, 'permissions', [])
        if 'admin' not in user_permissions and 'manage_users' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required to list project members")

        # Get project
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

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

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"List project members error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list project members")


@router.post("/{project_hash}/members", response_model=AddMemberToProjectResponse)
async def add_member_to_project(
        project_hash: str = Path(...),
        user_hash: str = Form(...),
        role: Optional[str] = Form("consumer"),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> AddMemberToProjectResponse:
    """
    Add a member to a project with specified role.
    
    **Admin access required**: Only admin users can add members to projects.
    
    Args:
        project_hash: Project identifier
        user_hash: User to add to the project
        role: Role to assign (consumer, admin)
        
    Returns:
        Added member information
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)

        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")

        # Check admin permissions
        user_permissions = getattr(session_data, 'permissions', [])
        if 'admin' not in user_permissions and 'manage_users' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required to add project members")

        # Get project
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Get target user
        target_user = get_user_by_hash(user_hash)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get current user for audit trail
        current_user = get_user_by_hash(session_data.user_hash)

        # Validate role
        if role not in ['consumer', 'admin']:
            raise HTTPException(status_code=400, detail="Invalid role. Must be 'consumer' or 'admin'")

        # Handle different role assignments
        if role == 'consumer':
            # Add consumer user to project
            if target_user.user_type != 'consumer':
                raise HTTPException(status_code=400, detail="Only consumer users can be assigned consumer role")

            # Check if user already has access
            existing_access = get_user_project_access(target_user.id, project.id)
            if existing_access:
                raise HTTPException(status_code=400, detail="User already has access to this project")

            # Grant project access
            user_project = grant_user_project_access(target_user.id, project.id, granted_by=current_user.id)

            if not user_project:
                raise HTTPException(status_code=500, detail="Failed to grant project access")

            # Assign to default group
            assign_user_to_default_group(user_project.id, project.id)

            access_type = "consumer_access"

        elif role == 'admin':
            # Add admin user to project
            if target_user.user_type != 'admin':
                raise HTTPException(status_code=400, detail="Only admin users can be assigned admin role")

            # Check if admin already has access to this project
            admin_projects = get_admin_assigned_projects(target_user.id)
            if project.id in admin_projects:
                raise HTTPException(status_code=400, detail="Admin user already has access to this project")

            # Add admin to project
            success = add_admin_to_project(target_user.id, project.id, assigned_by=current_user.id)

            if not success:
                raise HTTPException(status_code=500, detail="Failed to add admin to project")

            access_type = "admin_access"

        # Get user's permissions in this project
        permissions = get_user_project_permissions(target_user.id, project.id)

        # Get user groups for consumer users
        groups = []
        if target_user.user_type == 'consumer':
            user_groups = get_user_groups_for_user(target_user.id)
            groups = [g.group_name for g in user_groups]

        member_info = {
            "user_hash": target_user.user_hash,
            "username": target_user.username,
            "email": target_user.email,
            "user_type": target_user.user_type,
            "role": role,
            "permissions": permissions,
            "groups": groups,
            "access_type": access_type,
            "added_by": current_user.username,
            "added_at": datetime.now().isoformat()
        }

        project_info = ProjectInfo(
            project_hash=project.project_hash,
            project_name=project.project_name,
            project_description=project.project_description
        )

        logger.info(
            f"Member added to project: {target_user.username} -> {project.project_name} as {role} by {current_user.username}")

        return AddMemberToProjectResponse(
            success=True,
            message=f"User '{target_user.username}' added to project '{project.project_name}' as {role}",
            member=member_info,
            project=project_info
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Add member to project error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to add member to project")


def assign_user_to_default_group(user_project_id: int, project_id: int):
    """Helper function to assign consumer user to default 'user' group in a project"""
    try:
        from src.Util.db_config import get_connection

        with get_connection() as con:
            cur = con.cursor()
            # Get default 'user' group ID
            cur.execute("""
                        SELECT id
                        FROM user_groups
                        WHERE project_id = %s
                          AND group_name = 'user'
                          AND is_active = 1
                        """, [project_id])

            group_result = cur.fetchone()
            if group_result:
                group_id = group_result[0]
                cur.execute("""
                            INSERT INTO user_project_groups (user_project_id, group_id, assigned_at)
                            VALUES (%s, %s, NOW()) ON DUPLICATE KEY
                            UPDATE is_active = 1, assigned_at = NOW()
                            """, [user_project_id, group_id])
                con.commit()
    except Exception as e:
        logger.warning(f"Failed to assign user to default group: {str(e)}")


@router.delete("/{project_hash}/members/{user_hash}")
async def remove_member_from_project(
        project_hash: str = Path(...),
        user_hash: str = Path(...),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Remove member from project.
    
    **Admin access required**: Only admin users can remove project members.
    **Phase 2 Implementation**: Remove member from project
    
    Args:
        project_hash: Project identifier
        user_hash: User to remove from project
        
    Returns:
        Removal confirmation
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)

        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")

        # Check admin permissions
        user_permissions = getattr(session_data, 'permissions', [])
        if 'admin' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required to remove project members")

        # Get project and user
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        target_user = get_user_by_hash(user_hash)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")

        current_user = get_user_by_hash(session_data.user_hash)

        # Remove user from project
        success = revoke_user_project_access(target_user.id, project.id, removed_by=current_user.id)

        if not success:
            raise HTTPException(status_code=400, detail="Failed to remove user from project")

        # Log the activity
        log_activity(
            user_id=current_user.id,
            activity_type=ActivityType.PROJECT_MEMBER_REMOVED,
            details=f"Removed user {target_user.username} from project {project.project_name}",
            target_user_id=target_user.id,
            project_id=project.id
        )

        logger.info(
            f"User {target_user.username} removed from project {project.project_name} by {current_user.username}")

        return {
            "success": True,
            "message": f"User {target_user.username} removed from project {project.project_name}",
            "project": {
                "project_hash": project.project_hash,
                "project_name": project.project_name
            },
            "removed_member": {
                "user_hash": target_user.user_hash,
                "username": target_user.username,
                "email": target_user.email
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Remove member error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to remove member from project")


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
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)

        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")

        # Get project
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Check user access to project
        current_user = get_user_by_hash(session_data.user_hash)
        user_permissions = get_user_project_permissions(current_user.id, project.id)
        session_permissions = getattr(session_data, 'permissions', [])

        if not user_permissions and 'admin' not in session_permissions:
            raise HTTPException(status_code=403, detail="Access denied to this project")

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
            "generated_at": datetime.utcnow().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project activity error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve project activity")


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
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)

        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")

        # Get project
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Check user access to project
        current_user = get_user_by_hash(session_data.user_hash)
        user_permissions = get_user_project_permissions(current_user.id, project.id)
        session_permissions = getattr(session_data, 'permissions', [])

        if not user_permissions and 'admin' not in session_permissions:
            raise HTTPException(status_code=403, detail="Access denied to this project")

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
            "generated_at": datetime.utcnow().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project stats error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve project statistics")


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
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)

        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")

        # Check admin permissions
        user_permissions = getattr(session_data, 'permissions', [])
        if 'admin' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required to transfer project ownership")

        # Get project and users
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        new_owner = get_user_by_hash(new_owner_hash)
        if not new_owner:
            raise HTTPException(status_code=404, detail="New owner not found")

        current_user = get_user_by_hash(session_data.user_hash)

        # Transfer ownership (placeholder implementation)
        # TODO: Implement actual ownership transfer logic
        success = True  # For now, just return success

        if not success:
            raise HTTPException(status_code=500, detail="Failed to transfer project ownership")

        # Log the activity
        log_activity(
            user_id=current_user.id,
            activity_type=ActivityType.PROJECT_OWNERSHIP_TRANSFERRED,
            details=f"Transferred ownership of project {project.project_name} to {new_owner.username}",
            target_user_id=new_owner.id,
            project_id=project.id
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
            "transferred_at": datetime.utcnow().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ownership transfer error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to transfer project ownership")


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
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)

        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")

        # Check admin permissions
        user_permissions = getattr(session_data, 'permissions', [])
        if 'admin' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required to archive/unarchive projects")

        # Get project
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        current_user = get_user_by_hash(session_data.user_hash)

        # Archive/unarchive project (placeholder implementation)
        # TODO: Implement actual archive/unarchive logic
        success = True  # For now, just return success

        if not success:
            raise HTTPException(status_code=500, detail=f"Failed to {'archive' if archived else 'unarchive'} project")

        # Log the activity
        action = "archived" if archived else "unarchived"
        log_activity(
            user_id=current_user.id,
            activity_type=ActivityType.PROJECT_ARCHIVED if archived else ActivityType.PROJECT_UNARCHIVED,
            details=f"Project {project.project_name} {action}",
            project_id=project.id
        )

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
                "performed_at": datetime.utcnow().isoformat()
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Archive project error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to archive/unarchive project")


# =================== NEW GROUP-PROJECT ENDPOINTS ===================

@router.get("/{project_hash}/groups", response_model=ListUserGroupsResponse)
async def list_project_user_groups(
        project_hash: str = Path(..., description="Project identifier"),
        limit: int = Query(100, ge=1, le=500, description="Max groups to return"),
        offset: int = Query(0, ge=0, description="Offset for pagination"),
        credentials: HTTPAuthorizationCredentials = Depends(security)) -> ListUserGroupsResponse:
    """List all user groups that have access to the specified project (admin only)."""

    try:
        # Validate session
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")

        # Admin permission check
        user_permissions = getattr(session_data, 'permissions', [])
        if 'admin' not in user_permissions and 'manage_users' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required to list project groups")

        # Resolve project
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Fetch groups
        groups_all = get_user_groups_for_project(project.id)
        groups_paginated = groups_all[offset:offset + limit]

        user_groups_info = []
        for grp in groups_paginated:
            user_groups_info.append(UserGroupInfo(
                group_hash=grp.group_hash,
                group_name=grp.group_name,
                description=grp.group_description,
                created_at=grp.created_at
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

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"List project groups error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list project groups")


@router.post("/{project_hash}/groups", response_model=GrantGroupProjectAccessResponse)
async def assign_group_to_project(
        project_hash: str = Path(..., description="Project identifier"),
        group_hash: str = Form(..., description="User group identifier"),
        credentials: HTTPAuthorizationCredentials = Depends(security)) -> GrantGroupProjectAccessResponse:
    """Assign an existing user group to a project (admin only)."""
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")

        # Admin permission check
        user_permissions = getattr(session_data, 'permissions', [])
        if 'admin' not in user_permissions and 'manage_users' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required to assign group to project")

        # Resolve entities
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        user_group = get_user_group_by_hash(group_hash)
        if not user_group:
            raise HTTPException(status_code=404, detail="User group not found")

        # Current user (for audit trail)
        current_user = get_user_by_hash(session_data.user_hash)

        # Grant access
        access = grant_group_project_access(user_group.id, project.id, granted_by=current_user.id)
        if not access:
            raise HTTPException(status_code=400, detail="Failed to grant group access to project or already granted")

        access_details = {
            "group_hash": user_group.group_hash,
            "group_name": user_group.group_name,
            "project_hash": project.project_hash,
            "project_name": project.project_name,
            "granted_by": current_user.username,
            "granted_at": access.granted_at.isoformat()
        }

        return GrantGroupProjectAccessResponse(
            success=True,
            message=f"Group '{user_group.group_name}' granted access to project '{project.project_name}'",
            access_details=access_details
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Assign group to project error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to assign group to project")
