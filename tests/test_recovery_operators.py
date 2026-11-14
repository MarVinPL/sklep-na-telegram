import hashlib
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import create_app
from app.models import AuthSession, RecoveryCase, RecoveryContact, SecurityOperator, User

ORIGIN = "http://localhost:5173"
SESSION = "operator-test-session"


@pytest.fixture
def operator_client(monkeypatch: pytest.MonkeyPatch) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        with factory() as db:
            yield db

    settings = SimpleNamespace(
        app_name="test", app_env="development", allowed_origins=[ORIGIN],
        telegram_bot_token="test", telegram_init_data_max_age=300,
        webauthn_rp_id="localhost", webauthn_rp_name="test", webauthn_origin=ORIGIN,
        webauthn_challenge_ttl=180, auth_session_ttl=3600, auth_cookie_name="shop_session",
        auth_rate_limit_max_requests=50, auth_rate_limit_account_max_requests=50,
        auth_rate_limit_window_seconds=60, recovery_contact_encryption_key=Fernet.generate_key().decode(),
        smtp_host="", smtp_port=587, smtp_username="", smtp_password="", smtp_from_address="",
        smtp_starttls=True, smtp_ssl=False, smtp_timeout_seconds=3,
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.origins.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.rate_limit.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.sessions.get_settings", lambda: settings)
    monkeypatch.setattr("app.routers.recovery_contact.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.recovery_contact_crypto.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.telegram.verify_telegram_init_data", lambda raw: {"telegram_user_id": raw})
    monkeypatch.setattr("app.routers.recovery_contact.verify_telegram_init_data", lambda raw: {"telegram_user_id": raw})
    monkeypatch.setattr("app.routers.recovery_operators.verify_telegram_init_data", lambda raw: {"telegram_user_id": raw})
    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client, factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def seed(factory, *telegram_ids: str) -> dict[str, int]:
    result = {}
    with factory() as db:
        for telegram_id in telegram_ids:
            user = User(telegram_user_id=telegram_id)
            db.add(user)
            db.flush()
            result[telegram_id] = user.id
            db.add(AuthSession(
                user_id=user.id,
                token_hash=hashlib.sha256(f"{SESSION}-{telegram_id}".encode()).hexdigest(),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ))
        db.commit()
    return result


def test_tenant_user_cannot_request_operator_change(operator_client):
    client, factory = operator_client
    seed(factory, "requester", "target")
    client.cookies.set("shop_session", f"{SESSION}-requester")
    response = client.post(
        "/auth/passkeys/recovery-operators/changes",
        headers={"Origin": ORIGIN, "X-Telegram-Init-Data": "requester"},
        json={"target_telegram_user_id": "target", "action": "grant", "reason": "Add operator after review"},
    )
    assert response.status_code == 403


def test_operator_change_requires_two_distinct_approvals(operator_client):
    client, factory = operator_client
    ids = seed(factory, "requester", "target", "operator-b")
    with factory() as db:
        db.add(SecurityOperator(user_id=ids["requester"], grant_reason="bootstrap"))
        db.add(SecurityOperator(user_id=ids["operator-b"], grant_reason="bootstrap"))
        db.commit()
    client.cookies.set("shop_session", f"{SESSION}-requester")
    created = client.post(
        "/auth/passkeys/recovery-operators/changes",
        headers={"Origin": ORIGIN, "X-Telegram-Init-Data": "requester"},
        json={"target_telegram_user_id": "target", "action": "grant", "reason": "Grant after independent vetting"},
    )
    assert created.status_code == 200
    assert created.json()["approvals_recorded"] == 1
    request_id = created.json()["request_id"]

    client.cookies.set("shop_session", f"{SESSION}-operator-b")
    queue = client.get(
        "/auth/passkeys/recovery-operators/changes",
        headers={"Origin": ORIGIN, "X-Telegram-Init-Data": "operator-b"},
    )
    assert queue.status_code == 200
    assert queue.json()["requests"][0]["request_id"] == request_id
    second = client.post(
        f"/auth/passkeys/recovery-operators/changes/{request_id}/approval",
        headers={"Origin": ORIGIN, "X-Telegram-Init-Data": "operator-b"},
        json={"decision": "approve", "reason": "Independent second approval"},
    )
    assert second.status_code == 200
    assert second.json()["status"] == "approved"
    with factory() as db:
        assert db.get(SecurityOperator, ids["target"]).revoked_at is None


def test_operator_cannot_decide_own_recovery_and_case_decision_is_unique(operator_client):
    client, factory = operator_client
    ids = seed(factory, "operator", "target")
    with factory() as db:
        db.add(SecurityOperator(user_id=ids["operator"], grant_reason="bootstrap"))
        db.add(RecoveryContact(
            user_id=ids["target"], encrypted_email=b"ciphertext", email_digest="d" * 64,
            verification_expires_at=datetime.now(UTC) + timedelta(days=1),
            verified_at=datetime.now(UTC),
        ))
        db.add(RecoveryCase(
            id="7b4b1d6e-9d6f-4e91-8c27-9b35b8f53e2a",
            user_id=ids["target"],
            status="awaiting_approvals",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ))
        db.commit()
    client.cookies.set("shop_session", f"{SESSION}-operator")
    path = "/auth/passkeys/recovery-operators/cases/7b4b1d6e-9d6f-4e91-8c27-9b35b8f53e2a/decision"
    body = {"recovery_telegram_user_id": "target", "decision": "approve", "reason": "Reviewed independent evidence"}
    headers = {"Origin": ORIGIN, "X-Telegram-Init-Data": "operator"}
    assert client.post(path, headers=headers, json=body).status_code == 200
    assert client.post(path, headers=headers, json=body).status_code == 409
    own = {**body, "recovery_telegram_user_id": "operator"}
    assert client.post(path, headers=headers, json=own).status_code == 403
