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
import uuid
from datetime import datetime
from typing import List, Optional, Tuple, Any, Dict

import pymysql

from src.Util.JWT_Security import JWTTokenHandler
from src.Util.Models import (
    User, Project, UserProject, LegacyUserGroup as UserGroup, EnhancedUserLogin
)
from src.Util.cache_manager import cache_manager
from src.Util.db_config import get_connection, redis_client as client
from src.Util.password_security import hash_password, verify_password, needs_rehash
from src.Util.uuid_generator import generate_user_id


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

def get_user_type(user_id: str) -> Optional[str]:
    """Get user type for a user"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT user_type
                    FROM users
                    WHERE id = %s
                      AND is_active = 1
                    """, [user_id])

        result = cur.fetchone()
        return result[0] if result else None


def get_admin_assigned_project(user_id: str) -> Optional[str]:
    """Get assigned project for admin user through user groups"""
    assigned_projects = get_admin_assigned_projects(user_id)
    return assigned_projects[0] if assigned_projects else None


def update_user_type(user_id: str, new_user_type: str, assigned_project_id: str = None, updated_by: str = None) -> bool:
    """Update user type and project assignment"""
    with get_connection() as con:
        cur = con.cursor()

        # The users table no longer stores direct project assignments.  We allow
        # callers to omit *assigned_project_id*.  When supplied (and the target
        # type is admin) we will ensure a record exists in the
        # admin_project_assignments bridge table, but we no longer enforce it
        # as mandatory at this layer.
        if new_user_type in ['root', 'consumer']:
            assigned_project_id = None

        # Update the user_type only – project assignments are now handled in
        # the admin_project_assignments table instead of the users table.
        cur.execute("""
                    UPDATE users
                    SET user_type  = %s,
                        updated_at = NOW()
                    WHERE id = %s
                      AND is_active = 1
                    """, [new_user_type, user_id])

        # If converting the user to an admin and a project was supplied, make
        # sure we create (or reactivate) the assignment record.
        if new_user_type == 'admin' and assigned_project_id:
            add_admin_to_project(user_id, assigned_project_id, assigned_by=updated_by)

        success = cur.rowcount > 0
        if success:
            con.commit()

            # Invalidate all cache for this user when user type changes
            cache_manager.invalidate_user_cache(user_id)

        return success


# Note: assign_admin_to_project is now a wrapper function defined later for multi-project support


# =================== USER TYPE-SPECIFIC CREATION ===================

def create_root_user(username: str, password: str, email: str = None, created_by: str = None) -> User:
    """Create a root (super admin) user"""
    password_hash = hash_password(password)
    user_hash = generate_user_hash()

    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    INSERT INTO users (user_hash, username, email, password_hash, user_type,
                                       created_by, created_at)
                    VALUES (%s, %s, %s, %s, 'root', %s, NOW())
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
            last_login=None,  # New user, no login yet
            is_active=True
        )


# Note: create_admin_user has been moved to the bottom of the file to support multi-project assignments


