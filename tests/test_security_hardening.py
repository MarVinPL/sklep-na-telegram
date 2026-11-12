from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import Response
from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import Settings
from app.models import AuthSession, User
from app.routers import passkeys


def production_settings(**overrides: str) -> dict[str, str]:
    values = {
        "app_env": "production",
        "database_url": "postgresql+psycopg://shop:secret@db.example.com/shop",
        "telegram_bot_token": "test-bot-token",
        "webauthn_rp_id": "example.com",
        "webauthn_origin": "https://shop.example.com",
    }
    values.update(overrides)
    return values


def test_production_configuration_accepts_explicit_secure_values() -> None:
    settings = Settings(_env_file=None, **production_settings())

    assert settings.app_env == "production"
    assert settings.webauthn_rp_id == "example.com"


@pytest.mark.parametrize(
    "overrides",
    [
        {"telegram_bot_token": ""},
        {"database_url": "sqlite:///./production.db"},
        {"webauthn_rp_id": "localhost"},
        {"webauthn_origin": "http://shop.example.com"},
        {"webauthn_origin": "https://attacker.example.net"},
        {"webauthn_origin": "https://shop.example.com/path"},
    ],
)
def test_production_configuration_rejects_unsafe_values(overrides: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **production_settings(**overrides))


def test_successful_login_rotates_previous_active_session(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        passkeys,
        "get_settings",
        lambda: SimpleNamespace(
            app_env="production",
            auth_cookie_name="shop_session",
            auth_session_ttl=3600,
        ),
    )
    user = User(telegram_user_id="rotate-session-user")
    db.add(user)
    db.flush()
    previous = AuthSession(
        user_id=user.id,
        token_hash="a" * 64,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(previous)
    db.commit()

    response = Response()
    passkeys._session_cookie(db, user, response)

    db.refresh(previous)
    active_sessions = db.scalars(
        select(AuthSession).where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
        )
    ).all()
    assert previous.revoked_at is not None
    assert len(active_sessions) == 1
    assert active_sessions[0].token_hash != previous.token_hash
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie
