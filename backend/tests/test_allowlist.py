import json

from app.core.config import settings
from app.services import allowlist as allowlist_service


def _write(tmp_path, monkeypatch, data):
    f = tmp_path / "allowlist.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(settings, "ACCESS_ALLOWLIST_FILE", str(f))


def test_lookup_is_case_insensitive(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, [{"email": "Ann@X.com", "role": "admin", "name": "Ann"}])
    entry = allowlist_service.lookup("ann@x.COM")
    assert entry is not None
    assert entry["role"] == "admin"
    assert entry["name"] == "Ann"


def test_lookup_absent_returns_none(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, [{"email": "ann@x.com", "role": "annotator"}])
    assert allowlist_service.lookup("intruder@x.com") is None


def test_missing_file_is_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ACCESS_ALLOWLIST_FILE", str(tmp_path / "nope.json"))
    assert allowlist_service.load_allowlist() == {}


def test_malformed_file_is_fail_closed(tmp_path, monkeypatch):
    f = tmp_path / "allowlist.json"
    f.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(settings, "ACCESS_ALLOWLIST_FILE", str(f))
    assert allowlist_service.load_allowlist() == {}


def test_default_role_is_annotator(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, [{"email": "ann@x.com"}])
    assert allowlist_service.lookup("ann@x.com")["role"] == "annotator"


def test_non_list_json_is_fail_closed(tmp_path, monkeypatch):
    f = tmp_path / "allowlist.json"
    f.write_text('{"email": "a@x.com"}', encoding="utf-8")  # a dict, not a list
    monkeypatch.setattr(settings, "ACCESS_ALLOWLIST_FILE", str(f))
    assert allowlist_service.load_allowlist() == {}


def test_bad_entries_are_skipped_valid_ones_kept(tmp_path, monkeypatch):
    f = tmp_path / "allowlist.json"
    f.write_text(
        '["nope", {"email": 123}, {"email": "ok@x.com", "role": "admin"}]', encoding="utf-8"
    )
    monkeypatch.setattr(settings, "ACCESS_ALLOWLIST_FILE", str(f))
    assert allowlist_service.load_allowlist() == {
        "ok@x.com": {"email": "ok@x.com", "role": "admin", "name": None}
    }
