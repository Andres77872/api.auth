"""
Enhanced 3-Tier User Type Database Operations

This module handles all user-related database operations with support for
the 3-tier user type system:
- ROOT USERS: Super administrators with unrestricted global access
- ADMIN USERS: Project-specific administrators limited to assigned projects  
- CONSUMER USERS: End users with RBAC-based permissions through groups

Key features:
- User type-specific creation functions
- User type management and validation
- Enhanced authentication with user type checking
- Project assignment for admin users
- Legacy compatibility maintained
"""

import json
import secrets
import os
import uuid
from typing import List, Optional, Tuple
from datetime import datetime

import pymysql
import hashlib
import redis

from src.Util.Models import (
    User, Project, UserProject, LegacyUserGroup as UserGroup, EnhancedUserLogin
)
from src.Util.db_config import get_connection, redis_client as client


# =================== USER HASH UTILITY ===================

def generate_user_hash() -> str:
    """
    Generate a unique user hash with UUID4 and 'usr-' prefix.
    
    Returns:
        User hash in format: usr-{UUID4}
    """
    return f"usr-{uuid.uuid4()}"


def generate_user_project_hash() -> str:
    """
    Generate a unique user-project hash with UUID4 and 'uprj-' prefix.
    
    Returns:
        User-project hash in format: uprj-{UUID4}
    """
    return f"uprj-{uuid.uuid4()}"


# =================== USER TYPE MANAGEMENT ===================

def get_user_type(user_id: int) -> Optional[str]:
    """Get user type for a user"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT user_type FROM users 
            WHERE id = %s AND is_active = 1
        """, [user_id])
        
        result = cur.fetchone()
        return result[0] if result else None


def get_admin_assigned_project(user_id: int) -> Optional[int]:
    """Get assigned project for admin user"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT assigned_project_id FROM users 
            WHERE id = %s AND user_type = 'admin' AND is_active = 1
        """, [user_id])
        
        result = cur.fetchone()
        return result[0] if result else None


def update_user_type(user_id: int, new_user_type: str, assigned_project_id: int = None, updated_by: int = None) -> bool:
    """Update user type and project assignment"""
    with get_connection() as con:
        cur = con.cursor()
        
        # Validate user type and project assignment
        if new_user_type == 'admin' and not assigned_project_id:
            raise ValueError("Admin users must have an assigned project")
        elif new_user_type in ['root', 'consumer'] and assigned_project_id:
            assigned_project_id = None  # Clear project assignment for root/consumer users
        
        cur.execute("""
            UPDATE users 
            SET user_type = %s, assigned_project_id = %s, updated_at = NOW()
            WHERE id = %s AND is_active = 1
        """, [new_user_type, assigned_project_id, user_id])
        
        success = cur.rowcount > 0
        if success:
            con.commit()
        return success


def assign_admin_to_project(user_id: int, project_id: int, assigned_by: int = None) -> bool:
    """Assign admin user to a specific project"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            UPDATE users 
            SET assigned_project_id = %s, updated_at = NOW()
            WHERE id = %s AND user_type = 'admin' AND is_active = 1
        """, [project_id, user_id])
        
        success = cur.rowcount > 0
        if success:
            con.commit()
        return success


# =================== USER TYPE-SPECIFIC CREATION ===================

