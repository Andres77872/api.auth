"""
RBAC (Role-Based Access Control) Permissions Module

This module implements proper RBAC architecture with:
- Project-specific permissions catalog
- Project-specific permission groups (roles)
- User role assignments per project
- Audit trail for all permission changes

Key RBAC Principles Enforced:
- Each project has its own permission catalog
- Permission groups are project-specific
- Cannot assign permissions outside project scope
- Complete audit trail
"""

import json
import secrets
import os
from typing import List, Optional
from datetime import datetime

import pymysql

from src.Util.Models import (
    Permission, PermissionGroup, PermissionGroupPermission,
    UserProjectPermissionGroup
)

# Database connection settings
ip = "192.168.1.90"
# ip = "127.0.0.1"

connectionDB = {
    "host": ip,
    "user": "root",
    "password": os.environ.get("DB_MYSQL_PASSWORD"),
    "database": "magic-auth"
}


def get_connection():
    """Get database connection"""
    return pymysql.connect(**connectionDB)


# =================== PERMISSION MANAGEMENT ===================

def create_permission(
    project_id: int,
    permission_name: str,
    permission_display_name: str = None,
    permission_description: str = None,
    permission_category: str = 'general',
    category: str = None,  # Compatibility parameter
    is_system_permission: bool = False,
    created_by: int = None
) -> Permission:
    """Create a new project-specific permission"""
    # Handle compatibility parameters
    if category:
        permission_category = category
    if not permission_display_name:
        permission_display_name = permission_name.replace('_', ' ').title()
    
    permission_hash = secrets.token_hex(32).upper()
    
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO permissions (
                permission_hash, project_id, permission_name, permission_display_name,
                permission_description, permission_category, is_system_permission, created_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, [
            permission_hash, project_id, permission_name, permission_display_name,
            permission_description, permission_category, is_system_permission, created_by
        ])
        
        permission_id = con.insert_id()
        con.commit()
        
        return Permission(
            id=permission_id,
            permission_hash=permission_hash,
            project_id=project_id,
            permission_name=permission_name,
            permission_display_name=permission_display_name,
            permission_description=permission_description,
            permission_category=permission_category,
            is_system_permission=is_system_permission,
            created_at=datetime.now(),
            created_by=created_by,
            is_active=True
        )


def get_project_permissions(project_id: int, category: str = None) -> List[Permission]:
    """Get all permissions for a project, optionally filtered by category"""
    with get_connection() as con:
        cur = con.cursor()
        
        query = """
            SELECT id, permission_hash, project_id, permission_name, permission_display_name,
                   permission_description, permission_category, is_system_permission,
                   created_at, updated_at, created_by, is_active
            FROM permissions
            WHERE project_id = %s AND is_active = 1
        """
        params = [project_id]
        
        if category:
            query += " AND permission_category = %s"
            params.append(category)
        
        query += " ORDER BY permission_category, permission_name"
        
        cur.execute(query, params)
        
        permissions = []
        for row in cur.fetchall():
            permissions.append(Permission(
                id=row[0], permission_hash=row[1], project_id=row[2],
                permission_name=row[3], permission_display_name=row[4],
                permission_description=row[5], permission_category=row[6],
                is_system_permission=bool(row[7]), created_at=row[8],
                updated_at=row[9], created_by=row[10], is_active=bool(row[11])
            ))
        
        return permissions


def check_user_permission(user_id: int, project_id: int, permission_name: str) -> bool:
    """Check if user has a specific permission within a project"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT COUNT(*) > 0
            FROM permissions p
            JOIN permission_group_permissions pgp ON p.id = pgp.permission_id
            JOIN permission_groups pg ON pgp.permission_group_id = pg.id
            JOIN user_project_permission_groups uppg ON pg.id = uppg.permission_group_id
            WHERE uppg.user_id = %s AND uppg.project_id = %s AND p.permission_name = %s
            AND p.is_active = 1 AND pgp.is_active = 1 AND pg.is_active = 1 AND uppg.is_active = 1
        """, [user_id, project_id, permission_name])
        
        result = cur.fetchone()
        return bool(result[0]) if result else False


