"""
Authentication Middleware

Provides authentication and authorization middleware for API endpoints.
Handles session validation, user type checking, and API key authentication.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, APIKeyHeader

from src.Util.db import validate_session, is_root_user, is_admin_user
from src.Util.db.db_api_keys import validate_api_key_lookup
from src.Util.db.db_projects import get_project_by_id
from src.Util.db.db_user_groups import get_user_groups_in_project_by_hash
from src.Util.api_key_security import verify_api_key_token
from src.Util.cache_manager import cache_manager
from src.Util.error_handler import ErrorCode

logger = logging.getLogger(__name__)

# HTTP Bearer token security
security = HTTPBearer()

# API Key header extractor (auto_error=False so missing header is handled gracefully)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


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


async def verify_api_key(api_key: Optional[str] = Depends(api_key_header)) -> Dict[str, Any]:
    """
    Validate an API key from the X-API-Key header and return user context.

    Flow:
    1. Parse token: sk_{public_id}.{secret}
    2. Check Redis cache: apikey:{public_id}
    3. If miss: validate_api_key_lookup(public_id) → verify_api_key_token()
    4. Resolve live permissions via existing group-chain logic
    5. Cache result in Redis (60s TTL)
    6. Return dict compatible with verify_session shape

    Args:
        api_key: The full API key token from X-API-Key header

    Returns:
        User context dict with keys: user_id, user_hash, user_type, username,
        project_id, project_hash, permissions, groups, auth_method="api_key"

    Raises:
        HTTPException: 401 on any validation failure
    """
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Parse token format: sk_{public_id}.{secret}
    try:
        if not api_key.startswith("sk_"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid API key format: {ErrorCode.API_KEY_INVALID.value}",
            )
        # Extract public_id (between "sk_" and the last ".")
        token_body = api_key[3:]  # Remove "sk_" prefix
        public_id = token_body.rsplit(".", 1)[0]
    except (ValueError, IndexError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Malformed API key: {ErrorCode.API_KEY_INVALID.value}",
        )

    # Check Redis cache first
    cached = cache_manager.get_api_key(public_id)
    if cached:
        # Cache hit — check if still valid (cache may hold a stale "valid" entry
        # if the key was revoked within the 60s window; the stored procedure
        # re-validates on cache miss, so we trust the cache for the TTL window)
        if cached.get("validation_status") != "valid":
            _raise_api_key_error(cached.get("validation_status", "invalid"))
        return {
            "user_id": cached["user_id"],
            "user_hash": cached["user_hash"],
            "user_type": cached["user_type"],
            "username": cached.get("username"),
            "project_id": cached["project_id"],
            "project_hash": cached["project_hash"],
            "permissions": cached.get("permissions", []),
            "groups": cached.get("groups", []),
            "auth_method": "api_key",
        }

    # Cache miss — validate via stored procedure
    key_data = validate_api_key_lookup(public_id)
    if not key_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"API key not found: {ErrorCode.API_KEY_NOT_FOUND.value}",
        )

    validation_status = key_data.get("validation_status")
    if validation_status != "valid":
        # Key found but failed a pre-hash check (revoked, expired, etc.)
        _raise_api_key_error(validation_status)

    # Perform constant-time hash comparison (app-layer, not SQL)
    stored_hash = key_data.get("secret_hash")
    if not stored_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"API key verification failed: {ErrorCode.API_KEY_INVALID.value}",
        )

    if not verify_api_key_token(api_key, public_id, stored_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid API key: {ErrorCode.API_KEY_INVALID.value}",
        )

    # Key is cryptographically valid — now resolve live permissions
    owner_user_id = key_data["owner_user_id"]
    project_id = key_data["project_id"]

    # Get project info for project_hash
    project = get_project_by_id(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Project not found for API key scope",
        )

    # Resolve owner user info and permissions (same logic as validate_session)
    from src.Util.db.db_users import get_user_by_id
    owner = get_user_by_id(owner_user_id)
    if not owner:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Key owner user not found",
        )

    user_type = owner.user_type
    username = owner.username
    user_hash = owner.user_hash

    # Resolve permissions based on user type
    permissions: list = []
    groups: list = []

    if user_type == "root":
        permissions = ["admin", "global_admin"]
        groups = ["root_users"]
    elif user_type == "admin":
        from src.Util.db import check_admin_project_access
        if not check_admin_project_access(owner_user_id, project_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin lost project access",
            )
        permissions = ["admin", "project_admin"]
        groups = ["project_admins"]
    else:
        # Consumer: resolve via group chain
        groups_objs = get_user_groups_in_project_by_hash(owner_user_id, project.project_hash)
        if not groups_objs:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User lost project access via group chain",
            )
        groups = [g.group_name for g in groups_objs]
        # Get permissions from global role system
        try:
            from src.Util.db.db_global_roles import get_user_permissions
            permissions = get_user_permissions(owner_user_id)
        except Exception as e:
            logger.warning(f"Failed to load global role permissions for API key owner {owner_user_id}: {e}")
            permissions = []

    # Build validation result for caching
    validation_result = {
        "validation_status": "valid",
        "user_id": owner_user_id,
        "user_hash": user_hash,
        "user_type": user_type,
        "username": username,
        "project_id": project_id,
        "project_hash": project.project_hash,
        "permissions": permissions,
        "groups": groups,
        "key_id": key_data["id"],
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }

    # Cache the result (60s TTL)
    cache_manager.set_api_key(public_id, validation_result)

    return {
        "user_id": owner_user_id,
        "user_hash": user_hash,
        "user_type": user_type,
        "username": username,
        "project_id": project_id,
        "project_hash": project.project_hash,
        "permissions": permissions,
        "groups": groups,
        "auth_method": "api_key",
    }


def _raise_api_key_error(validation_status: Optional[str]) -> None:
    """Raise an appropriate HTTP 401 based on the validation status."""
    error_map = {
        "not_found": (ErrorCode.API_KEY_NOT_FOUND.value, "API key not found"),
        "revoked": (ErrorCode.API_KEY_REVOKED.value, "API key has been revoked"),
        "expired": (ErrorCode.API_KEY_EXPIRED.value, "API key has expired"),
        "owner_inactive": (ErrorCode.API_KEY_INVALID.value, "API key owner is inactive"),
        "no_project_access": (ErrorCode.API_KEY_NO_ACCESS.value, "API key owner lost project access"),
    }
    code, detail = error_map.get(validation_status, (ErrorCode.API_KEY_INVALID.value, "Invalid API key"))
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=f"{detail}: {code}",
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
