from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, or_
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import PasskeyHandoff


def cleanup_expired_passkey_handoffs(
    db: Session,
    *,
    retention_seconds: int | None = None,
    now: datetime | None = None,
) -> int:
    """Delete handoff rows only after their consumed/expiry time plus retention."""
    settings = get_settings()
    retention = (
        retention_seconds
        if retention_seconds is not None
        else settings.passkey_handoff_retention_seconds
    )
    if retention < 0:
        raise ValueError("retention_seconds must be non-negative")

    current_time = now or datetime.now(UTC)
    cutoff = current_time - timedelta(seconds=retention)
    statement = delete(PasskeyHandoff).where(
        or_(
            PasskeyHandoff.consumed_at < cutoff,
            and_(
                PasskeyHandoff.consumed_at.is_(None),
                PasskeyHandoff.expires_at < cutoff,
            ),
        )
    )
    result = db.execute(statement)
    db.commit()
    return int(result.rowcount or 0)


def main() -> None:
    with SessionLocal() as db:
        deleted = cleanup_expired_passkey_handoffs(db)
    print(f"Deleted {deleted} expired/consumed Passkey handoff record(s).")


if __name__ == "__main__":
    main()