def create_consumer_user(username: str, password: str, email: str = None, created_by: str = None) -> User:
    """Create a consumer (end user) user"""
    password_hash = hash_password(password)
    user_hash = generate_user_hash()
    user_id = generate_user_id()
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    INSERT INTO users (id, user_hash, username, email, password_hash, user_type,
                                       created_by, created_at)
                    VALUES (%s, %s, %s, %s, %s, 'consumer', %s, NOW())
                    """, [user_id, user_hash, username, email, password_hash, created_by])

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
            last_login=None,  # New user, no login yet
            is_active=True
        )


# =================== ENHANCED USER MANAGEMENT ===================

def create_user(username: str, password: str, email: str = None, user_type: str = "consumer",
                assigned_project_id: str = None) -> User:
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
    """Get user by username/email and password (enhanced with user type and password migration)"""
    with get_connection() as con:
        cur = con.cursor()

        # Fetch user record via stored procedure (uses new 3-tier schema)
        cur.callproc('sp_user_login', [username])

        result = cur.fetchone()
        # Cleanup any additional result-sets returned by the connector
        while cur.nextset():
            pass

        if not result:
            return None

        # Map result to variables (assigned_project_id was removed in new schema)
        (
            user_id,
            user_hash,
            db_username,
            db_email,
            stored_password_hash,
            user_type,
            created_at,
            is_active_flag,
        ) = result

        # Verify password (handles legacy & new Argon2 hashes)
        if not verify_password(password, stored_password_hash):
            return None

        # Check if password hash needs migration to Argon2
        if needs_rehash(stored_password_hash):
            try:
                # Migrate to new Argon2 hash
                new_password_hash = hash_password(password)
                cur.execute("""
                            UPDATE users
                            SET password_hash = %s,
                                updated_at    = NOW()
                            WHERE id = %s
                            """, [new_password_hash, user_id])
                con.commit()

                # Update the result with new hash for return
                result = list(result)
                result[4] = new_password_hash

                # Log the migration (optional)
                print(f"Password migrated to Argon2 for user: {db_username}")

            except Exception as e:
                print(f"Warning: Password migration failed for user {db_username}: {e}")
                # Continue with login even if migration fails

        return User(
            id=user_id,
            user_hash=user_hash,
            username=db_username,
            email=db_email,
            password_hash=result[4],
            user_type=user_type,
            assigned_project_id=None,
            created_at=created_at,
            last_login=None,  # Field doesn't exist in DB yet
            is_active=bool(is_active_flag)
        )


def get_user_by_id(user_id: str) -> Optional[User]:
    """Get user by user ID (enhanced with user type)"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT id,
                           user_hash,
                           username,
                           email,
                           password_hash,
                           user_type,
                           created_at,
                           is_active
                    FROM users
                    WHERE id = %s
                      AND is_active = 1
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
                assigned_project_id=None,
                created_at=result[6],
                last_login=None,  # Field doesn't exist in DB yet
                is_active=bool(result[7])
            )
    return None


def get_user_by_hash(user_hash: str, include_inactive: bool = False) -> Optional[User]:
    """
    Get user by user hash (enhanced with user type)
    
    Args:
        user_hash: The user's hash
        include_inactive: If True, returns inactive users too. Default False for security.
    
    Returns:
        User object or None
    """
    with get_connection() as con:
        cur = con.cursor()
        
        if include_inactive:
            query = """
                SELECT id, user_hash, username, email, password_hash, 
                       user_type, created_at, is_active
                FROM users
                WHERE user_hash = %s
            """
        else:
            query = """
                SELECT id, user_hash, username, email, password_hash,
                       user_type, created_at, is_active
                FROM users
                WHERE user_hash = %s AND is_active = 1
            """
        
        cur.execute(query, [user_hash])

        result = cur.fetchone()
        if result:
            return User(
                id=result[0],
                user_hash=result[1],
                username=result[2],
                email=result[3],
                password_hash=result[4],
                user_type=result[5],
                assigned_project_id=None,
                created_at=result[6],
                last_login=None,  # Field doesn't exist in DB yet
                is_active=bool(result[7])
            )
    return None


def check_username_email_available(username_or_email: str) -> bool:
    """Check if username or email is available globally"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT COUNT(*)
                    FROM users
                    WHERE (username = %s OR email = %s)
                      AND is_active = 1
                    """, [username_or_email, username_or_email])

        return cur.fetchone()[0] == 0


def update_user(user_id: str, username: str = None, email: str = None, password: str = None, user_type: str = None,
                assigned_project_id: str = None) -> Optional[User]:
    """Update user information (enhanced with user type support)"""
    if not any([username, email, password, user_type]):
        return None

    with get_connection() as con:
        cur = con.cursor()

        # If caller provided a project assignment for an admin user, ensure the
        # bridge table reflects it. The users table itself no longer stores
        # project assignments.
        if user_type == 'admin' and assigned_project_id:
            add_admin_to_project(user_id, assigned_project_id, assigned_by=None)

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
            password_hash = hash_password(password)
            update_fields.append("password_hash = %s")
            update_values.append(password_hash)

        if user_type:
            update_fields.append("user_type = %s")
            update_values.append(user_type)

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

            # Invalidate all cache for this user when user data changes
            cache_manager.invalidate_user_cache(user_id)

            return get_user_by_id(user_id)
        else:
            return None


