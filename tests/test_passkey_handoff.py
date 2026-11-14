import hashlib
import logging
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import AuthSession, PasskeyCredential, PasskeyHandoff, User, WebAuthnChallenge
from app.routers import passkeys


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


def make_user(db: Session, telegram_user_id: str) -> User:
    user = User(telegram_user_id=telegram_user_id)
    db.add(user)
    db.flush()
    return user


def test_handoff_token_is_hashed_context_bound_and_single_use(
    db: Session, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=passkeys.__name__)
    monkeypatch.setattr(
        passkeys,
        "get_settings",
        lambda: SimpleNamespace(passkey_handoff_ttl_seconds=120),
    )
    user = make_user(db, "handoff-owner")
    init_data = "signed-telegram-init-data"
    raw_token = passkeys._new_handoff(db, user, init_data)

    stored = db.scalar(select(PasskeyHandoff))
    assert stored is not None
    assert stored.token_hash == hashlib.sha256(raw_token.encode()).hexdigest()
    assert stored.token_hash != raw_token
    assert stored.context_hash == hashlib.sha256(init_data.encode()).hexdigest()
    assert len(stored.token_hash) == 64
    assert db.scalars(select(AuthSession)).all() == []

    handoff_id, user_id, context_hash, expires_at = passkeys._consume_handoff(db, raw_token)
    assert handoff_id == stored.id
    assert user_id == user.id
    assert context_hash == stored.context_hash
    assert expires_at == stored.expires_at
    db.commit()

    with pytest.raises(HTTPException) as replay:
        passkeys._consume_handoff(db, raw_token)
    assert replay.value.status_code == 400
    assert raw_token not in caplog.text
    assert init_data not in caplog.text


def test_handoff_token_rejects_expiry_and_wrong_purpose(db: Session) -> None:
    user = make_user(db, "handoff-expired")
    expired_token = "expired-handoff-token"
    wrong_purpose_token = "wrong-purpose-handoff-token"
    db.add_all(
        [
            PasskeyHandoff(
                user_id=user.id,
                purpose="authentication",
                token_hash=hashlib.sha256(expired_token.encode()).hexdigest(),
                context_hash=hashlib.sha256(b"init-data").hexdigest(),
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            ),
            PasskeyHandoff(
                user_id=user.id,
                purpose="registration",
                token_hash=hashlib.sha256(wrong_purpose_token.encode()).hexdigest(),
                context_hash=hashlib.sha256(b"init-data").hexdigest(),
                expires_at=datetime.now(UTC) + timedelta(minutes=1),
            ),
        ]
    )
    db.commit()

    for token in (expired_token, wrong_purpose_token):
        with pytest.raises(HTTPException) as error:
            passkeys._consume_handoff(db, token)
        assert error.value.status_code == 400


def test_handoff_challenge_is_bound_to_ticket_and_consumed_once(db: Session) -> None:
    user = make_user(db, "handoff-challenge")
    init_data = "original-telegram-context"
    raw_token = "handoff-token-for-challenge"
    context_hash = hashlib.sha256(init_data.encode()).hexdigest()
    handoff = PasskeyHandoff(
        user_id=user.id,
        purpose="authentication",
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        context_hash=context_hash,
        expires_at=datetime.now(UTC) + timedelta(minutes=2),
        consumed_at=datetime.now(UTC),
    )
    challenge = WebAuthnChallenge(
        id="handoff-challenge-once",
        user_id=user.id,
        purpose="handoff_authentication",
        challenge=b"challenge-bytes",
        context_hash=context_hash,
        expires_at=datetime.now(UTC) + timedelta(minutes=2),
    )
    db.add_all([handoff, challenge])
    db.commit()

    handoff_id, user_id, challenge_bytes = passkeys._consume_handoff_challenge(
        db, challenge.id, raw_token
    )
    assert handoff_id == handoff.id
    assert user_id == user.id
    assert challenge_bytes == b"challenge-bytes"

    with pytest.raises(HTTPException):
        passkeys._consume_handoff_challenge(db, challenge.id, raw_token)
    with pytest.raises(HTTPException):
        passkeys._consume_handoff_challenge(db, "handoff-challenge-once", "another-token")


