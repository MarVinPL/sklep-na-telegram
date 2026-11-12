from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import PasskeyCredential, PasskeyHandoff, User, WebAuthnChallenge
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


def test_handoff_token_is_hashed_and_can_be_consumed_only_once(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        passkeys,
        "get_settings",
        lambda: SimpleNamespace(passkey_handoff_ttl_seconds=120),
    )
    user = make_user(db, "handoff-owner")
    raw_token = passkeys._new_handoff(db, user)

    stored = db.scalar(select(PasskeyHandoff))
    assert stored is not None
    assert stored.token_hash != raw_token
    assert len(stored.token_hash) == 64
    assert passkeys.hashlib.sha256(raw_token.encode()).hexdigest() == stored.token_hash
    assert stored.expires_at.replace(tzinfo=UTC) > datetime.now(UTC)

    assert passkeys._consume_handoff(db, raw_token) == user.id
    with pytest.raises(HTTPException) as replay:
        passkeys._consume_handoff(db, raw_token)
    assert replay.value.status_code == 400


def test_handoff_token_is_bound_to_purpose_and_expiry(db: Session) -> None:
    user = make_user(db, "handoff-expired")
    expired = PasskeyHandoff(
        user_id=user.id,
        purpose="authentication",
        token_hash=passkeys.hashlib.sha256(b"expired-token").hexdigest(),
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    wrong_purpose = PasskeyHandoff(
        user_id=user.id,
        purpose="registration",
        token_hash=passkeys.hashlib.sha256(b"wrong-purpose-token").hexdigest(),
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    db.add_all([expired, wrong_purpose])
    db.commit()

    for token in ("expired-token", "wrong-purpose-token"):
        with pytest.raises(HTTPException) as error:
            passkeys._consume_handoff(db, token, purpose="authentication")
        assert error.value.status_code == 400


def test_handoff_challenge_is_consumed_once(db: Session) -> None:
    user = make_user(db, "handoff-challenge")
    challenge = WebAuthnChallenge(
        id="handoff-challenge-once",
        user_id=user.id,
        purpose="handoff_authentication",
        challenge=b"challenge-bytes",
        context_hash=passkeys.hashlib.sha256(b"handoff-token").hexdigest(),
        expires_at=datetime.now(UTC) + timedelta(minutes=2),
    )
    db.add(challenge)
    db.commit()

    assert passkeys._consume_handoff_challenge(db, challenge.id) == (
        user.id,
        b"challenge-bytes",
    )
    with pytest.raises(HTTPException) as replay:
        passkeys._consume_handoff_challenge(db, challenge.id)
    assert replay.value.status_code == 400


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
    db.add(PasskeyCredential(
        user_id=owner_with_passkey.id,
        credential_id="existing-credential",
        public_key=b"public-key",
        sign_count=0,
    ))
    db.commit()

    without = passkeys.authentication_options("without-passkey", db)["publicKey"]
    with_existing = passkeys.authentication_options("with-passkey", db)["publicKey"]

    assert not without.get("allowCredentials")
    assert not with_existing.get("allowCredentials")
    assert without["userVerification"] == "required"
    assert with_existing["userVerification"] == "required"