def delete_user(user_id: str, deleted_by: str = None) -> bool:
    """Soft delete a user"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    UPDATE users
                    SET is_active  = 0,
                        updated_at = NOW()
                    WHERE id = %s
                      AND is_active = 1
                    """, [user_id])

        success = cur.rowcount > 0
        if success:
            con.commit()
        return success


def list_users(
        limit: int = 100,
        offset: int = 0,
        sort_by: str = 'username',
        sort_order: str = 'asc',
        search: Optional[str] = None,
        user_type_filter: Optional[str] = None,
        group_filter: Optional[str] = None,
        project_filter: Optional[str] = None,
        include_inactive: bool = False,
        # legacy parameters retained for backwards-compatibility
        user_type: str = None,
        project_id: str = None) -> List[User]:
    """List users leveraging the MySQL stored procedure *sp_list_users*.

    The signature has been expanded to match the filtering options available in
    the /users/list endpoint. The previous *user_type* / *project_id* arguments
    are still accepted; they are internally mapped to their newer equivalents
    to avoid breaking legacy callers (e.g. user_types_auth routes).
    """

    # Map legacy arguments -----------------------------------------------------
    if user_type_filter is None and user_type is not None:
        user_type_filter = user_type
    if project_filter is None and project_id is not None:
        project_filter = str(project_id)

    # Normalise input ----------------------------------------------------------
    if sort_order.lower() not in ['asc', 'desc']:
        sort_order = 'asc'

    with get_connection() as con:
        cur = con.cursor()
        try:
            cur.callproc(
                'sp_list_users_with_access',
                [
                    int(limit),
                    int(offset),
                    sort_by,
                    sort_order,
                    search,
                    user_type_filter,
                    group_filter,
                    project_filter,
                    int(include_inactive)
                ]
            )

            results = cur.fetchall()

            # Procedure returns: id, user_hash, username, email, user_type,
            # created_at, last_login, is_active, groups_json, projects_json
            users: List[User] = []
            for row in results:
                users.append(
                    User(
                        id=row[0],
                        user_hash=row[1],
                        username=row[2],
                        email=row[3],
                        password_hash="",  # not provided by the SP – not needed here
                        user_type=row[4],
                        assigned_project_id=None,
                        created_at=row[5],
                        last_login=row[6],  # last_login from stored procedure (NULL)
                        is_active=bool(row[7])
                    )
                )

            # Consume additional result-sets (PyMySQL requirement)
            while cur.nextset():
                pass

            return users
        finally:
            cur.close()


def count_users(user_type: str = None, **kwargs) -> int:
    """Count total number of users.

    The function now gracefully accepts (and ignores for now) any additional
    filtering arguments that may be forwarded by newer routes. This prevents
    *TypeError* exceptions in call-sites that already pass those parameters.
    A fully-featured counting implementation will be introduced in a future
    iteration.
    """
    include_inactive: bool = bool(kwargs.get('include_inactive', False))
    with get_connection() as con:
        cur = con.cursor()

        base_query = "SELECT COUNT(*) FROM users WHERE 1 = 1 "
        params: List[Any] = []

        if not include_inactive:
            base_query += "AND is_active = 1 "

        if user_type:
            base_query += "AND user_type = %s "
            params.append(user_type)

        cur.execute(base_query, params)
        return int(cur.fetchone()[0])


def search_users(search_term: str, user_type: str = None, limit: int = 50) -> List[User]:
    """Search users by username or email with optional user type filter"""
    with get_connection() as con:
        cur = con.cursor()
        search_pattern = f"%{search_term}%"

        query = """
                SELECT id,
                       user_hash,
                       username,
                       email,
                       password_hash,
                       user_type,
                       created_at,
                       is_active
                FROM users
                WHERE is_active = 1
                  AND (username LIKE %s OR email LIKE %s) \
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
                assigned_project_id=None,
                created_at=row[6],
                last_login=None,  # Field doesn't exist in DB yet
                is_active=bool(row[7])
            ))

        return results


# =================== USER-PROJECT ACCESS MANAGEMENT (Via User Groups) ===================
# Note: In the new schema, users access projects through user_groups → user_group_projects
# The old user_projects table no longer exists

def grant_user_project_access(user_id: str, project_id: str, granted_by: str = None) -> bool:
    """Grant a user access to a project through a user group"""
    from src.Util.db.db_user_groups import (
        assign_user_to_group,
        grant_group_project_access,
        get_user_groups_for_user
    )
    
    with get_connection() as con:
        cur = con.cursor()
        
        # Find or create a default user group for this project
        cur.execute("""
                    SELECT ug.id
                    FROM user_groups ug
                    INNER JOIN user_group_projects ugp ON ug.id = ugp.user_group_id
                    WHERE ugp.project_id = %s
                      AND ug.group_name LIKE '%user%'
                      AND ug.is_active = 1
                      AND ugp.is_active = 1
                    LIMIT 1
                    """, [project_id])
        
        group_result = cur.fetchone()
        if group_result:
            user_group_id = group_result[0]
            # Add user to this group
            result = assign_user_to_group(user_id, user_group_id, granted_by)
            return result is not None
        else:
            print(f"Warning: No default user group found for project {project_id}")
            return False


def get_user_project_access(user_id: str, project_id: str) -> Optional[bool]:
    """Check if user has access to a specific project through user groups"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT COUNT(*)
                    FROM user_group_members ugm
                    INNER JOIN user_group_projects ugp ON ugm.user_group_id = ugp.user_group_id
                    WHERE ugm.user_id = %s
                      AND ugp.project_id = %s
                      AND ugm.is_active = 1
                      AND ugp.is_active = 1
                    """, [user_id, project_id])
        
        result = cur.fetchone()
        return result[0] > 0 if result else False


def get_user_projects(user_id: str) -> List[Tuple[Project, Any]]:
    """Get all projects a user has access to through user groups"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT DISTINCT p.id,
                           p.project_hash,
                           p.project_name,
                           p.project_description,
                           p.project_created,
                           p.is_active
                    FROM projects p
                    INNER JOIN user_group_projects ugp ON p.id = ugp.project_id
                    INNER JOIN user_group_members ugm ON ugp.user_group_id = ugm.user_group_id
                    WHERE ugm.user_id = %s
                      AND p.is_active = 1
                      AND ugp.is_active = 1
                      AND ugm.is_active = 1
                    ORDER BY p.project_name
                    """, [user_id])
        
        results = []
        for row in cur.fetchall():
            project = Project(
                id=row[0], project_hash=row[1], project_name=row[2],
                project_description=row[3], project_created=row[4], is_active=bool(row[5])
            )
            # Return project with None for the second tuple element (compatibility)
            results.append((project, None))
        
        return results


def revoke_user_project_access(user_id: str, project_id: str, revoked_by: str = None) -> bool:
    """Revoke user's access to a project by removing them from all groups with access"""
    from src.Util.db.db_user_groups import remove_user_from_group
    
    with get_connection() as con:
        cur = con.cursor()
        
        # Find all user groups that give access to this project
        cur.execute("""
                    SELECT DISTINCT ug.id
                    FROM user_groups ug
                    INNER JOIN user_group_projects ugp ON ug.id = ugp.user_group_id
                    INNER JOIN user_group_members ugm ON ug.id = ugm.user_group_id
                    WHERE ugm.user_id = %s
                      AND ugp.project_id = %s
                      AND ugm.is_active = 1
                      AND ugp.is_active = 1
                    """, [user_id, project_id])
        
        groups = cur.fetchall()
        success = False
        
        for (group_id,) in groups:
            if remove_user_from_group(user_id, group_id, revoked_by):
                success = True
        
        return success


# =================== USER GROUP MANAGEMENT (Updated for New Schema) ===================

