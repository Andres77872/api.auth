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
- Comprehensive error handling with handle_db_operation wrapper
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
from src.Util.db_error_wrapper import handle_db_operation
from src.Util.error_handler import ValidationError, NotFoundError, ErrorCode, mask_uuid


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
    """
    Get user type for a user.
    
    Args:
        user_id: User ID to lookup
        
    Returns:
        User type string or None if not found
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_user_type', [user_id])
            result = cur.fetchone()
            return result[0] if result else None
    
    return handle_db_operation(
        _get,
        error_context=f"get_user_type(user_id={user_id})"
    )


def get_admin_assigned_project(user_id: str) -> Optional[str]:
    """
    Get assigned project for admin user through user groups.
    
    Args:
        user_id: Admin user ID
        
    Returns:
        First assigned project ID or None
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        assigned_projects = get_admin_assigned_projects(user_id)
        return assigned_projects[0] if assigned_projects else None
    
    return handle_db_operation(
        _get,
        error_context=f"get_admin_assigned_project(user_id={user_id})"
    )


def update_user_type(user_id: str, new_user_type: str, assigned_project_id: str = None, updated_by: str = None) -> bool:
    """
    Update user type and project assignment.
    
    Args:
        user_id: User ID to update
        new_user_type: New user type (root, admin, consumer)
        assigned_project_id: Project to assign if admin (optional)
        updated_by: User ID who performed update
        
    Returns:
        True if updated successfully
        
    Raises:
        DatabaseError: On database operation errors
        ValidationError: On invalid user type
    """
    def _update():
        with get_connection() as con:
            cur = con.cursor()

            if new_user_type in ['root', 'consumer']:
                assigned_project_id = None

            cur.callproc('sp_update_user_type', [user_id, new_user_type])
            
            if new_user_type == 'admin' and assigned_project_id:
                add_admin_to_project(user_id, assigned_project_id, assigned_by=updated_by)

            con.commit()
            cache_manager.invalidate_user_cache(user_id)
            return True
    
    return handle_db_operation(
        _update,
        error_context=f"update_user_type(user_id={user_id}, new_user_type='{new_user_type}')"
    )


# Note: assign_admin_to_project is now a wrapper function defined later for multi-project support


# =================== USER TYPE-SPECIFIC CREATION ===================

def create_root_user(username: str, password: str, email: str = None, created_by: str = None) -> User:
    """
    Create a root (super admin) user.
    
    Args:
        username: Unique username for the root user
        password: Plain text password (will be hashed)
        email: Optional email address
        created_by: User ID of the creator
        
    Returns:
        User object for the created root user
        
    Raises:
        ConflictError: If username or email already exists
        DatabaseError: On database operation errors
        ValidationError: On invalid input
    """
    def _create():
        password_hash = hash_password(password)
        user_hash = generate_user_hash()

        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_create_root_user', [user_hash, username, email, password_hash, created_by])

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
    
    return handle_db_operation(
        _create,
        error_context=f"create_root_user(username='{username}', email='{email}')"
    )


# Note: create_admin_user has been moved to the bottom of the file to support multi-project assignments


