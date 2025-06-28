"""
Enhanced Multi-Project Authentication - User Database Operations

This module handles all user-related database operations including:
- User management (create, read, update, delete)
- User authentication and credentials
- User-project access management
- User session management
- User group memberships
"""

import json
import secrets
import os
from typing import List, Optional, Tuple
from datetime import datetime

import pymysql
import hashlib
import redis

from src.Util.Models import (
    User, Project, UserProject, UserGroup, EnhancedUserLogin
)

# Database connection settings
ip = "192.168.1.90"
# ip = "127.0.0.1"

connectionDB = {
    "host": ip,
    "user": "root",
    "password": os.environ.get("DB_MYSQL_PASSWORD"),
    "database": "magic_auth_enhanced"
}

client = redis.StrictRedis(host=ip,
                           port=6379,
                           db=0,
                           password=os.environ.get("DB_REDIS_PASSWORD"))


def get_connection():
    """Get database connection"""
    return pymysql.connect(**connectionDB)


# =================== USER MANAGEMENT ===================

def create_user(username: str, password: str, email: str = None) -> User:
    """Create a new global user account"""
    password_hash = hashlib.sha256(password.encode()).hexdigest().upper()
    user_hash = secrets.token_hex(32).upper()
    
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO users (user_hash, username, email, password_hash, created_at)
            VALUES (%s, %s, %s, %s, NOW())
        """, [user_hash, username, email, password_hash])
        
        user_id = con.insert_id()
        con.commit()
        
        return User(
            id=user_id,
            user_hash=user_hash,
            username=username,
            email=email,
            password_hash=password_hash,
            created_at=datetime.now(),
            is_active=True
        )


def get_user_by_credentials(username: str, password: str) -> Optional[User]:
    """Get user by username/email and password"""
    password_hash = hashlib.sha256(password.encode()).hexdigest().upper()
    
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT id, user_hash, username, email, password_hash, created_at, is_active
            FROM users 
            WHERE (username = %s OR email = %s) AND password_hash = %s AND is_active = 1
        """, [username, username, password_hash])
        
        result = cur.fetchone()
        if result:
            return User(
                id=result[0],
                user_hash=result[1],
                username=result[2],
                email=result[3],
                password_hash=result[4],
                created_at=result[5],
                is_active=bool(result[6])
            )
    return None


def get_user_by_id(user_id: int) -> Optional[User]:
    """Get user by user ID"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT id, user_hash, username, email, password_hash, created_at, is_active
            FROM users 
            WHERE id = %s AND is_active = 1
        """, [user_id])
        
        result = cur.fetchone()
        if result:
            return User(
                id=result[0],
                user_hash=result[1],
                username=result[2],
                email=result[3],
                password_hash=result[4],
                created_at=result[5],
                is_active=bool(result[6])
            )
    return None


def get_user_by_hash(user_hash: str) -> Optional[User]:
    """Get user by user hash"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT id, user_hash, username, email, password_hash, created_at, is_active
            FROM users 
            WHERE user_hash = %s AND is_active = 1
        """, [user_hash])
        
        result = cur.fetchone()
        if result:
            return User(
                id=result[0],
                user_hash=result[1],
                username=result[2],
                email=result[3],
                password_hash=result[4],
                created_at=result[5],
                is_active=bool(result[6])
            )
    return None


def check_username_email_available(username_or_email: str) -> bool:
    """Check if username or email is available globally"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM users 
            WHERE (username = %s OR email = %s) AND is_active = 1
        """, [username_or_email, username_or_email])
        
        return cur.fetchone()[0] == 0


def update_user(user_id: int, username: str = None, email: str = None, password: str = None) -> Optional[User]:
    """Update user information"""
    if not username and not email and not password:
        return None
    
    with get_connection() as con:
        cur = con.cursor()
        
        # Build dynamic update query
        update_fields = []
        update_values = []
        
        if username:
            update_fields.append("username = %s")
            update_values.append(username)
        
        if email is not None:
            update_fields.append("email = %s")
            update_values.append(email)
        
        if password:
            password_hash = hashlib.sha256(password.encode()).hexdigest().upper()
            update_fields.append("password_hash = %s")
            update_values.append(password_hash)
        
        update_fields.append("updated_at = NOW()")
        update_values.append(user_id)
        
        query = f"""
            UPDATE users 
            SET {', '.join(update_fields)}
            WHERE id = %s AND is_active = 1
        """
        
        cur.execute(query, update_values)
        
        if cur.rowcount > 0:
            con.commit()
            return get_user_by_id(user_id)
        else:
            return None


def delete_user(user_id: int) -> bool:
    """Soft delete a user"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            UPDATE users 
            SET is_active = 0, updated_at = NOW()
            WHERE id = %s AND is_active = 1
        """, [user_id])
        
        success = cur.rowcount > 0
        if success:
            con.commit()
        return success


