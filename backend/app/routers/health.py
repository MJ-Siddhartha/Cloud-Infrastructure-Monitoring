"""Health and readiness check endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
import time

from fastapi import APIRouter, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["health"])

_START_TIME = time.time()


@router.get("/health")
async def health_check() -> dict:
    """Liveness probe — always returns 200 if the process is running."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics_endpoint() -> str:
    """Prometheus exposition metrics endpoint."""
    uptime = time.time() - _START_TIME
    db_ok = 0
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        db_ok = 1
    except Exception:
        db_ok = 0

    lines = [
        "# HELP backend_up Whether the backend service is running",
        "# TYPE backend_up gauge",
        "backend_up 1",
        "# HELP backend_uptime_seconds Uptime in seconds",
        "# TYPE backend_uptime_seconds counter",
        f"backend_uptime_seconds {uptime:.2f}",
        "# HELP backend_database_connected Database connection status",
        "# TYPE backend_database_connected gauge",
        f"backend_database_connected {db_ok}",
        "",
    ]
    return "\n".join(lines)


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
