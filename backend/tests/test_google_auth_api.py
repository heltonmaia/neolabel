import json

from app.core.config import settings


def _set_allowlist(tmp_path, monkeypatch, entries):
    f = tmp_path / "allowlist.json"
    f.write_text(json.dumps(entries), encoding="utf-8")
    monkeypatch.setattr(settings, "ACCESS_ALLOWLIST_FILE", str(f))


def _fake_google(monkeypatch, email, name="Test User", verified=True, sub="sub-1"):
    from app.services import google_auth

    def fake(credential):
        return {"email": email, "email_verified": verified, "name": name, "sub": sub}

    monkeypatch.setattr(google_auth, "verify_google_id_token", fake)


def test_allowlisted_email_gets_token_and_is_provisioned(client, tmp_path, monkeypatch):
    _set_allowlist(tmp_path, monkeypatch, [{"email": "a@x.com", "role": "annotator"}])
    _fake_google(monkeypatch, "a@x.com")
    r = client.post("/api/v1/auth/google", json={"credential": "tok"})
    assert r.status_code == 200
    assert r.json()["access_token"]
    from app.services import user as user_service

    u = user_service.get_by_email("a@x.com")
    assert u is not None and u.role.value == "annotator" and u.google_sub == "sub-1"


def test_non_allowlisted_email_forbidden(client, tmp_path, monkeypatch):
    _set_allowlist(tmp_path, monkeypatch, [{"email": "a@x.com", "role": "annotator"}])
    _fake_google(monkeypatch, "intruder@x.com")
    r = client.post("/api/v1/auth/google", json={"credential": "tok"})
    assert r.status_code == 403


def test_unverified_email_forbidden(client, tmp_path, monkeypatch):
    _set_allowlist(tmp_path, monkeypatch, [{"email": "a@x.com", "role": "admin"}])
    _fake_google(monkeypatch, "a@x.com", verified=False)
    r = client.post("/api/v1/auth/google", json={"credential": "tok"})
    assert r.status_code == 403


def test_invalid_token_unauthorized(client, tmp_path, monkeypatch):
    _set_allowlist(tmp_path, monkeypatch, [{"email": "a@x.com", "role": "admin"}])
    from app.services import google_auth

    def boom(credential):
        raise ValueError("bad token")

    monkeypatch.setattr(google_auth, "verify_google_id_token", boom)
    r = client.post("/api/v1/auth/google", json={"credential": "tok"})
    assert r.status_code == 401


def test_role_sync_on_relogin(client, tmp_path, monkeypatch):
    _set_allowlist(tmp_path, monkeypatch, [{"email": "a@x.com", "role": "annotator"}])
    _fake_google(monkeypatch, "a@x.com")
    client.post("/api/v1/auth/google", json={"credential": "t"})
    _set_allowlist(tmp_path, monkeypatch, [{"email": "a@x.com", "role": "admin"}])
    client.post("/api/v1/auth/google", json={"credential": "t"})
    from app.services import user as user_service

    assert user_service.get_by_email("a@x.com").role.value == "admin"


def test_revocation_after_removal(client, tmp_path, monkeypatch):
    _set_allowlist(tmp_path, monkeypatch, [{"email": "a@x.com", "role": "annotator"}])
    _fake_google(monkeypatch, "a@x.com")
    assert client.post("/api/v1/auth/google", json={"credential": "t"}).status_code == 200
    _set_allowlist(tmp_path, monkeypatch, [])
    assert client.post("/api/v1/auth/google", json={"credential": "t"}).status_code == 403
