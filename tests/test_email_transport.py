from email.message import EmailMessage
from unittest.mock import MagicMock

import pytest

from app.core.config import Settings
from app.services import email as email_service


def test_email_is_disabled_without_smtp_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(email_service, "get_settings", lambda: Settings())
    with pytest.raises(email_service.EmailTransportNotConfigured):
        email_service.send_email(recipient="person@example.com", subject="Test", text_body="Body")


def test_smtp_requires_host_and_sender_together() -> None:
    with pytest.raises(ValueError):
        Settings(smtp_host="mail.example.com")


def test_smtp_requires_username_and_password_together() -> None:
    with pytest.raises(ValueError):
        Settings(
            smtp_host="mail.example.com", smtp_from_address="shop@example.com",
            smtp_username="operator",
        )


def test_smtp_rejects_two_tls_modes() -> None:
    with pytest.raises(ValueError):
        Settings(
            smtp_host="mail.example.com", smtp_from_address="shop@example.com",
            smtp_ssl=True, smtp_starttls=True,
        )


def test_smtp_uses_starttls_and_submits_plain_text(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        smtp_host="mail.example.com", smtp_from_address="shop@example.com",
    )
    client = MagicMock()
    client.__enter__.return_value = client
    monkeypatch.setattr(email_service, "get_settings", lambda: settings)
    monkeypatch.setattr(email_service.smtplib, "SMTP", lambda *args, **kwargs: client)

    email_service.send_email(
        recipient="person@example.com", subject="Verify", text_body="Verification message",
    )

    client.starttls.assert_called_once()
    sent = client.send_message.call_args.args[0]
    assert isinstance(sent, EmailMessage)
    assert sent["To"] == "person@example.com"
    assert sent["Subject"] == "Verify"


def test_smtp_failure_is_normalized_without_server_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        smtp_host="mail.example.com", smtp_from_address="shop@example.com",
        smtp_starttls=False,
    )
    client = MagicMock()
    client.__enter__.return_value = client
    client.send_message.side_effect = OSError("private server diagnostic")
    monkeypatch.setattr(email_service, "get_settings", lambda: settings)
    monkeypatch.setattr(email_service.smtplib, "SMTP", lambda *args, **kwargs: client)

    with pytest.raises(email_service.EmailDeliveryError) as error:
        email_service.send_email(
            recipient="person@example.com", subject="Verify", text_body="Body",
        )
    assert "private server diagnostic" not in str(error.value)

def test_production_smtp_rejects_plaintext_transport() -> None:
    with pytest.raises(ValueError, match="Production SMTP requires TLS"):
        Settings(
            app_env="production",
            database_url="postgresql+psycopg://shop:secret@db:5432/shop",
            telegram_bot_token="test-token",
            webauthn_rp_id="example.com",
            webauthn_origin="https://shop.example.com",
            smtp_host="mail.example.com",
            smtp_from_address="shop@example.com",
            smtp_starttls=False,
            smtp_ssl=False,
        )
