import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import HTTPException, status

from app.core.config import get_settings


def verify_telegram_init_data(raw_init_data: str) -> dict:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise HTTPException(status_code=503, detail="Telegram authentication is not configured")
    if not raw_init_data or len(raw_init_data) > 16_384:
        raise HTTPException(status_code=400, detail="Invalid Telegram initData")

    try:
        pairs = parse_qsl(raw_init_data, keep_blank_values=True, strict_parsing=True)
        values = dict(pairs)
        if len(values) != len(pairs) or "hash" not in values or "user" not in values:
            raise ValueError("Missing or duplicate fields")
        received_hash = values.pop("hash")
        data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
        secret_key = hmac.new(b"WebAppData", settings.telegram_bot_token.encode(), hashlib.sha256).digest()
        expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_hash, received_hash):
            raise ValueError("Signature mismatch")
        auth_date = int(values["auth_date"])
        now = int(time.time())
        if auth_date > now + 30 or now - auth_date > settings.telegram_init_data_max_age:
            raise ValueError("Expired initData")
        user = json.loads(values["user"])
        telegram_user_id = str(user["id"])
        if not telegram_user_id.isdigit():
            raise ValueError("Invalid Telegram user")
        return {"telegram_user_id": telegram_user_id, "user": user}
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired Telegram initData") from None
