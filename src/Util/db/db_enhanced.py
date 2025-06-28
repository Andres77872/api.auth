"""
Enhanced Multi-Project Authentication - Main Database Module

This module provides the enhanced authentication system functions that require
both user and project operations. It imports from specialized modules:
- db_users.py: User management operations
- db_projects.py: Project management operations

Key features:
- Enhanced login and registration with multi-project support
- Session management and validation
- Legacy compatibility functions
"""

import json
import secrets
from typing import Optional

# Import specialized modules
from src.Util.db.db_users import (
    # User operations
    create_user, get_user_by_credentials, check_username_email_available,
    grant_user_project_access, get_user_projects, get_user_groups_in_project,
    get_user_permissions_in_project, get_session_data, client,
    
    # Re-export user functions
    get_user_project_access
)

from src.Util.db.db_projects import (
    # Project operations  
    get_project_by_hash,  # Re-export project functions
)

from src.Util.Models import EnhancedUserLogin, UserLogin


# Re-export database connection for backward compatibility


# =================== ENHANCED AUTHENTICATION ===================

def enhanced_login(username: str, password: str, project_hash: str) -> Optional[EnhancedUserLogin]:
    """Enhanced login with multi-project support"""
    # Get user by credentials
    user = get_user_by_credentials(username, password)
    if not user:
        return None
    
    # Get project
    project = get_project_by_hash(project_hash)
    if not project:
        return None
    
    # Check if user has access to this project
    user_project = get_user_project_access(user.id, project.id)
    if not user_project:
        return None
    
    # Get user's groups and permissions in this project
    groups = get_user_groups_in_project(user_project.id)
    permissions = get_user_permissions_in_project(user_project.id)
    
    # Get all projects user has access to
    available_projects = [proj for proj, _ in get_user_projects(user.id)]
    
    # Create session
    session_token = secrets.token_hex(32).upper()
    session_length = 60 * 60 * 24 * 3  # 3 days
    
    # Store session in Redis
    session_data = {
        'user_id': user.id,
        'user_hash': user.user_hash,
        'project_id': project.id,
        'project_hash': project.project_hash,
        'user_project_id': user_project.id,
        'user_project_hash': user_project.user_project_hash,
        'groups': [g.group_name for g in groups],
        'permissions': permissions
    }
    
    client.set(f"session:{session_token}", json.dumps(session_data), ex=session_length)
    
    return EnhancedUserLogin(
        user_hash=user.user_hash,
        project_hash=project.project_hash,
        project_name=project.project_name,
        user_project_hash=user_project.user_project_hash,
        session_token=session_token,
        session_length=session_length,
        user_id=user.id,
        project_id=project.id,
        user_project_id=user_project.id,
        groups=[g.group_name for g in groups],
        permissions=permissions,
        available_projects=available_projects
    )


def enhanced_register(username: str, password: str, email: str, project_hash: str) -> Optional[EnhancedUserLogin]:
    """Enhanced registration with multi-project support"""
    # Check if username/email is available
    if not check_username_email_available(username) or (email and not check_username_email_available(email)):
        return None
    
    # Get or create project
    project = get_project_by_hash(project_hash)
    if not project:
        return None
    
    # Create user
    user = create_user(username, password, email)
    
    # Grant user access to the project
    user_project = grant_user_project_access(user.id, project.id)
    
    # Continue with login flow
    return enhanced_login(username, password, project_hash)


def validate_session(session_token: str) -> Optional[EnhancedUserLogin]:
    """Validate a session token and return user data"""
    session_data = get_session_data(session_token)
    if not session_data:
        return None
    
    # Get fresh project data
    project = get_project_by_hash(session_data['project_hash'])
    if not project:
        return None
    
    # Get fresh user groups and permissions
    groups = get_user_groups_in_project(session_data['user_project_id'])
    permissions = get_user_permissions_in_project(session_data['user_project_id'])
    
    # Get available projects
    available_projects = [proj for proj, _ in get_user_projects(session_data['user_id'])]
    
    return EnhancedUserLogin(
        user_hash=session_data['user_hash'],
        project_hash=session_data['project_hash'],
        project_name=project.project_name,
        user_project_hash=session_data['user_project_hash'],
        session_token=session_token,
        session_length=0,  # We don't track remaining time
        user_id=session_data['user_id'],
        project_id=session_data['project_id'],
        user_project_id=session_data['user_project_id'],
        groups=[g.group_name for g in groups],
        permissions=permissions,
        available_projects=available_projects
    )


# =================== LEGACY COMPATIBILITY ===================

def db_login(user: str, password: str, collection: str) -> Optional[UserLogin]:
    """Legacy login function for backward compatibility"""
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
            groups=enhanced_result.groups
        )
    return None


def db_register(collection: str, user: str, password: str, email: str = None) -> Optional[UserLogin]:
    """Legacy register function for backward compatibility"""
    enhanced_result = enhanced_register(user, password, email, collection)
    if enhanced_result:
        return UserLogin(
            user_session=enhanced_result.session_token,
            user_session_length=enhanced_result.session_length,
            user_hash=enhanced_result.user_hash,
            user_collection=enhanced_result.project_hash,
            user_id=enhanced_result.user_id,
            project_id=enhanced_result.project_id,
            user_project_id=enhanced_result.user_project_id,
            groups=enhanced_result.groups
        )
    return None


def db_username_or_email_available(username_or_email: str, collection: str) -> bool:
    """Legacy function for checking username/email availability"""
    return check_username_email_available(username_or_email) 