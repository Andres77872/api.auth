from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Depends

from src.Util.Models import UserLogin
from src.Util.Seccurity import middleware_user_token_validation

router = APIRouter()


@router.delete("")
async def delete(user: Annotated[UserLogin, Depends(middleware_user_token_validation)]):
    raise HTTPException(status_code=501, detail='Not implemented yet')


@router.patch("")
async def update_by_user(user: Annotated[UserLogin, Depends(middleware_user_token_validation)]):
    raise HTTPException(status_code=501, detail='Not implemented yet')


@router.put("")
async def update_by_admin(user: Annotated[UserLogin, Depends(middleware_user_token_validation)]):
    raise HTTPException(status_code=501, detail='Not implemented yet')


