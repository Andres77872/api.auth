"""
API Audit Logger Utility

Provides async/background logging functions for API audit trail.
Works with the api_audit_log table and stored procedures.
"""

import json
import time
import uuid
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

from src.Util.db_config import get_connection

logger = logging.getLogger(__name__)


class APIAuditLogger:
    """
    Utility class for logging API requests and responses to the audit log.
    Designed to work as background tasks without blocking requests.
    """
    
    # Sensitive fields to filter from request/response bodies
    SENSITIVE_FIELDS = [
        'password', 'password_hash', 'api_key', 'secret', 'token',
        'access_token', 'refresh_token', 'session_token', 'authorization',
        'temporary_password', 'reset_token', 'api_secret'
    ]
    
    # Sensitive headers to filter
    SENSITIVE_HEADERS = [
        'authorization', 'cookie', 'x-api-key', 'x-auth-token',
        'x-session-token', 'x-api-secret'
    ]
    
    # Endpoints to exclude from audit logging (high-frequency, low-value)
    EXCLUDED_PATHS = [
        '/ping',
        '/health',
        '/metrics',
        '/docs',
        '/redoc',
        '/openapi.json',
        '/auth/validate',  # Phase 1.3: high-frequency, low-value validation — skip sync audit log
    ]
    
    @staticmethod
    def should_log_request(path: str, method: str) -> bool:
        """
        Determine if a request should be logged based on path and method.
        
        Args:
            path: Request path
            method: HTTP method
            
        Returns:
            True if should log, False otherwise
        """
        # Exclude OPTIONS requests (CORS preflight - not business logic)
        if method == "OPTIONS":
            return False
        
        # Normalize path by removing query string if present
        path_without_query = path.split('?')[0]
        
        # Check if path is in exclusion list
        for excluded in APIAuditLogger.EXCLUDED_PATHS:
            # Exact match
            if path_without_query == excluded:
                return False
            # Sub-path match (e.g., /docs/openapi.json matches /docs)
            # Only match if followed by / to avoid false matches like /documents matching /docs
            if path_without_query.startswith(excluded + '/'):
                return False
        
        return True
    
    @staticmethod
    def filter_sensitive_data(data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Recursively filter sensitive data from dictionaries.
        
        Args:
            data: Data dictionary to filter
            
        Returns:
            Filtered dictionary with sensitive values masked
        """
        if not data or not isinstance(data, dict):
            return data
        
        filtered = {}
        for key, value in data.items():
            # Check if key is sensitive
            if any(sensitive in key.lower() for sensitive in APIAuditLogger.SENSITIVE_FIELDS):
                filtered[key] = '***FILTERED***'
            elif isinstance(value, dict):
                # Recursively filter nested dictionaries
                filtered[key] = APIAuditLogger.filter_sensitive_data(value)
            elif isinstance(value, list):
                # Filter lists of dictionaries
                filtered[key] = [
                    APIAuditLogger.filter_sensitive_data(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                filtered[key] = value
        
        return filtered
    
    @staticmethod
    def filter_headers(headers: Dict[str, str]) -> Dict[str, str]:
        """
        Filter sensitive headers.
        
        Args:
            headers: Request/response headers
            
        Returns:
            Filtered headers dictionary
        """
        filtered = {}
        for key, value in headers.items():
            if key.lower() in APIAuditLogger.SENSITIVE_HEADERS:
                filtered[key] = '***FILTERED***'
            else:
                filtered[key] = value
        
        return filtered
    
    @staticmethod
    def extract_resource_info(path: str, method: str) -> tuple:
        """
        Extract resource type and ID from request path.
        
        Args:
            path: Request path
            method: HTTP method
            
        Returns:
            Tuple of (resource_type, resource_id)
        """
        parts = [p for p in path.strip('/').split('/') if p]
        
        # Common patterns: /api/v1/users/{hash}, /api/v1/projects/{hash}
        resource_keywords = {
            'users': 'user',
            'projects': 'project',
            'groups': 'group',
            'user-groups': 'user_group',
            'project-groups': 'project_group',
            'roles': 'role',
            'permissions': 'permission',
            'sessions': 'session'
        }
        
        for keyword, resource_type in resource_keywords.items():
            if keyword in parts:
                idx = parts.index(keyword)
                # Next part might be the ID/hash
                if len(parts) > idx + 1:
                    potential_id = parts[idx + 1]
                    # Check if it looks like an ID (not another keyword)
                    if potential_id not in resource_keywords and '-' in potential_id:
                        return (resource_type, potential_id)
                return (resource_type, None)
        
        return (None, None)
    
    @staticmethod
    def is_security_event(path: str, method: str, status_code: int, user_type: Optional[str] = None) -> bool:
        """
        Determine if request is a security-relevant event.
        
        Args:
            path: Request path
            method: HTTP method
            status_code: Response status code
            user_type: User type if authenticated
            
        Returns:
            True if this is a security event
        """
        # Failed authentication
        if status_code == 401 and '/auth/' in path:
            return True
        
        # Unauthorized access attempts
        if status_code == 403:
            return True
        
        # Admin actions
        if '/admin/' in path and user_type in ['root', 'admin']:
            return True
        
        # DELETE operations
        if method == 'DELETE':
            return True
        
        # User type or permission changes
        if any(keyword in path for keyword in ['/user-type', '/permissions', '/roles']):
            return True
        
        # Password resets
        if '/password' in path or '/reset' in path:
            return True
        
        return False
    
    @staticmethod
    def generate_tags(path: str, method: str, status_code: int, user_type: Optional[str] = None) -> List[str]:
        """
        Generate searchable tags for the audit log entry.
        
        Args:
            path: Request path
            method: HTTP method
            status_code: Response status code
            user_type: User type if authenticated
            
        Returns:
            List of tags
        """
        tags = []
        
        # Add method tag
        tags.append(method.lower())
        
        # Add status category
        if status_code >= 500:
            tags.append('server_error')
        elif status_code >= 400:
            tags.append('client_error')
        elif status_code >= 300:
            tags.append('redirect')
        elif status_code >= 200:
            tags.append('success')
        
        # Add user type tag
        if user_type:
            tags.append(f'user_type_{user_type}')
        else:
            tags.append('unauthenticated')
        
        # Add endpoint category tags
        if '/auth/' in path:
            tags.append('authentication')
        if '/admin/' in path:
            tags.append('admin_action')
        if '/users/' in path:
            tags.append('user_management')
        if '/projects/' in path:
            tags.append('project_management')
        if '/groups/' in path:
            tags.append('group_management')
        if '/roles/' in path:
            tags.append('role_management')
        if '/permissions/' in path:
            tags.append('permission_management')
        
        # Add operation type
        if method == 'POST':
            tags.append('create')
        elif method == 'PUT' or method == 'PATCH':
            tags.append('update')
        elif method == 'DELETE':
            tags.append('delete')
        elif method == 'GET':
            tags.append('read')
        
        return tags
    
    @staticmethod
    def log_request(
        audit_id: str,
        request_id: str,
        http_method: str,
        endpoint_path: str,
        route_pattern: Optional[str],
        user_id: Optional[str],
        user_type: Optional[str],
        session_id: Optional[str],
        request_headers: Optional[Dict],
        request_body: Optional[Dict],
        request_query: Optional[Dict],
        request_size_bytes: int,
        client_ip: Optional[str],
        user_agent: Optional[str],
        referer: Optional[str],
        project_id: Optional[str],
        metadata: Optional[Dict],
        auth_method: str = "session"
    ) -> bool:
        """
        Log API request start to database (called in background).

        Args:
            All request details
            auth_method: Authentication method used ('session' or 'api_key').
                         Defaults to 'session' for backward compatibility.

        Returns:
            True if logged successfully, False otherwise
        """
        t0 = time.monotonic()
        try:
            logger.info(f"API Audit: Logging request [{http_method}] {endpoint_path} [audit_id={audit_id}]")

            # Filter sensitive data
            filtered_headers = APIAuditLogger.filter_headers(request_headers) if request_headers else None
            filtered_body = APIAuditLogger.filter_sensitive_data(request_body) if request_body else None

            with get_connection() as conn:
                cursor = conn.cursor()
                logger.debug(f"Calling sp_log_api_request with method={http_method}, path={endpoint_path}")
                cursor.callproc('sp_log_api_request', (
                    audit_id,
                    request_id,
                    http_method,
                    endpoint_path,
                    route_pattern,
                    user_id,
                    user_type,
                    session_id,
                    json.dumps(filtered_headers) if filtered_headers else None,
                    json.dumps(filtered_body) if filtered_body else None,
                    json.dumps(request_query) if request_query else None,
                    request_size_bytes,
                    client_ip,
                    user_agent,
                    referer,
                    project_id,
                    json.dumps(metadata) if metadata else None,
                    auth_method
                ))
                conn.commit()

            logger.debug(f"Successfully logged API request: {audit_id}")
            logger.info(f"AUTH_PERF|api_audit_log|{(time.monotonic() - t0) * 1000:.3f}")
            return True

        except Exception as e:
            logger.info(f"AUTH_PERF|api_audit_log|{(time.monotonic() - t0) * 1000:.3f}")
            logger.error(
                f"Failed to log API request [audit_id={audit_id}, endpoint={endpoint_path}]: {e}",
                exc_info=True,
                extra={
                    "audit_id": audit_id,
                    "endpoint": endpoint_path,
                    "method": http_method,
                    "error_type": type(e).__name__
                }
            )
            return False
    
    @staticmethod
    def log_response(
        audit_id: str,
        response_status: int,
        response_body: Optional[Dict],
        response_headers: Optional[Dict],
        response_size_bytes: int,
        error_code: Optional[str],
        error_message: Optional[str],
        target_resource_type: Optional[str],
        target_resource_id: Optional[str],
        tags: Optional[List[str]],
        security_event: bool
    ) -> bool:
        """
        Update audit log with response details (called in background).
        
        Args:
            All response details
            
        Returns:
            True if logged successfully, False otherwise
        """
        try:
            logger.debug(f"Logging API response: status={response_status} [audit_id={audit_id}]")
            
            # Filter sensitive data
            filtered_body = APIAuditLogger.filter_sensitive_data(response_body) if response_body else None
            filtered_headers = APIAuditLogger.filter_headers(response_headers) if response_headers else None
            
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.callproc('sp_update_api_response', (
                    audit_id,
                    response_status,
                    json.dumps(filtered_body) if filtered_body else None,
                    json.dumps(filtered_headers) if filtered_headers else None,
                    response_size_bytes,
                    error_code,
                    error_message,
                    target_resource_type,
                    target_resource_id,
                    json.dumps(tags) if tags else None,
                    security_event
                ))
                conn.commit()
            
            logger.debug(f"Successfully logged API response: {audit_id}")
            return True
            
        except Exception as e:
            logger.error(
                f"Failed to log API response [audit_id={audit_id}, status={response_status}]: {e}", 
                exc_info=True,
                extra={
                    "audit_id": audit_id,
                    "status": response_status,
                    "error_type": type(e).__name__
                }
            )
            return False


def generate_audit_id() -> str:
    """Generate unique audit log ID"""
    return f"audit-{uuid.uuid4()}"


def generate_request_id() -> str:
    """Generate unique request ID"""
    return f"req-{uuid.uuid4()}"
