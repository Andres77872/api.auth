"""
Authentication Context Middleware

Sets user context on request.state for downstream middleware (like audit logging).
This middleware tries to extract auth info without enforcing it.

Supports dual authentication paths:
- X-API-Key header → API key authentication (checked first)
- Authorization: Bearer → JWT session authentication (fallback)
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

    This middleware attempts to extract user information from either:
    1. X-API-Key header (API key authentication — checked first)
    2. Authorization: Bearer header (JWT session authentication — fallback)

    It populates request.state with user context. It does NOT enforce
    authentication — that's handled by the dependency injection in routes.

    This allows other middleware (like audit logging) to access user context
    even before the route handler is called.

    Both auth paths populate request.state with identical shape:
    - request.state.user (UserContext)
    - request.state.session_id (JWT token or API key ID)
    - request.state.project_id
    - request.state.project_hash
    - request.state.auth_method ("api_key" or "session")

    Usage:
        app = FastAPI()
        app.add_middleware(AuthContextMiddleware)
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Extract auth context and set on request.state.

        Checks X-API-Key header first. If present, validates via API key logic.
        If absent or invalid, falls back to existing Bearer token flow.
        Always sets request.state.auth_method.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/endpoint in chain

        Returns:
            Response from endpoint
        """
        # --- Path 1: API Key Authentication (X-API-Key header) ---
        api_key_header = request.headers.get("x-api-key")

        if api_key_header and request.url.path not in {"/auth/validate", "/auth/validate-api-key"}:
            try:
                auth_context = self._extract_api_key_context(api_key_header)
                if auth_context:
                    request.state.user = auth_context["user"]
                    request.state.session_id = auth_context["session_id"]
                    request.state.project_id = auth_context["project_id"]
                    request.state.project_hash = auth_context["project_hash"]
                    request.state.auth_method = "api_key"
                    # Process request with API key context set
                    response = await call_next(request)
                    return response
            except Exception as e:
                # Don't fail the request, just log and fall through to Bearer
                logger.debug(f"API key context extraction failed: {e}")

        # --- Path 2: Access-token authentication (Bearer/session_token cookie) ---
        from src.Util.Seccurity import extract_jwt_token_from_request

        session_token = extract_jwt_token_from_request(request)

        if session_token and session_token.count(".") == 2:

            try:
                # Validate access-session and get user info. Wrong token types,
                # revoked families, and inactive users simply leave request.state
                # unauthenticated; route dependencies still enforce auth.
                from src.Util.db.db_enhanced import validate_session
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
                    request.state.user_id = session_data.user_id
                    request.state.session_id = session_token
                    request.state.project_id = session_data.project_id
                    request.state.project_hash = session_data.project_hash
                    request.state.auth_method = "session"
                    # Phase 2.2a: Store full validate_session result for decorator reuse
                    request.state.session_validation = session_data

            except Exception as e:
                # Don't fail the request, just log the error
                logger.debug(f"Could not extract auth context: {e}")

        # Default: no auth context found — set auth_method to session for backward compat
        if not hasattr(request.state, 'auth_method'):
            request.state.auth_method = "session"

        # Process request
        response = await call_next(request)

        return response

    def _extract_api_key_context(self, api_key: str) -> Optional[dict]:
        """
        Extract user context from an API key token (non-blocking).

        This mirrors the verify_api_key dependency logic but is designed
        for middleware use — it returns None on failure rather than raising.

        Args:
            api_key: The full token from X-API-Key header

        Returns:
            Dict with user, session_id, project_id, project_hash — or None
        """
        try:
            # Parse token format: sk_{public_id}.{secret}
            if not api_key.startswith("sk_"):
                return None

            token_body = api_key[3:]  # Remove "sk_" prefix
            public_id = token_body.rsplit(".", 1)[0]
        except (ValueError, IndexError):
            return None

        # Check Redis cache first
        from src.Util.cache_manager import cache_manager
        cached = cache_manager.get_api_key(public_id)
        if cached and cached.get("validation_status") == "valid":
            return self._build_api_key_context_from_cache(cached)

        # Cache miss — validate via stored procedure
        from src.Util.db.db_api_keys import validate_api_key_lookup
        key_data = validate_api_key_lookup(public_id)
        if not key_data or key_data.get("validation_status") != "valid":
            return None

        # Perform constant-time hash comparison
        from src.Util.api_key_security import verify_api_key_token
        stored_hash = key_data.get("secret_hash")
        if not stored_hash:
            return None

        if not verify_api_key_token(api_key, public_id, stored_hash):
            return None

        # Resolve user and project info
        owner_user_id = key_data["owner_user_id"]
        project_id = key_data["project_id"]

        from src.Util.db.db_projects import get_project_by_id
        project = get_project_by_id(project_id)
        if not project:
            return None

        from src.Util.db.db_users import get_user_by_id
        owner = get_user_by_id(owner_user_id)
        if not owner:
            return None

        # Resolve permissions (same logic as verify_api_key dependency)
        permissions, groups = self._resolve_api_key_permissions(
            owner, project, owner_user_id, project_id
        )

        # Build UserContext
        class UserContext:
            def __init__(self, owner, permissions, groups, project):
                self.id = owner.id
                self.user_hash = owner.user_hash
                self.user_type = owner.user_type
                self.username = owner.username
                self.permissions = permissions
                self.groups = groups
                self.project_id = project.id
                self.project_hash = project.project_hash

        user_ctx = UserContext(owner, permissions, groups, project)

        # Cache the result for subsequent requests
        from datetime import datetime, timezone
        cache_manager.set_api_key(public_id, {
            "validation_status": "valid",
            "user_id": owner_user_id,
            "user_hash": owner.user_hash,
            "user_type": owner.user_type,
            "username": owner.username,
            "project_id": project_id,
            "project_hash": project.project_hash,
            "permissions": permissions,
            "groups": groups,
            "key_id": key_data["id"],
            "cached_at": datetime.now(timezone.utc).isoformat(),
        })

        return {
            "user": user_ctx,
            "session_id": key_data["id"],
            "project_id": project_id,
            "project_hash": project.project_hash,
        }

    def _build_api_key_context_from_cache(self, cached: dict) -> Optional[dict]:
        """Build request.state context from cached API key validation data."""
        try:
            class UserContext:
                def __init__(self, data):
                    self.id = data["user_id"]
                    self.user_hash = data["user_hash"]
                    self.user_type = data["user_type"]
                    self.username = data.get("username")
                    self.permissions = data.get("permissions", [])
                    self.groups = data.get("groups", [])
                    self.project_id = data["project_id"]
                    self.project_hash = data["project_hash"]

            user_ctx = UserContext(cached)
            return {
                "user": user_ctx,
                "session_id": cached.get("key_id", ""),
                "project_id": cached["project_id"],
                "project_hash": cached["project_hash"],
            }
        except (KeyError, TypeError):
            return None

    def _resolve_api_key_permissions(self, owner, project, owner_user_id, project_id):
        """
        Resolve live permissions for an API key owner.

        Mirrors the permission resolution in validate_session:
        - root: full permissions
        - admin: check project access, return admin permissions
        - consumer: resolve via group chain

        Returns:
            Tuple of (permissions_list, groups_list)
        """
        permissions = []
        groups = []

        if owner.user_type == "root":
            permissions = ["admin", "global_admin"]
            groups = ["root_users"]
        elif owner.user_type == "admin":
            from src.Util.db import check_admin_project_access
            if not check_admin_project_access(owner_user_id, project_id):
                return ([], [])
            permissions = ["admin", "project_admin"]
            groups = ["project_admins"]
        else:
            # Consumer: resolve via group chain
            from src.Util.db.db_user_groups import get_user_groups_in_project_by_hash
            groups_objs = get_user_groups_in_project_by_hash(owner_user_id, project.project_hash)
            if not groups_objs:
                return ([], [])
            groups = [g.group_name for g in groups_objs]
            # Get permissions from global role system
            try:
                from src.Util.db.db_global_roles import get_user_permissions
                permissions = get_user_permissions(owner_user_id)
            except Exception as e:
                logger.warning(
                    f"Failed to resolve consumer permissions for user {owner_user_id}: {e}",
                    exc_info=True
                )
                permissions = []

        return permissions, groups
