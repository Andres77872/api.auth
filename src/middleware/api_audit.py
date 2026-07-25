"""
API Audit Middleware

Automatically logs ALL API requests and responses to api_audit_log table.
Runs logging in background tasks to avoid blocking requests.
"""

import json
import time
import logging
from typing import Callable, Optional, Dict, Any
from fastapi import Request, BackgroundTasks
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response, StreamingResponse
import io

from src.Util.api_audit_logger import (
    APIAuditLogger,
    generate_audit_id,
    generate_request_id
)
from src.Util.auth_constants import PATREON_WEBHOOK_ROUTE

logger = logging.getLogger(__name__)


class APIAuditMiddleware(BaseHTTPMiddleware):
    """
    Middleware to automatically log all API requests and responses.
    
    Features:
    - Logs every HTTP request/response to api_audit_log table
    - Filters sensitive data (passwords, tokens, etc.)
    - Runs logging as background tasks (non-blocking)
    - Extracts user context from request.state (set by auth middleware)
    - Automatically flags security events
    - Generates searchable tags
    
    Usage:
        app = FastAPI()
        app.add_middleware(APIAuditMiddleware)
    
    Note: This middleware should be added AFTER authentication middleware
    so it can access user context from request.state
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request and log to audit trail.
        
        Args:
            request: Incoming HTTP request
            call_next: Next middleware/endpoint in chain
            
        Returns:
            Response from endpoint
        """
        # Check if this request should be logged
        should_log = APIAuditLogger.should_log_request(request.url.path, request.method)
        logger.debug(f"API Audit Middleware: {request.method} {request.url.path} - should_log={should_log}")
        
        if not should_log:
            return await call_next(request)
        
        # Generate unique IDs
        audit_id = generate_audit_id()
        request_id = request.headers.get("X-Request-ID", generate_request_id())
        
        # Start timing
        start_time = time.time()
        
        # Extract user context (set by authentication middleware)
        user_id = None
        user_type = None
        session_id = None
        project_id = None
        auth_method = "session"  # Default for authenticated session traffic
        
        if hasattr(request.state, 'user'):
            user = request.state.user
            user_id = getattr(user, 'id', None)
            user_type = getattr(user, 'user_type', None)
        
        if hasattr(request.state, 'session_id'):
            session_id = request.state.session_id
            # Truncate session_id to 256 characters to fit database column
            if session_id:
                session_id = session_id[:256]
        
        if hasattr(request.state, 'project_id'):
            project_id = request.state.project_id
        
        path = str(request.url.path)

        if APIAuditLogger.is_google_oauth_path(path):
            auth_method = "oauth"
        elif self._is_patreon_webhook_path(path):
            auth_method = "webhook"
        elif self._is_patreon_internal_entitlements_path(path):
            auth_method = "api_key"
        elif self._is_stripe_webhook_path(path):
            auth_method = "webhook"
        elif self._is_billing_internal_path(path):
            auth_method = "api_key"
        elif hasattr(request.state, 'auth_method'):
            auth_method = request.state.auth_method
        else:
            auth_method = self._infer_auth_method(path, user_id=user_id, session_id=session_id)
        
        # Get client IP address
        client_ip = self._get_client_ip(request)
        
        # Get user agent and referer
        user_agent = request.headers.get("user-agent")
        referer = request.headers.get("referer")
        
        # Get request headers (convert to dict)
        request_headers = dict(request.headers)
        
        # Get query parameters
        request_query = dict(request.query_params) if request.query_params else None
        
        # Get request body (if present)
        request_body = None
        request_size_bytes = 0
        
        if request.method in ["POST", "PUT", "PATCH", "DELETE"]:
            try:
                if self._is_raw_body_audit_excluded(request.url.path):
                    request_size_bytes = int(request.headers.get("content-length") or 0)
                    request_body = {"_note": "Request body excluded from audit"}
                else:
                    # Read body
                    body_bytes = await request.body()
                    request_size_bytes = len(body_bytes)

                    if body_bytes:
                        try:
                            request_body = json.loads(body_bytes.decode('utf-8'))
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            # Body is not JSON, skip logging it
                            request_body = {"_note": "Non-JSON body"}

                        # BaseHTTPMiddleware supplies a _CachedRequest whose
                        # wrapped_receive() replays this cached body downstream.
                        # Replacing request._receive here breaks the ASGI
                        # disconnect lifecycle and can hang POST endpoints that
                        # return StreamingResponse.
                    
            except Exception as e:
                logger.warning(f"Failed to read request body: {e}")
        
        # Get route pattern if available
        route_pattern = None
        if hasattr(request, 'scope') and 'route' in request.scope:
            route = request.scope.get('route')
            if route and hasattr(route, 'path'):
                route_pattern = route.path
        
        # Log request start immediately (more reliable than background tasks)
        logger.info(f"API Audit Middleware: Capturing request [{request.method}] {str(request.url.path)}")
        APIAuditLogger.log_request(
            audit_id=audit_id,
            request_id=request_id,
            http_method=request.method,
            endpoint_path=str(request.url.path),
            route_pattern=route_pattern,
            user_id=user_id,
            user_type=user_type,
            session_id=session_id,
            request_headers=request_headers,
            request_body=request_body,
            request_query=request_query,
            request_size_bytes=request_size_bytes,
            client_ip=client_ip,
            user_agent=user_agent,
            referer=referer,
            project_id=project_id,
            metadata=None,
            auth_method=auth_method
        )
        
        # Process request
        try:
            response = await call_next(request)
            
            # Calculate duration
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Get response status
            status_code = response.status_code
            
            # Extract error information if present
            error_code = None
            error_message = None
            response_body_data = None
            
            # Try to read response body for error details (only for errors)
            if status_code >= 400:
                try:
                    # For StreamingResponse, we can't read the body without consuming it
                    # So we'll only read for regular Response objects
                    if hasattr(response, 'body') and not isinstance(response, StreamingResponse):
                        response_body = response.body
                        if response_body:
                            try:
                                response_body_data = json.loads(response_body.decode('utf-8'))
                                # Extract error details from standardized error response
                                if isinstance(response_body_data, dict) and 'error' in response_body_data:
                                    error_info = response_body_data['error']
                                    if isinstance(error_info, dict):
                                        error_code = error_info.get('code')
                                        error_message = error_info.get('message')
                            except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                                # Body is not JSON or can't be decoded, skip
                                pass
                except Exception as e:
                    logger.debug(f"Could not extract error details from response: {e}")
            
            # Extract resource info from path
            resource_type, resource_id = APIAuditLogger.extract_resource_info(
                path,
                request.method
            )
            
            # Determine if this is a security event
            is_security = APIAuditLogger.is_security_event(
                path,
                request.method,
                status_code,
                user_type
            ) or self._is_route_specific_security_event(path, status_code)
            
            # Generate tags
            tags = APIAuditLogger.generate_tags(
                path,
                request.method,
                status_code,
                user_type
            )
            tags = self._add_route_specific_tags(path, tags, status_code=status_code)
            
            # Get response headers
            response_headers = dict(response.headers) if hasattr(response, 'headers') else {}
            
            # Get response size (estimate)
            response_size_bytes = 0
            if 'content-length' in response_headers:
                try:
                    response_size_bytes = int(response_headers['content-length'])
                except (ValueError, TypeError):
                    pass
            
            # Create background task for response logging
            async def log_response_task():
                # Log error response body for debugging (filtered)
                filtered_response_body = None
                if status_code >= 400 and response_body_data:
                    filtered_response_body = APIAuditLogger.filter_sensitive_data(response_body_data)
                
                APIAuditLogger.log_response(
                    audit_id=audit_id,
                    response_status=status_code,
                    response_body=filtered_response_body,  # Log error responses for debugging
                    response_headers=response_headers,
                    response_size_bytes=response_size_bytes,
                    error_code=error_code,
                    error_message=error_message,
                    target_resource_type=resource_type,
                    target_resource_id=resource_id,
                    tags=tags,
                    security_event=is_security
                )
            
            # Add response logging to background tasks
            if hasattr(response, 'background') and response.background:
                # Add to existing background tasks
                response.background.add_task(log_response_task)
            else:
                # Create new background tasks
                background = BackgroundTasks()
                background.add_task(log_response_task)
                response.background = background
            
            return response
            
        except Exception as e:
            # Log failed request
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Extract error info
            error_code = type(e).__name__
            error_message = APIAuditLogger.sanitize_sensitive_text(str(e))
            
            # Get resource info
            resource_type, resource_id = APIAuditLogger.extract_resource_info(
                path,
                request.method
            )
            
            # Flag as security event if it's an auth error
            is_security = APIAuditLogger.is_security_event(
                path,
                request.method,
                500,
                user_type,
            ) or self._is_route_specific_security_event(path, 500) or (
                'auth' in error_code.lower() or
                'permission' in error_code.lower() or
                'unauthorized' in error_code.lower()
            )
            
            # Generate tags for failed request
            tags = APIAuditLogger.generate_tags(
                path,
                request.method,
                500,  # Server error
                user_type
            )
            tags.append('exception')
            tags = self._add_route_specific_tags(path, tags, status_code=500)
            
            # Log the error response immediately (before re-raising)
            try:
                APIAuditLogger.log_response(
                    audit_id=audit_id,
                    response_status=500,
                    response_body=None,
                    response_headers={},
                    response_size_bytes=0,
                    error_code=error_code,
                    error_message=error_message,
                    target_resource_type=resource_type,
                    target_resource_id=resource_id,
                    tags=tags,
                    security_event=is_security
                )
            except Exception as log_error:
                logger.error(f"Failed to log error response: {log_error}")
            
            # Re-raise the exception
            raise
    
    def _get_client_ip(self, request: Request) -> Optional[str]:
        """
        Extract client IP address from request.
        
        Args:
            request: HTTP request
            
        Returns:
            Client IP address or None
        """
        # Check for proxy headers first
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            # Take the first IP if multiple are present
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip
        
        # Fall back to direct client
        if request.client:
            return request.client.host
        
        return None

    def _is_raw_body_audit_excluded(self, path: str) -> bool:
        """Return True for provider webhook/token paths where raw body is sensitive."""
        normalized_path = self._normalize_path(path)
        return APIAuditLogger.is_raw_body_audit_excluded(normalized_path)

    def _infer_auth_method(self, path: str, user_id: Optional[str], session_id: Optional[str]) -> str:
        """Classify unauthenticated email-link/webhook flows for audit taxonomy."""
        normalized_path = self._normalize_path(path)
        if APIAuditLogger.is_google_oauth_path(normalized_path):
            return "oauth"
        if normalized_path.startswith("/webhooks/email") or self._is_patreon_webhook_path(normalized_path):
            return "webhook"
        if self._is_patreon_internal_entitlements_path(normalized_path):
            return "api_key"
        if self._is_stripe_webhook_path(normalized_path):
            return "webhook"
        if self._is_billing_internal_path(normalized_path):
            return "api_key"
        if APIAuditLogger.is_session_auth_security_path(normalized_path):
            return "session" if user_id or session_id else "anonymous"
        if normalized_path.startswith("/auth/email/") or normalized_path.startswith("/auth/password/reset"):
            return "email_link"
        if user_id or session_id:
            return "session"
        return "anonymous"

    def _normalize_path(self, path: str) -> str:
        """Normalize a request path without query parameters for route classification."""
        return (path or "").split("?", 1)[0].rstrip("/") or "/"

    def _is_patreon_webhook_path(self, path: str) -> bool:
        """Return True for the Patreon webhook route family."""
        normalized_path = self._normalize_path(path)
        return normalized_path == PATREON_WEBHOOK_ROUTE or normalized_path.startswith(f"{PATREON_WEBHOOK_ROUTE}/")

    def _is_patreon_internal_entitlements_path(self, path: str) -> bool:
        """Return True for internal Patreon entitlement S2S route paths."""
        normalized_path = self._normalize_path(path)
        parts = [part for part in normalized_path.strip("/").split("/") if part]
        return len(parts) >= 4 and parts[0] == "internal" and parts[1] == "users" and parts[3] == "entitlements"

    def _is_stripe_webhook_path(self, path: str) -> bool:
        """Return True for the Stripe webhook route family."""
        return APIAuditLogger.is_stripe_webhook_path(self._normalize_path(path))

    def _is_billing_internal_path(self, path: str) -> bool:
        """Return True for internal billing S2S route paths."""
        return APIAuditLogger.is_billing_internal_path(self._normalize_path(path))

    def _add_route_specific_tags(self, path: str, tags: list, status_code: int) -> list:
        """Add Patreon route tags without relying on new DB enum values."""
        deduped_tags = list(dict.fromkeys(tags))

        def add_tag(tag: str) -> None:
            if tag not in deduped_tags:
                deduped_tags.append(tag)

        if self._is_patreon_webhook_path(path):
            add_tag("patreon")
            add_tag("webhook")
            if status_code >= 400:
                add_tag("security_event")
        elif self._is_patreon_internal_entitlements_path(path):
            add_tag("patreon")
            add_tag("internal")
            add_tag("s2s")
            add_tag("api_key")
            if status_code in {401, 403}:
                add_tag("security_event")
        elif self._is_stripe_webhook_path(path):
            add_tag("billing")
            add_tag("stripe")
            add_tag("webhook")
            if status_code >= 400:
                add_tag("security_event")
        elif self._is_billing_internal_path(path):
            add_tag("billing")
            add_tag("internal")
            add_tag("s2s")
            add_tag("api_key")
            if status_code in {401, 403}:
                add_tag("security_event")

        return deduped_tags

    def _is_route_specific_security_event(self, path: str, status_code: int) -> bool:
        """Classify Patreon webhook/S2S auth failures as security events."""
        if self._is_patreon_webhook_path(path):
            return status_code >= 400
        if self._is_patreon_internal_entitlements_path(path):
            return status_code in {401, 403}
        if self._is_stripe_webhook_path(path):
            return status_code >= 400
        if self._is_billing_internal_path(path):
            return status_code in {401, 403}
        return False
