"""Integration tests validating the entire monitoring and alert pipeline."""

import pytest
import httpx


def test_fastapi_health(config_urls):
    """Test that FastAPI backend health endpoint responds with 200."""
    try:
        res = httpx.get(f"{config_urls['backend']}/health", timeout=5.0)
        assert res.status_code == 200
        data = res.json()
        assert data.get("status") == "healthy"
    except httpx.ConnectError:
        pytest.skip("Backend is not running locally")


def test_fastapi_webhook_ingestion(config_urls, firing_payload):
    """Test webhook ingestion of firing alert."""
    try:
        res = httpx.post(
            f"{config_urls['backend']}/webhook/alertmanager",
            json=firing_payload,
            timeout=5.0,
        )
        assert res.status_code == 200
        data = res.json()
        assert data.get("status") == "accepted"
        assert data.get("processed") >= 1
    except httpx.ConnectError:
        pytest.skip("Backend is not running locally")


def test_incidents_api(config_urls):
    """Test retrieving incidents from database via REST API."""
    try:
        res = httpx.get(f"{config_urls['backend']}/api/incidents?page=1&per_page=10", timeout=5.0)
        assert res.status_code == 200
        data = res.json()
        assert "incidents" in data
        assert "total" in data
    except httpx.ConnectError:
        pytest.skip("Backend is not running locally")


def test_incidents_statistics_api(config_urls):
    """Test incident statistics calculation."""
    try:
        res = httpx.get(f"{config_urls['backend']}/api/statistics", timeout=5.0)
        assert res.status_code == 200
        data = res.json()
        assert "total_incidents" in data
        assert "by_severity" in data
    except httpx.ConnectError:
        pytest.skip("Backend is not running locally")


def test_webhook_resolved_update(config_urls, resolved_payload):
    """Test that resolved webhook updates incident state."""
    try:
        res = httpx.post(
            f"{config_urls['backend']}/webhook/alertmanager",
            json=resolved_payload,
            timeout=5.0,
        )
        assert res.status_code == 200
    except httpx.ConnectError:
        pytest.skip("Backend is not running locally")


def test_prometheus_rules_endpoint(config_urls):
    """Test Prometheus rules endpoint to ensure all rules are loaded."""
    try:
        res = httpx.get(f"{config_urls['prometheus']}/api/v1/rules", timeout=5.0)
        assert res.status_code == 200
        data = res.json()
        assert data.get("status") == "success"
    except httpx.ConnectError:
        pytest.skip("Prometheus is not running locally")


def test_alertmanager_status(config_urls):
    """Test Alertmanager status API."""
    try:
        res = httpx.get(f"{config_urls['alertmanager']}/api/v2/status", timeout=5.0)
        assert res.status_code == 200
    except httpx.ConnectError:
        pytest.skip("Alertmanager is not running locally")
