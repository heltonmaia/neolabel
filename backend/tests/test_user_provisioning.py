from app.schemas.user import UserRole
from app.services import user as user_service


def test_provision_creates_passwordless_user():
    u = user_service.get_or_provision_google_user(
        email="Ann@X.com", name="Ann Smith", google_sub="sub-1", role=UserRole.annotator
    )
    assert u.email == "ann@x.com"  # stored lowercase
    assert u.username == "Ann Smith"  # display name from Google
    assert u.hashed_password is None
    assert u.google_sub == "sub-1"
    assert user_service.get_by_email("ann@x.com").id == u.id


def test_provision_is_idempotent_and_syncs_role():
    a = user_service.get_or_provision_google_user(
        email="ann@x.com", name=None, google_sub="sub-1", role=UserRole.annotator
    )
    b = user_service.get_or_provision_google_user(
        email="ann@x.com", name=None, google_sub="sub-1", role=UserRole.admin
    )
    assert a.id == b.id  # same record, id preserved
    assert b.role == UserRole.admin  # role synced from allowlist
    assert b.username == "ann"  # fallback display name = local part


def test_upsert_password_admin_and_authenticate_by_email(monkeypatch):
    # authenticate() is break-glass-only — the admin's email must match
    # BREAKGLASS_ADMIN_EMAIL for password login to succeed.
    from app.core.config import settings

    monkeypatch.setattr(settings, "BREAKGLASS_ADMIN_EMAIL", "boss@x.com")
    status = user_service.upsert_password_admin("boss@x.com", "StrongPass!")
    assert status == "created"
    assert user_service.upsert_password_admin("boss@x.com", "StrongPass!") == "unchanged"
    u = user_service.authenticate("boss@x.com", "StrongPass!")
    assert u is not None and u.role == UserRole.admin


def test_google_user_cannot_authenticate_without_password():
    user_service.get_or_provision_google_user(
        email="ann@x.com", name=None, google_sub="s", role=UserRole.annotator
    )
    assert user_service.authenticate("ann@x.com", "whatever") is None


def test_empty_email_never_matches_passwordless_user():
    from app.schemas.user import UserCreate
    user_service.create(UserCreate(username="legacy", password="pw12"))
    assert user_service.get_by_email("") is None
    assert user_service.get_by_email("   ") is None
    assert user_service.authenticate("", "pw12") is None
