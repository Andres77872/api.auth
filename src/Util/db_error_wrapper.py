"""
Database Error Wrapper

Provides wrapper functions for database operations to handle errors consistently
with UUID masking and detailed error descriptions.
"""

import logging
import re
from typing import Callable, TypeVar, Any, Optional, Dict, Tuple
from functools import wraps
import pymysql
from redis.exceptions import RedisError

from src.Util.error_handler import (
    AppException,
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


def parse_duplicate_entry_error(error_msg: str) -> Dict[str, str]:
    """
    Parse MySQL duplicate entry error to extract details.
    
    Example error: (1062, "Duplicate entry 'basic' for key 'roles.uk_role_name'")
    
    Returns:
        Dictionary with 'value', 'table', 'key' fields
    """
    details = {
        "value": "unknown",
        "table": "unknown", 
        "key": "unknown",
        "field": "unknown"
    }
    
    # Pattern: Duplicate entry 'VALUE' for key 'TABLE.KEY'
    pattern = r"Duplicate entry '([^']+)' for key '([^.]+)\.([^']+)'"
    match = re.search(pattern, error_msg)
    
    if match:
        details["value"] = match.group(1)
        details["table"] = match.group(2)
        details["key"] = match.group(3)
        
        # Try to extract field name from key name
        # Common patterns: uk_role_name, idx_username, etc.
        key_name = match.group(3).lower()
        if "role_name" in key_name or "rolename" in key_name:
            details["field"] = "role_name"
        elif "username" in key_name or "user_name" in key_name:
            details["field"] = "username"
        elif "email" in key_name:
            details["field"] = "email"
        elif "name" in key_name:
            details["field"] = "name"
        elif "project" in key_name:
            details["field"] = "project_name"
        elif "group" in key_name:
            details["field"] = "group_name"
        else:
            # Use the key name as field name (strip prefixes)
            details["field"] = re.sub(r'^(uk|idx|uq)_', '', key_name)
    
    return details


def handle_db_operation(
    operation: Callable[..., T],
    error_context: Optional[str] = None,
    not_found_message: Optional[str] = None,
    default_return: Any = None
) -> T:
    """
    Wrapper for database operations with standardized error handling.
    
    Args:
        operation: Database operation function
        error_context: Context description for error messages
        not_found_message: Custom message for not found scenarios
        default_return: Default value to return on error (if provided, errors won't be raised)
        
    Returns:
        Result from the operation, or default_return on error
        
    Raises:
        DatabaseError: For database-related errors (unless default_return is provided)
        NotFoundError: When resource is not found (unless default_return is provided)
        ConflictError: For constraint violations (unless default_return is provided)
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
        # If default_return is provided, return it instead of raising
        if default_return is not None:
            return default_return() if callable(default_return) else default_return
        # Otherwise re-raise NotFoundError as-is
        raise

    except AppException:
        # Preserve already-classified application errors raised by nested
        # wrappers/routes. Rewrapping them hides the intended status/category.
        if default_return is not None:
            logger.warning(f"Application error, returning default: {error_context}", exc_info=True)
            return default_return() if callable(default_return) else default_return
        raise
        
    except pymysql.IntegrityError as e:
        # If default_return is provided, return it instead of raising
        if default_return is not None:
            logger.warning(f"Database integrity error, returning default: {error_context}", exc_info=True)
            return default_return() if callable(default_return) else default_return
        # Handle constraint violations (duplicates, foreign key violations)
        error_msg = str(e)
        error_code = e.args[0] if e.args else 0
        error_sql_msg = e.args[1] if len(e.args) > 1 else error_msg
        
        if "Duplicate entry" in error_msg or error_code == 1062:
            # Parse duplicate entry details
            duplicate_info = parse_duplicate_entry_error(error_msg)
            
            # Build user-friendly message
            field_name = duplicate_info["field"]
            field_value = duplicate_info["value"]
            
            message = f"A {duplicate_info['table']} with {field_name} '{field_value}' already exists"
            
            raise ConflictError(
                message=message,
                error_code=ErrorCode.DUPLICATE_ENTRY,
                details={
                    "constraint_type": "duplicate",
                    "field": field_name,
                    "value": field_value,
                    "table": duplicate_info["table"],
                    "constraint_key": duplicate_info["key"],
                    "mysql_error_code": error_code,
                    "mysql_error_message": sanitize_error_message(error_sql_msg),
                    "suggestion": f"Please use a different {field_name} or update the existing record"
                },
                original_error=e,
                error_context=error_context
            )
        elif "foreign key constraint" in error_msg.lower() or error_code == 1451 or error_code == 1452:
            # Parse foreign key error details
            sanitized_msg = sanitize_error_message(error_msg)
            error_sql_msg = e.args[1] if len(e.args) > 1 else error_msg
            
            # Determine if it's a delete restriction or invalid reference
            if error_code == 1451:
                message = "Cannot delete or update record because it is referenced by other records"
            elif error_code == 1452:
                message = "Cannot create or update record because the referenced record does not exist"
            else:
                message = "Foreign key constraint violation"
            
            raise DatabaseError(
                message=message,
                error_code=ErrorCode.CONSTRAINT_VIOLATION,
                details={
                    "constraint_type": "foreign_key",
                    "mysql_error_code": error_code,
                    "mysql_error_message": sanitize_error_message(error_sql_msg),
                    "error_details": sanitized_msg,
                    "suggestion": "Check that all referenced records exist and are not being used elsewhere"
                },
                original_error=e,
                error_context=error_context
            )
        else:
            sanitized_msg = sanitize_error_message(error_msg)
            error_sql_msg = e.args[1] if len(e.args) > 1 else error_msg
            
            raise DatabaseError(
                message=f"Database constraint violation: {sanitized_msg}",
                error_code=ErrorCode.CONSTRAINT_VIOLATION,
                details={
                    "constraint_type": "integrity",
                    "mysql_error_code": error_code,
                    "mysql_error_message": sanitize_error_message(error_sql_msg)
                },
                original_error=e,
                error_context=error_context
            )
    
    except pymysql.OperationalError as e:
        # If default_return is provided, return it instead of raising
        if default_return is not None:
            logger.warning(f"Database operational error, returning default: {error_context}", exc_info=True)
            return default_return() if callable(default_return) else default_return
        
        # Handle connection and operational errors
        error_code = e.args[0] if e.args else 0
        error_msg = e.args[1] if len(e.args) > 1 else str(e)
        sanitized_msg = sanitize_error_message(error_msg)
        
        raise DatabaseError(
            message=f"Database connection error: {sanitized_msg}",
            error_code=ErrorCode.CONNECTION_ERROR,
            details={
                "mysql_error_code": error_code,
                "mysql_error_message": sanitized_msg,
                "error_type": "OperationalError",
                "severity": "critical" if error_code in (2002, 2003, 2006, 2013) else "high"
            },
            original_error=e,
            error_context=error_context
        )
    
    except pymysql.ProgrammingError as e:
        # If default_return is provided, return it instead of raising
        if default_return is not None:
            logger.warning(f"Database programming error, returning default: {error_context}", exc_info=True)
            return default_return() if callable(default_return) else default_return
        
        # Handle SQL syntax and programming errors
        error_code = e.args[0] if e.args else 0
        error_msg = e.args[1] if len(e.args) > 1 else str(e)
        sanitized_msg = sanitize_error_message(error_msg)
        
        raise DatabaseError(
            message=f"Database query error: {sanitized_msg}",
            error_code=ErrorCode.QUERY_ERROR,
            details={
                "mysql_error_code": error_code,
                "mysql_error_message": sanitized_msg,
                "error_type": "ProgrammingError",
                "severity": "high"
            },
            original_error=e,
            error_context=error_context
        )
    
    except RedisError as e:
        # If default_return is provided, return it instead of raising
        if default_return is not None:
            logger.warning(f"Redis error, returning default: {error_context}", exc_info=True)
            return default_return() if callable(default_return) else default_return
        
        # Handle Redis cache errors
        sanitized_msg = sanitize_error_message(str(e))
        raise InternalError(
            message=f"Cache service error: {sanitized_msg}",
            error_code=ErrorCode.SERVICE_UNAVAILABLE,
            details={
                "error_type": type(e).__name__,
                "error_message": sanitized_msg,
                "service": "redis"
            },
            original_error=e,
            error_context=error_context
        )
    
    except Exception as e:
        # If default_return is provided, return it instead of raising
        if default_return is not None:
            logger.warning(f"Unexpected error, returning default: {error_context}", exc_info=True)
            return default_return() if callable(default_return) else default_return
        
        # Handle unexpected errors
        sanitized_msg = sanitize_error_message(str(e))
        logger.error(
            f"Unexpected error in database operation: {error_context or 'unknown'}",
            exc_info=True
        )
        raise InternalError(
            message=f"Internal error during {error_context or 'operation'}: {sanitized_msg}",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={
                "error_type": type(e).__name__,
                "error_message": sanitized_msg,
                "error_module": type(e).__module__
            },
            original_error=e,
            error_context=error_context
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
