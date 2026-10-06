"""
Enhanced Multi-Project Authentication - Project Group Management
REFACTORED TO USE STORED PROCEDURES

This module handles all project group-related database operations in the new
hierarchical access control system where:
- Projects belong to Project Groups
- Project groups contain projects
- Users reach projects through user-group grants; global roles resolve permissions
"""

import json
import logging
import secrets
from datetime import datetime
from typing import List, Optional

import pymysql

from src.Util.Models import (
    Project, ProjectGroup, ProjectGroupMember, User
)
from src.Util.db_config import get_connection
from src.Util.db_error_wrapper import handle_db_operation
from src.Util.error_handler import ValidationError, ErrorCode
from src.Util.uuid_generator import generate_project_group_id, generate_project_group_member_id

# Configure logging
logger = logging.getLogger(__name__)


# =================== PROJECT GROUP MANAGEMENT ===================

def create_project_group(group_name: str, group_description: str = None,
                         created_by: str = None) -> ProjectGroup:
    """
    Create a project container using the canonical stored procedure.
    
    Args:
        group_name: Name of the project group
        group_description: Optional description
        created_by: User ID of creator
        
    Returns:
        Created ProjectGroup object
        
    Raises:
        ConflictError: If group name already exists
        ValidationError: If input validation fails
        DatabaseError: On database operation errors
    """
    def _create():
        group_id = generate_project_group_id()
        group_hash = secrets.token_hex(32).upper()

        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_create_project_group', [group_id, group_hash, group_name, group_description, created_by])
            
            # Clean up result sets
            while cur.nextset():
                pass
            
            con.commit()

            return ProjectGroup(
                id=group_id,
                group_hash=group_hash,
                group_name=group_name,
                group_description=group_description,
                created_at=datetime.now(),
                is_active=True
            )
    
    return handle_db_operation(
        _create,
        error_context=f"create_project_group(group_name={group_name})"
    )


def get_project_group_by_id(group_id: str) -> Optional[ProjectGroup]:
    """
    Get project group by ID using stored procedure.
    
    Args:
        group_id: Project group ID
        
    Returns:
        ProjectGroup object if found, None otherwise
        
    Raises:
        DatabaseError: On database operation errors
        
    Note:
        Returns None if not found (not an error condition).
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_project_group_by_id', [group_id])
            
            result = cur.fetchone()
            
            # Clean up result sets
            while cur.nextset():
                pass
            
            if result:
                # SP returns: id, group_hash, group_name, group_description, created_at, updated_at, created_by, is_active
                return ProjectGroup(
                    id=result[0],
                    group_hash=result[1],
                    group_name=result[2],
                    group_description=result[3],
                    created_at=result[4],
                    updated_at=result[5],
                    is_active=bool(result[7])
                )
        return None
    
    return handle_db_operation(
        _get,
        error_context=f"get_project_group_by_id(group_id={group_id})"
    )


def get_project_group_by_hash(group_hash: str) -> Optional[ProjectGroup]:
    """
    Get project group by hash using stored procedure.
    
    Args:
        group_hash: Project group hash
        
    Returns:
        ProjectGroup object if found, None otherwise
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_project_group_by_hash', [group_hash])
            
            result = cur.fetchone()
            
            # Clean up result sets
            while cur.nextset():
                pass
            
            if result:
                # SP returns: id, group_hash, group_name, group_description, created_at, updated_at, created_by, is_active
                return ProjectGroup(
                    id=result[0],
                    group_hash=result[1],
                    group_name=result[2],
                    group_description=result[3],
                    created_at=result[4],
                    updated_at=result[5],
                    is_active=bool(result[7])
                )
        return None
    
    return handle_db_operation(
        _get,
        error_context=f"get_project_group_by_hash(group_hash={group_hash[:8]}...)"
    )


