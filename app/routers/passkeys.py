import hashlib
import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
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
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.core.config import get_settings
from app.db import get_db
from app.models import AuthSession, PasskeyCredential, PasskeyHandoff, User, WebAuthnChallenge
from app.security.origins import require_allowed_origin
from app.security.rate_limit import enforce_ip_rate_limit
from app.security.sessions import require_session
from app.security.telegram import verify_telegram_init_data

router = APIRouter(
    prefix="/auth/passkeys",
    tags=["passkeys"],
    dependencies=[Depends(require_allowed_origin), Depends(enforce_ip_rate_limit)],
)


class FinishRequest(BaseModel):
    challenge_id: str
    credential: dict
    name: str | None = Field(default=None, max_length=120)


class HandoffOptionsRequest(BaseModel):
    handoff_token: str = Field(min_length=32, max_length=128)


class HandoffVerifyRequest(BaseModel):
    challenge_id: str
    credential: dict


def _get_or_create_user(db: Session, telegram_user_id: str) -> User:
    user = db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if user is not None:
        return user

    user = User(telegram_user_id=telegram_user_id)
    db.add(user)
    try:
        db.flush()
        return user
    except IntegrityError:
        # Another request may have inserted the same Telegram identity after our SELECT.
        db.rollback()
        user = db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
        if user is None:
            raise
        return user


def _require_existing_passkey_session(request: Request, db: Session, user: User) -> None:
    existing = db.scalars(select(PasskeyCredential).where(
        PasskeyCredential.user_id == user.id,
        PasskeyCredential.revoked_at.is_(None),
    )).first()
    if existing is None:
        return
    session = require_session(request, db)
    if session.user_id != user.id:
        raise HTTPException(status_code=401, detail="Passkey management requires this user's session")


def _new_challenge(db: Session, user: User, purpose: str, challenge: bytes, init_data: str) -> str:
    settings = get_settings()
    challenge_id = str(uuid.uuid4())
    db.add(WebAuthnChallenge(
        id=challenge_id,
        user_id=user.id,
        purpose=purpose,
        challenge=challenge,
        context_hash=hashlib.sha256(init_data.encode()).hexdigest(),
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.webauthn_challenge_ttl),
    ))
    db.commit()
    return challenge_id


def _consume_challenge(
    db: Session, challenge_id: str, user_id: int, purpose: str, init_data: str
) -> bytes:
    now = datetime.now(UTC)
    row = db.scalar(
        select(WebAuthnChallenge)
        .where(
            WebAuthnChallenge.id == challenge_id,
            WebAuthnChallenge.user_id == user_id,
            WebAuthnChallenge.purpose == purpose,
            WebAuthnChallenge.context_hash == hashlib.sha256(init_data.encode()).hexdigest(),
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
    now = datetime.now(UTC)
    raw_token = secrets.token_urlsafe(32)

    # This application currently enforces one active browser session per user.
    # Revoke prior sessions in the same transaction as issuing the replacement.
    db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
        .execution_options(synchronize_session=False)
    )
    expires = now + timedelta(seconds=settings.auth_session_ttl)
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
        secure=settings.app_env != "development",
        samesite="lax",
        max_age=settings.auth_session_ttl,
        path="/",
    )


@router.post("/registration/options")
def registration_options(
    request: Request,
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
    db: Session = Depends(get_db),
) -> dict:
    identity = verify_telegram_init_data(x_telegram_init_data)
    user = _get_or_create_user(db, identity["telegram_user_id"])
    _require_existing_passkey_session(request, db, user)
    settings = get_settings()
    existing = db.scalars(select(PasskeyCredential).where(
        PasskeyCredential.user_id == user.id, PasskeyCredential.revoked_at.is_(None)
    )).all()
    options = generate_registration_options(
        rp_id=settings.webauthn_rp_id,
        rp_name=settings.webauthn_rp_name,
        user_id=user.user_handle,
        user_name=f"telegram-user-{user.id}",
        user_display_name=identity["user"].get("first_name", "Telegram user"),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(item.credential_id))
            for item in existing
        ],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    challenge_id = _new_challenge(db, user, "registration", options.challenge, x_telegram_init_data)
    return {"challenge_id": challenge_id, "publicKey": json.loads(options_to_json(options))}


@router.post("/registration/verify")
def registration_verify(
    payload: FinishRequest,
    request: Request,
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
    db: Session = Depends(get_db),
) -> dict:
    identity = verify_telegram_init_data(x_telegram_init_data)
    user = _get_or_create_user(db, identity["telegram_user_id"])
    _require_existing_passkey_session(request, db, user)
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
    except Exception:  # noqa: BLE001 - normalize all verifier failures into an HTTP response
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
    # Discoverable credentials keep the response independent of account credential count.
    # This avoids exposing whether/how many Passkeys are registered for this Telegram identity.
    options = generate_authentication_options(
        rp_id=settings.webauthn_rp_id,
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
    except Exception:  # noqa: BLE001 - normalize all verifier failures into an HTTP response
        raise HTTPException(status_code=401, detail="Passkey authentication failed") from None
    credential.sign_count = verified.new_sign_count
    credential.device_type = str(verified.credential_device_type)
    credential.backed_up = verified.credential_backed_up
    _session_cookie(db, user, response)
    return {"authenticated": True}


def _new_handoff(db: Session, user: User, purpose: str = "authentication") -> str:
    settings = get_settings()
    raw_token = secrets.token_urlsafe(32)
    db.add(PasskeyHandoff(
        user_id=user.id,
        purpose=purpose,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.passkey_handoff_ttl_seconds),
    ))
    db.commit()
    return raw_token


