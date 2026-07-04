import json

from app.core.config import settings
from app.schemas.user import UserRole
from app.services import user as user_service


def _allowlist(tmp_path, monkeypatch, entries):
    f = tmp_path / "allowlist.json"
    f.write_text(json.dumps(entries), encoding="utf-8")
    monkeypatch.setattr(settings, "ACCESS_ALLOWLIST_FILE", str(f))


def test_reconcile_removes_only_unlisted_non_breakglass(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "BREAKGLASS_ADMIN_EMAIL", "boss@x.com")
    _allowlist(tmp_path, monkeypatch, [{"email": "keep@x.com", "role": "annotator"}])
    user_service.upsert_password_admin("boss@x.com", "StrongPass!")
    user_service.get_or_provision_google_user("keep@x.com", None, None, UserRole.annotator)
    user_service.get_or_provision_google_user("drop@x.com", None, None, UserRole.annotator)

    from scripts.reconcile_users import reconcile

    preview = reconcile(apply=False)
    assert {u["email"] for u in preview} == {"drop@x.com"}
    assert user_service.get_by_email("drop@x.com") is not None  # dry-run kept it

    removed = reconcile(apply=True)
    assert {u["email"] for u in removed} == {"drop@x.com"}
    assert user_service.get_by_email("drop@x.com") is None
    assert user_service.get_by_email("keep@x.com") is not None
    assert user_service.get_by_email("boss@x.com") is not None  # break-glass preserved
