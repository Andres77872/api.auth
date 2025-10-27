"""
Database Error Logger

Logs all errors to the database for tracking and monitoring.
ALWAYS logs errors regardless of DEBUG_MODE setting.
DEBUG_MODE only controls what's returned in API responses, not database logging.
"""

import os
import json
import hashlib
import logging
from typing import Optional, Dict, Any
from datetime import datetime

from src.Util.db_config import get_connection

logger = logging.getLogger(__name__)


def generate_error_hash(
    error_code: str,
    error_message: str,
    request_path: Optional[str],
    function_name: Optional[str]
) -> str:
    """
    Generate a unique hash for this error occurrence.
    
    Args:
        error_code: Error code
        error_message: Error message
        request_path: API endpoint path
        function_name: Function where error occurred
        
    Returns:
        SHA256 hash of the error signature
    """
    timestamp = datetime.utcnow().isoformat()
    signature = f"{error_code}|{error_message}|{request_path}|{function_name}|{timestamp}"
    return hashlib.sha256(signature.encode()).hexdigest()


def log_error_to_database(
    error_code: str,
    error_category: str,
    error_message: str,
    status_code: int,
    severity_level: str = "error",
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    session_id: Optional[str] = None,
    request_path: Optional[str] = None,
    request_method: Optional[str] = None,
    request_query_params: Optional[Dict[str, Any]] = None,
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    function_name: Optional[str] = None,
    function_params: Optional[Dict[str, Any]] = None,
    error_context: Optional[str] = None,
    error_details: Optional[Dict[str, Any]] = None,
    database_error: Optional[Dict[str, Any]] = None,
    original_error_type: Optional[str] = None,
    original_error_message: Optional[str] = None,
    stack_trace: Optional[str] = None,
    debug_mode: bool = False
) -> Optional[str]:
    """
    Log error to the database.
    
    This function is called for EVERY error, regardless of DEBUG_MODE.
    DEBUG_MODE only affects what's returned to the client, not what's logged.
    
    Args:
        error_code: Error code (e.g., AUTH_1001, VAL_3001)
        error_category: Error category (authentication, validation, etc.)
        error_message: User-friendly error message
        status_code: HTTP status code
        severity_level: Severity (info, warning, error, critical)
        user_id: User ID (if authenticated)
        project_id: Project ID (if available)
        session_id: Session ID (if available)
        request_path: API endpoint path
        request_method: HTTP method
        request_query_params: Query parameters dict
        client_ip: Client IP address
        user_agent: User agent string
        function_name: Function where error occurred
        function_params: Function parameters dict
        error_context: Error context string
        error_details: Additional error details dict
        database_error: Database-specific error info dict
        original_error_type: Original exception type
        original_error_message: Original exception message
        stack_trace: Full stack trace
        debug_mode: Whether DEBUG_MODE was enabled when error occurred
        
    Returns:
        Error ID if successful, None if logging failed
    """
    try:
        # Generate error hash
        error_hash = generate_error_hash(
            error_code,
            error_message,
            request_path,
            function_name
        )
        
        # Get environment
        environment = os.getenv("ENVIRONMENT", "development")
        
        # Truncate session_id to fit database column (VARCHAR(256))
        # Session ID may be a JWT token which can be much longer
        if session_id and len(session_id) > 256:
            session_id = session_id[:256]
        
        # Convert dicts to JSON strings for database storage
        query_params_json = json.dumps(request_query_params) if request_query_params else None
        function_params_json = json.dumps(function_params) if function_params else None
        error_details_json = json.dumps(error_details) if error_details else None
        database_error_json = json.dumps(database_error) if database_error else None
        
        # Call stored procedure to log error
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_log_error', [
                error_hash,
                error_code,
                error_category,
                error_message,
                status_code,
                severity_level,
                user_id,
                project_id,
                session_id,
                request_path,
                request_method,
                query_params_json,
                client_ip,
                user_agent,
                function_name,
                function_params_json,
                error_context,
                error_details_json,
                database_error_json,
                original_error_type,
                original_error_message,
                stack_trace,
                environment,
                debug_mode
            ])
            result = cur.fetchone()
            
            if result:
                error_id = result[0]
                logger.debug(f"Error logged to database with ID: {error_id}")
                return error_id
            
            return None
        
    except Exception as e:
        # Don't let error logging failure break the application
        # Just log it and continue
        logger.error(f"Failed to log error to database: {str(e)}", exc_info=True)
        return None


