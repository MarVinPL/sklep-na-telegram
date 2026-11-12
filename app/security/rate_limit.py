import hashlib
import hmac
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import case
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import get_db
from app.models import AuthRateLimit
from app.security.telegram import verify_telegram_init_data


def _client_ip(request: Request) -> str:
    # Do not trust X-Forwarded-For unless a trusted-proxy policy is configured.
    return request.client.host if request.client is not None else "unknown"


def _consume_bucket(
    db: Session, *, bucket_key: str, window_seconds: int, now: datetime | None = None
) -> tuple[int, int]:
    now = now or datetime.now(UTC)
    window_epoch = int(now.timestamp()) // window_seconds * window_seconds
    window_start = datetime.fromtimestamp(window_epoch, UTC)
    table = AuthRateLimit.__table__
    dialect = db.get_bind().dialect.name

    if dialect == "postgresql":
        statement = pg_insert(table)
    elif dialect == "sqlite":
        statement = sqlite_insert(table)
    else:
        raise RuntimeError("Rate limiting requires PostgreSQL or SQLite")

    statement = statement.values(
        bucket_key=bucket_key,
        window_start=window_start,
        request_count=1,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[table.c.bucket_key],
        set_={
            "window_start": statement.excluded.window_start,
            "request_count": case(
                (
                    table.c.window_start == statement.excluded.window_start,
                    table.c.request_count + 1,
                ),
                else_=1,
            ),
        },
    ).returning(table.c.request_count)

    count = db.execute(statement).scalar_one()
    db.commit()
    retry_after = max(1, window_seconds - (int(now.timestamp()) - window_epoch))
    return count, retry_after


def consume_ip_rate_limit(
    db: Session, *, client_ip: str, now: datetime | None = None
) -> tuple[int, int]:
    settings = get_settings()
    key = hashlib.sha256(f"ip\0{client_ip}".encode()).hexdigest()
    return _consume_bucket(
        db, bucket_key=key, window_seconds=settings.auth_rate_limit_window_seconds, now=now
    )


def consume_account_rate_limit(
    db: Session, *, telegram_user_id: str, now: datetime | None = None
) -> tuple[int, int]:
    settings = get_settings()
    # HMAC prevents a database reader from reversing Telegram numeric IDs by enumeration.
    material = f"account\0{telegram_user_id}".encode()
    key = hmac.new(
        settings.telegram_bot_token.encode(), material, hashlib.sha256
    ).hexdigest()
    return _consume_bucket(
        db,
        bucket_key=key,
        window_seconds=settings.auth_rate_limit_window_seconds,
        now=now,
    )


def enforce_ip_rate_limit(request: Request, db: Session = Depends(get_db)) -> None:
    settings = get_settings()
    ip_count, ip_retry_after = consume_ip_rate_limit(
        db, client_ip=_client_ip(request)
    )
    if ip_count > settings.auth_rate_limit_max_requests:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication requests",
            headers={"Retry-After": str(ip_retry_after)},
        )

    # Invalid/missing initData is still covered by the IP bucket. Only a verified
    # Telegram identity is eligible for the account bucket.
    raw_init_data = request.headers.get("X-Telegram-Init-Data")
    if not raw_init_data:
        return
    try:
        identity = verify_telegram_init_data(raw_init_data)
    except HTTPException:
        return

    account_count, account_retry_after = consume_account_rate_limit(
        db,
        telegram_user_id=identity["telegram_user_id"],
    )
    if account_count > settings.auth_rate_limit_account_max_requests:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication requests",
            headers={"Retry-After": str(account_retry_after)},
        )
