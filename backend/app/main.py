"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.config import get_settings
from app.database import init_db
from app.routers import health, incidents, webhook
from app.utils.logging import get_logger, setup_logging

logger = get_logger(__name__)

_recovery_engine = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle events."""
    global _recovery_engine
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL)
    logger.info("Starting Cloud Monitoring Backend v1.0.0")
    await init_db()
    logger.info("Database initialised")

    if settings.RECOVERY_ENABLED:
        from app.recovery.engine import get_recovery_engine

        _recovery_engine = get_recovery_engine(settings)
        logger.info("Recovery engine started")

    yield

    # Shutdown
    if _recovery_engine is not None:
        from app.recovery.engine import reset_recovery_engine

        reset_recovery_engine()
        logger.info("Recovery engine shut down")
    logger.info("Cloud Monitoring Backend stopped")


app = FastAPI(
    title="Cloud Monitoring Backend",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(health.router)
app.include_router(webhook.router)
app.include_router(incidents.router)


@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError) -> JSONResponse:
    """Return 422 for Pydantic validation errors."""
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler that returns 500."""
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
