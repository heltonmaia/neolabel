import pytest

from app.core.config import settings
from app.core.security import decode_token


@pytest.fixture
def admin_email(monkeypatch):
    monkeypatch.setattr(settings, "EMERGENCY_ADMIN_EMAIL", "owner@example.com")
    return "owner@example.com"


@pytest.fixture
def capture_code(monkeypatch):
    box = {}
    monkeypatch.setattr(
        "app.services.emergency.email_service.send_emergency_code",
        lambda to, code: box.update(to=to, code=code),
    )
    return box


def test_request_always_generic(client, admin_email, capture_code):
    r1 = client.post("/api/v1/auth/emergency/request", json={"email": admin_email})
    r2 = client.post("/api/v1/auth/emergency/request", json={"email": "nope@example.com"})
    assert r1.status_code == r2.status_code == 200
    expected = {"detail": "If that email is registered, a code has been sent."}
    assert r1.json() == r2.json() == expected


def test_full_login_flow(client, admin_email, capture_code):
    client.post("/api/v1/auth/emergency/request", json={"email": admin_email})
    r = client.post(
        "/api/v1/auth/emergency/verify",
        json={"email": admin_email, "code": capture_code["code"]},
    )
    assert r.status_code == 200
    token = r.json()["access_token"]
    assert decode_token(token) is not None  # a valid session

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["role"] == "admin"


def test_verify_wrong_code_is_400(client, admin_email, capture_code):
    client.post("/api/v1/auth/emergency/request", json={"email": admin_email})
    r = client.post(
        "/api/v1/auth/emergency/verify", json={"email": admin_email, "code": "000000"}
    )
    assert r.status_code == 400
    assert r.json() == {"detail": "Invalid or expired code."}


def test_non_admin_cannot_get_code(client, admin_email, capture_code):
    client.post("/api/v1/auth/emergency/request", json={"email": "nope@example.com"})
    assert "code" not in capture_code  # nothing was generated/sent
