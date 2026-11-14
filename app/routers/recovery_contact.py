import hashlib
import json
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options,
    options_to_json,
    verify_authentication_response,
)
from webauthn.helpers import base64url_to_bytes
from webauthn.helpers.structs import PublicKeyCredentialDescriptor, UserVerificationRequirement

from app.core.config import get_settings
from app.db import get_db
from app.models import PasskeyCredential, RecoveryContact, User, WebAuthnChallenge
from app.security.origins import require_allowed_origin
from app.security.rate_limit import enforce_ip_rate_limit
from app.security.sessions import require_session
from app.security.telegram import verify_telegram_init_data
from app.services.email import EmailDeliveryError, EmailTransportNotConfigured, send_email
from app.services.recovery_contact_crypto import (
    RecoveryContactCryptoNotConfigured,
    contact_digest,
    encrypt_contact,
)

router = APIRouter(
    prefix="/auth/passkeys/recovery-contact",
    tags=["recovery-contact"],
    dependencies=[Depends(require_allowed_origin), Depends(enforce_ip_rate_limit)],
)

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class EnrollmentVerifyRequest(BaseModel):
    challenge_id: str = Field(min_length=36, max_length=36)
    email: str = Field(min_length=5, max_length=254)
    credential: dict


class ConfirmRequest(BaseModel):
    token: str = Field(min_length=32, max_length=128)


def _is_unexpired(expires_at: datetime, now: datetime) -> bool:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at > now


def _authenticated_user(request: Request, db: Session, init_data: str) -> tuple[User, list[PasskeyCredential]]:
    identity = verify_telegram_init_data(init_data)
    session = require_session(request, db)
    user = db.get(User, session.user_id)
    if user is None or user.telegram_user_id != identity["telegram_user_id"]:
        raise HTTPException(status_code=401, detail="Session identity mismatch")
    credentials = db.scalars(
        select(PasskeyCredential).where(
            PasskeyCredential.user_id == user.id,
            PasskeyCredential.revoked_at.is_(None),
        )
    ).all()
    if len(credentials) < 2:
        raise HTTPException(
            status_code=409,
            detail="At least two active Passkeys are required before recovery contact enrollment",
        )
    return user, credentials


def _consume_step_up_challenge(db: Session, challenge_id: str, user_id: int, init_data: str) -> bytes:
    now = datetime.now(UTC)
    row = db.scalar(
        select(WebAuthnChallenge)
        .where(
            WebAuthnChallenge.id == challenge_id,
            WebAuthnChallenge.user_id == user_id,
            WebAuthnChallenge.purpose == "contact_enroll",
            WebAuthnChallenge.context_hash == hashlib.sha256(init_data.encode()).hexdigest(),
            WebAuthnChallenge.consumed_at.is_(None),
            WebAuthnChallenge.expires_at > now,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=400, detail="Passkey challenge invalid, expired or already used")
    row.consumed_at = now
    challenge = row.challenge
    db.commit()
    return challenge


@router.post("/registration/options")
def registration_options(
    request: Request,
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
    db: Session = Depends(get_db),
) -> dict:
    user, credentials = _authenticated_user(request, db, x_telegram_init_data)
    existing = db.get(RecoveryContact, user.id)
    if existing is not None and (
        existing.verified_at is not None or _is_unexpired(existing.verification_expires_at, datetime.now(UTC))
    ):
        raise HTTPException(status_code=409, detail="A recovery contact is already registered or pending")
    if existing is not None:
        db.delete(existing)
        db.flush()

    settings = get_settings()
    options = generate_authentication_options(
        rp_id=settings.webauthn_rp_id,
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(item.credential_id))
            for item in credentials
        ],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    challenge_id = str(uuid.uuid4())
    db.add(WebAuthnChallenge(
        id=challenge_id,
        user_id=user.id,
        purpose="contact_enroll",
        challenge=options.challenge,
        context_hash=hashlib.sha256(x_telegram_init_data.encode()).hexdigest(),
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.webauthn_challenge_ttl),
    ))
    db.commit()
    return {"challenge_id": challenge_id, "publicKey": json.loads(options_to_json(options))}


