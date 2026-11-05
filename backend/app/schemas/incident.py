"""Pydantic schemas for incident API responses."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class IncidentBase(BaseModel):
    """Base incident fields."""

    alert_name: str
    severity: str = "warning"
    instance: str | None = None
    description: str | None = None
    status: str = "firing"


class IncidentResponse(BaseModel):
    """Full incident response with all fields."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    fingerprint: str
    alert_name: str
    severity: str
    instance: str | None = None
    metric_name: str | None = None
    metric_value: str | None = None
    description: str | None = None
    status: str
    started_at: datetime
    resolved_at: datetime | None = None
    acknowledged_at: datetime | None = None
    webhook_payload: dict | None = None
    recovery_action: str | None = None
    recovery_status: str | None = None
    recovery_started_at: datetime | None = None
    recovery_completed_at: datetime | None = None
    recovery_output: str | None = None
    recovery_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class IncidentListResponse(BaseModel):
    """Paginated list of incidents."""

    incidents: list[IncidentResponse]
    total: int
    page: int
    per_page: int


class IncidentStatistics(BaseModel):
    """Aggregate statistics about incidents."""

    total_incidents: int
    firing: int
    resolved: int
    by_severity: dict[str, int]
    by_alert: dict[str, int]
    avg_resolution_time_seconds: float | None = None
    recovery_success_count: int
    recovery_failure_count: int
