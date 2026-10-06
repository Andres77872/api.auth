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
- Cache-first access checks with automatic invalidation
"""

import logging
import time
from typing import Optional

from fastapi import HTTPException

from src.Util.Models import EnhancedUserLogin
from src.Util.auth_lifecycle import issue_project_token_pair, validate_access_session
# -- Database helpers --------------------------------------------------------
from src.Util.db.db_projects import (
    # Project operations
    get_project_by_hash,  # Re-export project functions
)

# User operations with user type support
from src.Util.db.db_users import create_consumer_user, check_username_email_available, get_user_by_hash, get_user_type

# User-group utilities
from src.Util.db.db_user_groups import (
    get_user_group_by_hash,
    assign_user_to_group,
    get_projects_for_user_group,
    get_user_groups_in_project,
    get_user_groups_in_project_by_hash,
    get_user_accessible_projects,  # canonical function for user project access
)

# Initialize logger
logger = logging.getLogger(__name__)


# =================== USER TYPE CHECKING FUNCTIONS ===================

def is_root_user(user_id: str) -> bool:
    """Check if user is a root user"""
    try:
        return get_user_type(user_id) == "root"
    except Exception:
        logger.error(f"is_root_user: DB error for user_id={user_id}", exc_info=True)
        raise


def is_admin_user(user_id: str) -> bool:
    """Check if user is an admin user"""
    try:
        return get_user_type(user_id) == "admin"
    except Exception:
        logger.error(f"is_admin_user: DB error for user_id={user_id}", exc_info=True)
        raise


def is_consumer_user(user_id: str) -> bool:
    """Check if user is a consumer user"""
    try:
        return get_user_type(user_id) == "consumer"
    except Exception:
        logger.error(f"is_consumer_user: DB error for user_id={user_id}", exc_info=True)
        raise


def check_admin_project_access(user_id: str, project_id: str) -> bool:
    """Check if admin user has access to specific project (supports multiple projects)"""
    try:
        if not is_admin_user(user_id):
            return False
        from src.Util.db.db_users import check_admin_multi_project_access
        return check_admin_multi_project_access(user_id, project_id)
    except Exception:
        logger.error(f"check_admin_project_access: error user_id={user_id} project_id={project_id}", exc_info=True)
        raise


# =================== ENHANCED AUTHENTICATION WITH USER TYPES ===================


def enhanced_register(
        username: str,
        password: str,
        group_hash: str,
) -> Optional[EnhancedUserLogin]:
    """Register a new user, assign to a group, and create a session.

    This function creates a new user, assigns them to a specified user group,
    and issues an access/refresh token pair for the first project associated
    with that group. Email addresses are enrolled through the activation flow.

    The supplied *group_hash* determines group membership and accessible projects.
    The first project linked to the group is used for the initial session.
    """
    # 1. Basic availability checks
    if not check_username_email_available(username):
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

    # Create a consumer account; privileged accounts use root-authorized admin routes.
    user = create_consumer_user(username, password)

    if not user:
        logging.debug(f"Failed to create user: {username}")
        return None  # User creation failed

    # 4. Add the user to the requested group
    assign_user_to_group(user.id, user_group.id)

    # 5. Build registration context. Project-scoped registrations issue the
    # same lifecycle token pair as login.
    groups = [user_group.group_name]
    from src.Util.db.db_global_roles import get_user_permissions
    permissions = get_user_permissions(user.id)
    available_projects = get_user_accessible_projects(user.id)
    token_pair = None
    if default_project_hash:
        token_pair = issue_project_token_pair(
            user=user,
            project={
                "id": default_project_id,
                "project_hash": default_project_hash,
                "project_name": project_name,
            },
            permissions=permissions,
            groups=groups,
        )
        logging.debug(f"Created lifecycle token pair for registered user {user.username} ({user.id})")

    # Build response object
    return EnhancedUserLogin(
        user_hash=user.user_hash,
        username=username,
        project_hash=default_project_hash,
        project_name=project_name,
        access_token=token_pair.access_token if token_pair else "",
        session_length=token_pair.expires_in if token_pair else 0,
        user_id=user.id,
        project_id=default_project_id,
        groups=groups,
        permissions=permissions,
        available_projects=available_projects,
        user_type="consumer",

        refresh_token=token_pair.refresh_token if token_pair else None,
        token_type=token_pair.token_type if token_pair else "Bearer",
        expires_in=token_pair.expires_in if token_pair else None,
        refresh_expires_in=token_pair.refresh_expires_in if token_pair else None,
        expires_at=token_pair.expires_at if token_pair else None,
        refresh_expires_at=token_pair.refresh_expires_at if token_pair else None,
        remember_me=token_pair.remember_me if token_pair else False,
        cookie_metadata=token_pair.cookie_metadata if token_pair else {},
    )


# Phase 0.8: Module-level call counter for validate_session()
_validation_call_counter: int = 0


# =================== USER TYPE SPECIFIC FUNCTIONS ===================


def validate_session(access_token: str) -> Optional[EnhancedUserLogin]:
    """Validate an access JWT against the current session and refresh family."""
    global _validation_call_counter
    _validation_call_counter += 1
    started = time.monotonic()
    if not isinstance(access_token, str) or access_token.count('.') != 2:
        raise HTTPException(status_code=401, detail='Invalid access token')
    result = validate_access_session(
        access_token,
        get_user_by_hash_fn=get_user_by_hash,
        get_project_by_hash_fn=get_project_by_hash,
        check_admin_project_access_fn=check_admin_project_access,
        get_user_groups_in_project_by_hash_fn=get_user_groups_in_project_by_hash,
        get_user_accessible_projects_fn=get_user_accessible_projects,
    )
    logger.info('AUTH_PERF|validate_session|canonical|%.3f', (time.monotonic() - started) * 1000)
    return result
