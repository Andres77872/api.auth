import secrets

from fastapi import APIRouter, Form, HTTPException

from src.Util.Cypher import cypher_x_encode
from src.Util.Seccurity import make_session, x_random_key, x_check_sum, x_params_keys
from src.Util.db import db_login, db_register, db_username_or_email_available

router = APIRouter()


@router.post("/login")
async def login(user: str = Form(),
                password: str = Form(),
                collection: str = Form(),
                ):
    """
    ## Login method and create a new session token
    The token consist in three parts _[**Public KEY**, **HASH integrity**, **Encrypted SessionID**]_.

    Each part has 256 bits with a total of 768 => Token with length of 128 encoded with base64.
    """
    user_model = db_login(user, password, collection)

    if user_model:
        session_id = secrets.randbits(256)
        token, _ = cypher_x_encode(
            random_key=x_random_key,
            check_sum=x_check_sum,
            padding=None,
            params_keys=x_params_keys,
            params_data=[session_id]
        )
        if make_session(user_model, session_id):
            return {
                'session-token': token
            }
        else:
            raise HTTPException(status_code=500, detail='Fail to start the user session')
    else:
        raise HTTPException(status_code=401, detail='user or password are incorrect or not exist')


@router.post("/register")
async def register(user: str = Form(),
                   password: str = Form(),
                   collections: str = Form(),
                   email: str = Form(None),
                   ):
    """
    ## Create a new user and start a new session with the token returned
    The token consist in three parts _[**Public KEY**, **HASH integrity**, **Encrypted SessionID**]_.

    Each part has 256 bits with a total of 768 => Token with length of 128 encoded with base64.

    The password will take without alteration and this will be hashed to be stored in the DB,
    and it is recommended that the password come hashed to avoid sending the raw password to the API.
    This hash must be on the client side.

    By default, each token will be set with expiration of 72 hrs.

    """
    user_model = db_register(collection=collections,
                             password=password,
                             email=email,
                             user=user)

    if user_model:
        session_id = secrets.randbits(256)

        token, _ = cypher_x_encode(
            random_key=x_random_key,
            check_sum=x_check_sum,
            padding=None,
            params_keys=x_params_keys,
            params_data=[session_id]
        )
        if make_session(user_model, session_id):
            return {
                'token': token,
                'user_hash': user_model.user_hash,
                'user_id': user_model.user_id
            }
        else:
            raise HTTPException(status_code=500, detail='Fail to start the user session')
    raise HTTPException(status_code=409, detail='User already exist')


@router.post("/check", status_code=204)
async def username_or_email_exist(username_or_email: str = Form(),
                                  collection: str = Form(),
                                  ):
    """
    Check the availability of the user or email.

    204 -> user not exist
    409 -> user exists

    """
    if not db_username_or_email_available(username_or_email=username_or_email,
                                          collection=collection):
        raise HTTPException(status_code=409, detail='exist')
