import hashlib
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request, Response
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db import Base
from app.models import AuthSession, User
from app.routers import passkeys
from app.security.origins import require_allowed_origin
from app.security.sessions import require_session


@pytest.fixture
def db() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


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


def make_request(raw_token: str = "", method: str = "GET", origin: str | None = None) -> Request:
    headers = []
    if raw_token:
        headers.append((b"cookie", f"shop_session={raw_token}".encode()))
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/",
            "headers": headers,
            "query_string": b"",
            "server": ("testserver", 443),
            "client": ("127.0.0.1", 12345),
            "scheme": "https",
        }
    )


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
        {"webauthn_rp_id": "203.0.113.10", "webauthn_origin": "https://203.0.113.10"},
        {"webauthn_origin": "http://shop.example.com"},
        {"webauthn_origin": "https://attacker.example.net"},
        {"webauthn_origin": "https://shop.example.com/path"},
        {"webauthn_origin": "https://shop.example.com/"},
        {"cors_allowed_origins": "https://*.example.com"},
        {"cors_allowed_origins": "https://attacker.example.net"},
        {"cors_allowed_origins": "https://shop.example.com/path"},
        {"cors_allowed_origins": "https://shop.example.com/"},
    ],
)
def test_production_configuration_rejects_unsafe_values(overrides: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **production_settings(**overrides))


def test_successful_login_rotates_previous_active_session(
    db: Session, monkeypatch: pytest.MonkeyPatch
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


def test_require_session_accepts_valid_session(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.security.sessions.get_settings",
        lambda: SimpleNamespace(auth_cookie_name="shop_session"),
    )
    user = User(telegram_user_id="valid-session-user")
    db.add(user)
    db.flush()
    raw_token = "valid-session-token"
    session = AuthSession(
        user_id=user.id,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(session)
    db.commit()

    assert require_session(make_request(raw_token), db).id == session.id


@pytest.mark.parametrize("revoked,expired", [(True, False), (False, True)])
def test_require_session_rejects_revoked_or_expired_session(
    db: Session, monkeypatch: pytest.MonkeyPatch, revoked: bool, expired: bool
) -> None:
    monkeypatch.setattr(
        "app.security.sessions.get_settings",
        lambda: SimpleNamespace(auth_cookie_name="shop_session"),
    )
    user = User(telegram_user_id=f"invalid-session-{revoked}-{expired}")
    db.add(user)
    db.flush()
    raw_token = f"invalid-{revoked}-{expired}"
    session = AuthSession(
        user_id=user.id,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        expires_at=(
            datetime.now(UTC) - timedelta(seconds=1)
            if expired
            else datetime.now(UTC) + timedelta(hours=1)
        ),
        revoked_at=datetime.now(UTC) if revoked else None,
    )
    db.add(session)
    db.commit()

    with pytest.raises(HTTPException) as error:
        require_session(make_request(raw_token), db)
    assert error.value.status_code == 401


def test_logout_revokes_server_session_and_clears_cookie(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        passkeys,
        "get_settings",
        lambda: SimpleNamespace(app_env="production", auth_cookie_name="shop_session"),
    )
    user = User(telegram_user_id="logout-user")
    db.add(user)
    db.flush()
    raw_token = "logout-session-token"
    session = AuthSession(
        user_id=user.id,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(session)
    db.commit()

    response = Response()
    result = passkeys.logout(make_request(raw_token), response, db)

    db.refresh(session)
    assert result == {"logged_out": True}
    assert session.revoked_at is not None
    assert "max-age=0" in response.headers["set-cookie"].lower()



def test_allowed_origin_accepts_configured_origin_on_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.security.origins.get_settings",
        lambda: SimpleNamespace(allowed_origins=["https://shop.example.com"]),
    )
    assert require_allowed_origin(
        make_request(method="POST", origin="https://shop.example.com")
    ) is None


@pytest.mark.parametrize("origin", [None, "https://attacker.example.net", "null"])
def test_allowed_origin_rejects_missing_or_untrusted_origin(
    monkeypatch: pytest.MonkeyPatch, origin: str | None
) -> None:
    monkeypatch.setattr(
        "app.security.origins.get_settings",
        lambda: SimpleNamespace(allowed_origins=["https://shop.example.com"]),
    )
    with pytest.raises(HTTPException) as error:
        require_allowed_origin(make_request(method="POST", origin=origin))
    assert error.value.status_code == 403


def test_safe_read_method_does_not_require_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.security.origins.get_settings",
        lambda: SimpleNamespace(allowed_origins=["https://shop.example.com"]),
    )
    assert require_allowed_origin(make_request(method="GET")) is None



def test_allowed_origins_uses_exact_comma_separated_values() -> None:
    settings = Settings(
        _env_file=None,
        **production_settings(
            cors_allowed_origins="https://shop.example.com,https://admin.example.com"
        ),
    )
    assert settings.allowed_origins == [
        "https://shop.example.com",
        "https://admin.example.com",
    ]


def test_allowed_origins_defaults_to_webauthn_origin() -> None:
    settings = Settings(_env_file=None, **production_settings())
    assert settings.allowed_origins == ["https://shop.example.com"]



def test_cors_preflight_allows_only_configured_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        app_name="test",
        app_env="production",
        allowed_origins=["https://shop.example.com"],
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    from app.main import create_app

    client = TestClient(create_app())
    allowed = client.options(
        "/auth/passkeys/logout",
        headers={
            "Origin": "https://shop.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    denied = client.options(
        "/auth/passkeys/logout",
        headers={
            "Origin": "https://attacker.example.net",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://shop.example.com"
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert denied.status_code == 400


def test_passkey_post_rejects_untrusted_origin_before_auth_logic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        app_name="test",
        app_env="production",
        allowed_origins=["https://shop.example.com"],
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.origins.get_settings", lambda: settings)
    from app.main import create_app

    response = TestClient(create_app()).post(
        "/auth/passkeys/logout",
        headers={"Origin": "https://attacker.example.net"},
    )
    assert response.status_code == 403
