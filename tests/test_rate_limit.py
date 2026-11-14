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


def test_ip_rate_limit_isolated_by_endpoint_scope(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.security.rate_limit.get_settings", _settings)
    now = datetime(2026, 11, 12, 12, 0, 15, tzinfo=UTC)

    assert consume_ip_rate_limit(
        db, client_ip="192.0.2.10", scope="/auth/passkeys/login", now=now
    )[0] == 1
    assert consume_ip_rate_limit(
        db, client_ip="192.0.2.10", scope="/auth/passkeys/logout", now=now
    )[0] == 1
    assert consume_ip_rate_limit(
        db, client_ip="192.0.2.10", scope="/auth/passkeys/login", now=now
    )[0] == 2


def test_account_limit_isolated_by_telegram_account_and_scope(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.security.rate_limit.get_settings", _settings)
    now = datetime(2026, 11, 12, 12, 0, 15, tzinfo=UTC)

    assert consume_account_rate_limit(
        db, telegram_user_id="10001", scope="/login", now=now
    )[0] == 1
    assert consume_account_rate_limit(
        db, telegram_user_id="10001", scope="/login", now=now
    )[0] == 2
    assert consume_account_rate_limit(
        db, telegram_user_id="10002", scope="/login", now=now
    )[0] == 1
    assert consume_account_rate_limit(
        db, telegram_user_id="10001", scope="/logout", now=now
    )[0] == 1

    rows = db.scalars(select(AuthRateLimit)).all()
    assert len(rows) == 3
    assert all(
        "10001" not in row.bucket_key and "10002" not in row.bucket_key
        for row in rows
    )


def _request(path: str, init_data: str | None = None):
    headers = []
    if init_data is not None:
        headers.append((b"x-telegram-init-data", init_data.encode()))
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": headers,
            "query_string": b"",
            "server": ("shop.example.com", 443),
            "client": ("192.0.2.10", 12345),
            "scheme": "https",
        }
    )


def test_ip_limit_returns_429_and_retry_after(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import HTTPException

    from app.security import rate_limit

    monkeypatch.setattr(
        rate_limit,
        "get_settings",
        lambda: SimpleNamespace(
            auth_rate_limit_max_requests=1,
            auth_rate_limit_account_max_requests=6,
            auth_rate_limit_window_seconds=60,
            telegram_bot_token="test-bot-token",
        ),
    )
    monkeypatch.setattr(rate_limit, "consume_ip_rate_limit", lambda *args, **kwargs: (2, 23))

    with pytest.raises(HTTPException) as error:
        rate_limit.enforce_ip_rate_limit(_request("/auth/passkeys/login"), db)
    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "23"


def test_account_limit_applies_only_after_telegram_validation(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import HTTPException

    from app.security import rate_limit

    monkeypatch.setattr(
        rate_limit,
        "get_settings",
        lambda: SimpleNamespace(
            auth_rate_limit_max_requests=10,
            auth_rate_limit_account_max_requests=1,
            auth_rate_limit_window_seconds=60,
            telegram_bot_token="test-bot-token",
        ),
    )
    monkeypatch.setattr(rate_limit, "consume_ip_rate_limit", lambda *args, **kwargs: (1, 60))
    monkeypatch.setattr(
        rate_limit,
        "verify_telegram_init_data",
        lambda raw: {"telegram_user_id": "12345"},
    )
    monkeypatch.setattr(
        rate_limit,
        "consume_account_rate_limit",
        lambda *args, **kwargs: (2, 17),
    )

    with pytest.raises(HTTPException) as error:
        rate_limit.enforce_ip_rate_limit(
            _request("/auth/passkeys/login", "signed-init-data"), db
        )
    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "17"


def test_invalid_telegram_context_is_still_covered_by_ip_bucket(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import HTTPException

    from app.security import rate_limit

    monkeypatch.setattr(
        rate_limit,
        "get_settings",
        lambda: SimpleNamespace(
            auth_rate_limit_max_requests=10,
            auth_rate_limit_account_max_requests=1,
            auth_rate_limit_window_seconds=60,
            telegram_bot_token="test-bot-token",
        ),
    )
    monkeypatch.setattr(rate_limit, "consume_ip_rate_limit", lambda *args, **kwargs: (1, 60))
    monkeypatch.setattr(
        rate_limit,
        "verify_telegram_init_data",
        lambda raw: (_ for _ in ()).throw(HTTPException(status_code=401)),
    )
    monkeypatch.setattr(
        rate_limit,
        "consume_account_rate_limit",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("account bucket must not run")),
    )

    assert rate_limit.enforce_ip_rate_limit(
        _request("/auth/passkeys/login", "invalid-init-data"), db
    ) is None