@router.post("/registration/verify")
def registration_verify(
    payload: EnrollmentVerifyRequest,
    request: Request,
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
    db: Session = Depends(get_db),
) -> dict:
    user, _credentials = _authenticated_user(request, db, x_telegram_init_data)
    email = payload.email.strip()
    if not _EMAIL_RE.fullmatch(email):
        raise HTTPException(status_code=422, detail="A valid email address is required")
    existing = db.get(RecoveryContact, user.id)
    if existing is not None and (
        existing.verified_at is not None
        or _is_unexpired(existing.verification_expires_at, datetime.now(UTC))
    ):
        raise HTTPException(status_code=409, detail="A recovery contact is already registered or pending")

    challenge = _consume_step_up_challenge(db, payload.challenge_id, user.id, x_telegram_init_data)
    credential_id = payload.credential.get("id")
    credential = db.scalar(
        select(PasskeyCredential)
        .where(
            PasskeyCredential.credential_id == credential_id,
            PasskeyCredential.user_id == user.id,
            PasskeyCredential.revoked_at.is_(None),
        )
        .with_for_update()
    )
    if credential is None:
        raise HTTPException(status_code=401, detail="Passkey verification failed")

    settings = get_settings()
    try:
        verified = verify_authentication_response(
            credential=payload.credential,
            expected_challenge=challenge,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=settings.webauthn_origin,
            credential_public_key=credential.public_key,
            credential_current_sign_count=credential.sign_count,
            require_user_verification=True,
        )
    except Exception:  # noqa: BLE001 - verifier errors must not expose credential details
        raise HTTPException(status_code=401, detail="Passkey verification failed") from None

    try:
        encrypted_email = encrypt_contact(email)
        digest = contact_digest(email)
    except RecoveryContactCryptoNotConfigured:
        raise HTTPException(status_code=503, detail="Recovery contact encryption is not configured") from None

    raw_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(minutes=15)
    if existing is not None:
        db.delete(existing)
    contact = RecoveryContact(
        user_id=user.id,
        encrypted_email=encrypted_email,
        email_digest=digest,
        verification_token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        verification_expires_at=expires_at,
    )
    credential.sign_count = verified.new_sign_count
    credential.device_type = str(verified.credential_device_type)
    credential.backed_up = verified.credential_backed_up
    db.add(contact)
    db.commit()

    try:
        send_email(
            recipient=email,
            subject="Weryfikacja niezależnego kontaktu odzyskiwania",
            text_body=(
                "Otrzymaliśmy prośbę o dodanie tego adresu jako niezależnego kontaktu "
                "odzyskiwania konta. Jeśli to Ty ją rozpocząłeś, wpisz poniższy jednorazowy "
                "kod w aplikacji. Kod wygaśnie po 15 minutach:\n\n"
                f"{raw_token}\n\n"
                "Samo otrzymanie tej wiadomości nie rozpoczyna ani nie zatwierdza odzyskiwania konta."
            ),
        )
    except (EmailTransportNotConfigured, EmailDeliveryError):
        db.delete(contact)
        db.commit()
        raise HTTPException(status_code=503, detail="Recovery contact verification email could not be sent") from None

    return {"verification_sent": True, "expires_in": 900}


@router.post("/registration/confirm")
def registration_confirm(payload: ConfirmRequest, db: Session = Depends(get_db)) -> dict:
    token_hash = hashlib.sha256(payload.token.encode()).hexdigest()
    now = datetime.now(UTC)
    contact = db.scalar(
        select(RecoveryContact).where(
            RecoveryContact.verification_token_hash == token_hash,
            RecoveryContact.verified_at.is_(None),
            RecoveryContact.verification_expires_at > now,
        ).with_for_update()
    )
    if contact is None:
        raise HTTPException(status_code=400, detail="Verification token invalid, expired or already used")
    contact.verified_at = now
    contact.verification_token_hash = None
    db.commit()
    return {"verified": True}


@router.get("")
def recovery_contact_status(
    request: Request,
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
    db: Session = Depends(get_db),
) -> dict:
    identity = verify_telegram_init_data(x_telegram_init_data)
    session = require_session(request, db)
    user = db.get(User, session.user_id)
    if user is None or user.telegram_user_id != identity["telegram_user_id"]:
        raise HTTPException(status_code=401, detail="Session identity mismatch")
    contact = db.get(RecoveryContact, user.id)
    if contact is None:
        return {"configured": False, "verified": False}
    return {
        "configured": True,
        "verified": contact.verified_at is not None,
        "verification_pending": contact.verified_at is None and _is_unexpired(contact.verification_expires_at, datetime.now(UTC)),
    }
