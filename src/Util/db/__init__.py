"""
Group-Based Multi-Project Authentication Database Module

This module provides database operations for the group-based authentication system.
The database operations are organized into specialized modules:

- db_users.py: User management, authentication, and session operations
- db_projects.py: Project management and statistics
- db_user_groups.py: User group management and membership operations
- db_project_groups.py: Project group management and permission operations
- db_enhanced.py: Main authentication functions that combine all operations

All operations use the group-based architecture with hierarchical access control:
Users → User Groups → Project Access → Project Groups → Permissions
"""

# Import core database functions from main module
from src.Util.db.db_enhanced import (
    # Core database connection
    client,

    # Group-based authentication functions
    enhanced_login,
    enhanced_register,
    validate_session,
    get_session_data,

    # Legacy compatibility functions
    db_login,
    db_register,
    db_username_or_email_available
)

# Import user management functions
from src.Util.db.db_users import (
    # User CRUD operations
    create_user,
    get_user_by_credentials,
    get_user_by_id,
    get_user_by_hash,
    update_user,
    delete_user,
    list_users,
    count_users,
    search_users,
    check_username_email_available,

    # User-project access management
    grant_user_project_access,
    get_user_project_access,
    get_user_projects,
    revoke_user_project_access,

    # User group management
    get_user_groups_in_project,
    get_user_permissions_in_project,
    assign_user_to_group,
    remove_user_from_group,

    # Session management
    create_session,
    invalidate_session
)

# Import project management functions
from src.Util.db.db_projects import (
    # Project CRUD operations
    create_project,
    get_project_by_hash,
    get_project_by_id,
    list_all_projects,
    count_projects,
    update_project,
    delete_project,
    search_projects,
    get_project_stats,

    # Project group management
    get_project_groups,
    create_project_group,
    update_project_group,
    delete_project_group,
    create_default_groups
)

from src.Util.Models import UserLogin
import json


# Session management functions for backward compatibility
def set_session(key: int, value: str, ex: int, user_hash: str) -> bool:
    """
    Set session data in Redis cache.
    Group-based system uses different session management, but this provides compatibility.
    """
    try:
        client.set(hex(key)[2:], value, ex=ex)
        return True
    except Exception as e:
        print(f"Session creation error: {e}")
        return False


def get_session(key: int) -> UserLogin | None:
    """
    Get session data from Redis cache.
    Group-based system uses validate_session() instead, but this provides compatibility.
    """
    try:
        res = client.get(hex(key)[2:])
        if res:
            res = json.loads(res)
            return UserLogin(
                user_session=res.get('user_session', ''),
                user_session_length=res.get('user_session_length', 0),
                user_hash=res.get('user_hash', ''),
                user_collection=res.get('user_collection', '')
            )
    except Exception as e:
        print(f"Session retrieval error: {e}")

    return None


def db_validate_session(user_hash: str, user_session: str) -> bool:
    """
    Validate a session token and user hash.
    Group-based system uses validate_session() instead, but this provides compatibility.
    """
    try:
        result = validate_session(user_session)
        return result is not None and result.user_hash == user_hash
    except Exception as e:
        print(f"Session validation error: {e}")
        return False


# Export all available functions for easy importing
__all__ = [
    # Core database
    'client',

    # Group-based authentication
    'enhanced_login',
    'enhanced_register',
    'validate_session',
    'get_session_data',

    # User management
    'create_user',
    'get_user_by_credentials',
    'get_user_by_id',
    'get_user_by_hash',
    'update_user',
    'delete_user',
    'list_users',
    'count_users',
    'search_users',
    'check_username_email_available',

    # User-project access
    'grant_user_project_access',
    'get_user_project_access',
    'get_user_projects',
    'revoke_user_project_access',

    # Group management
    'get_user_groups_in_project',
    'get_user_permissions_in_project',
    'assign_user_to_group',
    'remove_user_from_group',

    # Project management
    'create_project',
    'get_project_by_hash',
    'get_project_by_id',
    'list_all_projects',
    'count_projects',
    'update_project',
    'delete_project',
    'search_projects',
    'get_project_stats',

    # Project group management
    'get_project_groups',
    'create_project_group',
    'update_project_group',
    'delete_project_group',
    'create_default_groups',

    # Session management
    'create_session',
    'invalidate_session',

    # Legacy compatibility
    'db_login',
    'db_register',
    'db_username_or_email_available',
    'set_session',
    'get_session',
    'db_validate_session'
]