def create_consumer_user(username: str, password: str, email: str = None, created_by: str = None) -> User:
    """
    Create a consumer (end user) user.
    
    Args:
        username: Unique username for the consumer user
        password: Plain text password (will be hashed)
        email: Optional email address
        created_by: User ID of the creator
        
    Returns:
        User object for the created consumer user
        
    Raises:
        ConflictError: If username or email already exists
        DatabaseError: On database operation errors
        ValidationError: On invalid input
    """
    def _create():
        password_hash = hash_password(password)
        user_hash = generate_user_hash()
        user_id = generate_user_id()
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_create_consumer_user', [user_id, user_hash, username, email, password_hash, created_by])
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
    
    return handle_db_operation(
        _create,
        error_context=f"create_consumer_user(username='{username}', email='{email}')"
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
    """
    Get user by username/email and password (enhanced with user type and password migration).
    
    Args:
        username: Username or email to authenticate
        password: Plain text password to verify
        
    Returns:
        User object if credentials are valid, None if invalid or not found
        
    Raises:
        DatabaseError: On database operation errors (not for invalid credentials)
    
    Note:
        Returns None for invalid credentials (not an error condition).
        Password hash migration to Argon2 happens automatically on successful login.
    """
    def _authenticate():
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
                role_id,
                created_at,
                last_login,
                is_active_flag,
            ) = result

            # Verify password (handles legacy & new Argon2 hashes)
            if not verify_password(password, stored_password_hash):
                return None

            # Check if password hash needs migration to Argon2
            if needs_rehash(stored_password_hash):
                # Migrate password hash (non-critical, don't fail login if it fails)
                try:
                    new_password_hash = hash_password(password)
                    cur.callproc('sp_update_password_hash', [user_id, new_password_hash])
                    con.commit()

                    # Update the result with new hash for return
                    result = list(result)
                    result[4] = new_password_hash
                    
                    import logging
                    logging.getLogger(__name__).info(f"Password migrated to Argon2 for user: {db_username}")

                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(
                        f"Password migration failed for user {db_username}: {str(e)}"
                    )
                    # Continue with login even if migration fails

            return User(
                id=user_id,
                user_hash=user_hash,
                username=db_username,
                email=db_email,
                password_hash=result[4] if isinstance(result, list) else stored_password_hash,
                user_type=user_type,
                assigned_project_id=None,
                created_at=created_at,
                last_login=None,  # Field doesn't exist in DB yet
                is_active=bool(is_active_flag)
            )
    
    # Do NOT add not_found_message - None is a valid response for authentication
    return handle_db_operation(
        _authenticate,
        error_context=f"get_user_by_credentials(username='{username}')"
    )


def get_user_by_id(user_id: str) -> Optional[User]:
    """
    Get user by user ID (enhanced with user type).
    
    Args:
        user_id: User ID to lookup
        
    Returns:
        User object if found, None if not found
        
    Raises:
        DatabaseError: On database operation errors
    
    Note:
        Returns None if user not found (not an error condition).
        Only returns active users.
    """
    def _get_user():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_user_by_id', [user_id])
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
                    created_at=result[7],
                    last_login=None,
                    is_active=bool(result[9])
                )
            return None
    
    return handle_db_operation(
        _get_user,
        error_context=f"get_user_by_id(user_id={user_id})"
    )


def get_user_by_hash(user_hash: str, include_inactive: bool = False) -> Optional[User]:
    """
    Get user by user hash (enhanced with user type).
    
    Args:
        user_hash: The user's hash (format: usr-UUID)
        include_inactive: If True, returns inactive users too. Default False for security.
    
    Returns:
        User object if found, None if not found
        
    Raises:
        DatabaseError: On database operation errors
    
    Note:
        Returns None if user not found (not an error condition).
        By default, only returns active users unless include_inactive=True.
    """
    def _get_user():
        with get_connection() as con:
            cur = con.cursor()
            # Pass include_inactive as 1 (True) or 0 (False) for MySQL TINYINT
            cur.callproc('sp_get_user_by_hash', [user_hash, 1 if include_inactive else 0])

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
                    created_at=result[7],
                    last_login=result[8],
                    is_active=bool(result[10])
                )
            return None
    
    return handle_db_operation(
        _get_user,
        error_context=f"get_user_by_hash(user_hash='{mask_uuid(user_hash)}', include_inactive={include_inactive})"
    )


