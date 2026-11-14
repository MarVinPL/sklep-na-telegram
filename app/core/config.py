from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Sklep na Telegram"
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./dev.db"
    telegram_bot_token: str = ""
    telegram_init_data_max_age: int = 300
    webauthn_rp_id: str = "localhost"
    webauthn_rp_name: str = "Sklep na Telegram"
    webauthn_origin: str = "http://localhost:8000"
    webauthn_challenge_ttl: int = 180
    auth_session_ttl: int = 86400
    auth_cookie_name: str = "shop_session"

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.telegram_init_data_max_age <= 0:
            raise ValueError("TELEGRAM_INIT_DATA_MAX_AGE must be positive")
        if self.webauthn_challenge_ttl <= 0 or self.auth_session_ttl <= 0:
            raise ValueError("WebAuthn challenge and auth session TTLs must be positive")
        if not self.auth_cookie_name.strip():
            raise ValueError("AUTH_COOKIE_NAME must not be empty")

        if self.app_env.lower() != "production":
            return self

        database_scheme = urlsplit(self.database_url).scheme
        if not database_scheme.startswith("postgresql"):
            raise ValueError("Production requires a PostgreSQL DATABASE_URL")
        if not self.telegram_bot_token:
            raise ValueError("Production requires TELEGRAM_BOT_TOKEN")

        rp_id = self.webauthn_rp_id.strip().lower().rstrip(".")
        origin = urlsplit(self.webauthn_origin)
        origin_host = (origin.hostname or "").lower().rstrip(".")
        if (
            origin.scheme != "https"
            or not origin_host
            or origin.username is not None
            or origin.password is not None
            or origin.path not in ("", "/")
            or origin.query
            or origin.fragment
        ):
            raise ValueError("Production WEBAUTHN_ORIGIN must be a bare HTTPS origin")
        if rp_id == "localhost" or not (
            origin_host == rp_id or origin_host.endswith(f".{rp_id}")
        ):
            raise ValueError("Production WEBAUTHN_RP_ID must match the HTTPS origin host")

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
