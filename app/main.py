from fastapi import FastAPI

from app.core.config import get_settings
from app.routers.passkeys import router as passkeys_router


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version="0.2.0",
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url=None,
    )

    @application.get("/healthz", tags=["health"])
    async def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    application.include_router(passkeys_router)
    return application


app = create_app()
