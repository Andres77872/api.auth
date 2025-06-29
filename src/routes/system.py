"""
System Information Routes

Handles system information, health checks, and monitoring endpoints
for the group-based multi-project authentication system.
"""

import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException

from src.Util.db import (
    count_users, count_projects, count_user_groups,
    count_project_permission_groups, client
)

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router
router = APIRouter(prefix="/system", tags=["System Information"])


@router.get("/info")
async def get_system_info():
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
        
        return {
            "success": True,
            "system": {
                "name": "Group-Based Multi-Project Authentication API",
                "version": "2.0.0",
                "architecture": "hierarchical-group-based",
                "status": "operational"
            },
            "statistics": {
                "total_users": total_users,
                "total_projects": total_projects,
                "total_user_groups": total_user_groups,
                "total_project_groups": total_project_groups,
                "authentication_type": "group-based-jwt"
            },
            "features": [
                "hierarchical-group-access-control",
                "global-user-groups",
                "project-permission-groups",
                "multi-project-support",
                "session-management-with-group-context",
                "comprehensive-audit-trail",
                "restful-admin-api"
            ]
        }
        
    except Exception as e:
        logger.error(f"System info error: {str(e)}")
        return {
            "success": False,
            "error": "System information temporarily unavailable",
            "system": {
                "name": "Group-Based Multi-Project Authentication API",
                "version": "2.0.0",
                "architecture": "hierarchical-group-based",
                "status": "operational"
            }
        }


@router.get("/health")
async def system_health():
    """
    Comprehensive system health check.
    
    Returns:
        Detailed health status of all system components
    """
    try:
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "components": {}
        }
        
        # Check database connectivity
        try:
            count_users()
            health_status["components"]["database"] = {"status": "healthy", "message": "Database accessible"}
        except Exception as e:
            health_status["components"]["database"] = {"status": "unhealthy", "message": f"Database error: {str(e)}"}
            health_status["status"] = "degraded"
        
        # Check Redis connectivity
        try:
            from src.Util.db_config import redis_client
            redis_client.ping()
            health_status["components"]["redis"] = {"status": "healthy", "message": "Redis accessible"}
        except Exception as e:
            health_status["components"]["redis"] = {"status": "unhealthy", "message": f"Redis error: {str(e)}"}
            health_status["status"] = "degraded"
        
        # Check group system
        try:
            user_groups_count = count_user_groups()
            project_groups_count = count_project_permission_groups()
            health_status["components"]["group_system"] = {
                "status": "healthy", 
                "message": f"Group system operational: {user_groups_count} user groups, {project_groups_count} project groups"
            }
        except Exception as e:
            health_status["components"]["group_system"] = {"status": "unhealthy", "message": f"Group system error: {str(e)}"}
            health_status["status"] = "degraded"
        
        return health_status
        
    except Exception as e:
        logger.error(f"Health check error: {str(e)}")
        return {
            "status": "unhealthy",
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }


@router.get("/ping")
async def ping():
    """
    Simple health check endpoint.
    
    Returns:
        Basic health status
    """
    return {
        "success": True, 
        "message": "Group-based authentication API is running", 
        "timestamp": datetime.now().isoformat()
    } 