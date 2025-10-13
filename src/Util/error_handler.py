"""
Enhanced Error Handling System

Provides centralized error handling with:
- UUID masking for security
- Detailed error descriptions
- Standardized error responses
- Error categorization
"""

import re
import traceback
import logging
from typing import Optional, Dict, Any, List
from enum import Enum

logger = logging.getLogger(__name__)


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
    """Standardized error codes"""
    # Authentication errors (1xxx)
    INVALID_CREDENTIALS = "AUTH_1001"
    SESSION_EXPIRED = "AUTH_1002"
    SESSION_INVALID = "AUTH_1003"
    TOKEN_INVALID = "AUTH_1004"
    ACCOUNT_INACTIVE = "AUTH_1005"
    ACCOUNT_LOCKED = "AUTH_1006"
    
    # Authorization errors (2xxx)
    ACCESS_DENIED = "AUTHZ_2001"
    INSUFFICIENT_PERMISSIONS = "AUTHZ_2002"
    PROJECT_ACCESS_DENIED = "AUTHZ_2003"
    GROUP_ACCESS_DENIED = "AUTHZ_2004"
    RESOURCE_ACCESS_DENIED = "AUTHZ_2005"
    
    # Validation errors (3xxx)
    INVALID_INPUT = "VAL_3001"
    MISSING_REQUIRED_FIELD = "VAL_3002"
    INVALID_FORMAT = "VAL_3003"
    INVALID_UUID = "VAL_3004"
    INVALID_EMAIL = "VAL_3005"
    INVALID_USERNAME = "VAL_3006"
    WEAK_PASSWORD = "VAL_3007"
    
    # Not Found errors (4xxx)
    USER_NOT_FOUND = "NF_4001"
    PROJECT_NOT_FOUND = "NF_4002"
    GROUP_NOT_FOUND = "NF_4003"
    RESOURCE_NOT_FOUND = "NF_4004"
    PERMISSION_NOT_FOUND = "NF_4005"
    SESSION_NOT_FOUND = "NF_4006"
    
    # Conflict errors (5xxx)
    USERNAME_EXISTS = "CONF_5001"
    EMAIL_EXISTS = "CONF_5002"
    RESOURCE_EXISTS = "CONF_5003"
    DUPLICATE_ENTRY = "CONF_5004"
    
    # Database errors (6xxx)
    DATABASE_ERROR = "DB_6001"
    CONNECTION_ERROR = "DB_6002"
    QUERY_ERROR = "DB_6003"
    TRANSACTION_ERROR = "DB_6004"
    
    # Internal errors (7xxx)
    INTERNAL_ERROR = "INT_7001"
    CONFIGURATION_ERROR = "INT_7002"
    SERVICE_UNAVAILABLE = "INT_7003"


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
    """
    
    def __init__(
        self,
        message: str,
        error_code: ErrorCode,
        category: ErrorCategory,
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None
    ):
        self.message = sanitize_error_message(message)
        self.error_code = error_code
        self.category = category
        self.status_code = status_code
        self.details = details or {}
        self.original_error = original_error
        
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
        """Convert exception to dictionary for API response"""
        result = {
            "success": False,
            "error": {
                "code": self.error_code.value,
                "category": self.category.value,
                "message": self.message,
            }
        }
        
        if self.details:
            result["error"]["details"] = self.details
        
        return result


# =================== SPECIFIC EXCEPTION CLASSES ===================

class AuthenticationError(AppException):
    """Authentication related errors"""
    
    def __init__(self, message: str, error_code: ErrorCode = ErrorCode.INVALID_CREDENTIALS, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            error_code=error_code,
            category=ErrorCategory.AUTHENTICATION,
            status_code=401,
            details=details
        )


class AuthorizationError(AppException):
    """Authorization/Permission related errors"""
    
    def __init__(self, message: str, error_code: ErrorCode = ErrorCode.ACCESS_DENIED, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            error_code=error_code,
            category=ErrorCategory.AUTHORIZATION,
            status_code=403,
            details=details
        )


class ValidationError(AppException):
    """Input validation errors"""
    
    def __init__(self, message: str, error_code: ErrorCode = ErrorCode.INVALID_INPUT, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            error_code=error_code,
            category=ErrorCategory.VALIDATION,
            status_code=400,
            details=details
        )


class NotFoundError(AppException):
    """Resource not found errors"""
    
    def __init__(self, message: str, error_code: ErrorCode = ErrorCode.RESOURCE_NOT_FOUND, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            error_code=error_code,
            category=ErrorCategory.NOT_FOUND,
            status_code=404,
            details=details
        )


class ConflictError(AppException):
    """Resource conflict errors"""
    
    def __init__(self, message: str, error_code: ErrorCode = ErrorCode.RESOURCE_EXISTS, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            error_code=error_code,
            category=ErrorCategory.CONFLICT,
            status_code=409,
            details=details
        )


class DatabaseError(AppException):
    """Database operation errors"""
    
    def __init__(self, message: str, error_code: ErrorCode = ErrorCode.DATABASE_ERROR, details: Optional[Dict[str, Any]] = None, original_error: Optional[Exception] = None):
        super().__init__(
            message=message,
            error_code=error_code,
            category=ErrorCategory.DATABASE,
            status_code=500,
            details=details,
            original_error=original_error
        )


class InternalError(AppException):
    """Internal server errors"""
    
    def __init__(self, message: str, error_code: ErrorCode = ErrorCode.INTERNAL_ERROR, details: Optional[Dict[str, Any]] = None, original_error: Optional[Exception] = None):
        super().__init__(
            message=message,
            error_code=error_code,
            category=ErrorCategory.INTERNAL,
            status_code=500,
            details=details,
            original_error=original_error
        )


# =================== ERROR RESPONSE BUILDER ===================

def build_error_response(
    error: Exception,
    include_traceback: bool = False
) -> Dict[str, Any]:
    """
    Build standardized error response from exception.
    
    Args:
        error: Exception object
        include_traceback: Whether to include stack trace (dev mode only)
        
    Returns:
        Standardized error response dictionary
    """
    if isinstance(error, AppException):
        response = error.to_dict()
    else:
        # Handle unexpected exceptions
        response = {
            "success": False,
            "error": {
                "code": ErrorCode.INTERNAL_ERROR.value,
                "category": ErrorCategory.INTERNAL.value,
                "message": sanitize_error_message(str(error)),
            }
        }
    
    if include_traceback:
        response["error"]["traceback"] = traceback.format_exc()
    
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
