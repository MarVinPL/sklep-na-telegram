from functools import lru_cache

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
