import pytest

from app.services import recovery_contact_crypto as crypto


def test_contact_encryption_round_trip_and_digest_is_normalized(monkeypatch):
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    monkeypatch.setattr(
        crypto,
        "get_settings",
        lambda: type("Settings", (), {"recovery_contact_encryption_key": key})(),
    )
    encrypted = crypto.encrypt_contact("Contact@Example.com")
    assert encrypted != b"Contact@Example.com"
    assert crypto.decrypt_contact(encrypted) == "Contact@Example.com"
    assert crypto.contact_digest("Contact@Example.com") == crypto.contact_digest(" contact@example.COM ")


def test_crypto_fails_closed_without_key(monkeypatch):
    monkeypatch.setattr(
        crypto,
        "get_settings",
        lambda: type("Settings", (), {"recovery_contact_encryption_key": ""})(),
    )
    with pytest.raises(crypto.RecoveryContactCryptoNotConfigured):
        crypto.encrypt_contact("contact@example.com")
