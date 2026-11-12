import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
    PublicKeyCredentialDescriptor,
)

from app.core.config import get_settings
from app.db import get_db
from app.models import AuthSession, PasskeyCredential, User, WebAuthnChallenge
from app.security.sessions import require_session
from app.security.telegram import verify_telegram_init_data

router = APIRouter(prefix="/auth/passkeys", tags=["passkeys"])


class FinishRequest(BaseModel):
    challenge_id: str
    credential: dict
    name: str | None = Field(default=None, max_length=120)


def _get_or_create_user(db: Session, telegram_user_id: str) -> User:
    user = db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if user is None:
        user = User(telegram_user_id=telegram_user_id)
        db.add(user)
        db.flush()
    return user


def _new_challenge(db: Session, user: User, purpose: str, challenge: bytes, init_data: str) -> str:
    settings = get_settings()
    challenge_id = str(uuid.uuid4())
    db.add(WebAuthnChallenge(
        id=challenge_id,
        user_id=user.id,
        purpose=purpose,
        challenge=challenge,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=settings.webauthn_challenge_ttl),
    ))
    db.commit()
    return challenge_id


def _consume_challenge(db: Session, challenge_id: str, user_id: int, purpose: str, init_data: str) -> bytes:
    now = datetime.now(timezone.utc)
    row = db.scalar(
        select(WebAuthnChallenge)
        .where(
            WebAuthnChallenge.id == challenge_id,
            WebAuthnChallenge.user_id == user_id,
            WebAuthnChallenge.purpose == purpose,
            WebAuthnChallenge.consumed_at.is_(None),
            WebAuthnChallenge.expires_at > now,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=400, detail="Challenge invalid, expired or already used")
    row.consumed_at = now
    db.commit()
    return row.challenge


def _session_cookie(db: Session, user: User, response: Response) -> None:
    settings = get_settings()
    raw_token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(seconds=settings.auth_session_ttl)
    db.add(AuthSession(
        user_id=user.id,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        expires_at=expires,
    ))
    db.commit()
    response.set_cookie(
        settings.auth_cookie_name,
        raw_token,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        max_age=settings.auth_session_ttl,
        path="/",
    )


@router.post("/registration/options")
def registration_options(
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
    db: Session = Depends(get_db),
) -> dict:
    identity = verify_telegram_init_data(x_telegram_init_data)
    user = _get_or_create_user(db, identity["telegram_user_id"])
    settings = get_settings()
    existing = db.scalars(select(PasskeyCredential).where(
        PasskeyCredential.user_id == user.id, PasskeyCredential.revoked_at.is_(None)
    )).all()
    options = generate_registration_options(
        rp_id=settings.webauthn_rp_id,
        rp_name=settings.webauthn_rp_name,
        user_id=user.telegram_user_id.encode(),
        user_name=f"telegram:{user.telegram_user_id}",
        user_display_name=identity["user"].get("first_name", "Telegram user"),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(item.credential_id))
            for item in existing
        ],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    challenge_id = _new_challenge(db, user, "registration", options.challenge, x_telegram_init_data)
    return {"challenge_id": challenge_id, "publicKey": json.loads(options_to_json(options))}


@router.post("/registration/verify")
def registration_verify(
    payload: FinishRequest,
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
    db: Session = Depends(get_db),
) -> dict:
    identity = verify_telegram_init_data(x_telegram_init_data)
    user = _get_or_create_user(db, identity["telegram_user_id"])
    challenge = _consume_challenge(db, payload.challenge_id, user.id, "registration", x_telegram_init_data)
    settings = get_settings()
    try:
        verified = verify_registration_response(
            credential=payload.credential,
            expected_challenge=challenge,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=settings.webauthn_origin,
            require_user_verification=True,
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Passkey registration verification failed") from None

    credential_id = bytes_to_base64url(verified.credential_id)
    duplicate = db.scalar(select(PasskeyCredential).where(PasskeyCredential.credential_id == credential_id))
    if duplicate:
        raise HTTPException(status_code=409, detail="Passkey already registered")
    db.add(PasskeyCredential(
        user_id=user.id,
        credential_id=credential_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        transports=json.dumps(payload.credential.get("response", {}).get("transports", [])),
        device_type=str(verified.credential_device_type),
        backed_up=verified.credential_backed_up,
        name=payload.name,
    ))
    db.commit()
    return {"registered": True}


@router.post("/authentication/options")
def authentication_options(
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
    db: Session = Depends(get_db),
) -> dict:
    identity = verify_telegram_init_data(x_telegram_init_data)
    user = _get_or_create_user(db, identity["telegram_user_id"])
    credentials = db.scalars(select(PasskeyCredential).where(
        PasskeyCredential.user_id == user.id, PasskeyCredential.revoked_at.is_(None)
    )).all()
    if not credentials:
        raise HTTPException(status_code=404, detail="No active Passkey is registered")
    settings = get_settings()
    options = generate_authentication_options(
        rp_id=settings.webauthn_rp_id,
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(item.credential_id))
            for item in credentials
        ],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    challenge_id = _new_challenge(db, user, "authentication", options.challenge, x_telegram_init_data)
    return {"challenge_id": challenge_id, "publicKey": json.loads(options_to_json(options))}


