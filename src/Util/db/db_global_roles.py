"""
Database functions for Global Role System
Uses stored procedures for all database operations
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


# =================== ROLE MANAGEMENT ===================

def create_role(role_name: str, role_display_name: str, role_description: Optional[str] = None,
                role_priority: int = 50, created_by: Optional[str] = None, is_system_role: bool = False):
    """Create a new global role using stored procedure"""
    def _create():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            role_id = generate_id('role')
            role_hash = generate_hash('role', role_name)
            
            cur.callproc('sp_global_create_role', (
                role_id, role_hash, role_name, role_display_name, role_description,
                role_priority, is_system_role, created_by
            ))
            
            result = cur.fetchone()
            con.commit()
            return result
    
    return handle_db_operation(
        _create,
        error_context=f"create_role(role_name='{role_name}')",
        not_found_message=f"Failed to create role '{role_name}'"
    )


def get_role_by_hash(role_hash: str):
    """Get role by hash using stored procedure"""
    def _get():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            cur.callproc('sp_global_get_role_by_hash', (role_hash,))
            return cur.fetchone()
    
    return handle_db_operation(
        _get,
        error_context=f"get_role_by_hash(role_hash='{role_hash}')"
    )


def list_roles(limit: int = 50, offset: int = 0):
    """List all roles using stored procedure"""
    def _list():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            cur.callproc('sp_global_list_roles', (limit, offset))
            return cur.fetchall()
    
    return handle_db_operation(
        _list,
        error_context=f"list_roles(limit={limit}, offset={offset})"
    )


def update_role(role_id: str, **kwargs):
    """Update role details using stored procedure"""
    def _update():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            
            # Extract expected parameters
            role_display_name = kwargs.get('role_display_name')
            role_description = kwargs.get('role_description')
            role_priority = kwargs.get('role_priority')
            
            cur.callproc('sp_global_update_role', (
                role_id, role_display_name, role_description, role_priority
            ))
            
            con.commit()
            return True
    
    return handle_db_operation(
        _update,
        error_context=f"update_role(role_id='{role_id}')"
    )


def delete_role(role_id: str):
    """Soft delete a role using stored procedure"""
    def _delete():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_global_delete_role', (role_id,))
            con.commit()
            return True
    
    return handle_db_operation(
        _delete,
        error_context=f"delete_role(role_id='{role_id}')"
    )


# =================== PERMISSION GROUP MANAGEMENT ===================

def create_permission_group(group_name: str, group_display_name: str, group_description: Optional[str] = None,
                           group_category: str = 'general', created_by: Optional[str] = None):
    """Create a new permission group using stored procedure"""
    def _create():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            group_id = generate_id('pg')
            group_hash = generate_hash('pg', group_name)
            
            cur.callproc('sp_global_create_permission_group', (
                group_id, group_hash, group_name, group_display_name,
                group_description, group_category, created_by
            ))
            
            result = cur.fetchone()
            con.commit()
            return result
    
    return handle_db_operation(
        _create,
        error_context=f"create_permission_group(group_name='{group_name}')",
        not_found_message=f"Failed to create permission group '{group_name}'"
    )


def get_permission_group_by_hash(group_hash: str):
    """Get permission group by hash using stored procedure"""
    def _get():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            cur.callproc('sp_global_get_permission_group_by_hash', (group_hash,))
            return cur.fetchone()
    
    return handle_db_operation(
        _get,
        error_context=f"get_permission_group_by_hash(group_hash='{group_hash}')"
    )


def list_permission_groups(category: Optional[str] = None, limit: int = 50, offset: int = 0):
    """List permission groups using stored procedure"""
    def _list():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            cur.callproc('sp_global_list_permission_groups', (category, limit, offset))
            return cur.fetchall()
    
    return handle_db_operation(
        _list,
        error_context=f"list_permission_groups(category='{category}')"
    )


def update_permission_group(group_id: str, group_display_name: Optional[str] = None,
                           group_description: Optional[str] = None, group_category: Optional[str] = None):
    """Update permission group details"""
    def _update():
        if group_display_name is None and group_description is None and group_category is None:
            return True

        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            cur.callproc('sp_global_update_permission_group', (
                group_id, group_display_name, group_description, group_category
            ))
            result = cur.fetchone()
            while cur.nextset():
                pass
            con.commit()
            return bool(result and result.get('rows_affected', 0) > 0)
    
    return handle_db_operation(
        _update,
        error_context=f"update_permission_group(group_id='{group_id}')"
    )


def delete_permission_group(group_id: str) -> bool:
    """Soft delete a permission group"""
    def _delete():
        with get_connection() as con:
            cur = con.cursor()
            # Soft delete - set is_active = 0
            cur.execute(
                "UPDATE global_permission_groups SET is_active = 0, updated_at = NOW() WHERE id = %s",
                (group_id,)
            )
            con.commit()
            return cur.rowcount > 0
    
    return handle_db_operation(
        _delete,
        error_context=f"delete_permission_group(group_id='{group_id}')"
    )


# =================== PERMISSION MANAGEMENT ===================

def create_permission(permission_name: str, permission_display_name: str, permission_description: Optional[str] = None,
                     permission_category: str = 'general', created_by: Optional[str] = None):
    """Create a new global permission using stored procedure"""
    def _create():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            perm_id = generate_id('perm')
            perm_hash = generate_hash('perm', permission_name)
            
            cur.callproc('sp_global_create_permission', (
                perm_id, perm_hash, permission_name, permission_display_name,
                permission_description, permission_category, created_by
            ))
            
            result = cur.fetchone()
            con.commit()
            return result
    
    return handle_db_operation(
        _create,
        error_context=f"create_permission(permission_name='{permission_name}')",
        not_found_message=f"Failed to create permission '{permission_name}'"
    )


def get_permission_by_hash(permission_hash: str):
    """Get permission by hash using stored procedure"""
    def _get():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            cur.callproc('sp_global_get_permission_by_hash', (permission_hash,))
            return cur.fetchone()
    
    return handle_db_operation(
        _get,
        error_context=f"get_permission_by_hash(permission_hash='{permission_hash}')"
    )


def list_permissions(category: Optional[str] = None, limit: int = 50, offset: int = 0):
    """List permissions using stored procedure"""
    def _list():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            cur.callproc('sp_global_list_permissions', (category, limit, offset))
            return cur.fetchall()
    
    return handle_db_operation(
        _list,
        error_context=f"list_permissions(category='{category}')"
    )


def update_permission(permission_id: str, permission_display_name: Optional[str] = None,
                     permission_description: Optional[str] = None, permission_category: Optional[str] = None):
    """Update permission details"""
    def _update():
        if permission_display_name is None and permission_description is None and permission_category is None:
            return True

        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            cur.callproc('sp_global_update_permission', (
                permission_id, permission_display_name, permission_description, permission_category
            ))
            result = cur.fetchone()
            while cur.nextset():
                pass
            con.commit()
            return bool(result and result.get('rows_affected', 0) > 0)
    
    return handle_db_operation(
        _update,
        error_context=f"update_permission(permission_id='{permission_id}')"
    )


def delete_permission(permission_id: str) -> bool:
    """Soft delete a permission"""
    def _delete():
        with get_connection() as con:
            cur = con.cursor()
            # Soft delete - set is_active = 0
            cur.execute(
                "UPDATE global_permissions SET is_active = 0, updated_at = NOW() WHERE id = %s",
                (permission_id,)
            )
            con.commit()
            return cur.rowcount > 0
    
    return handle_db_operation(
        _delete,
        error_context=f"delete_permission(permission_id='{permission_id}')"
    )


# =================== RELATIONSHIPS ===================

def assign_permission_group_to_role(role_id: str, permission_group_id: str, assigned_by: Optional[str] = None):
    """Assign permission group to role using stored procedure"""
    def _assign():
        with get_connection() as con:
            cur = con.cursor()
            link_id = generate_id('rpg')
            
            cur.callproc('sp_global_assign_permission_group_to_role', (
                link_id, role_id, permission_group_id, assigned_by
            ))
            
            con.commit()
            return True
    
    return handle_db_operation(
        _assign,
        error_context=f"assign_permission_group_to_role(role_id='{role_id}', group_id='{permission_group_id}')"
    )


def get_role_permission_groups(role_id: str):
    """Get permission groups for a role using stored procedure"""
    def _get():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            cur.callproc('sp_global_get_role_permission_groups', (role_id,))
            return cur.fetchall()
    
    return handle_db_operation(
        _get,
        error_context=f"get_role_permission_groups(role_id='{role_id}')"
    )


def assign_permission_to_group(permission_group_id: str, permission_id: str, granted_by: Optional[str] = None):
    """Assign permission to group using stored procedure"""
    def _assign():
        with get_connection() as con:
            cur = con.cursor()
            link_id = generate_id('pgp')
            
            cur.callproc('sp_global_assign_permission_to_group', (
                link_id, permission_group_id, permission_id, granted_by
            ))
            
            con.commit()
            return True
    
    return handle_db_operation(
        _assign,
        error_context=f"assign_permission_to_group(group_id='{permission_group_id}', permission_id='{permission_id}')"
    )


def get_permission_group_permissions(permission_group_id: str):
    """Get permissions in a permission group using stored procedure"""
    def _get():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            cur.callproc('sp_global_get_permission_group_permissions', (permission_group_id,))
            return cur.fetchall()
    
    return handle_db_operation(
        _get,
        error_context=f"get_permission_group_permissions(group_id='{permission_group_id}')"
    )


def remove_permission_from_group(permission_group_id: str, permission_id: str) -> bool:
    """Remove a permission from a permission group"""
    def _remove():
        with get_connection() as con:
            cur = con.cursor()
            # Soft delete - set is_active = 0 instead of hard delete
            cur.execute(
                "UPDATE global_permission_group_permissions SET is_active = 0, removed_at = NOW() WHERE permission_group_id = %s AND permission_id = %s AND is_active = 1",
                (permission_group_id, permission_id)
            )
            con.commit()
            return cur.rowcount > 0
    
    return handle_db_operation(
        _remove,
        error_context=f"remove_permission_from_group(group_id='{permission_group_id}', permission_id='{permission_id}')"
    )


def remove_permission_group_from_role(role_id: str, permission_group_id: str) -> bool:
    """Remove a permission group from a role"""
    def _remove():
        with get_connection() as con:
            cur = con.cursor()
            # Soft delete - set is_active = 0 instead of hard delete
            cur.execute(
                "UPDATE role_permission_groups SET is_active = 0, removed_at = NOW() WHERE role_id = %s AND permission_group_id = %s AND is_active = 1",
                (role_id, permission_group_id)
            )
            con.commit()
            return cur.rowcount > 0
    
    return handle_db_operation(
        _remove,
        error_context=f"remove_permission_group_from_role(role_id='{role_id}', permission_group_id='{permission_group_id}')"
    )


def remove_role_from_user(user_id: str) -> bool:
    """Remove role from a user (unassign their role)"""
    def _remove():
        with get_connection() as con:
            cur = con.cursor()
            cur.execute(
                "UPDATE users SET role_id = NULL WHERE id = %s",
                (user_id,)
            )
            con.commit()
            return cur.rowcount > 0
    
    return handle_db_operation(
        _remove,
        error_context=f"remove_role_from_user(user_id='{user_id}')"
    )


# =================== USER ROLE ASSIGNMENT ===================

def assign_role_to_user(user_id: str, role_id: str):
    """Assign role to user using stored procedure"""
    def _assign():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_global_assign_role_to_user', (user_id, role_id))
            con.commit()
            return True
    
    return handle_db_operation(
        _assign,
        error_context=f"assign_role_to_user(user_id='{user_id}', role_id='{role_id}')"
    )


def get_user_role(user_id: str):
    """Get user's role using stored procedure"""
    def _get():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            cur.callproc('sp_global_get_user_role', (user_id,))
            return cur.fetchone()
    
    return handle_db_operation(
        _get,
        error_context=f"get_user_role(user_id='{user_id}')"
    )


