"""
Unified Decorators for Logging and Error Handling

Provides decorators for automatic logging and error handling in API endpoints.
"""

import logging
import traceback
import uuid
from typing import Callable, Optional, Any, Dict
from functools import wraps
from datetime import datetime, timezone
from inspect import signature

from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials

from src.Util.log_context_models import LogContext, UnauthenticatedLogContext, OperationMetadata
from src.Util.error_handler import (
    AppException, InternalError, AuthenticationError, ErrorCode,
    build_error_response, log_error, sanitize_error_message
)
from src.Util.activity_logger import ActivityLogger, ActivityType
from src.Util.db import validate_session, get_user_by_hash

logger = logging.getLogger(__name__)


def log_and_handle_errors(
    operation_name: str,
    activity_type: Optional[ActivityType] = None,
    log_success: bool = True,
    log_args: bool = False,
    require_auth: bool = True
):
    """
    Unified decorator for logging and error handling in authenticated endpoints.
    
    This decorator:
    - Validates user session and extracts user context
    - Logs the operation with detailed context
    - Handles errors with proper logging and sanitization
    - Returns standardized error responses
    
    Args:
        operation_name: Name of the operation (for logging)
        activity_type: ActivityType enum value for activity logging
        log_success: Whether to log successful operations
        log_args: Whether to log function arguments (be careful with sensitive data)
        require_auth: Whether authentication is required
        
    Usage:
        @router.get("/users/{user_hash}")
        @log_and_handle_errors(
            operation_name="get_user_details",
            activity_type=ActivityType.ADMIN_ACTION,
            log_success=True
        )
        async def get_user_details(
            user_hash: str,
            credentials: HTTPAuthorizationCredentials = Depends(security)
        ):
            # Your endpoint logic
            return result
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            log_context = None
            start_time = datetime.now(timezone.utc)
            request_id = str(uuid.uuid4())
            
            try:
                # Extract credentials from kwargs if available
                credentials = kwargs.get('credentials')
                request = kwargs.get('request')
                
                # Build log context
                if require_auth and credentials:
                    # Validate session and get user info
                    session_token = credentials.credentials
                    session_data = validate_session(session_token)
                    
                    if not session_data:
                        raise AuthenticationError(
                            message="Invalid or expired session",
                            error_code=ErrorCode.SESSION_INVALID
                        )
                    
                    # Get full user data
                    user_data = get_user_by_hash(session_data.user_hash)
                    
                    # Build authenticated log context
                    log_context = LogContext(
                        user_id=session_data.user_id if hasattr(session_data, 'user_id') else user_data.id if user_data else None,
                        user_hash=session_data.user_hash,
                        username=user_data.username if user_data else None,
                        project_id=session_data.project_id if hasattr(session_data, 'project_id') else None,
                        project_hash=session_data.project_hash if hasattr(session_data, 'project_hash') else None,
                        ip_address=request.client.host if request and hasattr(request, 'client') else None,
                        user_agent=request.headers.get('user-agent') if request else None,
                        endpoint=func.__name__,
                        method=request.method if request else None,
                        request_id=request_id,
                        timestamp=start_time
                    )
                    
                    # Inject log_context into kwargs for the function to use if needed
                    kwargs['log_context'] = log_context
                
                # Log operation start
                logger.info(
                    f"Operation started: {operation_name}",
                    extra={
                        "operation": operation_name,
                        "request_id": request_id,
                        "user_id": log_context.user_id if log_context else None,
                        "user_hash": log_context.user_hash if log_context else None,
                        "endpoint": func.__name__
                    }
                )
                
                # Execute the function
                result = await func(*args, **kwargs)
                
                # Log successful operation
                if log_success and log_context:
                    duration = (datetime.now(timezone.utc) - start_time).total_seconds()
                    
                    # Log to activity logger if activity_type is provided
                    if activity_type:
                        ActivityLogger.log_activity(
                            user_id=log_context.user_id,
                            activity_type=activity_type.value,
                            details={
                                "operation": operation_name,
                                "success": True,
                                "duration_seconds": duration,
                                "request_id": request_id
                            },
                            project_id=log_context.project_id,
                            ip_address=log_context.ip_address,
                            user_agent=log_context.user_agent
                        )
                    
                    logger.info(
                        f"Operation completed: {operation_name}",
                        extra={
                            "operation": operation_name,
                            "request_id": request_id,
                            "user_id": log_context.user_id,
                            "duration_seconds": duration,
                            "success": True
                        }
                    )
                
                return result
                
            except AppException as e:
                # Handle known application exceptions
                duration = (datetime.now(timezone.utc) - start_time).total_seconds()
                
                # Log the error
                log_error(e, context={
                    "operation": operation_name,
                    "request_id": request_id,
                    "user_id": log_context.user_id if log_context else None,
                    "user_hash": log_context.user_hash if log_context else None,
                    "duration_seconds": duration
                })
                
                # Log to activity logger
                if activity_type and log_context:
                    ActivityLogger.log_activity(
                        user_id=log_context.user_id,
                        activity_type=activity_type.value,
                        details={
                            "operation": operation_name,
                            "success": False,
                            "error_code": e.error_code.value,
                            "error_message": e.message,
                            "duration_seconds": duration,
                            "request_id": request_id
                        },
                        project_id=log_context.project_id,
                        ip_address=log_context.ip_address if log_context else None,
                        user_agent=log_context.user_agent if log_context else None
                    )
                
                raise  # Re-raise to be handled by FastAPI exception handler
                
            except Exception as e:
                # Handle unexpected exceptions
                duration = (datetime.now(timezone.utc) - start_time).total_seconds()
                
                logger.error(
                    f"Unexpected error in {operation_name}: {sanitize_error_message(str(e))}",
                    exc_info=True,
                    extra={
                        "operation": operation_name,
                        "request_id": request_id,
                        "user_id": log_context.user_id if log_context else None,
                        "duration_seconds": duration,
                        "traceback": traceback.format_exc()
                    }
                )
                
                # Log to activity logger
                if activity_type and log_context:
                    ActivityLogger.log_activity(
                        user_id=log_context.user_id,
                        activity_type=activity_type.value,
                        details={
                            "operation": operation_name,
                            "success": False,
                            "error": "Internal error",
                            "duration_seconds": duration,
                            "request_id": request_id
                        },
                        project_id=log_context.project_id,
                        ip_address=log_context.ip_address if log_context else None,
                        user_agent=log_context.user_agent if log_context else None
                    )
                
                # Wrap in InternalError and raise
                raise InternalError(
                    message=f"Error during {operation_name}",
                    error_code=ErrorCode.INTERNAL_ERROR,
                    details={"operation": operation_name, "request_id": request_id},
                    original_error=e
                )
        
        return async_wrapper
    
    return decorator


def log_unauthenticated_operation(
    operation_name: str,
    activity_type: Optional[ActivityType] = None,
    log_success: bool = True,
    extract_username: Optional[Callable] = None
):
    """
    Decorator for logging and error handling in unauthenticated endpoints (login, register, etc.)
    
    This decorator:
    - Logs the operation with available context (IP, user agent)
    - Handles errors with proper logging
    - Returns standardized error responses
    
    Args:
        operation_name: Name of the operation (for logging)
        activity_type: ActivityType enum value for activity logging
        log_success: Whether to log successful operations
        extract_username: Optional function to extract username from args/kwargs
        
    Usage:
        @router.post("/auth/login")
        @log_unauthenticated_operation(
            operation_name="user_login",
            activity_type=ActivityType.USER_LOGIN,
            extract_username=lambda *args, **kwargs: kwargs.get('username')
        )
        async def login(
            username: str = Form(...),
            password: str = Form(...),
            request: Request = None
        ):
            # Your login logic
            return result
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = datetime.now(timezone.utc)
            request_id = str(uuid.uuid4())
            username = None
            
            try:
                # Extract request for IP and user agent
                request = kwargs.get('request')
                
                # Extract username if function provided
                if extract_username:
                    try:
                        username = extract_username(*args, **kwargs)
                    except:
                        username = None
                
                # Build unauthenticated log context
                log_context = UnauthenticatedLogContext(
                    ip_address=request.client.host if request and hasattr(request, 'client') else None,
                    user_agent=request.headers.get('user-agent') if request else None,
                    endpoint=func.__name__,
                    method=request.method if request else None,
                    request_id=request_id,
                    timestamp=start_time,
                    username=username
                )
                
                # Log operation start
                logger.info(
                    f"Unauthenticated operation started: {operation_name}",
                    extra={
                        "operation": operation_name,
                        "request_id": request_id,
                        "username": username,
                        "ip_address": log_context.ip_address,
                        "endpoint": func.__name__
                    }
                )
                
                # Inject log_context into kwargs for the function to use if needed
                kwargs['log_context'] = log_context
                
                # Execute the function
                result = await func(*args, **kwargs)
                
                # Log successful operation
                if log_success:
                    duration = (datetime.now(timezone.utc) - start_time).total_seconds()
                    
                    logger.info(
                        f"Unauthenticated operation completed: {operation_name}",
                        extra={
                            "operation": operation_name,
                            "request_id": request_id,
                            "username": username,
                            "duration_seconds": duration,
                            "success": True
                        }
                    )
                    
                    # Log to activity logger if user_id is available in result
                    if activity_type:
                        user_id = None
                        project_id = None
                        
                        # Handle both Pydantic models and dicts
                        if isinstance(result, dict):
                            user_id = result.get('user_id')
                            project_id = result.get('project_id')
                            if not user_id and 'user' in result and isinstance(result['user'], dict):
                                user_id = str(result['user'].get('id') or result['user'].get('user_id'))
                        elif hasattr(result, 'user_id'):
                            # Pydantic model with user_id attribute
                            user_id = getattr(result, 'user_id', None)
                            # Try to get project_id from project object or directly
                            if hasattr(result, 'project') and result.project:
                                if hasattr(result.project, 'id'):
                                    project_id = result.project.id
                                elif isinstance(result.project, dict):
                                    project_id = result.project.get('id')
                        
                        if user_id:
                            ActivityLogger.log_activity(
                                user_id=str(user_id),
                                activity_type=activity_type.value,
                                details={
                                    "operation": operation_name,
                                    "success": True,
                                    "duration_seconds": duration,
                                    "request_id": request_id
                                },
                                project_id=project_id,
                                ip_address=log_context.ip_address,
                                user_agent=log_context.user_agent
                            )
                
                return result
                
            except AppException as e:
                # Handle known application exceptions
                duration = (datetime.now(timezone.utc) - start_time).total_seconds()
                
                # Log the error
                log_error(e, context={
                    "operation": operation_name,
                    "request_id": request_id,
                    "username": username,
                    "duration_seconds": duration
                })
                
                # Log failed attempt to activity logger
                if activity_type:
                    ActivityLogger.log_activity(
                        user_id=None,
                        activity_type=activity_type.value,
                        details={
                            "operation": operation_name,
                            "success": False,
                            "error_code": e.error_code.value,
                            "error_message": e.message,
                            "duration_seconds": duration,
                            "request_id": request_id,
                            "username": username
                        },
                        ip_address=kwargs.get('request').client.host if kwargs.get('request') and hasattr(kwargs.get('request'), 'client') else None,
                        user_agent=kwargs.get('request').headers.get('user-agent') if kwargs.get('request') else None
                    )
                
                raise  # Re-raise to be handled by FastAPI exception handler
                
            except Exception as e:
                # Handle unexpected exceptions
                duration = (datetime.now(timezone.utc) - start_time).total_seconds()
                
                logger.error(
                    f"Unexpected error in {operation_name}: {sanitize_error_message(str(e))}",
                    exc_info=True,
                    extra={
                        "operation": operation_name,
                        "request_id": request_id,
                        "username": username,
                        "duration_seconds": duration,
                        "traceback": traceback.format_exc()
                    }
                )
                
                # Log to activity logger
                if activity_type:
                    ActivityLogger.log_activity(
                        user_id=None,
                        activity_type=activity_type.value,
                        details={
                            "operation": operation_name,
                            "success": False,
                            "error": "Internal error",
                            "duration_seconds": duration,
                            "request_id": request_id,
                            "username": username
                        },
                        ip_address=kwargs.get('request').client.host if kwargs.get('request') and hasattr(kwargs.get('request'), 'client') else None,
                        user_agent=kwargs.get('request').headers.get('user-agent') if kwargs.get('request') else None
                    )
                
                # Wrap in InternalError and raise
                raise InternalError(
                    message=f"Error during {operation_name}",
                    error_code=ErrorCode.INTERNAL_ERROR,
                    details={"operation": operation_name, "request_id": request_id},
                    original_error=e
                )
        
        return async_wrapper
    
    return decorator


