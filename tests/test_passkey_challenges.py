from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import AuthSession, User
from starlette.requests import Request
from starlette.responses import Response
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



def request_with_cookie(cookie: str) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [(b"cookie", cookie.encode())],
            "client": ("test", 123),
            "server": ("test", 80),
        }
    )


def test_successful_authentication_rotates_presented_session(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        passkeys,
        "get_settings",
        lambda: SimpleNamespace(
            auth_cookie_name="shop_session", auth_session_ttl=3600, app_env="development"
        ),
    )
    user = make_user(db, "1001")
    old_token = "previous-session-token"
    old_session = AuthSession(
        user_id=user.id,
        token_hash=passkeys.hashlib.sha256(old_token.encode()).hexdigest(),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(old_session)
    db.commit()

    response = Response()
    passkeys._session_cookie(db, user, response, request_with_cookie(f"shop_session={old_token}"))

    db.refresh(old_session)
    active_sessions = db.scalars(
        select(AuthSession).where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
        )
    ).all()
    assert old_session.revoked_at is not None
    assert len(active_sessions) == 1
    assert "shop_session=" in response.headers["set-cookie"]
    assert old_token not in response.headers["set-cookie"]


def test_passkey_revocation_invalidates_all_active_sessions(db: Session) -> None:
    user = make_user(db, "1001")
    now = datetime.now(UTC)
    active = [
        AuthSession(
            user_id=user.id,
            token_hash=passkeys.hashlib.sha256(f"token-{index}".encode()).hexdigest(),
            expires_at=now + timedelta(hours=1),
        )
        for index in range(2)
    ]
    already_revoked = AuthSession(
        user_id=user.id,
        token_hash=passkeys.hashlib.sha256(b"revoked-token").hexdigest(),
        expires_at=now + timedelta(hours=1),
        revoked_at=now - timedelta(minutes=1),
    )
    db.add_all([*active, already_revoked])
    db.commit()

    count = passkeys._revoke_user_sessions(db, user.id, now)
    db.commit()

    assert count == 2
    assert all(session.revoked_at == now for session in active)
    assert already_revoked.revoked_at == now - timedelta(minutes=1)
