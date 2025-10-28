"""
FastAPI Exception Handler Middleware

Handles all exceptions and converts them to standardized error responses
with UUID masking and detailed error descriptions.
"""

import logging
import traceback
import inspect
import sys
from typing import Union, Optional, Dict, Any
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.Util.error_handler import (
    AppException,
    build_error_response,
    sanitize_error_message,
    ErrorCode,
    ErrorCategory,
    ValidationError,
    log_error,
    mask_uuid
)
from src.Util.db.db_error_logger import (
    log_app_exception_to_db, 
    log_generic_exception_to_db,
    log_http_exception_to_db,
    log_validation_exception_to_db
)

logger = logging.getLogger(__name__)


def extract_user_context_from_request(request: Request) -> Dict[str, Optional[str]]:
    """
    Extract user context (user_id, project_id, session_id) from request.
    
    Args:
        request: FastAPI request object
        
    Returns:
        Dictionary with user_id, project_id, session_id (all optional)
    """
    context = {
        "user_id": None,
        "project_id": None,
        "session_id": None
    }
    
    try:
        # Try to get user context from request state (if authentication middleware set it)
        if hasattr(request.state, 'user_id'):
            context["user_id"] = request.state.user_id
        
        if hasattr(request.state, 'project_id'):
            context["project_id"] = request.state.project_id
        
        if hasattr(request.state, 'session_id'):
            session_id = request.state.session_id
            # Truncate session_id to 256 characters to fit database column
            # (session_id may be a JWT token which is much longer)
            if session_id:
                context["session_id"] = session_id[:256]
        
        # Alternative: try to get from session data if available
        if hasattr(request.state, 'session_data'):
            session_data = request.state.session_data
            if hasattr(session_data, 'user_id'):
                context["user_id"] = session_data.user_id
            if hasattr(session_data, 'project_id'):
                context["project_id"] = session_data.project_id
    except Exception as e:
        logger.debug(f"Failed to extract user context from request: {e}")
    
    return context


def extract_function_context_from_exception() -> Optional[Dict[str, Any]]:
    """
    Extract function name and parameters from the exception's traceback.
    
    This automatically captures where the exception was raised by inspecting
    the exception's traceback (not the current stack!) and extracting the 
    function name and its parameters.
    
    Returns:
        Dictionary with 'name' and 'params' or None if extraction fails
    """
    try:
        # Get the exception info - THIS is the key!
        # We need the traceback from when the exception was raised,
        # not the current call stack
        exc_type, exc_value, exc_traceback = sys.exc_info()
        
        if not exc_traceback:
            return None
        
        # Walk the traceback frames to find the route handler
        tb = exc_traceback
        while tb is not None:
            frame = tb.tb_frame
            filepath = frame.f_code.co_filename
            function_name = frame.f_code.co_name
            
            # Look for frames in src/routes/ (the route handler)
            if '/src/routes/' in filepath and not filepath.endswith('error_handler.py'):
                # Skip internal FastAPI/Starlette functions
                if function_name.startswith('_') or function_name in ['app', 'wrapped_app']:
                    tb = tb.tb_next
                    continue
                
                # Get local variables (function parameters) from the frame
                local_vars = frame.f_locals
                
                # Extract relevant parameters (skip internal FastAPI stuff)
                params = {}
                skip_params = {'request', 'response', 'credentials', 'session_data', 
                              'log_context', 'self', 'cls', '__class__'}
                
                for key, value in local_vars.items():
                    if key in skip_params or key.startswith('_'):
                        continue
                    
                    # Convert value to string representation
                    if isinstance(value, str):
                        # Mask UUIDs in string values
                        params[key] = mask_uuid(value)
                    elif isinstance(value, (int, float, bool)):
                        params[key] = value
                    elif value is None:
                        params[key] = None
                    elif hasattr(value, 'user_hash'):
                        # Session data or user object
                        params[key] = mask_uuid(value.user_hash)
                    elif hasattr(value, 'project_hash'):
                        params[key] = mask_uuid(value.project_hash)
                    else:
                        # For other objects, just use their type
                        params[key] = f"<{type(value).__name__}>"
                
                return {
                    "name": function_name,
                    "params": params
                }
            
            tb = tb.tb_next
        
        return None
    except Exception as e:
        # Don't let context extraction break error handling
        logger.debug(f"Failed to extract function context: {e}")
        return None


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """
    Handle custom AppException instances.
    
    Automatically extracts function context (name and parameters) from the
    traceback if not already provided in the exception.
    
    Args:
        request: FastAPI request object
        exc: AppException instance
        
    Returns:
        JSONResponse with standardized error format
    """
    # Build request context for logging and error details
    request_context = {
        "path": request.url.path,
        "method": request.method,
        "client": request.client.host if request.client else "unknown",
        "query_params": dict(request.query_params) if request.query_params else {},
        "user_agent": request.headers.get("user-agent")
    }
    
    # Automatically extract function context if not already provided
    # This is the key: we don't need to manually add error_context everywhere!
    if not hasattr(exc, 'error_context') or not exc.error_context:
        function_context = extract_function_context_from_exception()
        logger.debug(f"Extracted function context: {function_context}")
        if function_context:
            # Build error_context string in function call format
            params_str = ', '.join([f"{k}={v!r}" for k, v in function_context['params'].items()])
            exc.error_context = f"{function_context['name']}({params_str})"
            logger.debug(f"Set error_context: {exc.error_context}")
        else:
            logger.warning("Failed to extract function context from traceback")
    
    # Log the error with request context
    log_error(exc, request_context)
    
    # ALWAYS log to database (regardless of DEBUG_MODE)
    user_context = extract_user_context_from_request(request)
    log_app_exception_to_db(
        exception=exc,
        request_context=request_context,
        user_id=user_context.get("user_id"),
        project_id=user_context.get("project_id"),
        session_id=user_context.get("session_id")
    )
    
    # Get error response
    response_data = exc.to_dict()
    
    # Add API context to details if DEBUG_MODE is enabled
    from src.Util.error_handler import DEBUG_MODE
    if DEBUG_MODE and "error" in response_data and "details" in response_data["error"]:
        if "api_error" not in response_data["error"]["details"]:
            response_data["error"]["details"]["api_error"] = {}
        
        response_data["error"]["details"]["api_error"].update({
            "endpoint": request.url.path,
            "method": request.method,
            "query_params": request_context["query_params"],
            "client_host": request_context["client"]
        })
    
    return JSONResponse(
        status_code=exc.status_code,
        content=response_data
    )


