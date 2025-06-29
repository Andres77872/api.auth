"""
RBAC (Role-Based Access Control) Database Module

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
from datetime import datetime
from typing import List, Optional

import pymysql

from src.Util.Models import (
    Permission, PermissionGroup, PermissionGroupPermission,
    UserProjectPermissionGroup, PermissionAuditLog,
    UserPermissionSummary, ProjectRoleSummary
)
from src.Util.db_config import get_connection


# =================== PERMISSION MANAGEMENT ===================

def create_permission(
        project_id: int,
        permission_name: str,
        permission_display_name: str,
        permission_description: str = None,
        permission_category: str = 'general',
        is_system_permission: bool = False,
        created_by: int = None
) -> Permission:
    """Create a new project-specific permission"""
    permission_hash = secrets.token_hex(32).upper()

    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    INSERT INTO permissions (permission_hash, project_id, permission_name, permission_display_name,
                                             permission_description, permission_category, is_system_permission,
                                             created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, [
                        permission_hash, project_id, permission_name, permission_display_name,
                        permission_description, permission_category, is_system_permission, created_by
                    ])

        permission_id = con.insert_id()
        con.commit()

        # Log the action
        log_permission_action(
            'CREATE_PERMISSION', project_id, permission_id=permission_id,
            performed_by=created_by, new_values={
                'permission_name': permission_name,
                'permission_display_name': permission_display_name,
                'permission_category': permission_category
            }
        )

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


def get_permission_by_id(permission_id: int) -> Optional[Permission]:
    """Get permission by ID"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT id,
                           permission_hash,
                           project_id,
                           permission_name,
                           permission_display_name,
                           permission_description,
                           permission_category,
                           is_system_permission,
                           created_at,
                           updated_at,
                           created_by,
                           is_active
                    FROM permissions
                    WHERE id = %s
                      AND is_active = 1
                    """, [permission_id])

        result = cur.fetchone()
        if result:
            return Permission(
                id=result[0], permission_hash=result[1], project_id=result[2],
                permission_name=result[3], permission_display_name=result[4],
                permission_description=result[5], permission_category=result[6],
                is_system_permission=bool(result[7]), created_at=result[8],
                updated_at=result[9], created_by=result[10], is_active=bool(result[11])
            )
    return None


def get_project_permissions(project_id: int, category: str = None) -> List[Permission]:
    """Get all permissions for a project, optionally filtered by category"""
    with get_connection() as con:
        cur = con.cursor()

        query = """
                SELECT id,
                       permission_hash,
                       project_id,
                       permission_name,
                       permission_display_name,
                       permission_description,
                       permission_category,
                       is_system_permission,
                       created_at,
                       updated_at,
                       created_by,
                       is_active
                FROM permissions
                WHERE project_id = %s
                  AND is_active = 1 \
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


def update_permission(
        permission_id: int,
        permission_display_name: str = None,
        permission_description: str = None,
        permission_category: str = None,
        updated_by: int = None
) -> Optional[Permission]:
    """Update permission information (name cannot be changed for consistency)"""
    old_permission = get_permission_by_id(permission_id)
    if not old_permission:
        return None

    update_fields = []
    update_values = []
    changes = {}

    if permission_display_name is not None:
        update_fields.append("permission_display_name = %s")
        update_values.append(permission_display_name)
        changes['permission_display_name'] = permission_display_name

    if permission_description is not None:
        update_fields.append("permission_description = %s")
        update_values.append(permission_description)
        changes['permission_description'] = permission_description

    if permission_category is not None:
        update_fields.append("permission_category = %s")
        update_values.append(permission_category)
        changes['permission_category'] = permission_category

    if not update_fields:
        return old_permission

    update_fields.append("updated_at = NOW()")
    update_values.append(permission_id)

    with get_connection() as con:
        cur = con.cursor()
        query = f"UPDATE permissions SET {', '.join(update_fields)} WHERE id = %s AND is_active = 1"
        cur.execute(query, update_values)

        if cur.rowcount > 0:
            con.commit()

            # Log the action
            log_permission_action(
                'UPDATE_PERMISSION', old_permission.project_id,
                permission_id=permission_id, performed_by=updated_by,
                old_values={
                    'permission_display_name': old_permission.permission_display_name,
                    'permission_description': old_permission.permission_description,
                    'permission_category': old_permission.permission_category
                },
                new_values=changes
            )

            return get_permission_by_id(permission_id)

    return None


