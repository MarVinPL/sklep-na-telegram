from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routers.passkeys import router as passkeys_router
from app.routers.recovery_cases import router as recovery_cases_router
from app.routers.recovery_contact import router as recovery_contact_router
from app.routers.recovery_operators import router as recovery_operators_router


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version="0.2.0",
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url=None,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Telegram-Init-Data"],
        max_age=600,
    )

    @application.get("/healthz", tags=["health"])
    async def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    application.include_router(passkeys_router)
    application.include_router(recovery_contact_router)
    application.include_router(recovery_cases_router)
    application.include_router(recovery_operators_router)
    return application


app = create_app()
