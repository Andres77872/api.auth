"""
Enhanced Multi-Project Authentication - Project Database Operations

This module handles all project-related database operations including:
- Project management (create, read, update, delete)
- Project search and statistics
- Project group management
- Default group creation
"""

import json
import secrets
import os
from typing import List, Optional
from datetime import datetime

import pymysql

from src.Util.Models import Project, LegacyUserGroup as UserGroup

# Database connection settings
ip = "192.168.1.90"
# ip = "127.0.0.1"

connectionDB = {
    "host": ip,
    "user": "root",
    "password": os.environ.get("DB_MYSQL_PASSWORD"),
    "database": "magic_auth_enhanced"
}


def get_connection():
    """Get database connection"""
    return pymysql.connect(**connectionDB)


# =================== PROJECT MANAGEMENT ===================

def create_project(project_name: str, project_description: str = None) -> Project:
    """Create a new project/application"""
    project_hash = secrets.token_hex(32).upper()
    
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO projects (project_hash, project_name, project_description, project_created)
            VALUES (%s, %s, %s, NOW())
        """, [project_hash, project_name, project_description])
        
        project_id = con.insert_id()
        con.commit()
        
        # Create default user group for this project
        create_default_groups(project_id)
        
        return Project(
            id=project_id,
            project_hash=project_hash,
            project_name=project_name,
            project_description=project_description,
            project_created=datetime.now(),
            is_active=True
        )


def get_project_by_hash(project_hash: str) -> Optional[Project]:
    """Get project by project hash"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT id, project_hash, project_name, project_description, project_created, is_active
            FROM projects 
            WHERE project_hash = %s AND is_active = 1
        """, [project_hash])
        
        result = cur.fetchone()
        if result:
            return Project(
                id=result[0],
                project_hash=result[1],
                project_name=result[2],
                project_description=result[3],
                project_created=result[4],
                is_active=bool(result[5])
            )
    return None


def get_project_by_id(project_id: int) -> Optional[Project]:
    """Get project by project ID"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT id, project_hash, project_name, project_description, project_created, is_active
            FROM projects 
            WHERE id = %s AND is_active = 1
        """, [project_id])
        
        result = cur.fetchone()
        if result:
            return Project(
                id=result[0],
                project_hash=result[1],
                project_name=result[2],
                project_description=result[3],
                project_created=result[4],
                is_active=bool(result[5])
            )
    return None


def list_all_projects(limit: int = 100, offset: int = 0) -> List[Project]:
    """List all active projects with pagination"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT id, project_hash, project_name, project_description, project_created, is_active
            FROM projects 
            WHERE is_active = 1
            ORDER BY project_created DESC
            LIMIT %s OFFSET %s
        """, [limit, offset])
        
        results = []
        for row in cur.fetchall():
            results.append(Project(
                id=row[0],
                project_hash=row[1],
                project_name=row[2],
                project_description=row[3],
                project_created=row[4],
                is_active=bool(row[5])
            ))
        
        return results


def count_projects() -> int:
    """Count total number of active projects"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM projects WHERE is_active = 1")
        return cur.fetchone()[0]


def update_project(project_id: int, project_name: str = None, project_description: str = None, updated_by: int = None) -> Optional[Project]:
    """Update project information"""
    if not project_name and project_description is None:
        return None
    
    with get_connection() as con:
        cur = con.cursor()
        
        # Build dynamic update query
        update_fields = []
        update_values = []
        
        if project_name:
            update_fields.append("project_name = %s")
            update_values.append(project_name)
        
        if project_description is not None:
            update_fields.append("project_description = %s")
            update_values.append(project_description)
        
        update_fields.append("updated_at = NOW()")
        update_values.append(project_id)
        
        query = f"""
            UPDATE projects 
            SET {', '.join(update_fields)}
            WHERE id = %s AND is_active = 1
        """
        
        cur.execute(query, update_values)
        
        if cur.rowcount > 0:
            con.commit()
            return get_project_by_id(project_id)
        else:
            return None


