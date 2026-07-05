from app.core.config import settings


def test_new_auth_settings_exist():
    assert hasattr(settings, "GOOGLE_CLIENT_ID")
    assert settings.ACCESS_ALLOWLIST_FILE.endswith("allowlist.json")


def test_emergency_settings_defaults():
    from app.core.config import Settings

    s = Settings()
    assert s.EMERGENCY_ADMIN_EMAIL == ""
    assert s.RESEND_API_KEY == ""
    assert s.EMAIL_FROM == ""
    assert s.EMERGENCY_CODE_TTL_MINUTES == 10
    assert s.EMERGENCY_CODE_MAX_ATTEMPTS == 5
    assert s.EMERGENCY_CODE_COOLDOWN_SECONDS == 60
