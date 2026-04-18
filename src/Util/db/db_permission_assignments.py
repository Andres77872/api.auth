"""
Database functions for Permission Assignment System
Handles user group and direct user assignment of permission groups
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import hashlib
import pymysql.cursors

from src.Util.db_config import get_connection
from src.Util.db_error_wrapper import handle_db_operation

logger = logging.getLogger(__name__)


def generate_hash(prefix: str, value: str) -> str:
    """Generate a unique hash"""
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    hash_input = f"{prefix}:{value}:{timestamp}"
    return hashlib.sha256(hash_input.encode()).hexdigest()[:32]


def generate_id(prefix: str) -> str:
    """Generate a unique ID"""
    timestamp = datetime.now(timezone.utc).timestamp()
    hash_input = f"{prefix}:{timestamp}"
    return f"{prefix}_{hashlib.sha256(hash_input.encode()).hexdigest()[:16]}"


# =================== USER GROUP PERMISSION GROUP ASSIGNMENTS ===================

def assign_permission_group_to_user_group(user_group_id: str, permission_group_id: str, 
                                         assigned_by: Optional[str] = None):
    """
    Assign permission group to user group.
    
    Args:
        user_group_id: User group ID
        permission_group_id: Permission group ID
        assigned_by: User ID of assigner
        
    Returns:
        True if assigned successfully
        
    Raises:
        NotFoundError: If user group or permission group not found
        ConflictError: If assignment already exists
        DatabaseError: On database operation errors
    """
    def _assign():
        with get_connection() as con:
            cur = con.cursor()
            link_id = generate_id('ugpg')
            
            cur.callproc('sp_assign_permission_group_to_user_group', (
                link_id, user_group_id, permission_group_id, assigned_by
            ))
            
            con.commit()
            return True
    
    return handle_db_operation(
        _assign,
        error_context=f"assign_permission_group_to_user_group(user_group_id={user_group_id}, permission_group_id={permission_group_id})"
    )


def remove_permission_group_from_user_group(user_group_id: str, permission_group_id: str,
                                           removed_by: Optional[str] = None):
    """
    Remove permission group from user group.
    
    Args:
        user_group_id: User group ID
        permission_group_id: Permission group ID
        removed_by: User ID of remover
        
    Returns:
        True if removed successfully
        
    Raises:
        NotFoundError: If assignment not found
        DatabaseError: On database operation errors
    """
    def _remove():
        with get_connection() as con:
            cur = con.cursor()
            
            cur.callproc('sp_remove_permission_group_from_user_group', (
                user_group_id, permission_group_id, removed_by
            ))
            
            con.commit()
            return True
    
    return handle_db_operation(
        _remove,
        error_context=f"remove_permission_group_from_user_group(user_group_id={user_group_id}, permission_group_id={permission_group_id})"
    )


def get_user_group_permission_groups(user_group_id: str):
    """
    Get permission groups assigned to a user group.
    
    Args:
        user_group_id: User group ID
        
    Returns:
        List of permission group dictionaries
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            
            cur.callproc('sp_get_user_group_permission_groups', (user_group_id,))
            return cur.fetchall()
    
    return handle_db_operation(
        _get,
        error_context=f"get_user_group_permission_groups(user_group_id={user_group_id})"
    )


def get_user_groups_with_permission_group(permission_group_id: str):
    """
    Get user groups that have a specific permission group.
    
    Args:
        permission_group_id: Permission group ID
        
    Returns:
        List of user group dictionaries
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            
            cur.callproc('sp_get_user_groups_with_permission_group', (permission_group_id,))
            return cur.fetchall()
    
    return handle_db_operation(
        _get,
        error_context=f"get_user_groups_with_permission_group(permission_group_id={permission_group_id})"
    )


# =================== DIRECT USER PERMISSION GROUP ASSIGNMENTS ===================

def assign_permission_group_to_user(user_id: str, permission_group_id: str,
                                   assigned_by: Optional[str] = None, notes: Optional[str] = None):
    """
    Assign permission group directly to user.
    
    Args:
        user_id: User ID
        permission_group_id: Permission group ID
        assigned_by: User ID of assigner
        notes: Optional notes
        
    Returns:
        True if assigned successfully
        
    Raises:
        NotFoundError: If user or permission group not found
        ConflictError: If assignment already exists
        DatabaseError: On database operation errors
    """
    def _assign():
        with get_connection() as con:
            cur = con.cursor()
            link_id = generate_id('upg')
            
            cur.callproc('sp_assign_permission_group_to_user', (
                link_id, user_id, permission_group_id, assigned_by, notes
            ))
            
            con.commit()
            return True
    
    return handle_db_operation(
        _assign,
        error_context=f"assign_permission_group_to_user(user_id={user_id}, permission_group_id={permission_group_id})"
    )


def remove_permission_group_from_user(user_id: str, permission_group_id: str,
                                     removed_by: Optional[str] = None):
    """
    Remove permission group from user.
    
    Args:
        user_id: User ID
        permission_group_id: Permission group ID
        removed_by: User ID of remover
        
    Returns:
        True if removed successfully
        
    Raises:
        NotFoundError: If assignment not found
        DatabaseError: On database operation errors
    """
    def _remove():
        with get_connection() as con:
            cur = con.cursor()
            
            cur.callproc('sp_remove_permission_group_from_user', (
                user_id, permission_group_id, removed_by
            ))
            
            con.commit()
            return True
    
    return handle_db_operation(
        _remove,
        error_context=f"remove_permission_group_from_user(user_id={user_id}, permission_group_id={permission_group_id})"
    )


def get_user_permission_groups(user_id: str):
    """
    Get permission groups directly assigned to a user.
    
    Args:
        user_id: User ID
        
    Returns:
        List of permission group dictionaries
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            
            cur.callproc('sp_get_user_permission_groups', (user_id,))
            return cur.fetchall()
    
    return handle_db_operation(
        _get,
        error_context=f"get_user_permission_groups(user_id={user_id})"
    )


