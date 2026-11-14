import json
import urllib.error
import urllib.request

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    NotificationAttempt,
    NotificationOutbox,
    RecoveryCase,
    RecoveryContact,
    User,
)
from app.services.email import EmailDeliveryError, EmailTransportNotConfigured, send_email
from app.services.recovery_contact_crypto import (
    RecoveryContactCryptoNotConfigured,
    decrypt_contact,
    decrypt_payload,
    encrypt_payload,
)


MAX_ATTEMPTS = 8
RETRY_BASE_SECONDS = 30
RETRY_MAX_SECONDS = 6 * 60 * 60


class NotificationChannelUnavailable(RuntimeError):
    """Raised when a required notification channel cannot currently deliver."""


def queue_event(
    db: Session,
    *,
    user_id: int,
    event_key: str,
    event_type: str,
    email_subject: str,
    email_body: str,
    telegram_body: str,
) -> None:
    """Idempotently queue both required security channels with encrypted payloads."""
    payloads = {
        "email": {"subject": email_subject, "body": email_body},
        "telegram": {"body": telegram_body},
    }
    now = datetime.now(UTC)
    for channel, payload in payloads.items():
        values = {
            "event_key": event_key,
            "user_id": user_id,
            "channel": channel,
            "event_type": event_type,
            "encrypted_payload": encrypt_payload(json.dumps(payload, separators=(",", ":"))),
            "status": "pending",
            "attempt_count": 0,
            "next_attempt_at": now,
            "created_at": now,
        }
        dialect = db.get_bind().dialect.name
        if dialect == "postgresql":
            statement = pg_insert(NotificationOutbox).values(**values).on_conflict_do_nothing(
                index_elements=["event_key", "channel"]
            )
            db.execute(statement)
        elif dialect == "sqlite":
            statement = sqlite_insert(NotificationOutbox).values(**values).on_conflict_do_nothing(
                index_elements=["event_key", "channel"]
            )
            db.execute(statement)
        else:
            existing = db.scalar(
                select(NotificationOutbox).where(
                    NotificationOutbox.event_key == event_key,
                    NotificationOutbox.channel == channel,
                )
            )
            if existing is None:
                db.add(NotificationOutbox(**values))


def _send_telegram(chat_id: str, text: str) -> None:
    token = get_settings().telegram_bot_token.strip()
    if not token:
        raise NotificationChannelUnavailable("telegram_not_configured")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({"chat_id": chat_id, "text": text, "disable_web_page_preview": True}).encode()
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not result.get("ok"):
            raise NotificationChannelUnavailable("telegram_rejected")
    except (OSError, urllib.error.URLError, TimeoutError):
        raise NotificationChannelUnavailable("telegram_delivery_failed") from None


def _deliver(db: Session, row: NotificationOutbox) -> None:
    payload = json.loads(decrypt_payload(row.encrypted_payload))
    user = db.get(User, row.user_id)
    if user is None:
        raise NotificationChannelUnavailable("recipient_unavailable")
    if row.channel == "email":
        contact = db.get(RecoveryContact, row.user_id)
        if contact is None or contact.verified_at is None:
            raise NotificationChannelUnavailable("verified_contact_unavailable")
        recipient = decrypt_contact(contact.encrypted_email)
        send_email(recipient=recipient, subject=payload["subject"], text_body=payload["body"])
        return
    if row.channel == "telegram":
        _send_telegram(user.telegram_user_id, payload["body"])
        return
    raise NotificationChannelUnavailable("unsupported_channel")


def _maybe_start_hold(db: Session, event_key: str, now: datetime) -> None:
    if not event_key.endswith(":hold_started"):
        return
    case_id = event_key.removesuffix(":hold_started")
    case = db.scalar(select(RecoveryCase).where(RecoveryCase.id == case_id).with_for_update())
    if case is None or case.status != "awaiting_notification_delivery":
        return
    rows = db.scalars(
        select(NotificationOutbox).where(NotificationOutbox.event_key == event_key)
    ).all()
    if len(rows) == 2 and all(row.status == "delivered" for row in rows):
        case.status = "hold_active"
        case.hold_started_at = now
        case.hold_ends_at = now + timedelta(hours=24)
        case.updated_at = now


