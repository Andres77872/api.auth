"""
Database functions for Global Role System
Uses stored procedures for all database operations
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
import hashlib

from src.Util.db_config import get_connection

logger = logging.getLogger(__name__)


def generate_hash(prefix: str, value: str) -> str:
    """Generate a unique hash"""
    timestamp = datetime.utcnow().isoformat()
    hash_input = f"{prefix}:{value}:{timestamp}"
    return hashlib.sha256(hash_input.encode()).hexdigest()[:32]


def generate_id(prefix: str) -> str:
    """Generate a unique ID"""
    timestamp = datetime.utcnow().timestamp()
    hash_input = f"{prefix}:{timestamp}"
    return f"{prefix}_{hashlib.sha256(hash_input.encode()).hexdigest()[:16]}"


# =================== ROLE MANAGEMENT ===================

def create_role(role_name: str, role_display_name: str, role_description: Optional[str] = None,
                role_priority: int = 50, created_by: Optional[str] = None, is_system_role: bool = False):
    """Create a new global role using stored procedure"""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        role_id = generate_id('role')
        role_hash = generate_hash('role', role_name)
        
        cursor.callproc('sp_global_create_role', (
            role_id, role_hash, role_name, role_display_name, role_description,
            role_priority, is_system_role, created_by
        ))
        
        # Fetch result
        for result in cursor.stored_results():
            return result.fetchone()
        
        connection.commit()
        return None
    except Exception as e:
        logger.error(f"Error creating role: {str(e)}")
        connection.rollback()
        return None
    finally:
        cursor.close()
        connection.close()


def get_role_by_hash(role_hash: str):
    """Get role by hash using stored procedure"""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        
        cursor.callproc('sp_global_get_role_by_hash', (role_hash,))
        
        for result in cursor.stored_results():
            return result.fetchone()
        return None
    except Exception as e:
        logger.error(f"Error getting role: {str(e)}")
        return None
    finally:
        cursor.close()
        connection.close()


def list_roles(limit: int = 50, offset: int = 0):
    """List all roles using stored procedure"""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        
        cursor.callproc('sp_global_list_roles', (limit, offset))
        
        for result in cursor.stored_results():
            return result.fetchall()
        return []
    except Exception as e:
        logger.error(f"Error listing roles: {str(e)}")
        return []
    finally:
        cursor.close()
        connection.close()


def update_role(role_id: str, **kwargs):
    """Update role details using stored procedure"""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Extract expected parameters
        role_display_name = kwargs.get('role_display_name')
        role_description = kwargs.get('role_description')
        role_priority = kwargs.get('role_priority')
        
        cursor.callproc('sp_global_update_role', (
            role_id, role_display_name, role_description, role_priority
        ))
        
        connection.commit()
        return True
    except Exception as e:
        logger.error(f"Error updating role: {str(e)}")
        connection.rollback()
        return False
    finally:
        cursor.close()
        connection.close()


def delete_role(role_id: str):
    """Soft delete a role using stored procedure"""
    try:
        connection = get_connection()
        cursor = connection.cursor()
        
        cursor.callproc('sp_global_delete_role', (role_id,))
        
        connection.commit()
        return True
    except Exception as e:
        logger.error(f"Error deleting role: {str(e)}")
        connection.rollback()
        return False
    finally:
        cursor.close()
        connection.close()


# =================== PERMISSION GROUP MANAGEMENT ===================

def create_permission_group(group_name: str, group_display_name: str, group_description: Optional[str] = None,
                           group_category: str = 'general', created_by: Optional[str] = None):
    """Create a new permission group using stored procedure"""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        group_id = generate_id('pg')
        group_hash = generate_hash('pg', group_name)
        
        cursor.callproc('sp_global_create_permission_group', (
            group_id, group_hash, group_name, group_display_name,
            group_description, group_category, created_by
        ))
        
        for result in cursor.stored_results():
            return result.fetchone()
        
        connection.commit()
        return None
    except Exception as e:
        logger.error(f"Error creating permission group: {str(e)}")
        connection.rollback()
        return None
    finally:
        cursor.close()
        connection.close()


def get_permission_group_by_hash(group_hash: str):
    """Get permission group by hash using stored procedure"""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        
        cursor.callproc('sp_global_get_permission_group_by_hash', (group_hash,))
        
        for result in cursor.stored_results():
            return result.fetchone()
        return None
    except Exception as e:
        logger.error(f"Error getting permission group: {str(e)}")
        return None
    finally:
        cursor.close()
        connection.close()


def list_permission_groups(category: Optional[str] = None, limit: int = 50, offset: int = 0):
    """List permission groups using stored procedure"""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        
        cursor.callproc('sp_global_list_permission_groups', (category, limit, offset))
        
        for result in cursor.stored_results():
            return result.fetchall()
        return []
    except Exception as e:
        logger.error(f"Error listing permission groups: {str(e)}")
        return []
    finally:
        cursor.close()
        connection.close()


# =================== PERMISSION MANAGEMENT ===================

def create_permission(permission_name: str, permission_display_name: str, permission_description: Optional[str] = None,
                     permission_category: str = 'general', created_by: Optional[str] = None):
    """Create a new global permission using stored procedure"""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        perm_id = generate_id('perm')
        perm_hash = generate_hash('perm', permission_name)
        
        cursor.callproc('sp_global_create_permission', (
            perm_id, perm_hash, permission_name, permission_display_name,
            permission_description, permission_category, created_by
        ))
        
        for result in cursor.stored_results():
            return result.fetchone()
        
        connection.commit()
        return None
    except Exception as e:
        logger.error(f"Error creating permission: {str(e)}")
        connection.rollback()
        return None
    finally:
        cursor.close()
        connection.close()


def get_permission_by_hash(permission_hash: str):
    """Get permission by hash using stored procedure"""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        
        cursor.callproc('sp_global_get_permission_by_hash', (permission_hash,))
        
        for result in cursor.stored_results():
            return result.fetchone()
        return None
    except Exception as e:
        logger.error(f"Error getting permission: {str(e)}")
        return None
    finally:
        cursor.close()
        connection.close()


def list_permissions(category: Optional[str] = None, limit: int = 50, offset: int = 0):
    """List permissions using stored procedure"""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        
        cursor.callproc('sp_global_list_permissions', (category, limit, offset))
        
        for result in cursor.stored_results():
            return result.fetchall()
        return []
    except Exception as e:
        logger.error(f"Error listing permissions: {str(e)}")
        return []
    finally:
        cursor.close()
        connection.close()


# =================== RELATIONSHIPS ===================

def assign_permission_group_to_role(role_id: str, permission_group_id: str, assigned_by: Optional[str] = None):
    """Assign permission group to role using stored procedure"""
    try:
        connection = get_connection()
        cursor = connection.cursor()
        link_id = generate_id('rpg')
        
        cursor.callproc('sp_global_assign_permission_group_to_role', (
            link_id, role_id, permission_group_id, assigned_by
        ))
        
        connection.commit()
        return True
    except Exception as e:
        logger.error(f"Error assigning permission group to role: {str(e)}")
        connection.rollback()
        return False
    finally:
        cursor.close()
        connection.close()


def get_role_permission_groups(role_id: str):
    """Get permission groups for a role using stored procedure"""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        
        cursor.callproc('sp_global_get_role_permission_groups', (role_id,))
        
        for result in cursor.stored_results():
            return result.fetchall()
        return []
    except Exception as e:
        logger.error(f"Error getting role permission groups: {str(e)}")
        return []
    finally:
        cursor.close()
        connection.close()


def assign_permission_to_group(permission_group_id: str, permission_id: str, granted_by: Optional[str] = None):
    """Assign permission to group using stored procedure"""
    try:
        connection = get_connection()
        cursor = connection.cursor()
        link_id = generate_id('pgp')
        
        cursor.callproc('sp_global_assign_permission_to_group', (
            link_id, permission_group_id, permission_id, granted_by
        ))
        
        connection.commit()
        return True
    except Exception as e:
        logger.error(f"Error assigning permission to group: {str(e)}")
        connection.rollback()
        return False
    finally:
        cursor.close()
        connection.close()


def get_permission_group_permissions(permission_group_id: str):
    """Get permissions in a permission group using stored procedure"""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        
        cursor.callproc('sp_global_get_permission_group_permissions', (permission_group_id,))
        
        for result in cursor.stored_results():
            return result.fetchall()
        return []
    except Exception as e:
        logger.error(f"Error getting permission group permissions: {str(e)}")
        return []
    finally:
        cursor.close()
        connection.close()


# =================== USER ROLE ASSIGNMENT ===================

def assign_role_to_user(user_id: str, role_id: str):
    """Assign role to user using stored procedure"""
    try:
        connection = get_connection()
        cursor = connection.cursor()
        
        cursor.callproc('sp_global_assign_role_to_user', (user_id, role_id))
        
        connection.commit()
        return True
    except Exception as e:
        logger.error(f"Error assigning role to user: {str(e)}")
        connection.rollback()
        return False
    finally:
        cursor.close()
        connection.close()


def get_user_role(user_id: str):
    """Get user's role using stored procedure"""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        
        cursor.callproc('sp_global_get_user_role', (user_id,))
        
        for result in cursor.stored_results():
            return result.fetchone()
        return None
    except Exception as e:
        logger.error(f"Error getting user role: {str(e)}")
        return None
    finally:
        cursor.close()
        connection.close()


