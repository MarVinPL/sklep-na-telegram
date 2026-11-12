import ipaddress
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
        if self.app_env.lower() != "production":
            return self

        if not self.telegram_bot_token.strip():
            raise ValueError("TELEGRAM_BOT_TOKEN is required in production")

        if self.database_url.lower().startswith("sqlite:"):
            raise ValueError("DATABASE_URL must use PostgreSQL in production")
        if not self.database_url.lower().startswith(
            ("postgresql://", "postgresql+psycopg://")
        ):
            raise ValueError("DATABASE_URL must use a supported PostgreSQL URL in production")

        rp_id = self.webauthn_rp_id.strip().lower().rstrip(".")
        if not rp_id or rp_id == "localhost" or rp_id.endswith(".localhost"):
            raise ValueError("WEBAUTHN_RP_ID must be a public domain in production")
        try:
            ipaddress.ip_address(rp_id)
        except ValueError:
            pass
        else:
            raise ValueError("WEBAUTHN_RP_ID must be a domain name, not an IP address")

        origin = urlsplit(self.webauthn_origin)
        origin_host = (origin.hostname or "").lower().rstrip(".")
        if (
            origin.scheme != "https"
            or not origin_host
            or origin.username
            or origin.password
            or origin.path not in ("", "/")
            or origin.query
            or origin.fragment
        ):
            raise ValueError("WEBAUTHN_ORIGIN must be an exact HTTPS origin in production")
        if origin_host != rp_id and not origin_host.endswith(f".{rp_id}"):
            raise ValueError("WEBAUTHN_ORIGIN host must match WEBAUTHN_RP_ID")

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