def get_project_group_by_name(group_name: str) -> Optional[ProjectGroup]:
    """
    Get project group by name using stored procedure.
    
    Args:
        group_name: Project group name
        
    Returns:
        ProjectGroup object if found, None otherwise
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_project_group_by_name', [group_name])
            
            result = cur.fetchone()
            
            # Clean up result sets
            while cur.nextset():
                pass
            
            if result:
                # SP returns: id, group_hash, group_name, group_description, created_at, updated_at, created_by, is_active
                return ProjectGroup(
                    id=result[0],
                    group_hash=result[1],
                    group_name=result[2],
                    group_description=result[3],
                    created_at=result[4],
                    updated_at=result[5],
                    is_active=bool(result[7])
                )
        return None
    
    return handle_db_operation(
        _get,
        error_context=f"get_project_group_by_name(group_name={group_name})"
    )


def list_all_project_groups(
    limit: int = 100, 
    offset: int = 0,
    sort_by: str = 'group_name',
    sort_order: str = 'ASC',
    search: str = None
) -> List[ProjectGroup]:
    """
    List all active project groups with pagination using stored procedure.
    
    Args:
        limit: Maximum number of results
        offset: Number of results to skip
        sort_by: Column to sort by (group_name, created_at, updated_at)
        sort_order: Sort direction (ASC or DESC)
        search: Optional search term for group name
        
    Returns:
        List of ProjectGroup objects
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _list():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_list_all_project_groups', [limit, offset, sort_by, sort_order, search])
            
            results = []
            for row in cur.fetchall():
                # SP returns: id, group_hash, group_name, group_description, created_at, updated_at, is_active
                results.append(ProjectGroup(
                    id=row[0],
                    group_hash=row[1],
                    group_name=row[2],
                    group_description=row[3],
                    created_at=row[4],
                    updated_at=row[5],
                    is_active=bool(row[6])
                ))
            
            # Clean up result sets
            while cur.nextset():
                pass

            return results
    
    return handle_db_operation(
        _list,
        error_context=f"list_all_project_groups(limit={limit}, offset={offset}, sort_by={sort_by})"
    )


def update_project_group(group_id: str, group_name: str = None, group_description: str = None) -> Optional[ProjectGroup]:
    """
    Update project group information using stored procedure.
    
    Args:
        group_id: Project group ID
        group_name: New group name (optional)
        group_description: New description (optional)
        
    Returns:
        Updated ProjectGroup object, None if no fields to update
        
    Raises:
        NotFoundError: If group not found
        DatabaseError: On database operation errors
    """
    def _update():
        if not group_name and group_description is None:
            return None

        with get_connection() as con:
            cur = con.cursor()
            
            cur.callproc('sp_update_project_group', [group_id, group_name, group_description])
            
            # Clean up result sets
            while cur.nextset():
                pass
            
            con.commit()
            
            # Return updated group
            return get_project_group_by_id(group_id)
    
    return handle_db_operation(
        _update,
        error_context=f"update_project_group(group_id={group_id})"
    )


def delete_project_group(group_id: str, deleted_by: str = None) -> bool:
    """
    Soft delete a project group and all related relationships using stored procedure.
    
    Args:
        group_id: Project group ID
        deleted_by: User ID of deleter
        
    Returns:
        True if deleted successfully
        
    Raises:
        NotFoundError: If group not found
        DatabaseError: On database operation errors
    """
    def _delete():
        with get_connection() as con:
            cur = con.cursor()
            
            cur.callproc('sp_delete_project_group', [group_id, deleted_by])
            
            # Clean up result sets
            while cur.nextset():
                pass
            
            con.commit()
            return True
    
    return handle_db_operation(
        _delete,
        error_context=f"delete_project_group(group_id={group_id})"
    )


# =================== PROJECT GROUP MEMBERSHIP ===================

def assign_project_to_group(project_id: str, project_group_id: str, assigned_by: str = None) -> Optional[
    ProjectGroupMember]:
    """
    Assign a project to a project group using stored procedure.
    
    Args:
        project_id: Project ID
        project_group_id: Project group ID
        assigned_by: User ID of assigner
        
    Returns:
        ProjectGroupMember object representing the assignment
        
    Raises:
        NotFoundError: If project or group not found
        DatabaseError: On database operation errors
        
    Note:
        Auto-reactivates if assignment previously existed.
    """
    def _assign():
        with get_connection() as con:
            cur = con.cursor()

            try:
                member_id = generate_project_group_member_id()
                cur.callproc('sp_assign_project_to_group', [member_id, project_id, project_group_id, assigned_by])
                
                # Clean up result sets
                while cur.nextset():
                    pass
                
                con.commit()

                return ProjectGroupMember(
                    id=member_id,
                    project_id=project_id,
                    project_group_id=project_group_id,
                    assigned_at=datetime.now(),
                    assigned_by=assigned_by,
                    is_active=True
                )

            except Exception:
                con.rollback()
                raise
    
    return handle_db_operation(
        _assign,
        error_context=f"assign_project_to_group(project_id={project_id}, project_group_id={project_group_id})"
    )


