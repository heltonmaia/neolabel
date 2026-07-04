from app.core.config import settings


def test_new_auth_settings_exist():
    assert hasattr(settings, "GOOGLE_CLIENT_ID")
    assert hasattr(settings, "BREAKGLASS_ADMIN_EMAIL")
    assert hasattr(settings, "BREAKGLASS_ADMIN_PASSWORD")
    assert settings.ACCESS_ALLOWLIST_FILE.endswith("allowlist.json")
