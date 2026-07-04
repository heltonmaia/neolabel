from app.core.config import settings


def _configure(tmp_path, monkeypatch, allowlist):
    (tmp_path / "allowlist.json").write_text(__import__("json").dumps(allowlist), encoding="utf-8")
    monkeypatch.setattr(settings, "ACCESS_ALLOWLIST_FILE", str(tmp_path / "allowlist.json"))
    monkeypatch.setattr(settings, "BREAKGLASS_ADMIN_EMAIL", "boss@x.com")
    monkeypatch.setattr(settings, "BREAKGLASS_ADMIN_PASSWORD", "StrongPass!")


def test_seed_creates_breakglass_and_allowlist_users(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, [{"email": "ann@x.com", "role": "annotator", "name": "Ann"}])
    from app.main import seed_users

    seed_users()
    from app.services import user as user_service

    boss = user_service.get_by_email("boss@x.com")
    assert boss is not None and boss.role.value == "admin" and boss.hashed_password
    ann = user_service.get_by_email("ann@x.com")
    assert ann is not None and ann.role.value == "annotator" and ann.hashed_password is None


def test_breakglass_can_password_login_google_user_cannot(client, tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, [{"email": "ann@x.com", "role": "annotator"}])
    from app.main import seed_users

    seed_users()
    ok = client.post(
        "/api/v1/auth/login", data={"username": "boss@x.com", "password": "StrongPass!"}
    )
    assert ok.status_code == 200
    no = client.post("/api/v1/auth/login", data={"username": "ann@x.com", "password": "anything"})
    assert no.status_code == 401


def test_no_breakglass_when_env_unset(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ACCESS_ALLOWLIST_FILE", str(tmp_path / "none.json"))
    monkeypatch.setattr(settings, "BREAKGLASS_ADMIN_EMAIL", "")
    monkeypatch.setattr(settings, "BREAKGLASS_ADMIN_PASSWORD", "")
    from app.main import seed_users

    seed_users()
    from app.services import user as user_service

    assert user_service.get_by_email("boss@x.com") is None
