"""
System Information Routes

Handles system information, health checks, monitoring endpoints, and cache management
for the group-based multi-project authentication system.
"""

import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.Util.db import (
    count_users, count_projects, count_user_groups,
    count_project_permission_groups, client, validate_session
)
from src.Util.cache_manager import cache_manager
from src.Util.Models import (
    SystemInfoResponse, HealthCheckResponse, PingResponse,
    CacheStatsResponse, ClearCacheResponse, InvalidateCacheResponse
)

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/system", tags=["System Information"])
security = HTTPBearer()


@router.get("/info", response_model=SystemInfoResponse)
async def get_system_info() -> SystemInfoResponse:
    """
    Get system information and health status.
    
    Returns:
        System status and configuration information
    """
    try:
        # Get basic system statistics (safely)
        try:
            total_users = count_users()
        except:
            total_users = 0
            
        try:
            total_projects = count_projects()
        except:
            total_projects = 0
            
        try:
            total_user_groups = count_user_groups()
        except:
            total_user_groups = 0
            
        try:
            total_project_groups = count_project_permission_groups()
        except:
            total_project_groups = 0
        
        system_info = {
            "name": "Group-Based Multi-Project Authentication API",
            "version": "2.0.0",
            "architecture": "hierarchical-group-based",
            "status": "operational"
        }
        
        statistics = {
            "total_users": total_users,
            "total_projects": total_projects,
            "total_user_groups": total_user_groups,
            "total_project_groups": total_project_groups,
            "authentication_type": "group-based-jwt"
        }
        
        features = [
            "hierarchical-group-access-control",
            "global-user-groups",
            "project-permission-groups",
            "multi-project-support",
            "session-management-with-group-context",
            "comprehensive-audit-trail",
            "restful-admin-api"
        ]
        
        return SystemInfoResponse(
            success=True,
            system=system_info,
            statistics=statistics,
            features=features
        )
        
    except Exception as e:
        logger.error(f"System info error: {str(e)}")
        return SystemInfoResponse(
            success=False,
            message="System information temporarily unavailable",
            system={
                "name": "Group-Based Multi-Project Authentication API",
                "version": "2.0.0",
                "architecture": "hierarchical-group-based",
                "status": "operational"
            }
        )


@router.get("/health", response_model=HealthCheckResponse)
async def system_health() -> HealthCheckResponse:
    """
    Comprehensive system health check.
    
    Returns:
        Detailed health status of all system components
    """
    try:
        status = "healthy"
        timestamp = datetime.now().isoformat()
        components = {}
        
        # Check database connectivity
        try:
            count_users()
            components["database"] = {"status": "healthy", "message": "Database accessible"}
        except Exception as e:
            components["database"] = {"status": "unhealthy", "message": f"Database error: {str(e)}"}
            status = "degraded"
        
        # Check Redis connectivity
        try:
            from src.Util.db_config import redis_client
            redis_client.ping()
            components["redis"] = {"status": "healthy", "message": "Redis accessible"}
        except Exception as e:
            components["redis"] = {"status": "unhealthy", "message": f"Redis error: {str(e)}"}
            status = "degraded"
        
        # Check group system
        try:
            user_groups_count = count_user_groups()
            project_groups_count = count_project_permission_groups()
            components["group_system"] = {
                "status": "healthy", 
                "message": f"Group system operational: {user_groups_count} user groups, {project_groups_count} project groups"
            }
        except Exception as e:
            components["group_system"] = {"status": "unhealthy", "message": f"Group system error: {str(e)}"}
            status = "degraded"
        
        return HealthCheckResponse(
            success=True,
            status=status,
            timestamp=timestamp,
            components=components
        )
        
    except Exception as e:
        logger.error(f"Health check error: {str(e)}")
        return HealthCheckResponse(
            success=False,
            status="unhealthy",
            timestamp=datetime.now().isoformat(),
            components={"error": str(e)}
        )


@router.get("/ping", response_model=PingResponse)
async def ping() -> PingResponse:
    """
    Simple health check endpoint.
    
    Returns:
        Basic health status
    """
    return PingResponse(
        success=True,
        message="Group-based authentication API is running",
        timestamp=datetime.now().isoformat()
    )


