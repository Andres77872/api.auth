"""
Enhanced Error Handling System

Provides centralized error handling with:
- UUID masking for security
- Detailed error descriptions with full traceback (DEBUG_MODE only)
- Standardized error responses
- Error categorization
- Database-specific error details
- API error cause tracking
- DEBUG_MODE support for detailed error information including traces
"""

import os
import re
import traceback
import sys
import logging
from typing import Optional, Dict, Any, List
from enum import Enum

logger = logging.getLogger(__name__)

# Check if DEBUG_MODE is enabled (default: False)
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() in ("true", "1", "yes")


class ErrorCategory(str, Enum):
    """Error categories for better error organization"""
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    DATABASE = "database"
    INTERNAL = "internal"
    EXTERNAL = "external"


class ErrorCode(str, Enum):
    """
    Standardized error codes catalog
    
    Error code format: CATEGORY_NNNN
    - AUTH_1xxx: Authentication errors
    - AUTHZ_2xxx: Authorization errors
    - VAL_3xxx: Validation errors
    - NF_4xxx: Not Found errors
    - CONF_5xxx: Conflict errors
    - DB_6xxx: Database errors
    - INT_7xxx: Internal errors
    - EXT_8xxx: External service errors
    """
    
    # Authentication errors (1xxx)
    INVALID_CREDENTIALS = "AUTH_1001"
    SESSION_EXPIRED = "AUTH_1002"
    SESSION_INVALID = "AUTH_1003"
    TOKEN_INVALID = "AUTH_1004"
    ACCOUNT_INACTIVE = "AUTH_1005"
    ACCOUNT_LOCKED = "AUTH_1006"
    PASSWORD_RESET_REQUIRED = "AUTH_1007"
    MFA_REQUIRED = "AUTH_1008"
    MFA_INVALID = "AUTH_1009"
    
    # Authorization errors (2xxx)
    ACCESS_DENIED = "AUTHZ_2001"
    INSUFFICIENT_PERMISSIONS = "AUTHZ_2002"
    PROJECT_ACCESS_DENIED = "AUTHZ_2003"
    GROUP_ACCESS_DENIED = "AUTHZ_2004"
    RESOURCE_ACCESS_DENIED = "AUTHZ_2005"
    ROLE_ASSIGNMENT_DENIED = "AUTHZ_2006"
    PERMISSION_DENIED = "AUTHZ_2007"
    
    # Validation errors (3xxx)
    INVALID_INPUT = "VAL_3001"
    MISSING_REQUIRED_FIELD = "VAL_3002"
    INVALID_FORMAT = "VAL_3003"
    INVALID_UUID = "VAL_3004"
    INVALID_EMAIL = "VAL_3005"
    INVALID_USERNAME = "VAL_3006"
    WEAK_PASSWORD = "VAL_3007"
    INVALID_DATE = "VAL_3008"
    INVALID_RANGE = "VAL_3009"
    INVALID_LENGTH = "VAL_3010"
    INVALID_TYPE = "VAL_3011"
    INVALID_ENUM_VALUE = "VAL_3012"
    
    # Not Found errors (4xxx)
    USER_NOT_FOUND = "NF_4001"
    PROJECT_NOT_FOUND = "NF_4002"
    GROUP_NOT_FOUND = "NF_4003"
    RESOURCE_NOT_FOUND = "NF_4004"
    PERMISSION_NOT_FOUND = "NF_4005"
    SESSION_NOT_FOUND = "NF_4006"
    ROLE_NOT_FOUND = "NF_4007"
    ENDPOINT_NOT_FOUND = "NF_4008"
    USER_TYPE_NOT_FOUND = "NF_4009"
    
    # Conflict errors (5xxx)
    USERNAME_EXISTS = "CONF_5001"
    EMAIL_EXISTS = "CONF_5002"
    RESOURCE_EXISTS = "CONF_5003"
    DUPLICATE_ENTRY = "CONF_5004"
    STATE_CONFLICT = "CONF_5005"
    VERSION_CONFLICT = "CONF_5006"
    
    # Database errors (6xxx)
    DATABASE_ERROR = "DB_6001"
    CONNECTION_ERROR = "DB_6002"
    QUERY_ERROR = "DB_6003"
    TRANSACTION_ERROR = "DB_6004"
    CONSTRAINT_VIOLATION = "DB_6005"
    DEADLOCK = "DB_6006"
    
    # Internal errors (7xxx)
    INTERNAL_ERROR = "INT_7001"
    CONFIGURATION_ERROR = "INT_7002"
    SERVICE_UNAVAILABLE = "INT_7003"
    TIMEOUT = "INT_7004"
    RATE_LIMIT_EXCEEDED = "INT_7005"
    FEATURE_NOT_IMPLEMENTED = "INT_7006"
    
    # External service errors (8xxx)
    EXTERNAL_SERVICE_ERROR = "EXT_8001"
    EXTERNAL_API_ERROR = "EXT_8002"
    EXTERNAL_TIMEOUT = "EXT_8003"


