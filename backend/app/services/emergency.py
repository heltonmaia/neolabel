"""Emergency email-code access (break-glass v2).

Only settings.EMERGENCY_ADMIN_EMAIL is eligible. A 6-digit, single-use,
short-lived code is emailed (via services.email) and verified here; success
mints a normal admin session. Independent of Google and of allowlist.json.
"""
from __future__ import annotations

import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone

from app.core import storage
from app.core.config import settings
from app.core.security import hash_emergency_code
from app.schemas.user import UserRecord, UserRole
from app.services import email as email_service
from app.services import user as user_service

log = logging.getLogger("neolabel")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_admin_email(email: str) -> bool:
    admin = (settings.EMERGENCY_ADMIN_EMAIL or "").strip().lower()
    return bool(admin) and (email or "").strip().lower() == admin


def request_code(email: str) -> None:
    """If `email` is the emergency admin and no fresh code is within the
    cooldown window, generate + store + email a new 6-digit code. Returns
    nothing so the endpoint responds identically for any email."""
    if not _is_admin_email(email):
        return
    existing = storage.load_emergency_code()
    if existing:
        created = datetime.fromisoformat(existing["created_at"])
        if _now() - created < timedelta(seconds=settings.EMERGENCY_CODE_COOLDOWN_SECONDS):
            return
    admin = settings.EMERGENCY_ADMIN_EMAIL.strip().lower()
    code = f"{secrets.randbelow(10**6):06d}"
    storage.save_emergency_code(
        {
            "email": admin,
            "code_hash": hash_emergency_code(code),
            "expires_at": (
                _now() + timedelta(minutes=settings.EMERGENCY_CODE_TTL_MINUTES)
            ).isoformat(),
            "attempts": 0,
            "created_at": _now().isoformat(),
        }
    )
    try:
        email_service.send_emergency_code(admin, code)
    except Exception:  # noqa: BLE001 - never leak send status to the caller
        log.exception("emergency code: failed to send email")


def verify_code(email: str, code: str) -> UserRecord | None:
    """Validate a submitted code. On success burn it and return the admin
    user (provisioned if needed). On failure count the attempt and burn the
    code once attempts are exhausted. Returns None on any failure."""
    stored = storage.load_emergency_code()
    if not stored or not _is_admin_email(email):
        return None
    if _now() >= datetime.fromisoformat(stored["expires_at"]):
        storage.delete_emergency_code()
        return None
    if stored.get("attempts", 0) >= settings.EMERGENCY_CODE_MAX_ATTEMPTS:
        storage.delete_emergency_code()
        return None
    if hmac.compare_digest(stored["code_hash"], hash_emergency_code(code)):
        storage.delete_emergency_code()
        return user_service.get_or_provision_google_user(
            email=settings.EMERGENCY_ADMIN_EMAIL.strip().lower(),
            name=None,
            google_sub=None,
            role=UserRole.admin,
        )
    stored["attempts"] = stored.get("attempts", 0) + 1
    if stored["attempts"] >= settings.EMERGENCY_CODE_MAX_ATTEMPTS:
        storage.delete_emergency_code()
    else:
        storage.save_emergency_code(stored)
    return None
