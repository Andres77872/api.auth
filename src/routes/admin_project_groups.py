"""
Admin Project Group Management Routes

Handles project group (permission group) administration including creation,
management, and permission control for the group-based multi-project authentication system.
"""

import logging
from typing import List
from fastapi import APIRouter, HTTPException, Depends, Query, Path, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from src.Util.db import (
    validate_session, get_user_by_hash, get_project_by_hash,
    create_project_permission_group, get_project_permission_group_by_id,
    get_project_permission_group_by_hash, get_project_permission_group_by_name,
    list_all_project_permission_groups, update_project_permission_group,
    delete_project_permission_group, count_project_permission_groups,
    assign_project_to_permission_group, remove_project_from_permission_group,
    get_permission_groups_for_project, get_projects_in_permission_group
)

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/admin/project-groups", tags=["Admin - Project Groups"])
security = HTTPBearer()

# Pydantic models
class ProjectGroupCreate(BaseModel):
    group_name: str
    permissions: List[str]
    description: str = None

class ProjectGroupUpdate(BaseModel):
    group_name: str = None
    permissions: List[str] = None
    description: str = None

class ProjectAssignment(BaseModel):
    project_hash: str
    project_group_hash: str = None


# Helper function to check admin permissions
async def require_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Ensure user has admin permissions"""
    session_data = validate_session(credentials.credentials)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    user_permissions = session_data.permissions if hasattr(session_data, 'permissions') else []
    if 'admin' not in user_permissions and 'manage_roles' not in user_permissions:
        raise HTTPException(status_code=403, detail="Admin or manage_roles permission required")
    
    return session_data


@router.get("")
async def list_project_groups(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session_data = Depends(require_admin)
):
    """
    List all project permission groups (admin only).
    
    Returns:
        List of project groups with project counts
    """
    try:
        # Get all project groups
        project_groups = list_all_project_permission_groups(limit, offset)
        
        # Add project counts
        groups_with_counts = []
        for group in project_groups:
            projects = get_projects_in_permission_group(group.id)
            groups_with_counts.append({
                "group_hash": group.group_hash,
                "group_name": group.group_name,
                "description": group.description,
                "permissions": group.permissions,
                "project_count": len(projects),
                "created_at": group.created_at,
                "is_active": group.is_active
            })
        
        return {
            "success": True,
            "project_groups": groups_with_counts,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total": len(groups_with_counts)
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project groups listing error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project groups listing error")


@router.post("")
async def create_project_group_endpoint(
    group_data: ProjectGroupCreate,
    session_data = Depends(require_admin)
):
    """
    Create a new project permission group (admin only).
    
    Args:
        group_data: Project group creation data
        
    Returns:
        Created project group information
    """
    try:
        # Get current user for audit trail
        user_data = get_user_by_hash(session_data.user_hash)
        
        # Create project group
        new_group = create_project_permission_group(
            group_data.group_name,
            group_data.permissions,
            group_data.description,
            created_by=user_data.id
        )
        
        if not new_group:
            raise HTTPException(status_code=400, detail="Project group creation failed")
        
        return {
            "success": True,
            "message": f"Project group \"{group_data.group_name}\" created successfully",
            "project_group": {
                "group_hash": new_group.group_hash,
                "group_name": new_group.group_name,
                "description": new_group.description,
                "permissions": new_group.permissions,
                "created_at": new_group.created_at
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project group creation error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project group creation error")


@router.get("/{group_hash}")
async def get_project_group_details(
    group_hash: str = Path(...),
    session_data = Depends(require_admin)
):
    """
    Get detailed project group information (admin only).
    
    Args:
        group_hash: Project group identifier
        
    Returns:
        Project group details with assigned projects
    """
    try:
        # Get project group
        project_group = get_project_permission_group_by_hash(group_hash)
        if not project_group:
            raise HTTPException(status_code=404, detail="Project group not found")
        
        # Get assigned projects
        assigned_projects = get_projects_in_permission_group(project_group.id)
        
        return {
            "success": True,
            "project_group": {
                "group_hash": project_group.group_hash,
                "group_name": project_group.group_name,
                "description": project_group.description,
                "permissions": project_group.permissions,
                "created_at": project_group.created_at,
                "is_active": project_group.is_active
            },
            "assigned_projects": [
                {
                    "project_hash": project.project_hash,
                    "project_name": project.project_name,
                    "project_description": project.project_description
                } for project in assigned_projects
            ],
            "statistics": {
                "total_projects": len(assigned_projects),
                "total_permissions": len(project_group.permissions)
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project group details error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project group details error")


@router.put("/{group_hash}")
async def update_project_group_endpoint(
    group_hash: str = Path(...),
    group_data: ProjectGroupUpdate = None,
    session_data = Depends(require_admin)
):
    """
    Update project group information (admin only).
    
    Args:
        group_hash: Project group identifier
        group_data: Update data
        
    Returns:
        Updated project group information
    """
    try:
        # Get project group
        project_group = get_project_permission_group_by_hash(group_hash)
        if not project_group:
            raise HTTPException(status_code=404, detail="Project group not found")
        
        # Update group
        updated_group = update_project_permission_group(
            project_group.id,
            group_name=group_data.group_name if group_data else None,
            group_description=group_data.description if group_data else None,
            permissions=group_data.permissions if group_data else None
        )
        
        if not updated_group:
            raise HTTPException(status_code=400, detail="Update failed")
        
        return {
            "success": True,
            "message": "Project group updated successfully",
            "project_group": {
                "group_hash": updated_group.group_hash,
                "group_name": updated_group.group_name,
                "description": updated_group.description,
                "permissions": updated_group.permissions
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project group update error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project group update error")


@router.delete("/{group_hash}")
async def delete_project_group_endpoint(
    group_hash: str = Path(...),
    session_data = Depends(require_admin)
):
    """
    Delete a project group (admin only).
    
    Args:
        group_hash: Project group identifier
        
    Returns:
        Deletion confirmation
    """
    try:
        # Get project group
        project_group = get_project_permission_group_by_hash(group_hash)
        if not project_group:
            raise HTTPException(status_code=404, detail="Project group not found")
        
        # Get current user for audit trail
        user_data = get_user_by_hash(session_data.user_hash)
        
        # Delete group
        if delete_project_permission_group(project_group.id, deleted_by=user_data.id):
            return {
                "success": True,
                "message": f"Project group \"{project_group.group_name}\" deleted successfully",
                "warning": "All project assignments have been removed"
            }
        else:
            raise HTTPException(status_code=400, detail="Delete failed")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project group deletion error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project group deletion error")


@router.post("/{group_hash}/projects")
async def assign_project_to_group_endpoint(
    group_hash: str = Path(...),
    assignment: ProjectAssignment = None,
    project_hash: str = Form(None),
    session_data = Depends(require_admin)
):
    """
    Assign a project to a project group (admin only).
    
    Args:
        group_hash: Project group identifier
        assignment: Project assignment data (JSON) or
        project_hash: Project hash (form data)
        
    Returns:
        Assignment confirmation
    """
    try:
        # Get target project hash
        target_project_hash = assignment.project_hash if assignment else project_hash
        if not target_project_hash:
            raise HTTPException(status_code=400, detail="Project hash required")
        
        # Get project group
        project_group = get_project_permission_group_by_hash(group_hash)
        if not project_group:
            raise HTTPException(status_code=404, detail="Project group not found")
        
        # Get target project
        target_project = get_project_by_hash(target_project_hash)
        if not target_project:
            raise HTTPException(status_code=404, detail="Target project not found")
        
        # Get current user for audit trail
        current_user = get_user_by_hash(session_data.user_hash)
        
        # Assign project to group
        assignment_result = assign_project_to_permission_group(
            target_project.id,
            project_group.id,
            assigned_by=current_user.id
        )
        
        if not assignment_result:
            raise HTTPException(status_code=400, detail="Assignment failed")
        
        return {
            "success": True,
            "message": f"Project \"{target_project.project_name}\" assigned to group \"{project_group.group_name}\"",
            "assignment": {
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
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project group assignment error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project group assignment error")


@router.delete("/{group_hash}/projects/{project_hash}")
async def remove_project_from_group_endpoint(
    group_hash: str = Path(...),
    project_hash: str = Path(...),
    session_data = Depends(require_admin)
):
    """
    Remove a project from a project group (admin only).
    
    Args:
        group_hash: Project group identifier
        project_hash: Project identifier
        
    Returns:
        Removal confirmation
    """
    try:
        # Get project group
        project_group = get_project_permission_group_by_hash(group_hash)
        if not project_group:
            raise HTTPException(status_code=404, detail="Project group not found")
        
        # Get project
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Get current user for audit trail
        current_user = get_user_by_hash(session_data.user_hash)
        
        # Remove project from group
        if remove_project_from_permission_group(project.id, project_group.id, removed_by=current_user.id):
            return {
                "success": True,
                "message": f"Project \"{project.project_name}\" removed from group \"{project_group.group_name}\""
            }
        else:
            raise HTTPException(status_code=400, detail="Removal failed")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project group removal error: {str(e)}")
        raise HTTPException(status_code=500, detail="Project group removal error") 