import json
import secrets
import os
from typing import List, Optional, Tuple
from datetime import datetime, timedelta

import pymysql
import hashlib
import redis

from src.Util.Models import (
    User, Project, UserProject, UserGroup, UserProjectGroup, 
    UserSession, UserLogin, EnhancedUserLogin
)

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


def check_username_email_available(username_or_email: str) -> bool:
    """Check if username or email is available globally"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM users 
            WHERE (username = %s OR email = %s) AND is_active = 1
        """, [username_or_email, username_or_email])
        
        return cur.fetchone()[0] == 0


# =================== USER-PROJECT MANAGEMENT ===================

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


# =================== GROUP MANAGEMENT ===================

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


# =================== AUTHENTICATION ===================

def enhanced_login(username: str, password: str, project_hash: str) -> Optional[EnhancedUserLogin]:
    """Enhanced login with multi-project support"""
    # Get user by credentials
    user = get_user_by_credentials(username, password)
    if not user:
        return None
    
    # Get project
    project = get_project_by_hash(project_hash)
    if not project:
        return None
    
    # Check if user has access to this project
    user_project = get_user_project_access(user.id, project.id)
    if not user_project:
        return None
    
    # Get user's groups and permissions in this project
    groups = get_user_groups_in_project(user_project.id)
    permissions = get_user_permissions_in_project(user_project.id)
    
    # Get all projects user has access to
    available_projects = [proj for proj, _ in get_user_projects(user.id)]
    
    # Create session
    session_token = secrets.token_hex(32).upper()
    session_length = 60 * 60 * 24 * 3  # 3 days
    
    # Store session in Redis
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
    
    return EnhancedUserLogin(
        user_hash=user.user_hash,
        project_hash=project.project_hash,
        project_name=project.project_name,
        user_project_hash=user_project.user_project_hash,
        session_token=session_token,
        session_length=session_length,
        user_id=user.id,
        project_id=project.id,
        user_project_id=user_project.id,
        groups=[g.group_name for g in groups],
        permissions=permissions,
        available_projects=available_projects
    )


def enhanced_register(username: str, password: str, email: str, project_hash: str) -> Optional[EnhancedUserLogin]:
    """Enhanced registration with multi-project support"""
    # Check if username/email is available
    if not check_username_email_available(username) or (email and not check_username_email_available(email)):
        return None
    
    # Get or create project
    project = get_project_by_hash(project_hash)
    if not project:
        return None
    
    # Create user
    user = create_user(username, password, email)
    
    # Grant user access to the project
    user_project = grant_user_project_access(user.id, project.id)
    
    # Continue with login flow
    return enhanced_login(username, password, project_hash)


def get_session_data(session_token: str) -> Optional[dict]:
    """Get session data from Redis"""
    session_data = client.get(f"session:{session_token}")
    if session_data:
        return json.loads(session_data)
    return None


def validate_session(session_token: str) -> Optional[EnhancedUserLogin]:
    """Validate a session token and return user data"""
    session_data = get_session_data(session_token)
    if not session_data:
        return None
    
    # Get fresh project data
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


# =================== LEGACY COMPATIBILITY ===================

def db_login(user: str, password: str, collection: str) -> Optional[UserLogin]:
    """Legacy login function for backward compatibility"""
    enhanced_result = enhanced_login(user, password, collection)
    if enhanced_result:
        return UserLogin(
            user_session=enhanced_result.session_token,
            user_session_length=enhanced_result.session_length,
            user_hash=enhanced_result.user_hash,
            user_collection=enhanced_result.project_hash,
            user_id=enhanced_result.user_id,
            project_id=enhanced_result.project_id,
            user_project_id=enhanced_result.user_project_id,
            groups=enhanced_result.groups
        )
    return None


def db_register(collection: str, user: str, password: str, email: str = None) -> Optional[UserLogin]:
    """Legacy register function for backward compatibility"""
    enhanced_result = enhanced_register(user, password, email, collection)
    if enhanced_result:
        return UserLogin(
            user_session=enhanced_result.session_token,
            user_session_length=enhanced_result.session_length,
            user_hash=enhanced_result.user_hash,
            user_collection=enhanced_result.project_hash,
            user_id=enhanced_result.user_id,
            project_id=enhanced_result.project_id,
            user_project_id=enhanced_result.user_project_id,
            groups=enhanced_result.groups
        )
    return None


def db_username_or_email_available(username_or_email: str, collection: str) -> bool:
    """Legacy function for checking username/email availability"""
    return check_username_email_available(username_or_email) 