def mask_uuid(uuid_str: str, prefix: Optional[str] = None) -> str:
    """
    Mask UUID to show only prefix, first 4 chars, and last 4 chars.
    
    Examples:
        usr-550e8400-e29b-41d4-a716-446655440000 -> usr-[550e]...[0000]
        proj-123e4567-e89b-12d3-a456-426614174000 -> proj-[123e]...[4000]
        550e8400-e29b-41d4-a716-446655440000 -> [550e]...[0000]
    
    Args:
        uuid_str: UUID string to mask
        prefix: Optional prefix to extract (e.g., 'usr', 'proj')
        
    Returns:
        Masked UUID string
    """
    if not uuid_str or not isinstance(uuid_str, str):
        return "[invalid]"
    
    # Extract prefix if present (e.g., usr-, proj-, grp-)
    prefix_match = re.match(r'^([a-z]+-)?(.+)$', uuid_str)
    if prefix_match:
        extracted_prefix = prefix_match.group(1) or ""
        uuid_part = prefix_match.group(2)
    else:
        extracted_prefix = ""
        uuid_part = uuid_str
    
    # Remove hyphens from UUID part
    clean_uuid = uuid_part.replace('-', '')
    
    # Check if it's a valid UUID format (at least 8 chars)
    if len(clean_uuid) < 8:
        return f"{extracted_prefix}[{uuid_str[:4]}...]"
    
    # Get first 4 and last 4 characters
    first_four = clean_uuid[:4]
    last_four = clean_uuid[-4:]
    
    return f"{extracted_prefix}[{first_four}]...[{last_four}]"


def mask_multiple_uuids(text: str) -> str:
    """
    Find and mask all UUIDs in a text string.
    
    Patterns matched:
    - prefix-UUID: usr-XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
    - plain UUID: XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
    
    Args:
        text: Text containing UUIDs
        
    Returns:
        Text with all UUIDs masked
    """
    if not text:
        return text
    
    # Pattern for prefix-UUID (e.g., usr-uuid, proj-uuid)
    pattern_with_prefix = r'([a-z]+-)([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})'
    # Pattern for plain UUID
    pattern_plain = r'\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b'
    
    # Replace UUIDs with prefix
    text = re.sub(
        pattern_with_prefix,
        lambda m: mask_uuid(m.group(0)),
        text,
        flags=re.IGNORECASE
    )
    
    # Replace plain UUIDs
    text = re.sub(
        pattern_plain,
        lambda m: mask_uuid(m.group(0)),
        text,
        flags=re.IGNORECASE
    )
    
    return text


def sanitize_error_message(message: str) -> str:
    """
    Sanitize error message by masking UUIDs and sensitive data.
    
    Args:
        message: Original error message
        
    Returns:
        Sanitized error message
    """
    if not message:
        return "An error occurred"
    
    # Mask all UUIDs
    sanitized = mask_multiple_uuids(message)
    
    # Mask potential IDs in various formats
    sanitized = re.sub(r'\bid[=:]\s*\d+', 'id=[REDACTED]', sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r'\buser_id[=:]\s*\d+', 'user_id=[REDACTED]', sanitized, flags=re.IGNORECASE)
    
    return sanitized


