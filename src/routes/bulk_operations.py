"""
Bulk Operations Routes - Phase 2 Implementation

Handles bulk operations for users, projects, and other entities
for efficient mass management in the authentication system.
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Form
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.activity_logger import ActivityLogger, ActivityType
from src.Util.bulk_operations import (
    bulk_update_users, bulk_delete_users,
    bulk_assign_roles, bulk_add_users_to_group
)
from src.Util.db import validate_session, get_user_by_hash

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/admin", tags=["Bulk Operations"])
security = HTTPBearerOrCookie()


# Pydantic models
class BulkUpdateRequest(BaseModel):
    user_hashes: List[str]
    updates: Dict[str, Any]


class BulkDeleteRequest(BaseModel):
    user_hashes: List[str]
    confirm_deletion: bool = False


class BulkRoleAssignRequest(BaseModel):
    user_hashes: List[str]
    project_hash: str
    role_names: List[str]


class BulkGroupAssignRequest(BaseModel):
    user_hashes: List[str]
    group_names: List[str]


@router.post("/users/bulk-update")
async def bulk_update_users_endpoint(
        user_hashes: List[str] = Form(...),
        is_active: Optional[bool] = Form(None),
        user_type: Optional[str] = Form(None),
        force_password_reset: Optional[bool] = Form(None),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Update multiple users at once.
    
    **Admin access required**: Only admin users can perform bulk updates.
    **Phase 2 Implementation**: Bulk user updates with transaction support
    
    Args:
        user_hashes: List of user hashes to update
        is_active: Set active status for all users
        user_type: Set user type for all users
        force_password_reset: Force password reset on next login
        
    Returns:
        Success/error count with details
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)

        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")

        # Check admin permissions
        current_user = get_user_by_hash(session_data.user_hash)
        user_permissions = getattr(session_data, 'permissions', [])

        if 'admin' not in user_permissions and 'manage_users' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required for bulk operations")

        # Validate input
        if not user_hashes:
            raise HTTPException(status_code=400, detail="At least one user hash is required")

        if len(user_hashes) > 100:
            raise HTTPException(status_code=400, detail="Maximum 100 users can be updated at once")

        # Validate user type if provided
        if user_type and user_type not in ['root', 'admin', 'consumer']:
            raise HTTPException(status_code=400, detail="Invalid user type")

        # Build updates dictionary
        updates = {}
        if is_active is not None:
            updates['is_active'] = is_active
        if user_type:
            updates['user_type'] = user_type
        if force_password_reset is not None:
            updates['force_password_reset'] = force_password_reset

        if not updates:
            raise HTTPException(status_code=400, detail="At least one update field is required")

        # Perform bulk update
        result = bulk_update_users(user_hashes, updates, current_user.id)

        # Log the activity
        ActivityLogger.log_bulk_user_update(
            current_user.id,
            count=result['success_count'],
            project_id=getattr(session_data, 'project_id', None)
        )

        logger.info(
            f"Bulk user update by {current_user.username}: {result['success_count']} succeeded, {result['error_count']} failed")

        return {
            "success": True,
            "message": f"Bulk update completed: {result['success_count']} succeeded, {result['error_count']} failed",
            "summary": {
                "total_requested": len(user_hashes),
                "success_count": result['success_count'],
                "error_count": result['error_count'],
                "skipped_count": result.get('skipped_count', 0)
            },
            "updates_applied": updates,
            "results": result['results'],
            "errors": result.get('errors', []),
            "performed_by": current_user.username,
            "performed_at": datetime.utcnow().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bulk update error: {str(e)}")
        raise HTTPException(status_code=500, detail="Bulk update failed")


@router.post("/users/bulk-delete")
async def bulk_delete_users_endpoint(
        user_hashes: List[str] = Form(...),
        confirm_deletion: bool = Form(False),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Delete multiple users.
    
    **Admin access required**: Only admin users can perform bulk deletions.  
    **Phase 2 Implementation**: Bulk user deletions with safety checks
    
    Args:
        user_hashes: List of user hashes to delete
        confirm_deletion: Explicit confirmation required for deletion
        
    Returns:
        Deletion count and any errors
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)

        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")

        # Check admin permissions
        current_user = get_user_by_hash(session_data.user_hash)
        user_permissions = getattr(session_data, 'permissions', [])

        if 'admin' not in user_permissions and 'manage_users' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required for bulk operations")

        # Safety checks
        if not confirm_deletion:
            raise HTTPException(status_code=400, detail="Deletion must be explicitly confirmed")

        if not user_hashes:
            raise HTTPException(status_code=400, detail="At least one user hash is required")

        if len(user_hashes) > 50:
            raise HTTPException(status_code=400, detail="Maximum 50 users can be deleted at once")

        # Perform bulk deletion
        result = bulk_delete_users(user_hashes, current_user.id)

        # Log the activity
        ActivityLogger.log_bulk_user_delete(
            current_user.id,
            count=result['success_count'],
            project_id=getattr(session_data, 'project_id', None)
        )

        logger.info(
            f"Bulk user deletion by {current_user.username}: {result['success_count']} succeeded, {result['error_count']} failed")

        return {
            "success": True,
            "message": f"Bulk deletion completed: {result['success_count']} deleted, {result['error_count']} failed",
            "summary": {
                "total_requested": len(user_hashes),
                "success_count": result['success_count'],
                "error_count": result['error_count'],
                "protected_count": result.get('protected_count', 0)
            },
            "results": result['results'],
            "errors": result.get('errors', []),
            "warnings": result.get('warnings', []),
            "performed_by": current_user.username,
            "performed_at": datetime.utcnow().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bulk deletion error: {str(e)}")
        raise HTTPException(status_code=500, detail="Bulk deletion failed")


@router.post("/projects/{project_hash}/bulk-assign-roles")
async def bulk_assign_roles_to_project_users(
        project_hash: str,
        user_hashes: List[str] = Form(...),
        role_names: List[str] = Form(...),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Bulk assign roles to users in a project.
    
    **Admin access required**: Only admin users can perform bulk role assignments.
    **Phase 2 Implementation**: Bulk role assignments with validation
    
    Args:
        project_hash: Project identifier
        user_hashes: List of user hashes to assign roles to
        role_names: List of role names to assign
        
    Returns:
        Assignment results with success/error counts
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)

        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")

        # Check admin permissions
        current_user = get_user_by_hash(session_data.user_hash)
        user_permissions = getattr(session_data, 'permissions', [])

        if 'admin' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required for bulk role assignments")

        # Validate input
        if not user_hashes or not role_names:
            raise HTTPException(status_code=400, detail="User hashes and role names are required")

        if len(user_hashes) > 100:
            raise HTTPException(status_code=400, detail="Maximum 100 users can be assigned at once")

        # Get project
        from src.Util.db import get_project_by_hash
        project = get_project_by_hash(project_hash)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Perform bulk role assignment
        role_assignments = [{"user_hash": user_hash, "role_name": role_name} for user_hash in user_hashes for role_name
                            in role_names]
        result = bulk_assign_roles(project.project_hash, role_assignments, current_user.id)

        # Log the activity
        ActivityLogger.log_bulk_role_assignment(
            current_user.id,
            count=result['success_count'],
            project_id=project.id
        )

        logger.info(
            f"Bulk role assignment by {current_user.username} in project {project.project_name}: {result['success_count']} succeeded")

        return {
            "success": True,
            "message": f"Bulk role assignment completed: {result['success_count']} succeeded, {result['error_count']} failed",
            "project": {
                "project_hash": project.project_hash,
                "project_name": project.project_name
            },
            "roles_assigned": role_names,
            "summary": {
                "total_requested": len(user_hashes),
                "success_count": result['success_count'],
                "error_count": result['error_count']
            },
            "results": result['results'],
            "errors": result.get('errors', []),
            "performed_by": current_user.username,
            "performed_at": datetime.utcnow().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bulk role assignment error: {str(e)}")
        raise HTTPException(status_code=500, detail="Bulk role assignment failed")


@router.post("/user-groups/bulk-assign")
async def bulk_assign_users_to_groups(
        user_hashes: List[str] = Form(...),
        group_names: List[str] = Form(...),
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Bulk assign users to user groups.
    
    **Admin access required**: Only admin users can perform bulk group assignments.
    **Phase 2 Implementation**: Bulk user group assignments
    
    Args:
        user_hashes: List of user hashes to assign to groups
        group_names: List of group names to assign users to
        
    Returns:
        Assignment results with success/error counts
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)

        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")

        # Check admin permissions
        current_user = get_user_by_hash(session_data.user_hash)
        user_permissions = getattr(session_data, 'permissions', [])

        if 'admin' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required for bulk group assignments")

        # Validate input
        if not user_hashes or not group_names:
            raise HTTPException(status_code=400, detail="User hashes and group names are required")

        if len(user_hashes) > 100:
            raise HTTPException(status_code=400, detail="Maximum 100 users can be assigned at once")

        # Perform bulk group assignment
        result = {}
        for group_name in group_names:
            group_result = bulk_add_users_to_group(group_name, user_hashes, current_user.id)
            if not result:
                result = group_result
            else:
                result['success_count'] += group_result.get('success_count', 0)
                result['error_count'] += group_result.get('error_count', 0)

        # Log the activity
        ActivityLogger.log_bulk_group_assignment(
            current_user.id,
            count=result['success_count'],
            project_id=getattr(session_data, 'project_id', None)
        )

        logger.info(
            f"Bulk group assignment by {current_user.username}: {result['success_count']} users assigned to groups")

        return {
            "success": True,
            "message": f"Bulk group assignment completed: {result['success_count']} succeeded, {result['error_count']} failed",
            "groups_assigned": group_names,
            "summary": {
                "total_requested": len(user_hashes),
                "success_count": result['success_count'],
                "error_count": result['error_count']
            },
            "results": result['results'],
            "errors": result.get('errors', []),
            "performed_by": current_user.username,
            "performed_at": datetime.utcnow().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bulk group assignment error: {str(e)}")
        raise HTTPException(status_code=500, detail="Bulk group assignment failed")