def list_users(limit: int = 100, offset: int = 0) -> List[User]:
    """List all active users with pagination"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT id, user_hash, username, email, password_hash, created_at, is_active
            FROM users 
            WHERE is_active = 1
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, [limit, offset])
        
        results = []
        for row in cur.fetchall():
            results.append(User(
                id=row[0],
                user_hash=row[1],
                username=row[2],
                email=row[3],
                password_hash=row[4],
                created_at=row[5],
                is_active=bool(row[6])
            ))
        
        return results


def count_users() -> int:
    """Count total number of active users"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
        return cur.fetchone()[0]


def search_users(search_term: str, limit: int = 50) -> List[User]:
    """Search users by username or email"""
    with get_connection() as con:
        cur = con.cursor()
        search_pattern = f"%{search_term}%"
        
        cur.execute("""
            SELECT id, user_hash, username, email, password_hash, created_at, is_active
            FROM users 
            WHERE is_active = 1 
            AND (username LIKE %s OR email LIKE %s)
            ORDER BY username ASC
            LIMIT %s
        """, [search_pattern, search_pattern, limit])
        
        results = []
        for row in cur.fetchall():
            results.append(User(
                id=row[0],
                user_hash=row[1],
                username=row[2],
                email=row[3],
                password_hash=row[4],
                created_at=row[5],
                is_active=bool(row[6])
            ))
        
        return results


# =================== USER-PROJECT ACCESS MANAGEMENT ===================

