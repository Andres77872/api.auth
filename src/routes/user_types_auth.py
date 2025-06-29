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
- Admin user project assignment management
"""

import logging
from fastapi import APIRouter, HTTPException, Depends, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional, List

from src.Util.db import (
    validate_session, get_user_by_hash, get_user_by_id,
    create_root_user, create_admin_user, create_consumer_user,
    get_user_type, get_admin_assigned_project, get_admin_assigned_projects,
    assign_admin_to_multiple_projects, add_admin_to_project, remove_admin_from_project,
    get_admin_project_assignments_with_details,
    update_user_type, assign_admin_to_project,
    is_root_user, is_admin_user, check_admin_project_access,
    get_user_type_info, list_users, count_users,
    get_project_by_id
)
from src.Util.Models import (
    CreateRootUserResponse, CreateAdminUserResponse, UserTypeInfoResponse,
    UpdateUserTypeResponse, ListUsersByTypeResponse, UserTypeStatsResponse,
    UpdateAdminProjectsResponse, AddAdminToProjectResponse, RemoveAdminFromProjectResponse,
    AdminProjectAssignmentsResponse,
    UserInfo, ProjectInfo, UserTypeInfo, PaginationInfo,
    CreateRootUserRequest, CreateAdminUserRequest, UpdateUserTypeRequest
)

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/user-types", tags=["User Type Management"])
security = HTTPBearer()

# Pydantic models for requests that aren't in Models.py
class UpdateAdminProject(BaseModel):
    assigned_project_id: int

class UpdateAdminProjects(BaseModel):
    assigned_project_ids: List[int]

class AddAdminToProject(BaseModel):
    project_id: int

class RemoveAdminFromProject(BaseModel):
    project_id: int


def require_root_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Middleware to ensure only root users can access certain endpoints"""
    session_token = credentials.credentials
    session_data = validate_session(session_token)
    
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    user = get_user_by_hash(session_data.user_hash)
    if not user or not is_root_user(user.id):
        raise HTTPException(status_code=403, detail="Root user access required")
    
    return user