# =================== PERMISSION RESOLUTION (GLOBAL, PROJECT-AGNOSTIC) ===================

def get_user_permissions(user_id: str) -> List[str]:
    """Get all permissions for a user using stored procedure (GLOBAL - no project context needed)"""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        
        cursor.callproc('sp_global_get_user_permissions', (user_id,))
        
        for result in cursor.stored_results():
            rows = result.fetchall()
            return [row['permission_name'] for row in rows]
        return []
    except Exception as e:
        logger.error(f"Error getting user permissions: {str(e)}")
        return []
    finally:
        cursor.close()
        connection.close()


def check_user_has_permission(user_id: str, permission_name: str) -> bool:
    """Check if user has permission using stored procedure (GLOBAL - no project context needed)"""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        
        cursor.callproc('sp_global_check_user_has_permission', (user_id, permission_name))
        
        for result in cursor.stored_results():
            row = result.fetchone()
            return row['has_permission'] == 1 if row else False
        return False
    except Exception as e:
        logger.error(f"Error checking user permission: {str(e)}")
        return False
    finally:
        cursor.close()
        connection.close()


# =================== CATALOG FUNCTIONS (METADATA ONLY - NOT FOR AUTHORIZATION) ===================

def add_role_to_project_catalog(role_id: str, project_id: str, catalog_purpose: Optional[str] = None,
                                notes: Optional[str] = None, added_by: Optional[str] = None):
    """Add role to project catalog using stored procedure (METADATA ONLY - NOT used for permission checks)"""
    try:
        connection = get_connection()
        cursor = connection.cursor()
        catalog_id = generate_id('rpc')
        
        cursor.callproc('sp_global_add_role_to_project_catalog', (
            catalog_id, role_id, project_id, catalog_purpose, notes, added_by
        ))
        
        connection.commit()
        return True
    except Exception as e:
        logger.error(f"Error adding role to project catalog: {str(e)}")
        connection.rollback()
        return False
    finally:
        cursor.close()
        connection.close()


def get_project_cataloged_roles(project_id: str):
    """Get roles cataloged for a project using stored procedure (METADATA - for UI suggestions only)"""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        
        cursor.callproc('sp_global_get_project_cataloged_roles', (project_id,))
        
        for result in cursor.stored_results():
            return result.fetchall()
        return []
    except Exception as e:
        logger.error(f"Error getting project cataloged roles: {str(e)}")
        return []
    finally:
        cursor.close()
        connection.close()
