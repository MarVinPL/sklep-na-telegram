import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    OperatorChangeApproval,
    OperatorChangeRequest,
    RecoveryContact,
    RecoveryOperatorDecision,
    SecurityOperator,
    User,
)
from app.security.origins import require_allowed_origin
from app.security.rate_limit import enforce_ip_rate_limit
from app.security.sessions import require_session
from app.security.telegram import verify_telegram_init_data

router = APIRouter(
    prefix="/auth/passkeys/recovery-operators",
    tags=["recovery-operators"],
    dependencies=[Depends(require_allowed_origin), Depends(enforce_ip_rate_limit)],
)


class ChangeRequestBody(BaseModel):
    target_telegram_user_id: str = Field(min_length=1, max_length=32)
    action: str = Field(pattern="^(grant|revoke)$")
    reason: str = Field(min_length=12, max_length=1000)


class ChangeApprovalBody(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    reason: str = Field(min_length=12, max_length=1000)


class CaseDecisionBody(BaseModel):
    recovery_telegram_user_id: str = Field(min_length=1, max_length=32)
    decision: str = Field(pattern="^(approve|reject)$")
    reason: str = Field(min_length=12, max_length=1000)


def _current_user(request: Request, db: Session, init_data: str) -> User:
    identity = verify_telegram_init_data(init_data)
    session = require_session(request, db)
    user = db.get(User, session.user_id)
    if user is None or user.telegram_user_id != identity["telegram_user_id"]:
        raise HTTPException(status_code=401, detail="Session identity mismatch")
    return user


def _require_operator(db: Session, user_id: int) -> SecurityOperator:
    operator = db.scalar(
        select(SecurityOperator).where(
            SecurityOperator.user_id == user_id,
            SecurityOperator.revoked_at.is_(None),
        )
    )
    if operator is None:
        raise HTTPException(status_code=403, detail="Security operator role required")
    return operator


@router.post("/changes")
def request_operator_change(
    payload: ChangeRequestBody,
    request: Request,
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
    db: Session = Depends(get_db),
) -> dict:
    requester = _current_user(request, db, x_telegram_init_data)
    _require_operator(db, requester.id)
    target = db.scalar(select(User).where(User.telegram_user_id == payload.target_telegram_user_id))
    if target is None:
        raise HTTPException(status_code=404, detail="Target account not found")
    if target.id == requester.id:
        raise HTTPException(status_code=409, detail="Operators cannot change their own role")
    active = db.get(SecurityOperator, target.id)
    if payload.action == "grant" and active is not None and active.revoked_at is None:
        raise HTTPException(status_code=409, detail="Target is already an active operator")
    if payload.action == "revoke" and (active is None or active.revoked_at is not None):
        raise HTTPException(status_code=409, detail="Target is not an active operator")
    change = OperatorChangeRequest(
        id=str(uuid.uuid4()),
        target_user_id=target.id,
        requested_by_user_id=requester.id,
        action=payload.action,
        reason=payload.reason.strip(),
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    db.add(change)
    db.flush()
    db.add(OperatorChangeApproval(
        request_id=change.id,
        approver_user_id=requester.id,
        decision="approve",
        reason=payload.reason.strip(),
    ))
    db.commit()
    return {"request_id": change.id, "status": change.status, "approvals_required": 2, "approvals_recorded": 1}


@router.post("/changes/{request_id}/approval")
def approve_operator_change(
    request_id: str,
    payload: ChangeApprovalBody,
    request: Request,
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
    db: Session = Depends(get_db),
) -> dict:
    approver = _current_user(request, db, x_telegram_init_data)
    _require_operator(db, approver.id)
    change = db.scalar(
        select(OperatorChangeRequest)
        .where(OperatorChangeRequest.id == request_id)
        .with_for_update()
    )
    now = datetime.now(UTC)
    if change is None or change.status != "pending" or change.expires_at <= now:
        raise HTTPException(status_code=409, detail="Operator change request is unavailable")
    if approver.id in {change.requested_by_user_id, change.target_user_id}:
        raise HTTPException(status_code=403, detail="Requester and target cannot approve this change")
    existing = db.scalar(
        select(OperatorChangeApproval).where(
            OperatorChangeApproval.request_id == change.id,
            OperatorChangeApproval.approver_user_id == approver.id,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Operator has already decided this request")
    db.add(OperatorChangeApproval(
        request_id=change.id,
        approver_user_id=approver.id,
        decision=payload.decision,
        reason=payload.reason.strip(),
    ))
    if payload.decision == "reject":
        change.status = "rejected"
        change.decided_at = now
        db.commit()
        return {"status": "rejected"}
    db.flush()
    approvals = db.scalar(
        select(func.count(OperatorChangeApproval.id)).where(
            OperatorChangeApproval.request_id == change.id,
            OperatorChangeApproval.decision == "approve",
        )
    ) or 0
    if approvals >= 2:
        target_operator = db.get(SecurityOperator, change.target_user_id)
        if change.action == "grant":
            if target_operator is not None and target_operator.revoked_at is None:
                change.status = "conflict"
            elif target_operator is None:
                db.add(SecurityOperator(
                    user_id=change.target_user_id,
                    granted_by_user_id=change.requested_by_user_id,
                    grant_reason=change.reason,
                    granted_at=now,
                ))
                change.status = "approved"
            else:
                target_operator.granted_by_user_id = change.requested_by_user_id
                target_operator.grant_reason = change.reason
                target_operator.granted_at = now
                target_operator.revoked_at = None
                target_operator.revoked_by_user_id = None
                target_operator.revocation_reason = None
                change.status = "approved"
        elif target_operator is None or target_operator.revoked_at is not None:
            change.status = "conflict"
        else:
            target_operator.revoked_at = now
            target_operator.revoked_by_user_id = approver.id
            target_operator.revocation_reason = change.reason
            change.status = "approved"
        change.decided_at = now
    db.commit()
    return {"status": change.status, "approvals": approvals, "approvals_required": 2}


@router.post("/cases/{case_id}/decision")
def record_recovery_operator_decision(
    case_id: str,
    payload: CaseDecisionBody,
    request: Request,
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
    db: Session = Depends(get_db),
) -> dict:
    try:
        normalized_case_id = str(uuid.UUID(case_id))
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid recovery case identifier") from None
    operator = _current_user(request, db, x_telegram_init_data)
    _require_operator(db, operator.id)
    recovery_user = db.scalar(select(User).where(User.telegram_user_id == payload.recovery_telegram_user_id))
    if recovery_user is None:
        raise HTTPException(status_code=404, detail="Recovery account not found")
    if recovery_user.id == operator.id:
        raise HTTPException(status_code=403, detail="Recovery contact and security operator must be different principals")
    contact = db.get(RecoveryContact, recovery_user.id)
    if contact is None or contact.verified_at is None:
        raise HTTPException(status_code=409, detail="A verified recovery contact is required")
    db.add(RecoveryOperatorDecision(
        case_id=normalized_case_id,
        recovery_user_id=recovery_user.id,
        operator_user_id=operator.id,
        decision=payload.decision,
        reason=payload.reason.strip(),
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Operator already decided this recovery case") from None
    return {"recorded": True, "decision": payload.decision}
