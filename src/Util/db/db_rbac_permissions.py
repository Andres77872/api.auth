"""
RBAC (Role-Based Access Control) Permissions Module

This module implements proper RBAC architecture with:
- Project-specific permissions catalog
- Project-specific permission groups (roles)
- User role assignments per project
- Audit trail for all permission changes
- Cached permission checks for performance

Key RBAC Principles Enforced:
- Each project has its own permission catalog
- Permission groups are project-specific
- Cannot assign permissions outside project scope
- Complete audit trail
- Cache-first permission checking with automatic invalidation
"""

import json
import secrets
from datetime import datetime
from typing import List

import pymysql

from src.Util.Models import (
    Permission, PermissionGroup
)
from src.Util.cache_manager import cache_manager
from src.Util.db_config import get_connection


# =================== PERMISSION MANAGEMENT ===================

def create_permission(
        project_id: str,
        permission_name: str,
        permission_display_name: str = None,
        permission_description: str = None,
        permission_category: str = 'general',
        category: str = None,  # Compatibility parameter
        is_system_permission: bool = False,
        created_by: str = None
) -> Permission:
    """Create a new project-specific permission using stored procedure"""
    # Handle compatibility parameters
    if category:
        permission_category = category
    if not permission_display_name:
        permission_display_name = permission_name.replace('_', ' ').title()

    permission_id = secrets.token_hex(32)
    permission_hash = secrets.token_hex(32).upper()

    with get_connection() as con:
        cur = con.cursor()
        cur.callproc('sp_rbac_create_permission', [
            permission_id, permission_hash, project_id, permission_name,
            permission_display_name, permission_description,
            permission_category, is_system_permission, created_by
        ])
        
        # Fetch result
        row = cur.fetchone()
        result = None
        if row:
            result = Permission(
                id=row[0], permission_hash=row[1], project_id=row[2],
                permission_name=row[3], permission_display_name=row[4],
                permission_description=row[5], permission_category=row[6],
                is_system_permission=bool(row[7]), created_at=row[8],
                updated_at=row[9], created_by=row[10], is_active=bool(row[11])
            )
        
        while cur.nextset():
            pass
        
        con.commit()

        # Invalidate RBAC cache for this project
        cache_manager.invalidate_rbac_cache(project_id)

        return result


def get_project_permissions(project_id: str, category: str = None) -> List[Permission]:
    """Get all permissions for a project using stored procedure"""
    with get_connection() as con:
        cur = con.cursor()
        cur.callproc('sp_rbac_get_project_permissions', [project_id, category])

        permissions = []
        for row in cur.fetchall():
            permissions.append(Permission(
                id=row[0], permission_hash=row[1], project_id=row[2],
                permission_name=row[3], permission_display_name=row[4],
                permission_description=row[5], permission_category=row[6],
                is_system_permission=bool(row[7]), created_at=row[8],
                updated_at=row[9], created_by=row[10], is_active=bool(row[11])
            ))
        
        while cur.nextset():
            pass

        return permissions


def check_user_permission(user_id: str, project_id: str, permission_name: str) -> bool:
    """Check if user has a specific permission within a project (cache-first) using stored procedure"""
    # Try cache first
    cached_result = cache_manager.get_permission_check(user_id, project_id, permission_name)
    if cached_result is not None:
        return cached_result

    # If not in cache, check database using stored procedure
    with get_connection() as con:
        cur = con.cursor()
        cur.callproc('sp_rbac_check_user_permission', [user_id, project_id, permission_name])

        row = cur.fetchone()
        has_permission = bool(row[0]) if row else False
        
        while cur.nextset():
            pass

        # Cache the result
        cache_manager.set_permission_check(user_id, project_id, permission_name, has_permission)

        return has_permission


