import hashlib
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import case
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import get_db
from app.models import AuthRateLimit


def _client_ip(request: Request) -> str:
    # Do not trust X-Forwarded-For unless a trusted-proxy policy is configured.
    return request.client.host if request.client is not None else "unknown"


def consume_ip_rate_limit(
    db: Session, *, client_ip: str, route: str, now: datetime | None = None
) -> tuple[int, int]:
    settings = get_settings()
    now = now or datetime.now(UTC)
    window_seconds = settings.auth_rate_limit_window_seconds
    window_epoch = int(now.timestamp()) // window_seconds * window_seconds
    window_start = datetime.fromtimestamp(window_epoch, UTC)
    key = hashlib.sha256(f"{client_ip}\0{route}".encode()).hexdigest()
    table = AuthRateLimit.__table__
    dialect = db.get_bind().dialect.name

    if dialect == "postgresql":
        statement = pg_insert(table)
    elif dialect == "sqlite":
        statement = sqlite_insert(table)
    else:
        raise RuntimeError("Rate limiting requires PostgreSQL or SQLite")

    statement = statement.values(
        bucket_key=key,
        window_start=window_start,
        request_count=1,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[table.c.bucket_key],
        set_={
            "window_start": statement.excluded.window_start,
            "request_count": case(
                (table.c.window_start == statement.excluded.window_start, table.c.request_count + 1),
                else_=1,
            ),
        },
    ).returning(table.c.request_count)

    count = db.execute(statement).scalar_one()
    db.commit()
    retry_after = max(1, window_seconds - (int(now.timestamp()) - window_epoch))
    return count, retry_after


def enforce_ip_rate_limit(
    request: Request, db: Session = Depends(get_db)
) -> None:
    settings = get_settings()
    count, retry_after = consume_ip_rate_limit(
        db,
        client_ip=_client_ip(request),
        route=request.url.path,
    )
    if count > settings.auth_rate_limit_max_requests:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication requests",
            headers={"Retry-After": str(retry_after)},
        )
