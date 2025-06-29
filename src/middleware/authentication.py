"""
Authentication Middleware

Provides authentication and authorization middleware for API endpoints.
Handles session validation and user type checking.
"""

from typing import Dict, Any, Optional

from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.Util.db import validate_session, is_root_user, is_admin_user

# HTTP Bearer token security
security = HTTPBearer()


async def verify_session(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    """
    Verify user session and return user data
    
    Args:
        credentials: HTTP Bearer token
        
    Returns:
        User session data
        
    Raises:
        HTTPException: If session is invalid
    """
    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)

        if not session_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired session",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return {
            "user_id": session_data.user_id,
            "user_hash": session_data.user_hash,
            "user_type": session_data.user_type,
            "project_id": session_data.project_id,
            "project_hash": session_data.project_hash,
            "permissions": session_data.permissions,
            "groups": session_data.groups,
            "session_token": session_token
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Session validation error: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def verify_admin_access(current_user: Dict[str, Any] = Depends(verify_session)) -> Dict[str, Any]:
    """
    Verify user has admin access (root or admin user types)
    
    Args:
        current_user: User session data from verify_session
        
    Returns:
        User session data if user has admin access
        
    Raises:
        HTTPException: If user doesn't have admin access
    """
    try:
        user_type = current_user.get("user_type")
        user_id = current_user.get("user_id")
        permissions = current_user.get("permissions", [])

        # Check if user is root or admin type
        if user_type in ["root", "admin"]:
            return current_user

        # Check if user has admin permissions
        if "admin" in permissions or "global_admin" in permissions:
            return current_user

        # Additional check using database functions
        if user_id and (is_root_user(user_id) or is_admin_user(user_id)):
            return current_user

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Authorization error: {str(e)}"
        )


async def verify_root_access(current_user: Dict[str, Any] = Depends(verify_session)) -> Dict[str, Any]:
    """
    Verify user has root access (root user type only)
    
    Args:
        current_user: User session data from verify_session
        
    Returns:
        User session data if user has root access
        
    Raises:
        HTTPException: If user doesn't have root access
    """
    try:
        user_type = current_user.get("user_type")
        user_id = current_user.get("user_id")
        permissions = current_user.get("permissions", [])

        # Check if user is root type
        if user_type == "root":
            return current_user

        # Check if user has global admin permissions
        if "global_admin" in permissions:
            return current_user

        # Additional check using database functions
        if user_id and is_root_user(user_id):
            return current_user

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Root access required"
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Root authorization error: {str(e)}"
        )


async def verify_project_access(
        project_id: int,
        current_user: Dict[str, Any] = Depends(verify_session)
) -> Dict[str, Any]:
    """
    Verify user has access to a specific project
    
    Args:
        project_id: Project ID to check access for
        current_user: User session data from verify_session
        
    Returns:
        User session data if user has project access
        
    Raises:
        HTTPException: If user doesn't have project access
    """
    try:
        user_type = current_user.get("user_type")
        user_id = current_user.get("user_id")
        user_project_id = current_user.get("project_id")

        # Root users have access to all projects
        if user_type == "root":
            return current_user

        # Admin users have access to their assigned projects
        if user_type == "admin":
            from src.Util.db import check_admin_project_access
            if check_admin_project_access(user_id, project_id):
                return current_user

        # Consumer users have access through their project assignments
        if user_type == "consumer":
            if user_project_id == project_id:
                return current_user

            # Check if user has access to this project through user-project relationships
            from src.Util.db import get_user_project_access
            user_project = get_user_project_access(user_id, project_id)
            if user_project and user_project.is_active:
                return current_user

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied to project {project_id}"
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Project access verification error: {str(e)}"
        )


def require_permission(permission: str):
    """
    Create a dependency that requires a specific permission
    
    Args:
        permission: Permission name to check
        
    Returns:
        Dependency function
    """

    async def verify_permission(current_user: Dict[str, Any] = Depends(verify_session)) -> Dict[str, Any]:
        try:
            permissions = current_user.get("permissions", [])

            # Check if user has the required permission
            if permission in permissions:
                return current_user

            # Admin and global_admin permissions grant all access
            if "admin" in permissions or "global_admin" in permissions:
                return current_user

            # Check permission through RBAC system for consumer users
            user_type = current_user.get("user_type")
            if user_type == "consumer":
                user_id = current_user.get("user_id")
                project_id = current_user.get("project_id")

                if user_id and project_id:
                    from src.Util.db import check_user_permission
                    if check_user_permission(user_id, project_id, permission):
                        return current_user

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{permission}' required"
            )

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission verification error: {str(e)}"
            )

    return verify_permission


# Optional authentication (for endpoints that work with or without auth)
async def optional_auth(credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False))) -> \
Optional[Dict[str, Any]]:
    """
    Optional authentication - returns user data if authenticated, None otherwise
    
    Args:
        credentials: Optional HTTP Bearer token
        
    Returns:
        User session data if authenticated, None otherwise
    """
    if not credentials:
        return None

    try:
        session_token = credentials.credentials
        session_data = validate_session(session_token)

        if session_data:
            return {
                "user_id": session_data.user_id,
                "user_hash": session_data.user_hash,
                "user_type": session_data.user_type,
                "project_id": session_data.project_id,
                "project_hash": session_data.project_hash,
                "permissions": session_data.permissions,
                "groups": session_data.groups,
                "session_token": session_token
            }
    except Exception:
        pass  # Ignore errors for optional auth

    return None
