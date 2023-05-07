import json

from fastapi import HTTPException, Request
from fastapi.security import APIKeyHeader
from starlette.responses import JSONResponse

from src.Util.Cypher import cypher_x_decode
from src.Util.Models import UserLogin
from src.Util.db import set_session, get_session, db_validate_session

x_token_user_name = 'X-token-user'
x_token_collection_name = 'X-token-collection'

x_token_user = APIKeyHeader(name=x_token_user_name, auto_error=True, scheme_name=x_token_user_name)
x_token_collection = APIKeyHeader(name=x_token_collection_name, auto_error=True, scheme_name=x_token_collection_name)

x_random_key = 256
x_check_sum = 256
# [SessionKEY]
x_params_keys = [256]


def middleware_user_token_validation(request: Request) -> UserLogin:
    """
    This method will return the user id, this will raise an exception if the token is invalid
    or not exist
    :param request: Request
    :return: Int with the user id
    """
    if x_token_user_name in request.headers and x_token_collection_name in request.headers:
        try:
            user, _ = cypher_x_decode(
                random_key=x_random_key,
                check_sum=x_check_sum,
                params_keys=x_params_keys,
                encoded=request.headers[x_token_user_name],
                padding=None
            )

            user_model = get_session(user[0])
            # print(user[0])
            if (user_model and  # Session exists
                    # Session expected == session Actual
                    request.headers[x_token_collection_name] == user_model.user_collection and
                    # Session actual == User session
                    db_validate_session(user_session=user_model.user_session, user_hash=user_model.user_hash)):
                return user_model
            raise HTTPException(status_code=401, detail='User token invalid')
        except Exception as e:
            print(e)
            raise HTTPException(status_code=401, detail='User token invalid')
    else:
        raise HTTPException(status_code=401, detail='User token invalid')


def make_session(user_model: UserLogin, session_id: int) -> bool:
    try:
        session_state = {
            'user_session_length': user_model.user_session_length,
            'user_hash': user_model.user_hash,
            'user_session': user_model.user_session,
            'user_collection': user_model.user_collection
        }

        return set_session(key=session_id,
                           value=json.dumps(session_state),
                           ex=user_model.user_session_length,
                           user_hash=user_model.user_hash)
    except Exception as e:
        print(e)
        return False


def returnJson_401(data=None):
    if data is None:
        data = {'status': 'Error', 'action': 'Access forbidden, access token required or token invalid'}
    return JSONResponse(content=data, media_type="application/json", status_code=401)


def returnJson_403(data=None):
    if data is None:
        data = {'status': 'Error', 'action': 'Access forbidden, access token required or token invalid'}
    return JSONResponse(content=data, media_type="application/json", status_code=403)


def returnJson_404(data=None):
    if data is None:
        data = {'status': 'Error', 'action': 'Resource not found'}
    return JSONResponse(content=data, media_type="application/json", status_code=403)


def returnJson_413(data=None):
    if data is None:
        data = {'status': 'Error', 'action': 'Max sie 8 mib'}
    return JSONResponse(content=data, media_type="application/json", status_code=413)


def returnJson_422(data=None):
    if data is None:
        data = {'status': 'Error', 'action': 'header user-agent not found'}
    return JSONResponse(content=data, media_type="application/json", status_code=422)


def returnJson_500(data=None):
    if data is None:
        data = {'status': 'Error', 'action': 'Internal error'}
    return JSONResponse(content=data, media_type="application/json", status_code=500)


def returnJson_200(data=None):
    if data is None:
        data = {'status': 'OK', 'action': 'Action successfull'}
    return JSONResponse(content=data, media_type="application/json", status_code=200)