def remove_project_from_group(project_id: str, project_group_id: str, removed_by: str = None) -> bool:
    """
    Remove a project from a project group using stored procedure.
    
    Args:
        project_id: Project ID
        project_group_id: Project group ID
        removed_by: User ID of remover
        
    Returns:
        True if removed successfully
        
    Raises:
        NotFoundError: If project or group not found
        DatabaseError: On database operation errors
    """
    def _remove():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_remove_project_from_group', [project_id, project_group_id, removed_by])
            
            # Clean up result sets
            while cur.nextset():
                pass
            
            con.commit()
            return True
    
    return handle_db_operation(
        _remove,
        error_context=f"remove_project_from_group(project_id={project_id}, project_group_id={project_group_id})"
    )


def get_project_groups_for_project(project_id: str) -> List[ProjectGroup]:
    """
    Get all project groups a project belongs to using stored procedure.
    
    Args:
        project_id: Project ID
        
    Returns:
        List of ProjectGroup objects
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_project_groups_for_project', [project_id])
            
            groups = []
            for row in cur.fetchall():
                # SP returns: id, group_hash, group_name, group_description,
                #             created_at, updated_at, is_active, assigned_at, assigned_by
                groups.append(ProjectGroup(
                    id=row[0],
                    group_hash=row[1],
                    group_name=row[2],
                    group_description=row[3],
                    created_at=row[4],
                    updated_at=row[5],
                    is_active=bool(row[6])
                ))
            
            # Clean up result sets
            while cur.nextset():
                pass

            return groups
    
    return handle_db_operation(
        _get,
        error_context=f"get_project_groups_for_project(project_id={project_id})"
    )


def get_projects_in_group(project_group_id: str) -> List[Project]:
    """
    Get all projects in a project group using stored procedure.
    
    Args:
        project_group_id: Project group ID
        
    Returns:
        List of Project objects
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_projects_in_project_group', [project_group_id])
            
            projects = []
            for row in cur.fetchall():
                projects.append(Project(
                    id=row[0],
                    project_hash=row[1],
                    project_name=row[2],
                    project_description=row[3],
                    project_created=row[4],
                    updated_at=row[5],
                    is_active=bool(row[6])
                ))
            
            # Clean up result sets
            while cur.nextset():
                pass

            return projects
    
    return handle_db_operation(
        _get,
        error_context=f"get_projects_in_group(project_group_id={project_group_id})"
    )


def get_users_with_access_to_project_group(project_group_id: str) -> List[User]:
    """Get active users with direct active access to a project group."""
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_users_with_access_to_project_group', [project_group_id])

            users = []
            for row in cur.fetchall():
                users.append(User(
                    id=row[0],
                    user_hash=row[1],
                    username=row[2],
                    email=row[3],
                    password_hash="",
                    user_type=row[4],
                    created_at=datetime.now(),
                    is_active=True,
                ))

            while cur.nextset():
                pass

            return users

    return handle_db_operation(
        _get,
        error_context=f"get_users_with_access_to_project_group(project_group_id={project_group_id})"
    )


# =================== PERMISSION UTILITIES ===================


# =================== DEFAULT GROUPS ===================


# =================== UTILITIES ===================

def count_project_groups(search: str = None) -> int:
    """
    Count total number of active project groups using stored procedure.
    
    Args:
        search: Optional search term to filter by group_name (LIKE)
    
    Returns:
        Count of active project groups
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _count():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_count_project_groups', [search])
            
            result = cur.fetchone()
            
            # Clean up result sets
            while cur.nextset():
                pass
            
            return result[0] if result else 0
    
    return handle_db_operation(
        _count,
        error_context=f"count_project_groups(search={search})"
    )
