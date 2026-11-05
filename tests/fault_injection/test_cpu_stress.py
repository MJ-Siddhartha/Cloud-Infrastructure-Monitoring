"""Fault injection test case for CPU saturation scenario."""

import time
import pytest
import httpx


def test_cpu_alert_detection(fault_env):
    """
    Validates CPU alert rule expression evaluation in Prometheus:
    Expression: 100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 85
    """
    prom_url = fault_env["prometheus_url"]
    query = '100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)'
    
    try:
        res = httpx.get(f"{prom_url}/api/v1/query", params={"query": query}, timeout=5.0)
        assert res.status_code == 200
        data = res.json()
        assert data.get("status") == "success"
        # The query should successfully return a result format
        assert "data" in data
    except httpx.ConnectError:
        pytest.skip("Prometheus server is not reachable")
