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


def test_empty_email_never_matches_passwordless_user():
    from app.schemas.user import UserCreate

    user_service.create(UserCreate(username="legacy", password="pw12"))
    assert user_service.get_by_email("") is None
    assert user_service.get_by_email("   ") is None