def delete_project(project_id: int, deleted_by: int = None) -> bool:
    """Soft delete a project and all related data"""
    with get_connection() as con:
        cur = con.cursor()
        
        try:
            # Start transaction
            con.begin()
            
            # Soft delete the project
            cur.execute("""
                UPDATE projects 
                SET is_active = 0, updated_at = NOW()
                WHERE id = %s AND is_active = 1
            """, [project_id])
            
            if cur.rowcount == 0:
                con.rollback()
                return False
            
            # Soft delete all user-project relationships
            cur.execute("""
                UPDATE user_projects 
                SET is_active = 0, revoked_at = NOW(), revoked_by = %s
                WHERE project_id = %s AND is_active = 1
            """, [deleted_by, project_id])
            
            # Soft delete all project groups
            cur.execute("""
                UPDATE user_groups 
                SET is_active = 0, updated_at = NOW()
                WHERE project_id = %s AND is_active = 1
            """, [project_id])
            
            # Soft delete all user-project-group relationships for this project
            cur.execute("""
                UPDATE user_project_groups upg
                INNER JOIN user_projects up ON upg.user_project_id = up.id
                SET upg.is_active = 0, upg.removed_at = NOW(), upg.removed_by = %s
                WHERE up.project_id = %s AND upg.is_active = 1
            """, [deleted_by, project_id])
            
            # Soft delete all sessions for this project
            cur.execute("""
                UPDATE user_sessions us
                INNER JOIN user_projects up ON us.user_project_id = up.id
                SET us.is_active = 0
                WHERE up.project_id = %s AND us.is_active = 1
            """, [project_id])
            
            con.commit()
            return True
            
        except Exception as e:
            con.rollback()
            print(f"Error deleting project: {e}")
            return False


def search_projects(search_term: str, limit: int = 50) -> List[Project]:
    """Search projects by name or description"""
    with get_connection() as con:
        cur = con.cursor()
        search_pattern = f"%{search_term}%"
        
        cur.execute("""
            SELECT id, project_hash, project_name, project_description, project_created, is_active
            FROM projects 
            WHERE is_active = 1 
            AND (project_name LIKE %s OR project_description LIKE %s)
            ORDER BY project_name ASC
            LIMIT %s
        """, [search_pattern, search_pattern, limit])
        
        results = []
        for row in cur.fetchall():
            results.append(Project(
                id=row[0],
                project_hash=row[1],
                project_name=row[2],
                project_description=row[3],
                project_created=row[4],
                is_active=bool(row[5])
            ))
        
        return results


def get_project_stats(project_id: int) -> dict:
    """Get statistics for a project"""
    with get_connection() as con:
        cur = con.cursor()
        
        # Count total users with access
        cur.execute("""
            SELECT COUNT(*) FROM user_projects 
            WHERE project_id = %s AND is_active = 1
        """, [project_id])
        total_users = cur.fetchone()[0]
        
        # Count active sessions
        cur.execute("""
            SELECT COUNT(*) FROM user_sessions us
            INNER JOIN user_projects up ON us.user_project_id = up.id
            WHERE up.project_id = %s AND us.is_active = 1 AND us.expires_at > NOW()
        """, [project_id])
        active_sessions = cur.fetchone()[0]
        
        # Count groups
        cur.execute("""
            SELECT COUNT(*) FROM user_groups 
            WHERE project_id = %s AND is_active = 1
        """, [project_id])
        total_groups = cur.fetchone()[0]
        
        # Get group distribution
        cur.execute("""
            SELECT ug.group_name, COUNT(upg.id) as user_count
            FROM user_groups ug
            LEFT JOIN user_project_groups upg ON ug.id = upg.group_id AND upg.is_active = 1
            WHERE ug.project_id = %s AND ug.is_active = 1
            GROUP BY ug.id, ug.group_name
            ORDER BY user_count DESC
        """, [project_id])
        
        group_distribution = {}
        for row in cur.fetchall():
            group_distribution[row[0]] = row[1]
        
        return {
            'total_users': total_users,
            'active_sessions': active_sessions,
            'total_groups': total_groups,
            'group_distribution': group_distribution
        }


