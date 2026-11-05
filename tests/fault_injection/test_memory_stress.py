"""Fault injection test case for memory saturation scenario."""

import pytest
import httpx


def test_memory_alert_evaluation(fault_env):
    """
    Validates Memory alert rule expression evaluation in Prometheus:
    Expression: (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100 > 85
    """
    prom_url = fault_env["prometheus_url"]
    query = '(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100'
    
    try:
        res = httpx.get(f"{prom_url}/api/v1/query", params={"query": query}, timeout=5.0)
        assert res.status_code == 200
        data = res.json()
        assert data.get("status") == "success"
        assert "data" in data
    except httpx.ConnectError:
        pytest.skip("Prometheus server is not reachable")