def create_root_user(username: str, password: str, email: str = None, created_by: int = None) -> User:
    """Create a root (super admin) user"""
    password_hash = hashlib.sha256(password.encode()).hexdigest().upper()
    user_hash = generate_user_hash()
    
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO users (user_hash, username, email, password_hash, user_type, assigned_project_id, created_by, created_at)
            VALUES (%s, %s, %s, %s, 'root', NULL, %s, NOW())
        """, [user_hash, username, email, password_hash, created_by])
        
        user_id = con.insert_id()
        con.commit()
        
        return User(
            id=user_id,
            user_hash=user_hash,
            username=username,
            email=email,
            password_hash=password_hash,
            user_type='root',
            assigned_project_id=None,
            created_at=datetime.now(),
            is_active=True
        )


def create_admin_user(username: str, password: str, email: str, assigned_project_id: int, created_by: int = None) -> User:
    """Create an admin user assigned to a specific project"""
    password_hash = hashlib.sha256(password.encode()).hexdigest().upper()
    user_hash = generate_user_hash()
    
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO users (user_hash, username, email, password_hash, user_type, assigned_project_id, created_by, created_at)
            VALUES (%s, %s, %s, %s, 'admin', %s, %s, NOW())
        """, [user_hash, username, email, password_hash, assigned_project_id, created_by])
        
        user_id = con.insert_id()
        con.commit()
        
        return User(
            id=user_id,
            user_hash=user_hash,
            username=username,
            email=email,
            password_hash=password_hash,
            user_type='admin',
            assigned_project_id=assigned_project_id,
            created_at=datetime.now(),
            is_active=True
        )


def create_consumer_user(username: str, password: str, email: str = None, created_by: int = None) -> User:
    """Create a consumer (end user) user"""
    password_hash = hashlib.sha256(password.encode()).hexdigest().upper()
    user_hash = generate_user_hash()
    
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO users (user_hash, username, email, password_hash, user_type, assigned_project_id, created_by, created_at)
            VALUES (%s, %s, %s, %s, 'consumer', NULL, %s, NOW())
        """, [user_hash, username, email, password_hash, created_by])
        
        user_id = con.insert_id()
        con.commit()
        
        return User(
            id=user_id,
            user_hash=user_hash,
            username=username,
            email=email,
            password_hash=password_hash,
            user_type='consumer',
            assigned_project_id=None,
            created_at=datetime.now(),
            is_active=True
        )


# =================== ENHANCED USER MANAGEMENT ===================

def create_user(username: str, password: str, email: str = None, user_type: str = "consumer", assigned_project_id: int = None) -> User:
    """Create a user with specified type (enhanced to support all user types)"""
    if user_type == "root":
        return create_root_user(username, password, email)
    elif user_type == "admin":
        if not assigned_project_id:
            raise ValueError("Admin users must have an assigned project")
        return create_admin_user(username, password, email, assigned_project_id)
    else:  # consumer (default)
        return create_consumer_user(username, password, email)


def get_user_by_credentials(username: str, password: str) -> Optional[User]:
    """Get user by username/email and password (enhanced with user type)"""
    password_hash = hashlib.sha256(password.encode()).hexdigest().upper()
    
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT id, user_hash, username, email, password_hash, user_type, assigned_project_id, created_at, is_active
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
                user_type=result[5],
                assigned_project_id=result[6],
                created_at=result[7],
                is_active=bool(result[8])
            )
    return None


def get_user_by_id(user_id: int) -> Optional[User]:
    """Get user by user ID (enhanced with user type)"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT id, user_hash, username, email, password_hash, user_type, assigned_project_id, created_at, is_active
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
                user_type=result[5],
                assigned_project_id=result[6],
                created_at=result[7],
                is_active=bool(result[8])
            )
    return None


