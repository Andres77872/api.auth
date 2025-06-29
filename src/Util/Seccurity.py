import json

from fastapi import HTTPException, Request
from fastapi.security import APIKeyHeader
from starlette.responses import JSONResponse

from src.Util.Models import UserLogin
from src.Util.db.db_enhanced import validate_session
from src.Util.db_config import redis_client as client
from src.Util.cache_manager import cache_manager

x_token_user_name = 'X-token-user'
x_token_collection_name = 'X-token-collection'

x_token_user = APIKeyHeader(name=x_token_user_name, auto_error=True, scheme_name=x_token_user_name)
x_token_collection = APIKeyHeader(name=x_token_collection_name, auto_error=True, scheme_name=x_token_collection_name)


def middleware_user_token_validation(request: Request) -> UserLogin:
    """
    Enhanced token validation method with cache-first approach.
    Validates session tokens and returns user information with project context.
    
    :param request: Request containing authentication headers
    :return: UserLogin model with session data
    """
    if x_token_user_name in request.headers and x_token_collection_name in request.headers:
        try:
            user_token = request.headers[x_token_user_name]
            collection_token = request.headers[x_token_collection_name]
            
            # Validate session token using enhanced system (cache-first)
            enhanced_user = validate_session(user_token)
            
            if enhanced_user and enhanced_user.project_hash == collection_token:
                # Convert to legacy UserLogin format for compatibility
                return UserLogin(
                    user_session=enhanced_user.session_token,
                    user_session_length=enhanced_user.session_length,
                    user_hash=enhanced_user.user_hash,
                    user_collection=enhanced_user.project_hash,
                    user_id=enhanced_user.user_id,
                    project_id=enhanced_user.project_id,
                    user_project_id=enhanced_user.user_project_id,
                    groups=enhanced_user.groups
                )
            else:
                raise HTTPException(status_code=401, detail='Invalid token or project access denied')
            
        except HTTPException:
            # Re-raise HTTP exceptions (they already have proper error messages)
            raise
        except Exception as e:
            print(f"Token validation error: {e}")
            raise HTTPException(status_code=401, detail='User token invalid')
    else:
        raise HTTPException(status_code=401, detail='Authentication headers missing')


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
