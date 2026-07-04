from datetime import datetime, timezone

from app.core import storage
from app.core.config import settings
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


def _find_by_email(users: list[dict], email: str) -> dict | None:
    target = (email or "").strip().lower()
    if not target:
        return None
    for u in users:
        if (u.get("email") or "").lower() == target:
            return u
    return None


def get_by_email(email: str) -> UserRecord | None:
    u = _find_by_email(storage.load_users(), email)
    return _to_record(u) if u else None


def _display_name(name: str | None, email: str) -> str:
    if name and name.strip():
        return name.strip()
    return email.split("@", 1)[0]


def _new_record(
    username: str,
    email: str | None,
    role: UserRole,
    google_sub: str | None = None,
    hashed_password: str | None = None,
) -> dict:
    return {
        "id": storage.next_id("users"),
        "username": username,
        "email": email.lower() if email else None,
        "google_sub": google_sub,
        "hashed_password": hashed_password,
        "role": role.value,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def get_or_provision_google_user(
    email: str, name: str | None, google_sub: str | None, role: UserRole
) -> UserRecord:
    """Find a user by email or create a passwordless one. Syncs role and
    google_sub from the caller (the allowlist / Google claims)."""
    users = storage.load_users()
    target = email.strip().lower()
    breakglass = (settings.BREAKGLASS_ADMIN_EMAIL or "").strip().lower()
    existing = _find_by_email(users, email)
    if existing:
        changed = False
        if target != breakglass and existing.get("role") != role.value:
            existing["role"] = role.value
            changed = True
        if google_sub and existing.get("google_sub") != google_sub:
            existing["google_sub"] = google_sub
            changed = True
        if changed:
            storage.save_users(users)
        return _to_record(existing)
    record = _new_record(_display_name(name, target), target, role, google_sub=google_sub)
    users.append(record)
    storage.save_users(users)
    return _to_record(record)


def upsert_password_admin(email: str, password: str) -> str:
    """Create or reconcile the break-glass admin (password account, keyed by
    email). Returns 'created' | 'updated' | 'unchanged'."""
    users = storage.load_users()
    target = email.strip().lower()
    existing = _find_by_email(users, email)
    if existing:
        changed = False
        if not existing.get("hashed_password") or not verify_password(
            password, existing["hashed_password"]
        ):
            existing["hashed_password"] = hash_password(password)
            changed = True
        if existing.get("role") != "admin":
            existing["role"] = "admin"
            changed = True
        if changed:
            storage.save_users(users)
            return "updated"
        return "unchanged"
    record = _new_record(
        _display_name(None, target),
        target,
        UserRole.admin,
        hashed_password=hash_password(password),
    )
    users.append(record)
    storage.save_users(users)
    return "created"


def authenticate(login: str, password: str) -> UserRecord | None:
    user = get_by_username(login) or get_by_email(login)
    if not user or not user.hashed_password:
        return None
    # Password login is restricted to the break-glass admin identity. Every
    # other user authenticates via Google; a legacy record that still carries
    # a password hash must NOT be able to log in.
    breakglass = (settings.BREAKGLASS_ADMIN_EMAIL or "").strip().lower()
    if not breakglass or (user.email or "").strip().lower() != breakglass:
        return None
    if not verify_password(password, user.hashed_password):
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
