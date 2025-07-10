from typing import Annotated

from fastapi import APIRouter, Depends, Response

from src.Util.Models import UserLogin
from src.Util.Seccurity import middleware_user_token_validation

router = APIRouter()


@router.head("", status_code=204)
async def access(response: Response,
                 user: Annotated[UserLogin, Depends(middleware_user_token_validation)]):
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
    response.headers['X_user_HASH'] = user.user_hash