def create_default_project_permissions(project_id: str, created_by: str = None) -> List[Permission]:
    """Create default system permissions for a new project"""
    default_permissions = [
        # General permissions
        ('read', 'Read Access', 'Can view content and data', 'general'),
        ('write', 'Write Access', 'Can create and modify content', 'general'),
        ('delete', 'Delete Access', 'Can delete content and data', 'general'),
        ('create', 'Create Access', 'Can create new items', 'general'),
        ('update', 'Update Access', 'Can modify existing items', 'general'),

        # Admin permissions
        ('admin', 'Administrator', 'Full administrative access', 'admin'),
        ('manage_users', 'Manage Users', 'Can manage user accounts and roles', 'admin'),
        ('manage_roles', 'Manage Roles', 'Can create and modify roles and permissions', 'admin'),
        ('view_audit', 'View Audit Log', 'Can view audit trail and logs', 'admin'),

        # Data permissions
        ('export_data', 'Export Data', 'Can export data from the system', 'data'),
        ('import_data', 'Import Data', 'Can import data into the system', 'data'),

        # API permissions
        ('api_access', 'API Access', 'Can access API endpoints', 'api'),
        ('full_access', 'Full Access', 'Complete access to all features', 'admin')
    ]

    created_permissions = []
    for perm_name, display_name, description, category in default_permissions:
        try:
            permission = create_permission(
                project_id=project_id,
                permission_name=perm_name,
                permission_display_name=display_name,
                permission_description=description,
                permission_category=category,
                is_system_permission=True,
                created_by=created_by
            )
            created_permissions.append(permission)
        except pymysql.IntegrityError:
            # Permission already exists, skip
            continue

    return created_permissions


# =================== PERMISSION GROUP (ROLE) MANAGEMENT ===================

def create_permission_group(
        project_id: str,
        group_name: str,
        group_display_name: str = None,
        group_description: str = None,
        group_priority: int = 0,
        priority: int = None,  # Compatibility parameter
        description: str = None,  # Compatibility parameter
        is_system_role: bool = False,
        created_by: str = None
) -> PermissionGroup:
    """Create a new project-specific permission group (role) using stored procedure"""
    # Handle compatibility parameters
    if priority is not None:
        group_priority = priority
    if description:
        group_description = description
    if not group_display_name:
        group_display_name = group_name.replace('_', ' ').title()

    group_id = secrets.token_hex(32)
    group_hash = secrets.token_hex(32).upper()

    with get_connection() as con:
        cur = con.cursor()
        cur.callproc('sp_rbac_create_permission_group', [
            group_id, group_hash, project_id, group_name,
            group_display_name, group_description,
            group_priority, is_system_role, created_by
        ])

        row = cur.fetchone()
        result = None
        if row:
            result = PermissionGroup(
                id=row[0], group_hash=row[1], project_id=row[2],
                group_name=row[3], group_display_name=row[4],
                group_description=row[5], group_priority=row[6],
                is_system_role=bool(row[7]), created_at=row[8],
                updated_at=row[9], created_by=row[10], is_active=bool(row[11])
            )
        
        while cur.nextset():
            pass

        con.commit()

        # Invalidate RBAC cache for this project when new role is created
        cache_manager.invalidate_rbac_cache(project_id)

        return result


def assign_user_to_permission_group(
        user_id: str,
        project_id: str,
        permission_group_id: str,
        assigned_by: str = None
) -> bool:
    """Assign a user to a permission group within a project through user groups using stored procedure"""
    assignment_id = secrets.token_hex(32)
    
    with get_connection() as con:
        cur = con.cursor()
        # Call stored procedure with OUT parameters
        args = [assignment_id, user_id, project_id, permission_group_id, assigned_by, 0, '']
        cur.callproc('sp_rbac_assign_user_to_permission_group', args)
        
        # Get OUT parameters
        cur.execute('SELECT @_sp_rbac_assign_user_to_permission_group_5, @_sp_rbac_assign_user_to_permission_group_6')
        result = cur.fetchone()
        success = bool(result[0]) if result else False
        error_message = result[1] if result and result[1] else None
        
        if not success:
            raise ValueError(error_message or "Failed to assign user to permission group")
        
        con.commit()

        # Invalidate user cache and RBAC cache for this project
        cache_manager.invalidate_user_cache(user_id)
        cache_manager.invalidate_rbac_cache(project_id)

        return success


