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
import secrets
from typing import Optional

# Import specialized modules
from src.Util.db.db_users import (
    # User operations with user type support
    create_user, create_root_user, create_admin_user, create_consumer_user,
    get_user_by_credentials, check_username_email_available,
    get_user_type, get_admin_assigned_project,
    grant_user_project_access, get_user_projects, get_user_groups_in_project,
    get_user_permissions_in_project, get_session_data,
    
    # Re-export user functions
    get_user_project_access
)
from src.Util.db_config import redis_client as client
from src.Util.cache_manager import cache_manager

from src.Util.db.db_projects import (
    # Project operations  
    get_project_by_hash,  # Re-export project functions
)

from src.Util.Models import EnhancedUserLogin, UserLogin


# Re-export database connection for backward compatibility


# =================== USER TYPE CHECKING FUNCTIONS ===================

def is_root_user(user_id: int) -> bool:
    """Check if user is a root user"""
    try:
        return get_user_type(user_id) == "root"
    except:
        return False


def is_admin_user(user_id: int) -> bool:
    """Check if user is an admin user"""
    try:
        return get_user_type(user_id) == "admin"
    except:
        return False


def is_consumer_user(user_id: int) -> bool:
    """Check if user is a consumer user"""
    try:
        return get_user_type(user_id) == "consumer"
    except:
        return False


def check_admin_project_access(user_id: int, project_id: int) -> bool:
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
            session_token = secrets.token_hex(32).upper()
            session_length = 60 * 60 * 24 * 7  # 7 days for root users
            
            # Build global session data for root user
            session_data = {
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
        # Consumer users need group-based access
        user_project = get_user_project_access(user.id, project.id)
        if not user_project:
            return None
    else:
        return None
    
    # Create session with user type context
    session_token = secrets.token_hex(32).upper()
    session_length = 60 * 60 * 24 * 3  # 3 days
    
    # Build session data based on user type
    session_data = {
        'user_id': user.id,
        'user_hash': user.user_hash,
        'project_id': project.id,
        'project_hash': project.project_hash,
        'user_type': user_type
    }
    
    # Add user type specific data
    if user_type == "root":
        session_data['permissions'] = ['admin', 'global_admin', 'unrestricted_access']
        session_data['groups'] = ['root_users']
        available_projects = []  # Root users can access all projects
    elif user_type == "admin":
        session_data['assigned_project_id'] = get_admin_assigned_project(user.id)
        session_data['permissions'] = ['admin', 'project_admin', 'manage_users', 'manage_groups', 'manage_permissions']
        session_data['groups'] = ['project_admins']
        # Admin users only see their assigned project
        available_projects = [project] if check_admin_project_access(user.id, project.id) else []
    elif user_type == "consumer":
        user_project = get_user_project_access(user.id, project.id)
        session_data['user_project_id'] = user_project.id
        session_data['user_project_hash'] = user_project.user_project_hash
        groups = get_user_groups_in_project(user_project.id)
        permissions = get_user_permissions_in_project(user_project.id)
        session_data['groups'] = [g.group_name for g in groups]
        session_data['permissions'] = permissions
        available_projects = [proj for proj, _ in get_user_projects(user.id)]
    
    # Store session in cache with 1-hour TTL
    cache_manager.set_session(session_token, session_data)
    
    # Also store in legacy Redis format for backward compatibility
    client.set(f"session:{session_token}", json.dumps(session_data), ex=session_length)
    
    return EnhancedUserLogin(
        user_hash=user.user_hash,
        project_hash=project.project_hash,
        project_name=project.project_name,
        user_project_hash=session_data.get('user_project_hash', ''),
        session_token=session_token,
        session_length=session_length,
        user_id=user.id,
        project_id=project.id,
        user_project_id=session_data.get('user_project_id'),
        groups=session_data.get('groups', []),
        permissions=session_data.get('permissions', []),
        available_projects=available_projects,
        user_type=user_type,  # NEW: Include user type
        assigned_project_id=session_data.get('assigned_project_id')  # NEW: For admin users
    )


def enhanced_register(username: str, password: str, email: str, project_hash: str, user_type: str = "consumer") -> Optional[EnhancedUserLogin]:
    """Enhanced registration with 3-tier user type support"""
    # Check if username/email is available
    if not check_username_email_available(username) or (email and not check_username_email_available(email)):
        return None
    
    # Get or validate project
    project = get_project_by_hash(project_hash)
    if not project:
        return None
    
    # Create user based on type
    if user_type == "root":
        user = create_root_user(username, password, email)
    elif user_type == "admin":
        user = create_admin_user(username, password, email, project.id)
    else:  # consumer (default)
        user = create_consumer_user(username, password, email)
        # Grant user access to the project for consumer users
        grant_user_project_access(user.id, project.id)
    
    # Continue with login flow
    return enhanced_login(username, password, project_hash)


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
    if user_type == 'root' and session_data.get('is_global_session'):
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
        # Get fresh user groups and permissions for consumer users
        if 'user_project_id' not in session_data:
            return None
        groups = get_user_groups_in_project(session_data['user_project_id'])
        permissions = get_user_permissions_in_project(session_data['user_project_id'])
        available_projects = [proj for proj, _ in get_user_projects(session_data['user_id'])]
        groups = [g.group_name for g in groups]
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
    
    session_token = secrets.token_hex(32).upper()
    session_length = 60 * 60 * 24 * 7  # 7 days for root users
    
    session_data = {
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


def validate_admin_session(session_token: str, project_id: int) -> bool:
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


def db_register(collection: str, user: str, password: str, email: str = None, user_type: str = "consumer") -> Optional[UserLogin]:
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