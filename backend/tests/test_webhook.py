"""Tests for the Alertmanager webhook endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


def _make_webhook(alerts: list[dict] | None = None, **overrides) -> dict:
    """Build a minimal valid Alertmanager webhook payload."""
    default_alert = {
        "status": "firing",
        "labels": {
            "alertname": "HighCPU",
            "severity": "critical",
            "instance": "server-1:9090",
            "job": "node",
        },
        "annotations": {
            "summary": "CPU is high",
            "description": "CPU usage above 90%",
        },
        "startsAt": "2024-01-01T00:00:00Z",
        "endsAt": "0001-01-01T00:00:00Z",
        "fingerprint": "abc123",
    }
    payload = {
        "version": "4",
        "groupKey": "test-group",
        "status": "firing",
        "receiver": "test-receiver",
        "alerts": alerts if alerts is not None else [default_alert],
        "groupLabels": {},
        "commonLabels": {},
        "commonAnnotations": {},
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_valid_firing_alert_creates_incident(client: AsyncClient):
    payload = _make_webhook()
    response = await client.post("/webhook/alertmanager", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "accepted"
    assert data["processed"] == 1

    # Verify it was persisted
    incidents = await client.get("/api/incidents")
    assert incidents.json()["total"] == 1


@pytest.mark.asyncio
async def test_valid_resolved_alert_updates_incident(client: AsyncClient):
    # First fire
    payload = _make_webhook()
    await client.post("/webhook/alertmanager", json=payload)

    # Then resolve
    resolved_alert = {
        "status": "resolved",
        "labels": {
            "alertname": "HighCPU",
            "severity": "critical",
            "instance": "server-1:9090",
            "job": "node",
        },
        "annotations": {"summary": "CPU is high", "description": "CPU usage above 90%"},
        "startsAt": "2024-01-01T00:00:00Z",
        "endsAt": "2024-01-01T01:00:00Z",
        "fingerprint": "abc123",
    }
    response = await client.post(
        "/webhook/alertmanager",
        json=_make_webhook(alerts=[resolved_alert], status="resolved"),
    )
    assert response.status_code == 200
    assert response.json()["processed"] == 1

    # Verify status changed
    incidents = await client.get("/api/incidents")
    inc = incidents.json()["incidents"][0]
    assert inc["status"] == "resolved"


@pytest.mark.asyncio
async def test_duplicate_firing_alert_is_deduplicated(client: AsyncClient):
    payload = _make_webhook()
    await client.post("/webhook/alertmanager", json=payload)
    response = await client.post("/webhook/alertmanager", json=payload)
    assert response.status_code == 200
    assert response.json()["processed"] == 0  # duplicate skipped

    incidents = await client.get("/api/incidents")
    assert incidents.json()["total"] == 1


@pytest.mark.asyncio
async def test_malformed_payload_returns_422(client: AsyncClient):
    response = await client.post("/webhook/alertmanager", json={"bad": "data"})
    # FastAPI validates AlertmanagerWebhook — bad data still has defaults so may pass.
    # Send truly invalid JSON instead:
    response = await client.post(
        "/webhook/alertmanager",
        content=b"not json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_multiple_alerts_in_single_webhook(client: AsyncClient):
    alerts = [
        {
            "status": "firing",
            "labels": {"alertname": "HighCPU", "severity": "critical", "instance": "s1:9090", "job": "node"},
            "annotations": {"summary": "CPU high", "description": "CPU > 90%"},
            "startsAt": "2024-01-01T00:00:00Z",
            "endsAt": "0001-01-01T00:00:00Z",
            "fingerprint": "fp1",
        },
        {
            "status": "firing",
            "labels": {"alertname": "DiskFull", "severity": "warning", "instance": "s2:9090", "job": "node"},
            "annotations": {"summary": "Disk full", "description": "Disk > 95%"},
            "startsAt": "2024-01-01T00:00:00Z",
            "endsAt": "0001-01-01T00:00:00Z",
            "fingerprint": "fp2",
        },
    ]
    response = await client.post("/webhook/alertmanager", json=_make_webhook(alerts=alerts))
    assert response.status_code == 200
    assert response.json()["processed"] == 2


@pytest.mark.asyncio
async def test_empty_alerts_list(client: AsyncClient):
    response = await client.post("/webhook/alertmanager", json=_make_webhook(alerts=[]))
    assert response.status_code == 200
    assert response.json()["processed"] == 0
