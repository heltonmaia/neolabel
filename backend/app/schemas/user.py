import enum
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserRole(str, enum.Enum):
    admin = "admin"
    annotator = "annotator"
    reviewer = "reviewer"


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=4, max_length=128)


class UserRecord(BaseModel):
    """Full user record as stored on disk (may include a password hash)."""

    id: int
    username: str
    email: str | None = None
    google_sub: str | None = None
    hashed_password: str | None = None
    role: UserRole = UserRole.annotator
    created_at: datetime


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None = None
    role: UserRole
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class GoogleLogin(BaseModel):
    credential: str