def check_username_email_available(username_or_email: str) -> bool:
    """
    Check if username or email is available globally.
    
    Args:
        username_or_email: Username or email to check
        
    Returns:
        True if available (not taken), False if already exists
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _check():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_check_username_email_available', [username_or_email])
            return cur.fetchone()[0] == 0
    
    return handle_db_operation(
        _check,
        error_context=f"check_username_email_available(username_or_email='{username_or_email}')"
    )


def update_user(user_id: str, username: str = None, email: str = None, password: str = None, user_type: str = None,
                assigned_project_id: str = None) -> Optional[User]:
    """
    Update user information (enhanced with user type support).
    
    Args:
        user_id: ID of user to update
        username: New username (optional)
        email: New email (optional)
        password: New password (optional, will be hashed)
        user_type: New user type (optional)
        assigned_project_id: Project assignment for admin users (optional)
        
    Returns:
        Updated User object, or None if no fields to update
        
    Raises:
        ConflictError: If username or email already exists
        DatabaseError: On database operation errors
        ValidationError: On invalid input
        NotFoundError: If user not found
    """
    # Validation: at least one field must be provided
    if not any([username, email, password, user_type]):
        raise ValidationError(
            message="At least one field must be provided to update",
            error_code=ErrorCode.INVALID_INPUT,
            details={"user_id": user_id}
        )
    
    def _update():
        with get_connection() as con:
            cur = con.cursor()

            # If caller provided a project assignment for an admin user, ensure the
            # bridge table reflects it. The users table itself no longer stores
            # project assignments.
            if user_type == 'admin' and assigned_project_id:
                add_admin_to_project(user_id, assigned_project_id, assigned_by=None)

            # Hash password if provided
            password_hash_value = hash_password(password) if password else None

            # Use stored procedure for update (sp_update_user uses COALESCE for NULL params)
            cur.callproc('sp_update_user', [user_id, username, email, password_hash_value, user_type])

            # Get the result
            result = cur.fetchone()
            rows_affected = result[0] if result else 0

            if rows_affected > 0:
                con.commit()

                # Invalidate all cache for this user when user data changes
                cache_manager.invalidate_user_cache(user_id)

                return get_user_by_id(user_id)
            else:
                raise NotFoundError(
                    message=f"User not found or inactive: {user_id}",
                    error_code=ErrorCode.USER_NOT_FOUND,
                    details={"user_id": user_id}
                )
    
    return handle_db_operation(
        _update,
        error_context=f"update_user(user_id={user_id}, username={username}, email={email}, user_type={user_type})"
    )


def delete_user(user_id: str, deleted_by: str = None) -> bool:
    """
    Soft delete a user.
    
    Args:
        user_id: ID of user to delete
        deleted_by: User ID of who performed deletion
        
    Returns:
        True if deleted, False if user not found
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _delete():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_delete_user', [user_id])

            success = cur.rowcount > 0
            if success:
                con.commit()
            return success
    
    return handle_db_operation(
        _delete,
        error_context=f"delete_user(user_id={user_id})"
    )


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
    """List users leveraging *sp_list_users_with_access* stored procedure.

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

    raw_rows = _retrieve_users_with_access_rows(
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order,
        search=search,
        user_type_filter=user_type_filter,
        group_filter=group_filter,
        project_filter=project_filter,
        include_inactive=include_inactive
    )

    users: List[User] = []
    for row in raw_rows:
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
                last_login=row[6],
                is_active=bool(row[7])
            )
        )

    return users


def count_users(user_type: str = None, **kwargs) -> int:
    """
    Count total number of users.

    Args:
        user_type: Filter by user type (optional)
        **kwargs: Additional filtering arguments (include_inactive, etc.)
        
    Returns:
        Count of users matching filters
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _count():
        include_inactive: bool = bool(kwargs.get('include_inactive', False))
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_count_users', [user_type, include_inactive])
            return int(cur.fetchone()[0])
    
    return handle_db_operation(
        _count,
        error_context=f"count_users(user_type='{user_type}')"
    )


