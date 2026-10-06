"""Bearer and cookie transports for access and refresh credentials."""
from fastapi import HTTPException, Request
from fastapi.security import HTTPBearer
from fastapi.security.http import HTTPAuthorizationCredentials
from src.Util.auth_constants import ACCESS_COOKIE_NAME, REFRESH_COOKIE_NAME


class HTTPBearerOrCookie(HTTPBearer):
    """
    Custom HTTPBearer that accepts tokens from both Authorization header and cookies.
    """

    def __init__(self, bearerFormat: str = None, scheme_name: str = None, description: str = None,
                 auto_error: bool = True):
        super().__init__(bearerFormat=bearerFormat, scheme_name=scheme_name, description=description,
                         auto_error=auto_error)

    async def __call__(self, request: Request) -> HTTPAuthorizationCredentials:
        token = extract_jwt_token_from_request(request)
        if token:
            return HTTPAuthorizationCredentials(scheme='Bearer', credentials=token)
        if self.auto_error:
            raise HTTPException(status_code=401, detail='Not authenticated', headers={'WWW-Authenticate': 'Bearer'})
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
    cookie_token = request.cookies.get(ACCESS_COOKIE_NAME)
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