def remove_user_from_permission_group(
        user_id: str,
        project_id: str,
        permission_group_id: str,
        removed_by: str = None
) -> bool:
    """Remove a user from a permission group within a project through user groups using stored procedure"""
    with get_connection() as con:
        cur = con.cursor()
        
        # Call stored procedure with OUT parameter
        args = [user_id, project_id, permission_group_id, removed_by, 0]
        cur.callproc('sp_rbac_remove_user_from_permission_group', args)
        
        # Get OUT parameter
        cur.execute('SELECT @_sp_rbac_remove_user_from_permission_group_4')
        result = cur.fetchone()
        rows_affected = result[0] if result else 0
        
        success = rows_affected > 0
        
        if success:
            con.commit()

            # Invalidate user cache and RBAC cache for this project
            cache_manager.invalidate_user_cache(user_id)
            cache_manager.invalidate_rbac_cache(project_id)

        return success


def get_project_permission_groups(project_id: str) -> List[PermissionGroup]:
    """Get all permission groups (roles) for a project using stored procedure"""
    with get_connection() as con:
        cur = con.cursor()
        cur.callproc('sp_rbac_get_project_permission_groups', [project_id])

        groups = []
        for row in cur.fetchall():
            groups.append(PermissionGroup(
                id=row[0], group_hash=row[1], project_id=row[2],
                group_name=row[3], group_display_name=row[4],
                group_description=row[5], group_priority=row[6],
                is_system_role=bool(row[7]), created_at=row[8],
                updated_at=row[9], created_by=row[10], is_active=bool(row[11])
            ))
        
        while cur.nextset():
            pass

        return groups


def assign_permission_to_group(permission_group_id: str, permission_id: str, assigned_by: str = None) -> bool:
    """Assign a permission to a permission group using stored procedure"""
    link_id = secrets.token_hex(32)
    
    with get_connection() as con:
        cur = con.cursor()
        
        # Call stored procedure with OUT parameter
        args = [link_id, permission_group_id, permission_id, assigned_by, 0]
        cur.callproc('sp_rbac_assign_permission_to_group', args)
        
        # Get OUT parameter
        cur.execute('SELECT @_sp_rbac_assign_permission_to_group_4')
        result = cur.fetchone()
        success = bool(result[0]) if result else False
        
        if not success:
            raise ValueError("Permission and permission group must belong to the same project")
        
        con.commit()

        # Get project_id for cache invalidation
        cur.execute('SELECT project_id FROM permission_groups WHERE id = %s', [permission_group_id])
        pg_result = cur.fetchone()
        if pg_result:
            cache_manager.invalidate_rbac_cache(pg_result[0])

        return success


def get_user_permission_groups_in_project(user_id: str, project_id: str) -> List[PermissionGroup]:
    """Get all permission groups assigned to a user in a specific project using stored procedure"""
    with get_connection() as con:
        cur = con.cursor()
        cur.callproc('sp_rbac_get_user_permission_groups_in_project', [user_id, project_id])

        groups = []
        for row in cur.fetchall():
            group = PermissionGroup(
                id=row[0], group_hash=row[1], project_id=row[2],
                group_name=row[3], group_display_name=row[4],
                group_description=row[5], group_priority=row[6],
                is_system_role=bool(row[7]), created_at=row[8],
                updated_at=row[9], created_by=row[10], is_active=bool(row[11])
            )
            # Add assignment date for audit purposes
            group.assigned_at = row[12]
            groups.append(group)
        
        while cur.nextset():
            pass

        return groups


def get_user_effective_permissions(user_id: str, project_id: str) -> List[Permission]:
    """Get all effective permissions for a user in a project using stored procedure"""
    with get_connection() as con:
        cur = con.cursor()
        cur.callproc('sp_rbac_get_user_effective_permissions', [user_id, project_id])

        permissions = []
        for row in cur.fetchall():
            permission = Permission(
                id=row[0], permission_hash=row[1], project_id=row[2],
                permission_name=row[3], permission_display_name=row[4],
                permission_description=row[5], permission_category=row[6],
                is_system_permission=bool(row[7]), created_at=row[8],
                updated_at=row[9], created_by=row[10], is_active=bool(row[11])
            )
            # Add role information for audit purposes
            permission.granted_through_role = row[12]
            permissions.append(permission)
        
        while cur.nextset():
            pass

        return permissions


