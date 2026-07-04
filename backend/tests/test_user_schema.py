from datetime import datetime, timezone

from app.schemas.user import GoogleLogin, UserRecord, UserRole


def test_user_record_allows_passwordless_google_user():
    u = UserRecord(
        id=1,
        username="Ann",
        email="ann@x.com",
        google_sub="sub-1",
        role=UserRole.annotator,
        created_at=datetime.now(timezone.utc),
    )
    assert u.hashed_password is None
    assert u.email == "ann@x.com"


def test_user_record_still_allows_password_user():
    u = UserRecord(
        id=2,
        username="admin",
        hashed_password="$2b$hash",
        role=UserRole.admin,
        created_at=datetime.now(timezone.utc),
    )
    assert u.email is None
    assert u.google_sub is None


def test_google_login_schema():
    assert GoogleLogin(credential="abc").credential == "abc"