def delete_permission(permission_id: int, deleted_by: int = None) -> bool:
    """Soft delete a permission and remove from all permission groups"""
    permission = get_permission_by_id(permission_id)
    if not permission:
        return False

    with get_connection() as con:
        cur = con.cursor()

        try:
            con.begin()

            # Soft delete the permission
            cur.execute("""
                        UPDATE permissions
                        SET is_active  = 0,
                            updated_at = NOW()
                        WHERE id = %s
                          AND is_active = 1
                        """, [permission_id])

            if cur.rowcount == 0:
                con.rollback()
                return False

            # Remove from all permission groups
            cur.execute("""
                        UPDATE permission_group_permissions
                        SET is_active  = 0,
                            revoked_at = NOW(),
                            revoked_by = %s
                        WHERE permission_id = %s
                          AND is_active = 1
                        """, [deleted_by, permission_id])

            con.commit()

            # Log the action
            log_permission_action(
                'DELETE_PERMISSION', permission.project_id,
                permission_id=permission_id, performed_by=deleted_by,
                old_values={
                    'permission_name': permission.permission_name,
                    'permission_display_name': permission.permission_display_name
                }
            )

            return True

        except Exception as e:
            con.rollback()
            print(f"Error deleting permission: {e}")
            return False


# =================== PERMISSION GROUP (ROLE) MANAGEMENT ===================

def create_permission_group(
        project_id: int,
        group_name: str,
        group_display_name: str,
        group_description: str = None,
        group_priority: int = 0,
        is_system_role: bool = False,
        created_by: int = None
) -> PermissionGroup:
    """Create a new project-specific permission group (role)"""
    group_hash = secrets.token_hex(32).upper()

    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    INSERT INTO permission_groups (group_hash, project_id, group_name, group_display_name,
                                                   group_description, group_priority, is_system_role, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, [
                        group_hash, project_id, group_name, group_display_name,
                        group_description, group_priority, is_system_role, created_by
                    ])

        group_id = con.insert_id()
        con.commit()

        # Log the action
        log_permission_action(
            'CREATE_ROLE', project_id, permission_group_id=group_id,
            performed_by=created_by, new_values={
                'group_name': group_name,
                'group_display_name': group_display_name,
                'group_priority': group_priority
            }
        )

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


def get_permission_group_by_id(group_id: int) -> Optional[PermissionGroup]:
    """Get permission group by ID"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT id,
                           group_hash,
                           project_id,
                           group_name,
                           group_display_name,
                           group_description,
                           group_priority,
                           is_system_role,
                           created_at,
                           updated_at,
                           created_by,
                           is_active
                    FROM permission_groups
                    WHERE id = %s
                      AND is_active = 1
                    """, [group_id])

        result = cur.fetchone()
        if result:
            return PermissionGroup(
                id=result[0], group_hash=result[1], project_id=result[2],
                group_name=result[3], group_display_name=result[4],
                group_description=result[5], group_priority=result[6],
                is_system_role=bool(result[7]), created_at=result[8],
                updated_at=result[9], created_by=result[10], is_active=bool(result[11])
            )
    return None


