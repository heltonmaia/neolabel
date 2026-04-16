from fastapi import APIRouter

from app.core import storage
from app.core.deps import AdminUser
from app.schemas.user import UserRead

router = APIRouter()


@router.get("", response_model=list[UserRead])
def list_users(current_user: AdminUser) -> list[UserRead]:
    return [UserRead.model_validate(u) for u in storage.load_users()]
