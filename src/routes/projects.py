"""
Project Management Routes

Handles project CRUD operations and project-related queries
for the group-based multi-project authentication system.
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query, Path
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from src.Util.db import (
    validate_session, get_user_by_hash,
    create_project, get_project_by_hash, list_all_projects,
    update_project, delete_project, search_projects,
    get_project_stats, get_user_accessible_projects,
    get_user_project_permissions, get_user_groups_for_user
)

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/projects", tags=["Project Management"])
security = HTTPBearer()

# Pydantic models
class ProjectCreate(BaseModel):
    project_name: str
    project_description: str = None

class ProjectUpdate(BaseModel):
    project_name: str = None
    project_description: str = None


@router.get("")
async def list_projects(
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: str = Query(None),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
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
        user_permissions = session_data.permissions if hasattr(session_data, 'permissions') else []
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
            projects = accessible_projects[offset:offset+limit] if accessible_projects else []
        
        # Add access level information
        projects_with_access = []
        for project in projects:
            project_hash = project.project_hash if hasattr(project, 'project_hash') else project.get('project_hash')
            project_permissions = get_user_project_permissions(user_data.id, project.id if hasattr(project, 'id') else project.get('project_id'))
            
            project_data = {
                "project_hash": project_hash,
                "project_name": project.project_name if hasattr(project, 'project_name') else project.get('project_name'),
                "project_description": project.project_description if hasattr(project, 'project_description') else project.get('project_description'),
                "access_level": "admin" if "admin" in project_permissions else ("read-write" if "write" in project_permissions else "read-only"),
                "access_through": "admin_access" if is_admin else "user_group"
            }
            projects_with_access.append(project_data)
        
        return {
            "success": True,
            "projects": projects_with_access,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total_count": len(projects_with_access),
                "has_more": len(projects_with_access) == limit
            },
            "user_access_level": "admin" if is_admin else "user"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project listing error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project listing error")


@router.post("")
async def create_new_project(
    project_data: ProjectCreate,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Create new project and assign it to default project group.
    
    Args:
        project_data: Project creation data
        
    Returns:
        Created project information
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        # Check if user has permission to create projects
        user_permissions = session_data.permissions if hasattr(session_data, 'permissions') else []
        if 'admin' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required to create projects")
        
        # Get current user for audit trail
        user_data = get_user_by_hash(session_data.user_hash)
        
        # Create project
        new_project = create_project(project_data.project_name, project_data.project_description)
        
        if not new_project:
            raise HTTPException(status_code=400, detail="Project creation failed")
        
        logger.info(f"Project created: {project_data.project_name} by user: {user_data.username}")
        
        return {
            "success": True,
            "message": f"Project \"{project_data.project_name}\" created successfully",
            "project": {
                "project_hash": new_project.project_hash,
                "project_name": new_project.project_name,
                "project_description": new_project.project_description,
                "created_at": new_project.project_created if hasattr(new_project, 'project_created') else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project creation error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project creation error")


@router.get("/{project_hash}")
async def get_project_details(
    project_hash: str = Path(...),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
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
        if not user_permissions and 'admin' not in (session_data.permissions if hasattr(session_data, 'permissions') else []):
            raise HTTPException(status_code=403, detail="Access denied to this project")
        
        # Get project statistics
        project_stats = get_project_stats(project.id)
        
        # Get user groups that have access to this project
        user_groups = get_user_groups_for_user(user_data.id)
        
        return {
            "success": True,
            "project": {
                "project_id": project.id,
                "project_hash": project.project_hash,
                "project_name": project.project_name,
                "project_description": project.project_description,
                "created_at": project.project_created if hasattr(project, 'project_created') else None,
                "is_active": project.is_active if hasattr(project, 'is_active') else True
            },
            "user_access": {
                "permissions": user_permissions,
                "access_level": "admin" if "admin" in user_permissions else ("read-write" if "write" in user_permissions else "read-only"),
                "user_groups": [group.group_name for group in user_groups]
            },
            "statistics": project_stats or {}
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project details error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project details error")


@router.put("/{project_hash}")
async def update_project_details(
    project_hash: str = Path(...),
    project_data: ProjectUpdate = None,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Update project information (admin only).
    
    Args:
        project_hash: Project identifier
        project_data: Project update data
        
    Returns:
        Updated project information
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        # Check admin permission
        user_permissions = session_data.permissions if hasattr(session_data, 'permissions') else []
        if 'admin' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required")
        
        # Get project
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Get current user for audit trail
        user_data = get_user_by_hash(session_data.user_hash)
        
        # Update project
        updated_project = update_project(
            project.id,
            project_name=project_data.project_name if project_data else None,
            project_description=project_data.project_description if project_data else None,
            updated_by=user_data.id
        )
        
        if not updated_project:
            raise HTTPException(status_code=400, detail="Update failed")
        
        return {
            "success": True,
            "message": "Project updated successfully",
            "project": {
                "project_id": updated_project.id,
                "project_hash": updated_project.project_hash,
                "project_name": updated_project.project_name,
                "project_description": updated_project.project_description,
                "updated_by": user_data.id
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project update error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project update error")


@router.delete("/{project_hash}")
async def delete_project_endpoint(
    project_hash: str = Path(...),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
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
        user_permissions = session_data.permissions if hasattr(session_data, 'permissions') else []
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
            return {
                "success": True,
                "message": f"Project \"{project.project_name}\" deleted successfully",
                "deleted_project": {
                    "project_hash": project.project_hash,
                    "project_name": project.project_name,
                    "deleted_by": user_data.id
                },
                "warning": "All user group access to this project has been revoked"
            }
        else:
            raise HTTPException(status_code=400, detail="Delete failed")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project deletion error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project deletion error") 