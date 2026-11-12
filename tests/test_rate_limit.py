from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import AuthRateLimit
from app.security.rate_limit import consume_ip_rate_limit


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


def test_rate_limit_increments_atomically_in_current_window(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.security.rate_limit.get_settings",
        lambda: SimpleNamespace(auth_rate_limit_window_seconds=60),
    )
    now = datetime(2026, 11, 12, 12, 0, 15, tzinfo=UTC)

    assert consume_ip_rate_limit(db, client_ip="192.0.2.10", route="/auth/passkeys/login", now=now) == (1, 45)
    assert consume_ip_rate_limit(db, client_ip="192.0.2.10", route="/auth/passkeys/login", now=now) == (2, 45)
    assert consume_ip_rate_limit(db, client_ip="192.0.2.10", route="/auth/passkeys/login", now=now) == (3, 45)


def test_rate_limit_resets_after_window_and_isolated_by_route_and_ip(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.security.rate_limit.get_settings",
        lambda: SimpleNamespace(auth_rate_limit_window_seconds=60),
    )
    now = datetime(2026, 11, 12, 12, 0, 15, tzinfo=UTC)
    later = now + timedelta(minutes=1)

    assert consume_ip_rate_limit(db, client_ip="192.0.2.10", route="/login", now=now)[0] == 1
    assert consume_ip_rate_limit(db, client_ip="192.0.2.10", route="/login", now=later)[0] == 1
    assert consume_ip_rate_limit(db, client_ip="192.0.2.11", route="/login", now=now)[0] == 1
    assert consume_ip_rate_limit(db, client_ip="192.0.2.10", route="/logout", now=now)[0] == 1

    rows = db.scalars(select(AuthRateLimit)).all()
    assert len(rows) == 4
