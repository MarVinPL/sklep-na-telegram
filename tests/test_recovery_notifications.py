from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import NotificationOutbox, RecoveryCase, User
from app.services import recovery_notifications as notifications


def _database():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine


def _configure_crypto(monkeypatch) -> None:
    fernet = Fernet(Fernet.generate_key())
    monkeypatch.setattr(notifications, "encrypt_payload", lambda value: fernet.encrypt(value.encode()))


def _case(db: Session, status: str = "awaiting_notification_delivery") -> RecoveryCase:
    user = User(telegram_user_id="123456")
    db.add(user)
    db.flush()
    case = RecoveryCase(
        id="7b4b1d6e-9d6f-4e91-8c27-9b35b8f53e2a",
        user_id=user.id,
        status=status,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(case)
    db.flush()
    return case


def test_outbox_is_idempotent_and_payload_is_encrypted(monkeypatch):
    _configure_crypto(monkeypatch)
    engine = _database()
    with Session(engine) as db:
        user = User(telegram_user_id="123456")
        db.add(user)
        db.flush()
        notifications.queue_event(
            db,
            user_id=user.id,
            event_key="case-1:case_started",
            event_type="recovery_case_started",
            email_subject="Recovery",
            email_body="secret-token-value",
            telegram_body="Security notice",
        )
        db.flush()
        notifications.queue_event(
            db,
            user_id=user.id,
            event_key="case-1:case_started",
            event_type="recovery_case_started",
            email_subject="Recovery",
            email_body="different duplicate payload",
            telegram_body="Security notice",
        )
        rows = db.scalars(select(NotificationOutbox)).all()
        assert len(rows) == 2
        email = next(row for row in rows if row.channel == "email")
        assert b"secret-token-value" not in email.encrypted_payload
        assert not email.encrypted_payload.startswith(b"{")
    engine.dispose()


def test_hold_starts_only_after_both_channels_are_delivered(monkeypatch):
    _configure_crypto(monkeypatch)
    engine = _database()
    monkeypatch.setattr(notifications, "_deliver", lambda db, row: None)
    with Session(engine) as db:
        case = _case(db)
        notifications.queue_event(
            db,
            user_id=case.user_id,
            event_key=f"{case.id}:hold_started",
            event_type="recovery_hold_started",
            email_subject="Hold",
            email_body="Email",
            telegram_body="Telegram",
        )
        db.commit()
        assert notifications.dispatch_due_notifications(db) == 2
        db.refresh(case)
        assert case.status == "hold_active"
        assert case.hold_started_at is not None
        assert case.hold_ends_at - case.hold_started_at == timedelta(hours=24)
        assert db.scalar(select(NotificationOutbox).where(NotificationOutbox.status != "delivered")) is None
    engine.dispose()


def test_critical_delivery_failure_blocks_case_and_uses_bounded_retry(monkeypatch):
    _configure_crypto(monkeypatch)
    engine = _database()

    def fail_delivery(db, row):
        raise notifications.NotificationChannelUnavailable("private provider details")

    monkeypatch.setattr(notifications, "_deliver", fail_delivery)
    with Session(engine) as db:
        case = _case(db)
        notifications.queue_event(
            db,
            user_id=case.user_id,
            event_key=f"{case.id}:hold_started",
            event_type="recovery_hold_started",
            email_subject="Hold",
            email_body="Email",
            telegram_body="Telegram",
        )
        db.flush()
        rows = db.scalars(select(NotificationOutbox)).all()
        for row in rows:
            row.attempt_count = notifications.MAX_ATTEMPTS - 1
        db.commit()
        assert notifications.dispatch_due_notifications(db) == 0
        db.refresh(case)
        assert case.status == "notification_blocked"
        assert all(row.status == "dead" for row in db.scalars(select(NotificationOutbox)).all())
        assert all(row.last_error_code == "delivery_unavailable" for row in db.scalars(select(NotificationOutbox)).all())
    engine.dispose()


def test_transient_failure_is_retried_with_backoff(monkeypatch):
    _configure_crypto(monkeypatch)
    engine = _database()
    monkeypatch.setattr(
        notifications,
        "_deliver",
        lambda db, row: (_ for _ in ()).throw(notifications.NotificationChannelUnavailable()),
    )
    with Session(engine) as db:
        user = User(telegram_user_id="123456")
        db.add(user)
        db.flush()
        notifications.queue_event(
            db,
            user_id=user.id,
            event_key="case-2:case_started",
            event_type="recovery_case_started",
            email_subject="Recovery",
            email_body="Email",
            telegram_body="Telegram",
        )
        db.commit()
        notifications.dispatch_due_notifications(db)
        rows = db.scalars(select(NotificationOutbox)).all()
        assert all(row.status == "retry" for row in rows)
        assert all(row.attempt_count == 1 for row in rows)
        assert all(
            (row.next_attempt_at.replace(tzinfo=UTC) if row.next_attempt_at.tzinfo is None else row.next_attempt_at)
            > datetime.now(UTC)
            for row in rows
        )
    engine.dispose()



def test_veto_prevents_pending_hold_notification_from_starting_clock(monkeypatch):
    _configure_crypto(monkeypatch)
    engine = _database()
    monkeypatch.setattr(notifications, "_deliver", lambda db, row: None)
    with Session(engine) as db:
        case = _case(db, status="manual_review")
        case.vetoed_at = datetime.now(UTC)
        notifications.queue_event(
            db,
            user_id=case.user_id,
            event_key=f"{case.id}:hold_started",
            event_type="recovery_hold_started",
            email_subject="Hold",
            email_body="Email",
            telegram_body="Telegram",
        )
        db.commit()
        notifications.dispatch_due_notifications(db)
        db.refresh(case)
        assert case.status == "manual_review"
        assert case.hold_started_at is None
        assert case.hold_ends_at is None
    engine.dispose()



def test_expired_contact_approval_closes_case_and_queues_notice(monkeypatch):
    _configure_crypto(monkeypatch)
    engine = _database()
    with Session(engine) as db:
        case = _case(db, status="awaiting_approvals")
        case.contact_approval_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        case.contact_approval_token_hash = "a" * 64
        assert notifications.expire_due_recovery_cases(db) == 1
        db.refresh(case)
        assert case.status == "expired"
        assert case.contact_approval_token_hash is None
        notices = db.scalars(
            select(NotificationOutbox).where(NotificationOutbox.event_key == f"{case.id}:case_expired")
        ).all()
        assert len(notices) == 2
    engine.dispose()



def test_stalled_operator_approval_expires_after_seven_days(monkeypatch):
    _configure_crypto(monkeypatch)
    engine = _database()
    with Session(engine) as db:
        case = _case(db, status="awaiting_approvals")
        case.contact_approved_at = datetime.now(UTC) - timedelta(days=8)
        case.created_at = datetime.now(UTC) - timedelta(days=8)
        case.contact_approval_expires_at = datetime.now(UTC) - timedelta(days=8)
        assert notifications.expire_due_recovery_cases(db) == 1
        db.refresh(case)
        assert case.status == "expired"
        assert case.veto_token_hash is None
    engine.dispose()
