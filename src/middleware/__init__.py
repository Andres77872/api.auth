"""
Middleware Package

Contains all middleware components for the application.
"""

from src.middleware.activity_logging import ActivityLoggingMiddleware
from src.middleware.api_audit import APIAuditMiddleware
from src.middleware.auth_context import AuthContextMiddleware
from src.middleware.authentication import (
    verify_session,
    verify_admin_access,
    verify_root_access,
    verify_project_access,
    require_permission,
    optional_auth,
    security
)
from src.middleware.error_handler import register_exception_handlers
from src.middleware.request_validation import RequestValidationMiddleware

__all__ = [
    # Middleware classes
    'ActivityLoggingMiddleware',
    'APIAuditMiddleware',
    'AuthContextMiddleware',
    'RequestValidationMiddleware',
    
    # Authentication dependencies
    'verify_session',
    'verify_admin_access',
    'verify_root_access',
    'verify_project_access',
    'require_permission',
    'optional_auth',
    'security',
    
    # Error handler registration
    'register_exception_handlers',
]