def get_user_by_hash(user_hash: str) -> Optional[User]:
    """Get user by user hash (enhanced with user type)"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT id, user_hash, username, email, password_hash, user_type, assigned_project_id, created_at, is_active
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
                user_type=result[5],
                assigned_project_id=result[6],
                created_at=result[7],
                is_active=bool(result[8])
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


def update_user(user_id: int, username: str = None, email: str = None, password: str = None, user_type: str = None, assigned_project_id: int = None) -> Optional[User]:
    """Update user information (enhanced with user type support)"""
    if not any([username, email, password, user_type]):
        return None
    
    with get_connection() as con:
        cur = con.cursor()
        
        # Validate user type and project assignment
        if user_type == 'admin' and assigned_project_id is None:
            # Keep existing assignment for admin users if not specified
            existing_user = get_user_by_id(user_id)
            if existing_user and existing_user.user_type == 'admin':
                assigned_project_id = existing_user.assigned_project_id
            else:
                raise ValueError("Admin users must have an assigned project")
        elif user_type in ['root', 'consumer']:
            assigned_project_id = None  # Clear project assignment for root/consumer users
        
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
        
        if user_type:
            update_fields.append("user_type = %s")
            update_values.append(user_type)
            update_fields.append("assigned_project_id = %s")
            update_values.append(assigned_project_id)
        
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


def delete_user(user_id: int, deleted_by: int = None) -> bool:
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


def list_users(limit: int = 100, offset: int = 0, user_type: str = None, project_id: int = None) -> List[User]:
    """List all active users with filtering by user type and project"""
    with get_connection() as con:
        cur = con.cursor()
        
        query = """
            SELECT id, user_hash, username, email, password_hash, user_type, assigned_project_id, created_at, is_active
            FROM users 
            WHERE is_active = 1
        """
        params = []
        
        if user_type:
            query += " AND user_type = %s"
            params.append(user_type)
        
        if project_id:
            query += " AND (user_type = 'root' OR assigned_project_id = %s OR user_type = 'consumer')"
            params.append(project_id)
        
        query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        
        cur.execute(query, params)
        
        results = []
        for row in cur.fetchall():
            results.append(User(
                id=row[0],
                user_hash=row[1],
                username=row[2],
                email=row[3],
                password_hash=row[4],
                user_type=row[5],
                assigned_project_id=row[6],
                created_at=row[7],
                is_active=bool(row[8])
            ))
        
        return results


def count_users(user_type: str = None) -> int:
    """Count total number of active users by type"""
    with get_connection() as con:
        cur = con.cursor()
        
        if user_type:
            cur.execute("SELECT COUNT(*) FROM users WHERE is_active = 1 AND user_type = %s", [user_type])
        else:
            cur.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
        
        return cur.fetchone()[0]


def search_users(search_term: str, user_type: str = None, limit: int = 50) -> List[User]:
    """Search users by username or email with optional user type filter"""
    with get_connection() as con:
        cur = con.cursor()
        search_pattern = f"%{search_term}%"
        
        query = """
            SELECT id, user_hash, username, email, password_hash, user_type, assigned_project_id, created_at, is_active
            FROM users 
            WHERE is_active = 1 
            AND (username LIKE %s OR email LIKE %s)
        """
        params = [search_pattern, search_pattern]
        
        if user_type:
            query += " AND user_type = %s"
            params.append(user_type)
        
        query += " ORDER BY username ASC LIMIT %s"
        params.append(limit)
        
        cur.execute(query, params)
        
        results = []
        for row in cur.fetchall():
            results.append(User(
                id=row[0],
                user_hash=row[1],
                username=row[2],
                email=row[3],
                password_hash=row[4],
                user_type=row[5],
                assigned_project_id=row[6],
                created_at=row[7],
                is_active=bool(row[8])
            ))
        
        return results


# =================== USER-PROJECT ACCESS MANAGEMENT (Consumer Users) ===================

def grant_user_project_access(user_id: int, project_id: int, granted_by: int = None) -> UserProject:
    """Grant a consumer user access to a project"""
    user_project_hash = generate_user_project_hash()
    
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO user_projects (user_id, project_id, user_project_hash, granted_at, granted_by)
            VALUES (%s, %s, %s, NOW(), %s)
        """, [user_id, project_id, user_project_hash, granted_by])
        
        user_project_id = con.insert_id()
        con.commit()
        
        # Assign to default 'user' group for consumer users
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
    """Get consumer user's access to a specific project"""
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
    """Get all projects a consumer user has access to"""
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
    """Revoke consumer user's access to a project"""
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
    """Assign consumer user to default 'user' group in a project"""
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


# =================== USER GROUP MANAGEMENT (Consumer Users) ===================

def get_user_groups_in_project(user_project_id: int) -> List[UserGroup]:
    """Get all groups a consumer user belongs to in a project"""
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


