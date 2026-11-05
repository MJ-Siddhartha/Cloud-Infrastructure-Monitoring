"""Tests for the incidents API endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident


async def _create_test_incident(
    db: AsyncSession,
    alert_name: str = "TestAlert",
    severity: str = "warning",
    status: str = "firing",
    fingerprint: str = "fp-test",
    instance: str = "test-host:9090",
) -> Incident:
    """Helper to insert an incident directly into the DB."""
    incident = Incident(
        fingerprint=fingerprint,
        alert_name=alert_name,
        severity=severity,
        instance=instance,
        status=status,
        started_at=datetime.now(timezone.utc),
        description="Test incident",
    )
    db.add(incident)
    await db.flush()
    await db.refresh(incident)
    return incident


@pytest.mark.asyncio
async def test_list_incidents_with_pagination(client: AsyncClient, db_session: AsyncSession):
    for i in range(5):
        await _create_test_incident(db_session, fingerprint=f"fp-{i}")
    await db_session.commit()

    response = await client.get("/api/incidents", params={"page": 1, "per_page": 2})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 5
    assert len(data["incidents"]) == 2
    assert data["page"] == 1
    assert data["per_page"] == 2


@pytest.mark.asyncio
async def test_get_incident_by_id(client: AsyncClient, db_session: AsyncSession):
    inc = await _create_test_incident(db_session)
    await db_session.commit()

    response = await client.get(f"/api/incidents/{inc.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == inc.id
    assert data["alert_name"] == "TestAlert"


@pytest.mark.asyncio
async def test_get_nonexistent_incident_returns_404(client: AsyncClient):
    response = await client.get("/api/incidents/99999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_statistics_endpoint(client: AsyncClient, db_session: AsyncSession):
    await _create_test_incident(db_session, fingerprint="fp-1", status="firing", severity="critical")
    await _create_test_incident(db_session, fingerprint="fp-2", status="resolved", severity="warning")
    await db_session.commit()

    response = await client.get("/api/statistics")
    assert response.status_code == 200
    data = response.json()
    assert data["total_incidents"] == 2
    assert data["firing"] == 1
    assert data["resolved"] == 1
    assert "critical" in data["by_severity"]
    assert "warning" in data["by_severity"]


@pytest.mark.asyncio
async def test_filter_by_status(client: AsyncClient, db_session: AsyncSession):
    await _create_test_incident(db_session, fingerprint="fp-a", status="firing")
    await _create_test_incident(db_session, fingerprint="fp-b", status="resolved")
    await db_session.commit()

    response = await client.get("/api/incidents", params={"status": "firing"})
    data = response.json()
    assert data["total"] == 1
    assert data["incidents"][0]["status"] == "firing"


@pytest.mark.asyncio
async def test_filter_by_severity(client: AsyncClient, db_session: AsyncSession):
    await _create_test_incident(db_session, fingerprint="fp-c", severity="critical")
    await _create_test_incident(db_session, fingerprint="fp-d", severity="info")
    await db_session.commit()

    response = await client.get("/api/incidents", params={"severity": "critical"})
    data = response.json()
    assert data["total"] == 1
    assert data["incidents"][0]["severity"] == "critical"