@router.get("/cache/stats", response_model=CacheStatsResponse)
async def get_cache_statistics(credentials: HTTPAuthorizationCredentials = Depends(security)) -> CacheStatsResponse:
    """
    Get cache statistics and performance metrics.
    Requires valid session token.
    
    Returns:
        Cache statistics including hit rates and storage info
    """
    try:
        # Validate session (any authenticated user can see cache stats)
        session_data = validate_session(credentials.credentials)
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        # Get cache statistics
        cache_stats = cache_manager.get_cache_stats()
        
        cache_config = {
            "session_ttl": "3600 seconds (1 hour)",
            "access_check_ttl": "1800 seconds (30 minutes)",
            "rbac_check_ttl": "1800 seconds (30 minutes)",
            "user_info_ttl": "3600 seconds (1 hour)"
        }
        
        return CacheStatsResponse(
            success=True,
            cache_statistics=cache_stats,
            cache_configuration=cache_config,
            timestamp=datetime.now().isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cache statistics error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get cache statistics")


@router.post("/cache/clear", response_model=ClearCacheResponse)
async def clear_cache(credentials: HTTPAuthorizationCredentials = Depends(security)) -> ClearCacheResponse:
    """
    Clear entire authentication cache.
    Requires admin permissions.
    
    Returns:
        Cache clearing confirmation
    """
    try:
        # Validate session and check admin permissions
        session_data = validate_session(credentials.credentials)
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        # Check if user has admin permissions (support global root sessions)
        user_permissions = getattr(session_data, 'permissions', [])
        if 'admin' not in user_permissions and 'manage_users' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required to clear cache")
        
        # Clear entire cache
        success = cache_manager.clear_all_cache()
        
        if success:
            logger.warning(f"Cache cleared by user: {session_data.user_hash}")
            return ClearCacheResponse(
                success=True,
                message="Entire authentication cache has been cleared",
                cleared_by=session_data.user_hash,
                timestamp=datetime.now().isoformat(),
                warning="All users will need to re-authenticate or may experience slower response times"
            )
        else:
            raise HTTPException(status_code=500, detail="Failed to clear cache")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cache clearing error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to clear cache")


@router.post("/cache/invalidate/user/{user_hash}", response_model=InvalidateCacheResponse)
async def invalidate_user_cache(
    user_hash: str,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> InvalidateCacheResponse:
    """
    Invalidate cache for a specific user.
    Requires admin permissions.
    
    Args:
        user_hash: Hash of the user whose cache should be invalidated
        
    Returns:
        Cache invalidation confirmation
    """
    try:
        # Validate session and check admin permissions
        session_data = validate_session(credentials.credentials)
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        user_permissions = getattr(session_data, 'permissions', [])
        if 'admin' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required")
        
        # Get user ID from hash
        from src.Util.db import get_user_by_hash
        target_user = get_user_by_hash(user_hash)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Invalidate user cache
        success = cache_manager.invalidate_user_cache(target_user.id)
        
        if success:
            return InvalidateCacheResponse(
                success=True,
                message=f"Cache invalidated for user: {user_hash}",
                invalidated_by=session_data.user_hash,
                timestamp=datetime.now().isoformat()
            )
        else:
            raise HTTPException(status_code=500, detail="Failed to invalidate user cache")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User cache invalidation error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to invalidate user cache")


@router.post("/cache/invalidate/project/{project_id}", response_model=InvalidateCacheResponse)
async def invalidate_project_cache(
    project_id: int,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> InvalidateCacheResponse:
    """
    Invalidate cache for a specific project.
    Requires admin permissions.
    
    Args:
        project_id: ID of the project whose cache should be invalidated
        
    Returns:
        Cache invalidation confirmation
    """
    try:
        # Validate session and check admin permissions
        session_data = validate_session(credentials.credentials)
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        user_permissions = getattr(session_data, 'permissions', [])
        if 'admin' not in user_permissions:
            raise HTTPException(status_code=403, detail="Admin permission required")
        
        # Invalidate project cache
        success = cache_manager.invalidate_project_cache(project_id)
        
        if success:
            return InvalidateCacheResponse(
                success=True,
                message=f"Cache invalidated for project: {project_id}",
                invalidated_by=session_data.user_hash,
                timestamp=datetime.now().isoformat()
            )
        else:
            raise HTTPException(status_code=500, detail="Failed to invalidate project cache")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Project cache invalidation error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to invalidate project cache") 