def get_project_audit_log(project_id: str, action_type: str = None, limit: int = 50, offset: int = 0) -> List:
    """Get audit log entries for a project using stored procedure"""
    with get_connection() as con:
        cur = con.cursor()
        cur.callproc('sp_rbac_get_project_audit_log', [project_id, action_type, limit, offset])

        audit_entries = []
        for row in cur.fetchall():
            audit_entries.append({
                'id': row[0],
                'action_type': row[1],
                'table_name': row[2],
                'record_id': row[3],
                'old_values': json.loads(row[4]) if row[4] else None,
                'new_values': json.loads(row[5]) if row[5] else None,
                'performed_by': row[6],
                'performed_at': row[7],
                'ip_address': row[8],
                'user_agent': row[9],
                'project_id': row[10]
            })
        
        while cur.nextset():
            pass

        return audit_entries


def get_project_user_assignments(project_id: str) -> List:
    """Get all user role assignments for a project using stored procedure"""
    with get_connection() as con:
        cur = con.cursor()
        cur.callproc('sp_rbac_get_project_user_assignments', [project_id])

        row = cur.fetchone()
        result_data = {
            'total_users': row[0] if row and row[0] else 0,
            'total_assignments': row[1] if row and row[1] else 0
        }
        
        while cur.nextset():
            pass

        return result_data


def create_default_project_roles(project_id: str, created_by: str = None) -> List[PermissionGroup]:
    """Create default roles for a new project"""
    default_roles = [
        ('admin', 'Administrator', 'Full administrative access', 100),
        ('manager', 'Manager', 'Management and user oversight', 80),
        ('editor', 'Editor', 'Content creation and editing', 60),
        ('contributor', 'Contributor', 'Content contribution', 40),
        ('api_user', 'API User', 'API access with limited permissions', 30),
        ('viewer', 'Viewer', 'Read-only access', 20)
    ]

    created_roles = []
    for role_name, display_name, description, priority in default_roles:
        try:
            role = create_permission_group(
                project_id=project_id,
                group_name=role_name,
                group_display_name=display_name,
                group_description=description,
                group_priority=priority,
                is_system_role=True,
                created_by=created_by
            )
            created_roles.append(role)
        except pymysql.IntegrityError:
            # Role already exists, skip
            continue

    return created_roles


def assign_default_permissions_to_roles(project_id: str, assigned_by: str = None) -> dict:
    """Assign default permissions to default roles"""
    # Get permissions and roles
    permissions = get_project_permissions(project_id)
    roles = get_project_permission_groups(project_id)

    permission_map = {p.permission_name: p for p in permissions}
    role_map = {r.group_name: r for r in roles}

    # Define default role-permission mappings
    role_permissions = {
        'admin': ['admin', 'manage_users', 'manage_roles', 'view_audit', 'read', 'write', 'delete', 'create', 'update',
                  'export_data', 'import_data', 'api_access', 'full_access'],
        'manager': ['manage_users', 'view_audit', 'read', 'write', 'create', 'update', 'export_data', 'api_access'],
        'editor': ['read', 'write', 'create', 'update', 'api_access'],
        'contributor': ['read', 'create', 'update'],
        'api_user': ['api_access', 'read'],
        'viewer': ['read']
    }

    assignments_made = 0
    for role_name, perm_names in role_permissions.items():
        if role_name in role_map:
            role = role_map[role_name]
            for perm_name in perm_names:
                if perm_name in permission_map:
                    permission = permission_map[perm_name]
                    if assign_permission_to_group(role.id, permission.id, assigned_by):
                        assignments_made += 1

    return {
        'assignments_made': assignments_made,
        'total_roles': len(role_map),
        'total_permissions': len(permission_map)
    }


def initialize_project_rbac(
        project_id: str,
        create_defaults: bool = True,
        create_roles: bool = True,
        created_by: str = None
) -> dict:
    """Initialize RBAC for a new project with default permissions and roles"""
    try:
        result = {
            'success': True,
            'permissions_created': 0,
            'roles_created': 0,
            'assignments_made': 0,
            'permissions': [],
            'roles': []
        }

        # Create default permissions
        if create_defaults:
            permissions = create_default_project_permissions(project_id, created_by)
            result['permissions_created'] = len(permissions)
            result['permissions'] = [p.permission_name for p in permissions]

        # Create default roles
        if create_roles:
            roles = create_default_project_roles(project_id, created_by)
            result['roles_created'] = len(roles)
            result['roles'] = [r.group_name for r in roles]

            # Assign default permissions to roles
            if create_defaults:
                assignment_result = assign_default_permissions_to_roles(project_id, created_by)
                result['assignments_made'] = assignment_result['assignments_made']

        return result

    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