def search_users(search_term: str, user_type: str = None, limit: int = 50) -> List[User]:
    """
    Search users by username or email with optional user type filter.
    
    Args:
        search_term: Search term for username or email
        user_type: Filter by user type (optional)
        limit: Maximum results to return
        
    Returns:
        List of matching users
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _search():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_search_users', [search_term, user_type, limit])
            results = []
            for row in cur.fetchall():
                results.append(User(
                    id=row[0],
                    user_hash=row[1],
                    username=row[2],
                    email=row[3],
                    password_hash="",  # Not returned by stored procedure
                    user_type=row[4],
                    assigned_project_id=None,
                    created_at=row[6],
                    last_login=None,
                    is_active=bool(row[7])
                ))

            return results
    
    return handle_db_operation(
        _search,
        error_context=f"search_users(search_term='{search_term}', user_type='{user_type}', limit={limit})"
    )


# =================== USER-PROJECT ACCESS MANAGEMENT (Via User Groups) ===================
# Note: In the new schema, users access projects through user_groups → user_group_projects
# The old user_projects table no longer exists

def grant_user_project_access(user_id: str, project_id: str, granted_by: str = None) -> bool:
    """
    Grant a user access to a project through a user group.
    
    Args:
        user_id: User ID to grant access
        project_id: Project ID to grant access to
        granted_by: User ID of grantor
        
    Returns:
        True if access granted successfully
        
    Raises:
        NotFoundError: If user, project, or default user group not found
        DatabaseError: On database operation errors
    """
    def _grant():
        from src.Util.db.db_user_groups import assign_user_to_group
        from src.Util.error_handler import NotFoundError
        
        with get_connection() as con:
            cur = con.cursor()
            
            # Find a default user group for this project
            cur.callproc('sp_find_default_user_group_for_project', [project_id])
            group_result = cur.fetchone()
            if not group_result:
                raise NotFoundError(
                    message=f"No default user group found for project",
                    error_code="NF_4003"
                )
            
            user_group_id = group_result[0]
            # Add user to this group
            result = assign_user_to_group(user_id, user_group_id, granted_by)
            return result is not None
    
    return handle_db_operation(
        _grant,
        error_context=f"grant_user_project_access(user_id={user_id}, project_id={project_id})"
    )


def get_user_project_access(user_id: str, project_id: str) -> Optional[bool]:
    """
    Check if user has access to a specific project through user groups.
    
    Args:
        user_id: User ID to check
        project_id: Project ID to check
        
    Returns:
        True if user has access, False otherwise
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _check():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_check_user_project_access', [user_id, project_id])
            result = cur.fetchone()
            return result[0] > 0 if result else False
    
    return handle_db_operation(
        _check,
        error_context=f"get_user_project_access(user_id={user_id}, project_id={project_id})"
    )


