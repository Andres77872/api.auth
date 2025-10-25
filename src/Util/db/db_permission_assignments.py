"""
Database functions for Permission Assignment System
Handles user group and direct user assignment of permission groups
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
import hashlib
import pymysql.cursors

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


# =================== USER GROUP PERMISSION GROUP ASSIGNMENTS ===================

def assign_permission_group_to_user_group(user_group_id: str, permission_group_id: str, 
                                         assigned_by: Optional[str] = None):
    """Assign permission group to user group"""
    with get_connection() as con:
        cur = con.cursor()
        link_id = generate_id('ugpg')
        
        try:
            cur.callproc('sp_assign_permission_group_to_user_group', (
                link_id, user_group_id, permission_group_id, assigned_by
            ))
            
            con.commit()
            return True
        except Exception as e:
            logger.error(f"Error assigning permission group to user group: {str(e)}")
            con.rollback()
            return False


def remove_permission_group_from_user_group(user_group_id: str, permission_group_id: str,
                                           removed_by: Optional[str] = None):
    """Remove permission group from user group"""
    with get_connection() as con:
        cur = con.cursor()
        
        try:
            cur.callproc('sp_remove_permission_group_from_user_group', (
                user_group_id, permission_group_id, removed_by
            ))
            
            con.commit()
            return True
        except Exception as e:
            logger.error(f"Error removing permission group from user group: {str(e)}")
            con.rollback()
            return False


def get_user_group_permission_groups(user_group_id: str):
    """Get permission groups assigned to a user group"""
    with get_connection() as con:
        cur = con.cursor(pymysql.cursors.DictCursor)
        
        try:
            cur.callproc('sp_get_user_group_permission_groups', (user_group_id,))
            return cur.fetchall()
        except Exception as e:
            logger.error(f"Error getting user group permission groups: {str(e)}")
            return []


def get_user_groups_with_permission_group(permission_group_id: str):
    """Get user groups that have a specific permission group"""
    with get_connection() as con:
        cur = con.cursor(pymysql.cursors.DictCursor)
        
        try:
            cur.callproc('sp_get_user_groups_with_permission_group', (permission_group_id,))
            return cur.fetchall()
        except Exception as e:
            logger.error(f"Error getting user groups with permission group: {str(e)}")
            return []


# =================== DIRECT USER PERMISSION GROUP ASSIGNMENTS ===================

def assign_permission_group_to_user(user_id: str, permission_group_id: str,
                                   assigned_by: Optional[str] = None, notes: Optional[str] = None):
    """Assign permission group directly to user"""
    with get_connection() as con:
        cur = con.cursor()
        link_id = generate_id('upg')
        
        try:
            cur.callproc('sp_assign_permission_group_to_user', (
                link_id, user_id, permission_group_id, assigned_by, notes
            ))
            
            con.commit()
            return True
        except Exception as e:
            logger.error(f"Error assigning permission group to user: {str(e)}")
            con.rollback()
            return False


def remove_permission_group_from_user(user_id: str, permission_group_id: str,
                                     removed_by: Optional[str] = None):
    """Remove permission group from user"""
    with get_connection() as con:
        cur = con.cursor()
        
        try:
            cur.callproc('sp_remove_permission_group_from_user', (
                user_id, permission_group_id, removed_by
            ))
            
            con.commit()
            return True
        except Exception as e:
            logger.error(f"Error removing permission group from user: {str(e)}")
            con.rollback()
            return False


def get_user_permission_groups(user_id: str):
    """Get permission groups directly assigned to a user"""
    with get_connection() as con:
        cur = con.cursor(pymysql.cursors.DictCursor)
        
        try:
            cur.callproc('sp_get_user_permission_groups', (user_id,))
            return cur.fetchall()
        except Exception as e:
            logger.error(f"Error getting user permission groups: {str(e)}")
            return []


def get_users_with_permission_group(permission_group_id: str):
    """Get users that have a specific permission group directly assigned"""
    with get_connection() as con:
        cur = con.cursor(pymysql.cursors.DictCursor)
        
        try:
            cur.callproc('sp_get_users_with_permission_group', (permission_group_id,))
            return cur.fetchall()
        except Exception as e:
            logger.error(f"Error getting users with permission group: {str(e)}")
            return []


# =================== PERMISSION GROUP PROJECT CATALOG (METADATA ONLY) ===================

def add_permission_group_to_project_catalog(permission_group_id: str, project_id: str,
                                           catalog_purpose: Optional[str] = None,
                                           notes: Optional[str] = None,
                                           added_by: Optional[str] = None):
    """Add permission group to project catalog (METADATA ONLY - NOT used for authorization)"""
    with get_connection() as con:
        cur = con.cursor()
        catalog_id = generate_id('pgpc')
        
        try:
            cur.callproc('sp_add_permission_group_to_project_catalog', (
                catalog_id, permission_group_id, project_id, catalog_purpose, notes, added_by
            ))
            
            con.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding permission group to project catalog: {str(e)}")
            con.rollback()
            return False


def remove_permission_group_from_project_catalog(permission_group_id: str, project_id: str,
                                                 removed_by: Optional[str] = None):
    """Remove permission group from project catalog"""
    with get_connection() as con:
        cur = con.cursor()
        
        try:
            cur.callproc('sp_remove_permission_group_from_project_catalog', (
                permission_group_id, project_id, removed_by
            ))
            
            con.commit()
            return True
        except Exception as e:
            logger.error(f"Error removing permission group from project catalog: {str(e)}")
            con.rollback()
            return False


def get_project_cataloged_permission_groups(project_id: str):
    """Get permission groups cataloged for a project (METADATA - for UI suggestions only)"""
    with get_connection() as con:
        cur = con.cursor(pymysql.cursors.DictCursor)
        
        try:
            cur.callproc('sp_get_project_cataloged_permission_groups', (project_id,))
            return cur.fetchall()
        except Exception as e:
            logger.error(f"Error getting project cataloged permission groups: {str(e)}")
            return []


def get_permission_group_cataloged_projects(permission_group_id: str):
    """Get projects that catalog a specific permission group"""
    with get_connection() as con:
        cur = con.cursor(pymysql.cursors.DictCursor)
        
        try:
            cur.callproc('sp_get_permission_group_cataloged_projects', (permission_group_id,))
            return cur.fetchall()
        except Exception as e:
            logger.error(f"Error getting permission group cataloged projects: {str(e)}")
            return []


# =================== ENHANCED PERMISSION RESOLUTION ===================  

def get_user_all_permissions(user_id: str) -> List[str]:
    """Get all permissions for a user from all sources (GLOBAL - no project context needed)"""
    with get_connection() as con:
        cur = con.cursor(pymysql.cursors.DictCursor)
        
        try:
            cur.callproc('sp_get_user_all_permissions', (user_id,))
            rows = cur.fetchall()
            return [row['permission_name'] for row in rows]
        except Exception as e:
            logger.error(f"Error getting user all permissions: {str(e)}")
            return []


def check_user_has_permission_extended(user_id: str, permission_name: str) -> bool:
    """Check if user has permission from all sources (GLOBAL - no project context needed)"""
    with get_connection() as con:
        cur = con.cursor(pymysql.cursors.DictCursor)
        
        try:
            cur.callproc('sp_check_user_has_permission', (user_id, permission_name))
            row = cur.fetchone()
            return row['has_permission'] == 1 if row else False
        except Exception as e:
            logger.error(f"Error checking user permission: {str(e)}")
            return False


def get_user_permission_sources(user_id: str):
    """Get detailed permission sources for a user"""
    with get_connection() as con:
        cur = con.cursor(pymysql.cursors.DictCursor)
        
        try:
            cur.callproc('sp_get_user_permission_sources', (user_id,))
            return cur.fetchall()
        except Exception as e:
            logger.error(f"Error getting user permission sources: {str(e)}")
            return []
