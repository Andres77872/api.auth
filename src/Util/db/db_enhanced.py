"""
Enhanced 3-Tier User Type Authentication - Main Database Module

This module provides the enhanced authentication system functions for the
3-tier user type model:
- ROOT USERS: Super administrators with unrestricted global access
- ADMIN USERS: Project-specific administrators limited to assigned projects  
- CONSUMER USERS: End users with RBAC-based permissions through groups

Key features:
- User type-aware login and registration
- Session management with user type context (1-hour cache)
- Permission checking based on user types with caching
- Legacy compatibility functions
- Cache-first access checks with automatic invalidation
"""

import json
import logging
import secrets
from typing import Optional

from src.Util.JWT_Security import JWTTokenHandler
from src.Util.Models import EnhancedUserLogin, UserLogin
from src.Util.cache_manager import cache_manager
# -- Database helpers --------------------------------------------------------
from src.Util.db.db_projects import (
    # Project operations
    get_project_by_hash,  # Re-export project functions
)

# User operations with user type support
from src.Util.db.db_users import (
    create_root_user, create_admin_user, create_consumer_user,
    get_user_by_credentials, check_username_email_available,
    get_user_type, get_admin_assigned_project,
    get_user_project_access,  # legacy accessor still used in some paths
    get_user_projects,  # used for available project listing
    get_session_data,
)

# NEW: user-group utilities --------------------------------------------------
from src.Util.db.db_user_groups import (
    get_user_group_by_hash,
    assign_user_to_group,
    get_projects_for_user_group,
    get_user_groups_in_project,
    get_user_groups_in_project_by_hash,
)

# Global role system permission resolver
from src.Util.db_config import redis_client as client


# Re-export database connection for backward compatibility


# =================== USER TYPE CHECKING FUNCTIONS ===================

def is_root_user(user_id: str) -> bool:
    """Check if user is a root user"""
    try:
        return get_user_type(user_id) == "root"
    except:
        return False


def is_admin_user(user_id: str) -> bool:
    """Check if user is an admin user"""
    try:
        return get_user_type(user_id) == "admin"
    except:
        return False


def is_consumer_user(user_id: str) -> bool:
    """Check if user is a consumer user"""
    try:
        return get_user_type(user_id) == "consumer"
    except:
        return False


def check_admin_project_access(user_id: str, project_id: str) -> bool:
    """Check if admin user has access to specific project (supports multiple projects)"""
    try:
        if not is_admin_user(user_id):
            return False
        from src.Util.db.db_users import check_admin_multi_project_access
        return check_admin_multi_project_access(user_id, project_id)
    except:
        return False


# =================== ENHANCED AUTHENTICATION WITH USER TYPES ===================

