import hashlib
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from cryptography.fernet import Fernet
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from webauthn.helpers import bytes_to_base64url

from app.db import Base, get_db
from app.main import create_app
from app.models import AuthRateLimit, AuthSession, PasskeyCredential, RecoveryContact, User
from app.routers import recovery_contact
from app.services import recovery_contact_crypto


ORIGIN = "http://localhost:5173"
INIT_DATA = "signed-original-telegram-init-data"
SESSION_TOKEN = "test-session-token"


@pytest.fixture
def recovery_client(monkeypatch: pytest.MonkeyPatch) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
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
        recovery_contact_encryption_key=Fernet.generate_key().decode(),
        smtp_host="smtp.test",
        smtp_from_address="no-reply@example.test",
        smtp_starttls=True,
        smtp_ssl=False,
        smtp_timeout_seconds=3,
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.origins.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.rate_limit.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.sessions.get_settings", lambda: settings)
    monkeypatch.setattr("app.routers.recovery_contact.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.recovery_contact_crypto.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.routers.recovery_contact.verify_telegram_init_data",
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


def _seed_user(factory: sessionmaker[Session], credential_count: int = 2) -> None:
    with factory() as db:
        user = User(telegram_user_id="424242")
        db.add(user)
        db.flush()
        for index in range(credential_count):
            db.add(PasskeyCredential(
                user_id=user.id,
                credential_id=bytes_to_base64url(f"credential-{index}".encode()),
                public_key=b"test-public-key",
                sign_count=0,
            ))
        db.add(AuthSession(
            user_id=user.id,
            token_hash=hashlib.sha256(SESSION_TOKEN.encode()).hexdigest(),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ))
        db.commit()


def test_enrollment_requires_two_active_passkeys(recovery_client):
    client, factory = recovery_client
    _seed_user(factory, credential_count=1)
    client.cookies.set("shop_session", SESSION_TOKEN)
    response = client.post(
        "/auth/passkeys/recovery-contact/registration/options",
        headers={"Origin": ORIGIN, "X-Telegram-Init-Data": INIT_DATA},
    )
    assert response.status_code == 409
    assert "two active Passkeys" in response.json()["detail"]


def test_recovery_contact_enrollment_requires_session(recovery_client):
    client, factory = recovery_client
    _seed_user(factory, credential_count=2)
    response = client.post(
        "/auth/passkeys/recovery-contact/registration/options",
        headers={"Origin": ORIGIN, "X-Telegram-Init-Data": INIT_DATA},
    )
    assert response.status_code == 401


def test_contact_is_encrypted_and_only_verified_by_one_use_email_token(
    recovery_client, monkeypatch: pytest.MonkeyPatch
):
    client, factory = recovery_client
    _seed_user(factory, credential_count=2)
    client.cookies.set("shop_session", SESSION_TOKEN)
    sent = {}

    def fake_send_email(*, recipient: str, subject: str, text_body: str) -> None:
        sent["recipient"] = recipient
        sent["body"] = text_body

    monkeypatch.setattr(recovery_contact, "send_email", fake_send_email)
    monkeypatch.setattr(
        recovery_contact,
        "verify_authentication_response",
        lambda **kwargs: SimpleNamespace(
            new_sign_count=1,
            credential_device_type="single_device",
            credential_backed_up=False,
        ),
    )
    headers = {"Origin": ORIGIN, "X-Telegram-Init-Data": INIT_DATA}
    options = client.post(
        "/auth/passkeys/recovery-contact/registration/options",
        headers=headers,
    )
    assert options.status_code == 200
    with factory() as db:
        user = db.scalar(select(User).where(User.telegram_user_id == "424242"))
        db.add(RecoveryContact(
            user_id=user.id,
            encrypted_email=b"expired",
            email_digest="b" * 64,
            verification_token_hash=None,
            verification_expires_at=datetime.now(UTC) - timedelta(minutes=1),
        ))
        db.commit()
    credential_id = bytes_to_base64url(b"credential-0")
    verified = client.post(
        "/auth/passkeys/recovery-contact/registration/verify",
        headers=headers,
        json={
            "challenge_id": options.json()["challenge_id"],
            "email": "Contact@Example.com",
            "credential": {"id": credential_id},
        },
    )
    assert verified.status_code == 200
    assert verified.json() == {"verification_sent": True, "expires_in": 900}
    assert sent["recipient"] == "Contact@Example.com"

    with factory() as db:
        contact = db.scalar(select(RecoveryContact))
        assert contact is not None
        assert b"Contact@Example.com" not in contact.encrypted_email
        assert contact.email_digest == recovery_contact_crypto.contact_digest("Contact@Example.com")
        assert contact.verification_token_hash is not None
        assert db.scalars(select(AuthRateLimit)).all()

    token = sent["body"].splitlines()[2]
    confirmed = client.post(
        "/auth/passkeys/recovery-contact/registration/confirm",
        headers={"Origin": ORIGIN},
        json={"token": token},
    )
    assert confirmed.status_code == 200
    assert confirmed.json() == {"verified": True}
    replay = client.post(
        "/auth/passkeys/recovery-contact/registration/confirm",
        headers={"Origin": ORIGIN},
        json={"token": token},
    )
    assert replay.status_code == 400

    status_response = client.get(
        "/auth/passkeys/recovery-contact",
        headers=headers,
    )
    assert status_response.status_code == 200
    assert status_response.json() == {
        "configured": True,
        "verified": True,
        "verification_pending": False,
    }


def test_expired_contact_can_be_replaced_with_sqlite_timestamp(recovery_client, monkeypatch):
    client, factory = recovery_client
    _seed_user(factory, credential_count=2)
    client.cookies.set("shop_session", SESSION_TOKEN)
    with factory() as db:
        user = db.scalar(select(User).where(User.telegram_user_id == "424242"))
        db.add(RecoveryContact(
            user_id=user.id,
            encrypted_email=b"expired",
            email_digest="a" * 64,
            verification_token_hash=None,
            verification_expires_at=datetime.now(UTC) - timedelta(minutes=1),
        ))
        db.commit()
    headers = {"Origin": ORIGIN, "X-Telegram-Init-Data": INIT_DATA}
    response = client.post(
        "/auth/passkeys/recovery-contact/registration/options",
        headers=headers,
    )
    assert response.status_code == 200