def _consume_handoff(db: Session, raw_token: str, purpose: str = "authentication") -> int:
    now = datetime.now(UTC)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    user_id = db.execute(
        update(PasskeyHandoff)
        .where(
            PasskeyHandoff.token_hash == token_hash,
            PasskeyHandoff.purpose == purpose,
            PasskeyHandoff.consumed_at.is_(None),
            PasskeyHandoff.expires_at > now,
        )
        .values(consumed_at=now)
        .returning(PasskeyHandoff.user_id)
    ).scalar_one_or_none()
    db.commit()
    if user_id is None:
        raise HTTPException(status_code=400, detail="Handoff invalid, expired or already used")
    return user_id


def _consume_handoff_challenge(db: Session, challenge_id: str) -> tuple[int, bytes]:
    now = datetime.now(UTC)
    row = db.execute(
        update(WebAuthnChallenge)
        .where(
            WebAuthnChallenge.id == challenge_id,
            WebAuthnChallenge.purpose == "handoff_authentication",
            WebAuthnChallenge.consumed_at.is_(None),
            WebAuthnChallenge.expires_at > now,
        )
        .values(consumed_at=now)
        .returning(WebAuthnChallenge.user_id, WebAuthnChallenge.challenge)
    ).one_or_none()
    db.commit()
    if row is None:
        raise HTTPException(status_code=400, detail="Challenge invalid, expired or already used")
    return row.user_id, row.challenge


@router.post("/handoff")
def create_handoff(
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
    db: Session = Depends(get_db),
) -> dict:
    identity = verify_telegram_init_data(x_telegram_init_data)
    user = _get_or_create_user(db, identity["telegram_user_id"])
    settings = get_settings()
    return {
        "handoff_token": _new_handoff(db, user),
        "expires_in": settings.passkey_handoff_ttl_seconds,
    }


@router.post("/handoff/authentication/options")
def handoff_authentication_options(
    payload: HandoffOptionsRequest,
    db: Session = Depends(get_db),
) -> dict:
    user_id = _consume_handoff(db, payload.handoff_token)
    settings = get_settings()
    options = generate_authentication_options(
        rp_id=settings.webauthn_rp_id,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    challenge_id = str(uuid.uuid4())
    db.add(WebAuthnChallenge(
        id=challenge_id,
        user_id=user_id,
        purpose="handoff_authentication",
        challenge=options.challenge,
        context_hash=hashlib.sha256(payload.handoff_token.encode()).hexdigest(),
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.webauthn_challenge_ttl),
    ))
    db.commit()
    return {"challenge_id": challenge_id, "publicKey": json.loads(options_to_json(options))}


@router.post("/handoff/authentication/verify")
def handoff_authentication_verify(
    payload: HandoffVerifyRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    user_id, challenge = _consume_handoff_challenge(db, payload.challenge_id)
    credential_id = payload.credential.get("id")
    credential = db.scalar(select(PasskeyCredential).where(
        PasskeyCredential.credential_id == credential_id,
        PasskeyCredential.user_id == user_id,
        PasskeyCredential.revoked_at.is_(None),
    ))
    if credential is None:
        raise HTTPException(status_code=401, detail="Passkey authentication failed")
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
    except Exception:  # noqa: BLE001 - normalize all verifier failures into a generic response
        raise HTTPException(status_code=401, detail="Passkey authentication failed") from None
    credential.sign_count = verified.new_sign_count
    credential.device_type = str(verified.credential_device_type)
    credential.backed_up = verified.credential_backed_up
    _session_cookie(db, db.get(User, user_id), response)
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
            session.revoked_at = datetime.now(UTC)
            db.commit()
    response.delete_cookie(
        settings.auth_cookie_name,
        path="/",
        httponly=True,
        secure=settings.app_env != "development",
        samesite="lax",
    )
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
    active_credentials = db.scalars(select(PasskeyCredential).where(
        PasskeyCredential.user_id == user.id,
        PasskeyCredential.revoked_at.is_(None),
    )).all()
    if len(active_credentials) <= 1:
        raise HTTPException(
            status_code=409,
            detail="Register another Passkey before revoking the last one",
        )
    credential.revoked_at = datetime.now(UTC)
    db.commit()
    return {"revoked": True}


@router.get("")
def list_passkeys(
    request: Request,
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
    db: Session = Depends(get_db),
) -> dict:
    identity = verify_telegram_init_data(x_telegram_init_data)
    session = require_session(request, db)
    user = db.get(User, session.user_id)
    if user is None or user.telegram_user_id != identity["telegram_user_id"]:
        raise HTTPException(status_code=401, detail="Session identity mismatch")
    credentials = db.scalars(select(PasskeyCredential).where(
        PasskeyCredential.user_id == user.id,
        PasskeyCredential.revoked_at.is_(None),
    )).all()
    return {
        "credentials": [
            {
                "credential_id": item.credential_id,
                "name": item.name,
                "created_at": item.created_at.isoformat(),
                "device_type": item.device_type,
                "backed_up": item.backed_up,
            }
            for item in credentials
        ]
    }