def test_handoff_options_do_not_create_a_session(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = make_user(db, "handoff-options")
    init_data = "telegram-context-options"
    raw_token = "o" * 43
    context_hash = hashlib.sha256(init_data.encode()).hexdigest()
    db.add(
        PasskeyHandoff(
            user_id=user.id,
            purpose="authentication",
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
            context_hash=context_hash,
            expires_at=datetime.now(UTC) + timedelta(minutes=2),
        )
    )
    db.commit()
    monkeypatch.setattr(
        passkeys,
        "get_settings",
        lambda: SimpleNamespace(webauthn_rp_id="example.com", webauthn_challenge_ttl=180),
    )

    result = passkeys.handoff_authentication_options(
        passkeys.HandoffOptionsRequest(handoff_token=raw_token), db
    )

    challenge = db.get(WebAuthnChallenge, result["challenge_id"])
    assert challenge is not None
    assert challenge.user_id == user.id
    assert challenge.context_hash == context_hash
    assert challenge.purpose == "handoff_authentication"
    assert db.scalars(select(AuthSession)).all() == []


def test_handoff_verification_marks_ticket_ready_without_creating_session(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = make_user(db, "handoff-verify")
    init_data = "telegram-context-verify"
    raw_token = "v" * 43
    context_hash = hashlib.sha256(init_data.encode()).hexdigest()
    handoff = PasskeyHandoff(
        user_id=user.id,
        purpose="authentication",
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        context_hash=context_hash,
        expires_at=datetime.now(UTC) + timedelta(minutes=2),
        consumed_at=datetime.now(UTC),
    )
    credential = PasskeyCredential(
        user_id=user.id,
        credential_id="discoverable-credential",
        public_key=b"public-key",
        sign_count=0,
    )
    challenge = WebAuthnChallenge(
        id="handoff-verify-challenge",
        user_id=user.id,
        purpose="handoff_authentication",
        challenge=b"challenge-bytes",
        context_hash=context_hash,
        expires_at=datetime.now(UTC) + timedelta(minutes=2),
    )
    db.add_all([handoff, credential, challenge])
    db.commit()

    monkeypatch.setattr(
        passkeys,
        "get_settings",
        lambda: SimpleNamespace(
            webauthn_rp_id="example.com",
            webauthn_origin="https://shop.example.com",
        ),
    )
    monkeypatch.setattr(
        passkeys,
        "verify_authentication_response",
        lambda **kwargs: SimpleNamespace(
            new_sign_count=1,
            credential_device_type="single_device",
            credential_backed_up=False,
        ),
    )

    result = passkeys.handoff_authentication_verify(
        passkeys.HandoffVerifyRequest(
            handoff_token=raw_token,
            challenge_id=challenge.id,
            credential={"id": credential.credential_id},
        ),
        db,
    )

    db.refresh(handoff)
    assert result == {"verified": True}
    assert handoff.verified_at is not None
    assert handoff.redeemed_at is None
    assert db.scalars(select(AuthSession)).all() == []


def test_redeem_handoff_requires_original_telegram_context_and_creates_session(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = make_user(db, "handoff-redeem")
    init_data = "original-telegram-init-data"
    raw_token = "r" * 43
    handoff = PasskeyHandoff(
        user_id=user.id,
        purpose="authentication",
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        context_hash=hashlib.sha256(init_data.encode()).hexdigest(),
        expires_at=datetime.now(UTC) + timedelta(minutes=2),
        consumed_at=datetime.now(UTC),
        verified_at=datetime.now(UTC),
    )
    db.add(handoff)
    db.commit()
    monkeypatch.setattr(
        passkeys,
        "verify_telegram_init_data",
        lambda raw: {"telegram_user_id": "handoff-redeem"},
    )
    monkeypatch.setattr(
        passkeys,
        "get_settings",
        lambda: SimpleNamespace(
            app_env="production",
            auth_cookie_name="shop_session",
            auth_session_ttl=3600,
        ),
    )

    response = Response()
    result = passkeys.redeem_handoff(
        passkeys.HandoffOptionsRequest(handoff_token=raw_token),
        response,
        init_data,
        db,
    )

    db.refresh(handoff)
    sessions = db.scalars(select(AuthSession).where(AuthSession.user_id == user.id)).all()
    assert result == {"authenticated": True}
    assert handoff.redeemed_at is not None
    assert len(sessions) == 1
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "secure" in response.headers["set-cookie"].lower()


def test_redeem_handoff_does_not_create_session_before_verification(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = make_user(db, "handoff-pending")
    init_data = "telegram-context-pending"
    raw_token = "p" * 43
    handoff = PasskeyHandoff(
        user_id=user.id,
        purpose="authentication",
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        context_hash=hashlib.sha256(init_data.encode()).hexdigest(),
        expires_at=datetime.now(UTC) + timedelta(minutes=2),
        consumed_at=datetime.now(UTC),
    )
    db.add(handoff)
    db.commit()
    monkeypatch.setattr(
        passkeys,
        "verify_telegram_init_data",
        lambda raw: {"telegram_user_id": "handoff-pending"},
    )

    result = passkeys.redeem_handoff(
        passkeys.HandoffOptionsRequest(handoff_token=raw_token),
        Response(),
        init_data,
        db,
    )

    assert result == {"authenticated": False}
    assert db.scalars(select(AuthSession)).all() == []


def test_redeem_handoff_rejects_different_telegram_context(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = make_user(db, "handoff-context-mismatch")
    raw_token = "c" * 43
    db.add(
        PasskeyHandoff(
            user_id=user.id,
            purpose="authentication",
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
            context_hash=hashlib.sha256(b"original-init-data").hexdigest(),
            expires_at=datetime.now(UTC) + timedelta(minutes=2),
            consumed_at=datetime.now(UTC),
            verified_at=datetime.now(UTC),
        )
    )
    db.commit()
    monkeypatch.setattr(
        passkeys,
        "verify_telegram_init_data",
        lambda raw: {"telegram_user_id": "handoff-context-mismatch"},
    )

    with pytest.raises(HTTPException) as error:
        passkeys.redeem_handoff(
            passkeys.HandoffOptionsRequest(handoff_token=raw_token),
            Response(),
            "different-init-data",
            db,
        )
    assert error.value.status_code == 400


def test_authentication_options_do_not_disclose_credential_presence_or_count(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        passkeys,
        "get_settings",
        lambda: SimpleNamespace(
            webauthn_rp_id="example.com",
            webauthn_challenge_ttl=180,
        ),
    )
    monkeypatch.setattr(
        passkeys,
        "verify_telegram_init_data",
        lambda raw: {"telegram_user_id": raw},
    )
    make_user(db, "without-passkey")
    owner_with_passkey = make_user(db, "with-passkey")
    db.add(
        PasskeyCredential(
            user_id=owner_with_passkey.id,
            credential_id="existing-credential",
            public_key=b"public-key",
            sign_count=0,
        )
    )
    db.commit()

    without = passkeys.authentication_options("without-passkey", db)["publicKey"]
    with_existing = passkeys.authentication_options("with-passkey", db)["publicKey"]

    assert not without.get("allowCredentials")
    assert not with_existing.get("allowCredentials")
    assert without["userVerification"] == "required"
    assert with_existing["userVerification"] == "required"


def test_failed_handoff_passkey_never_creates_a_session(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = make_user(db, "handoff-failed-auth")
    raw_token = "f" * 43
    context_hash = hashlib.sha256(b"failed-auth-context").hexdigest()
    handoff = PasskeyHandoff(
        user_id=user.id,
        purpose="authentication",
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        context_hash=context_hash,
        expires_at=datetime.now(UTC) + timedelta(minutes=2),
        consumed_at=datetime.now(UTC),
    )
    credential = PasskeyCredential(
        user_id=user.id,
        credential_id="failed-auth-credential",
        public_key=b"public-key",
        sign_count=0,
    )
    challenge = WebAuthnChallenge(
        id="handoff-failed-auth-challenge",
        user_id=user.id,
        purpose="handoff_authentication",
        challenge=b"challenge-bytes",
        context_hash=context_hash,
        expires_at=datetime.now(UTC) + timedelta(minutes=2),
    )
    db.add_all([handoff, credential, challenge])
    db.commit()
    monkeypatch.setattr(
        passkeys,
        "get_settings",
        lambda: SimpleNamespace(
            webauthn_rp_id="example.com",
            webauthn_origin="https://shop.example.com",
        ),
    )
    monkeypatch.setattr(
        passkeys,
        "verify_authentication_response",
        lambda **kwargs: (_ for _ in ()).throw(ValueError("invalid signature")),
    )

    with pytest.raises(HTTPException) as error:
        passkeys.handoff_authentication_verify(
            passkeys.HandoffVerifyRequest(
                handoff_token=raw_token,
                challenge_id=challenge.id,
                credential={"id": credential.credential_id},
            ),
            db,
        )

    assert error.value.status_code == 401
    db.refresh(handoff)
    assert handoff.verified_at is None
    assert db.scalars(select(AuthSession)).all() == []