def get_user_projects(user_id: str) -> List[Tuple[Project, Any]]:
    """
    Get all projects a user has access to through user groups.
    
    Args:
        user_id: User ID to query
        
    Returns:
        List of tuples (Project, None) for compatibility
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_user_projects', [user_id])
            results = []
            for row in cur.fetchall():
                project = Project(
                    id=row[0], project_hash=row[1], project_name=row[2],
                    project_description=row[3], project_created=row[4], is_active=bool(row[5])
                )
                results.append((project, None))
            
            return results
    
    return handle_db_operation(
        _get,
        error_context=f"get_user_projects(user_id={user_id})"
    )


def revoke_user_project_access(user_id: str, project_id: str, revoked_by: str = None) -> bool:
    """Revoke user's access to a project by removing them from all groups with access"""
    from src.Util.db.db_user_groups import remove_user_from_group
    
    with get_connection() as con:
        cur = con.cursor()
        
        # Find all user groups that give access to this project
        cur.callproc('sp_find_user_groups_for_project_access', [user_id, project_id])
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
    """
    Get all permissions a user has (global role system - project_id kept for compatibility).
    
    Args:
        user_id: User ID to query
        project_id: Project ID (kept for compatibility, not used)
        
    Returns:
        List of permission names (empty list on error)
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        from src.Util.db.db_global_roles import get_user_permissions
        return get_user_permissions(user_id)
    
    return handle_db_operation(
        _get,
        error_context=f"get_user_permissions_in_project(user_id={user_id}, project_id={project_id})"
    )


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
    """
    Get session data from Redis.
    
    Args:
        session_token: Session token to retrieve
        
    Returns:
        Session data dictionary or None if not found
        
    Raises:
        DatabaseError: On Redis operation errors
    """
    def _get():
        session_data = client.get(f"session:{session_token}")
        if session_data:
            return json.loads(session_data)
        return None
    
    return handle_db_operation(
        _get,
        error_context=f"get_session_data(session_token='***')"
    )


def create_session(user_id: str, project_id: str, user_project_id: str = None,
                   session_length: int = 259200) -> str | None:
    """
    Create a new session and store in Redis with user type context.
    
    Args:
        user_id: User ID
        project_id: Project ID
        user_project_id: Deprecated parameter (kept for compatibility)
        session_length: Session duration in seconds
        
    Returns:
        Session token or None if user/project not found
        
    Raises:
        DatabaseError: On database/Redis operation errors
    """
    def _create():
        session_id = secrets.randbelow(2 ** 31)

        user = get_user_by_id(user_id)
        if not user:
            return None

        from src.Util.db.db_projects import get_project_by_id
        project = get_project_by_id(project_id)
        if not project:
            return None

        session_token = JWTTokenHandler.create_access_token(
            session_id=session_id,
            user_hash=user.user_hash,
            collection=project.project_hash,
        )

        session_data = {
            'session_id': session_id,
            'user_id': user.id,
            'user_hash': user.user_hash,
            'project_id': project.id,
            'project_hash': project.project_hash,
            'user_type': user.user_type
        }

        if user.user_type == 'root':
            session_data['permissions'] = ['admin', 'global_admin', 'unrestricted_access']
            session_data['groups'] = ['root_users']
        elif user.user_type == 'admin':
            session_data['permissions'] = ['admin', 'project_admin', 'manage_users', 'manage_groups']
            session_data['groups'] = ['project_admins']
        elif user.user_type == 'consumer':
            groups = get_user_groups_in_project(user_id, project_id)
            permissions = get_user_permissions_in_project(user_id, project_id)
            session_data['groups'] = [g.group_name for g in groups]
            session_data['permissions'] = permissions

        client.set(f"session:{session_token}", json.dumps(session_data), ex=session_length)

        return session_token
    
    return handle_db_operation(
        _create,
        error_context=f"create_session(user_id={user_id}, project_id={project_id})"
    )


def invalidate_session(session_token: str) -> bool:
    """
    Invalidate a session by removing it from Redis.
    
    Args:
        session_token: Session token to invalidate
        
    Returns:
        True if session was found and deleted, False otherwise
        
    Raises:
        DatabaseError: On Redis operation errors
    """
    def _invalidate():
        result = client.delete(f"session:{session_token}")
        return result > 0
    
    return handle_db_operation(
        _invalidate,
        error_context=f"invalidate_session(session_token='***')"
    )


def invalidate_user_sessions(user_id: str) -> bool:
    """
    Invalidate all sessions for a specific user.
    
    Args:
        user_id: User ID whose sessions to invalidate
        
    Returns:
        True if any sessions were deleted, False otherwise
        
    Raises:
        DatabaseError: On Redis operation errors
    """
    def _invalidate():
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
    
    return handle_db_operation(
        _invalidate,
        error_context=f"invalidate_user_sessions(user_id={user_id})"
    )


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
    """
    Get all projects assigned to an admin user through user groups.
    
    Args:
        user_id: Admin user ID
        
    Returns:
        List of project IDs (empty list if not admin or no projects)
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()

            user_type = get_user_type(user_id)
            if user_type != 'admin':
                return []

            cur.callproc('sp_get_admin_assigned_projects', [user_id])
            return [row[0] for row in cur.fetchall()]
    
    return handle_db_operation(
        _get,
        error_context=f"get_admin_assigned_projects(user_id={user_id})"
    )


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
                cur.callproc('sp_find_admin_group_for_project', [project_id])
                admin_group_result = cur.fetchone()
                if admin_group_result:
                    admin_group_id = admin_group_result[0]

                    # Check if user is already in this group
                    cur.callproc('sp_check_user_in_group', [user_id, admin_group_id])
                    if not cur.fetchone()[0]:
                        # Add user to admin group
                        assign_user_to_group(user_id, admin_group_id, assigned_by)

            con.commit()
            return True

        except Exception as e:
            con.rollback()
            print(f"Error assigning admin to multiple projects: {e}")
            return False


