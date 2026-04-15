from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.core.config import settings
from app.core.security import decode_token
from app.schemas.user import UserRecord
from app.services import user as user_service

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")


def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> UserRecord:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    subject = decode_token(token)
    if not subject:
        raise credentials_exc
    user = user_service.get_by_id(int(subject))
    if not user:
        raise credentials_exc
    return user


CurrentUser = Annotated[UserRecord, Depends(get_current_user)]
