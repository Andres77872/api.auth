import json

from fastapi import HTTPException, Request
from fastapi.security import APIKeyHeader, HTTPBearer
from fastapi.security.http import HTTPAuthorizationCredentials
from starlette.responses import JSONResponse

from src.Util.Models import UserLogin
from src.Util.auth_constants import ACCESS_COOKIE_NAME, REFRESH_COOKIE_NAME, PLATFORM_COLLECTION_SENTINEL
from src.Util.db.db_enhanced import validate_session
from src.Util.db_config import redis_client as client

# Legacy header names for backwards compatibility
x_token_user_name = 'X-token-user'
x_token_collection_name = 'X-token-collection'

x_token_user = APIKeyHeader(name=x_token_user_name, auto_error=True, scheme_name=x_token_user_name)
x_token_collection = APIKeyHeader(name=x_token_collection_name, auto_error=True, scheme_name=x_token_collection_name)

# JWT token constants (legacy exported names kept for tests/imports)
JWT_COOKIE_NAME = ACCESS_COOKIE_NAME
REFRESH_JWT_COOKIE_NAME = REFRESH_COOKIE_NAME


class HTTPBearerOrCookie(HTTPBearer):
    """
    Custom HTTPBearer that accepts tokens from both Authorization header and cookies.
    """

    def __init__(self, bearerFormat: str = None, scheme_name: str = None, description: str = None,
                 auto_error: bool = True):
        super().__init__(bearerFormat=bearerFormat, scheme_name=scheme_name, description=description,
                         auto_error=auto_error)

    async def __call__(self, request: Request) -> HTTPAuthorizationCredentials:
        # First, try the standard Authorization header
        try:
            authorization = request.headers.get("Authorization")
            if authorization and authorization.startswith("Bearer "):
                token = authorization.split(" ")[1]
                return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        except:
            pass

        # Then, try cookie
        cookie_token = request.cookies.get(JWT_COOKIE_NAME)
        if cookie_token:
            return HTTPAuthorizationCredentials(scheme="Bearer", credentials=cookie_token)

        # If auto_error is True and no token found, raise exception
        if self.auto_error:
            raise HTTPException(
                status_code=401,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        else:
            return None


def extract_jwt_token_from_request(request: Request) -> str:
    """
    Extract JWT token from request, checking both Authorization header and cookies.
    
    :param request: FastAPI request object
    :return: JWT token string or None
    """
    # First, try Authorization header (Bearer token)
    authorization = request.headers.get("Authorization")
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]  # split on first space only
        if token:  # Reject empty tokens (e.g., "Bearer " with nothing after)
            return token

    # Then, try cookie
    cookie_token = request.cookies.get(JWT_COOKIE_NAME)
    if cookie_token:
        return cookie_token

    return None