def get_project_permission_groups(project_id: int) -> List[PermissionGroup]:
    """Get all permission groups for a project"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT id,
                           group_hash,
                           project_id,
                           group_name,
                           group_display_name,
                           group_description,
                           group_priority,
                           is_system_role,
                           created_at,
                           updated_at,
                           created_by,
                           is_active
                    FROM permission_groups
                    WHERE project_id = %s
                      AND is_active = 1
                    ORDER BY group_priority DESC, group_name ASC
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


def grant_permission_to_group(
        permission_group_id: int,
        permission_id: int,
        granted_by: int = None
) -> Optional[PermissionGroupPermission]:
    """Grant a permission to a permission group (ensures same project)"""
    # Verify both belong to the same project
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT pg.project_id, p.project_id
                    FROM permission_groups pg,
                         permissions p
                    WHERE pg.id = %s
                      AND p.id = %s
                      AND pg.is_active = 1
                      AND p.is_active = 1
                    """, [permission_group_id, permission_id])

        result = cur.fetchone()
        if not result or result[0] != result[1]:
            raise ValueError("Permission and permission group must belong to the same project")

        project_id = result[0]

        try:
            cur.execute("""
                        INSERT INTO permission_group_permissions (permission_group_id, permission_id, granted_by)
                        VALUES (%s, %s, %s)
                        """, [permission_group_id, permission_id, granted_by])

            link_id = con.insert_id()
            con.commit()

            # Log the action
            log_permission_action(
                'GRANT_PERMISSION', project_id,
                permission_id=permission_id, permission_group_id=permission_group_id,
                performed_by=granted_by
            )

            return PermissionGroupPermission(
                id=link_id,
                permission_group_id=permission_group_id,
                permission_id=permission_id,
                granted_at=datetime.now(),
                granted_by=granted_by,
                is_active=True
            )

        except pymysql.IntegrityError:
            # Permission already granted, reactivate if needed
            cur.execute("""
                        UPDATE permission_group_permissions
                        SET is_active  = 1,
                            revoked_at = NULL,
                            revoked_by = NULL,
                            granted_by = %s
                        WHERE permission_group_id = %s
                          AND permission_id = %s
                        """, [granted_by, permission_group_id, permission_id])

            if cur.rowcount > 0:
                con.commit()
                return get_permission_group_permission(permission_group_id, permission_id)

            return None


def revoke_permission_from_group(
        permission_group_id: int,
        permission_id: int,
        revoked_by: int = None
) -> bool:
    """Revoke a permission from a permission group"""
    with get_connection() as con:
        cur = con.cursor()

        # Get project ID for logging
        cur.execute("""
                    SELECT pg.project_id
                    FROM permission_groups pg
                    WHERE pg.id = %s
                      AND pg.is_active = 1
                    """, [permission_group_id])

        result = cur.fetchone()
        if not result:
            return False

        project_id = result[0]

        cur.execute("""
                    UPDATE permission_group_permissions
                    SET is_active  = 0,
                        revoked_at = NOW(),
                        revoked_by = %s
                    WHERE permission_group_id = %s
                      AND permission_id = %s
                      AND is_active = 1
                    """, [revoked_by, permission_group_id, permission_id])

        success = cur.rowcount > 0
        if success:
            con.commit()

            # Log the action
            log_permission_action(
                'REVOKE_PERMISSION', project_id,
                permission_id=permission_id, permission_group_id=permission_group_id,
                performed_by=revoked_by
            )

        return success


def get_permission_group_permission(permission_group_id: int, permission_id: int) -> Optional[
    PermissionGroupPermission]:
    """Get specific permission group permission link"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT id,
                           permission_group_id,
                           permission_id,
                           granted_at,
                           granted_by,
                           revoked_at,
                           revoked_by,
                           is_active
                    FROM permission_group_permissions
                    WHERE permission_group_id = %s
                      AND permission_id = %s
                      AND is_active = 1
                    """, [permission_group_id, permission_id])

        result = cur.fetchone()
        if result:
            return PermissionGroupPermission(
                id=result[0], permission_group_id=result[1], permission_id=result[2],
                granted_at=result[3], granted_by=result[4], revoked_at=result[5],
                revoked_by=result[6], is_active=bool(result[7])
            )
    return None


def get_permission_group_permissions(permission_group_id: int) -> List[Permission]:
    """Get all permissions assigned to a permission group"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT p.id,
                           p.permission_hash,
                           p.project_id,
                           p.permission_name,
                           p.permission_display_name,
                           p.permission_description,
                           p.permission_category,
                           p.is_system_permission,
                           p.created_at,
                           p.updated_at,
                           p.created_by,
                           p.is_active
                    FROM permissions p
                             JOIN permission_group_permissions pgp ON p.id = pgp.permission_id
                    WHERE pgp.permission_group_id = %s
                      AND p.is_active = 1
                      AND pgp.is_active = 1
                    ORDER BY p.permission_category, p.permission_name
                    """, [permission_group_id])

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


# =================== USER ROLE ASSIGNMENTS ===================