def log_app_exception_to_db(
    exception,
    request_context: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    session_id: Optional[str] = None
) -> Optional[str]:
    """
    Log an AppException to the database with full context.
    
    This is a convenience function that extracts all relevant information
    from an AppException and logs it to the database.
    
    Args:
        exception: AppException instance
        request_context: Request context dict (path, method, query_params, client, user_agent)
        user_id: User ID (if authenticated)
        project_id: Project ID (if available)
        session_id: Session ID (if available)
        
    Returns:
        Error ID if successful, None if logging failed
    """
    from src.Util.error_handler import AppException, DEBUG_MODE
    
    if not isinstance(exception, AppException):
        logger.warning(f"Attempted to log non-AppException: {type(exception).__name__}")
        return None
    
    try:
        # Extract request context
        request_context = request_context or {}
        request_path = request_context.get('path')
        request_method = request_context.get('method')
        query_params = request_context.get('query_params')
        client_ip = request_context.get('client')
        user_agent = request_context.get('user_agent')
        
        # Extract function context from exception
        function_context = exception._extract_function_context()
        function_name = function_context.get('name') if function_context else None
        function_params = function_context.get('params') if function_context else None
        
        # Extract database error if present
        database_error = None
        if exception.details and isinstance(exception.details, dict):
            # Check if this is a database error
            if 'database_error' in exception.details:
                database_error = exception.details['database_error']
        
        # Determine severity level based on status code and category
        if exception.status_code >= 500:
            severity_level = "critical"
        elif exception.category.value in ['database', 'internal']:
            severity_level = "critical"
        elif exception.status_code >= 400:
            severity_level = "error"
        else:
            severity_level = "warning"
        
        # Log to database
        return log_error_to_database(
            error_code=exception.error_code.value,
            error_category=exception.category.value,
            error_message=exception.message,
            status_code=exception.status_code,
            severity_level=severity_level,
            user_id=user_id,
            project_id=project_id,
            session_id=session_id,
            request_path=request_path,
            request_method=request_method,
            request_query_params=query_params,
            client_ip=client_ip,
            user_agent=user_agent,
            function_name=function_name,
            function_params=function_params,
            error_context=exception.error_context,
            error_details=exception.details,
            database_error=database_error,
            original_error_type=type(exception.original_error).__name__ if exception.original_error else None,
            original_error_message=str(exception.original_error) if exception.original_error else None,
            stack_trace=exception.full_traceback,
            debug_mode=DEBUG_MODE
        )
        
    except Exception as e:
        logger.error(f"Failed to log AppException to database: {str(e)}", exc_info=True)
        return None


def log_generic_exception_to_db(
    exception: Exception,
    request_context: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    session_id: Optional[str] = None
) -> Optional[str]:
    """
    Log a generic (non-AppException) exception to the database.
    
    Args:
        exception: Exception instance
        request_context: Request context dict
        user_id: User ID (if authenticated)
        project_id: Project ID (if available)
        session_id: Session ID (if available)
        
    Returns:
        Error ID if successful, None if logging failed
    """
    from src.Util.error_handler import ErrorCode, ErrorCategory, DEBUG_MODE, sanitize_error_message
    import traceback
    
    try:
        # Extract request context
        request_context = request_context or {}
        request_path = request_context.get('path')
        request_method = request_context.get('method')
        query_params = request_context.get('query_params')
        client_ip = request_context.get('client')
        user_agent = request_context.get('user_agent')
        
        # Get stack trace
        stack_trace = traceback.format_exc()
        
        # Log to database
        return log_error_to_database(
            error_code=ErrorCode.INTERNAL_ERROR.value,
            error_category=ErrorCategory.INTERNAL.value,
            error_message=sanitize_error_message(str(exception)),
            status_code=500,
            severity_level="critical",
            user_id=user_id,
            project_id=project_id,
            session_id=session_id,
            request_path=request_path,
            request_method=request_method,
            request_query_params=query_params,
            client_ip=client_ip,
            user_agent=user_agent,
            function_name=None,
            function_params=None,
            error_context=None,
            error_details={
                "error_type": type(exception).__name__,
                "error_module": type(exception).__module__
            },
            database_error=None,
            original_error_type=type(exception).__name__,
            original_error_message=str(exception),
            stack_trace=stack_trace,
            debug_mode=DEBUG_MODE
        )
        
    except Exception as e:
        logger.error(f"Failed to log generic exception to database: {str(e)}", exc_info=True)
        return None
