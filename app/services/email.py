"""Optional operator-configured SMTP transport.

Persistence, retry, idempotency, and recovery authorization belong to callers.
"""

import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import get_settings


class EmailTransportNotConfigured(RuntimeError):
    """Raised when outbound email is disabled."""


class EmailDeliveryError(RuntimeError):
    """Raised when SMTP cannot accept a message."""


def send_email(*, recipient: str, subject: str, text_body: str) -> None:
    """Submit one plain-text email without exposing SMTP diagnostics or secrets."""
    settings = get_settings()
    if not settings.smtp_host.strip() or not settings.smtp_from_address.strip():
        raise EmailTransportNotConfigured("Outbound email is not configured")

    message = EmailMessage()
    try:
        message["From"] = settings.smtp_from_address
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(text_body)
    except (TypeError, ValueError):
        raise EmailDeliveryError("Email message headers are invalid") from None

    try:
        if settings.smtp_ssl:
            with smtplib.SMTP_SSL(
                settings.smtp_host, settings.smtp_port,
                timeout=settings.smtp_timeout_seconds,
                context=ssl.create_default_context(),
            ) as client:
                if settings.smtp_username:
                    client.login(settings.smtp_username, settings.smtp_password)
                client.send_message(message)
        else:
            with smtplib.SMTP(
                settings.smtp_host, settings.smtp_port,
                timeout=settings.smtp_timeout_seconds,
            ) as client:
                client.ehlo()
                if settings.smtp_starttls:
                    client.starttls(context=ssl.create_default_context())
                    client.ehlo()
                if settings.smtp_username:
                    client.login(settings.smtp_username, settings.smtp_password)
                client.send_message(message)
    except (OSError, smtplib.SMTPException):
        raise EmailDeliveryError("SMTP delivery failed") from None