def assign_user_to_permission_group(
        user_id: int,
        project_id: int,
        permission_group_id: int,
        assigned_by: int = None
) -> Optional[UserProjectPermissionGroup]:
    """Assign a user to a permission group within a project"""
    # Verify permission group belongs to the project
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT project_id
                    FROM permission_groups
                    WHERE id = %s
                      AND is_active = 1
                    """, [permission_group_id])

        result = cur.fetchone()
        if not result or result[0] != project_id:
            raise ValueError("Permission group does not belong to the specified project")

        try:
            cur.execute("""
                        INSERT INTO user_project_permission_groups (user_id, project_id, permission_group_id, assigned_by)
                        VALUES (%s, %s, %s, %s)
                        """, [user_id, project_id, permission_group_id, assigned_by])

            assignment_id = con.insert_id()
            con.commit()

            # Log the action
            log_permission_action(
                'ASSIGN_ROLE', project_id,
                target_user_id=user_id, permission_group_id=permission_group_id,
                performed_by=assigned_by
            )

            return UserProjectPermissionGroup(
                id=assignment_id,
                user_id=user_id,
                project_id=project_id,
                permission_group_id=permission_group_id,
                assigned_at=datetime.now(),
                assigned_by=assigned_by,
                is_active=True
            )

        except pymysql.IntegrityError:
            # User already assigned, reactivate if needed
            cur.execute("""
                        UPDATE user_project_permission_groups
                        SET is_active   = 1,
                            removed_at  = NULL,
                            removed_by  = NULL,
                            assigned_by = %s
                        WHERE user_id = %s
                          AND project_id = %s
                          AND permission_group_id = %s
                        """, [assigned_by, user_id, project_id, permission_group_id])

            if cur.rowcount > 0:
                con.commit()
                return get_user_permission_group_assignment(user_id, project_id, permission_group_id)

            return None


def remove_user_from_permission_group(
        user_id: int,
        project_id: int,
        permission_group_id: int,
        removed_by: int = None
) -> bool:
    """Remove a user from a permission group within a project"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    UPDATE user_project_permission_groups
                    SET is_active  = 0,
                        removed_at = NOW(),
                        removed_by = %s
                    WHERE user_id = %s
                      AND project_id = %s
                      AND permission_group_id = %s
                      AND is_active = 1
                    """, [removed_by, user_id, project_id, permission_group_id])

        success = cur.rowcount > 0
        if success:
            con.commit()

            # Log the action
            log_permission_action(
                'REMOVE_ROLE', project_id,
                target_user_id=user_id, permission_group_id=permission_group_id,
                performed_by=removed_by
            )

        return success


def get_user_permission_group_assignment(user_id: int, project_id: int, permission_group_id: int) -> Optional[
    UserProjectPermissionGroup]:
    """Get specific user permission group assignment"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT id,
                           user_id,
                           project_id,
                           permission_group_id,
                           assigned_at,
                           assigned_by,
                           removed_at,
                           removed_by,
                           is_active
                    FROM user_project_permission_groups
                    WHERE user_id = %s
                      AND project_id = %s
                      AND permission_group_id = %s
                      AND is_active = 1
                    """, [user_id, project_id, permission_group_id])

        result = cur.fetchone()
        if result:
            return UserProjectPermissionGroup(
                id=result[0], user_id=result[1], project_id=result[2],
                permission_group_id=result[3], assigned_at=result[4], assigned_by=result[5],
                removed_at=result[6], removed_by=result[7], is_active=bool(result[8])
            )
    return None


def get_user_permission_groups(user_id: int, project_id: int) -> List[PermissionGroup]:
    """Get all permission groups assigned to a user within a project"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT pg.id,
                           pg.group_hash,
                           pg.project_id,
                           pg.group_name,
                           pg.group_display_name,
                           pg.group_description,
                           pg.group_priority,
                           pg.is_system_role,
                           pg.created_at,
                           pg.updated_at,
                           pg.created_by,
                           pg.is_active
                    FROM permission_groups pg
                             JOIN user_project_permission_groups uppg ON pg.id = uppg.permission_group_id
                    WHERE uppg.user_id = %s
                      AND uppg.project_id = %s
                      AND pg.is_active = 1
                      AND uppg.is_active = 1
                    ORDER BY pg.group_priority DESC, pg.group_name ASC
                    """, [user_id, project_id])

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


def get_user_effective_permissions(user_id: int, project_id: int) -> List[Permission]:
    """Get all effective permissions for a user within a project"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT DISTINCT p.id,
                                    p.permission_hash,
                                    p.project_id,
                                    p.permission_name,
                                    p.permission_display_name,
                                    p.permission_description,
                                    p.permission_category,
                                    p.is_system_permission,
                                    p.created_at,
                                    p.updated_at,
                                    p.created_by,
                                    p.is_active
                    FROM permissions p
                             JOIN permission_group_permissions pgp ON p.id = pgp.permission_id
                             JOIN permission_groups pg ON pgp.permission_group_id = pg.id
                             JOIN user_project_permission_groups uppg ON pg.id = uppg.permission_group_id
                    WHERE uppg.user_id = %s
                      AND uppg.project_id = %s
                      AND p.is_active = 1
                      AND pgp.is_active = 1
                      AND pg.is_active = 1
                      AND uppg.is_active = 1
                    ORDER BY p.permission_category, p.permission_name
                    """, [user_id, project_id])

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
                    WHERE uppg.user_id = %s
                      AND uppg.project_id = %s
                      AND p.permission_name = %s
                      AND p.is_active = 1
                      AND pgp.is_active = 1
                      AND pg.is_active = 1
                      AND uppg.is_active = 1
                    """, [user_id, project_id, permission_name])

        result = cur.fetchone()
        return bool(result[0]) if result else False


