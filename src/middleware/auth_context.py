"""
Authentication Context Middleware

Sets user context on request.state for downstream middleware (like audit logging).
This middleware tries to extract auth info without enforcing it.
"""

import logging
from typing import Callable, Optional
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger(__name__)


class AuthContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware to set authentication context on request.state.
    
    This middleware attempts to extract user information from the Authorization
    header and populate request.state with user context. It does NOT enforce
    authentication - that's handled by the dependency injection in routes.
    
    This allows other middleware (like audit logging) to access user context
    even before the route handler is called.
    
    Usage:
        app = FastAPI()
        app.add_middleware(AuthContextMiddleware)
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Extract auth context and set on request.state.
        
        Args:
            request: Incoming HTTP request
            call_next: Next middleware/endpoint in chain
            
        Returns:
            Response from endpoint
        """
        # Try to extract user context from Authorization header
        auth_header = request.headers.get("authorization")
        
        if auth_header and auth_header.startswith("Bearer "):
            session_token = auth_header.replace("Bearer ", "")
            
            try:
                # Validate session and get user info
                from src.Util.db import validate_session
                session_data = validate_session(session_token)
                
                if session_data:
                    # Create user object on request.state
                    class UserContext:
                        def __init__(self, session_data):
                            self.id = session_data.user_id
                            self.user_hash = session_data.user_hash
                            self.user_type = session_data.user_type
                            self.username = getattr(session_data, 'username', None)
                            self.permissions = session_data.permissions
                            self.groups = session_data.groups
                    
                    request.state.user = UserContext(session_data)
                    request.state.session_id = session_token
                    request.state.project_id = session_data.project_id
                    request.state.project_hash = session_data.project_hash
                    
            except Exception as e:
                # Don't fail the request, just log the error
                logger.debug(f"Could not extract auth context: {e}")
        
        # Process request
        response = await call_next(request)
        
        return response
