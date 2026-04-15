from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.deps import CurrentUser
from app.core.security import create_access_token
from app.schemas.user import Token, UserCreate, UserRead
from app.services import user as user_service

router = APIRouter()


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(data: UserCreate) -> UserRead:
    if user_service.get_by_username(data.username):
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already taken")
    user = user_service.create(data)
    return UserRead.model_validate(user.model_dump())


@router.post("/login", response_model=Token)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> Token:
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
