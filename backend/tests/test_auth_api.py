from app.core.config import settings


def _seed_breakglass(monkeypatch, email="boss@x.com", password="StrongPass!"):
    monkeypatch.setattr(settings, "BREAKGLASS_ADMIN_EMAIL", email)
    from app.services import user as user_service
    user_service.upsert_password_admin(email, password)
    return email, password


def test_register_endpoint_removed(client):
    # Public registration is disabled — users are provisioned via allowlist.json.
    r = client.post("/api/v1/auth/register", json={"username": "alice", "password": "secret123"})
    assert r.status_code == 404


def test_breakglass_login_returns_bearer_token(client, monkeypatch):
    email, password = _seed_breakglass(monkeypatch)
    r = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    assert body["token_type"].lower() == "bearer"


def test_breakglass_login_wrong_password(client, monkeypatch):
    email, _ = _seed_breakglass(monkeypatch)
    r = client.post("/api/v1/auth/login", data={"username": email, "password": "wrong"})
    assert r.status_code == 401


def test_login_rejects_non_breakglass_password_account(client, monkeypatch):
    # Password login is break-glass-only: a legacy/other password account must be rejected.
    _seed_breakglass(monkeypatch, email="boss@x.com")
    from app.schemas.user import UserRole
    from app.services import user as user_service
    user_service.ensure_seed_user("alice", "secret123", UserRole.annotator)
    r = client.post("/api/v1/auth/login", data={"username": "alice", "password": "secret123"})
    assert r.status_code == 401


def test_me_requires_auth(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_returns_current_user(client, auth_headers):
    r = client.get("/api/v1/auth/me", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["username"] == "alice"


def test_me_rejects_garbage_token(client):
    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401