# =================== PROJECT GROUP MANAGEMENT ===================

def create_default_groups(project_id: int):
    """Create default groups for a new project"""
    default_groups = [
        ("admin", "Project administrators", '["admin", "read", "write", "delete", "manage_users"]'),
        ("user", "Regular users", '["read", "write"]'),
        ("readonly", "Read-only users", '["read"]')
    ]
    
    with get_connection() as con:
        cur = con.cursor()
        for group_name, description, permissions in default_groups:
            cur.execute("""
                INSERT INTO user_groups (project_id, group_name, group_description, permissions, created_at)
                VALUES (%s, %s, %s, %s, NOW())
            """, [project_id, group_name, description, permissions])
        con.commit()


def get_project_groups(project_id: int) -> List[UserGroup]:
    """Get all groups for a project"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT id, project_id, group_name, group_description, permissions, created_at, is_active
            FROM user_groups
            WHERE project_id = %s AND is_active = 1
            ORDER BY group_name ASC
        """, [project_id])
        
        groups = []
        for row in cur.fetchall():
            groups.append(UserGroup(
                id=row[0],
                project_id=row[1],
                group_name=row[2],
                group_description=row[3],
                permissions=row[4],
                created_at=row[5],
                is_active=bool(row[6])
            ))
        
        return groups


def create_project_group(project_id: int, group_name: str, group_description: str = None, permissions: List[str] = None) -> Optional[UserGroup]:
    """Create a new group for a project"""
    permissions_json = json.dumps(permissions) if permissions else '[]'
    
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO user_groups (project_id, group_name, group_description, permissions, created_at)
            VALUES (%s, %s, %s, %s, NOW())
        """, [project_id, group_name, group_description, permissions_json])
        
        group_id = con.insert_id()
        con.commit()
        
        return UserGroup(
            id=group_id,
            project_id=project_id,
            group_name=group_name,
            group_description=group_description,
            permissions=permissions_json,
            created_at=datetime.now(),
            is_active=True
        )


def update_project_group(group_id: int, group_name: str = None, group_description: str = None, permissions: List[str] = None) -> Optional[UserGroup]:
    """Update a project group"""
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
            UPDATE user_groups 
            SET {', '.join(update_fields)}
            WHERE id = %s AND is_active = 1
        """
        
        cur.execute(query, update_values)
        
        if cur.rowcount > 0:
            con.commit()
            # Get updated group
            cur.execute("""
                SELECT id, project_id, group_name, group_description, permissions, created_at, is_active
                FROM user_groups
                WHERE id = %s
            """, [group_id])
            
            result = cur.fetchone()
            if result:
                return UserGroup(
                    id=result[0],
                    project_id=result[1],
                    group_name=result[2],
                    group_description=result[3],
                    permissions=result[4],
                    created_at=result[5],
                    is_active=bool(result[6])
                )
        
        return None


def delete_project_group(group_id: int) -> bool:
    """Soft delete a project group"""
    with get_connection() as con:
        cur = con.cursor()
        
        try:
            # Start transaction
            con.begin()
            
            # Soft delete the group
            cur.execute("""
                UPDATE user_groups 
                SET is_active = 0, updated_at = NOW()
                WHERE id = %s AND is_active = 1
            """, [group_id])
            
            if cur.rowcount == 0:
                con.rollback()
                return False
            
            # Soft delete all user-group relationships
            cur.execute("""
                UPDATE user_project_groups 
                SET is_active = 0, removed_at = NOW()
                WHERE group_id = %s AND is_active = 1
            """, [group_id])
            
            con.commit()
            return True
            
        except Exception as e:
            con.rollback()
            print(f"Error deleting group: {e}")
            return False 