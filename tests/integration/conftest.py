"""Shared fixtures and configuration for integration testing."""

import os
import pytest
import httpx

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
ALERTMANAGER_URL = os.getenv("ALERTMANAGER_URL", "http://localhost:9093")
GRAFANA_URL = os.getenv("GRAFANA_URL", "http://localhost:3000")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


@pytest.fixture
def config_urls():
    return {
        "prometheus": PROMETHEUS_URL,
        "alertmanager": ALERTMANAGER_URL,
        "grafana": GRAFANA_URL,
        "backend": BACKEND_URL,
    }


@pytest.fixture
def firing_payload():
    return {
        "version": "4",
        "groupKey": "{}:{alertname=\"HighCPUUsage\",instance=\"node1:9100\"}",
        "status": "firing",
        "receiver": "webhook-backend",
        "groupLabels": {
            "alertname": "HighCPUUsage",
            "instance": "node1:9100"
        },
        "commonLabels": {
            "alertname": "HighCPUUsage",
            "instance": "node1:9100",
            "severity": "critical"
        },
        "commonAnnotations": {
            "summary": "Integration Test CPU High",
            "description": "Integration test payload description",
            "current_value": "91.2%",
            "recommended_action": "Check process table"
        },
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "HighCPUUsage",
                    "instance": "node1:9100",
                    "severity": "critical"
                },
                "annotations": {
                    "summary": "Integration Test CPU High",
                    "description": "Integration test payload description",
                    "current_value": "91.2%"
                },
                "startsAt": "2026-11-05T20:00:00Z",
                "fingerprint": "int_test_fp_001"
            }
        ]
    }


@pytest.fixture
def resolved_payload(firing_payload):
    payload = dict(firing_payload)
    payload["status"] = "resolved"
    payload["alerts"] = [
        {
            "status": "resolved",
            "labels": firing_payload["alerts"][0]["labels"],
            "annotations": firing_payload["alerts"][0]["annotations"],
            "startsAt": firing_payload["alerts"][0]["startsAt"],
            "endsAt": "2026-11-05T20:10:00Z",
            "fingerprint": firing_payload["alerts"][0]["fingerprint"]
        }
    ]
    return payload