def create_default_project_permissions(project_id: int, created_by: int = None) -> List[Permission]:
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
    project_id: int,
    group_name: str,
    group_display_name: str = None,
    group_description: str = None,
    group_priority: int = 0,
    priority: int = None,  # Compatibility parameter
    description: str = None,  # Compatibility parameter
    is_system_role: bool = False,
    created_by: int = None
) -> PermissionGroup:
    """Create a new project-specific permission group (role)"""
    # Handle compatibility parameters
    if priority is not None:
        group_priority = priority
    if description:
        group_description = description
    if not group_display_name:
        group_display_name = group_name.replace('_', ' ').title()
    
    group_hash = secrets.token_hex(32).upper()
    
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO permission_groups (
                group_hash, project_id, group_name, group_display_name,
                group_description, group_priority, is_system_role, created_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, [
            group_hash, project_id, group_name, group_display_name,
            group_description, group_priority, is_system_role, created_by
        ])
        
        group_id = con.insert_id()
        con.commit()
        
        return PermissionGroup(
            id=group_id,
            group_hash=group_hash,
            project_id=project_id,
            group_name=group_name,
            group_display_name=group_display_name,
            group_description=group_description,
            group_priority=group_priority,
            is_system_role=is_system_role,
            created_at=datetime.now(),
            created_by=created_by,
            is_active=True
        )