def log_operation_details(
    user_id: str,
    operation: OperationMetadata,
    log_context: Optional[LogContext] = None
):
    """
    Helper function to log detailed operation information.
    
    Use this within your endpoint functions to log specific operation details.
    
    Args:
        user_id: User performing the operation
        operation: OperationMetadata with operation details
        log_context: Optional LogContext from the decorator
        
    Usage:
        @log_and_handle_errors("update_user", ActivityType.USER_UPDATE)
        async def update_user(
            user_hash: str,
            data: dict,
            credentials: HTTPAuthorizationCredentials = Depends(security),
            log_context: LogContext = None
        ):
            # ... perform update ...
            
            # Log the specific changes
            log_operation_details(
                user_id=log_context.user_id,
                operation=OperationMetadata(
                    operation_name="update_user",
                    target_resource=user_hash,
                    target_resource_type="user",
                    changes={"email": "new@email.com"}
                ),
                log_context=log_context
            )
            
            return result
    """
    logger.info(
        f"Operation details: {operation.operation_name}",
        extra={
            "operation": operation.operation_name,
            "user_id": user_id,
            "target_resource": operation.target_resource,
            "target_resource_type": operation.target_resource_type,
            "changes": operation.changes,
            "additional_data": operation.additional_data,
            "request_id": log_context.request_id if log_context else None
        }
    )