def get_users_with_permission_group(permission_group_id: str):
    """
    Get users that have a specific permission group directly assigned.
    
    Args:
        permission_group_id: Permission group ID
        
    Returns:
        List of user dictionaries
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            
            cur.callproc('sp_get_users_with_permission_group', (permission_group_id,))
            return cur.fetchall()
    
    return handle_db_operation(
        _get,
        error_context=f"get_users_with_permission_group(permission_group_id={permission_group_id})"
    )


# =================== PERMISSION GROUP PROJECT CATALOG (METADATA ONLY) ===================

def add_permission_group_to_project_catalog(permission_group_id: str, project_id: str,
                                           catalog_purpose: Optional[str] = None,
                                           notes: Optional[str] = None,
                                           added_by: Optional[str] = None):
    """
    Add permission group to project catalog (METADATA ONLY - NOT used for authorization).
    
    Args:
        permission_group_id: Permission group ID
        project_id: Project ID
        catalog_purpose: Purpose of cataloging
        notes: Optional notes
        added_by: User ID of adder
        
    Returns:
        True if added successfully
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _add():
        with get_connection() as con:
            cur = con.cursor()
            catalog_id = generate_id('pgpc')
            
            cur.callproc('sp_add_permission_group_to_project_catalog', (
                catalog_id, permission_group_id, project_id, catalog_purpose, notes, added_by
            ))
            
            con.commit()
            return True
    
    return handle_db_operation(
        _add,
        error_context=f"add_permission_group_to_project_catalog(permission_group_id={permission_group_id}, project_id={project_id})"
    )


def remove_permission_group_from_project_catalog(permission_group_id: str, project_id: str,
                                                 removed_by: Optional[str] = None):
    """
    Remove permission group from project catalog.
    
    Args:
        permission_group_id: Permission group ID
        project_id: Project ID
        removed_by: User ID of remover
        
    Returns:
        True if removed successfully
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _remove():
        with get_connection() as con:
            cur = con.cursor()
            
            cur.callproc('sp_remove_permission_group_from_project_catalog', (
                permission_group_id, project_id, removed_by
            ))
            
            con.commit()
            return True
    
    return handle_db_operation(
        _remove,
        error_context=f"remove_permission_group_from_project_catalog(permission_group_id={permission_group_id}, project_id={project_id})"
    )


def get_project_cataloged_permission_groups(project_id: str):
    """
    Get permission groups cataloged for a project (METADATA - for UI suggestions only).
    
    Args:
        project_id: Project ID
        
    Returns:
        List of permission group dictionaries
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            
            cur.callproc('sp_get_project_cataloged_permission_groups', (project_id,))
            return cur.fetchall()
    
    return handle_db_operation(
        _get,
        error_context=f"get_project_cataloged_permission_groups(project_id={project_id})"
    )


def get_permission_group_cataloged_projects(permission_group_id: str):
    """
    Get projects that catalog a specific permission group.
    
    Args:
        permission_group_id: Permission group ID
        
    Returns:
        List of project dictionaries
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            
            cur.callproc('sp_get_permission_group_cataloged_projects', (permission_group_id,))
            return cur.fetchall()
    
    return handle_db_operation(
        _get,
        error_context=f"get_permission_group_cataloged_projects(permission_group_id={permission_group_id})"
    )


# =================== ENHANCED PERMISSION RESOLUTION ===================  

def get_user_all_permissions(user_id: str) -> List[str]:
    """
    Get all permissions for a user from all sources (GLOBAL - no project context needed).
    
    Args:
        user_id: User ID
        
    Returns:
        List of permission names
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            
            cur.callproc('sp_get_user_all_permissions', (user_id,))
            rows = cur.fetchall()
            return [row['permission_name'] for row in rows]
    
    return handle_db_operation(
        _get,
        error_context=f"get_user_all_permissions(user_id={user_id})"
    )


def check_user_has_permission_extended(user_id: str, permission_name: str) -> bool:
    """
    Check if user has permission from all sources (GLOBAL - no project context needed).
    
    Args:
        user_id: User ID
        permission_name: Permission name to check
        
    Returns:
        True if user has permission, False otherwise
        
    Raises:
        DatabaseError: On database operation errors
        
    Note:
        Returns False on error to prevent unauthorized access.
    """
    def _check():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            
            cur.callproc('sp_check_user_has_permission', (user_id, permission_name))
            row = cur.fetchone()
            return row['has_permission'] == 1 if row else False
    
    return handle_db_operation(
        _check,
        error_context=f"check_user_has_permission_extended(user_id={user_id}, permission_name={permission_name})",
        default_return=False
    )


def get_user_permission_sources(user_id: str):
    """
    Get detailed permission sources for a user.
    
    Args:
        user_id: User ID
        
    Returns:
        List of permission source dictionaries
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            
            cur.callproc('sp_get_user_permission_sources', (user_id,))
            return cur.fetchall()
    
    return handle_db_operation(
        _get,
        error_context=f"get_user_permission_sources(user_id={user_id})"
    )
