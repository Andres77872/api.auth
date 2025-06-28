"""
Enhanced Multi-Project Authentication Database Module

This module provides database operations for the enhanced authentication system.
All operations use the multi-project architecture with user isolation and group-based permissions.
"""

# Import all enhanced database functions
from src.Util.db_enhanced import (
    # Core database functions
    get_connection,
    client,
    
    # Project management
    create_project,
    get_project_by_hash,
    
    # User management  
    create_user,
    get_user_by_credentials,
    check_username_email_available,
    
    # User-project access
    grant_user_project_access,
    get_user_project_access,
    get_user_projects,
    
    # Group management
    get_user_groups_in_project,
    get_user_permissions_in_project,
    
    # Authentication
    enhanced_login,
    enhanced_register,
    get_session_data,
    validate_session,
    
    # Legacy compatibility - these map to enhanced functions
    enhanced_login as db_login,
    enhanced_register as db_register,
    check_username_email_available as db_username_or_email_available
)

from src.Util.Models import UserLogin
import json


# Session management functions for backward compatibility
def set_session(key: int, value: str, ex: int, user_hash: str) -> bool:
    """
    Set session data in Redis cache.
    Enhanced system uses different session management, but this provides compatibility.
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
    Enhanced system uses validate_session() instead, but this provides compatibility.
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
    Enhanced system uses validate_session() instead, but this provides compatibility.
    """
    try:
        result = validate_session(user_session)
        return result is not None and result.user_hash == user_hash
    except Exception as e:
        print(f"Session validation error: {e}")
        return False


# Export all available functions
__all__ = [
    # Core database
    'get_connection',
    'client',
    
    # Project management
    'create_project',
    'get_project_by_hash',
    
    # User management
    'create_user',
    'get_user_by_credentials', 
    'check_username_email_available',
    
    # User-project access
    'grant_user_project_access',
    'get_user_project_access',
    'get_user_projects',
    
    # Group management
    'get_user_groups_in_project',
    'get_user_permissions_in_project',
    
    # Authentication
    'enhanced_login',
    'enhanced_register',
    'get_session_data',
    'validate_session',
    
    # Legacy compatibility
    'db_login',
    'db_register',
    'db_username_or_email_available',
    'set_session',
    'get_session',
    'db_validate_session'
]
