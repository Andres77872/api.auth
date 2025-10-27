"""
Request Validation and Processing Middleware

Handles request validation, processing time tracking, and activity logging context.
"""

import time
import logging
from typing import Callable
from fastapi import Request, BackgroundTasks
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from src.Util.Seccurity import returnJson_422, returnJson_413
from src.Util.activity_logger import set_request_context, clear_request_context
from src.Util.logger_ws import logger

# Configure logging
log = logging.getLogger(__name__)


class RequestValidationMiddleware(BaseHTTPMiddleware):
    """
    Middleware for request validation, processing time tracking, and activity logging context.
    
    Features:
    - Validates user-agent header presence
    - Checks POST request size limits (8MB)
    - Tracks request processing time
    - Sets activity logging context (IP, user agent)
    - Logs requests via logger_ws
    
    Usage:
        app = FastAPI()
        app.add_middleware(RequestValidationMiddleware)
    """
    
    # Maximum POST request size in bytes (8MB)
    MAX_CONTENT_LENGTH = 8388608
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process and validate incoming requests.
        
        Args:
            request: Incoming HTTP request
            call_next: Next middleware/endpoint in chain
            
        Returns:
            Response from endpoint or validation error response
        """
        start_time = time.time()
        
        # Validate user-agent header
        if 'user-agent' not in request.headers:
            response = returnJson_422()
            process_time = time.time() - start_time
            response.headers["X-Process-Time"] = str(process_time)
            response.headers['Access-Control-Allow-Origin'] = '*'
            return response
        
        # Validate POST request size
        if request.method == 'POST':
            content_length = request.headers.get('content-length')
            if content_length and int(content_length) > self.MAX_CONTENT_LENGTH:
                response = returnJson_413()
                process_time = time.time() - start_time
                response.headers["X-Process-Time"] = str(process_time)
                response.headers['Access-Control-Allow-Origin'] = '*'
                return response
        
        # Extract IP address for activity logging
        ip_address = self._get_client_ip(request)
        
        # Extract user agent for activity logging
        user_agent = request.headers.get('user-agent')
        
        # Set activity logging context
        set_request_context(ip_address=ip_address, user_agent=user_agent)
        
        try:
            # Process request
            response = await call_next(request)
            
            # Calculate process time
            process_time = time.time() - start_time
            response.headers["X-Process-Time"] = str(process_time)
            
            # Prepare logging data
            data = {
                'path': request.url.path,
                'host': request.url.hostname,
                'query': str(request.query_params),
                'method': request.method,
                'cl': request.headers.get('content-length'),
                'ua': user_agent,
                'status': response.status_code,
                'time': process_time,
                'ip': ip_address if ip_address else 'localhost'
            }
            
            # Log request in background
            background_task = BackgroundTasks()
            background_task.add_task(logger, data, 'auth', 'access')
            
            # Merge with existing background tasks if any
            if hasattr(response, 'background'):
                if response.background:
                    # Add our task to existing background
                    response.background.add_task(logger, data, 'auth', 'access')
                else:
                    response.background = background_task
            else:
                response.background = background_task
            
            return response
            
        finally:
            # Clean up activity logging context
            clear_request_context()
    
    def _get_client_ip(self, request: Request) -> str:
        """
        Extract client IP address from request.
        
        Args:
            request: HTTP request
            
        Returns:
            Client IP address
        """
        # Check for X-Forwarded-For header (proxy/load balancer)
        try:
            forwarded_for = request.headers.get('x-forwarded-for')
            if forwarded_for:
                return forwarded_for.split(',')[0].strip()
        except Exception:
            pass
        
        # Check for X-Real-IP header
        real_ip = request.headers.get('x-real-ip')
        if real_ip:
            return real_ip
        
        # Fall back to direct client
        if request.client:
            return request.client.host
        
        return 'localhost'