def get_user_groups_in_project(user_id: str, project_id: str) -> List[UserGroup]:
    """Get all groups a user belongs to that have access to a specific project"""
    # Use the new function from db_user_groups module
    from src.Util.db.db_user_groups import get_user_groups_in_project as get_groups
    return get_groups(user_id, project_id)


def get_user_permissions_in_project(user_id: str, project_id: str) -> List[str]:
    """Get all permissions a user has (global role system - project_id parameter kept for compatibility)"""
    # Use the global role system to get permissions
    try:
        from src.Util.db.db_global_roles import get_user_permissions
        return get_user_permissions(user_id)
    except Exception:
        return []


def assign_user_to_group(user_id: str, group_id: str, assigned_by: str = None) -> bool:
    """Assign user to a user group"""
    from src.Util.db.db_user_groups import assign_user_to_group as assign_to_group
    result = assign_to_group(user_id, group_id, assigned_by)
    return result is not None


def remove_user_from_group(user_id: str, group_id: str, removed_by: str = None) -> bool:
    """Remove user from a user group"""
    from src.Util.db.db_user_groups import remove_user_from_group as remove_from_group
    return remove_from_group(user_id, group_id, removed_by)


# =================== USER SESSION MANAGEMENT WITH USER TYPES ===================

def get_session_data(session_token: str) -> Optional[dict]:
    """Get session data from Redis"""
    session_data = client.get(f"session:{session_token}")
    if session_data:
        return json.loads(session_data)
    return None


