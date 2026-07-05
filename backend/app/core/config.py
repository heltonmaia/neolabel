from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATA_DIR: str = "./data"
    SECRET_KEY: str = "dev-secret-change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    FRONTEND_URL: str = "http://localhost:5173"
    API_V1_PREFIX: str = "/api/v1"

    # Google Sign-In (public Client ID — no secret needed for the ID-token flow)
    GOOGLE_CLIENT_ID: str = ""
    # Email allowlist mapping email -> role (relative to backend CWD)
    ACCESS_ALLOWLIST_FILE: str = "../allowlist.json"
    # Break-glass local admin (empty -> not seeded)
    BREAKGLASS_ADMIN_EMAIL: str = ""
    BREAKGLASS_ADMIN_PASSWORD: str = ""

    # Emergency email-code access (break-glass v2). BREAKGLASS_* above are
    # removed in a later task once the password path is gone.
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = ""
    EMERGENCY_ADMIN_EMAIL: str = ""
    EMERGENCY_CODE_TTL_MINUTES: int = 10
    EMERGENCY_CODE_MAX_ATTEMPTS: int = 5
    EMERGENCY_CODE_COOLDOWN_SECONDS: int = 60


settings = Settings()