async def http_exception_handler(request: Request, exc: Union[HTTPException, StarletteHTTPException]) -> JSONResponse:
    """
    Handle FastAPI/Starlette HTTPException instances.
    
    Args:
        request: FastAPI request object
        exc: HTTPException instance
        
    Returns:
        JSONResponse with standardized error format
    """
    # Map HTTP status codes to error categories
    category_map = {
        400: ErrorCategory.VALIDATION,
        401: ErrorCategory.AUTHENTICATION,
        403: ErrorCategory.AUTHORIZATION,
        404: ErrorCategory.NOT_FOUND,
        409: ErrorCategory.CONFLICT,
        500: ErrorCategory.INTERNAL,
    }
    
    # Map HTTP status codes to error codes
    error_code_map = {
        400: ErrorCode.INVALID_INPUT,
        401: ErrorCode.SESSION_INVALID,
        403: ErrorCode.ACCESS_DENIED,
        404: ErrorCode.RESOURCE_NOT_FOUND,
        409: ErrorCode.DUPLICATE_ENTRY,
        500: ErrorCode.INTERNAL_ERROR,
    }
    
    status_code = exc.status_code
    category = category_map.get(status_code, ErrorCategory.INTERNAL)
    error_code = error_code_map.get(status_code, ErrorCode.INTERNAL_ERROR)
    
    # Sanitize the error message
    sanitized_detail = sanitize_error_message(str(exc.detail))
    
    response = {
        "status": "error",
        "error": {
            "code": error_code.value,
            "category": category.value,
            "message": sanitized_detail,
        }
    }
    
    # Add detailed information in DEBUG_MODE
    from src.Util.error_handler import DEBUG_MODE
    import traceback
    import sys
    
    if DEBUG_MODE:
        response["error"]["details"] = {
            "error_type": type(exc).__name__,
            "error_message": sanitized_detail,
            "api_error": {
                "endpoint": request.url.path,
                "method": request.method,
                "query_params": dict(request.query_params) if request.query_params else {},
                "client_host": request.client.host if request.client else "unknown"
            }
        }
        
        # Include trace
        exc_info = sys.exc_info()
        if exc_info[0] is not None:
            response["error"]["trace"] = ''.join(traceback.format_exception(*exc_info))
        else:
            response["error"]["trace"] = ''.join(traceback.format_stack())
    
    logger.warning(
        f"HTTP {status_code} - {sanitized_detail}",
        extra={
            "path": request.url.path,
            "method": request.method,
            "status_code": status_code
        }
    )
    
    # Log to database
    request_context = {
        "path": request.url.path,
        "method": request.method,
        "client": request.client.host if request.client else "unknown",
        "query_params": dict(request.query_params) if request.query_params else {},
        "user_agent": request.headers.get("user-agent")
    }
    user_context = extract_user_context_from_request(request)
    log_http_exception_to_db(
        exception=exc,
        error_code=error_code.value,
        error_category=category.value,
        request_context=request_context,
        user_id=user_context.get("user_id"),
        project_id=user_context.get("project_id"),
        session_id=user_context.get("session_id")
    )
    
    return JSONResponse(
        status_code=status_code,
        content=response
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Handle FastAPI request validation errors.
    
    Args:
        request: FastAPI request object
        exc: RequestValidationError instance
        
    Returns:
        JSONResponse with standardized error format
    """
    # Extract validation errors
    validation_errors = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error.get("loc", []))
        message = error.get("msg", "Validation error")
        error_type = error.get("type", "value_error")
        
        validation_errors.append({
            "field": field,
            "message": message,
            "type": error_type
        })
    
    # Build error response
    error_dict = {
        "code": ErrorCode.INVALID_INPUT.value,
        "category": ErrorCategory.VALIDATION.value,
        "message": "Request validation failed",
    }
    
    # Always include validation errors in details (these are safe to expose)
    error_dict["details"] = {
        "validation_errors": validation_errors
    }
    
    # Add API context and trace in DEBUG_MODE
    from src.Util.error_handler import DEBUG_MODE
    import traceback
    import sys
    
    if DEBUG_MODE:
        error_dict["details"]["api_error"] = {
            "endpoint": request.url.path,
            "method": request.method,
            "query_params": dict(request.query_params) if request.query_params else {},
            "client_host": request.client.host if request.client else "unknown"
        }
        
        # Include trace
        exc_info = sys.exc_info()
        if exc_info[0] is not None:
            error_dict["trace"] = ''.join(traceback.format_exception(*exc_info))
        else:
            error_dict["trace"] = ''.join(traceback.format_stack())
    
    response = {
        "status": "error",
        "error": error_dict
    }
    
    logger.warning(
        f"Validation error on {request.url.path}",
        extra={
            "path": request.url.path,
            "method": request.method,
            "errors": validation_errors
        }
    )
    
    # Log to database
    request_context = {
        "path": request.url.path,
        "method": request.method,
        "client": request.client.host if request.client else "unknown",
        "query_params": dict(request.query_params) if request.query_params else {},
        "user_agent": request.headers.get("user-agent")
    }
    user_context = extract_user_context_from_request(request)
    log_validation_exception_to_db(
        exception=exc,
        request_context=request_context,
        user_id=user_context.get("user_id"),
        project_id=user_context.get("project_id"),
        session_id=user_context.get("session_id")
    )
    
    return JSONResponse(
        status_code=400,
        content=response
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handle all unhandled exceptions.
    
    Args:
        request: FastAPI request object
        exc: Exception instance
        
    Returns:
        JSONResponse with standardized error format
    """
    # Build request context
    request_context = {
        "path": request.url.path,
        "method": request.method,
        "client": request.client.host if request.client else "unknown",
        "query_params": dict(request.query_params) if request.query_params else {},
        "user_agent": request.headers.get("user-agent")
    }
    
    # Log the full error with traceback
    logger.error(
        f"Unhandled exception on {request.url.path}: {str(exc)}",
        exc_info=True,
        extra=request_context
    )
    
    # ALWAYS log to database (regardless of DEBUG_MODE)
    user_context = extract_user_context_from_request(request)
    log_generic_exception_to_db(
        exception=exc,
        request_context=request_context,
        user_id=user_context.get("user_id"),
        project_id=user_context.get("project_id"),
        session_id=user_context.get("session_id")
    )
    
    # Build sanitized response (traceback included only if DEBUG_MODE is True)
    response = build_error_response(exc, include_traceback=True)
    
    # Add API context to details if DEBUG_MODE is enabled
    from src.Util.error_handler import DEBUG_MODE
    if DEBUG_MODE and "error" in response:
        if "details" not in response["error"]:
            response["error"]["details"] = {}
        
        if "api_error" not in response["error"]["details"]:
            response["error"]["details"]["api_error"] = {}
        
        response["error"]["details"]["api_error"].update({
            "endpoint": request.url.path,
            "method": request.method,
            "query_params": dict(request.query_params) if request.query_params else {},
            "client_host": request.client.host if request.client else "unknown"
        })
    
    return JSONResponse(
        status_code=500,
        content=response
    )


def register_exception_handlers(app):
    """
    Register all exception handlers with the FastAPI app.
    
    Args:
        app: FastAPI application instance
    """
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
    
    logger.info("Exception handlers registered successfully")
