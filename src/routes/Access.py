import secrets
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Depends

from src.Util.Cypher import cypher_x_encode, cypher_x_decode
from src.Util.Models import UserLogin
from src.Util.Seccurity import middleware_user_token_validation
from src.Util.db import db_register

router = APIRouter()


@router.head("", status_code=204)
async def access(user: Annotated[UserLogin, Depends(middleware_user_token_validation)]):
    """
    ## Session token verification
    Verifies if the session token exists and if its is a valid token, also the permissions of the user for
    the resource requested.

    Each part has 256 bits with a total of 768 => Token with length of 128 encoded with base64.
    """

    print(user.user_hash)
