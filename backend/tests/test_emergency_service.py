import pytest

from app.core.config import settings


@pytest.fixture
def admin_email(monkeypatch):
    monkeypatch.setattr(settings, "EMERGENCY_ADMIN_EMAIL", "owner@example.com")
    return "owner@example.com"


@pytest.fixture
def capture_code(monkeypatch):
    """Capture the code the service tries to email."""
    box = {}

    def fake_send(to, code):
        box["to"] = to
        box["code"] = code

    monkeypatch.setattr("app.services.emergency.email_service.send_emergency_code", fake_send)
    return box


def test_request_code_non_admin_is_noop(monkeypatch, capture_code):
    monkeypatch.setattr(settings, "EMERGENCY_ADMIN_EMAIL", "owner@example.com")
    from app.core import storage
    from app.services import emergency

    emergency.request_code("intruder@example.com")
    assert storage.load_emergency_code() is None
    assert "code" not in capture_code


def test_request_code_admin_stores_and_sends(admin_email, capture_code):
    from app.core import storage
    from app.services import emergency

    emergency.request_code("Owner@Example.com")  # case-insensitive
    stored = storage.load_emergency_code()
    assert stored is not None and stored["attempts"] == 0
    assert capture_code["to"] == admin_email
    assert len(capture_code["code"]) == 6 and capture_code["code"].isdigit()


def test_request_code_within_cooldown_does_not_resend(admin_email, capture_code):
    from app.services import emergency

    emergency.request_code(admin_email)
    capture_code.clear()
    emergency.request_code(admin_email)  # immediate second call
    assert "code" not in capture_code  # cooldown → no new send


def test_verify_success_returns_admin_and_burns(admin_email, capture_code):
    from app.core import storage
    from app.core.security import decode_token, create_access_token  # noqa: F401
    from app.services import emergency

    emergency.request_code(admin_email)
    user = emergency.verify_code(admin_email, capture_code["code"])
    assert user is not None and user.role.value == "admin"
    assert storage.load_emergency_code() is None  # single-use burned


def test_verify_wrong_code_counts_attempt(admin_email, capture_code):
    from app.core import storage
    from app.services import emergency

    emergency.request_code(admin_email)
    assert emergency.verify_code(admin_email, "000000") is None
    assert storage.load_emergency_code()["attempts"] == 1


def test_verify_burns_after_max_attempts(admin_email, capture_code, monkeypatch):
    monkeypatch.setattr(settings, "EMERGENCY_CODE_MAX_ATTEMPTS", 2)
    from app.core import storage
    from app.services import emergency

    emergency.request_code(admin_email)
    emergency.verify_code(admin_email, "000000")
    emergency.verify_code(admin_email, "000000")  # hits max
    assert storage.load_emergency_code() is None
    # even the real code now fails (burned)
    assert emergency.verify_code(admin_email, capture_code["code"]) is None


def test_verify_expired_code_fails(admin_email, capture_code, monkeypatch):
    monkeypatch.setattr(settings, "EMERGENCY_CODE_TTL_MINUTES", 0)
    from app.core import storage
    from app.services import emergency

    emergency.request_code(admin_email)
    assert emergency.verify_code(admin_email, capture_code["code"]) is None
    assert storage.load_emergency_code() is None