def enhanced_login(username: str, password: str, project_hash: str = None) -> Optional[EnhancedUserLogin]:
    """Enhanced login with 3-tier user type support"""
    # Get user by credentials
    user = get_user_by_credentials(username, password)
    if not user:
        return None

    # Get user type for permission checking
    user_type = get_user_type(user.id)

    # Handle root users who may not have a project_hash
    if user_type == "root":
        if not project_hash:
            # Root user global login - no specific project
            session_length = 60 * 60 * 24 * 7  # 7 days for root users
            session_id = secrets.randbelow(2 ** 31)  # Generate unique session ID for JWT

            # Create JWT token for root user global session
            session_token = JWTTokenHandler.create_access_token(
                session_id=session_id,
                user_hash=user.user_hash,
                collection="",  # Empty for global root session
            )

            # Build global session data for root user
            session_data = {
                'session_id': session_id,
                'user_id': user.id,
                'user_hash': user.user_hash,
                'user_type': 'root',
                'permissions': ['admin', 'global_admin', 'unrestricted_access'],
                'groups': ['root_users'],
                'is_global_session': True,
                'project_id': None,
                'project_hash': None
            }

            # Store session in cache and Redis
            cache_manager.set_session(session_token, session_data)
            client.set(f"session:{session_token}", json.dumps(session_data), ex=session_length)

            return EnhancedUserLogin(
                user_hash=user.user_hash,
                project_hash="",  # Empty for global root session
                project_name="Global Root Access",
                user_project_hash="",
                session_token=session_token,
                session_length=session_length,
                user_id=user.id,
                project_id=None,  # No specific project
                user_project_id=None,
                groups=['root_users'],
                permissions=['admin', 'global_admin', 'unrestricted_access'],
                available_projects=[],  # Root users can access all projects
                user_type='root',
                assigned_project_id=None
            )
        # If root user provided project_hash, continue with normal flow

    # For non-root users or root users with project context, project_hash is required
    if not project_hash:
        return None

    # Get project
    project = get_project_by_hash(project_hash)
    if not project:
        return None

    # Check access based on user type
    if user_type == "root":
        # Root users have access to all projects
        pass
    elif user_type == "admin":
        # Admin users can only access their assigned project
        if not check_admin_project_access(user.id, project.id):
            return None
    elif user_type == "consumer":
        # Consumer users need group-based access (no direct user_project records)
        groups = get_user_groups_in_project(user.id, project.id)
        if not groups:
            return None  # user not part of any group that grants project access

        # Resolve effective permissions via global role system
        try:
            from src.Util.db.db_global_roles import get_user_permissions
            permission_names = get_user_permissions(user.id)
        except Exception:
            permission_names = []

        # Prepare convenience collections ----------------------------------
        group_names = [g.group_name for g in groups]

        available_projects = [proj for proj, _ in get_user_projects(user.id)]

        # Consumer-specific session data additions
        session_specific = {
            'groups': group_names,
            'permissions': permission_names,
        }
    else:
        return None

    # ------------------------------------------------------------------
    # Shared session creation logic (moved outside the user_type blocks)
    # ------------------------------------------------------------------

    session_length = 60 * 60 * 24 * 3  # 3 days for project-scoped sessions
    session_id = secrets.randbelow(2 ** 31)

    session_token = JWTTokenHandler.create_access_token(
        session_id=session_id,
        user_hash=user.user_hash,
        collection=project.project_hash,
    )

    # Base payload
    session_data = {
        'session_id': session_id,
        'user_id': user.id,
        'user_hash': user.user_hash,
        'project_id': project.id,
        'project_hash': project.project_hash,
        'user_type': user_type,
    }

    # Merge user-type specific extras -----------------------------------
    if user_type == "root":
        session_data.update({
            'permissions': ['admin', 'global_admin', 'unrestricted_access'],
            'groups': ['root_users'],
        })
    elif user_type == "admin":
        available_projects = [project] if check_admin_project_access(user.id, project.id) else []
        session_data.update({
            'assigned_project_id': get_admin_assigned_project(user.id),
            'permissions': ['admin', 'project_admin', 'manage_users', 'manage_groups', 'manage_permissions'],
            'groups': ['project_admins'],
        })
    elif user_type == "consumer":
        session_data.update(session_specific)

    # Persist session -------------------------------------------------------
    cache_manager.set_session(session_token, session_data)  # cache (1-h default inside)
    client.set(f"session:{session_token}", json.dumps(session_data), ex=session_length)  # Redis store

    # Build response --------------------------------------------------------
    return EnhancedUserLogin(
        user_hash=user.user_hash,
        project_hash=project.project_hash,
        project_name=project.project_name,
        user_project_hash='',  # deprecated in group-based flow
        session_token=session_token,
        session_length=session_length,
        user_id=user.id,
        project_id=project.id,
        user_project_id=None,
        groups=session_data.get('groups', []),
        permissions=session_data.get('permissions', []),
        available_projects=available_projects,
        user_type=user_type,
        assigned_project_id=session_data.get('assigned_project_id'),
    )


