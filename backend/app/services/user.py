from datetime import datetime, timezone

from app.core import storage
from app.core.security import hash_password, verify_password
from app.schemas.user import UserCreate, UserRecord, UserRole


def _to_record(d: dict) -> UserRecord:
    return UserRecord.model_validate(d)


def get_by_id(user_id: int) -> UserRecord | None:
    for u in storage.load_users():
        if u["id"] == user_id:
            return _to_record(u)
    return None


def get_by_username(username: str) -> UserRecord | None:
    for u in storage.load_users():
        if u["username"].lower() == username.lower():
            return _to_record(u)
    return None


def create(data: UserCreate, role: UserRole = UserRole.annotator) -> UserRecord:
    users = storage.load_users()
    uid = storage.next_id("users")
    record = {
        "id": uid,
        "username": data.username,
        "hashed_password": hash_password(data.password),
        "role": role.value,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    users.append(record)
    storage.save_users(users)
    return _to_record(record)


def authenticate(username: str, password: str) -> UserRecord | None:
    user = get_by_username(username)
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


def ensure_seed_user(
    username: str, password: str, role: UserRole = UserRole.annotator
) -> bool:
    """Create the default user if it doesn't exist yet. Returns True if created."""
    if get_by_username(username):
        return False
    create(UserCreate(username=username, password=password), role=role)
    return True


def upsert_seed_user(
    username: str, password: str, role: UserRole = UserRole.annotator
) -> str:
    """Create or reconcile a user against seed_users.json.

    Returns one of: 'created', 'updated', 'unchanged'.
    Updates password/role in place when they differ from the seed file, so the
    JSON is always authoritative.
    """
    users = storage.load_users()
    for u in users:
        if u["username"].lower() != username.lower():
            continue
        changed = False
        if not verify_password(password, u["hashed_password"]):
            u["hashed_password"] = hash_password(password)
            changed = True
        if u.get("role") != role.value:
            u["role"] = role.value
            changed = True
        if changed:
            storage.save_users(users)
            return "updated"
        return "unchanged"
    create(UserCreate(username=username, password=password), role=role)
    return "created"