def get_user_permissions_in_project(user_id: int, project_id: int) -> List[str]:
    """Get all permissions a consumer user has in a project"""
    # For consumer users, use the existing RBAC system
    user_project = get_user_project_access(user_id, project_id)
    if not user_project:
        return []
    
    groups = get_user_groups_in_project(user_project.id)
    permissions = set()
    
    for group in groups:
        if group.permissions:
            group_permissions = json.loads(group.permissions)
            permissions.update(group_permissions)
    
    return list(permissions)


def assign_user_to_group(user_project_id: int, group_id: int, assigned_by: int = None) -> bool:
    """Assign consumer user to a group in a project"""
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
    """Remove consumer user from a group in a project"""
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


# =================== USER SESSION MANAGEMENT WITH USER TYPES ===================

def get_session_data(session_token: str) -> Optional[dict]:
    """Get session data from Redis"""
    session_data = client.get(f"session:{session_token}")
    if session_data:
        return json.loads(session_data)
    return None


def create_session(user_id: int, project_id: int, user_project_id: int = None, session_length: int = 259200) -> str:
    """Create a new session and store in Redis with user type context"""
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
    
    # Build session data based on user type
    session_data = {
        'user_id': user.id,
        'user_hash': user.user_hash,
        'project_id': project.id,
        'project_hash': project.project_hash,
        'user_type': user.user_type
    }
    
    # Add user type specific data
    if user.user_type == 'root':
        session_data['permissions'] = ['admin', 'global_admin', 'unrestricted_access']
        session_data['groups'] = ['root_users']
    elif user.user_type == 'admin':
        session_data['assigned_project_id'] = user.assigned_project_id
        session_data['permissions'] = ['admin', 'project_admin', 'manage_users', 'manage_groups']
        session_data['groups'] = ['project_admins']
    elif user.user_type == 'consumer':
        if user_project_id:
            user_project = get_user_project_access(user_id, project_id)
            if user_project:
                session_data['user_project_id'] = user_project.id
                session_data['user_project_hash'] = user_project.user_project_hash
                
                # Get user's groups and permissions
                groups = get_user_groups_in_project(user_project.id)
                permissions = get_user_permissions_in_project(user_id, project_id)
                session_data['groups'] = [g.group_name for g in groups]
                session_data['permissions'] = permissions
    
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
    """Validate a session token and return user data with user type context"""
    session_data = get_session_data(session_token)
    if not session_data:
        return None
    
    # Get fresh project data
    from src.Util.db.db_projects import get_project_by_hash
    project = get_project_by_hash(session_data['project_hash'])
    if not project:
        return None
    
    user_type = session_data.get('user_type', 'consumer')
    
    # Build user login data based on user type
    if user_type == 'root':
        groups = ['root_users']
        permissions = ['admin', 'global_admin', 'unrestricted_access']
        available_projects = []  # Root users can access all projects
    elif user_type == 'admin':
        groups = ['project_admins']
        permissions = ['admin', 'project_admin', 'manage_users', 'manage_groups']
        available_projects = [project]  # Admin users see only their project
    elif user_type == 'consumer':
        # Get fresh user groups and permissions for consumer users
        if 'user_project_id' not in session_data:
            return None
        groups = get_user_groups_in_project(session_data['user_project_id'])
        permissions = get_user_permissions_in_project(session_data['user_id'], project.id)
        available_projects = [proj for proj, _ in get_user_projects(session_data['user_id'])]
        groups = [g.group_name for g in groups]
    else:
        return None
    
    return EnhancedUserLogin(
        user_hash=session_data['user_hash'],
        project_hash=session_data['project_hash'],
        project_name=project.project_name,
        user_project_hash=session_data.get('user_project_hash', ''),
        session_token=session_token,
        session_length=0,  # We don't track remaining time
        user_id=session_data['user_id'],
        project_id=session_data['project_id'],
        user_project_id=session_data.get('user_project_id'),
        groups=groups,
        permissions=permissions,
        available_projects=available_projects,
        user_type=user_type,
        assigned_project_id=session_data.get('assigned_project_id')
    ) 