def extract_refresh_token_from_request(request: Request, explicit_refresh_token: str = None) -> str:
    """
    Extract a refresh token from the documented refresh transport only.

    Refresh credentials are accepted from the ``refresh_token`` HttpOnly cookie
    and/or an explicit body/form value supplied by the route. Authorization
    bearer tokens are intentionally ignored for refresh so access tokens cannot
    renew themselves.
    """
    cookie_token = request.cookies.get(REFRESH_COOKIE_NAME)
    body_token = explicit_refresh_token or None

    if cookie_token and body_token and cookie_token != body_token:
        raise HTTPException(
            status_code=401,
            detail="Mismatched refresh token transports",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = cookie_token or body_token
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing refresh token: provide refresh_token cookie or body field",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token


def middleware_user_token_validation(request: Request) -> UserLogin:
    """
    Enhanced token validation method with JWT support from both headers and cookies.
    Validates session tokens and returns user information with project context.
    Supports global root sessions without project context.
    
    :param request: Request containing authentication headers or cookies
    :return: UserLogin model with session data
    """
    # Try to get JWT token from Authorization header or cookie
    jwt_token = extract_jwt_token_from_request(request)

    if jwt_token:
        try:
            # Validate JWT session token using enhanced system (cache-first)
            enhanced_user = validate_session(jwt_token)

            if enhanced_user:
                if enhanced_user.scope == 'platform':
                    return UserLogin(
                        user_session=enhanced_user.session_token,
                        user_session_length=enhanced_user.session_length,
                        user_hash=enhanced_user.user_hash,
                        user_collection=PLATFORM_COLLECTION_SENTINEL,
                        user_id=enhanced_user.user_id,
                        project_id=enhanced_user.project_id,
                        user_project_id=enhanced_user.user_project_id,
                        groups=enhanced_user.groups,
                        user_type=enhanced_user.user_type,
                        assigned_project_id=enhanced_user.assigned_project_id
                    )

                # For project-based sessions, validate project access
                project_hash = enhanced_user.project_hash
                if project_hash:
                    # Convert to legacy UserLogin format for compatibility
                    return UserLogin(
                        user_session=enhanced_user.session_token,
                        user_session_length=enhanced_user.session_length,
                        user_hash=enhanced_user.user_hash,
                        user_collection=enhanced_user.project_hash,
                        user_id=enhanced_user.user_id,
                        project_id=enhanced_user.project_id,
                        user_project_id=enhanced_user.user_project_id,
                        groups=enhanced_user.groups,
                        user_type=enhanced_user.user_type,
                        assigned_project_id=enhanced_user.assigned_project_id
                    )
                else:
                    raise HTTPException(status_code=401, detail='Invalid session or project access denied')
            else:
                raise HTTPException(status_code=401, detail='Invalid session token')

        except HTTPException:
            # Re-raise HTTP exceptions (they already have proper error messages)
            raise
        except Exception as e:
            print(f"JWT token validation error: {e}")
            raise HTTPException(status_code=401, detail='User token invalid')

    # Legacy fallback: check for old header-based authentication
    if x_token_user_name in request.headers and x_token_collection_name in request.headers:
        try:
            user_token = request.headers[x_token_user_name]
            collection_token = request.headers[x_token_collection_name]

            # Validate session token using enhanced system (cache-first)
            enhanced_user = validate_session(user_token)

            if enhanced_user:
                if enhanced_user.scope == 'platform':
                    if collection_token != PLATFORM_COLLECTION_SENTINEL:
                        raise HTTPException(status_code=401, detail='Invalid token or platform access denied')

                    return UserLogin(
                        user_session=enhanced_user.session_token,
                        user_session_length=enhanced_user.session_length,
                        user_hash=enhanced_user.user_hash,
                        user_collection=PLATFORM_COLLECTION_SENTINEL,
                        user_id=enhanced_user.user_id,
                        project_id=enhanced_user.project_id,
                        user_project_id=enhanced_user.user_project_id,
                        groups=enhanced_user.groups,
                        user_type=enhanced_user.user_type,
                        assigned_project_id=enhanced_user.assigned_project_id
                    )

                # For project-based sessions, validate project access
                if enhanced_user.project_hash == collection_token:
                    # Convert to legacy UserLogin format for compatibility
                    return UserLogin(
                        user_session=enhanced_user.session_token,
                        user_session_length=enhanced_user.session_length,
                        user_hash=enhanced_user.user_hash,
                        user_collection=enhanced_user.project_hash,
                        user_id=enhanced_user.user_id,
                        project_id=enhanced_user.project_id,
                        user_project_id=enhanced_user.user_project_id,
                        groups=enhanced_user.groups,
                        user_type=enhanced_user.user_type,
                        assigned_project_id=enhanced_user.assigned_project_id
                    )
                else:
                    raise HTTPException(status_code=401, detail='Invalid token or project access denied')
            else:
                raise HTTPException(status_code=401, detail='Invalid session token')

        except HTTPException:
            # Re-raise HTTP exceptions (they already have proper error messages)
            raise
        except Exception as e:
            print(f"Token validation error: {e}")
            raise HTTPException(status_code=401, detail='User token invalid')

    # No authentication found
    raise HTTPException(status_code=401, detail='Authentication required')


def make_session(user_model: UserLogin, session_id: int) -> bool:
    """
    Create a session in Redis cache for compatibility.
    Enhanced system uses its own session management, but this maintains compatibility.
    """
    try:
        session_state = {
            'user_session_length': user_model.user_session_length,
            'user_hash': user_model.user_hash,
            'user_session': user_model.user_session,
            'user_collection': user_model.user_collection
        }

        # Store in Redis using hex key format for compatibility
        client.set(hex(session_id)[2:],
                   json.dumps(session_state),
                   ex=user_model.user_session_length)
        return True

    except Exception as e:
        print(f"Session creation error: {e}")
        return False


def returnJson_401(data=None):
    """Return 401 Unauthorized response"""
    if data is None:
        data = {'status': 'Error', 'action': 'Access forbidden, access token required or token invalid'}
    return JSONResponse(content=data, media_type="application/json", status_code=401)


def returnJson_403(data=None):
    """Return 403 Forbidden response"""
    if data is None:
        data = {'status': 'Error', 'action': 'Access forbidden, insufficient permissions'}
    return JSONResponse(content=data, media_type="application/json", status_code=403)


def returnJson_404(data=None):
    """Return 404 Not Found response"""
    if data is None:
        data = {'status': 'Error', 'action': 'Resource not found'}
    return JSONResponse(content=data, media_type="application/json", status_code=404)


def returnJson_413(data=None):
    """Return 413 Payload Too Large response"""
    if data is None:
        data = {'status': 'Error', 'action': 'Payload too large (max 8 MiB)'}
    return JSONResponse(content=data, media_type="application/json", status_code=413)


def returnJson_422(data=None):
    """Return 422 Unprocessable Entity response"""
    if data is None:
        data = {'status': 'Error', 'action': 'User-Agent header not found'}
    return JSONResponse(content=data, media_type="application/json", status_code=422)


def returnJson_500(data=None):
    """Return 500 Internal Server Error response"""
    if data is None:
        data = {'status': 'Error', 'action': 'Internal server error'}
    return JSONResponse(content=data, media_type="application/json", status_code=500)


def returnJson_200(data=None):
    """Return 200 OK response"""
    if data is None:
        data = {'status': 'OK', 'action': 'Action successful'}
    return JSONResponse(content=data, media_type="application/json", status_code=200)
