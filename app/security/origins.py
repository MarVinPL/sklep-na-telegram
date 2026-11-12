from fastapi import HTTPException, Request, status

from app.core.config import get_settings


def require_allowed_origin(request: Request) -> None:
    """Reject browser state-changing requests without an exact configured Origin."""
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return

    origin = request.headers.get("origin")
    settings = get_settings()
    if origin is None or origin not in settings.allowed_origins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request origin is not allowed",
        )
