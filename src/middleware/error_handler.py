"""
FastAPI Exception Handler Middleware

Handles all exceptions and converts them to standardized error responses
with UUID masking and detailed error descriptions.
"""

import logging
from typing import Union
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
    log_error
)

logger = logging.getLogger(__name__)


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """
    Handle custom AppException instances.
    
    Args:
        request: FastAPI request object
        exc: AppException instance
        
    Returns:
        JSONResponse with standardized error format
    """
    # Log the error with request context
    log_error(exc, {
        "path": request.url.path,
        "method": request.method,
        "client": request.client.host if request.client else "unknown"
    })
    
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict()
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
        "success": False,
        "error": {
            "code": error_code.value,
            "category": category.value,
            "message": sanitized_detail,
        }
    }
    
    logger.warning(
        f"HTTP {status_code} - {sanitized_detail}",
        extra={
            "path": request.url.path,
            "method": request.method,
            "status_code": status_code
        }
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
    
    response = {
        "success": False,
        "error": {
            "code": ErrorCode.INVALID_INPUT.value,
            "category": ErrorCategory.VALIDATION.value,
            "message": "Request validation failed",
            "details": {
                "validation_errors": validation_errors
            }
        }
    }
    
    logger.warning(
        f"Validation error on {request.url.path}",
        extra={
            "path": request.url.path,
            "method": request.method,
            "errors": validation_errors
        }
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
    # Log the full error with traceback
    logger.error(
        f"Unhandled exception on {request.url.path}: {str(exc)}",
        exc_info=True,
        extra={
            "path": request.url.path,
            "method": request.method,
            "client": request.client.host if request.client else "unknown"
        }
    )
    
    # Build sanitized response
    response = build_error_response(exc, include_traceback=False)
    
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
