from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import User
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


def test_challenge_is_one_time_and_bound_to_telegram_context(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        passkeys,
        "get_settings",
        lambda: SimpleNamespace(webauthn_challenge_ttl=180),
    )
    user = make_user(db, "1001")
    challenge_id = passkeys._new_challenge(
        db, user, "authentication", b"test-challenge", "signed-telegram-init-data"
    )

    with pytest.raises(HTTPException) as wrong_context:
        passkeys._consume_challenge(
            db, challenge_id, user.id, "authentication", "different-init-data"
        )
    assert wrong_context.value.status_code == 400

    assert passkeys._consume_challenge(
        db, challenge_id, user.id, "authentication", "signed-telegram-init-data"
    ) == b"test-challenge"

    with pytest.raises(HTTPException) as replay:
        passkeys._consume_challenge(
            db, challenge_id, user.id, "authentication", "signed-telegram-init-data"
        )
    assert replay.value.status_code == 400


def test_challenge_is_bound_to_user_and_purpose(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        passkeys,
        "get_settings",
        lambda: SimpleNamespace(webauthn_challenge_ttl=180),
    )
    owner = make_user(db, "1001")
    other_user = make_user(db, "2002")
    challenge_id = passkeys._new_challenge(
        db, owner, "registration", b"register-challenge", "init-data"
    )

    with pytest.raises(HTTPException):
        passkeys._consume_challenge(db, challenge_id, other_user.id, "registration", "init-data")
    with pytest.raises(HTTPException):
        passkeys._consume_challenge(db, challenge_id, owner.id, "authentication", "init-data")

    assert passkeys._consume_challenge(
        db, challenge_id, owner.id, "registration", "init-data"
    ) == b"register-challenge"


def test_expired_challenge_is_rejected(db: Session) -> None:
    user = make_user(db, "1001")
    row = passkeys.WebAuthnChallenge(
        id="expired-challenge",
        user_id=user.id,
        purpose="authentication",
        challenge=b"expired",
        context_hash=passkeys.hashlib.sha256(b"init-data").hexdigest(),
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    db.add(row)
    db.commit()

    with pytest.raises(HTTPException) as error:
        passkeys._consume_challenge(
            db, "expired-challenge", user.id, "authentication", "init-data"
        )

    assert error.value.status_code == 400
