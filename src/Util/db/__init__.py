"""
3-Tier User Type Multi-Project Authentication Database Module

This module provides database operations for the 3-tier user type authentication system:

1. ROOT USERS: Super administrators with unrestricted global access
2. ADMIN USERS: Project-specific administrators limited to assigned projects  
3. CONSUMER USERS: End users with RBAC-based permissions through groups

The database operations are organized into specialized modules:
- db_users.py: User management with user type support
- db_projects.py: Project management and statistics
- db_user_groups.py: User group management and membership operations
- db_project_groups.py: Project group management and permission operations
- db_rbac_permissions.py: RBAC permission and role management
- db_enhanced.py: Main authentication functions with user type handling

User Type Access Model:
Root Users → Unrestricted Access to Everything
Admin Users → Project-Scoped Admin Access (assigned_project_id)
Consumer Users → RBAC Access (User Groups → Project Access → Project Groups → Permissions)
"""

import json

# Import utility functions
from src.Util.Models import UserLogin
# Import enhanced authentication functions
from src.Util.db.db_enhanced import (
    enhanced_login,
    enhanced_register,
    validate_session,
    get_session_data,
    is_root_user,
    is_admin_user,
    is_consumer_user,
    check_admin_project_access,
    # Legacy compatibility
    db_login,
    db_register,
    db_username_or_email_available
)
# Import project group management functions
from src.Util.db.db_project_groups import (
    create_project_group as create_project_permission_group,
    get_project_group_by_id as get_project_permission_group_by_id,
    get_project_group_by_hash as get_project_permission_group_by_hash,
    get_project_group_by_name as get_project_permission_group_by_name,
    list_all_project_groups as list_all_project_permission_groups,
    update_project_group as update_project_permission_group,
    delete_project_group as delete_project_permission_group,
    count_project_groups as count_project_permission_groups,
    search_project_groups as search_project_permission_groups,
    assign_project_to_group as assign_project_to_permission_group,
    remove_project_from_group as remove_project_from_permission_group,
    get_project_group_membership as get_project_permission_group_membership,
    get_project_groups_for_project as get_permission_groups_for_project,
    get_projects_in_group as get_projects_in_permission_group,
    get_project_permissions,
    get_user_project_permissions,
    check_user_project_permission,
    create_default_project_groups as create_default_permission_groups
)
# Import project management functions
from src.Util.db.db_projects import (
    create_project,
    get_project_by_hash,
    get_project_by_id,
    list_all_projects,
    count_projects,
    update_project,
    delete_project,
    search_projects,
    get_project_stats,
    get_project_groups,
    create_default_groups
)
# Import RBAC permissions functions
from src.Util.db.db_rbac_permissions import (
    create_permission,
    get_project_permissions as get_rbac_project_permissions,
    check_user_permission,
    create_default_project_permissions,
    create_permission_group,
    assign_user_to_permission_group,
    remove_user_from_permission_group,
    initialize_project_rbac,
    get_project_permission_groups,
    get_user_permission_groups_in_project,
    get_user_effective_permissions,
    get_project_audit_log,
    get_project_user_assignments,
    create_default_project_roles,
    assign_default_permissions_to_roles,
    assign_permission_to_group
)
# Import session analytics functions
from src.Util.db.db_session_analytics import (
    count_active_sessions,
    get_session_statistics,
    get_user_status,
    set_user_status,
    get_recent_users_count,
    get_user_login_statistics,
    get_recent_projects_count,
    get_project_members,
    add_user_to_project,
    check_database_health,
    check_redis_health,
    get_recent_activity_count,
    initialize_activity_logs_table
)
# Import user group management functions
from src.Util.db.db_user_groups import (
    create_user_group,
    get_user_group_by_id,
    get_user_group_by_hash,
    get_user_group_by_name,
    list_all_user_groups,
    update_user_group,
    delete_user_group,
    count_user_groups,
    get_total_user_groups_count,
    assign_user_to_group as assign_user_to_user_group,
    remove_user_from_group as remove_user_from_user_group,
    get_user_group_membership,
    get_user_groups_for_user,
    get_users_in_group,
    grant_group_project_access,
    revoke_group_project_access,
    get_group_project_access,
    get_projects_for_user_group,
    get_user_groups_for_project,
    get_user_accessible_projects
)
# Import user management functions
from src.Util.db.db_users import (
    create_user,
    create_root_user,
    create_admin_user,
    create_consumer_user,
    get_user_by_credentials,
    get_user_by_id,
    get_user_by_hash,
    update_user,
    delete_user,
    list_users,
    count_users,
    search_users,
    check_username_email_available,
    get_user_type,
    get_admin_assigned_project,
    get_admin_assigned_projects,
    assign_admin_to_multiple_projects,
    add_admin_to_project,
    remove_admin_from_project,
    check_admin_multi_project_access,
    get_admin_project_assignments_with_details,
    update_user_type,
    assign_admin_to_project,
    grant_user_project_access,
    get_user_project_access,
    get_user_projects,
    revoke_user_project_access,
    get_user_groups_in_project,
    get_user_permissions_in_project,
    assign_user_to_group,
    remove_user_from_group,
    create_session,
    invalidate_session
)
# Import core database connection
from src.Util.db_config import redis_client as client, get_connection