# =================== ADDITIONAL HELPER FUNCTIONS ===================

def get_group_permissions(permission_group_id: str) -> List[Permission]:
    """
    Get all permissions assigned to a permission group using stored procedure.
    """
    with get_connection() as con:
        cur = con.cursor()
        cur.callproc('sp_rbac_get_group_permissions', [permission_group_id])

        permissions = []
        for row in cur.fetchall():
            permissions.append(Permission(
                id=row[0], permission_hash=row[1], project_id=row[2],
                permission_name=row[3], permission_display_name=row[4],
                permission_description=row[5], permission_category=row[6],
                is_system_permission=bool(row[7]), created_at=row[8],
                updated_at=row[9], created_by=row[10], is_active=bool(row[11])
            ))
        
        while cur.nextset():
            pass

        return permissions


def get_group_users(permission_group_id: str) -> List[dict]:
    """
    Get all users assigned to a permission group using stored procedure.
    Returns list of users with their assignment details.
    """
    with get_connection() as con:
        cur = con.cursor()
        cur.callproc('sp_rbac_get_group_users', [permission_group_id])

        users = []
        for row in cur.fetchall():
            users.append({
                'id': row[0],
                'user_hash': row[1],
                'username': row[2],
                'email': row[3],
                'user_type': row[4],
                'user_group_name': row[5],
                'assigned_at': row[6]
            })
        
        while cur.nextset():
            pass

        return users


def get_project_users_with_permissions(project_id: str) -> List[dict]:
    """
    Get all users who have permissions in a project using stored procedure.
    Returns list of users with permission counts and roles.
    """
    with get_connection() as con:
        cur = con.cursor()
        cur.callproc('sp_rbac_get_project_users_with_permissions', [project_id])

        users = []
        for row in cur.fetchall():
            users.append({
                'id': row[0],
                'user_hash': row[1],
                'username': row[2],
                'email': row[3],
                'user_type': row[4],
                'permission_count': row[5],
                'role_count': row[6],
                'roles': row[7]
            })
        
        while cur.nextset():
            pass

        return users


def get_user_role_assignment_history(user_id: str, project_id: str, limit: int = 50, offset: int = 0) -> List[dict]:
    """
    Get role assignment history for a user in a project using stored procedure.
    Returns historical data from permission_audit_log.
    """
    with get_connection() as con:
        cur = con.cursor()
        cur.callproc('sp_rbac_get_user_role_assignment_history', [user_id, project_id, limit, offset])

        history = []
        for row in cur.fetchall():
            history.append({
                'id': row[0],
                'action': 'assigned' if row[1] == 'ASSIGN_ROLE' else 'removed',
                'role_id': row[2],
                'role_name': row[3],
                'role_description': row[4],
                'performed_by': row[5],
                'performed_by_username': row[6],
                'performed_by_hash': row[7],
                'performed_at': row[8],
                'old_values': json.loads(row[9]) if row[9] else None,
                'new_values': json.loads(row[10]) if row[10] else None,
                'ip_address': row[11],
                'is_active': row[1] == 'ASSIGN_ROLE',
                'details': f"Role {row[3]} {'assigned to' if row[1] == 'ASSIGN_ROLE' else 'removed from'} user"
            })
        
        while cur.nextset():
            pass

        return history


def count_user_role_assignment_history(user_id: str, project_id: str) -> int:
    """
    Count total role assignment history entries for a user in a project using stored procedure.
    """
    with get_connection() as con:
        cur = con.cursor()
        cur.callproc('sp_rbac_count_user_role_assignment_history', [user_id, project_id])

        row = cur.fetchone()
        total_count = row[0] if row else 0
        
        while cur.nextset():
            pass

        return total_count
