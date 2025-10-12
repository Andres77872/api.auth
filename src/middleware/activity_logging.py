"""
Activity Logging Middleware

Automatically captures request context (IP address, user agent) for activity logging.
This middleware sets up the context that will be automatically included in all activity logs.
"""

import logging
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.Util.activity_logger import set_request_context, clear_request_context

# Configure logging
logger = logging.getLogger(__name__)


class ActivityLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to automatically capture and set request context for activity logging.
    
    This middleware extracts IP address and user agent from incoming requests and makes
    them available to all activity logging calls within the request lifecycle.
    
    Usage:
        from fastapi import FastAPI
        from src.middleware.activity_logging import ActivityLoggingMiddleware
        
        app = FastAPI()
        app.add_middleware(ActivityLoggingMiddleware)
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request and set activity logging context
        
        Args:
            request: Incoming request
            call_next: Next middleware/endpoint in chain
            
        Returns:
            Response from endpoint
        """
        # Extract IP address
        ip_address = None
        if request.client:
            ip_address = request.client.host
        
        # Check for proxy headers (X-Forwarded-For, X-Real-IP)
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            # Take the first IP if multiple are present
            ip_address = forwarded_for.split(",")[0].strip()
        elif request.headers.get("x-real-ip"):
            ip_address = request.headers.get("x-real-ip")
        
        # Extract user agent
        user_agent = request.headers.get("user-agent")
        
        # Set context for activity logging
        set_request_context(ip_address=ip_address, user_agent=user_agent)
        
        try:
            # Process request
            response = await call_next(request)
            return response
        finally:
            # Clean up context after request
            clear_request_context()


# Alternative: Function-based middleware
async def activity_logging_middleware(request: Request, call_next: Callable) -> Response:
    """
    Function-based middleware for activity logging context.
    
    Usage:
        from fastapi import FastAPI
        from src.middleware.activity_logging import activity_logging_middleware
        
        app = FastAPI()
        app.middleware("http")(activity_logging_middleware)
    """
    # Extract IP address
    ip_address = None
    if request.client:
        ip_address = request.client.host
    
    # Check for proxy headers
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        ip_address = forwarded_for.split(",")[0].strip()
    elif request.headers.get("x-real-ip"):
        ip_address = request.headers.get("x-real-ip")
    
    # Extract user agent
    user_agent = request.headers.get("user-agent")
    
    # Set context
    set_request_context(ip_address=ip_address, user_agent=user_agent)
    
    try:
        response = await call_next(request)
        return response
    finally:
        clear_request_context()
