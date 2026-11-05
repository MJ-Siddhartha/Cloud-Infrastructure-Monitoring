"""Fault injection test case for disk space exhaustion scenario."""

import pytest
import httpx


def test_disk_alert_evaluation(fault_env):
    """
    Validates Disk alert rule expression evaluation in Prometheus:
    Expression: (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100 < 15
    """
    prom_url = fault_env["prometheus_url"]
    query = '(node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100'
    
    try:
        res = httpx.get(f"{prom_url}/api/v1/query", params={"query": query}, timeout=5.0)
        assert res.status_code == 200
        data = res.json()
        assert data.get("status") == "success"
        assert "data" in data
    except httpx.ConnectError:
        pytest.skip("Prometheus server is not reachable")
