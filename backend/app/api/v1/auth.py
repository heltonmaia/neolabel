from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.deps import CurrentUser
from app.core.ratelimit import limiter
from app.core.security import create_access_token
from app.schemas.user import GoogleLogin, Token, UserRead, UserRole
from app.services import allowlist as allowlist_service
from app.services import google_auth
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


@router.post("/google", response_model=Token)
@limiter.limit("5/minute")
def google_login(request: Request, body: GoogleLogin) -> Token:
    try:
        idinfo = google_auth.verify_google_id_token(body.credential)
    except ValueError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid Google credential",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not idinfo.get("email_verified"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Google e-mail is not verified")
    email = (idinfo.get("email") or "").lower()
    entry = allowlist_service.lookup(email)
    if not entry:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized")
    role = UserRole(entry.get("role", "annotator"))
    user = user_service.get_or_provision_google_user(
        email=email,
        name=idinfo.get("name"),
        google_sub=idinfo.get("sub"),
        role=role,
    )
    return Token(access_token=create_access_token(str(user.id)))


@router.get("/me", response_model=UserRead)
def me(current_user: CurrentUser) -> UserRead:
    return UserRead.model_validate(current_user.model_dump())
