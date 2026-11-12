from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import AuthRateLimit
from app.security.rate_limit import consume_account_rate_limit, consume_ip_rate_limit


@pytest.fixture
def db():
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


def _settings():
    return SimpleNamespace(
        auth_rate_limit_window_seconds=60,
        telegram_bot_token="test-bot-token",
    )


def test_ip_rate_limit_increments_in_current_window(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.security.rate_limit.get_settings", _settings)
    now = datetime(2026, 11, 12, 12, 0, 15, tzinfo=UTC)

    assert consume_ip_rate_limit(db, client_ip="192.0.2.10", now=now) == (1, 45)
    assert consume_ip_rate_limit(db, client_ip="192.0.2.10", now=now) == (2, 45)
    assert consume_ip_rate_limit(db, client_ip="192.0.2.10", now=now) == (3, 45)


def test_ip_rate_limit_resets_and_isolated_by_ip(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.security.rate_limit.get_settings", _settings)
    now = datetime(2026, 11, 12, 12, 0, 15, tzinfo=UTC)
    later = now + timedelta(minutes=1)

    assert consume_ip_rate_limit(db, client_ip="192.0.2.10", now=now)[0] == 1
    assert consume_ip_rate_limit(db, client_ip="192.0.2.10", now=later)[0] == 1
    assert consume_ip_rate_limit(db, client_ip="192.0.2.11", now=now)[0] == 1
    assert consume_ip_rate_limit(db, client_ip="192.0.2.10", now=now)[0] == 1


def test_account_limit_isolated_by_telegram_account(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.security.rate_limit.get_settings", _settings)
    now = datetime(2026, 11, 12, 12, 0, 15, tzinfo=UTC)

    assert consume_account_rate_limit(
        db, telegram_user_id="10001", now=now
    )[0] == 1
    assert consume_account_rate_limit(
        db, telegram_user_id="10001", now=now
    )[0] == 2
    assert consume_account_rate_limit(
        db, telegram_user_id="10002", now=now
    )[0] == 1
    assert consume_account_rate_limit(
        db, telegram_user_id="10001", now=now
    )[0] == 3

    rows = db.scalars(select(AuthRateLimit)).all()
    assert len(rows) == 2
    assert all(
        "10001" not in row.bucket_key and "10002" not in row.bucket_key
        for row in rows
    )