def enhanced_register(
        username: str,
        password: str,
        email: str,
        group_hash: str,
        user_type: str = "consumer",
) -> Optional[EnhancedUserLogin]:
    """Register a new user, assign to a group, and create a session.

    This function creates a new user, assigns them to a specified user group,
    and then generates a session token for a default project associated with
    that group. This avoids issues with transactional visibility that can
    occur when calling enhanced_login immediately after registration.

    The supplied *group_hash* determines group membership and accessible projects.
    The first project linked to the group is used for the initial session.
    """
    # 1. Basic availability checks
    if not check_username_email_available(username) or \
       (email and not check_username_email_available(email)):
        return None

    # 2. Resolve target user group and default project
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        logging.debug(f"Group hash not found: {group_hash}")
        return None  # Unknown or inactive group

    grp_projects = get_projects_for_user_group(user_group.id)
    if not grp_projects:
        logging.debug(f"Group hash not linked to any projects: {group_hash}")
        return None  # Group must be linked to at least one project

    default_project_id, default_project_hash, project_name, _ = grp_projects[0]

    # 3. Create the user record
    user = None
    if user_type == "root":
        user = create_root_user(username, password, email)
    elif user_type == "admin":
        user = create_admin_user(username, password, email, assigned_project_id=default_project_id)
    else:  # Default to consumer
        user = create_consumer_user(username, password, email)

    if not user:
        logging.debug(f"Failed to create user: {username}")
        return None  # User creation failed

    # 4. Add the user to the requested group
    assign_user_to_group(user.id, user_group.id)

    # 5. Create session directly, bypassing enhanced_login
    session_length = 60 * 60 * 24 * 3  # 3 days for project-scoped sessions
    session_id = secrets.randbelow(2 ** 31)

    session_token = JWTTokenHandler.create_access_token(
        session_id=session_id,
        user_hash=user.user_hash,
        collection=default_project_hash,
    )

    # Base session payload
    session_data = {
        'session_id': session_id,
        'user_id': user.id,
        'user_hash': user.user_hash,
        'project_id': default_project_id,
        'project_hash': default_project_hash,
        'user_type': user_type,
    }

    # User-type specific session details
    groups = []
    permissions = []
    assigned_project_id = None
    available_projects = []

    if user_type == "consumer":
        # For new consumer, we know their group and can get permissions from global role system
        groups = [user_group.group_name]
        try:
            from src.Util.db.db_global_roles import get_user_permissions
            permissions = get_user_permissions(user.id)
        except Exception:
            permissions = []
        session_data.update({'groups': groups, 'permissions': permissions})
        # Get all projects accessible to the user
        available_projects = [proj for proj, _ in get_user_projects(user.id)]

    elif user_type == "admin":
        assigned_project_id = default_project_id
        groups = ['project_admins']
        permissions = ['admin', 'project_admin', 'manage_users', 'manage_groups', 'manage_permissions']
        session_data.update({
            'assigned_project_id': assigned_project_id,
            'permissions': permissions,
            'groups': groups,
        })
        available_projects = [proj for proj, _ in get_user_projects(user.id)]

    elif user_type == "root":
        groups = ['root_users']
        permissions = ['admin', 'global_admin', 'unrestricted_access']
        session_data.update({'groups': groups, 'permissions': permissions})
        # Root users can access all projects, so this list could be populated differently
        # For now, keeping it simple as per original logic.

    # Persist session
    cache_manager.set_session(session_token, session_data)
    client.set(f"session:{session_token}", json.dumps(session_data), ex=session_length)
    logging.debug(f"Created session for user {user.username} ({user.id})")
    # Build response object
    return EnhancedUserLogin(
        user_hash=user.user_hash,
        project_hash=default_project_hash,
        project_name=project_name,
        user_project_hash='',  # Deprecated
        session_token=session_token,
        session_length=session_length,
        user_id=user.id,
        project_id=default_project_id,
        user_project_id=None,  # Deprecated
        groups=groups,
        permissions=permissions,
        available_projects=available_projects,
        user_type=user_type,
        assigned_project_id=assigned_project_id,
    )


def validate_session(session_token: str) -> Optional[EnhancedUserLogin]:
    """Validate a session token and return user data with user type context (cache-first)"""
    # Try cache first
    session_data = cache_manager.get_session(session_token)

    # If not in cache, check database/Redis
    if not session_data:
        session_data = get_session_data(session_token)
        if not session_data:
            return None

        # Cache the session data for future requests
        cache_manager.set_session(session_token, session_data)

    user_type = session_data.get('user_type', 'consumer')

    # Handle global root sessions (no project context)
    if user_type == 'root':
        return EnhancedUserLogin(
            user_hash=session_data['user_hash'],
            project_hash="",  # Empty for global session
            project_name="Global Root Access",
            user_project_hash="",
            session_token=session_token,
            session_length=0,  # We don't track remaining time
            user_id=session_data['user_id'],
            project_id=None,  # No specific project
            user_project_id=None,
            groups=['root_users'],
            permissions=['admin', 'global_admin', 'unrestricted_access'],
            available_projects=[],  # Root users can access all projects
            user_type='root',
            assigned_project_id=None
        )

    # For sessions with project context, get fresh project data
    project_hash = session_data.get('project_hash')
    if not project_hash:
        return None

    project = get_project_by_hash(project_hash)
    if not project:
        return None

    # Validate access based on user type
    if user_type == "root":
        # Root users always have access
        groups = session_data.get('groups', ['root_users'])
        permissions = session_data.get('permissions', ['admin', 'global_admin'])
        available_projects = []  # Root users can access all projects
    elif user_type == "admin":
        # Validate admin user still has access to project
        if not check_admin_project_access(session_data['user_id'], project.id):
            return None
        groups = session_data.get('groups', ['project_admins'])
        permissions = session_data.get('permissions', ['admin', 'project_admin'])
        available_projects = [project]
    elif user_type == "consumer":
        # Resolve group memberships and permissions dynamically (group-based)
        groups_objs = get_user_groups_in_project_by_hash(session_data['user_id'], project_hash)
        if not groups_objs:
            return None

        groups = [g.group_name for g in groups_objs]
        # Get permissions from global role system
        try:
            from src.Util.db.db_global_roles import get_user_permissions
            permissions = get_user_permissions(session_data['user_id'])
        except Exception:
            permissions = []
        available_projects = [proj for proj, _ in get_user_projects(session_data['user_id'])]
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