# =================== USER TYPE HELPER FUNCTIONS ===================

def get_user_type_info(user_id: int) -> dict:
    """
    Get comprehensive user type information.
    
    Args:
        user_id: User ID
        
    Returns:
        Dictionary with user type information
    """
    try:
        user = get_user_by_id(user_id)
        if not user:
            return {"user_type": None, "error": "User not found"}

        user_type = get_user_type(user_id)

        result = {
            "user_id": user_id,
            "user_hash": user.user_hash,
            "username": user.username,
            "user_type": user_type,
            "capabilities": []
        }

        if user_type == "root":
            result["capabilities"] = [
                "unrestricted_access",
                "global_admin",
                "create_root_users",
                "manage_all_projects",
                "manage_all_users"
            ]
        elif user_type == "admin":
            assigned_projects = get_admin_assigned_projects(user_id)
            result["assigned_project_ids"] = assigned_projects
            result["capabilities"] = [
                "project_admin",
                "manage_project_users",
                "manage_project_groups",
                "manage_project_permissions"
            ]
        elif user_type == "consumer":
            result["capabilities"] = [
                "rbac_permissions",
                "group_based_access",
                "project_access_via_groups"
            ]

        return result

    except Exception as e:
        return {"user_type": None, "error": str(e)}


def check_user_type_permission(user_id: int, operation: str, project_id: int = None) -> bool:
    """
    Check if user has permission for operation based on their user type.
    
    Args:
        user_id: User ID
        operation: Operation to check (e.g., 'admin', 'manage_users', 'read')
        project_id: Project ID (required for admin and consumer users)
        
    Returns:
        Boolean indicating permission
    """
    try:
        user_type = get_user_type(user_id)

        # Root users can do anything
        if user_type == "root":
            return True

        # Admin users can do admin operations in their assigned project
        elif user_type == "admin":
            if not project_id:
                return False
            return check_admin_project_access(user_id, project_id)

        # Consumer users follow RBAC permissions
        elif user_type == "consumer":
            if not project_id:
                return False
            return check_user_permission(user_id, project_id, operation)

        return False

    except Exception as e:
        print(f"Permission check error: {e}")
        return False


# =================== USER TYPE AWARE SESSION MANAGEMENT ===================

def create_user_type_session(user_id: int, project_id: int, session_length: int = 259200) -> dict:
    """
    Create session with user type context.
    
    Args:
        user_id: User ID
        project_id: Project ID
        session_length: Session duration in seconds
        
    Returns:
        Session information with user type context
    """
    try:
        user = get_user_by_id(user_id)
        user_type = get_user_type(user_id)

        # Create base session
        session_token = create_session(user_id, project_id, None, session_length)

        if not session_token:
            return None

        # Add user type specific context
        session_data = {
            "session_token": session_token,
            "user_type": user_type,
            "user_id": user_id,
            "user_hash": user.user_hash,
            "project_id": project_id
        }

        if user_type == "admin":
            session_data["assigned_project_ids"] = get_admin_assigned_projects(user_id)
            session_data["can_access_project"] = check_admin_project_access(user_id, project_id)
        elif user_type == "consumer":
            session_data["user_groups"] = [g.group_name for g in get_user_groups_for_user(user_id)]
            session_data["permissions"] = get_user_permissions_in_project(user_id, project_id)

        return session_data

    except Exception as e:
        print(f"Session creation error: {e}")
        return None


# Session management functions for backward compatibility
def set_session(key: int, value: str, ex: int, user_hash: str) -> bool:
    """
    Set session data in Redis cache.
    Enhanced to support user types.
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
    Enhanced to support user types.
    """
    try:
        res = client.get(hex(key)[2:])
        if res:
            res = json.loads(res)
            return UserLogin(
                user_session=res.get('user_session', ''),
                user_session_length=res.get('user_session_length', 0),
                user_hash=res.get('user_hash', ''),
                user_collection=res.get('user_collection', ''),
                user_id=res.get('user_id', 0),
                project_id=res.get('project_id'),
                user_project_id=res.get('user_project_id'),
                groups=res.get('groups', []),
                user_type=res.get('user_type', 'consumer'),
                assigned_project_id=res.get('assigned_project_id')
            )
    except Exception as e:
        print(f"Session retrieval error: {e}")

    return None