def add_admin_to_project(user_id: str, project_id: str, assigned_by: str = None) -> bool:
    """
    Add admin user to an additional project through user groups.
    
    Args:
        user_id: User ID to add
        project_id: Project ID to add to
        assigned_by: User ID of assigner
        
    Returns:
        True if admin added successfully (or already assigned)
        
    Raises:
        ValidationError: If user is not an admin user
        NotFoundError: If admin group not found for project
        DatabaseError: On database operation errors
    """
    def _add():
        from src.Util.db.db_user_groups import assign_user_to_group
        from src.Util.error_handler import ValidationError, NotFoundError
        
        # Verify user is admin
        user_type = get_user_type(user_id)
        if user_type != 'admin':
            raise ValidationError(
                message="User is not an admin user",
                error_code="VAL_3001",
                details={"user_id": user_id, "user_type": user_type}
            )
        
        with get_connection() as con:
            cur = con.cursor()
            
            # Look for an existing admin group for this project
            cur.callproc('sp_find_admin_group_for_project', [project_id])
            admin_group_result = cur.fetchone()
            if not admin_group_result:
                raise NotFoundError(
                    message=f"No admin group found for project",
                    error_code="NF_4003"
                )
            
            admin_group_id = admin_group_result[0]
            
            # Check if user is already in this group
            cur.callproc('sp_check_user_in_group', [user_id, admin_group_id])
            if not cur.fetchone()[0]:
                # Add user to admin group
                result = assign_user_to_group(user_id, admin_group_id, assigned_by)
                return result is not None
            else:
                # User is already in the group
                return True
    
    return handle_db_operation(
        _add,
        error_context=f"add_admin_to_project(user_id={user_id}, project_id={project_id})"
    )


def remove_admin_from_project(user_id: str, project_id: str, removed_by: str = None) -> bool:
    """
    Remove admin user from a specific project through user groups.
    
    Args:
        user_id: User ID to remove
        project_id: Project ID to remove from
        removed_by: User ID of remover
        
    Returns:
        True if admin removed from at least one admin group successfully
        
    Raises:
        NotFoundError: If user is not in any admin group for project
        DatabaseError: On database operation errors
    """
    def _remove():
        from src.Util.db.db_user_groups import remove_user_from_group
        from src.Util.error_handler import NotFoundError
        
        with get_connection() as con:
            cur = con.cursor()
            
            # Find admin groups for this project that the user is a member of
            cur.callproc('sp_find_admin_groups_for_user_in_project', [project_id, user_id])
            admin_groups = cur.fetchall()
            if not admin_groups:
                raise NotFoundError(
                    message=f"User is not in any admin group for project",
                    error_code="NF_4003"
                )
            
            success = False
            for (admin_group_id,) in admin_groups:
                # Remove user from each admin group for this project
                if remove_user_from_group(user_id, admin_group_id, removed_by):
                    success = True
            
            return success
    
    return handle_db_operation(
        _remove,
        error_context=f"remove_admin_from_project(user_id={user_id}, project_id={project_id})"
    )


def check_admin_multi_project_access(user_id: str, project_id: str) -> bool:
    """
    Check if admin user has access to specific project (supports multiple projects).
    
    Args:
        user_id: User ID to check
        project_id: Project ID to check access for
        
    Returns:
        True if admin has access to project, False otherwise (returns False on error)
        
    Note:
        Returns False instead of raising exceptions for permission checks.
    """
    def _check():
        user_type = get_user_type(user_id)
        if user_type != 'admin':
            return False
        assigned_projects = get_admin_assigned_projects(user_id)
        return project_id in assigned_projects
    
    return handle_db_operation(
        _check,
        error_context=f"check_admin_multi_project_access(user_id={user_id}, project_id={project_id})",
        default_return=False
    )