def grant_user_project_access(user_id: int, project_id: int, granted_by: int = None) -> UserProject:
    """Grant a user access to a project"""
    user_project_hash = secrets.token_hex(32).upper()
    
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO user_projects (user_id, project_id, user_project_hash, granted_at, granted_by)
            VALUES (%s, %s, %s, NOW(), %s)
        """, [user_id, project_id, user_project_hash, granted_by])
        
        user_project_id = con.insert_id()
        con.commit()
        
        # Assign to default 'user' group
        assign_user_to_default_group(user_project_id, project_id)
        
        return UserProject(
            id=user_project_id,
            user_id=user_id,
            project_id=project_id,
            user_project_hash=user_project_hash,
            granted_at=datetime.now(),
            granted_by=granted_by,
            is_active=True
        )


def get_user_project_access(user_id: int, project_id: int) -> Optional[UserProject]:
    """Get user's access to a specific project"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT id, user_id, project_id, user_project_hash, granted_at, granted_by, is_active
            FROM user_projects 
            WHERE user_id = %s AND project_id = %s AND is_active = 1
        """, [user_id, project_id])
        
        result = cur.fetchone()
        if result:
            return UserProject(
                id=result[0],
                user_id=result[1],
                project_id=result[2],
                user_project_hash=result[3],
                granted_at=result[4],
                granted_by=result[5],
                is_active=bool(result[6])
            )
    return None


def get_user_projects(user_id: int) -> List[Tuple[Project, UserProject]]:
    """Get all projects a user has access to"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT p.id, p.project_hash, p.project_name, p.project_description, p.project_created, p.is_active,
                   up.id, up.user_id, up.project_id, up.user_project_hash, up.granted_at, up.granted_by, up.is_active
            FROM projects p
            INNER JOIN user_projects up ON p.id = up.project_id
            WHERE up.user_id = %s AND p.is_active = 1 AND up.is_active = 1
        """, [user_id])
        
        results = []
        for row in cur.fetchall():
            project = Project(
                id=row[0], project_hash=row[1], project_name=row[2],
                project_description=row[3], project_created=row[4], is_active=bool(row[5])
            )
            user_project = UserProject(
                id=row[6], user_id=row[7], project_id=row[8],
                user_project_hash=row[9], granted_at=row[10], granted_by=row[11], is_active=bool(row[12])
            )
            results.append((project, user_project))
        
        return results


def revoke_user_project_access(user_id: int, project_id: int, revoked_by: int = None) -> bool:
    """Revoke user's access to a project"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            UPDATE user_projects 
            SET is_active = 0, revoked_at = NOW(), revoked_by = %s
            WHERE user_id = %s AND project_id = %s AND is_active = 1
        """, [revoked_by, user_id, project_id])
        
        success = cur.rowcount > 0
        if success:
            con.commit()
        return success


def assign_user_to_default_group(user_project_id: int, project_id: int):
    """Assign user to default 'user' group in a project"""
    with get_connection() as con:
        cur = con.cursor()
        # Get default 'user' group ID
        cur.execute("""
            SELECT id FROM user_groups 
            WHERE project_id = %s AND group_name = 'user' AND is_active = 1
        """, [project_id])
        
        group_result = cur.fetchone()
        if group_result:
            group_id = group_result[0]
            cur.execute("""
                INSERT INTO user_project_groups (user_project_id, group_id, assigned_at)
                VALUES (%s, %s, NOW())
            """, [user_project_id, group_id])
            con.commit()


# =================== USER GROUP MANAGEMENT ===================

def get_user_groups_in_project(user_project_id: int) -> List[UserGroup]:
    """Get all groups a user belongs to in a project"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT ug.id, ug.project_id, ug.group_name, ug.group_description, ug.permissions, ug.created_at, ug.is_active
            FROM user_groups ug
            INNER JOIN user_project_groups upg ON ug.id = upg.group_id
            WHERE upg.user_project_id = %s AND ug.is_active = 1 AND upg.is_active = 1
        """, [user_project_id])
        
        groups = []
        for row in cur.fetchall():
            groups.append(UserGroup(
                id=row[0], project_id=row[1], group_name=row[2],
                group_description=row[3], permissions=row[4], created_at=row[5], is_active=bool(row[6])
            ))
        
        return groups


def get_user_permissions_in_project(user_project_id: int) -> List[str]:
    """Get all permissions a user has in a project"""
    groups = get_user_groups_in_project(user_project_id)
    permissions = set()
    
    for group in groups:
        if group.permissions:
            group_permissions = json.loads(group.permissions)
            permissions.update(group_permissions)
    
    return list(permissions)


def assign_user_to_group(user_project_id: int, group_id: int, assigned_by: int = None) -> bool:
    """Assign user to a group in a project"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO user_project_groups (user_project_id, group_id, assigned_at, assigned_by)
            VALUES (%s, %s, NOW(), %s)
        """, [user_project_id, group_id, assigned_by])
        
        success = cur.rowcount > 0
        if success:
            con.commit()
        return success


def remove_user_from_group(user_project_id: int, group_id: int, removed_by: int = None) -> bool:
    """Remove user from a group in a project"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            UPDATE user_project_groups 
            SET is_active = 0, removed_at = NOW(), removed_by = %s
            WHERE user_project_id = %s AND group_id = %s AND is_active = 1
        """, [removed_by, user_project_id, group_id])
        
        success = cur.rowcount > 0
        if success:
            con.commit()
        return success


# =================== USER SESSION MANAGEMENT ===================

def get_session_data(session_token: str) -> Optional[dict]:
    """Get session data from Redis"""
    session_data = client.get(f"session:{session_token}")
    if session_data:
        return json.loads(session_data)
    return None


def create_session(user_id: int, project_id: int, user_project_id: int, session_length: int = 259200) -> str:
    """Create a new session and store in Redis"""
    session_token = secrets.token_hex(32).upper()
    
    # Get user and project data
    user = get_user_by_id(user_id)
    if not user:
        return None
    
    # Import here to avoid circular imports
    from src.Util.db.db_projects import get_project_by_id
    project = get_project_by_id(project_id)
    if not project:
        return None
    
    user_project = get_user_project_access(user_id, project_id)
    if not user_project:
        return None
    
    # Get user's groups and permissions
    groups = get_user_groups_in_project(user_project_id)
    permissions = get_user_permissions_in_project(user_project_id)
    
    # Store session data in Redis
    session_data = {
        'user_id': user.id,
        'user_hash': user.user_hash,
        'project_id': project.id,
        'project_hash': project.project_hash,
        'user_project_id': user_project.id,
        'user_project_hash': user_project.user_project_hash,
        'groups': [g.group_name for g in groups],
        'permissions': permissions
    }
    
    client.set(f"session:{session_token}", json.dumps(session_data), ex=session_length)
    
    return session_token


def invalidate_session(session_token: str) -> bool:
    """Invalidate a session by removing it from Redis"""
    try:
        result = client.delete(f"session:{session_token}")
        return result > 0
    except Exception:
        return False


def validate_session(session_token: str) -> Optional[EnhancedUserLogin]:
    """Validate a session token and return user data"""
    session_data = get_session_data(session_token)
    if not session_data:
        return None
    
    # Get fresh project data
    from src.Util.db.db_projects import get_project_by_hash
    project = get_project_by_hash(session_data['project_hash'])
    if not project:
        return None
    
    # Get fresh user groups and permissions
    groups = get_user_groups_in_project(session_data['user_project_id'])
    permissions = get_user_permissions_in_project(session_data['user_project_id'])
    
    # Get available projects
    available_projects = [proj for proj, _ in get_user_projects(session_data['user_id'])]
    
    return EnhancedUserLogin(
        user_hash=session_data['user_hash'],
        project_hash=session_data['project_hash'],
        project_name=project.project_name,
        user_project_hash=session_data['user_project_hash'],
        session_token=session_token,
        session_length=0,  # We don't track remaining time
        user_id=session_data['user_id'],
        project_id=session_data['project_id'],
        user_project_id=session_data['user_project_id'],
        groups=[g.group_name for g in groups],
        permissions=permissions,
        available_projects=available_projects
    ) 