# =================== USER TYPE SPECIFIC FUNCTIONS ===================

def create_root_session(username: str, password: str) -> Optional[dict]:
    """Create a special root session that can access any project"""
    user = get_user_by_credentials(username, password)
    if not user or not is_root_user(user.id):
        return None

    session_length = 60 * 60 * 24 * 7  # 7 days for root users
    session_id = secrets.randbelow(2 ** 31)  # Generate unique session ID for JWT

    # Create JWT token for root user global session
    session_token = JWTTokenHandler.create_access_token(
        session_id=session_id,
        user_hash=user.user_hash,
        collection="",  # Empty for global root session
    )

    session_data = {
        'session_id': session_id,
        'user_id': user.id,
        'user_hash': user.user_hash,
        'user_type': 'root',
        'permissions': ['admin', 'global_admin', 'unrestricted_access'],
        'groups': ['root_users'],
        'is_global_session': True,
        'project_id': None,
        'project_hash': None
    }

    # Store in both cache and Redis
    cache_manager.set_session(session_token, session_data)
    client.set(f"session:{session_token}", json.dumps(session_data), ex=session_length)

    return {
        'session_token': session_token,
        'user_type': 'root',
        'permissions': session_data['permissions'],
        'expires_in': session_length,
        'user_hash': user.user_hash,
        'username': user.username,
        'email': user.email
    }


def validate_root_session(session_token: str) -> bool:
    """Validate if session belongs to a root user"""
    try:
        session_data = get_session_data(session_token)
        return session_data and session_data.get('user_type') == 'root'
    except:
        return False


def validate_admin_session(session_token: str, project_id: str) -> bool:
    """Validate if session belongs to admin user with access to project"""
    try:
        session_data = get_session_data(session_token)
        if not session_data:
            return False

        user_type = session_data.get('user_type')
        if user_type == 'root':
            return True
        elif user_type == 'admin':
            return session_data.get('assigned_project_id') == project_id

        return False
    except:
        return False


# =================== LEGACY COMPATIBILITY WITH USER TYPES ===================

def db_login(user: str, password: str, collection: str) -> Optional[UserLogin]:
    """Legacy login function for backward compatibility with user type support"""
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
            groups=enhanced_result.groups,
            user_type=enhanced_result.user_type,  # NEW: Include user type
            assigned_project_id=enhanced_result.assigned_project_id  # NEW: For admin users
        )
    return None


def db_register(collection: str, user: str, password: str, email: str = None, user_type: str = "consumer") -> Optional[
    UserLogin]:
    """Legacy register function for backward compatibility with user type support"""
    enhanced_result = enhanced_register(user, password, email, collection, user_type)
    if enhanced_result:
        return UserLogin(
            user_session=enhanced_result.session_token,
            user_session_length=enhanced_result.session_length,
            user_hash=enhanced_result.user_hash,
            user_collection=enhanced_result.project_hash,
            user_id=enhanced_result.user_id,
            project_id=enhanced_result.project_id,
            user_project_id=enhanced_result.user_project_id,
            groups=enhanced_result.groups,
            user_type=enhanced_result.user_type,
            assigned_project_id=enhanced_result.assigned_project_id
        )
    return None


def db_username_or_email_available(username_or_email: str, collection: str = None) -> bool:
    """Legacy function for checking username/email availability"""
    return check_username_email_available(username_or_email)
