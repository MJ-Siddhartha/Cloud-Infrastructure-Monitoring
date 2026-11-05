"""Fault injection test case for systemd service termination scenario."""

import pytest
import httpx


def test_service_alert_evaluation(fault_env):
    """
    Validates Systemd Service alert rule expression evaluation in Prometheus:
    Expression: node_systemd_unit_state{state="failed"} == 1
    """
    prom_url = fault_env["prometheus_url"]
    query = 'node_systemd_unit_state{state="failed"}'
    
    try:
        res = httpx.get(f"{prom_url}/api/v1/query", params={"query": query}, timeout=5.0)
        assert res.status_code == 200
        data = res.json()
        assert data.get("status") == "success"
        assert "data" in data
    except httpx.ConnectError:
        pytest.skip("Prometheus server is not reachable")
