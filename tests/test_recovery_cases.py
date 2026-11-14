import json
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import create_app
from app.models import NotificationOutbox, RecoveryCase, RecoveryContact, User
from app.services.recovery_contact_crypto import decrypt_payload

ORIGIN = "http://localhost:5173"


def _make_client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    key = Fernet.generate_key().decode()
    settings = SimpleNamespace(
        app_name="test", app_env="development", allowed_origins=[ORIGIN],
        telegram_bot_token="test", telegram_init_data_max_age=300,
        webauthn_rp_id="localhost", webauthn_rp_name="test", webauthn_origin=ORIGIN,
        webauthn_challenge_ttl=180, auth_session_ttl=3600, auth_cookie_name="shop_session",
        auth_rate_limit_max_requests=50, auth_rate_limit_account_max_requests=50,
        auth_rate_limit_window_seconds=60, recovery_contact_encryption_key=key,
        smtp_host="", smtp_port=587, smtp_username="", smtp_password="", smtp_from_address="",
        smtp_starttls=True, smtp_ssl=False, smtp_timeout_seconds=3,
    )

    def override_get_db():
        with factory() as db:
            yield db

    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.origins.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.rate_limit.get_settings", lambda: settings)
    monkeypatch.setattr("app.routers.recovery_cases.verify_telegram_init_data", lambda raw: {"telegram_user_id": raw})
    monkeypatch.setattr("app.services.recovery_contact_crypto.get_settings", lambda: settings)
    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    return engine, factory, client


def _seed_recovery_user(factory, telegram_id="recover-me"):
    with factory() as db:
        user = User(telegram_user_id=telegram_id)
        db.add(user)
        db.flush()
        db.add(RecoveryContact(
            user_id=user.id,
            encrypted_email=b"encrypted-placeholder",
            email_digest=(telegram_id.encode().hex() + "0" * 64)[:64],
            verification_expires_at=datetime.now(UTC) + timedelta(days=1),
            verified_at=datetime.now(UTC),
        ))
        db.commit()


def test_recovery_contact_approval_and_veto_are_separate_one_use_actions(monkeypatch):
    engine, factory, client = _make_client(monkeypatch)
    _seed_recovery_user(factory)
    headers = {"Origin": ORIGIN, "X-Telegram-Init-Data": "recover-me"}
    started = client.post("/auth/passkeys/recovery/cases", headers=headers)
    assert started.status_code == 200
    case_id = started.json()["case_id"]
    with factory() as db:
        rows = db.scalars(
            select(NotificationOutbox).where(
                NotificationOutbox.event_key == f"{case_id}:case_started",
                NotificationOutbox.channel == "email",
            )
        ).all()
        payload = json.loads(decrypt_payload(rows[0].encrypted_payload))
        body = payload["body"]
        approval_token = body.split("Token zatwierdzenia kontaktu (ważny 15 minut): ")[1].splitlines()[0]
        veto_token = body.split("Token veto (ważny do 7 dni): ")[1].splitlines()[0]

    approved = client.post(
        f"/auth/passkeys/recovery/cases/{case_id}/contact-approval",
        headers={"Origin": ORIGIN},
        json={"token": approval_token},
    )
    assert approved.status_code == 200
    assert approved.json()["recorded"] is True

    with factory() as db:
        case = db.get(RecoveryCase, case_id)
        assert case.contact_approved_at is not None
        assert case.hold_started_at is None
        assert case.status == "awaiting_approvals"

    veto = client.post(
        f"/auth/passkeys/recovery/cases/{case_id}/veto",
        headers={"Origin": ORIGIN},
        json={"token": veto_token, "reason": "Nie rozpoznaję tego wniosku"},
    )
    assert veto.status_code == 200
    assert veto.json()["status"] == "manual_review"
    replay = client.post(
        f"/auth/passkeys/recovery/cases/{case_id}/veto",
        headers={"Origin": ORIGIN},
        json={"token": veto_token, "reason": "Ponowienie zgłoszenia veto"},
    )
    assert replay.status_code == 400

    with factory() as db:
        case = db.get(RecoveryCase, case_id)
        assert case.vetoed_at is not None
        assert case.status == "manual_review"
    client.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_telegram_init_data_only_starts_case_and_does_not_create_session(monkeypatch):
    engine, factory, client = _make_client(monkeypatch)
    _seed_recovery_user(factory)
    response = client.post(
        "/auth/passkeys/recovery/cases",
        headers={"Origin": ORIGIN, "X-Telegram-Init-Data": "recover-me"},
    )
    assert response.status_code == 200
    with factory() as db:
        assert db.scalar(select(RecoveryCase)) is not None
        assert db.scalar(select(User)).id is not None
    assert "shop_session" not in client.cookies
    client.close()
    Base.metadata.drop_all(engine)
    engine.dispose()
