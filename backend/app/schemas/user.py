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
    """Full user record as stored on disk (includes hash)."""

    id: int
    username: str
    hashed_password: str
    role: UserRole = UserRole.annotator
    created_at: datetime


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: UserRole
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
