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
    stored = storage.load_emergency_code()
    # record persists (so request_code's cooldown keeps withholding a fresh
    # code) — it is merely blocked, not deleted, once attempts are exhausted
    assert stored is not None
    assert stored["attempts"] >= settings.EMERGENCY_CODE_MAX_ATTEMPTS
    # even the real code now fails (blocked by the exhausted attempts guard)
    assert emergency.verify_code(admin_email, capture_code["code"]) is None


def test_cooldown_holds_after_burn(admin_email, capture_code, monkeypatch):
    """Burning a code via exhausted attempts must not let request_code skip
    the cooldown — otherwise an attacker can burn + immediately re-request
    a fresh code at network speed, bypassing the 60s throttle entirely."""
    monkeypatch.setattr(settings, "EMERGENCY_CODE_MAX_ATTEMPTS", 2)
    from app.services import emergency

    emergency.request_code(admin_email)
    emergency.verify_code(admin_email, "000000")
    emergency.verify_code(admin_email, "000000")  # exhausts attempts
    capture_code.clear()
    emergency.request_code(admin_email)  # immediate retry after burn
    assert "code" not in capture_code  # cooldown still holds — no regeneration


def test_request_code_swallows_send_failure(admin_email, monkeypatch):
    """A broken email transport must not raise out of request_code, and the
    code should still be stored (generation/storage happens before the send,
    which runs outside the lock and is best-effort)."""
    from app.core import storage
    from app.services import emergency

    def fake_send(to, code):
        raise RuntimeError("resend is down")

    monkeypatch.setattr("app.services.emergency.email_service.send_emergency_code", fake_send)

    emergency.request_code(admin_email)  # must not raise

    assert storage.load_emergency_code() is not None


def test_verify_expired_code_fails(admin_email, capture_code, monkeypatch):
    monkeypatch.setattr(settings, "EMERGENCY_CODE_TTL_MINUTES", 0)
    from app.core import storage
    from app.services import emergency

    emergency.request_code(admin_email)
    assert emergency.verify_code(admin_email, capture_code["code"]) is None
    assert storage.load_emergency_code() is None


def test_request_code_sanitizes_config_email_before_send(capture_code, monkeypatch):
    """Guard against passing raw config value to email service.
    If EMERGENCY_ADMIN_EMAIL has whitespace or mixed case, the send
    must receive the normalized (stripped + lowercased) version."""
    monkeypatch.setattr(settings, "EMERGENCY_ADMIN_EMAIL", "  Owner@Example.com  ")
    from app.services import emergency

    emergency.request_code("owner@example.com")
    # The email service must receive the normalized address
    assert capture_code["to"] == "owner@example.com"