def db_validate_session(user_hash: str, user_session: str) -> bool:
    """
    Validate a session token and user hash.
    Enhanced to support user types.
    """
    try:
        result = validate_session(user_session)
        if result and result.user_hash == user_hash:
            # Additional validation for user types
            user = get_user_by_hash(user_hash)
            if user:
                user_type = get_user_type(user.id)
                return True
        return False
    except Exception as e:
        print(f"Session validation error: {e}")
        return False


# Export all available functions for easy importing
__all__ = [
    # Core database
    'client',
    'get_connection',

    # Authentication
    'enhanced_login',
    'enhanced_register',
    'validate_session',
    'get_session_data',

    # User type functions
    'is_root_user',
    'is_admin_user',
    'is_consumer_user',
    'check_admin_project_access',
    'get_user_type_info',
    'check_user_type_permission',
    'create_user_type_session',

    # User management
    'create_user',
    'create_root_user',
    'create_admin_user',
    'create_consumer_user',
    'get_user_by_credentials',
    'get_user_by_id',
    'get_user_by_hash',
    'update_user',
    'delete_user',
    'list_users',
    'count_users',
    'search_users',
    'check_username_email_available',
    'get_user_type',
    'get_admin_assigned_project',
    'get_admin_assigned_projects',
    'assign_admin_to_multiple_projects',
    'add_admin_to_project',
    'remove_admin_from_project',
    'check_admin_multi_project_access',
    'get_admin_project_assignments_with_details',
    'update_user_type',
    'assign_admin_to_project',
    'grant_user_project_access',
    'get_user_project_access',
    'get_user_projects',
    'revoke_user_project_access',
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
    'get_project_groups',
    'create_default_groups',

    # Session management
    'create_session',
    'invalidate_session',
    'set_session',
    'get_session',
    'db_validate_session',

    # Legacy compatibility
    'db_login',
    'db_register',
    'db_username_or_email_available',

    # User group management
    'create_user_group',
    'get_user_group_by_id',
    'get_user_group_by_hash',
    'get_user_group_by_name',
    'list_all_user_groups',
    'update_user_group',
    'delete_user_group',
    'count_user_groups',
    'get_total_user_groups_count',
    'assign_user_to_user_group',
    'remove_user_from_user_group',
    'get_user_group_membership',
    'get_user_groups_for_user',
    'get_users_in_group',
    'grant_group_project_access',
    'revoke_group_project_access',
    'get_group_project_access',
    'get_projects_for_user_group',
    'get_user_groups_for_project',
    'get_user_accessible_projects',

    # Project group management
    'create_project_permission_group',
    'get_project_permission_group_by_id',
    'get_project_permission_group_by_hash',
    'get_project_permission_group_by_name',
    'list_all_project_permission_groups',
    'update_project_permission_group',
    'delete_project_permission_group',
    'count_project_permission_groups',
    'search_project_permission_groups',
    'assign_project_to_permission_group',
    'remove_project_from_permission_group',
    'get_project_permission_group_membership',
    'get_permission_groups_for_project',
    'get_projects_in_permission_group',
    'get_project_permissions',
    'get_user_project_permissions',
    'check_user_project_permission',
    'create_default_permission_groups',

    # RBAC Permission Management
    'create_permission',
    'get_rbac_project_permissions',
    'check_user_permission',
    'create_default_project_permissions',
    'create_permission_group',
    'assign_user_to_permission_group',
    'remove_user_from_permission_group',
    'initialize_project_rbac',
    'get_project_permission_groups',
    'get_user_permission_groups_in_project',
    'get_user_effective_permissions',
    'get_project_audit_log',
    'get_project_user_assignments',
    'create_default_project_roles',
    'assign_default_permissions_to_roles',
    'assign_permission_to_group',

    # Session Analytics
    'count_active_sessions',
    'get_session_statistics',
    'get_user_status',
    'set_user_status',
    'get_recent_users_count',
    'get_user_login_statistics',
    'get_recent_projects_count',
    'get_project_members',
    'add_user_to_project',
    'check_database_health',
    'check_redis_health',
    'get_recent_activity_count',
    'initialize_activity_logs_table'
]