# =================== DEFAULT PERMISSIONS AND ROLES ===================

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


def create_default_project_roles(project_id: int, created_by: int = None) -> List[PermissionGroup]:
    """Create default system roles for a new project"""
    # Get all permissions for this project
    all_permissions = get_project_permissions(project_id)
    permission_map = {p.permission_name: p for p in all_permissions}

    default_roles = [
        {
            'name': 'admin',
            'display_name': 'Administrator',
            'description': 'Full administrative access to all features',
            'priority': 100,
            'permissions': ['admin', 'read', 'write', 'delete', 'create', 'update',
                            'manage_users', 'manage_roles', 'view_audit', 'export_data',
                            'import_data', 'api_access', 'full_access']
        },
        {
            'name': 'manager',
            'display_name': 'Manager',
            'description': 'Management access with user and role management',
            'priority': 80,
            'permissions': ['read', 'write', 'create', 'update', 'manage_users',
                            'view_audit', 'export_data', 'api_access']
        },
        {
            'name': 'editor',
            'display_name': 'Editor',
            'description': 'Content editing and management access',
            'priority': 60,
            'permissions': ['read', 'write', 'create', 'update', 'export_data']
        },
        {
            'name': 'contributor',
            'display_name': 'Contributor',
            'description': 'Can create and edit own content',
            'priority': 40,
            'permissions': ['read', 'write', 'create']
        },
        {
            'name': 'viewer',
            'display_name': 'Viewer',
            'description': 'Read-only access to content',
            'priority': 20,
            'permissions': ['read']
        },
        {
            'name': 'api_user',
            'display_name': 'API User',
            'description': 'API access for integrations',
            'priority': 30,
            'permissions': ['api_access', 'read']
        }
    ]

    created_roles = []
    for role_data in default_roles:
        try:
            # Create the role
            role = create_permission_group(
                project_id=project_id,
                group_name=role_data['name'],
                group_display_name=role_data['display_name'],
                group_description=role_data['description'],
                group_priority=role_data['priority'],
                is_system_role=True,
                created_by=created_by
            )

            # Grant permissions to the role
            for perm_name in role_data['permissions']:
                if perm_name in permission_map:
                    grant_permission_to_group(
                        role.id,
                        permission_map[perm_name].id,
                        granted_by=created_by
                    )

            created_roles.append(role)

        except pymysql.IntegrityError:
            # Role already exists, skip
            continue

    return created_roles


# =================== AUDIT LOGGING ===================