def dispatch_due_notifications(db: Session, *, limit: int = 25) -> int:
    """Deliver due outbox rows; bounded retries are at-least-once, never exactly-once."""
    now = datetime.now(UTC)
    rows = db.scalars(
        select(NotificationOutbox)
        .where(
            NotificationOutbox.status.in_({"pending", "retry"}),
            NotificationOutbox.next_attempt_at <= now,
        )
        .order_by(NotificationOutbox.created_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    delivered = 0
    for row in rows:
        attempt_number = row.attempt_count + 1
        try:
            _deliver(db, row)
        except (
            NotificationChannelUnavailable,
            EmailDeliveryError,
            EmailTransportNotConfigured,
            RecoveryContactCryptoNotConfigured,
            ValueError,
        ):
            row.attempt_count = attempt_number
            row.status = "dead" if attempt_number >= MAX_ATTEMPTS else "retry"
            row.last_error_code = "delivery_unavailable"
            delay = min(RETRY_BASE_SECONDS * (2 ** (attempt_number - 1)), RETRY_MAX_SECONDS)
            row.next_attempt_at = now + timedelta(seconds=delay)
            db.add(NotificationAttempt(
                outbox_id=row.id,
                attempt_number=attempt_number,
                outcome="failed",
                error_code=row.last_error_code,
            ))
            if row.status == "dead" and row.event_type.startswith("recovery_"):
                case_id = row.event_key.split(":", 1)[0]
                case = db.scalar(select(RecoveryCase).where(RecoveryCase.id == case_id).with_for_update())
                if case is not None and case.status not in {
                    "vetoed", "manual_review", "cancelled", "expired", "hold_complete_pending_review",
                }:
                    case.status = "notification_blocked"
                    case.updated_at = now
            continue
        row.attempt_count = attempt_number
        row.status = "delivered"
        row.delivered_at = now
        row.last_error_code = None
        db.add(NotificationAttempt(
            outbox_id=row.id,
            attempt_number=attempt_number,
            outcome="delivered",
        ))
        _maybe_start_hold(db, row.event_key, now)
        delivered += 1
    db.commit()
    return delivered



def expire_due_recovery_cases(db: Session) -> int:
    """Expire stalled cases and enqueue end-of-hold notices without user polling."""
    now = datetime.now(UTC)
    cases = db.scalars(
        select(RecoveryCase)
        .where(RecoveryCase.status == "awaiting_approvals")
        .with_for_update(skip_locked=True)
    ).all()
    expired_cases = []
    for case in cases:
        created_at = case.created_at.replace(tzinfo=UTC) if case.created_at.tzinfo is None else case.created_at
        approval_expires_at = case.contact_approval_expires_at
        if approval_expires_at is not None and approval_expires_at.tzinfo is None:
            approval_expires_at = approval_expires_at.replace(tzinfo=UTC)
        contact_expired = (
            case.contact_approved_at is None
            and approval_expires_at is not None
            and approval_expires_at <= now
        )
        operator_expired = case.operator_approved_at is None and created_at + timedelta(days=7) <= now
        if not contact_expired and not operator_expired:
            continue
        expired_cases.append(case)
        case.status = "expired"
        case.contact_approval_token_hash = None
        case.veto_token_hash = None
        case.updated_at = now
        queue_event(
            db,
            user_id=case.user_id,
            event_key=f"{case.id}:case_expired",
            event_type="recovery_case_expired",
            email_subject="Wniosek odzyskiwania Passkey wygasł",
            email_body=f"Okno zatwierdzenia kontaktu dla sprawy {case.id} wygasło. Nie wydano tokenu ani sesji.",
            telegram_body="Wniosek odzyskiwania Passkey wygasł bez zatwierdzenia kontaktu.",
        )
    completed_cases = db.scalars(
        select(RecoveryCase)
        .where(
            RecoveryCase.status == "hold_active",
            RecoveryCase.hold_ends_at.is_not(None),
            RecoveryCase.hold_ends_at <= now,
            RecoveryCase.vetoed_at.is_(None),
        )
        .with_for_update(skip_locked=True)
    ).all()
    for case in completed_cases:
        case.status = "hold_complete_pending_review"
        case.updated_at = now
        queue_event(
            db,
            user_id=case.user_id,
            event_key=f"{case.id}:hold_complete",
            event_type="recovery_hold_complete",
            email_subject="Zakończono 24-godzinny okres ochronny",
            email_body=f"Okres ochronny sprawy {case.id} dobiegł końca. Sprawa wymaga jeszcze ręcznej kontroli; żaden token nie został wydany.",
            telegram_body="Okres ochronny dobiegł końca. Odzyskiwanie nadal oczekuje na ręczną kontrolę.",
        )
    db.commit()
    return len(expired_cases) + len(completed_cases)