@router.post("/authentication/verify")
def authentication_verify(
    payload: FinishRequest,
    response: Response,
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
    db: Session = Depends(get_db),
) -> dict:
    identity = verify_telegram_init_data(x_telegram_init_data)
    user = _get_or_create_user(db, identity["telegram_user_id"])
    challenge = _consume_challenge(db, payload.challenge_id, user.id, "authentication", x_telegram_init_data)
    credential_id = payload.credential.get("id")
    credential = db.scalar(select(PasskeyCredential).where(
        PasskeyCredential.credential_id == credential_id,
        PasskeyCredential.user_id == user.id,
        PasskeyCredential.revoked_at.is_(None),
    ))
    if credential is None:
        raise HTTPException(status_code=401, detail="Passkey not recognized")
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
    except Exception:
        raise HTTPException(status_code=401, detail="Passkey authentication failed") from None
    credential.sign_count = verified.new_sign_count
    credential.device_type = str(verified.credential_device_type)
    credential.backed_up = verified.credential_backed_up
    _session_cookie(db, user, response)
    return {"authenticated": True}


@router.get("/session")
def current_session(
    request: Request,
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
    db: Session = Depends(get_db),
) -> dict:
    identity = verify_telegram_init_data(x_telegram_init_data)
    session = require_session(request, db)
    user = db.get(User, session.user_id)
    if user is None or user.telegram_user_id != identity["telegram_user_id"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session identity mismatch")
    return {"authenticated": True, "telegram_user_id": user.telegram_user_id}


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    settings = get_settings()
    raw_token = request.cookies.get(settings.auth_cookie_name)
    if raw_token:
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))
        if session and session.revoked_at is None:
            session.revoked_at = datetime.now(timezone.utc)
            db.commit()
    response.delete_cookie(settings.auth_cookie_name, path="/", httponly=True, secure=settings.app_env == "production", samesite="lax")
    return {"logged_out": True}


@router.post("/{credential_id}/revoke")
def revoke_passkey(
    credential_id: str,
    request: Request,
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
    db: Session = Depends(get_db),
) -> dict:
    identity = verify_telegram_init_data(x_telegram_init_data)
    session = require_session(request, db)
    user = db.get(User, session.user_id)
    if user is None or user.telegram_user_id != identity["telegram_user_id"]:
        raise HTTPException(status_code=401, detail="Session identity mismatch")
    credential = db.scalar(select(PasskeyCredential).where(
        PasskeyCredential.credential_id == credential_id,
        PasskeyCredential.user_id == user.id,
        PasskeyCredential.revoked_at.is_(None),
    ))
    if credential is None:
        raise HTTPException(status_code=404, detail="Active Passkey not found")
    active_count = db.scalar(select(PasskeyCredential.id).where(
        PasskeyCredential.user_id == user.id,
        PasskeyCredential.revoked_at.is_(None),
    ).limit(2))
    active_credentials = db.scalars(select(PasskeyCredential).where(
        PasskeyCredential.user_id == user.id,
        PasskeyCredential.revoked_at.is_(None),
    )).all()
    if len(active_credentials) <= 1:
        raise HTTPException(status_code=409, detail="Register another Passkey before revoking the last one")
    credential.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return {"revoked": True}
