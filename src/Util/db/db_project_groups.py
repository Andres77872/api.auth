"""
Enhanced Multi-Project Authentication - Project Group Management

This module handles all project group-related database operations in the new
hierarchical access control system where:
- Projects belong to Project Groups
- Project Groups define permissions
- Users get permissions through: User Group → Project Access → Project Group Permissions
"""

import json
import secrets
from datetime import datetime
from typing import List, Optional

import pymysql

from src.Util.Models import (
    Project, ProjectGroup, ProjectGroupMember
)
from src.Util.db_config import get_connection


# =================== PROJECT GROUP MANAGEMENT ===================

def create_project_group(group_name: str, permissions: List[str], group_description: str = None,
                         created_by: int = None) -> ProjectGroup:
    """Create a new project group with permissions"""
    group_hash = secrets.token_hex(32).upper()
    permissions_json = json.dumps(permissions)

    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    INSERT INTO project_groups (group_hash, group_name, group_description, permissions, created_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    """, [group_hash, group_name, group_description, permissions_json])

        group_id = con.insert_id()
        con.commit()

        return ProjectGroup(
            id=group_id,
            group_hash=group_hash,
            group_name=group_name,
            group_description=group_description,
            permissions=permissions,
            created_at=datetime.now(),
            is_active=True
        )


def get_project_group_by_id(group_id: int) -> Optional[ProjectGroup]:
    """Get project group by ID"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT id,
                           group_hash,
                           group_name,
                           group_description,
                           permissions,
                           created_at,
                           updated_at,
                           is_active
                    FROM project_groups
                    WHERE id = %s
                      AND is_active = 1
                    """, [group_id])

        result = cur.fetchone()
        if result:
            permissions = json.loads(result[4]) if result[4] else []
            return ProjectGroup(
                id=result[0],
                group_hash=result[1],
                group_name=result[2],
                group_description=result[3],
                permissions=permissions,
                created_at=result[5],
                updated_at=result[6],
                is_active=bool(result[7])
            )
    return None


def get_project_group_by_hash(group_hash: str) -> Optional[ProjectGroup]:
    """Get project group by hash"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT id,
                           group_hash,
                           group_name,
                           group_description,
                           permissions,
                           created_at,
                           updated_at,
                           is_active
                    FROM project_groups
                    WHERE group_hash = %s
                      AND is_active = 1
                    """, [group_hash])

        result = cur.fetchone()
        if result:
            permissions = json.loads(result[4]) if result[4] else []
            return ProjectGroup(
                id=result[0],
                group_hash=result[1],
                group_name=result[2],
                group_description=result[3],
                permissions=permissions,
                created_at=result[5],
                updated_at=result[6],
                is_active=bool(result[7])
            )
    return None


def get_project_group_by_name(group_name: str) -> Optional[ProjectGroup]:
    """Get project group by name"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT id,
                           group_hash,
                           group_name,
                           group_description,
                           permissions,
                           created_at,
                           updated_at,
                           is_active
                    FROM project_groups
                    WHERE group_name = %s
                      AND is_active = 1
                    """, [group_name])

        result = cur.fetchone()
        if result:
            permissions = json.loads(result[4]) if result[4] else []
            return ProjectGroup(
                id=result[0],
                group_hash=result[1],
                group_name=result[2],
                group_description=result[3],
                permissions=permissions,
                created_at=result[5],
                updated_at=result[6],
                is_active=bool(result[7])
            )
    return None


def list_all_project_groups(limit: int = 100, offset: int = 0) -> List[ProjectGroup]:
    """List all active project groups with pagination"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT id,
                           group_hash,
                           group_name,
                           group_description,
                           permissions,
                           created_at,
                           updated_at,
                           is_active
                    FROM project_groups
                    WHERE is_active = 1
                    ORDER BY group_name ASC
                        LIMIT %s
                    OFFSET %s
                    """, [limit, offset])

        results = []
        for row in cur.fetchall():
            permissions = json.loads(row[4]) if row[4] else []
            results.append(ProjectGroup(
                id=row[0],
                group_hash=row[1],
                group_name=row[2],
                group_description=row[3],
                permissions=permissions,
                created_at=row[5],
                updated_at=row[6],
                is_active=bool(row[7])
            ))

        return results


def update_project_group(group_id: int, group_name: str = None, group_description: str = None,
                         permissions: List[str] = None) -> Optional[ProjectGroup]:
    """Update project group information"""
    if not group_name and group_description is None and permissions is None:
        return None

    with get_connection() as con:
        cur = con.cursor()

        # Build dynamic update query
        update_fields = []
        update_values = []

        if group_name:
            update_fields.append("group_name = %s")
            update_values.append(group_name)

        if group_description is not None:
            update_fields.append("group_description = %s")
            update_values.append(group_description)

        if permissions is not None:
            update_fields.append("permissions = %s")
            update_values.append(json.dumps(permissions))

        update_fields.append("updated_at = NOW()")
        update_values.append(group_id)

        query = f"""
            UPDATE project_groups 
            SET {', '.join(update_fields)}
            WHERE id = %s AND is_active = 1
        """

        cur.execute(query, update_values)

        if cur.rowcount > 0:
            con.commit()
            return get_project_group_by_id(group_id)
        else:
            return None


def delete_project_group(group_id: int, deleted_by: int = None) -> bool:
    """Soft delete a project group and all related relationships"""
    with get_connection() as con:
        cur = con.cursor()

        try:
            # Start transaction
            con.begin()

            # Soft delete the project group
            cur.execute("""
                        UPDATE project_groups
                        SET is_active  = 0,
                            updated_at = NOW()
                        WHERE id = %s
                          AND is_active = 1
                        """, [group_id])

            if cur.rowcount == 0:
                con.rollback()
                return False

            # Soft delete all project memberships
            cur.execute("""
                        UPDATE project_group_members
                        SET is_active  = 0,
                            removed_at = NOW(),
                            removed_by = %s
                        WHERE project_group_id = %s
                          AND is_active = 1
                        """, [deleted_by, group_id])

            con.commit()
            return True

        except Exception as e:
            con.rollback()
            print(f"Error deleting project group: {e}")
            return False


# =================== PROJECT GROUP MEMBERSHIP ===================

def assign_project_to_group(project_id: int, project_group_id: int, assigned_by: int = None) -> Optional[
    ProjectGroupMember]:
    """Assign a project to a project group"""
    with get_connection() as con:
        cur = con.cursor()

        try:
            cur.execute("""
                        INSERT INTO project_group_members (project_id, project_group_id, assigned_at, assigned_by)
                        VALUES (%s, %s, NOW(), %s)
                        """, [project_id, project_group_id, assigned_by])

            member_id = con.insert_id()
            con.commit()

            return ProjectGroupMember(
                id=member_id,
                project_id=project_id,
                project_group_id=project_group_id,
                assigned_at=datetime.now(),
                assigned_by=assigned_by,
                is_active=True
            )

        except pymysql.IntegrityError:
            # Project already in group, reactivate if needed
            cur.execute("""
                        UPDATE project_group_members
                        SET is_active   = 1,
                            removed_at  = NULL,
                            removed_by  = NULL,
                            assigned_by = %s
                        WHERE project_id = %s
                          AND project_group_id = %s
                        """, [assigned_by, project_id, project_group_id])

            if cur.rowcount > 0:
                con.commit()
                return get_project_group_membership(project_id, project_group_id)

            return None


def remove_project_from_group(project_id: int, project_group_id: int, removed_by: int = None) -> bool:
    """Remove a project from a project group"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    UPDATE project_group_members
                    SET is_active  = 0,
                        removed_at = NOW(),
                        removed_by = %s
                    WHERE project_id = %s
                      AND project_group_id = %s
                      AND is_active = 1
                    """, [removed_by, project_id, project_group_id])

        success = cur.rowcount > 0
        if success:
            con.commit()
        return success


def get_project_group_membership(project_id: int, project_group_id: int) -> Optional[ProjectGroupMember]:
    """Get specific project group membership"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT id,
                           project_id,
                           project_group_id,
                           assigned_at,
                           assigned_by,
                           removed_at,
                           removed_by,
                           is_active
                    FROM project_group_members
                    WHERE project_id = %s
                      AND project_group_id = %s
                      AND is_active = 1
                    """, [project_id, project_group_id])

        result = cur.fetchone()
        if result:
            return ProjectGroupMember(
                id=result[0],
                project_id=result[1],
                project_group_id=result[2],
                assigned_at=result[3],
                assigned_by=result[4],
                removed_at=result[5],
                removed_by=result[6],
                is_active=bool(result[7])
            )
    return None


def get_project_groups_for_project(project_id: int) -> List[ProjectGroup]:
    """Get all project groups a project belongs to"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT pg.id,
                           pg.group_hash,
                           pg.group_name,
                           pg.group_description,
                           pg.permissions,
                           pg.created_at,
                           pg.updated_at,
                           pg.is_active
                    FROM project_groups pg
                             INNER JOIN project_group_members pgm ON pg.id = pgm.project_group_id
                    WHERE pgm.project_id = %s
                      AND pg.is_active = 1
                      AND pgm.is_active = 1
                    ORDER BY pg.group_name ASC
                    """, [project_id])

        groups = []
        for row in cur.fetchall():
            permissions = json.loads(row[4]) if row[4] else []
            groups.append(ProjectGroup(
                id=row[0],
                group_hash=row[1],
                group_name=row[2],
                group_description=row[3],
                permissions=permissions,
                created_at=row[5],
                updated_at=row[6],
                is_active=bool(row[7])
            ))

        return groups


def get_projects_in_group(project_group_id: int) -> List[Project]:
    """Get all projects in a project group"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT p.id,
                           p.project_hash,
                           p.project_name,
                           p.project_description,
                           p.created_at,
                           p.updated_at,
                           p.is_active
                    FROM projects p
                             INNER JOIN project_group_members pgm ON p.id = pgm.project_id
                    WHERE pgm.project_group_id = %s
                      AND p.is_active = 1
                      AND pgm.is_active = 1
                    ORDER BY p.project_name ASC
                    """, [project_group_id])

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

        return projects


# =================== PERMISSION UTILITIES ===================

def get_project_permissions(project_id: int) -> List[str]:
    """Get all permissions available for a project (from all its project groups)"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT DISTINCT pg.permissions
                    FROM project_groups pg
                             INNER JOIN project_group_members pgm ON pg.id = pgm.project_group_id
                    WHERE pgm.project_id = %s
                      AND pg.is_active = 1
                      AND pgm.is_active = 1
                    """, [project_id])

        all_permissions = set()
        for row in cur.fetchall():
            permissions = json.loads(row[0]) if row[0] else []
            all_permissions.update(permissions)

        return list(all_permissions)


def get_user_project_permissions(user_id: int, project_id: int) -> List[str]:
    """Get permissions a user has for a specific project"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT DISTINCT pg.permissions
                    FROM project_groups pg
                             INNER JOIN project_group_members pgm ON pg.id = pgm.project_group_id
                             INNER JOIN projects p ON pgm.project_id = p.id
                             INNER JOIN user_group_projects ugp ON p.id = ugp.project_id
                             INNER JOIN user_groups ug ON ugp.user_group_id = ug.id
                             INNER JOIN user_group_members ugm ON ug.id = ugm.user_group_id
                    WHERE ugm.user_id = %s
                      AND p.id = %s
                      AND pg.is_active = 1
                      AND pgm.is_active = 1
                      AND p.is_active = 1
                      AND ugp.is_active = 1
                      AND ug.is_active = 1
                      AND ugm.is_active = 1
                    """, [user_id, project_id])

        all_permissions = set()
        for row in cur.fetchall():
            permissions = json.loads(row[0]) if row[0] else []
            all_permissions.update(permissions)

        return list(all_permissions)


def check_user_project_permission(user_id: int, project_id: int, required_permission: str) -> bool:
    """Check if user has a specific permission for a project"""
    user_permissions = get_user_project_permissions(user_id, project_id)
    return required_permission in user_permissions or 'admin' in user_permissions


# =================== DEFAULT GROUPS ===================

def create_default_project_groups():
    """Create default project groups"""
    default_groups = [
        {
            'name': 'full-access',
            'description': 'Full access to project resources',
            'permissions': ['admin', 'read', 'write', 'delete', 'manage_users', 'manage_groups', 'export_data']
        },
        {
            'name': 'read-write',
            'description': 'Read and write access to project resources',
            'permissions': ['read', 'write', 'create']
        },
        {
            'name': 'read-only',
            'description': 'Read-only access to project resources',
            'permissions': ['read', 'view']
        }
    ]

    created_groups = []
    for group_data in default_groups:
        # Check if group already exists
        existing_group = get_project_group_by_name(group_data['name'])
        if not existing_group:
            group = create_project_group(
                group_name=group_data['name'],
                group_description=group_data['description'],
                permissions=group_data['permissions']
            )
            created_groups.append(group)
        else:
            created_groups.append(existing_group)

    return created_groups


# =================== UTILITIES ===================

def count_project_groups() -> int:
    """Count total number of active project groups"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM project_groups WHERE is_active = 1")
        return cur.fetchone()[0]


def search_project_groups(search_term: str, limit: int = 50) -> List[ProjectGroup]:
    """Search project groups by name or description"""
    with get_connection() as con:
        cur = con.cursor()
        search_pattern = f"%{search_term}%"

        cur.execute("""
                    SELECT id,
                           group_hash,
                           group_name,
                           group_description,
                           permissions,
                           created_at,
                           updated_at,
                           is_active
                    FROM project_groups
                    WHERE is_active = 1
                      AND (group_name LIKE %s OR group_description LIKE %s)
                    ORDER BY group_name ASC
                        LIMIT %s
                    """, [search_pattern, search_pattern, limit])

        results = []
        for row in cur.fetchall():
            permissions = json.loads(row[4]) if row[4] else []
            results.append(ProjectGroup(
                id=row[0],
                group_hash=row[1],
                group_name=row[2],
                group_description=row[3],
                permissions=permissions,
                created_at=row[5],
                updated_at=row[6],
                is_active=bool(row[7])
            ))

        return results
