import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException

from app.security import telegram


def signed_init_data(bot_token: str, auth_date: int) -> str:
    fields = {
        "auth_date": str(auth_date),
        "user": json.dumps({"id": 123456789, "first_name": "Test"}, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_valid_telegram_init_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        telegram,
        "get_settings",
        lambda: SimpleNamespace(telegram_bot_token="test-token", telegram_init_data_max_age=300),
    )
    raw = signed_init_data("test-token", int(time.time()))

    result = telegram.verify_telegram_init_data(raw)

    assert result["telegram_user_id"] == "123456789"


def test_expired_telegram_init_data_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        telegram,
        "get_settings",
        lambda: SimpleNamespace(telegram_bot_token="test-token", telegram_init_data_max_age=60),
    )
    raw = signed_init_data("test-token", int(time.time()) - 120)

    with pytest.raises(HTTPException) as error:
        telegram.verify_telegram_init_data(raw)

    assert error.value.status_code == 401


def test_tampered_telegram_init_data_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        telegram,
        "get_settings",
        lambda: SimpleNamespace(telegram_bot_token="test-token", telegram_init_data_max_age=300),
    )
    raw = signed_init_data("test-token", int(time.time())).replace("Test", "Attacker")

    with pytest.raises(HTTPException) as error:
        telegram.verify_telegram_init_data(raw)

    assert error.value.status_code == 401
