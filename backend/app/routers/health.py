"""Health and readiness check endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict:
    """Liveness probe — always returns 200 if the process is running."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/ready")
async def readiness_check(response: Response) -> dict:
    """Readiness probe — verifies database connectivity."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ready", "database": "connected"}
    except Exception as exc:
        logger.error("Readiness check failed: %s", exc)
        response.status_code = 503
        return {"status": "not ready", "database": "disconnected", "error": str(exc)}
