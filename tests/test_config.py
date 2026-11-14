import pytest
from pydantic import ValidationError

from app.core.config import Settings


def production_settings(**overrides: str) -> dict[str, str]:
    values = {
        "app_env": "production",
        "database_url": "postgresql+psycopg://shop:secret@db:5432/shop",
        "telegram_bot_token": "test-token",
        "webauthn_rp_id": "example.com",
        "webauthn_origin": "https://shop.example.com",
    }
    values.update(overrides)
    return values


def test_production_accepts_explicit_secure_configuration() -> None:
    settings = Settings(**production_settings())

    assert settings.app_env == "production"


@pytest.mark.parametrize(
    "overrides",
    [
        {"database_url": "sqlite:///./dev.db"},
        {"telegram_bot_token": ""},
        {"webauthn_rp_id": "localhost"},
        {"webauthn_origin": "http://shop.example.com"},
        {"webauthn_rp_id": "other.example.net"},
        {"webauthn_origin": "https://shop.example.com/path"},
    ],
)
def test_production_rejects_unsafe_configuration(overrides: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        Settings(**production_settings(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"telegram_init_data_max_age": "0"},
        {"webauthn_challenge_ttl": "0"},
        {"auth_session_ttl": "0"},
        {"auth_cookie_name": " "},
    ],
)
def test_rejects_non_positive_ttls_and_empty_cookie_name(
    overrides: dict[str, str],
) -> None:
    with pytest.raises(ValidationError):
        Settings(**overrides)
