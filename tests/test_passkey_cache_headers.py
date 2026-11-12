from fastapi import Response

from app.routers.passkeys import _prevent_cache


def test_passkey_router_responses_are_marked_non_cacheable() -> None:
    response = Response()

    _prevent_cache(response)

    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate, private"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["expires"] == "0"
