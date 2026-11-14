import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class RecoveryContactCryptoNotConfigured(RuntimeError):
    """Raised when the operator has not configured the contact-encryption key."""


def _fernet() -> Fernet:
    key = get_settings().recovery_contact_encryption_key.strip()
    if not key:
        raise RecoveryContactCryptoNotConfigured("Recovery contact encryption is not configured")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        raise RecoveryContactCryptoNotConfigured("Recovery contact encryption key is invalid") from None


def encrypt_contact(value: str) -> bytes:
    return _fernet().encrypt(value.encode("utf-8"))


def decrypt_contact(value: bytes) -> str:
    try:
        return _fernet().decrypt(value).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError):
        raise ValueError("Recovery contact ciphertext is invalid") from None


def contact_digest(value: str) -> str:
    key = get_settings().recovery_contact_encryption_key.strip()
    if not key:
        raise RecoveryContactCryptoNotConfigured("Recovery contact encryption is not configured")
    normalized = value.strip().casefold().encode("utf-8")
    return hmac.new(key.encode("ascii"), b"recovery-contact-index:v1:" + normalized, hashlib.sha256).hexdigest()
