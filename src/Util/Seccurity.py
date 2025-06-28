import json

from fastapi import HTTPException, Request
from fastapi.security import APIKeyHeader
from starlette.responses import JSONResponse

from src.Util.JWT_Security import JWTTokenHandler, jwt_decode
from src.Util.Models import UserLogin
from src.Util.db import set_session, get_session, db_validate_session

x_token_user_name = 'X-token-user'
x_token_collection_name = 'X-token-collection'

x_token_user = APIKeyHeader(name=x_token_user_name, auto_error=True, scheme_name=x_token_user_name)
x_token_collection = APIKeyHeader(name=x_token_collection_name, auto_error=True, scheme_name=x_token_collection_name)

# Legacy parameters - kept for compatibility but not used with JWT
x_random_key = 256
x_check_sum = 256
x_params_keys = [256]


def middleware_user_token_validation(request: Request) -> UserLogin:
    """
    JWT-based token validation method that replaces the custom cipher validation.
    This method will return the user session data, raising an exception if the token is invalid.
    
    :param request: Request
    :return: UserLogin model with session data
    """
    if x_token_user_name in request.headers and x_token_collection_name in request.headers:
        try:
            # Decode JWT token to get session ID
            user_token = request.headers[x_token_user_name]
            collection_token = request.headers[x_token_collection_name]
            
            # Decode JWT token using our new JWT handler
            payload = JWTTokenHandler.decode_access_token(user_token)
            session_id = payload.get("session_id")
            token_user_hash = payload.get("user_hash")
            token_collection = payload.get("collection")
            
            # Validate collection matches
            if collection_token != token_collection:
                raise HTTPException(status_code=401, detail='Collection token mismatch')
            
            # Get session data from storage
            user_model = get_session(session_id)
            
            if (user_model and  # Session exists
                    # Collection validation
                    collection_token == user_model.user_collection and
                    # User hash validation
                    token_user_hash == user_model.user_hash and
                    # Session validation in database
                    db_validate_session(user_session=user_model.user_session, user_hash=user_model.user_hash)):
                return user_model
            raise HTTPException(status_code=401, detail='User token invalid')
            
        except HTTPException:
            # Re-raise HTTP exceptions (they already have proper error messages)
            raise
        except Exception as e:
            print(f"Token validation error: {e}")
            raise HTTPException(status_code=401, detail='User token invalid')
    else:
        raise HTTPException(status_code=401, detail='User token invalid')


def make_session(user_model: UserLogin, session_id: int) -> bool:
    """
    Create a session in both database and cache.
    No changes needed here as it handles session storage, not token generation.
    """
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