def log_permission_action(
        action_type: str,
        project_id: int,
        target_user_id: int = None,
        permission_id: int = None,
        permission_group_id: int = None,
        performed_by: int = None,
        old_values: dict = None,
        new_values: dict = None,
        ip_address: str = None,
        user_agent: str = None
):
    """Log permission-related actions for audit trail"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    INSERT INTO permission_audit_log (action_type, project_id, target_user_id, permission_id,
                                                      permission_group_id,
                                                      performed_by, old_values, new_values, ip_address, user_agent)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, [
                        action_type, project_id, target_user_id, permission_id, permission_group_id,
                        performed_by, json.dumps(old_values) if old_values else None,
                        json.dumps(new_values) if new_values else None, ip_address, user_agent
                    ])
        con.commit()


def get_project_audit_log(project_id: int, limit: int = 100, offset: int = 0) -> List[PermissionAuditLog]:
    """Get audit log for a project"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT id,
                           action_type,
                           project_id,
                           target_user_id,
                           permission_id,
                           permission_group_id,
                           performed_by,
                           old_values,
                           new_values,
                           action_timestamp,
                           ip_address,
                           user_agent
                    FROM permission_audit_log
                    WHERE project_id = %s
                    ORDER BY action_timestamp DESC
                        LIMIT %s
                    OFFSET %s
                    """, [project_id, limit, offset])

        logs = []
        for row in cur.fetchall():
            old_values = json.loads(row[7]) if row[7] else None
            new_values = json.loads(row[8]) if row[8] else None

            logs.append(PermissionAuditLog(
                id=row[0], action_type=row[1], project_id=row[2],
                target_user_id=row[3], permission_id=row[4], permission_group_id=row[5],
                performed_by=row[6], old_values=old_values, new_values=new_values,
                action_timestamp=row[9], ip_address=row[10], user_agent=row[11]
            ))

        return logs


# =================== SUMMARY AND REPORTING ===================

def get_user_permission_summary(user_id: int, project_id: int) -> Optional[UserPermissionSummary]:
    """Get comprehensive permission summary for a user within a project"""
    with get_connection() as con:
        cur = con.cursor()

        # Get user and project info
        cur.execute("""
                    SELECT u.user_hash, u.username, p.project_hash, p.project_name
                    FROM users u,
                         projects p
                    WHERE u.id = %s
                      AND p.id = %s
                      AND u.is_active = 1
                      AND p.is_active = 1
                    """, [user_id, project_id])

        result = cur.fetchone()
        if not result:
            return None

        user_hash, username, project_hash, project_name = result

        # Get assigned roles
        assigned_roles = get_user_permission_groups(user_id, project_id)

        # Get effective permissions
        effective_permissions = get_user_effective_permissions(user_id, project_id)

        # Get highest priority role
        highest_priority_role = assigned_roles[0] if assigned_roles else None

        return UserPermissionSummary(
            user_id=user_id,
            user_hash=user_hash,
            username=username,
            project_id=project_id,
            project_hash=project_hash,
            project_name=project_name,
            assigned_roles=assigned_roles,
            effective_permissions=effective_permissions,
            highest_priority_role=highest_priority_role
        )


def get_project_role_summary(project_id: int) -> Optional[ProjectRoleSummary]:
    """Get comprehensive role summary for a project"""
    with get_connection() as con:
        cur = con.cursor()

        # Get project info
        cur.execute("""
                    SELECT project_hash, project_name
                    FROM projects
                    WHERE id = %s
                      AND is_active = 1
                    """, [project_id])

        result = cur.fetchone()
        if not result:
            return None

        project_hash, project_name = result

        # Get all roles for project
        roles = get_project_permission_groups(project_id)

        # Get total permissions
        cur.execute("""
                    SELECT COUNT(DISTINCT permission_category)
                    FROM permissions
                    WHERE project_id = %s
                      AND is_active = 1
                    """, [project_id])

        total_permissions = cur.fetchone()[0]

        # Get total users with roles in this project
        cur.execute("""
                    SELECT COUNT(DISTINCT user_id)
                    FROM user_project_permission_groups
                    WHERE project_id = %s
                      AND is_active = 1
                    """, [project_id])

        total_users = cur.fetchone()[0]

        # Get permission categories
        cur.execute("""
                    SELECT DISTINCT permission_category
                    FROM permissions
                    WHERE project_id = %s
                      AND is_active = 1
                    ORDER BY permission_category
                    """, [project_id])

        permission_categories = [row[0] for row in cur.fetchall()]

        return ProjectRoleSummary(
            project_id=project_id,
            project_hash=project_hash,
            project_name=project_name,
            roles=roles,
            total_permissions=total_permissions,
            total_users=total_users,
            permission_categories=permission_categories
        )
