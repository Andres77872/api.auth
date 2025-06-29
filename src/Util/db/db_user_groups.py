"""
Enhanced Multi-Project Authentication - User Group Management

This module handles all user group-related database operations in the new
hierarchical access control system where:
- Users belong to User Groups (global)
- User Groups define which projects users can access
- Permissions are defined at the project level through Project Groups
"""

import json
import secrets
import os
from typing import List, Optional, Tuple
from datetime import datetime

import pymysql

from src.Util.Models import (
    User, UserGroup, UserGroupMember, UserGroupProject, ProjectSummary
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


# =================== USER GROUP MANAGEMENT ===================

def create_user_group(group_name: str, group_description: str = None, created_by: int = None) -> UserGroup:
    """Create a new global user group"""
    group_hash = secrets.token_hex(32).upper()
    
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO user_groups (group_hash, group_name, group_description, created_at)
            VALUES (%s, %s, %s, NOW())
        """, [group_hash, group_name, group_description])
        
        group_id = con.insert_id()
        con.commit()
        
        return UserGroup(
            id=group_id,
            group_hash=group_hash,
            group_name=group_name,
            group_description=group_description,
            created_at=datetime.now(),
            is_active=True
        )


def get_user_group_by_id(group_id: int) -> Optional[UserGroup]:
    """Get user group by ID"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT id, group_hash, group_name, group_description, created_at, updated_at, is_active
            FROM user_groups 
            WHERE id = %s AND is_active = 1
        """, [group_id])
        
        result = cur.fetchone()
        if result:
            return UserGroup(
                id=result[0],
                group_hash=result[1],
                group_name=result[2],
                group_description=result[3],
                created_at=result[4],
                updated_at=result[5],
                is_active=bool(result[6])
            )
    return None


def get_user_group_by_hash(group_hash: str) -> Optional[UserGroup]:
    """Get user group by hash"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT id, group_hash, group_name, group_description, created_at, updated_at, is_active
            FROM user_groups 
            WHERE group_hash = %s AND is_active = 1
        """, [group_hash])
        
        result = cur.fetchone()
        if result:
            return UserGroup(
                id=result[0],
                group_hash=result[1],
                group_name=result[2],
                group_description=result[3],
                created_at=result[4],
                updated_at=result[5],
                is_active=bool(result[6])
            )
    return None


def get_user_group_by_name(group_name: str) -> Optional[UserGroup]:
    """Get user group by name"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT id, group_hash, group_name, group_description, created_at, updated_at, is_active
            FROM user_groups 
            WHERE group_name = %s AND is_active = 1
        """, [group_name])
        
        result = cur.fetchone()
        if result:
            return UserGroup(
                id=result[0],
                group_hash=result[1],
                group_name=result[2],
                group_description=result[3],
                created_at=result[4],
                updated_at=result[5],
                is_active=bool(result[6])
            )
    return None


def list_all_user_groups(limit: int = 100, offset: int = 0) -> List[UserGroup]:
    """List all active user groups with pagination"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT id, group_hash, group_name, group_description, created_at, updated_at, is_active
            FROM user_groups 
            WHERE is_active = 1
            ORDER BY group_name ASC
            LIMIT %s OFFSET %s
        """, [limit, offset])
        
        results = []
        for row in cur.fetchall():
            results.append(UserGroup(
                id=row[0],
                group_hash=row[1],
                group_name=row[2],
                group_description=row[3],
                created_at=row[4],
                updated_at=row[5],
                is_active=bool(row[6])
            ))
        
        return results


def update_user_group(group_id: int, group_name: str = None, group_description: str = None) -> Optional[UserGroup]:
    """Update user group information"""
    if not group_name and group_description is None:
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
        
        update_fields.append("updated_at = NOW()")
        update_values.append(group_id)
        
        query = f"""
            UPDATE user_groups 
            SET {', '.join(update_fields)}
            WHERE id = %s AND is_active = 1
        """
        
        cur.execute(query, update_values)
        
        if cur.rowcount > 0:
            con.commit()
            return get_user_group_by_id(group_id)
        else:
            return None


def delete_user_group(group_id: int, deleted_by: int = None) -> bool:
    """Soft delete a user group and all related relationships"""
    with get_connection() as con:
        cur = con.cursor()
        
        try:
            # Start transaction
            con.begin()
            
            # Soft delete the user group
            cur.execute("""
                UPDATE user_groups 
                SET is_active = 0, updated_at = NOW()
                WHERE id = %s AND is_active = 1
            """, [group_id])
            
            if cur.rowcount == 0:
                con.rollback()
                return False
            
            # Soft delete all user memberships
            cur.execute("""
                UPDATE user_group_members 
                SET is_active = 0, removed_at = NOW(), removed_by = %s
                WHERE user_group_id = %s AND is_active = 1
            """, [deleted_by, group_id])
            
            # Soft delete all project access grants
            cur.execute("""
                UPDATE user_group_projects 
                SET is_active = 0, revoked_at = NOW(), revoked_by = %s
                WHERE user_group_id = %s AND is_active = 1
            """, [deleted_by, group_id])
            
            con.commit()
            return True
            
        except Exception as e:
            con.rollback()
            print(f"Error deleting user group: {e}")
            return False


# =================== USER GROUP MEMBERSHIP ===================

def assign_user_to_group(user_id: int, user_group_id: int, assigned_by: int = None) -> Optional[UserGroupMember]:
    """Assign a user to a user group"""
    with get_connection() as con:
        cur = con.cursor()
        
        try:
            cur.execute("""
                INSERT INTO user_group_members (user_id, user_group_id, assigned_at, assigned_by)
                VALUES (%s, %s, NOW(), %s)
            """, [user_id, user_group_id, assigned_by])
            
            member_id = con.insert_id()
            con.commit()
            
            return UserGroupMember(
                id=member_id,
                user_id=user_id,
                user_group_id=user_group_id,
                assigned_at=datetime.now(),
                assigned_by=assigned_by,
                is_active=True
            )
            
        except pymysql.IntegrityError:
            # User already in group, reactivate if needed
            cur.execute("""
                UPDATE user_group_members 
                SET is_active = 1, removed_at = NULL, removed_by = NULL, assigned_by = %s
                WHERE user_id = %s AND user_group_id = %s
            """, [assigned_by, user_id, user_group_id])
            
            if cur.rowcount > 0:
                con.commit()
                return get_user_group_membership(user_id, user_group_id)
            
            return None


def remove_user_from_group(user_id: int, user_group_id: int, removed_by: int = None) -> bool:
    """Remove a user from a user group"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            UPDATE user_group_members 
            SET is_active = 0, removed_at = NOW(), removed_by = %s
            WHERE user_id = %s AND user_group_id = %s AND is_active = 1
        """, [removed_by, user_id, user_group_id])
        
        success = cur.rowcount > 0
        if success:
            con.commit()
        return success


def get_user_group_membership(user_id: int, user_group_id: int) -> Optional[UserGroupMember]:
    """Get specific user group membership"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT id, user_id, user_group_id, assigned_at, assigned_by, removed_at, removed_by, is_active
            FROM user_group_members 
            WHERE user_id = %s AND user_group_id = %s AND is_active = 1
        """, [user_id, user_group_id])
        
        result = cur.fetchone()
        if result:
            return UserGroupMember(
                id=result[0],
                user_id=result[1],
                user_group_id=result[2],
                assigned_at=result[3],
                assigned_by=result[4],
                removed_at=result[5],
                removed_by=result[6],
                is_active=bool(result[7])
            )
    return None


def get_user_groups_for_user(user_id: int) -> List[UserGroup]:
    """Get all user groups a user belongs to"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT ug.id, ug.group_hash, ug.group_name, ug.group_description, 
                   ug.created_at, ug.updated_at, ug.is_active
            FROM user_groups ug
            INNER JOIN user_group_members ugm ON ug.id = ugm.user_group_id
            WHERE ugm.user_id = %s AND ug.is_active = 1 AND ugm.is_active = 1
            ORDER BY ug.group_name ASC
        """, [user_id])
        
        groups = []
        for row in cur.fetchall():
            groups.append(UserGroup(
                id=row[0],
                group_hash=row[1],
                group_name=row[2],
                group_description=row[3],
                created_at=row[4],
                updated_at=row[5],
                is_active=bool(row[6])
            ))
        
        return groups


def get_users_in_group(user_group_id: int) -> List[User]:
    """Get all users in a user group"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT u.id, u.user_hash, u.username, u.email, u.password_hash, 
                   u.created_at, u.updated_at, u.is_active
            FROM users u
            INNER JOIN user_group_members ugm ON u.id = ugm.user_id
            WHERE ugm.user_group_id = %s AND u.is_active = 1 AND ugm.is_active = 1
            ORDER BY u.username ASC
        """, [user_group_id])
        
        users = []
        for row in cur.fetchall():
            users.append(User(
                id=row[0],
                user_hash=row[1],
                username=row[2],
                email=row[3],
                password_hash=row[4],
                created_at=row[5],
                updated_at=row[6],
                is_active=bool(row[7])
            ))
        
        return users


# =================== PROJECT ACCESS MANAGEMENT ===================

def grant_group_project_access(user_group_id: int, project_id: int, granted_by: int = None) -> Optional[UserGroupProject]:
    """Grant a user group access to a project"""
    with get_connection() as con:
        cur = con.cursor()
        
        try:
            cur.execute("""
                INSERT INTO user_group_projects (user_group_id, project_id, granted_at, granted_by)
                VALUES (%s, %s, NOW(), %s)
            """, [user_group_id, project_id, granted_by])
            
            access_id = con.insert_id()
            con.commit()
            
            return UserGroupProject(
                id=access_id,
                user_group_id=user_group_id,
                project_id=project_id,
                granted_at=datetime.now(),
                granted_by=granted_by,
                is_active=True
            )
            
        except pymysql.IntegrityError:
            # Access already exists, reactivate if needed
            cur.execute("""
                UPDATE user_group_projects 
                SET is_active = 1, revoked_at = NULL, revoked_by = NULL, granted_by = %s
                WHERE user_group_id = %s AND project_id = %s
            """, [granted_by, user_group_id, project_id])
            
            if cur.rowcount > 0:
                con.commit()
                return get_group_project_access(user_group_id, project_id)
            
            return None


def revoke_group_project_access(user_group_id: int, project_id: int, revoked_by: int = None) -> bool:
    """Revoke a user group's access to a project"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            UPDATE user_group_projects 
            SET is_active = 0, revoked_at = NOW(), revoked_by = %s
            WHERE user_group_id = %s AND project_id = %s AND is_active = 1
        """, [revoked_by, user_group_id, project_id])
        
        success = cur.rowcount > 0
        if success:
            con.commit()
        return success


def get_group_project_access(user_group_id: int, project_id: int) -> Optional[UserGroupProject]:
    """Get specific group project access"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT id, user_group_id, project_id, granted_at, granted_by, revoked_at, revoked_by, is_active
            FROM user_group_projects 
            WHERE user_group_id = %s AND project_id = %s AND is_active = 1
        """, [user_group_id, project_id])
        
        result = cur.fetchone()
        if result:
            return UserGroupProject(
                id=result[0],
                user_group_id=result[1],
                project_id=result[2],
                granted_at=result[3],
                granted_by=result[4],
                revoked_at=result[5],
                revoked_by=result[6],
                is_active=bool(result[7])
            )
    return None


def get_projects_for_user_group(user_group_id: int) -> List[Tuple[int, str, str]]:
    """Get all projects accessible by a user group"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT p.id, p.project_hash, p.project_name, p.project_description
            FROM projects p
            INNER JOIN user_group_projects ugp ON p.id = ugp.project_id
            WHERE ugp.user_group_id = %s AND p.is_active = 1 AND ugp.is_active = 1
            ORDER BY p.project_name ASC
        """, [user_group_id])
        
        return cur.fetchall()


def get_user_groups_for_project(project_id: int) -> List[UserGroup]:
    """Get all user groups that have access to a project"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT ug.id, ug.group_hash, ug.group_name, ug.group_description, 
                   ug.created_at, ug.updated_at, ug.is_active
            FROM user_groups ug
            INNER JOIN user_group_projects ugp ON ug.id = ugp.user_group_id
            WHERE ugp.project_id = %s AND ug.is_active = 1 AND ugp.is_active = 1
            ORDER BY ug.group_name ASC
        """, [project_id])
        
        groups = []
        for row in cur.fetchall():
            groups.append(UserGroup(
                id=row[0],
                group_hash=row[1],
                group_name=row[2],
                group_description=row[3],
                created_at=row[4],
                updated_at=row[5],
                is_active=bool(row[6])
            ))
        
        return groups


# =================== UTILITIES ===================

def get_user_accessible_projects(user_id: int) -> List[ProjectSummary]:
    """Get all projects accessible by a user through their group memberships"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT DISTINCT p.project_hash, p.project_name, p.project_description,
                   pg.group_name as project_group_name, pg.permissions
            FROM users u
            JOIN user_group_members ugm ON u.id = ugm.user_id AND ugm.is_active = 1
            JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = 1
            JOIN user_group_projects ugp ON ug.id = ugp.user_group_id AND ugp.is_active = 1
            JOIN projects p ON ugp.project_id = p.id AND p.is_active = 1
            JOIN project_group_members pgm ON p.id = pgm.project_id AND pgm.is_active = 1
            JOIN project_groups pg ON pgm.project_group_id = pg.id AND pg.is_active = 1
            WHERE u.id = %s AND u.is_active = 1
            ORDER BY p.project_name ASC
        """, [user_id])
        
        projects = []
        for row in cur.fetchall():
            permissions = json.loads(row[4]) if row[4] else []
            projects.append(ProjectSummary(
                project_hash=row[0],
                project_name=row[1],
                project_description=row[2],
                project_group_name=row[3],
                permissions=permissions
            ))
        
        return projects


def count_user_groups() -> int:
    """Count total number of active user groups"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM user_groups WHERE is_active = 1")
        return cur.fetchone()[0] 