def get_admin_project_assignments_with_details(user_id: str) -> List[dict]:
    """
    Get admin's project assignments with project details through user groups.
    
    Args:
        user_id: User ID to get assignments for
        
    Returns:
        List of project assignment dictionaries with details (empty list if not admin)
        
    Raises:
        DatabaseError: On database operation errors
        
    Note:
        Returns empty list if user is not an admin (not an error condition).
    """
    def _get():
        # Get user type first to ensure this is an admin user
        user_type = get_user_type(user_id)
        if user_type != 'admin':
            return []
        
        with get_connection() as con:
            cur = con.cursor()
            
            cur.callproc('sp_get_admin_project_assignments_with_details', [user_id])
            
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
    
    return handle_db_operation(
        _get,
        error_context=f"get_admin_project_assignments_with_details(user_id={user_id})"
    )


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
    """
    Create an admin user assigned to one or multiple projects through user groups.
    
    Args:
        username: Unique username
        password: Plain text password (will be hashed)
        email: Email address
        assigned_project_id: Single project ID (for backward compatibility)
        assigned_project_ids: List of project IDs to assign
        created_by: User ID of creator
        
    Returns:
        Created User object
        
    Raises:
        ConflictError: If username or email already exists
        DatabaseError: On database operation errors
    """
    def _create():
        password_hash = hash_password(password)
        user_hash = generate_user_hash()

        if assigned_project_id and not assigned_project_ids:
            assigned_project_ids_list = [assigned_project_id]
        elif assigned_project_ids:
            assigned_project_ids_list = assigned_project_ids
            assigned_project_id_value = assigned_project_ids[0] if assigned_project_ids else None
        else:
            assigned_project_ids_list = []
            assigned_project_id_value = None

        with get_connection() as con:
            cur = con.cursor()

            con.begin()

            cur.callproc('sp_create_admin_user', [user_hash, username, email, password_hash, created_by])
            user_id = cur.fetchone()[0]

            if assigned_project_ids_list:
                from src.Util.db.db_user_groups import assign_user_to_group

                for project_id in assigned_project_ids_list:
                    cur.callproc('sp_find_admin_group_for_project', [project_id])

                    admin_group_result = cur.fetchone()
                    if admin_group_result:
                        admin_group_id = admin_group_result[0]
                        assign_user_to_group(user_id, admin_group_id, created_by)

            con.commit()

            return User(
                id=user_id,
                user_hash=user_hash,
                username=username,
                email=email,
                password_hash=password_hash,
                user_type='admin',
                assigned_project_id=assigned_project_id_value if 'assigned_project_id_value' in locals() else assigned_project_id,
                created_at=datetime.now(),
                last_login=None,
                is_active=True
            )
    
    return handle_db_operation(
        _create,
        error_context=f"create_admin_user(username='{username}', email='{email}')"
    )


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
    """Return users together with aggregated group and project information."""

    raw_rows = _retrieve_users_with_access_rows(
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order,
        search=search,
        user_type_filter=user_type_filter,
        group_filter=group_filter,
        project_filter=project_filter,
        include_inactive=include_inactive
    )

    users: List[Dict[str, Any]] = []
    for row in raw_rows:
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

    return users


def _retrieve_users_with_access_rows(
        limit: int,
        offset: int,
        sort_by: Optional[str],
        sort_order: Optional[str],
        search: Optional[str],
        user_type_filter: Optional[str],
        group_filter: Optional[str],
        project_filter: Optional[str],
        include_inactive: bool) -> List[Tuple[Any, ...]]:
    """Fetch raw user rows via the stored procedure."""

    normalised_sort_order = (sort_order or 'asc').lower()
    if normalised_sort_order not in ['asc', 'desc']:
        normalised_sort_order = 'asc'

    normalised_limit = max(1, int(limit)) if str(limit).isdigit() else 100
    normalised_offset = max(0, int(offset)) if str(offset).isdigit() else 0

    normalised_sort_by = (sort_by or 'username')

    cleaned_search = _clean_optional_str(search)
    cleaned_user_type = _clean_optional_str(user_type_filter)
    cleaned_group_filter = _clean_optional_str(group_filter)
    cleaned_project_filter = _clean_optional_str(project_filter)

    with get_connection() as con:
        return _call_list_users_with_access_sp(
            con,
            limit=normalised_limit,
            offset=normalised_offset,
            sort_by=normalised_sort_by,
            sort_order=normalised_sort_order,
            search=cleaned_search,
            user_type_filter=cleaned_user_type,
            group_filter=cleaned_group_filter,
            project_filter=cleaned_project_filter,
            include_inactive=include_inactive
        )


def _call_list_users_with_access_sp(
        con,
        limit: int,
        offset: int,
        sort_by: str,
        sort_order: str,
        search: Optional[str],
        user_type_filter: Optional[str],
        group_filter: Optional[str],
        project_filter: Optional[str],
        include_inactive: bool) -> List[Tuple[Any, ...]]:
    """Execute the stored procedure for listing users with access details."""

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

        rows = cur.fetchall()
        while cur.nextset():
            pass
        return rows
    finally:
        cur.close()


def _clean_optional_str(value: Optional[str]) -> Optional[str]:
    """Trim optional string values and convert blanks to None."""

    if value is None:
        return None
    cleaned = value.strip()
    return cleaned if cleaned else None