class AppException(Exception):
    """
    Base application exception with enhanced error details.
    
    All custom exceptions should inherit from this class.
    Automatically captures traceback and detailed error context.
    """
    
    def __init__(
        self,
        message: str,
        error_code: ErrorCode,
        category: ErrorCategory,
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
        error_context: Optional[str] = None
    ):
        self.message = sanitize_error_message(message)
        self.error_code = error_code
        self.category = category
        self.status_code = status_code
        self.details = details or {}
        self.original_error = original_error
        self.error_context = error_context  # Store function context string
        
        # Capture traceback at exception creation time
        self.traceback_str = ''.join(traceback.format_stack()[:-1])  # Exclude this __init__ frame
        self.exc_info = sys.exc_info()
        
        # If there's an active exception, capture its traceback too
        if self.exc_info[0] is not None:
            self.full_traceback = ''.join(traceback.format_exception(*self.exc_info))
        else:
            self.full_traceback = self.traceback_str
        
        # Sanitize details
        if self.details:
            self.details = self._sanitize_details(self.details)
        
        super().__init__(self.message)
    
    def _sanitize_details(self, details: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize details dictionary by masking sensitive data"""
        sanitized = {}
        for key, value in details.items():
            if isinstance(value, str):
                sanitized[key] = mask_multiple_uuids(value)
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_details(value)
            elif isinstance(value, list):
                sanitized[key] = [
                    self._sanitize_details(item) if isinstance(item, dict) else mask_multiple_uuids(str(item))
                    for item in value
                ]
            else:
                sanitized[key] = value
        return sanitized
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert exception to dictionary for API response.
        
        Response structure (Production):
        {
            "status": "error",
            "error": {
                "code": "ERROR_CODE",
                "category": "category",
                "message": "User-friendly message"
            }
        }
        
        Response structure (DEBUG_MODE):
        {
            "status": "error",
            "error": {
                "code": "ERROR_CODE",
                "category": "category",
                "message": "User-friendly message",
                "details": {
                    "context": {...},
                    "database_error": {...},  # if database error
                    "api_error": {...},       # if API error
                    "original_error": {...},
                    "trace": "..."            # full traceback
                }
            }
        }
        """
        error_dict = {
            "code": self.error_code.value,
            "category": self.category.value,
            "message": self.message,
        }
        
        # Include details and trace only if DEBUG_MODE is enabled
        if DEBUG_MODE:
            error_dict["details"] = self._build_detailed_error()
            error_dict["trace"] = self.full_traceback
        
        return {
            "status": "error",
            "error": error_dict
        }
    
    def _build_detailed_error(self) -> Dict[str, Any]:
        """
        Build detailed error information for DEBUG_MODE.
        
        Returns comprehensive error context including:
        - Context information (operation, parameters, etc.)
        - Function context (name and parameters)
        - Database error details (for database errors)
        - API error details (endpoint, method, etc.)
        - Original error (only for non-database errors to avoid redundancy)
        - Error metadata
        """
        detailed_info = {}
        
        # Include user-provided details
        if self.details:
            detailed_info["context"] = self.details.copy()
        
        # Extract and include function context if available
        function_context = self._extract_function_context()
        if function_context:
            detailed_info["function"] = function_context
        
        # Track if we have database error (to avoid redundancy)
        has_database_error = False
        
        # Include original error information with detailed breakdown
        if self.original_error:
            # For database errors (pymysql), extract detailed information
            if 'pymysql' in type(self.original_error).__module__:
                import pymysql
                has_database_error = True
                
                if isinstance(self.original_error, pymysql.IntegrityError):
                    error_code = self.original_error.args[0] if self.original_error.args else None
                    error_msg = self.original_error.args[1] if len(self.original_error.args) > 1 else str(self.original_error)
                    
                    detailed_info["database_error"] = {
                        "error_type": "IntegrityError",
                        "mysql_error_code": error_code,
                        "mysql_error_message": sanitize_error_message(error_msg),
                        "constraint_type": self._identify_constraint_type(error_code, error_msg)
                    }
                    
                elif isinstance(self.original_error, (pymysql.OperationalError, pymysql.ProgrammingError, pymysql.DatabaseError)):
                    error_code = self.original_error.args[0] if self.original_error.args else None
                    error_msg = self.original_error.args[1] if len(self.original_error.args) > 1 else str(self.original_error)
                    
                    detailed_info["database_error"] = {
                        "error_type": type(self.original_error).__name__,
                        "mysql_error_code": error_code,
                        "mysql_error_message": sanitize_error_message(error_msg),
                        "severity": self._get_db_error_severity(error_code)
                    }
            
            # Only include original_error for non-database errors to avoid redundancy
            # Database errors already have all info in database_error field
            if not has_database_error:
                detailed_info["original_error"] = {
                    "type": type(self.original_error).__name__,
                    "message": sanitize_error_message(str(self.original_error)),
                    "args": [sanitize_error_message(str(arg)) for arg in self.original_error.args] if hasattr(self.original_error, 'args') else []
                }
        
        # Add error metadata
        detailed_info["error_metadata"] = {
            "error_class": self.__class__.__name__,
            "error_code": self.error_code.value,
            "category": self.category.value,
            "status_code": self.status_code
        }
        
        return detailed_info
    
    def _extract_function_context(self) -> Optional[Dict[str, Any]]:
        """
        Extract function name and parameters from error context.
        
        Parses error_context strings like:
        - "create_user(username='john', email='john@example.com')"
        - "get_user_by_id(user_id=usr-abc123...def789)"
        - "update_project(project_id='123')"
        
        Returns:
            Dictionary with 'name' and 'params' or None if parsing fails
        """
        # Use error_context if provided, otherwise try to extract from details['context']
        context = self.error_context
        if not context and isinstance(self.details, dict):
            context = self.details.get('context')
        
        if not context or not isinstance(context, str):
            return None
        
        # Pattern: function_name(param1=value1, param2=value2, ...)
        pattern = r'^([a-zA-Z_][a-zA-Z0-9_]*)\((.*)\)$'
        match = re.match(pattern, context.strip())
        
        if not match:
            return None
        
        function_name = match.group(1)
        params_str = match.group(2)
        
        # Parse parameters
        params = {}
        if params_str:
            # Split by comma, but be careful with nested structures
            # Simple parsing: split by ', ' and then by '='
            param_parts = []
            current_part = []
            depth = 0
            
            for char in params_str + ',':
                if char in '([{':
                    depth += 1
                    current_part.append(char)
                elif char in ')]}':
                    depth -= 1
                    current_part.append(char)
                elif char == ',' and depth == 0:
                    if current_part:
                        param_parts.append(''.join(current_part).strip())
                        current_part = []
                else:
                    current_part.append(char)
            
            # Parse each parameter
            for part in param_parts:
                if '=' in part:
                    key, value = part.split('=', 1)
                    params[key.strip()] = value.strip().strip("'\"")
        
        return {
            "name": function_name,
            "params": params
        }
    
    def _identify_constraint_type(self, error_code: Optional[int], error_msg: str) -> str:
        """Identify the type of database constraint violation"""
        if error_code == 1062 or "Duplicate entry" in error_msg:
            return "duplicate_key"
        elif error_code == 1451:
            return "foreign_key_delete_restrict"
        elif error_code == 1452:
            return "foreign_key_invalid_reference"
        elif error_code == 1048:
            return "not_null_violation"
        elif "foreign key" in error_msg.lower():
            return "foreign_key_constraint"
        else:
            return "integrity_constraint"
    
    def _get_db_error_severity(self, error_code: Optional[int]) -> str:
        """Determine the severity of a database error"""
        if not error_code:
            return "unknown"
        
        # Critical errors (connection, server issues)
        if error_code in (2002, 2003, 2006, 2013):
            return "critical"
        # Syntax/programming errors
        elif error_code in (1064, 1146, 1054):
            return "high"
        # Constraint violations
        elif error_code in (1062, 1451, 1452, 1048):
            return "medium"
        else:
            return "low"


# =================== SPECIFIC EXCEPTION CLASSES ===================

class AuthenticationError(AppException):
    """Authentication related errors"""
    
    def __init__(self, message: str, error_code: ErrorCode = ErrorCode.INVALID_CREDENTIALS, details: Optional[Dict[str, Any]] = None, original_error: Optional[Exception] = None, error_context: Optional[str] = None):
        super().__init__(
            message=message,
            error_code=error_code,
            category=ErrorCategory.AUTHENTICATION,
            status_code=401,
            details=details,
            original_error=original_error,
            error_context=error_context
        )


class AuthorizationError(AppException):
    """Authorization/Permission related errors"""
    
    def __init__(self, message: str, error_code: ErrorCode = ErrorCode.ACCESS_DENIED, details: Optional[Dict[str, Any]] = None, original_error: Optional[Exception] = None, error_context: Optional[str] = None):
        super().__init__(
            message=message,
            error_code=error_code,
            category=ErrorCategory.AUTHORIZATION,
            status_code=403,
            details=details,
            original_error=original_error,
            error_context=error_context
        )


class ValidationError(AppException):
    """Input validation errors"""
    
    def __init__(self, message: str, error_code: ErrorCode = ErrorCode.INVALID_INPUT, details: Optional[Dict[str, Any]] = None, original_error: Optional[Exception] = None, error_context: Optional[str] = None):
        super().__init__(
            message=message,
            error_code=error_code,
            category=ErrorCategory.VALIDATION,
            status_code=400,
            details=details,
            original_error=original_error,
            error_context=error_context
        )


class NotFoundError(AppException):
    """Resource not found errors"""
    
    def __init__(self, message: str, error_code: ErrorCode = ErrorCode.RESOURCE_NOT_FOUND, details: Optional[Dict[str, Any]] = None, original_error: Optional[Exception] = None, error_context: Optional[str] = None):
        super().__init__(
            message=message,
            error_code=error_code,
            category=ErrorCategory.NOT_FOUND,
            status_code=404,
            details=details,
            original_error=original_error,
            error_context=error_context
        )


class ConflictError(AppException):
    """Resource conflict errors"""
    
    def __init__(self, message: str, error_code: ErrorCode = ErrorCode.RESOURCE_EXISTS, details: Optional[Dict[str, Any]] = None, original_error: Optional[Exception] = None, error_context: Optional[str] = None):
        super().__init__(
            message=message,
            error_code=error_code,
            category=ErrorCategory.CONFLICT,
            status_code=409,
            details=details,
            original_error=original_error,
            error_context=error_context
        )


class DatabaseError(AppException):
    """Database operation errors"""
    
    def __init__(self, message: str, error_code: ErrorCode = ErrorCode.DATABASE_ERROR, details: Optional[Dict[str, Any]] = None, original_error: Optional[Exception] = None, error_context: Optional[str] = None):
        super().__init__(
            message=message,
            error_code=error_code,
            category=ErrorCategory.DATABASE,
            status_code=500,
            details=details,
            original_error=original_error,
            error_context=error_context
        )


class InternalError(AppException):
    """Internal server errors"""
    
    def __init__(self, message: str, error_code: ErrorCode = ErrorCode.INTERNAL_ERROR, details: Optional[Dict[str, Any]] = None, original_error: Optional[Exception] = None, error_context: Optional[str] = None):
        super().__init__(
            message=message,
            error_code=error_code,
            category=ErrorCategory.INTERNAL,
            status_code=500,
            details=details,
            original_error=original_error,
            error_context=error_context
        )


class FeatureNotImplementedError(AppException):
    """Feature not yet implemented (501 Not Implemented)"""
    
    def __init__(self, message: str, error_code: ErrorCode = ErrorCode.FEATURE_NOT_IMPLEMENTED, details: Optional[Dict[str, Any]] = None, original_error: Optional[Exception] = None, error_context: Optional[str] = None):
        super().__init__(
            message=message,
            error_code=error_code,
            category=ErrorCategory.INTERNAL,
            status_code=501,
            details=details,
            original_error=original_error,
            error_context=error_context
        )


# =================== ERROR RESPONSE BUILDER ===================

def build_error_response(
    error: Exception,
    include_traceback: bool = True
) -> Dict[str, Any]:
    """
    Build standardized error response from exception.
    
    Args:
        error: Exception object
        include_traceback: Whether to include stack trace (only if DEBUG_MODE is enabled, defaults to True)
        
    Returns:
        Standardized error response dictionary with structure:
        
        Production Mode:
        {
            "status": "error",
            "error": {
                "code": "ERROR_CODE",
                "category": "category",
                "message": "User-friendly message"
            }
        }
        
        DEBUG_MODE:
        {
            "status": "error",
            "error": {
                "code": "ERROR_CODE",
                "category": "category",
                "message": "User-friendly message",
                "details": {
                    "error_type": "...",
                    "context": {...},
                    "database_error": {...},  # if applicable
                    "original_error": {...}
                },
                "trace": "..."  # full traceback
            }
        }
    """
    if isinstance(error, AppException):
        # AppException already handles DEBUG_MODE and includes trace
        response = error.to_dict()
    else:
        # Handle unexpected exceptions
        error_dict = {
            "code": ErrorCode.INTERNAL_ERROR.value,
            "category": ErrorCategory.INTERNAL.value,
            "message": sanitize_error_message(str(error)),
        }
        
        # Add detailed information and trace if DEBUG_MODE is enabled
        if DEBUG_MODE:
            error_dict["details"] = {
                "error_type": type(error).__name__,
                "error_message": sanitize_error_message(str(error)),
                "error_module": type(error).__module__
            }
            
            # Include exception args if available
            if hasattr(error, 'args') and error.args:
                error_dict["details"]["error_args"] = [
                    sanitize_error_message(str(arg)) for arg in error.args
                ]
            
            # Always include trace in DEBUG_MODE
            if include_traceback:
                # Get current traceback or format the exception
                exc_info = sys.exc_info()
                if exc_info[0] is not None:
                    error_dict["trace"] = ''.join(traceback.format_exception(*exc_info))
                else:
                    error_dict["trace"] = traceback.format_exc()
        
        response = {
            "status": "error",
            "error": error_dict
        }
    
    return response


def get_http_exception_details(error: AppException) -> tuple:
    """
    Extract HTTP status code and detail from AppException.
    
    Args:
        error: AppException instance
        
    Returns:
        Tuple of (status_code, detail_dict)
    """
    return error.status_code, error.to_dict()


# =================== HELPER FUNCTIONS ===================

def create_validation_error(field: str, message: str, value: Any = None) -> ValidationError:
    """Create a validation error for a specific field"""
    details = {
        "field": field,
        "provided_value": sanitize_error_message(str(value)) if value else None
    }
    return ValidationError(
        message=f"Invalid {field}: {message}",
        error_code=ErrorCode.INVALID_INPUT,
        details=details
    )


def create_not_found_error(resource_type: str, identifier: str) -> NotFoundError:
    """Create a not found error for a resource"""
    masked_id = mask_uuid(identifier) if identifier else "[unknown]"
    
    error_code_map = {
        "user": ErrorCode.USER_NOT_FOUND,
        "project": ErrorCode.PROJECT_NOT_FOUND,
        "group": ErrorCode.GROUP_NOT_FOUND,
        "permission": ErrorCode.PERMISSION_NOT_FOUND,
        "session": ErrorCode.SESSION_NOT_FOUND,
    }
    
    error_code = error_code_map.get(resource_type.lower(), ErrorCode.RESOURCE_NOT_FOUND)
    
    return NotFoundError(
        message=f"{resource_type.capitalize()} not found: {masked_id}",
        error_code=error_code,
        details={
            "resource_type": resource_type,
            "identifier": masked_id
        }
    )


def create_access_denied_error(resource_type: str, action: str, identifier: Optional[str] = None) -> AuthorizationError:
    """Create an access denied error"""
    masked_id = mask_uuid(identifier) if identifier else None
    
    message = f"Access denied: Cannot {action} {resource_type}"
    if masked_id:
        message += f" {masked_id}"
    
    error_code_map = {
        "project": ErrorCode.PROJECT_ACCESS_DENIED,
        "group": ErrorCode.GROUP_ACCESS_DENIED,
    }
    
    error_code = error_code_map.get(resource_type.lower(), ErrorCode.ACCESS_DENIED)
    
    details = {
        "resource_type": resource_type,
        "action": action
    }
    if masked_id:
        details["identifier"] = masked_id
    
    return AuthorizationError(
        message=message,
        error_code=error_code,
        details=details
    )


def log_error(error: Exception, context: Optional[Dict[str, Any]] = None):
    """
    Log error with context information.
    
    Args:
        error: Exception to log
        context: Additional context information
    """
    context = context or {}
    
    if isinstance(error, AppException):
        logger.error(
            f"[{error.error_code.value}] {error.message}",
            extra={
                "error_code": error.error_code.value,
                "category": error.category.value,
                "details": error.details,
                **context
            }
        )
    else:
        logger.error(
            f"Unexpected error: {sanitize_error_message(str(error))}",
            exc_info=True,
            extra=context
        )
