"""
3-Tier User Type Multi-Project Authentication Database Module

This module provides database operations for the 3-tier user type authentication system:

1. ROOT USERS: Super administrators with unrestricted global access
2. ADMIN USERS: Project-specific administrators limited to assigned projects  
3. CONSUMER USERS: End users with role-based permissions through the global role system

The database operations are organized into specialized modules:
- db_users.py: User management with user type support
- db_projects.py: Project management and statistics
- db_user_groups.py: User group management and membership operations
- db_project_groups.py: Project group management and permission operations
- db_global_roles.py: Global role system with roles, permissions, and permission groups
- db_enhanced.py: Main authentication functions with user type handling

User Type Access Model:
Root Users → Unrestricted Access to Everything
Admin Users → Project-Scoped Admin Access (assigned_project_id)
Consumer Users → Global Role System (User → Role → Permission Groups → Permissions)
"""

from src.Util.db.db_enhanced import (
    enhanced_login,
    enhanced_register,
    validate_session,
    get_session_data,
    is_root_user,
    is_admin_user,
    is_consumer_user,
    check_admin_project_access,
    create_root_session,
    validate_root_session,
    validate_admin_session
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
    get_user_project_permissions as get_user_effective_permissions,
    check_user_project_permission,
    check_user_project_permission as check_user_permission,
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
    # Project access via Groups-of-Groups architecture
    get_projects_for_user_group,
    get_user_groups_for_project,
    get_user_accessible_projects,
    get_user_groups_in_project,
    get_user_groups_in_project_by_hash,
    # Groups-of-Groups Architecture: User Group → Project Group access
    grant_user_group_project_group_access,
    revoke_user_group_project_group_access,
    get_project_groups_for_user_group,
    check_user_group_project_group_access
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
    list_users_with_access,
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
    get_user_permissions_in_project,
    assign_user_to_group,
    remove_user_from_group,
    create_session,
    invalidate_session,
    invalidate_user_sessions
)
# Import permission assignment functions
from src.Util.db.db_permission_assignments import (
    assign_permission_group_to_user_group,
    remove_permission_group_from_user_group,
    get_user_group_permission_groups,
    get_user_groups_with_permission_group,
    assign_permission_group_to_user,
    remove_permission_group_from_user,
    get_user_permission_groups,
    get_users_with_permission_group,
    add_permission_group_to_project_catalog,
    remove_permission_group_from_project_catalog,
    get_project_cataloged_permission_groups,
    get_permission_group_cataloged_projects,
    get_user_all_permissions,
    check_user_has_permission_extended,
    get_user_permission_sources
)
# Import core database connection
from src.Util.db_config import redis_client as client, get_connection
from src.Util.db_error_wrapper import handle_db_operation


# =================== USER TYPE HELPER FUNCTIONS ===================

def get_user_type_info(user_id: str) -> dict:
    """
    Get comprehensive user type information.
    
    Args:
        user_id: User ID
        
    Returns:
        Dictionary with user type information (error dict on failure)
        
    Raises:
        DatabaseError: On database operation errors
        
    Note:
        Returns error dict to prevent breaking callers.
    """
    def _get():
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
            # Root users have access to all projects
            result["accessible_projects"] = []  # Will be populated with all projects
            result["user_groups"] = []  # Root users don't need groups
            
        elif user_type == "admin":
            assigned_projects = get_admin_assigned_projects(user_id)
            result["assigned_project_ids"] = assigned_projects
            result["accessible_projects"] = assigned_projects
            result["capabilities"] = [
                "project_admin",
                "manage_project_users",
                "manage_project_groups",
                "manage_project_permissions"
            ]
            # Get user groups for admin users
            result["user_groups"] = [g.group_name for g in get_user_groups_for_user(user_id)]
            
        elif user_type == "consumer":
            # Get accessible projects through user groups
            accessible_projects = get_user_accessible_projects(user_id)
            result["accessible_projects"] = [p.id for p in accessible_projects]
            result["accessible_projects_details"] = [
                {
                    "project_id": p.id,
                    "project_hash": p.project_hash,
                    "project_name": p.project_name,
                    "project_description": p.project_description
                }
                for p in accessible_projects
            ]
            result["capabilities"] = [
                "global_role_permissions",
                "group_based_access",
                "project_access_via_groups"
            ]
            # Get user groups for consumer users
            result["user_groups"] = [g.group_name for g in get_user_groups_for_user(user_id)]

        return result
    
    return handle_db_operation(
        _get,
        error_context=f"get_user_type_info(user_id={user_id})",
        default_return={"user_type": None, "error": "Error retrieving user type info"}
    )


