"""
System Information Routes

Handles system information, health checks, monitoring endpoints, and cache management
for the group-based multi-project authentication system.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPAuthorizationCredentials

from src.Util.Models import (
    SystemInfoResponse, HealthCheckResponse, PingResponse,
    CacheStatsResponse, ClearCacheResponse, InvalidateCacheResponse
)
from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.decorators import log_and_handle_errors
from src.Util.log_context_models import LogContext
from src.Util.activity_logger import ActivityType
from src.Util.error_handler import AuthorizationError, ErrorCode, mask_uuid
from src.Util.db_error_wrapper import handle_db_operation
from src.Util.cache_manager import cache_manager
from src.Util.db import (
    count_users, count_projects, count_user_groups,
    count_project_permission_groups, validate_session, is_root_user, get_user_type
)

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/system", tags=["System Information"])
security = HTTPBearerOrCookie()


@router.get("/info", response_model=SystemInfoResponse)
async def get_system_info() -> SystemInfoResponse:
    """
    Get system information and health status.
    
    Returns:
        System status and configuration information
    """
    # Get basic system statistics (safely - all return 0 on error)
    total_users = handle_db_operation(
        lambda: count_users(),
        error_context="count users for system info",
        default_return=0
    )
    
    total_projects = handle_db_operation(
        lambda: count_projects(),
        error_context="count projects for system info",
        default_return=0
    )
    
    total_user_groups = handle_db_operation(
        lambda: count_user_groups(),
        error_context="count user groups for system info",
        default_return=0
    )
    
    total_project_groups = handle_db_operation(
        lambda: count_project_permission_groups(),
        error_context="count project groups for system info",
        default_return=0
    )

    system_info = {
        "name": "Group-Based Multi-Project Authentication API",
        "version": "1.0.0",
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


@router.get("/health", response_model=HealthCheckResponse)
async def system_health() -> HealthCheckResponse:
    """
    Comprehensive system health check.
    
    Returns:
        Detailed health status of all system components
    """
    status = "healthy"
    timestamp = datetime.utcnow().isoformat() + "Z"
    components = {}

    # Check database connectivity
    db_check = handle_db_operation(
        lambda: count_users(),
        error_context="database health check",
        default_return=None
    )
    if db_check is not None:
        components["database"] = {"status": "healthy", "message": "Database accessible"}
    else:
        components["database"] = {"status": "unhealthy", "message": "Database connection failed"}
        status = "degraded"

    # Check Redis connectivity
    def check_redis():
        from src.Util.db_config import redis_client
        redis_client.ping()
        return True
    
    redis_ok = handle_db_operation(
        check_redis,
        error_context="redis health check",
        default_return=False
    )
    if redis_ok:
        components["redis"] = {"status": "healthy", "message": "Redis accessible"}
    else:
        components["redis"] = {"status": "unhealthy", "message": "Redis connection failed"}
        status = "degraded"

    # Check group system
    def check_group_system():
        user_groups_count = count_user_groups()
        project_groups_count = count_project_permission_groups()
        return {"user_groups": user_groups_count, "project_groups": project_groups_count}
    
    group_stats = handle_db_operation(
        check_group_system,
        error_context="group system health check",
        default_return=None
    )
    if group_stats:
        components["group_system"] = {
            "status": "healthy",
            "message": f"Group system operational: {group_stats['user_groups']} user groups, {group_stats['project_groups']} project groups"
        }
    else:
        components["group_system"] = {"status": "unhealthy", "message": "Group system check failed"}
        status = "degraded"

    return HealthCheckResponse(
        success=True,
        status=status,
        timestamp=timestamp,
        components=components
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
        timestamp=datetime.utcnow().isoformat() + "Z"
    )


@router.get("/cache/stats", response_model=CacheStatsResponse)
@log_and_handle_errors(
    operation_name="get_cache_stats",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False
)
async def get_cache_statistics(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None
) -> CacheStatsResponse:
    """
    Get cache statistics and performance metrics.
    Requires valid session token.
    
    Returns:
        Cache statistics including hit rates and storage info
    """
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
        timestamp=datetime.utcnow().isoformat() + "Z"
    )


@router.post("/cache/clear", response_model=ClearCacheResponse)
@log_and_handle_errors(
    operation_name="clear_cache",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True
)
async def clear_cache(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None
) -> ClearCacheResponse:
    """
    Clear entire authentication cache.
    Requires admin permissions.
    
    Returns:
        Cache clearing confirmation
    """
    # Check if user has admin permissions
    user_type = get_user_type(log_context.user_id)
    is_root = is_root_user(log_context.user_id)
    
    if not is_root and user_type != 'admin':
        raise AuthorizationError(
            message="Admin permission required to clear cache",
            error_code=ErrorCode.ACCESS_DENIED
        )

    # Clear entire cache
    success = cache_manager.clear_all_cache()

    if not success:
        from src.Util.error_handler import InternalError
        raise InternalError(
            message="Failed to clear cache",
            error_code=ErrorCode.INTERNAL_ERROR
        )
    
    logger.warning(f"Cache cleared by user: {mask_uuid(log_context.user_hash)}")
    return ClearCacheResponse(
        success=True,
        message="Entire authentication cache has been cleared",
        cleared_by=mask_uuid(log_context.user_hash),
        timestamp=datetime.utcnow().isoformat() + "Z",
        warning="All users will need to re-authenticate or may experience slower response times"
    )


@router.post("/cache/invalidate/user/{user_hash}", response_model=InvalidateCacheResponse)
@log_and_handle_errors(
    operation_name="invalidate_user_cache",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True
)
async def invalidate_user_cache(
        user_hash: str,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> InvalidateCacheResponse:
    """
    Invalidate cache for a specific user.
    Requires admin permissions.
    
    Args:
        user_hash: Hash of the user whose cache should be invalidated
        
    Returns:
        Cache invalidation confirmation
    """
    # Check admin permissions
    user_type = get_user_type(log_context.user_id)
    is_root = is_root_user(log_context.user_id)
    
    if not is_root and user_type != 'admin':
        raise AuthorizationError(
            message="Admin permission required",
            error_code=ErrorCode.ACCESS_DENIED
        )

    # Get user ID from hash
    from src.Util.db import get_user_by_hash
    target_user = handle_db_operation(
        lambda: get_user_by_hash(user_hash),
        error_context="user lookup",
        not_found_message=f"User not found: {mask_uuid(user_hash)}"
    )

    # Invalidate user cache
    success = cache_manager.invalidate_user_cache(target_user.id)

    if not success:
        from src.Util.error_handler import InternalError
        raise InternalError(
            message="Failed to invalidate user cache",
            error_code=ErrorCode.INTERNAL_ERROR
        )

    return InvalidateCacheResponse(
        success=True,
        message=f"Cache invalidated for user: {mask_uuid(user_hash)}",
        invalidated_by=mask_uuid(log_context.user_hash),
        timestamp=datetime.utcnow().isoformat() + "Z"
    )


@router.post("/cache/invalidate/project/{project_id}", response_model=InvalidateCacheResponse)
@log_and_handle_errors(
    operation_name="invalidate_project_cache",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True
)
async def invalidate_project_cache(
        project_id: int,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> InvalidateCacheResponse:
    """
    Invalidate cache for a specific project.
    Requires admin permissions.
    
    Args:
        project_id: ID of the project whose cache should be invalidated
        
    Returns:
        Cache invalidation confirmation
    """
    # Check admin permissions
    user_type = get_user_type(log_context.user_id)
    is_root = is_root_user(log_context.user_id)
    
    if not is_root and user_type != 'admin':
        raise AuthorizationError(
            message="Admin permission required",
            error_code=ErrorCode.ACCESS_DENIED
        )

    # Invalidate project cache
    success = cache_manager.invalidate_project_cache(project_id)

    if not success:
        from src.Util.error_handler import InternalError
        raise InternalError(
            message="Failed to invalidate project cache",
            error_code=ErrorCode.INTERNAL_ERROR
        )

    return InvalidateCacheResponse(
        success=True,
        message=f"Cache invalidated for project: {project_id}",
        invalidated_by=mask_uuid(log_context.user_hash),
        timestamp=datetime.utcnow().isoformat() + "Z"
    )