def require_root_or_admin_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Middleware to ensure only root or admin users can access certain endpoints"""
    session_token = credentials.credentials
    session_data = validate_session(session_token)
    
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    user = get_user_by_hash(session_data.user_hash)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user_type = get_user_type(user.id)
    if user_type not in ['root', 'admin']:
        raise HTTPException(status_code=403, detail="Root or admin user access required")
    
    return user


@router.post("/root", response_model=CreateRootUserResponse)
async def create_root_user_endpoint(
    user_data: CreateRootUserRequest = None,
    username: str = Form(None),
    password: str = Form(None),
    email: Optional[str] = Form(None),
    current_user = Depends(require_root_user)
) -> CreateRootUserResponse:
    """
    Create a new root (super admin) user.
    
    **Root users only**: Only existing root users can create new root users.
    
    Accepts both JSON and form data:
    - JSON: Send CreateRootUserRequest object directly
    - Form: Send individual fields as form data
    
    Args:
        user_data: Root user creation data (JSON)
        username: Username (form)
        password: Password (form)
        email: Email (form)
        
    Returns:
        Created root user information
    """
    try:
        logger.info(f"Root user creation attempt by user: {current_user.username}")
        
        # Use JSON data if available, otherwise use form data
        if user_data:
            create_username = user_data.username
            create_password = user_data.password
            create_email = user_data.email
        else:
            create_username = username
            create_password = password
            create_email = email
        
        if not create_username or not create_password:
            raise HTTPException(status_code=400, detail="Username and password are required")
        
        # Create root user
        new_root_user = create_root_user(
            username=create_username,
            password=create_password,
            email=create_email,
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
            message=f"Root user '{create_username}' created successfully",
            user=user_info
        )
        
    except Exception as e:
        logger.error(f"Root user creation error: {str(e)}")
        if "Duplicate entry" in str(e):
            raise HTTPException(status_code=409, detail="Username or email already exists")
        raise HTTPException(status_code=500, detail="Root user creation failed")


@router.post("/admin", response_model=CreateAdminUserResponse)
async def create_admin_user_endpoint(
    user_data: CreateAdminUserRequest = None,
    username: str = Form(None),
    password: str = Form(None),
    email: str = Form(None),
    assigned_project_id: Optional[int] = Form(None),
    assigned_project_ids: Optional[List[int]] = Form(None),
    current_user = Depends(require_root_user)
) -> CreateAdminUserResponse:
    """
    Create a new admin user assigned to one or multiple projects.
    
    **Root users only**: Only root users can create admin users.
    
    Accepts both JSON and form data:
    - JSON: Send CreateAdminUserRequest object directly
    - Form: Send individual fields as form data
    
    Args:
        user_data: Admin user creation data (JSON)
        username: Username (form)
        password: Password (form)
        email: Email (form)
        assigned_project_id: Single project ID (form)
        assigned_project_ids: Multiple project IDs (form)
        
    Returns:
        Created admin user information with project assignment(s)
    """
    try:
        logger.info(f"Admin user creation attempt by user: {current_user.username}")
        
        # Use JSON data if available, otherwise use form data
        if user_data:
            create_username = user_data.username
            create_password = user_data.password
            create_email = user_data.email
            create_assigned_project_id = user_data.assigned_project_id
            create_assigned_project_ids = user_data.assigned_project_ids
        else:
            create_username = username
            create_password = password
            create_email = email
            create_assigned_project_id = assigned_project_id
            create_assigned_project_ids = assigned_project_ids
        
        if not create_username or not create_password or not create_email:
            raise HTTPException(status_code=400, detail="Username, password, and email are required")
        
        # Handle both single and multiple project assignments
        project_ids = []
        if create_assigned_project_ids:
            project_ids = create_assigned_project_ids
        elif create_assigned_project_id:
            project_ids = [create_assigned_project_id]
        else:
            raise HTTPException(status_code=400, detail="At least one project assignment is required")
        
        # Verify all projects exist
        projects = []
        for project_id in project_ids:
            project = get_project_by_id(project_id)
            if not project:
                raise HTTPException(status_code=404, detail=f"Project with ID {project_id} not found")
            projects.append(project)
        
        # Create admin user
        new_admin_user = create_admin_user(
            username=create_username,
            password=create_password,
            email=create_email,
            assigned_project_id=project_ids[0],  # Primary project for backwards compatibility
            assigned_project_ids=project_ids,    # All assigned projects
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
            message=f"Admin user '{create_username}' created and assigned to {len(projects)} project(s)",
            user=user_data_dict
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Admin user creation error: {str(e)}")
        if "Duplicate entry" in str(e):
            raise HTTPException(status_code=409, detail="Username or email already exists")
        raise HTTPException(status_code=500, detail="Admin user creation failed")


@router.get("/{user_hash}/info", response_model=UserTypeInfoResponse)
async def get_user_type_information(
    user_hash: str,
    current_user = Depends(require_root_or_admin_user)
) -> UserTypeInfoResponse:
    """
    Get comprehensive user type information.
    
    **Root/Admin access**: Root users can access any user, admin users can access users in their project.
    
    Args:
        user_hash: Hash of the user to get information for
        
    Returns:
        Comprehensive user type information including capabilities
    """
    try:
        target_user = get_user_by_hash(user_hash)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Access control: Root users can access anyone, admin users only their project users
        if not is_root_user(current_user.id):
            if is_admin_user(current_user.id):
                current_user_project = get_admin_assigned_project(current_user.id)
                target_user_project = get_admin_assigned_project(target_user.id)
                
                # Admin users can only access users in their project or other project admins in same project
                if target_user_project != current_user_project and get_user_type(target_user.id) != 'consumer':
                    raise HTTPException(status_code=403, detail="Access denied to user outside your project")
        
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
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get user type info error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get user type information")


@router.put("/{user_hash}/type", response_model=UpdateUserTypeResponse)
async def update_user_type_endpoint(
    user_hash: str,
    type_data: UpdateUserTypeRequest = None,
    user_type: str = Form(None),
    assigned_project_id: Optional[int] = Form(None),
    current_user = Depends(require_root_user)
) -> UpdateUserTypeResponse:
    """
    Update user type (promote/demote users).
    
    **Root users only**: Only root users can change user types.
    
    Accepts both JSON and form data:
    - JSON: Send UpdateUserTypeRequest object directly
    - Form: Send individual fields as form data
    
    Args:
        user_hash: Hash of the user to update
        type_data: New user type and optional project assignment (JSON)
        user_type: User type (form)
        assigned_project_id: Assigned project ID (form)
        
    Returns:
        Updated user type information
    """
    try:
        target_user = get_user_by_hash(user_hash)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Use JSON data if available, otherwise use form data
        if type_data:
            new_user_type = type_data.user_type
            new_assigned_project_id = type_data.assigned_project_id
        else:
            new_user_type = user_type
            new_assigned_project_id = assigned_project_id
        
        if not new_user_type:
            raise HTTPException(status_code=400, detail="User type is required")
        
        # Validate user type
        if new_user_type not in ['root', 'admin', 'consumer']:
            raise HTTPException(status_code=400, detail="Invalid user type. Must be 'root', 'admin', or 'consumer'")
        
        # Validate project assignment for admin users
        if new_user_type == 'admin':
            if not new_assigned_project_id:
                raise HTTPException(status_code=400, detail="Admin users must have an assigned project")
            
            project = get_project_by_id(new_assigned_project_id)
            if not project:
                raise HTTPException(status_code=404, detail="Assigned project not found")
        
        # Update user type
        success = update_user_type(
            user_id=target_user.id,
            new_user_type=new_user_type,
            assigned_project_id=new_assigned_project_id,
            updated_by=current_user.id
        )
        
        if not success:
            raise HTTPException(status_code=400, detail="Failed to update user type")
        
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
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update user type error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update user type")


@router.get("/users/{user_type}", response_model=ListUsersByTypeResponse)
async def list_users_by_type(
    user_type: str,
    limit: int = 50,
    offset: int = 0,
    current_user = Depends(require_root_or_admin_user)
) -> ListUsersByTypeResponse:
    """
    List users by user type.
    
    **Root/Admin access**: Root users see all users, admin users see users in their project scope.
    
    Args:
        user_type: Type of users to list ('root', 'admin', 'consumer')
        limit: Number of users to return (max 100)
        offset: Number of users to skip
        
    Returns:
        List of users with the specified type
    """
    try:
        # Validate user type
        if user_type not in ['root', 'admin', 'consumer']:
            raise HTTPException(status_code=400, detail="Invalid user type. Must be 'root', 'admin', or 'consumer'")
        
        # Limit constraints
        if limit > 100:
            limit = 100
        
        # Access control for admin users
        project_filter = None
        if not is_root_user(current_user.id) and is_admin_user(current_user.id):
            # Admin users can only see users in their project (for consumer users)
            # or other admin users assigned to the same project
            if user_type == 'root':
                raise HTTPException(status_code=403, detail="Admin users cannot list root users")
            
            if user_type in ['admin', 'consumer']:
                project_filter = get_admin_assigned_project(current_user.id)
        
        # Get users by type
        users = list_users(limit=limit, offset=offset, user_type=user_type, project_id=project_filter)
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
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"List users by type error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list users by type")


@router.put("/admin/{user_hash}/projects", response_model=UpdateAdminProjectsResponse)
async def update_admin_multiple_projects(
    user_hash: str,
    project_data: UpdateAdminProjects = None,
    assigned_project_ids: List[int] = Form(None),
    current_user = Depends(require_root_user)
) -> UpdateAdminProjectsResponse:
    """
    Update admin user's multiple project assignments.
    
    **Root users only**: Only root users can reassign admin users to multiple projects.
    
    Accepts both JSON and form data:
    - JSON: Send UpdateAdminProjects object directly
    - Form: Send assigned_project_ids as form data
    
    Args:
        user_hash: Hash of the admin user to update
        project_data: New project assignments (JSON)
        assigned_project_ids: Project IDs list (form)
        
    Returns:
        Updated project assignments information
    """
    try:
        target_user = get_user_by_hash(user_hash)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Verify user is admin
        if get_user_type(target_user.id) != 'admin':
            raise HTTPException(status_code=400, detail="User is not an admin user")
        
        # Use JSON data if available, otherwise use form data
        if project_data:
            update_project_ids = project_data.assigned_project_ids
        else:
            update_project_ids = assigned_project_ids
        
        if not update_project_ids:
            raise HTTPException(status_code=400, detail="At least one project assignment is required")
        
        # Verify all new projects exist
        projects = []
        for project_id in update_project_ids:
            project = get_project_by_id(project_id)
            if not project:
                raise HTTPException(status_code=404, detail=f"Project with ID {project_id} not found")
            projects.append(project)
        
        # Get old projects for logging
        old_assignments = get_admin_project_assignments_with_details(target_user.id)
        old_project_names = [a["project_name"] for a in old_assignments]
        
        # Update all project assignments
        success = assign_admin_to_multiple_projects(
            user_id=target_user.id,
            project_ids=update_project_ids,
            assigned_by=current_user.id
        )
        
        if not success:
            raise HTTPException(status_code=400, detail="Failed to update project assignments")
        
        # Update primary project in users table for backwards compatibility
        if update_project_ids:
            from src.Util.db.db_users import update_user
            update_user(target_user.id, assigned_project_id=update_project_ids[0])
        
        new_project_names = [p.project_name for p in projects]
        logger.info(f"Admin project assignments updated: {target_user.username} "
                   f"from [{', '.join(old_project_names)}] "
                   f"to [{', '.join(new_project_names)}]")
        
        assignment_info = {
            "user_hash": target_user.user_hash,
            "username": target_user.username,
            "previous_projects": old_project_names,
            "new_projects": [
                {
                    "project_id": p.id,
                    "project_hash": p.project_hash,
                    "project_name": p.project_name
                } for p in projects
            ],
            "total_projects": len(projects),
            "assigned_by": current_user.username
        }
        
        return UpdateAdminProjectsResponse(
            success=True,
            message=f"Admin user '{target_user.username}' reassigned to {len(projects)} project(s)",
            assignment=assignment_info
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update admin multiple projects error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update project assignments")


@router.post("/admin/{user_hash}/projects/add", response_model=AddAdminToProjectResponse)
async def add_admin_to_project_endpoint(
    user_hash: str,
    project_data: AddAdminToProject = None,
    project_id: int = Form(None),
    current_user = Depends(require_root_user)
) -> AddAdminToProjectResponse:
    """
    Add admin user to an additional project.
    
    **Root users only**: Only root users can add admin users to additional projects.
    
    Accepts both JSON and form data:
    - JSON: Send AddAdminToProject object directly
    - Form: Send project_id as form data
    
    Args:
        user_hash: Hash of the admin user
        project_data: Project to add (JSON)
        project_id: Project ID (form)
        
    Returns:
        Addition confirmation
    """
    try:
        target_user = get_user_by_hash(user_hash)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Verify user is admin
        if get_user_type(target_user.id) != 'admin':
            raise HTTPException(status_code=400, detail="User is not an admin user")
        
        # Use JSON data if available, otherwise use form data
        if project_data:
            add_project_id = project_data.project_id
        else:
            add_project_id = project_id
        
        if not add_project_id:
            raise HTTPException(status_code=400, detail="Project ID is required")
        
        # Verify project exists
        project = get_project_by_id(add_project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Check if already assigned
        current_assignments = get_admin_assigned_projects(target_user.id)
        if add_project_id in current_assignments:
            raise HTTPException(status_code=400, detail="Admin user is already assigned to this project")
        
        # Add to project
        success = add_admin_to_project(
            user_id=target_user.id,
            project_id=add_project_id,
            assigned_by=current_user.id
        )
        
        if not success:
            raise HTTPException(status_code=400, detail="Failed to add admin to project")
        
        logger.info(f"Admin user added to project: {target_user.username} -> {project.project_name}")
        
        assignment_info = {
            "user_hash": target_user.user_hash,
            "username": target_user.username,
            "added_project": {
                "project_id": project.id,
                "project_hash": project.project_hash,
                "project_name": project.project_name
            },
            "total_projects": len(get_admin_assigned_projects(target_user.id)),
            "assigned_by": current_user.username
        }
        
        return AddAdminToProjectResponse(
            success=True,
            message=f"Admin user '{target_user.username}' added to project '{project.project_name}'",
            assignment=assignment_info
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Add admin to project error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to add admin to project")


@router.delete("/admin/{user_hash}/projects/{project_id}", response_model=RemoveAdminFromProjectResponse)
async def remove_admin_from_project_endpoint(
    user_hash: str,
    project_id: int,
    current_user = Depends(require_root_user)
) -> RemoveAdminFromProjectResponse:
    """
    Remove admin user from a specific project.
    
    **Root users only**: Only root users can remove admin users from projects.
    
    Args:
        user_hash: Hash of the admin user
        project_id: Project ID to remove from
        
    Returns:
        Removal confirmation
    """
    try:
        target_user = get_user_by_hash(user_hash)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Verify user is admin
        if get_user_type(target_user.id) != 'admin':
            raise HTTPException(status_code=400, detail="User is not an admin user")
        
        # Verify project exists
        project = get_project_by_id(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Check if admin has remaining projects after removal
        current_assignments = get_admin_assigned_projects(target_user.id)
        if len(current_assignments) <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove admin from last assigned project. Admin users must have at least one project assignment.")
        
        # Remove from project
        success = remove_admin_from_project(
            user_id=target_user.id,
            project_id=project_id,
            removed_by=current_user.id
        )
        
        if not success:
            raise HTTPException(status_code=400, detail="Failed to remove admin from project")
        
        # Update primary project if needed
        remaining_projects = get_admin_assigned_projects(target_user.id)
        if remaining_projects and target_user.assigned_project_id == project_id:
            from src.Util.db.db_users import update_user
            update_user(target_user.id, assigned_project_id=remaining_projects[0])
        
        logger.info(f"Admin user removed from project: {target_user.username} -> {project.project_name}")
        
        removal_info = {
            "user_hash": target_user.user_hash,
            "username": target_user.username,
            "removed_project": {
                "project_id": project.id,
                "project_hash": project.project_hash,
                "project_name": project.project_name
            },
            "remaining_projects": len(remaining_projects),
            "removed_by": current_user.username
        }
        
        return RemoveAdminFromProjectResponse(
            success=True,
            message=f"Admin user '{target_user.username}' removed from project '{project.project_name}'",
            removal=removal_info
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Remove admin from project error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to remove admin from project")


@router.get("/admin/{user_hash}/projects", response_model=AdminProjectAssignmentsResponse)
async def get_admin_project_assignments(
    user_hash: str,
    current_user = Depends(require_root_or_admin_user)
) -> AdminProjectAssignmentsResponse:
    """
    Get all project assignments for an admin user.
    
    **Root/Admin access**: Root users can access any admin, admin users can only access their own assignments.
    
    Args:
        user_hash: Hash of the admin user
        
    Returns:
        List of project assignments
    """
    try:
        target_user = get_user_by_hash(user_hash)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Verify user is admin
        if get_user_type(target_user.id) != 'admin':
            raise HTTPException(status_code=400, detail="User is not an admin user")
        
        # Access control: Admin users can only see their own assignments
        if not is_root_user(current_user.id):
            if current_user.id != target_user.id:
                raise HTTPException(status_code=403, detail="Admin users can only view their own project assignments")
        
        # Get project assignments
        assignments = get_admin_project_assignments_with_details(target_user.id)
        
        user_info = UserInfo(
            user_hash=target_user.user_hash,
            username=target_user.username,
            email=target_user.email,
            user_type="admin",
            created_at=target_user.created_at
        )
        
        summary_info = {
            "total_projects": len(assignments),
            "primary_project": assignments[0] if assignments else None
        }
        
        return AdminProjectAssignmentsResponse(
            success=True,
            user=user_info,
            project_assignments=assignments,
            summary=summary_info
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get admin project assignments error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get project assignments")


@router.get("/stats", response_model=UserTypeStatsResponse)
async def get_user_type_statistics(
    current_user = Depends(require_root_or_admin_user)
) -> UserTypeStatsResponse:
    """
    Get user type statistics and distribution.
    
    **Root/Admin access**: Root users see global stats, admin users see project-scoped stats.
    
    Returns:
        User type statistics and system information
    """
    try:
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
        
    except Exception as e:
        logger.error(f"Get user type statistics error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get user type statistics") 