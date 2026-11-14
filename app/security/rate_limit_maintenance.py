from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import AuthRateLimit


def cleanup_expired_rate_limit_buckets(
    db: Session,
    *,
    retention_seconds: int | None = None,
    now: datetime | None = None,
) -> int:
    settings = get_settings()
    retention = (
        settings.auth_rate_limit_retention_seconds
        if retention_seconds is None
        else retention_seconds
    )
    if retention < 1:
        raise ValueError("retention_seconds must be positive")

    cutoff = (now or datetime.now(UTC)) - timedelta(seconds=retention)
    result = db.execute(
        delete(AuthRateLimit).where(AuthRateLimit.window_start < cutoff)
    )
    db.commit()
    return result.rowcount or 0


def main() -> None:
    with SessionLocal() as db:
        deleted = cleanup_expired_rate_limit_buckets(db)
    print(f"Removed {deleted} expired authentication rate-limit bucket(s).")


if __name__ == "__main__":
    main()
