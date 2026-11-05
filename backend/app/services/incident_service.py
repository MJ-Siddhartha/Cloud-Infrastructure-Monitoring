"""Incident database operations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident
from app.utils.logging import get_logger

logger = get_logger(__name__)


async def create_incident(db: AsyncSession, alert_data: dict[str, Any]) -> Incident:
    """Create a new incident record from alert data."""
    incident = Incident(
        fingerprint=alert_data["fingerprint"],
        alert_name=alert_data["alert_name"],
        severity=alert_data.get("severity", "warning"),
        instance=alert_data.get("instance"),
        metric_name=alert_data.get("metric_name"),
        metric_value=alert_data.get("metric_value"),
        description=alert_data.get("description"),
        status="firing",
        started_at=alert_data["started_at"],
        webhook_payload=alert_data.get("webhook_payload"),
    )
    db.add(incident)
    await db.flush()
    await db.refresh(incident)
    logger.info(
        "Created incident id=%s alert_name=%s fingerprint=%s",
        incident.id,
        incident.alert_name,
        incident.fingerprint,
    )
    return incident


async def get_incident(db: AsyncSession, incident_id: int) -> Incident | None:
    """Fetch a single incident by primary key."""
    result = await db.execute(select(Incident).where(Incident.id == incident_id))
    return result.scalar_one_or_none()


async def get_incidents(
    db: AsyncSession,
    page: int = 1,
    per_page: int = 20,
    status: str | None = None,
    severity: str | None = None,
    alert_name: str | None = None,
) -> tuple[list[Incident], int]:
    """Return a paginated, optionally filtered list of incidents and total count."""
    query = select(Incident)
    count_query = select(func.count(Incident.id))

    if status:
        query = query.where(Incident.status == status)
        count_query = count_query.where(Incident.status == status)
    if severity:
        query = query.where(Incident.severity == severity)
        count_query = count_query.where(Incident.severity == severity)
    if alert_name:
        query = query.where(Incident.alert_name == alert_name)
        count_query = count_query.where(Incident.alert_name == alert_name)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * per_page
    query = query.order_by(Incident.created_at.desc()).offset(offset).limit(per_page)
    result = await db.execute(query)
    incidents = list(result.scalars().all())

    return incidents, total


async def find_firing_incident(db: AsyncSession, fingerprint: str) -> Incident | None:
    """Find an existing incident in 'firing' status by fingerprint."""
    result = await db.execute(
        select(Incident).where(
            Incident.fingerprint == fingerprint,
            Incident.status == "firing",
        )
    )
    return result.scalar_one_or_none()


async def resolve_incident(
    db: AsyncSession, fingerprint: str, resolved_at: datetime
) -> Incident | None:
    """Resolve a firing incident by fingerprint."""
    incident = await find_firing_incident(db, fingerprint)
    if incident is None:
        logger.warning("No firing incident found for fingerprint=%s to resolve", fingerprint)
        return None

    incident.status = "resolved"
    incident.resolved_at = resolved_at
    await db.flush()
    await db.refresh(incident)
    logger.info("Resolved incident id=%s fingerprint=%s", incident.id, fingerprint)
    return incident


async def update_recovery_status(
    db: AsyncSession,
    incident_id: int,
    status: str,
    output: str | None = None,
    error: str | None = None,
) -> Incident:
    """Update recovery fields on an incident."""
    result = await db.execute(select(Incident).where(Incident.id == incident_id))
    incident = result.scalar_one()

    incident.recovery_status = status
    if output is not None:
        incident.recovery_output = output
    if error is not None:
        incident.recovery_error = error

    now = datetime.now(timezone.utc)
    if status == "running":
        incident.recovery_started_at = now
    elif status in ("success", "failed"):
        incident.recovery_completed_at = now

    await db.flush()
    await db.refresh(incident)
    logger.info(
        "Updated recovery status for incident id=%s to %s", incident_id, status
    )
    return incident


async def get_statistics(db: AsyncSession) -> dict[str, Any]:
    """Compute aggregate statistics across all incidents."""
    total_result = await db.execute(select(func.count(Incident.id)))
    total_incidents = total_result.scalar() or 0

    firing_result = await db.execute(
        select(func.count(Incident.id)).where(Incident.status == "firing")
    )
    firing = firing_result.scalar() or 0

    resolved_result = await db.execute(
        select(func.count(Incident.id)).where(Incident.status == "resolved")
    )
    resolved = resolved_result.scalar() or 0

    # By severity
    severity_rows = await db.execute(
        select(Incident.severity, func.count(Incident.id)).group_by(Incident.severity)
    )
    by_severity = {row[0]: row[1] for row in severity_rows.all()}

    # By alert name
    alert_rows = await db.execute(
        select(Incident.alert_name, func.count(Incident.id)).group_by(Incident.alert_name)
    )
    by_alert = {row[0]: row[1] for row in alert_rows.all()}

    # Average resolution time
    avg_resolution_time: float | None = None
    resolved_incidents = await db.execute(
        select(Incident.started_at, Incident.resolved_at).where(
            Incident.status == "resolved",
            Incident.resolved_at.isnot(None),
        )
    )
    resolved_rows = resolved_incidents.all()
    if resolved_rows:
        deltas = []
        for row in resolved_rows:
            if row[0] and row[1]:
                delta = (row[1] - row[0]).total_seconds()
                deltas.append(delta)
        if deltas:
            avg_resolution_time = sum(deltas) / len(deltas)

    # Recovery counts
    success_result = await db.execute(
        select(func.count(Incident.id)).where(Incident.recovery_status == "success")
    )
    recovery_success = success_result.scalar() or 0

    failure_result = await db.execute(
        select(func.count(Incident.id)).where(Incident.recovery_status == "failed")
    )
    recovery_failure = failure_result.scalar() or 0

    return {
        "total_incidents": total_incidents,
        "firing": firing,
        "resolved": resolved,
        "by_severity": by_severity,
        "by_alert": by_alert,
        "avg_resolution_time_seconds": avg_resolution_time,
        "recovery_success_count": recovery_success,
        "recovery_failure_count": recovery_failure,
    }
