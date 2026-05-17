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
import os
import secrets
import time
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
    get_session_data,
)

# User-group utilities
from src.Util.db.db_user_groups import (
    get_user_group_by_hash,
    assign_user_to_group,
    get_projects_for_user_group,
    get_user_groups_in_project,
    get_user_groups_in_project_by_hash,
    get_user_accessible_projects,  # canonical function for user project access
)

# Global role system permission resolver
from src.Util.db_config import redis_client as client

# Initialize logger
logger = logging.getLogger(__name__)

# Phase 2.1: Feature flag for cache-first validation
VALIDATE_CACHE_ENABLED = os.environ.get("VALIDATE_CACHE_ENABLED", "true").lower() in ("true", "1", "yes")

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

    # For non-root users, project_hash is required
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
        # Graceful degradation: if global roles fail, continue with empty permissions
        try:
            from src.Util.db.db_global_roles import get_user_permissions
            permission_names = get_user_permissions(user.id)
        except Exception as e:
            logger.warning(f"Failed to load global role permissions for user {user.id}: {str(e)}")
            permission_names = []

        # Prepare convenience collections ----------------------------------
        group_names = [g.group_name for g in groups]

        available_projects = get_user_accessible_projects(user.id)

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
    if grp_projects:
        default_project_id, default_project_hash, project_name, _ = grp_projects[0]
    else:
        default_project_id, default_project_hash, project_name = None, None, None

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
        # Graceful degradation: if global roles fail, continue with empty permissions
        try:
            from src.Util.db.db_global_roles import get_user_permissions
            permissions = get_user_permissions(user.id)
        except Exception as e:
            logger.warning(f"Failed to load global role permissions for user {user.id}: {str(e)}")
            permissions = []
        session_data.update({'groups': groups, 'permissions': permissions})
        # Get all projects accessible to the user
        available_projects = get_user_accessible_projects(user.id)

    elif user_type == "admin":
        assigned_project_id = default_project_id
        groups = ['project_admins']
        permissions = ['admin', 'project_admin', 'manage_users', 'manage_groups', 'manage_permissions']
        session_data.update({
            'assigned_project_id': assigned_project_id,
            'permissions': permissions,
            'groups': groups,
        })
        available_projects = get_user_accessible_projects(user.id)

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


# Phase 0.8: Module-level call counter for validate_session()
_validation_call_counter: int = 0


def validate_session(session_token: str) -> Optional[EnhancedUserLogin]:
    """Validate a session token and return user data with user type context (cache-first)"""
    global _validation_call_counter
    _validation_call_counter += 1

    t_total = time.monotonic()

    # Phase 2.1: Try full-session cache first (serialized EnhancedUserLogin)
    if VALIDATE_CACHE_ENABLED:
        cached_full = cache_manager.get_session_full(session_token)
        if cached_full is not None:
            duration_ms = (time.monotonic() - t_total) * 1000
            logger.info(f"AUTH_PERF|validate_session|hit|{duration_ms:.3f}")
            return cached_full

    cache_hit = True

    # Try cache first (raw session dict)
    session_data = cache_manager.get_session(session_token)
    
    # If not in cache, check database/Redis
    if not session_data:
        cache_hit = False
        session_data = get_session_data(session_token)
        if not session_data:
            return None

        # Cache the session data for future requests
        cache_manager.set_session(session_token, session_data)

    user_type = session_data.get('user_type', 'consumer')
    scope = session_data.get('scope')

    if scope == 'platform':
        if user_type not in {'root', 'admin'}:
            return None

        groups = session_data.get('groups', ['platform_admins'])
        if user_type == 'root':
            permissions = session_data.get('permissions', ['admin', 'global_admin', 'manage_users', 'manage_roles'])
        else:
            permissions = session_data.get('permissions', ['admin', 'project_admin', 'manage_users', 'manage_roles'])

        duration_ms = (time.monotonic() - t_total) * 1000
        outcome = "hit" if cache_hit else "miss"
        login_data = EnhancedUserLogin(
            user_hash=session_data['user_hash'],
            scope='platform',
            project_hash=None,
            project_name=None,
            user_project_hash=session_data.get('user_project_hash', ''),
            session_token=session_token,
            session_length=0,  # We don't track remaining time
            user_id=session_data['user_id'],
            project_id=None,
            user_project_id=session_data.get('user_project_id'),
            groups=groups,
            permissions=permissions,
            available_projects=[],
            user_type=user_type,
            assigned_project_id=session_data.get('assigned_project_id')
        )
        # Phase 2.1: Cache full result for subsequent requests
        if VALIDATE_CACHE_ENABLED:
            cache_manager.set_session_full(session_token, login_data)
        logger.info(f"AUTH_PERF|validate_session|{outcome}|{duration_ms:.3f}")
        return login_data

    # For sessions with project context, get fresh project data
    project_hash = session_data.get('project_hash')
    if not project_hash:
        return None

    # Phase 0.3: Time individual queries
    t0 = time.monotonic()
    project = get_project_by_hash(project_hash)
    logger.info(f"AUTH_PERF|query_project|{(time.monotonic() - t0) * 1000:.3f}")
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
        t0 = time.monotonic()
        access_granted = check_admin_project_access(session_data['user_id'], project.id)
        logger.info(f"AUTH_PERF|query_access|{(time.monotonic() - t0) * 1000:.3f}")
        if not access_granted:
            return None
        groups = session_data.get('groups', ['project_admins'])
        permissions = session_data.get('permissions', ['admin', 'project_admin', 'manage_users', 'manage_roles'])
        # Use get_user_accessible_projects to return proper ProjectSummary objects
        # (not raw Project objects which lack project_group_name field)
        t0 = time.monotonic()
        available_projects = get_user_accessible_projects(session_data['user_id'])
        logger.info(f"AUTH_PERF|query_projects|{(time.monotonic() - t0) * 1000:.3f}")
    elif user_type == "consumer":
        # Resolve group memberships and permissions dynamically (group-based)
        t0 = time.monotonic()
        groups_objs = get_user_groups_in_project_by_hash(session_data['user_id'], project_hash)
        logger.info(f"AUTH_PERF|query_access|{(time.monotonic() - t0) * 1000:.3f}")
        if not groups_objs:
            return None

        groups = [g.group_name for g in groups_objs]
        # Get permissions from global role system
        # Graceful degradation: if global roles fail, continue with empty permissions
        try:
            from src.Util.db.db_global_roles import get_user_permissions
            t0 = time.monotonic()
            permissions = get_user_permissions(session_data['user_id'])
            logger.info(f"AUTH_PERF|query_permissions|{(time.monotonic() - t0) * 1000:.3f}")
        except Exception as e:
            logger.warning(f"Failed to load global role permissions for user {session_data['user_id']}: {str(e)}")
            permissions = []
        t0 = time.monotonic()
        available_projects = get_user_accessible_projects(session_data['user_id'])
        logger.info(f"AUTH_PERF|query_projects|{(time.monotonic() - t0) * 1000:.3f}")
    else:
        return None

    duration_ms = (time.monotonic() - t_total) * 1000
    outcome = "hit" if cache_hit else "miss"
    login_data = EnhancedUserLogin(
        user_hash=session_data['user_hash'],
        scope=scope,
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
    # Phase 2.1: Cache full result for subsequent requests
    if VALIDATE_CACHE_ENABLED:
        cache_manager.set_session_full(session_token, login_data)
    logger.info(f"AUTH_PERF|validate_session|{outcome}|{duration_ms:.3f}")
    return login_data


# =================== USER TYPE SPECIFIC FUNCTIONS ===================

