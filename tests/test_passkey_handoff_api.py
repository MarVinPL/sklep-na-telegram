import hashlib
from collections.abc import Generator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import create_app
from app.models import AuthRateLimit, AuthSession, PasskeyCredential, PasskeyHandoff, User
from app.routers import passkeys

ORIGIN = "http://localhost:5173"
INIT_DATA = "signed-original-telegram-init-data"


@pytest.fixture
def api_client(monkeypatch: pytest.MonkeyPatch) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        with factory() as session:
            yield session

    settings = SimpleNamespace(
        app_name="Sklep na Telegram test",
        app_env="development",
        allowed_origins=[ORIGIN],
        telegram_bot_token="test-bot-token",
        telegram_init_data_max_age=300,
        webauthn_rp_id="localhost",
        webauthn_rp_name="Sklep test",
        webauthn_origin=ORIGIN,
        webauthn_challenge_ttl=180,
        auth_session_ttl=3600,
        auth_cookie_name="shop_session",
        auth_rate_limit_max_requests=20,
        auth_rate_limit_account_max_requests=20,
        auth_rate_limit_window_seconds=60,
        passkey_handoff_ttl_seconds=120,
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.origins.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.rate_limit.get_settings", lambda: settings)
    monkeypatch.setattr("app.routers.passkeys.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.routers.passkeys.verify_telegram_init_data",
        lambda raw: {"telegram_user_id": "424242"},
    )
    monkeypatch.setattr(
        "app.security.rate_limit.verify_telegram_init_data",
        lambda raw: {"telegram_user_id": "424242"},
    )

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client, factory

    Base.metadata.drop_all(engine)
    engine.dispose()


def test_handoff_api_full_flow_redeems_session_in_original_telegram_context(
    api_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, factory = api_client
    origin_headers = {"Origin": ORIGIN}

    issued = client.post(
        "/auth/passkeys/handoff",
        headers={**origin_headers, "X-Telegram-Init-Data": INIT_DATA},
    )
    assert issued.status_code == 200
    token = issued.json()["handoff_token"]
    assert len(token) >= 40
    assert INIT_DATA not in issued.text

    with factory() as db:
        user = db.scalar(select(User).where(User.telegram_user_id == "424242"))
        assert user is not None
        stored = db.scalar(select(PasskeyHandoff))
        assert stored is not None
        assert stored.token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert stored.token_hash != token
        assert stored.context_hash == hashlib.sha256(INIT_DATA.encode()).hexdigest()
        db.add(
            PasskeyCredential(
                user_id=user.id,
                credential_id="api-handoff-credential",
                public_key=b"test-public-key",
                sign_count=0,
            )
        )
        db.commit()

    options = client.post(
        "/auth/passkeys/handoff/authentication/options",
        headers=origin_headers,
        json={"handoff_token": token},
    )
    assert options.status_code == 200
    challenge_id = options.json()["challenge_id"]

    with factory() as db:
        assert db.scalars(select(AuthSession)).all() == []

    monkeypatch.setattr(
        passkeys,
        "verify_authentication_response",
        lambda **kwargs: SimpleNamespace(
            new_sign_count=1,
            credential_device_type="single_device",
            credential_backed_up=False,
        ),
    )
    verified = client.post(
        "/auth/passkeys/handoff/authentication/verify",
        headers=origin_headers,
        json={
            "handoff_token": token,
            "challenge_id": challenge_id,
            "credential": {"id": "api-handoff-credential"},
        },
    )
    assert verified.status_code == 200
    assert verified.json() == {"verified": True}
    assert "set-cookie" not in verified.headers

    with factory() as db:
        assert db.scalars(select(AuthSession)).all() == []

    redeemed = client.post(
        "/auth/passkeys/handoff/redeem",
        headers={**origin_headers, "X-Telegram-Init-Data": INIT_DATA},
        json={"handoff_token": token},
    )
    assert redeemed.status_code == 200
    assert redeemed.json() == {"authenticated": True}
    assert "shop_session=" in redeemed.headers["set-cookie"]
    assert "httponly" in redeemed.headers["set-cookie"].lower()

    with factory() as db:
        sessions = db.scalars(select(AuthSession)).all()
        assert len(sessions) == 1
        handoff = db.scalar(select(PasskeyHandoff))
        assert handoff is not None
        assert handoff.redeemed_at is not None
        assert db.scalars(select(AuthRateLimit)).all()


def test_handoff_api_rejects_untrusted_origin_before_issuing_ticket(api_client) -> None:
    client, factory = api_client
    response = client.post(
        "/auth/passkeys/handoff",
        headers={
            "Origin": "https://attacker.example",
            "X-Telegram-Init-Data": INIT_DATA,
        },
    )

    assert response.status_code == 403
    with factory() as db:
        assert db.scalars(select(PasskeyHandoff)).all() == []


def test_authentication_options_api_does_not_disclose_passkey_presence(api_client) -> None:
    client, _factory = api_client
    headers = {"Origin": ORIGIN, "X-Telegram-Init-Data": INIT_DATA}
    response = client.post("/auth/passkeys/authentication/options", headers=headers)

    assert response.status_code == 200
    assert "allowCredentials" not in response.json()["publicKey"]