def check_user_type_permission(user_id: str, operation: str, project_id: str = None) -> bool:
    """
    Check if user has permission for operation based on their user type.
    
    Args:
        user_id: User ID
        operation: Operation to check (e.g., 'admin', 'manage_users', 'read')
        project_id: Project ID (required for admin and consumer users)
        
    Returns:
        Boolean indicating permission (False on error)
        
    Raises:
        DatabaseError: On database operation errors
        
    Note:
        Returns False on error to prevent unauthorized access.
    """
    def _check():
        user_type = get_user_type(user_id)

        # Root users can do anything
        if user_type == "root":
            return True

        # Admin users can do admin operations in their assigned project
        elif user_type == "admin":
            if not project_id:
                return False
            return check_admin_project_access(user_id, project_id)

        # Consumer users follow global role permissions
        elif user_type == "consumer":
            # Global role system - no project context needed for permission checks
            # Import global role functions
            try:
                from src.Util.db.db_global_roles import check_user_has_permission
                return check_user_has_permission(user_id, operation)
            except Exception:
                return False

        return False
    
    return handle_db_operation(
        _check,
        error_context=f"check_user_type_permission(user_id={user_id}, operation={operation})",
        default_return=False
    )


# =================== USER TYPE AWARE SESSION MANAGEMENT ===================

def create_user_type_session(user_id: str, project_id: str, session_length: int = 259200) -> dict:
    """
    Create session with user type context.
    
    Args:
        user_id: User ID
        project_id: Project ID
        session_length: Session duration in seconds
        
    Returns:
        Session information with user type context (None on error)
        
    Raises:
        NotFoundError: If user not found
        DatabaseError: On database operation errors
        
    Note:
        Returns None on error to indicate session creation failure.
    """
    def _create():
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
            # Get permissions from global role system
            try:
                from src.Util.db.db_global_roles import get_user_permissions
                session_data["permissions"] = get_user_permissions(user_id)
            except Exception:
                session_data["permissions"] = []

        return session_data
    
    return handle_db_operation(
        _create,
        error_context=f"create_user_type_session(user_id={user_id}, project_id={project_id})"
    )




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
    'create_root_session',
    'validate_root_session',
    'validate_admin_session',

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
    'list_users_with_access',
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
    'invalidate_user_sessions',

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
    # Project access via Groups-of-Groups architecture
    'get_projects_for_user_group',
    'get_user_groups_for_project',
    'get_user_accessible_projects',
    # Groups-of-Groups Architecture: User Group → Project Group access
    'grant_user_group_project_group_access',
    'revoke_user_group_project_group_access',
    'get_project_groups_for_user_group',
    'check_user_group_project_group_access',

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
    'get_user_effective_permissions',
    'check_user_project_permission',
    'check_user_permission',
    'create_default_permission_groups',

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
    
    # Permission Assignment System
    'assign_permission_group_to_user_group',
    'remove_permission_group_from_user_group',
    'get_user_group_permission_groups',
    'get_user_groups_with_permission_group',
    'assign_permission_group_to_user',
    'remove_permission_group_from_user',
    'get_user_permission_groups',
    'get_users_with_permission_group',
    'add_permission_group_to_project_catalog',
    'remove_permission_group_from_project_catalog',
    'get_project_cataloged_permission_groups',
    'get_permission_group_cataloged_projects',
    'get_user_all_permissions',
    'check_user_has_permission_extended',
    'get_user_permission_sources'
]
