"""Incident listing, detail, and statistics endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.incident import (
    IncidentListResponse,
    IncidentResponse,
    IncidentStatistics,
)
from app.services import incident_service

router = APIRouter(prefix="/api", tags=["incidents"])


@router.get("/incidents", response_model=IncidentListResponse)
async def list_incidents(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    status: str | None = Query(None, description="Filter by status"),
    severity: str | None = Query(None, description="Filter by severity"),
    alert_name: str | None = Query(None, description="Filter by alert name"),
    db: AsyncSession = Depends(get_db),
) -> IncidentListResponse:
    """Return a paginated, filterable list of incidents."""
    incidents, total = await incident_service.get_incidents(
        db, page=page, per_page=per_page, status=status, severity=severity, alert_name=alert_name
    )
    return IncidentListResponse(
        incidents=[IncidentResponse.model_validate(i) for i in incidents],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/incidents/{incident_id}", response_model=IncidentResponse)
async def get_incident(
    incident_id: int,
    db: AsyncSession = Depends(get_db),
) -> IncidentResponse:
    """Return a single incident by ID or 404."""
    incident = await incident_service.get_incident(db, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return IncidentResponse.model_validate(incident)


@router.get("/statistics", response_model=IncidentStatistics)
async def get_statistics(
    db: AsyncSession = Depends(get_db),
) -> IncidentStatistics:
    """Compute and return aggregate incident statistics."""
    stats = await incident_service.get_statistics(db)
    return IncidentStatistics(**stats)
