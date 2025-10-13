"""
Database Error Wrapper

Provides wrapper functions for database operations to handle errors consistently
with UUID masking and detailed error descriptions.
"""

import logging
from typing import Callable, TypeVar, Any, Optional
from functools import wraps
import pymysql
from redis.exceptions import RedisError

from src.Util.error_handler import (
    DatabaseError,
    NotFoundError,
    ConflictError,
    InternalError,
    ErrorCode,
    mask_uuid,
    sanitize_error_message,
    log_error
)

logger = logging.getLogger(__name__)

T = TypeVar('T')


def handle_db_operation(
    operation: Callable[..., T],
    error_context: Optional[str] = None,
    not_found_message: Optional[str] = None
) -> T:
    """
    Wrapper for database operations with standardized error handling.
    
    Args:
        operation: Database operation function
        error_context: Context description for error messages
        not_found_message: Custom message for not found scenarios
        
    Returns:
        Result from the operation
        
    Raises:
        DatabaseError: For database-related errors
        NotFoundError: When resource is not found
        ConflictError: For constraint violations
    """
    try:
        result = operation()
        
        # Handle None results as "not found" if not_found_message is provided
        if result is None and not_found_message:
            raise NotFoundError(
                message=not_found_message,
                error_code=ErrorCode.RESOURCE_NOT_FOUND
            )
        
        return result
        
    except NotFoundError:
        # Re-raise NotFoundError as-is
        raise
        
    except pymysql.IntegrityError as e:
        # Handle constraint violations (duplicates, foreign key violations)
        error_msg = str(e)
        
        if "Duplicate entry" in error_msg:
            # Extract field name if possible
            sanitized_msg = sanitize_error_message(error_msg)
            raise ConflictError(
                message=f"Resource already exists: {sanitized_msg}",
                error_code=ErrorCode.DUPLICATE_ENTRY,
                details={
                    "context": error_context or "database operation",
                    "constraint_type": "duplicate"
                }
            )
        elif "foreign key constraint" in error_msg.lower():
            sanitized_msg = sanitize_error_message(error_msg)
            raise DatabaseError(
                message=f"Foreign key constraint violation: {sanitized_msg}",
                error_code=ErrorCode.DATABASE_ERROR,
                details={
                    "context": error_context or "database operation",
                    "constraint_type": "foreign_key"
                }
            )
        else:
            sanitized_msg = sanitize_error_message(error_msg)
            raise DatabaseError(
                message=f"Integrity constraint violation: {sanitized_msg}",
                error_code=ErrorCode.DATABASE_ERROR,
                details={"context": error_context or "database operation"},
                original_error=e
            )
    
    except pymysql.OperationalError as e:
        # Handle connection and operational errors
        sanitized_msg = sanitize_error_message(str(e))
        raise DatabaseError(
            message=f"Database connection error: {sanitized_msg}",
            error_code=ErrorCode.CONNECTION_ERROR,
            details={"context": error_context or "database operation"},
            original_error=e
        )
    
    except pymysql.ProgrammingError as e:
        # Handle SQL syntax and programming errors
        sanitized_msg = sanitize_error_message(str(e))
        raise DatabaseError(
            message=f"Database query error: {sanitized_msg}",
            error_code=ErrorCode.QUERY_ERROR,
            details={"context": error_context or "database operation"},
            original_error=e
        )
    
    except RedisError as e:
        # Handle Redis cache errors
        sanitized_msg = sanitize_error_message(str(e))
        raise InternalError(
            message=f"Cache service error: {sanitized_msg}",
            error_code=ErrorCode.SERVICE_UNAVAILABLE,
            details={"context": error_context or "cache operation"},
            original_error=e
        )
    
    except Exception as e:
        # Handle unexpected errors
        sanitized_msg = sanitize_error_message(str(e))
        logger.error(
            f"Unexpected error in database operation: {error_context or 'unknown'}",
            exc_info=True
        )
        raise InternalError(
            message=f"Internal error during {error_context or 'operation'}: {sanitized_msg}",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"context": error_context or "database operation"},
            original_error=e
        )


def db_operation(error_context: Optional[str] = None, not_found_message: Optional[str] = None):
    """
    Decorator for database operations with standardized error handling.
    
    Usage:
        @db_operation(error_context="user creation")
        def create_user(username: str) -> User:
            # database operation
            return user
    
    Args:
        error_context: Context description for error messages
        not_found_message: Custom message for not found scenarios
        
    Returns:
        Decorated function
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            return handle_db_operation(
                lambda: func(*args, **kwargs),
                error_context=error_context or func.__name__,
                not_found_message=not_found_message
            )
        return wrapper
    return decorator


def safe_db_operation(func: Callable[..., T], *args, **kwargs) -> Optional[T]:
    """
    Execute a database operation safely, returning None on error instead of raising.
    
    Use this for non-critical operations where errors should be logged but not propagated.
    
    Args:
        func: Function to execute
        *args: Positional arguments for the function
        **kwargs: Keyword arguments for the function
        
    Returns:
        Function result or None on error
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        log_error(e, {"operation": func.__name__})
        return None


def validate_uuid_format(uuid_str: str, resource_type: str) -> None:
    """
    Validate UUID format and raise appropriate error if invalid.
    
    Args:
        uuid_str: UUID string to validate
        resource_type: Type of resource (for error message)
        
    Raises:
        ValidationError: If UUID format is invalid
    """
    from src.Util.error_handler import ValidationError
    
    if not uuid_str:
        raise ValidationError(
            message=f"Invalid {resource_type} identifier: empty value",
            error_code=ErrorCode.INVALID_UUID,
            details={"resource_type": resource_type}
        )
    
    # Basic UUID format validation
    import re
    uuid_pattern = r'^[a-z]+-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    if not re.match(uuid_pattern, uuid_str, re.IGNORECASE):
        masked = mask_uuid(uuid_str)
        raise ValidationError(
            message=f"Invalid {resource_type} identifier format: {masked}",
            error_code=ErrorCode.INVALID_UUID,
            details={
                "resource_type": resource_type,
                "provided_value": masked
            }
        )
