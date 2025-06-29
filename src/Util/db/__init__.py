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

# Import core database functions from main module
from src.Util.db_config import redis_client as client
from src.Util.db.db_enhanced import (
    # 3-tier authentication functions
    enhanced_login,
    enhanced_register,
    validate_session,
    get_session_data,

    # User type checking functions
    is_root_user,
    is_admin_user,
    is_consumer_user,
    check_admin_project_access,

    # Legacy compatibility functions
    db_login,
    db_register,
    db_username_or_email_available
)

# Import user management functions with user type support
from src.Util.db.db_users import (
    # User CRUD operations with user type support
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

    # User type management
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
    
    # User-project access management (for consumer users)
    grant_user_project_access,
    get_user_project_access,
    get_user_projects,
    revoke_user_project_access,

    # User group management (for consumer users)
    get_user_groups_in_project,
    get_user_permissions_in_project,
    assign_user_to_group,
    remove_user_from_group,

    # Session management
    create_session,
    invalidate_session
)

# Import user group management functions (for consumer users)
from src.Util.db.db_user_groups import (
    # User group CRUD operations
    create_user_group,
    get_user_group_by_id,
    get_user_group_by_hash,
    get_user_group_by_name,
    list_all_user_groups,
    update_user_group,
    delete_user_group,
    count_user_groups,

    # User group membership management
    assign_user_to_group as assign_user_to_user_group,
    remove_user_from_group as remove_user_from_user_group,
    get_user_group_membership,
    get_user_groups_for_user,
    get_users_in_group,

    # User group project access
    grant_group_project_access,
    revoke_group_project_access,
    get_group_project_access,
    get_projects_for_user_group,
    get_user_groups_for_project,
    get_user_accessible_projects
)

# Import project group management functions (legacy support)
from src.Util.db.db_project_groups import (
    # Project group CRUD operations
    create_project_group as create_project_permission_group,
    get_project_group_by_id as get_project_permission_group_by_id,
    get_project_group_by_hash as get_project_permission_group_by_hash,
    get_project_group_by_name as get_project_permission_group_by_name,
    list_all_project_groups as list_all_project_permission_groups,
    update_project_group as update_project_permission_group,
    delete_project_group as delete_project_permission_group,
    count_project_groups as count_project_permission_groups,
    search_project_groups as search_project_permission_groups,

    # Project group membership management
    assign_project_to_group as assign_project_to_permission_group,
    remove_project_from_group as remove_project_from_permission_group,
    get_project_group_membership as get_project_permission_group_membership,
    get_project_groups_for_project as get_permission_groups_for_project,
    get_projects_in_group as get_projects_in_permission_group,

    # Permission utilities
    get_project_permissions,
    get_user_project_permissions,
    check_user_project_permission,
    create_default_project_groups as create_default_permission_groups
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

    # Project group management (legacy naming)
    get_project_groups,
    create_project_group,
    update_project_group,
    delete_project_group,
    create_default_groups
)

# Import RBAC permissions module (for consumer users)
from src.Util.db.db_rbac_permissions import (
    # Permission management
    create_permission,
    get_project_permissions as get_rbac_project_permissions,
    check_user_permission,
    create_default_project_permissions,
    
    # Permission group (role) management
    create_permission_group,
    assign_user_to_permission_group,
    
    # RBAC initialization
    initialize_project_rbac
)

# Import session analytics and activity management functions
from src.Util.db.db_session_analytics import (
    # Session analytics
    count_active_sessions,
    get_session_statistics,
    
    # User analytics
    get_user_status,
    set_user_status,
    get_recent_users_count,
    get_user_login_statistics,
    
    # Project analytics
    get_recent_projects_count,
    get_project_members,
    add_user_to_project,
    
    # System health
    check_database_health,
    check_redis_health,
    
    # Activity logs
    get_recent_activity_count,
    initialize_activity_logs_table
)

from src.Util.Models import UserLogin
import json


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
            assigned_project = get_admin_assigned_project(user_id)
            result["assigned_project_id"] = assigned_project
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
            session_data["assigned_project_id"] = get_admin_assigned_project(user_id)
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
                user_type=res.get('user_type', 'consumer'),  # NEW: user type
                assigned_project_id=res.get('assigned_project_id'),  # NEW: for admin users
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

    # 3-tier authentication
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

    # User management with user types
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

    # User type management
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

    # User-project access (consumer users)
    'grant_user_project_access',
    'get_user_project_access',
    'get_user_projects',
    'revoke_user_project_access',

    # Group management (consumer users)
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

    # Project group management (legacy)
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
    'db_validate_session',

    # User group management
    'create_user_group',
    'get_user_group_by_id',
    'get_user_group_by_hash',
    'get_user_group_by_name',
    'list_all_user_groups',
    'update_user_group',
    'delete_user_group',
    'count_user_groups',
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

    # Project group management (legacy)
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
    
    # RBAC Permission Management (consumer users)
    'create_permission',
    'get_rbac_project_permissions',
    'check_user_permission',
    'create_default_project_permissions',
    'create_permission_group',
    'assign_user_to_permission_group',
    'initialize_project_rbac',
    
    # Session Analytics and Activity Management
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
