import ipaddress
from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, model_validator
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
    cors_allowed_origins: str = ""
    webauthn_challenge_ttl: int = 180
    auth_session_ttl: int = 86400
    auth_cookie_name: str = "shop_session"
    auth_rate_limit_max_requests: int = Field(default=10, ge=1, le=1000)
    auth_rate_limit_account_max_requests: int = Field(default=6, ge=1, le=1000)
    auth_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    auth_rate_limit_retention_seconds: int = Field(default=86400, ge=3600, le=31536000)

    @property
    def allowed_origins(self) -> list[str]:
        configured = [
            item.strip() for item in self.cors_allowed_origins.split(",") if item.strip()
        ]
        return configured or [self.webauthn_origin]

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        if self.telegram_init_data_max_age <= 0:
            raise ValueError("TELEGRAM_INIT_DATA_MAX_AGE must be positive")
        if self.webauthn_challenge_ttl <= 0 or self.auth_session_ttl <= 0:
            raise ValueError("WebAuthn challenge and auth session TTLs must be positive")
        if not self.auth_cookie_name.strip():
            raise ValueError("AUTH_COOKIE_NAME must not be empty")

        if self.app_env.lower() != "production":
            return self

        database_scheme = urlsplit(self.database_url).scheme
        if database_scheme not in {"postgresql", "postgresql+psycopg"}:
            raise ValueError("Production requires a supported PostgreSQL DATABASE_URL")
        if not self.telegram_bot_token.strip():
            raise ValueError("Production requires TELEGRAM_BOT_TOKEN")

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
            or origin.username is not None
            or origin.password is not None
            or origin.path != ""
            or origin.query
            or origin.fragment
        ):
            raise ValueError("Production WEBAUTHN_ORIGIN must be a bare HTTPS origin")
        if origin_host != rp_id and not origin_host.endswith(f".{rp_id}"):
            raise ValueError("WEBAUTHN_ORIGIN host must match WEBAUTHN_RP_ID")

        for allowed_origin in self.allowed_origins:
            parsed = urlsplit(allowed_origin)
            host = (parsed.hostname or "").lower().rstrip(".")
            if (
                parsed.scheme != "https"
                or not host
                or "*" in host
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path != ""
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("CORS_ALLOWED_ORIGINS must contain exact HTTPS origins")
            if host != rp_id and not host.endswith(f".{rp_id}"):
                raise ValueError("Each CORS origin host must match WEBAUTHN_RP_ID")

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
