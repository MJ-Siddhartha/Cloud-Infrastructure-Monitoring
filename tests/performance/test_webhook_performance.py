"""Performance and stress benchmarks for FastAPI Alertmanager webhook ingestion."""

import time
import asyncio
import statistics
import pytest
import httpx


@pytest.mark.asyncio
async def test_single_webhook_latency(backend_url):
    """Measures single webhook processing time."""
    payload = {
        "version": "4",
        "groupKey": "perf-single",
        "status": "firing",
        "receiver": "webhook-backend",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "PerfSingle", "instance": "perf:9100", "severity": "warning"},
                "annotations": {"description": "Single test"},
                "startsAt": "2026-11-05T20:00:00Z",
                "fingerprint": f"perf_{time.time()}"
            }
        ]
    }
    
    async with httpx.AsyncClient() as client:
        try:
            start = time.perf_counter()
            res = await client.post(f"{backend_url}/webhook/alertmanager", json=payload, timeout=5.0)
            elapsed_ms = (time.perf_counter() - start) * 1000
            assert res.status_code == 200
            assert elapsed_ms < 100.0, f"Expected < 100ms, got {elapsed_ms:.2f}ms"
        except httpx.ConnectError:
            pytest.skip("Backend is not running locally")


@pytest.mark.asyncio
async def test_concurrent_webhook_latency_percentiles(backend_url):
    """Measures p50, p95, p99 latency under concurrent alert payloads."""
    concurrency = 30
    latencies = []

    async def send_alert(client, idx):
        payload = {
            "version": "4",
            "groupKey": f"perf-batch-{idx}",
            "status": "firing",
            "receiver": "webhook-backend",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": f"BatchAlert_{idx}", "instance": f"node-{idx}:9100", "severity": "warning"},
                    "annotations": {"description": f"Batch sample {idx}"},
                    "startsAt": "2026-11-05T20:00:00Z",
                    "fingerprint": f"batch_{idx}_{time.time()}"
                }
            ]
        }
        start = time.perf_counter()
        res = await client.post(f"{backend_url}/webhook/alertmanager", json=payload, timeout=10.0)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert res.status_code == 200
        latencies.append(elapsed_ms)

    async with httpx.AsyncClient() as client:
        try:
            tasks = [send_alert(client, i) for i in range(concurrency)]
            await asyncio.gather(*tasks)
            
            p50 = statistics.median(latencies)
            p95 = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies)
            p99 = max(latencies)

            print(f"\n[PERF RESULTS] Concurrency={concurrency} | P50={p50:.2f}ms | P95={p95:.2f}ms | P99={p99:.2f}ms")
            assert p50 < 150.0
        except httpx.ConnectError:
            pytest.skip("Backend is not running locally")
