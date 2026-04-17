from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.deps import CurrentUser
from app.core.ratelimit import limiter
from app.core.security import create_access_token
from app.schemas.user import Token, UserRead
from app.services import user as user_service

router = APIRouter()


@router.post("/login", response_model=Token)
@limiter.limit("5/minute")
def login(request: Request, form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> Token:
    user = user_service.authenticate(form.username, form.password)
    if not user:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_access_token(str(user.id)))


@router.get("/me", response_model=UserRead)
def me(current_user: CurrentUser) -> UserRead:
    return UserRead.model_validate(current_user.model_dump())
