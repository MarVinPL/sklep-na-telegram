from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import PasskeyHandoff, User
from app.security.passkey_handoff_maintenance import cleanup_expired_passkey_handoffs


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


def add_handoff(
    db: Session,
    user: User,
    *,
    token: str,
    expires_at: datetime,
    consumed_at: datetime | None = None,
) -> PasskeyHandoff:
    row = PasskeyHandoff(
        user_id=user.id,
        purpose="authentication",
        token_hash=token * 64,
        expires_at=expires_at,
        consumed_at=consumed_at,
    )
    db.add(row)
    db.flush()
    return row


def test_cleanup_removes_only_records_past_retention(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(
        "app.security.passkey_handoff_maintenance.get_settings",
        lambda: SimpleNamespace(passkey_handoff_retention_seconds=86400),
    )
    user = User(telegram_user_id="handoff-retention-user")
    db.add(user)
    db.flush()

    consumed_old = add_handoff(
        db, user, token="a", expires_at=now - timedelta(days=2),
        consumed_at=now - timedelta(days=2),
    )
    expired_old = add_handoff(
        db, user, token="b", expires_at=now - timedelta(days=2)
    )
    consumed_recent = add_handoff(
        db, user, token="c", expires_at=now - timedelta(days=2),
        consumed_at=now - timedelta(hours=1),
    )
    expired_recent = add_handoff(
        db, user, token="d", expires_at=now - timedelta(hours=1)
    )
    still_valid = add_handoff(
        db, user, token="e", expires_at=now + timedelta(minutes=1)
    )
    db.commit()

    deleted = cleanup_expired_passkey_handoffs(db, now=now)

    assert deleted == 2
    remaining_ids = set(db.scalars(select(PasskeyHandoff.id)).all())
    assert remaining_ids == {
        consumed_recent.id,
        expired_recent.id,
        still_valid.id,
    }


def test_cleanup_rejects_negative_retention(db: Session) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        cleanup_expired_passkey_handoffs(db, retention_seconds=-1)
