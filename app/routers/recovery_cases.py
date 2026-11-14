import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import RecoveryCase, RecoveryContact, User
from app.security.origins import require_allowed_origin
from app.security.rate_limit import enforce_ip_rate_limit
from app.security.telegram import verify_telegram_init_data
from app.services.recovery_contact_crypto import RecoveryContactCryptoNotConfigured
from app.services.recovery_notifications import queue_event

router = APIRouter(
    prefix="/auth/passkeys/recovery",
    tags=["passkey-recovery"],
    dependencies=[Depends(require_allowed_origin), Depends(enforce_ip_rate_limit)],
)


class ContactDecisionBody(BaseModel):
    token: str = Field(min_length=32, max_length=256)


class VetoBody(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    reason: str = Field(min_length=12, max_length=1000)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _queue_case_event(
    db: Session,
    case: RecoveryCase,
    event: str,
    *,
    email_subject: str,
    email_body: str,
    telegram_body: str,
) -> None:
    queue_event(
        db,
        user_id=case.user_id,
        event_key=f"{case.id}:{event}",
        event_type=f"recovery_{event}",
        email_subject=email_subject,
        email_body=email_body,
        telegram_body=telegram_body,
    )


@router.post("/cases")
def start_recovery_case(
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
    db: Session = Depends(get_db),
) -> dict:
    identity = verify_telegram_init_data(x_telegram_init_data)
    user = db.scalar(
        select(User)
        .where(User.telegram_user_id == identity["telegram_user_id"])
        .with_for_update()
    )
    if user is None:
        raise HTTPException(status_code=404, detail="Account not found")
    contact = db.get(RecoveryContact, user.id)
    if contact is None or contact.verified_at is None:
        raise HTTPException(status_code=409, detail="A verified independent recovery contact is required")
    active = db.scalar(
        select(RecoveryCase).where(
            RecoveryCase.user_id == user.id,
            RecoveryCase.status.in_({
                "awaiting_approvals", "awaiting_notification_delivery",
                "hold_active", "hold_complete_pending_review", "notification_blocked", "manual_review",
            }),
        )
    )
    if active is not None:
        raise HTTPException(status_code=409, detail="An active recovery case already exists")

    now = datetime.now(UTC)
    approval_token = secrets.token_urlsafe(32)
    veto_token = secrets.token_urlsafe(32)
    case = RecoveryCase(
        id=str(uuid.uuid4()),
        user_id=user.id,
        status="awaiting_approvals",
        contact_approval_token_hash=_hash_token(approval_token),
        contact_approval_expires_at=now + timedelta(minutes=15),
        veto_token_hash=_hash_token(veto_token),
        veto_expires_at=now + timedelta(days=7),
        created_at=now,
        updated_at=now,
    )
    db.add(case)
    try:
        _queue_case_event(
            db,
            case,
            "case_started",
            email_subject="Rozpoczęto wniosek odzyskiwania Passkey",
            email_body=(
                "Otrzymano wniosek odzyskiwania konta. Telegram nie potwierdza tożsamości.\n\n"
                f"Id sprawy: {case.id}\n"
                f"Token zatwierdzenia kontaktu (ważny 15 minut): {approval_token}\n"
                f"Token veto (ważny do 7 dni): {veto_token}\n\n"
                "Jeśli nie rozpoznajesz wniosku, użyj tokenu veto w niezależnym kanale obsługi."
            ),
            telegram_body=(
                "Otrzymano wniosek odzyskiwania Passkey dla Twojego konta. "
                "Jeśli to nie Ty, użyj wcześniej zarejestrowanego kontaktu odzyskiwania, "
                "aby zgłosić veto. Nie przekazuj nikomu kodów."
            ),
        )
        db.commit()
    except RecoveryContactCryptoNotConfigured:
        db.rollback()
        raise HTTPException(status_code=503, detail="Recovery notification encryption is not configured") from None
    return {"case_id": case.id, "status": case.status, "contact_approval_expires_in": 900}


@router.post("/cases/{case_id}/contact-approval")
def approve_recovery_contact(
    case_id: str,
    payload: ContactDecisionBody,
    db: Session = Depends(get_db),
) -> dict:
    try:
        normalized = str(uuid.UUID(case_id))
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid recovery case identifier") from None
    case = db.scalar(select(RecoveryCase).where(RecoveryCase.id == normalized).with_for_update())
    now = datetime.now(UTC)
    if (
        case is None
        or case.status not in {"awaiting_approvals", "awaiting_notification_delivery"}
        or case.contact_approval_token_hash is None
        or not secrets.compare_digest(case.contact_approval_token_hash, _hash_token(payload.token))
        or case.contact_approval_expires_at is None
        or _aware(case.contact_approval_expires_at) <= now
    ):
        raise HTTPException(status_code=400, detail="Contact approval token is invalid or expired")
    case.contact_approval_token_hash = None
    case.contact_approved_at = now
    case.updated_at = now
    _queue_case_event(
        db,
        case,
        "contact_approved",
        email_subject="Kontakt odzyskiwania zatwierdził wniosek",
        email_body=f"Kontakt odzyskiwania zatwierdził sprawę {case.id}. Veto pozostaje możliwe w okresie ochronnym.",
        telegram_body="Niezależny kontakt odzyskiwania zatwierdził wniosek. Sprawa nadal wymaga decyzji operatora bezpieczeństwa.",
    )
    if case.operator_approved_at is not None and case.vetoed_at is None:
        case.status = "awaiting_notification_delivery"
        _queue_case_event(
            db,
            case,
            "hold_started",
            email_subject="Rozpoczyna się 24-godzinny okres ochronny",
            email_body=f"Obie niezależne akceptacje są zapisane. Okres 24h rozpocznie się po potwierdzeniu dostarczenia obu kanałów powiadomień. Id sprawy: {case.id}",
            telegram_body="Obie niezależne akceptacje są zapisane. Okres ochronny rozpocznie się po dostarczeniu powiadomień na oba kanały.",
        )
    db.commit()
    return {"recorded": True, "status": case.status}


@router.post("/cases/{case_id}/veto")
def veto_recovery_case(
    case_id: str,
    payload: VetoBody,
    db: Session = Depends(get_db),
) -> dict:
    try:
        normalized = str(uuid.UUID(case_id))
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid recovery case identifier") from None
    case = db.scalar(select(RecoveryCase).where(RecoveryCase.id == normalized).with_for_update())
    now = datetime.now(UTC)
    if (
        case is None
        or case.status in {"vetoed", "cancelled"}
        or case.veto_token_hash is None
        or not secrets.compare_digest(case.veto_token_hash, _hash_token(payload.token))
        or case.veto_expires_at is None
        or _aware(case.veto_expires_at) <= now
    ):
        raise HTTPException(status_code=400, detail="Veto token is invalid or expired")
    case.veto_token_hash = None
    case.vetoed_at = now
    case.veto_reason = payload.reason.strip()
    case.status = "manual_review"
    case.updated_at = now
    _queue_case_event(
        db,
        case,
        "vetoed",
        email_subject="Odzyskiwanie Passkey zostało zablokowane",
        email_body=f"Zgłoszono veto dla sprawy {case.id}. Automatyczne odzyskiwanie jest zablokowane i wymaga ręcznej analizy.",
        telegram_body="Zgłoszono veto dla sprawy odzyskiwania Passkey. Automatyczna finalizacja została zablokowana.",
    )
    db.commit()
    return {"veto_recorded": True, "status": "manual_review"}




@router.post("/cases/{case_id}/cancel")
def cancel_recovery_case(
    case_id: str,
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
    db: Session = Depends(get_db),
) -> dict:
    identity = verify_telegram_init_data(x_telegram_init_data)
    user = db.scalar(select(User).where(User.telegram_user_id == identity["telegram_user_id"]))
    if user is None:
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        normalized = str(uuid.UUID(case_id))
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid recovery case identifier") from None
    case = db.scalar(
        select(RecoveryCase)
        .where(RecoveryCase.id == normalized, RecoveryCase.user_id == user.id)
        .with_for_update()
    )
    if case is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")
    if case.status not in {
        "awaiting_approvals", "awaiting_notification_delivery",
        "hold_active", "hold_complete_pending_review",
    }:
        raise HTTPException(status_code=409, detail="Recovery case cannot be cancelled in its current state")
    now = datetime.now(UTC)
    case.status = "cancelled"
    case.contact_approval_token_hash = None
    case.veto_token_hash = None
    case.updated_at = now
    _queue_case_event(
        db,
        case,
        "case_cancelled",
        email_subject="Wniosek odzyskiwania Passkey anulowano",
        email_body=f"Wniosek odzyskiwania {case.id} został anulowany. Nie wydano tokenu ani sesji.",
        telegram_body="Wniosek odzyskiwania Passkey został anulowany.",
    )
    db.commit()
    return {"cancelled": True, "status": case.status}


@router.get("/cases/{case_id}")
def get_recovery_case_status(
    case_id: str,
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
    db: Session = Depends(get_db),
) -> dict:
    identity = verify_telegram_init_data(x_telegram_init_data)
    user = db.scalar(select(User).where(User.telegram_user_id == identity["telegram_user_id"]))
    if user is None:
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        normalized = str(uuid.UUID(case_id))
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid recovery case identifier") from None
    case = db.scalar(select(RecoveryCase).where(RecoveryCase.id == normalized, RecoveryCase.user_id == user.id))
    if case is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")
    now = datetime.now(UTC)
    if (
        case.status == "hold_active"
        and case.hold_ends_at is not None
        and _aware(case.hold_ends_at) <= now
        and case.vetoed_at is None
    ):
        case.status = "hold_complete_pending_review"
        case.updated_at = now
        _queue_case_event(
            db,
            case,
            "hold_complete",
            email_subject="Zakończono 24-godzinny okres ochronny",
            email_body=f"Okres ochronny sprawy {case.id} dobiegł końca. Sprawa wymaga jeszcze ręcznej kontroli; żaden token nie został wydany.",
            telegram_body="Okres ochronny dobiegł końca. Odzyskiwanie nadal oczekuje na ręczną kontrolę.",
        )
        db.commit()
    return {
        "case_id": case.id,
        "status": case.status,
        "contact_approved": case.contact_approved_at is not None,
        "operator_approved": case.operator_approved_at is not None,
        "hold_started_at": case.hold_started_at.isoformat() if case.hold_started_at else None,
        "hold_ends_at": case.hold_ends_at.isoformat() if case.hold_ends_at else None,
        "vetoed": case.vetoed_at is not None,
        "recovery_token_issued": False,
    }