# =================== PERMISSION RESOLUTION (GLOBAL, PROJECT-AGNOSTIC) ===================

def get_user_permissions(user_id: str) -> List[str]:
    """Get all permissions for a user using stored procedure (GLOBAL - no project context needed)"""
    def _get():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            cur.callproc('sp_global_get_user_permissions', (user_id,))
            rows = cur.fetchall()
            return [row['permission_name'] for row in rows]
    
    result = handle_db_operation(
        _get,
        error_context=f"get_user_permissions(user_id='{user_id}')"
    )
    return result if result else []


def check_user_has_permission(user_id: str, permission_name: str) -> bool:
    """Check if user has permission using stored procedure (GLOBAL - no project context needed)"""
    def _check():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            cur.callproc('sp_global_check_user_has_permission', (user_id, permission_name))
            row = cur.fetchone()
            return row['has_permission'] == 1 if row else False
    
    try:
        return handle_db_operation(
            _check,
            error_context=f"check_user_has_permission(user_id='{user_id}', permission='{permission_name}')"
        )
    except Exception as e:
        logger.error(f"Error checking permission, defaulting to False: {str(e)}")
        return False


# =================== CATALOG FUNCTIONS (METADATA ONLY - NOT FOR AUTHORIZATION) ===================

def add_role_to_project_catalog(role_id: str, project_id: str, catalog_purpose: Optional[str] = None,
                                notes: Optional[str] = None, added_by: Optional[str] = None):
    """Add role to project catalog using stored procedure (METADATA ONLY - NOT used for permission checks)"""
    def _add():
        with get_connection() as con:
            cur = con.cursor()
            catalog_id = generate_id('rpc')
            
            cur.callproc('sp_global_add_role_to_project_catalog', (
                catalog_id, role_id, project_id, catalog_purpose, notes, added_by
            ))
            
            con.commit()
            return True
    
    return handle_db_operation(
        _add,
        error_context=f"add_role_to_project_catalog(role_id='{role_id}', project_id='{project_id}')"
    )


def get_project_cataloged_roles(project_id: str):
    """Get roles cataloged for a project using stored procedure (METADATA - for UI suggestions only)"""
    def _get():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            cur.callproc('sp_global_get_project_cataloged_roles', (project_id,))
            return cur.fetchall()
    
    result = handle_db_operation(
        _get,
        error_context=f"get_project_cataloged_roles(project_id='{project_id}')"
    )
    return result if result else []


def remove_role_from_project_catalog(role_id: str, project_id: str, removed_by: Optional[str] = None) -> bool:
    """Remove role from project catalog using stored procedure (METADATA ONLY - NOT used for permission checks)"""
    def _remove():
        with get_connection() as con:
            cur = con.cursor(pymysql.cursors.DictCursor)
            
            cur.callproc('sp_global_remove_role_from_project_catalog', (
                role_id, project_id, removed_by
            ))
            
            result = cur.fetchone()
            con.commit()
            return result and result.get('rows_affected', 0) > 0
    
    return handle_db_operation(
        _remove,
        error_context=f"remove_role_from_project_catalog(role_id='{role_id}', project_id='{project_id}')"
    )