def create_session(user_id: str, project_id: str, user_project_id: str = None,
                   session_length: int = 259200) -> str | None:
    """Create a new session and store in Redis with user type context"""
    session_id = secrets.randbelow(2 ** 31)  # Generate unique session ID for JWT

    # Get user and project data
    user = get_user_by_id(user_id)
    if not user:
        return None

    # Import here to avoid circular imports
    from src.Util.db.db_projects import get_project_by_id
    project = get_project_by_id(project_id)
    if not project:
        return None

    # Create JWT token
    session_token = JWTTokenHandler.create_access_token(
        session_id=session_id,
        user_hash=user.user_hash,
        collection=project.project_hash,
    )

    # Build session data based on user type
    session_data = {
        'session_id': session_id,
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
        # Admin users have permissions through admin groups
        session_data['permissions'] = ['admin', 'project_admin', 'manage_users', 'manage_groups']
        session_data['groups'] = ['project_admins']
    elif user.user_type == 'consumer':
        # Get user's groups and permissions through new RBAC system
        groups = get_user_groups_in_project(user_id, project_id)
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


def invalidate_user_sessions(user_id: str) -> bool:
    """Invalidate all sessions for a specific user"""
    try:
        # Get all session keys
        session_keys = client.keys("session:*")
        invalidated_count = 0
        
        for key in session_keys:
            try:
                session_data = client.get(key)
                if session_data:
                    data = json.loads(session_data)
                    if data.get('user_id') == user_id:
                        client.delete(key)
                        invalidated_count += 1
            except Exception:
                continue
        
        return invalidated_count > 0
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
        available_projects = [project]  # Admin users see their assigned projects
    elif user_type == 'consumer':
        # Get fresh user groups and permissions for consumer users
        groups = get_user_groups_in_project(session_data['user_id'], project.id)
        permissions = get_user_permissions_in_project(session_data['user_id'], project.id)
        available_projects = [proj for proj, _ in get_user_projects(session_data['user_id'])]
        groups = [g.group_name for g in groups]
    else:
        return None

    return EnhancedUserLogin(
        user_hash=session_data['user_hash'],
        project_hash=session_data['project_hash'],
        project_name=project.project_name,
        user_project_hash='',  # Deprecated field
        session_token=session_token,
        session_length=0,  # We don't track remaining time
        user_id=session_data['user_id'],
        project_id=session_data['project_id'],
        user_project_id=None,  # Deprecated field
        groups=groups,
        permissions=permissions,
        available_projects=available_projects,
        user_type=user_type,
        assigned_project_id=None  # Deprecated field
    )


# =================== ADMIN MULTI-PROJECT MANAGEMENT ===================

def get_admin_assigned_projects(user_id: str) -> List[str]:
    """Get all projects assigned to an admin user through user groups"""
    with get_connection() as con:
        cur = con.cursor()

        # Get user type first to ensure this is an admin user
        user_type = get_user_type(user_id)
        if user_type != 'admin':
            return []

        cur.execute("""
                    SELECT DISTINCT p.id
                    FROM projects p
                             INNER JOIN user_group_projects ugp ON p.id = ugp.project_id
                             INNER JOIN user_groups ug ON ugp.user_group_id = ug.id
                             INNER JOIN user_group_members ugm ON ug.id = ugm.user_group_id
                    WHERE ugm.user_id = %s
                      AND p.is_active = 1
                      AND ugp.is_active = 1
                      AND ug.is_active = 1
                      AND ugm.is_active = 1
                    """, [user_id])

        return [row[0] for row in cur.fetchall()]


def assign_admin_to_multiple_projects(user_id: str, project_ids: List[str], assigned_by: str = None) -> bool:
    """Assign admin user to multiple projects through user groups"""
    with get_connection() as con:
        cur = con.cursor()

        try:
            con.begin()

            # Verify user is admin
            user_type = get_user_type(user_id)
            if user_type != 'admin':
                raise ValueError("User is not an admin user")

            # For now, we'll use the existing user group management functions
            # This is a simplified approach - in a full implementation, you might want
            # to create project-specific admin groups or handle this differently

            # Import the user group functions
            from src.Util.db.db_user_groups import (
                assign_user_to_group,
                grant_group_project_access,
                get_user_groups_for_user
            )

            # Get user's current groups
            current_groups = get_user_groups_for_user(user_id)

            # For each project, ensure the user has access through an appropriate admin group
            for project_id in project_ids:
                # Look for an existing admin group for this project
                # This is a simplified approach - you might need more sophisticated logic
                cur.execute("""
                            SELECT ug.id
                            FROM user_groups ug
                                     INNER JOIN user_group_projects ugp ON ug.id = ugp.user_group_id
                            WHERE ugp.project_id = %s
                              AND ug.group_name LIKE '%admin%'
                              AND ug.is_active = 1
                              AND ugp.is_active = 1
                            LIMIT 1
                            """, [project_id])

                admin_group_result = cur.fetchone()
                if admin_group_result:
                    admin_group_id = admin_group_result[0]

                    # Check if user is already in this group
                    cur.execute("""
                                SELECT 1
                                FROM user_group_members ugm
                                WHERE ugm.user_id = %s
                                  AND ugm.user_group_id = %s
                                  AND ugm.is_active = 1
                                """, [user_id, admin_group_id])

                    if not cur.fetchone():
                        # Add user to admin group
                        assign_user_to_group(user_id, admin_group_id, assigned_by)

            con.commit()
            return True

        except Exception as e:
            con.rollback()
            print(f"Error assigning admin to multiple projects: {e}")
            return False


def add_admin_to_project(user_id: str, project_id: str, assigned_by: str = None) -> bool:
    """Add admin user to an additional project through user groups"""
    with get_connection() as con:
        cur = con.cursor()

        # Verify user is admin
        user_type = get_user_type(user_id)
        if user_type != 'admin':
            raise ValueError("User is not an admin user")

        try:
            # Import the user group functions
            from src.Util.db.db_user_groups import assign_user_to_group

            # Look for an existing admin group for this project
            cur.execute("""
                        SELECT ug.id
                        FROM user_groups ug
                                 INNER JOIN user_group_projects ugp ON ug.id = ugp.user_group_id
                        WHERE ugp.project_id = %s
                          AND ug.group_name LIKE '%admin%'
                          AND ug.is_active = 1
                          AND ugp.is_active = 1
                        LIMIT 1
                        """, [project_id])

            admin_group_result = cur.fetchone()
            if admin_group_result:
                admin_group_id = admin_group_result[0]

                # Check if user is already in this group
                cur.execute("""
                            SELECT 1
                            FROM user_group_members ugm
                            WHERE ugm.user_id = %s
                              AND ugm.user_group_id = %s
                              AND ugm.is_active = 1
                            """, [user_id, admin_group_id])

                if not cur.fetchone():
                    # Add user to admin group
                    result = assign_user_to_group(user_id, admin_group_id, assigned_by)
                    return result is not None
                else:
                    # User is already in the group
                    return True
            else:
                print(f"No admin group found for project {project_id}")
                return False

        except Exception as e:
            print(f"Error adding admin to project: {e}")
            return False


def remove_admin_from_project(user_id: str, project_id: str, removed_by: str = None) -> bool:
    """Remove admin user from a specific project through user groups"""
    with get_connection() as con:
        cur = con.cursor()

        try:
            # Import the user group functions
            from src.Util.db.db_user_groups import remove_user_from_group

            # Find admin groups for this project that the user is a member of
            cur.execute("""
                        SELECT ug.id
                        FROM user_groups ug
                                 INNER JOIN user_group_projects ugp ON ug.id = ugp.user_group_id
                                 INNER JOIN user_group_members ugm ON ug.id = ugm.user_group_id
                        WHERE ugp.project_id = %s
                          AND ugm.user_id = %s
                          AND ug.group_name LIKE '%admin%'
                          AND ug.is_active = 1
                          AND ugp.is_active = 1
                          AND ugm.is_active = 1
                        """, [project_id, user_id])

            admin_groups = cur.fetchall()
            success = False

            for (admin_group_id,) in admin_groups:
                # Remove user from each admin group for this project
                if remove_user_from_group(user_id, admin_group_id, removed_by):
                    success = True

            return success

        except Exception as e:
            print(f"Error removing admin from project: {e}")
            return False


def check_admin_multi_project_access(user_id: str, project_id: str) -> bool:
    """Check if admin user has access to specific project (supports multiple projects)"""
    try:
        user_type = get_user_type(user_id)
        if user_type != 'admin':
            return False
        assigned_projects = get_admin_assigned_projects(user_id)
        return project_id in assigned_projects
    except:
        return False


def get_admin_project_assignments_with_details(user_id: str) -> List[dict]:
    """Get admin's project assignments with project details through user groups"""
    with get_connection() as con:
        cur = con.cursor()

        # Get user type first to ensure this is an admin user
        user_type = get_user_type(user_id)
        if user_type != 'admin':
            return []

        cur.execute("""
                    SELECT DISTINCT p.id           as project_id,
                                    p.project_hash,
                                    p.project_name,
                                    p.project_description,
                                    ugp.granted_at as assigned_at,
                                    ugp.granted_by as assigned_by,
                                    ug.group_name  as access_through_group
                    FROM projects p
                             INNER JOIN user_group_projects ugp ON p.id = ugp.project_id
                             INNER JOIN user_groups ug ON ugp.user_group_id = ug.id
                             INNER JOIN user_group_members ugm ON ug.id = ugm.user_group_id
                    WHERE ugm.user_id = %s
                      AND p.is_active = 1
                      AND ugp.is_active = 1
                      AND ug.is_active = 1
                      AND ugm.is_active = 1
                    ORDER BY p.project_name
                    """, [user_id])

        assignments = []
        for row in cur.fetchall():
            assignments.append({
                'project_id': row[0],
                'project_hash': row[1],
                'project_name': row[2],
                'project_description': row[3],
                'assigned_at': row[4],
                'assigned_by': row[5],
                'access_through_group': row[6]
            })

        return assignments


# =================== UPDATED LEGACY COMPATIBILITY FUNCTIONS ===================

def get_admin_assigned_project(user_id: str) -> Optional[str]:
    """
    Get assigned project for admin user (backwards compatibility)
    Returns the first assigned project for legacy compatibility
    """
    assigned_projects = get_admin_assigned_projects(user_id)
    return assigned_projects[0] if assigned_projects else None


def check_admin_project_access(user_id: str, project_id: str) -> bool:
    """Check if admin user has access to specific project (updated for multi-project)"""
    return check_admin_multi_project_access(user_id, project_id)


def assign_admin_to_project(user_id: str, project_id: str, assigned_by: str = None) -> bool:
    """Assign admin user to a project (updated to preserve existing assignments)"""
    return add_admin_to_project(user_id, project_id, assigned_by)


# =================== UPDATED USER TYPE-SPECIFIC CREATION ===================

def create_admin_user(username: str, password: str, email: str, assigned_project_id: str = None,
                      assigned_project_ids: List[str] = None, created_by: str = None) -> User:
    """Create an admin user assigned to one or multiple projects through user groups"""
    password_hash = hash_password(password)
    user_hash = generate_user_hash()

    # Handle backwards compatibility: if single project_id provided, convert to list
    if assigned_project_id and not assigned_project_ids:
        assigned_project_ids = [assigned_project_id]
    elif assigned_project_ids and not assigned_project_id:
        assigned_project_id = assigned_project_ids[0]  # For legacy compatibility

    with get_connection() as con:
        cur = con.cursor()

        try:
            con.begin()

            # Create user
            cur.execute("""
                        INSERT INTO users (user_hash, username, email, password_hash, user_type,
                                           created_by, created_at)
                        VALUES (%s, %s, %s, %s, 'admin', %s, NOW())
                        """, [user_hash, username, email, password_hash, created_by])

            user_id = con.insert_id()

            # Assign to projects through user groups
            if assigned_project_ids:
                # Import user group functions
                from src.Util.db.db_user_groups import assign_user_to_group

                for project_id in assigned_project_ids:
                    # Look for an existing admin group for this project
                    cur.execute("""
                                SELECT ug.id
                                FROM user_groups ug
                                         INNER JOIN user_group_projects ugp ON ug.id = ugp.user_group_id
                                WHERE ugp.project_id = %s
                                  AND ug.group_name LIKE '%admin%'
                                  AND ug.is_active = 1
                                  AND ugp.is_active = 1
                                LIMIT 1
                                """, [project_id])

                    admin_group_result = cur.fetchone()
                    if admin_group_result:
                        admin_group_id = admin_group_result[0]
                        # Add user to admin group
                        assign_user_to_group(user_id, admin_group_id, created_by)

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
                last_login=None,  # New user, no login yet
                is_active=True
            )

        except Exception as e:
            con.rollback()
            raise e