def assign_user_to_permission_group(
    user_id: int,
    project_id: int,
    permission_group_id: int,
    assigned_by: int = None
) -> bool:
    """Assign a user to a permission group within a project"""
    # Verify permission group belongs to the project
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT project_id FROM permission_groups 
            WHERE id = %s AND is_active = 1
        """, [permission_group_id])
        
        result = cur.fetchone()
        if not result or result[0] != project_id:
            raise ValueError("Permission group does not belong to the specified project")
        
        try:
            cur.execute("""
                INSERT INTO user_project_permission_groups (user_id, project_id, permission_group_id, assigned_by)
                VALUES (%s, %s, %s, %s)
            """, [user_id, project_id, permission_group_id, assigned_by])
            
            con.commit()
            return True
            
        except pymysql.IntegrityError:
            # User already assigned, reactivate if needed
            cur.execute("""
                UPDATE user_project_permission_groups 
                SET is_active = 1, removed_at = NULL, removed_by = NULL, assigned_by = %s
                WHERE user_id = %s AND project_id = %s AND permission_group_id = %s
            """, [assigned_by, user_id, project_id, permission_group_id])
            
            if cur.rowcount > 0:
                con.commit()
                return True
            
            return False


def get_project_permission_groups(project_id: int) -> List[PermissionGroup]:
    """Get all permission groups (roles) for a project"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT id, group_hash, project_id, group_name, group_display_name,
                   group_description, group_priority, is_system_role,
                   created_at, updated_at, created_by, is_active
            FROM permission_groups
            WHERE project_id = %s AND is_active = 1
            ORDER BY group_priority DESC, group_name
        """, [project_id])
        
        groups = []
        for row in cur.fetchall():
            groups.append(PermissionGroup(
                id=row[0], group_hash=row[1], project_id=row[2],
                group_name=row[3], group_display_name=row[4],
                group_description=row[5], group_priority=row[6],
                is_system_role=bool(row[7]), created_at=row[8],
                updated_at=row[9], created_by=row[10], is_active=bool(row[11])
            ))
        
        return groups


def assign_permission_to_group(permission_group_id: int, permission_id: int, assigned_by: int = None) -> bool:
    """Assign a permission to a permission group"""
    with get_connection() as con:
        cur = con.cursor()
        
        # Verify both belong to the same project
        cur.execute("""
            SELECT pg.project_id, p.project_id
            FROM permission_groups pg, permissions p
            WHERE pg.id = %s AND p.id = %s
        """, [permission_group_id, permission_id])
        
        result = cur.fetchone()
        if not result or result[0] != result[1]:
            raise ValueError("Permission and permission group must belong to the same project")
        
        try:
            cur.execute("""
                INSERT INTO permission_group_permissions (permission_group_id, permission_id, assigned_by)
                VALUES (%s, %s, %s)
            """, [permission_group_id, permission_id, assigned_by])
            
            con.commit()
            return True
            
        except pymysql.IntegrityError:
            # Already assigned, reactivate if needed
            cur.execute("""
                UPDATE permission_group_permissions 
                SET is_active = 1, removed_at = NULL, removed_by = NULL, assigned_by = %s
                WHERE permission_group_id = %s AND permission_id = %s
            """, [assigned_by, permission_group_id, permission_id])
            
            if cur.rowcount > 0:
                con.commit()
                return True
                
            return False


def get_user_permission_groups_in_project(user_id: int, project_id: int) -> List[PermissionGroup]:
    """Get all permission groups assigned to a user in a specific project"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT pg.id, pg.group_hash, pg.project_id, pg.group_name, pg.group_display_name,
                   pg.group_description, pg.group_priority, pg.is_system_role,
                   pg.created_at, pg.updated_at, pg.created_by, pg.is_active,
                   uppg.assigned_at
            FROM permission_groups pg
            JOIN user_project_permission_groups uppg ON pg.id = uppg.permission_group_id
            WHERE uppg.user_id = %s AND uppg.project_id = %s 
            AND pg.is_active = 1 AND uppg.is_active = 1
            ORDER BY pg.group_priority DESC, pg.group_name
        """, [user_id, project_id])
        
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
        
        return groups


def get_user_effective_permissions(user_id: int, project_id: int) -> List[Permission]:
    """Get all effective permissions for a user in a project"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT DISTINCT p.id, p.permission_hash, p.project_id, p.permission_name, 
                   p.permission_display_name, p.permission_description, p.permission_category,
                   p.is_system_permission, p.created_at, p.updated_at, p.created_by, p.is_active,
                   pg.group_name as granted_through_role
            FROM permissions p
            JOIN permission_group_permissions pgp ON p.id = pgp.permission_id
            JOIN permission_groups pg ON pgp.permission_group_id = pg.id
            JOIN user_project_permission_groups uppg ON pg.id = uppg.permission_group_id
            WHERE uppg.user_id = %s AND uppg.project_id = %s
            AND p.is_active = 1 AND pgp.is_active = 1 AND pg.is_active = 1 AND uppg.is_active = 1
            ORDER BY p.permission_category, p.permission_name
        """, [user_id, project_id])
        
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
        
        return permissions


def get_project_audit_log(project_id: int, action_type: str = None, limit: int = 50, offset: int = 0) -> List:
    """Get audit log entries for a project"""
    with get_connection() as con:
        cur = con.cursor()
        
        query = """
            SELECT id, action_type, table_name, record_id, old_values, new_values,
                   performed_by, performed_at, ip_address, user_agent, project_id
            FROM permission_audit_log
            WHERE project_id = %s
        """
        params = [project_id]
        
        if action_type:
            query += " AND action_type = %s"
            params.append(action_type)
        
        query += " ORDER BY performed_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        
        cur.execute(query, params)
        
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
        
        return audit_entries


def get_project_user_assignments(project_id: int) -> List:
    """Get all user role assignments for a project"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT COUNT(DISTINCT user_id) as total_users,
                   COUNT(*) as total_assignments
            FROM user_project_permission_groups
            WHERE project_id = %s AND is_active = 1
        """, [project_id])
        
        result = cur.fetchone()
        return {
            'total_users': result[0] if result else 0,
            'total_assignments': result[1] if result else 0
        }


def create_default_project_roles(project_id: int, created_by: int = None) -> List[PermissionGroup]:
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


def assign_default_permissions_to_roles(project_id: int, assigned_by: int = None) -> dict:
    """Assign default permissions to default roles"""
    # Get permissions and roles
    permissions = get_project_permissions(project_id)
    roles = get_project_permission_groups(project_id)
    
    permission_map = {p.permission_name: p for p in permissions}
    role_map = {r.group_name: r for r in roles}
    
    # Define default role-permission mappings
    role_permissions = {
        'admin': ['admin', 'manage_users', 'manage_roles', 'view_audit', 'read', 'write', 'delete', 'create', 'update', 'export_data', 'import_data', 'api_access', 'full_access'],
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
    project_id: int, 
    create_defaults: bool = True, 
    create_roles: bool = True, 
    created_by: int = None
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