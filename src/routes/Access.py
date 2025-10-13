from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.security import HTTPAuthorizationCredentials

from src.Util.Models import UserLogin
from src.Util.Seccurity import middleware_user_token_validation, HTTPBearerOrCookie
from src.Util.decorators import log_and_handle_errors
from src.Util.log_context_models import LogContext
from src.Util.activity_logger import ActivityType

router = APIRouter()
security = HTTPBearerOrCookie()


@router.head("", status_code=204)
@log_and_handle_errors(
    operation_name="verify_access",
    activity_type=ActivityType.USER_LOGIN,
    log_success=False
)
async def access(
    response: Response,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None
):
    """
    ## JWT Session token verification
    Verifies if the JWT session token exists and if it is valid, including checking the permissions 
    of the user for the resource requested.

    JWT tokens are industry-standard, cryptographically secure tokens that contain:
    - session_id: Unique session identifier
    - user_hash: User identification hash  
    - collection: Collection identifier
    - exp: Expiration timestamp
    - iat: Issued at timestamp
    - type: Token type
    """
    response.headers['X_user_HASH'] = log_context.user_hash