# =================== NEW DETAILED USER LIST ===================

def list_users_with_access(
        limit: int = 100,
        offset: int = 0,
        sort_by: str = 'username',
        sort_order: str = 'asc',
        search: Optional[str] = None,
        user_type_filter: Optional[str] = None,
        group_filter: Optional[str] = None,
        project_filter: Optional[str] = None,
        include_inactive: bool = False) -> List[Dict[str, Any]]:
    """Return users together with aggregated group and project information.

    This function utilises the *sp_list_users_with_access* stored procedure which
    consolidates user details, group memberships, and accessible projects into a
    single result-set. Each row contains two JSON columns – *groups_json* and
    *projects_json* – that are parsed by the calling layer when required.
    """

    # Normalise input --------------------------------------------------------
    if sort_order.lower() not in ['asc', 'desc']:
        sort_order = 'asc'

    with get_connection() as con:
        cur = con.cursor()
        try:
            cur.callproc(
                'sp_list_users_with_access',
                [
                    int(limit),
                    int(offset),
                    sort_by,
                    sort_order,
                    search,
                    user_type_filter,
                    group_filter,
                    project_filter,
                    int(include_inactive)
                ]
            )

            results = cur.fetchall()

            # Expected order of columns returned by the SP
            # id, user_hash, username, email, user_type, created_at, last_login,
            # is_active, groups_json, projects_json
            users: List[Dict[str, Any]] = []
            for row in results:
                users.append({
                    "id": row[0],
                    "user_hash": row[1],
                    "username": row[2],
                    "email": row[3],
                    "user_type": row[4],
                    "created_at": row[5],
                    "last_login": row[6],
                    "is_active": bool(row[7]),
                    "groups_json": row[8],
                    "projects_json": row[9]
                })

            # Consume additional result-sets if the connector yields any
            while cur.nextset():
                pass

            return users
        finally:
            cur.close()
