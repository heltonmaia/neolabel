from app.core.config import settings


def _configure(tmp_path, monkeypatch, allowlist):
    (tmp_path / "allowlist.json").write_text(__import__("json").dumps(allowlist), encoding="utf-8")
    monkeypatch.setattr(settings, "ACCESS_ALLOWLIST_FILE", str(tmp_path / "allowlist.json"))


def test_seed_provisions_allowlist_users(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, [{"email": "ann@x.com", "role": "annotator", "name": "Ann"}])
    from app.main import seed_users

    seed_users()
    from app.services import user as user_service

    ann = user_service.get_by_email("ann@x.com")
    assert ann is not None and ann.role.value == "annotator" and ann.hashed_password is None
