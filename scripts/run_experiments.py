#!/usr/bin/env python3
"""
run_experiments.py - reproducible end-to-end evaluation of the monitoring stack.

Runs real fault-injection experiments against the running Docker Compose stack
and records raw timings measured from the live system (no simulated values).
Results are written as JSON to results/<phase>.json.

Phases
  service   N x stop nginx on app-server-01 -> detection -> live SSH recovery
  flap      stop nginx again right after a recovery -> cooldown must skip it
  cpu       N x stress-ng CPU load -> HighCPU/CriticalCPU + inhibition check
  memory    N x stress-ng memory allocation to ~70% -> HighMemoryUsage
  cleanup   old files in /tmp + LowDiskSpace webhook -> live cleanup playbook
  bench     webhook ingestion latency (sequential and concurrent)
  overhead  agent CPU/RSS, scrape success, container footprint over a window

All timestamps are taken from the Docker VM clock (container `date`, Prometheus,
PostgreSQL, docker log timestamps). Times observed by this script on the host
are converted with a measured host->VM clock offset.

Usage:  python scripts/run_experiments.py service --runs 10
"""
from __future__ import annotations

import argparse
import asyncio
import os
import json
import statistics
import subprocess
import sys
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

PROM = "http://127.0.0.1:9090"
AM = "http://127.0.0.1:9093"
BACKEND = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
TARGET = "app-server-01"
INSTANCE = f"{TARGET}:9100"
RESULTS = Path(__file__).resolve().parent.parent / "results"
POLL = 0.25


# ----------------------------------------------------------------- helpers
def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def sh(*args: str, check: bool = True) -> str:
    r = subprocess.run(args, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{args}: {r.stderr.strip()}")
    return r.stdout


def dexec(container: str, cmd: str, detach: bool = False) -> str:
    args = ["docker", "exec"] + (["-d"] if detach else []) + [container, "sh", "-c", cmd]
    return sh(*args, check=False)


def vm_now() -> float:
    return float(dexec(TARGET, "date +%s.%N").strip())


def clock_offset(samples: int = 5) -> float:
    """VM clock minus host clock (seconds), midpoint method, best of N."""
    best = None
    for _ in range(samples):
        h0 = time.time()
        v = vm_now()
        h1 = time.time()
        rtt = h1 - h0
        off = v - (h0 + h1) / 2
        if best is None or rtt < best[0]:
            best = (rtt, off)
    return best[1]


def ts(value: str | None) -> float | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def iso(t: float | None) -> str | None:
    return datetime.fromtimestamp(t, timezone.utc).isoformat() if t else None


def prom_alerts(client: httpx.Client) -> list[dict]:
    return client.get(f"{PROM}/api/v1/alerts").json()["data"]["alerts"]


def prom_query(client: httpx.Client, q: str, t: float | None = None) -> list[dict]:
    params = {"query": q}
    if t:
        params["time"] = f"{t:.3f}"
    return client.get(f"{PROM}/api/v1/query", params=params).json()["data"]["result"]


def prom_range(client: httpx.Client, q: str, start: float, end: float, step: str = "5s") -> list[dict]:
    params = {"query": q, "start": f"{start:.3f}", "end": f"{end:.3f}", "step": step}
    return client.get(f"{PROM}/api/v1/query_range", params=params).json()["data"]["result"]


def incidents(client: httpx.Client, alert_name: str | None = None, per_page: int = 50) -> list[dict]:
    params = {"per_page": per_page}
    if alert_name:
        params["alert_name"] = alert_name
    return client.get(f"{BACKEND}/api/incidents", params=params).json()["incidents"]


def max_incident_id(client: httpx.Client) -> int:
    items = incidents(client, per_page=1)
    return items[0]["id"] if items else 0


def backend_log_events(since_vm: float, pattern: str) -> list[float]:
    """VM timestamps of backend log lines containing `pattern`."""
    out = subprocess.run(
        ["docker", "logs", "--timestamps", "--since", iso(since_vm - 1), "backend"],
        capture_output=True, text=True,
    )
    events = []
    for line in (out.stdout + out.stderr).splitlines():
        if pattern in line:
            stamp = line.split(" ", 1)[0]
            stamp = stamp[:26] + "Z" if len(stamp) > 27 else stamp  # trim ns -> us
            events.append(ts(stamp))
    return sorted(e for e in events if e and e >= since_vm - 1)


def save(name: str, data) -> None:
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    log(f"saved {path}")


def summarize(values: list[float]) -> dict:
    v = [x for x in values if x is not None]
    if not v:
        return {"n": 0}
    out = {"n": len(v), "mean": statistics.mean(v), "min": min(v), "max": max(v),
           "median": statistics.median(v)}
    out["stdev"] = statistics.stdev(v) if len(v) > 1 else 0.0
    return {k: (round(x, 3) if isinstance(x, float) else x) for k, x in out.items()}


def nginx_running() -> bool:
    return "is running" in dexec(TARGET, "service nginx status")


def wait_until(pred, timeout: float, interval: float = 1.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(interval)
    return False


# ------------------------------------------------------------ service phase
def wait_quiet(client: httpx.Client, alert_prefixes: tuple[str, ...], timeout: float = 600) -> None:
    """Wait until no alert of the given names is pending/firing and nothing is firing in the DB."""
    def quiet() -> bool:
        busy = [a for a in prom_alerts(client) if a["labels"]["alertname"].startswith(alert_prefixes)]
        am = client.get(f"{AM}/api/v2/alerts", params={"active": "true"}).json()
        busy_am = [a for a in am if a["labels"]["alertname"].startswith(alert_prefixes)]
        return not busy and not busy_am
    if not wait_until(quiet, timeout, 2):
        raise RuntimeError("alerts did not clear in time")


def service_run(client: httpx.Client, idx: int, last_reserve_vm: float | None, cooldown: float) -> dict:
    if not nginx_running():
        dexec(TARGET, "service nginx start")
    wait_quiet(client, ("SystemdService",))
    if last_reserve_vm:  # respect the recovery cooldown so every run is a real recovery
        wait_s = last_reserve_vm + cooldown + 3 - vm_now()
        if wait_s > 0:
            log(f"  waiting {wait_s:.0f}s for recovery cooldown")
            time.sleep(wait_s)
    time.sleep(5)
    base_id = max_incident_id(client)
    off = clock_offset()

    t0 = float(dexec(TARGET, "date +%s.%N; service nginx stop >/dev/null 2>&1").splitlines()[0])
    log(f"run {idx}: nginx stopped at {iso(t0)}")
    rec: dict = {"run": idx, "t0": iso(t0), "clock_offset_s": round(off, 4)}
    pending_at = firing_seen = am_seen = am_starts = None
    inc = None
    deadline = time.time() + 240
    while time.time() < deadline:
        for a in prom_alerts(client):
            if a["labels"]["alertname"] == "SystemdServiceFailed" and a["labels"].get("instance") == INSTANCE:
                pending_at = pending_at or ts(a["activeAt"])
                if a["state"] == "firing" and firing_seen is None:
                    firing_seen = time.time() + off
        if am_seen is None:
            for a in client.get(f"{AM}/api/v2/alerts").json():
                if a["labels"]["alertname"] == "SystemdServiceFailed" and a["labels"].get("instance") == INSTANCE:
                    am_seen = time.time() + off
                    am_starts = ts(a["startsAt"])
        for i in incidents(client, "SystemdServiceFailed", 5):
            if i["id"] > base_id and i["instance"] == INSTANCE:
                inc = i
        if inc and inc.get("recovery_status") in ("success", "failed", "skipped"):
            break
        time.sleep(POLL)
    if not inc:
        rec["error"] = "no incident created"
        return rec

    created = ts(inc["created_at"])
    rec.update({
        "incident_id": inc["id"],
        "fingerprint": inc["fingerprint"],
        "recovery_status": inc["recovery_status"],
        "recovery_action": inc["recovery_action"],
        "recovery_output": inc["recovery_output"],
        "recovery_error": inc["recovery_error"],
        "pending_after_s": pending_at and pending_at - t0,
        "firing_after_s": firing_seen and firing_seen - t0,
        "alertmanager_received_after_s": am_seen and am_seen - t0,
        "alertmanager_startsAt_after_s": am_starts and am_starts - t0,
        "incident_after_s": created - t0,
        "firing_to_incident_s": firing_seen and created - firing_seen,
        "recovery_exec_s": (ts(inc["recovery_completed_at"]) or 0) - (ts(inc["recovery_started_at"]) or 0)
        if inc.get("recovery_completed_at") else None,
        "incident_to_recovered_s": ts(inc["recovery_completed_at"]) - created if inc.get("recovery_completed_at") else None,
        "fault_to_recovered_s": ts(inc["recovery_completed_at"]) - t0 if inc.get("recovery_completed_at") else None,
        "nginx_running_after": nginx_running(),
        "reserve_vm": ts(inc["recovery_started_at"]) or created,
    })
    # Notifications are sent in background tasks right after the incident is created
    time.sleep(8)
    tg = backend_log_events(created, "Telegram notification sent for alert=SystemdServiceFailed")
    # SMTP delivery can take tens of seconds; poll the log for up to 60 s.
    em_ok, em_err, deadline = [], [], time.time() + 60
    while time.time() < deadline:
        em_ok = backend_log_events(created, "Email notification sent for alert=SystemdServiceFailed")
        em_err = (backend_log_events(created, "Failed to send email notification")
                  + backend_log_events(created, "error sending email notification"))
        if em_ok or em_err:
            break
        time.sleep(2)
    rec["telegram_after_s"] = tg[0] - t0 if tg else None
    rec["incident_to_telegram_s"] = tg[0] - created if tg else None
    rec["email_after_s"] = em_ok[0] - t0 if em_ok else None
    rec["incident_to_email_s"] = em_ok[0] - created if em_ok else None
    rec["email_error"] = bool(em_err) and not em_ok

    # Wait for the alert to resolve and the incident to be closed
    def resolved():
        for i in incidents(client, "SystemdServiceFailed", 10):
            if i["id"] == inc["id"] and i["status"] == "resolved":
                rec["resolved_after_s"] = ts(i["resolved_at"]) - t0
                rec["incident_closed_in_db_after_s"] = (ts(i["updated_at"]) - t0) if i.get("updated_at") else None
                return True
        return False
    wait_until(resolved, 300, 2)
    for k, v in list(rec.items()):
        if isinstance(v, float):
            rec[k] = round(v, 3)
    log("  " + ", ".join(f"{k}={rec.get(k)}" for k in
                         ("firing_after_s", "incident_after_s", "telegram_after_s",
                          "fault_to_recovered_s", "recovery_status", "resolved_after_s")))
    return rec


def phase_service(runs: int, cooldown: float) -> None:
    out = []
    with httpx.Client(timeout=10) as c:
        last = None
        for i in range(1, runs + 1):
            r = service_run(c, i, last, cooldown)
            last = r.get("reserve_vm")
            out.append(r)
            save("service_failure_runs", {"runs": out})
    keys = ["pending_after_s", "firing_after_s", "alertmanager_received_after_s", "incident_after_s", "firing_to_incident_s",
            "incident_to_telegram_s", "telegram_after_s", "incident_to_email_s", "email_after_s",
            "alertmanager_startsAt_after_s", "recovery_exec_s",
            "incident_to_recovered_s", "fault_to_recovered_s", "resolved_after_s"]
    summary = {k: summarize([r.get(k) for r in out]) for k in keys}
    summary["recovery_success"] = sum(r.get("recovery_status") == "success" for r in out)
    summary["runs"] = len(out)
    summary["telegram_delivered"] = sum(r.get("telegram_after_s") is not None for r in out)
    summary["email_delivered"] = sum(r.get("email_after_s") is not None for r in out)
    summary["email_errors"] = sum(bool(r.get("email_error")) for r in out)
    save("service_failure_runs", {"runs": out, "summary": summary})


# --------------------------------------------------------------- flap phase
def phase_flap() -> None:
    """Stop nginx, let it be recovered, then stop it again inside the cooldown."""
    # Start outside any cooldown left over from an earlier phase.
    cooldown = float(os.getenv("RECOVERY_COOLDOWN_SECONDS", "120"))
    log(f"flap: waiting {cooldown + 10:.0f}s so that no earlier cooldown is active")
    time.sleep(cooldown + 10)
    with httpx.Client(timeout=10) as c:
        first = service_run(c, 1, None, 0)
        recovered_vm = vm_now()
        base_id = max_incident_id(c)
        t0 = float(dexec(TARGET, "date +%s.%N; service nginx stop >/dev/null 2>&1").splitlines()[0])
        log("flap: nginx stopped again inside cooldown")
        second = None
        end = time.time() + 180
        while time.time() < end and not second:
            for i in incidents(c, "SystemdServiceFailed", 5):
                if i["id"] > base_id and i.get("recovery_status"):
                    second = i
            time.sleep(POLL)
        time.sleep(5)
        still_down = not nginx_running()
        dexec(TARGET, "service nginx start")  # manual operator action
        save("flap_cooldown_test", {
            "first_run": first,
            "second_stop_after_first_recovery_s": round(t0 - (ts(first["t0"]) + (first.get("fault_to_recovered_s") or 0)), 3),
            "second_incident": {k: second.get(k) for k in ("id", "fingerprint", "recovery_status", "recovery_output", "created_at")} if second else None,
            "nginx_still_down_after_second_alert": still_down,
            "note": "second failure inside the cooldown window must be skipped (no restart loop); nginx restarted manually afterwards",
        })


# ---------------------------------------------------------------- cpu phase
def phase_cpu(runs: int, duration: int) -> None:
    out = []
    with httpx.Client(timeout=10) as c:
        for idx in range(1, runs + 1):
            wait_quiet(c, ("HighCPU", "CriticalCPU"))
            time.sleep(20)
            base_id = max_incident_id(c)
            off = clock_offset()
            t0 = float(dexec(TARGET, "date +%s.%N").strip())
            dexec(TARGET, f"stress-ng --cpu 0 --cpu-load 90 --timeout {duration}s", detach=True)
            log(f"cpu run {idx}: stress-ng started")
            first = {}
            inhibited_seen = False
            end = time.time() + duration + 15
            while time.time() < end:
                now_vm = time.time() + off
                for a in prom_alerts(c):
                    n, inst = a["labels"]["alertname"], a["labels"].get("instance")
                    if n in ("HighCPUUsage", "CriticalCPUUsage") and inst == INSTANCE:
                        first.setdefault(f"{n}_pending", ts(a["activeAt"]) - t0)
                        if a["state"] == "firing":
                            first.setdefault(f"{n}_firing", now_vm - t0)
                for a in c.get(f"{AM}/api/v2/alerts").json():
                    if a["labels"]["alertname"] == "HighCPUUsage" and a["status"]["inhibitedBy"]:
                        inhibited_seen = True
                time.sleep(0.5)
            t1 = time.time() + off
            peak = prom_range(c, '100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)', t0, t1, "5s")
            peak_val = {r["metric"]["instance"]: round(max(float(v[1]) for v in r["values"]), 2) for r in peak}
            time.sleep(10)
            new = [i for i in incidents(c, None, 50) if i["id"] > base_id and "CPU" in i["alert_name"]]
            out.append({
                "run": idx, "t0": iso(t0), "duration_s": duration,
                **{k: round(v, 3) for k, v in first.items()},
                "peak_cpu_percent": peak_val,
                "warning_inhibited_in_alertmanager": inhibited_seen,
                "incidents_created": sorted(f"{i['alert_name']}@{i['instance']}" for i in new),
                "incident_after_s": {f"{i['alert_name']}@{i['instance']}": round(ts(i["created_at"]) - t0, 3) for i in new},
                "recovery_attempted": any(i.get("recovery_status") for i in new),
            })
            log(f"  {out[-1]}")
            save("cpu_fault_runs", {"runs": out})


# ------------------------------------------------------------- memory phase
def phase_memory(runs: int, duration: int, target_pct: float) -> None:
    out = []
    with httpx.Client(timeout=10) as c:
        for idx in range(1, runs + 1):
            wait_quiet(c, ("HighMemory", "CriticalMemory"))
            time.sleep(15)
            res = prom_query(c, f'node_memory_MemTotal_bytes{{instance="{INSTANCE}"}}')
            total = float(res[0]["value"][1])
            avail = float(prom_query(c, f'node_memory_MemAvailable_bytes{{instance="{INSTANCE}"}}')[0]["value"][1])
            used_pct = (1 - avail / total) * 100
            alloc = int(max(0, target_pct / 100 * total - (total - avail)))
            base_id = max_incident_id(c)
            off = clock_offset()
            t0 = float(dexec(TARGET, "date +%s.%N").strip())
            dexec(TARGET, f"stress-ng --vm 1 --vm-bytes {alloc} --vm-keep --timeout {duration}s", detach=True)
            log(f"memory run {idx}: allocating {alloc/2**30:.2f} GiB (baseline {used_pct:.1f}%)")
            first = {}
            end = time.time() + duration + 10
            while time.time() < end:
                for a in prom_alerts(c):
                    if a["labels"]["alertname"] == "HighMemoryUsage" and a["labels"].get("instance") == INSTANCE:
                        first.setdefault("pending", ts(a["activeAt"]) - t0)
                        if a["state"] == "firing":
                            first.setdefault("firing", time.time() + off - t0)
                time.sleep(0.5)
            t1 = time.time() + off
            mem = prom_range(c, f'(1 - node_memory_MemAvailable_bytes{{instance="{INSTANCE}"}} / node_memory_MemTotal_bytes{{instance="{INSTANCE}"}}) * 100', t0, t1, "5s")
            peak = max(float(v[1]) for v in mem[0]["values"]) if mem else None
            time.sleep(10)
            new = [i for i in incidents(c, "HighMemoryUsage", 20) if i["id"] > base_id and i["instance"] == INSTANCE]
            out.append({
                "run": idx, "t0": iso(t0), "baseline_used_percent": round(used_pct, 2),
                "allocated_gib": round(alloc / 2**30, 3), "peak_used_percent": peak and round(peak, 2),
                "pending_after_s": first.get("pending") and round(first["pending"], 3),
                "firing_after_s": first.get("firing") and round(first["firing"], 3),
                "incident_after_s": round(ts(new[0]["created_at"]) - t0, 3) if new else None,
            })
            log(f"  {out[-1]}")
            save("memory_fault_runs", {"runs": out})


# ------------------------------------------------------------ cleanup phase
def phase_cleanup() -> None:
    files_old = [f"/tmp/exp_old_{i}.log" for i in range(3)]
    file_new = "/tmp/exp_recent.log"
    dexec(TARGET, " && ".join(
        [f"head -c 1048576 /dev/urandom > {f} && touch -d '10 days ago' {f}" for f in files_old]
        + [f"echo recent > {file_new}"]))
    before = dexec(TARGET, "ls -l /tmp/exp_*")
    fp = f"cleanup-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    payload = {"version": "4", "groupKey": "cleanup-test", "status": "firing", "receiver": "critical-alerts",
               "alerts": [{"status": "firing", "fingerprint": fp, "startsAt": now,
                           "labels": {"alertname": "LowDiskSpace", "severity": "warning", "category": "disk",
                                      "instance": INSTANCE, "mountpoint": "/"},
                           "annotations": {"summary": "Synthetic LowDiskSpace for cleanup playbook test",
                                           "description": "Synthetic trigger (the shared Docker disk cannot be filled safely)"}}]}
    with httpx.Client(timeout=10) as c:
        t = time.time()
        r = c.post(f"{BACKEND}/webhook/alertmanager", json=payload)
        inc = None
        while time.time() - t < 60:
            for i in incidents(c, "LowDiskSpace", 5):
                if i["fingerprint"] == fp and i.get("recovery_status") in ("success", "failed"):
                    inc = i
            if inc:
                break
            time.sleep(POLL)
        after = dexec(TARGET, "ls -l /tmp/exp_* 2>/dev/null")
        # resolve the synthetic alert
        payload["status"] = "resolved"
        payload["alerts"][0]["status"] = "resolved"
        payload["alerts"][0]["endsAt"] = datetime.now(timezone.utc).isoformat()
        c.post(f"{BACKEND}/webhook/alertmanager", json=payload)
    dexec(TARGET, f"rm -f {file_new}")
    save("cleanup_playbook_test", {
        "webhook_response": r.json(),
        "files_before": before.splitlines(), "files_after": after.splitlines(),
        "old_files_deleted": all(f not in after for f in files_old),
        "recent_file_kept": file_new in after,
        "recovery_status": inc and inc["recovery_status"],
        "recovery_output": inc and inc["recovery_output"],
        "incident_to_recovered_s": inc and round(ts(inc["recovery_completed_at"]) - ts(inc["created_at"]), 3),
    })


# -------------------------------------------------------------- bench phase
def percentile(v: list[float], p: float) -> float:
    v = sorted(v)
    k = (len(v) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def _bench_payload(i: int, tag: str) -> dict:
    return {"version": "4", "groupKey": f"bench-{tag}-{i}", "status": "firing", "receiver": "webhook-backend",
            "alerts": [{"status": "firing", "fingerprint": f"bench-{tag}-{i}-{uuid.uuid4().hex[:8]}",
                        "startsAt": datetime.now(timezone.utc).isoformat(),
                        "labels": {"alertname": "BenchAlert", "severity": "warning", "category": "bench",
                                   "instance": f"bench-{i % 10}:9100"},
                        "annotations": {"description": "webhook latency benchmark"}}]}


async def _bench(total: int, concurrency: int, tag: str) -> dict:
    lat: list[float] = []
    errors = 0
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(timeout=30) as c:
        for i in range(20):  # warm-up
            await c.post(f"{BACKEND}/webhook/alertmanager", json=_bench_payload(i, tag + "w"))

        async def one(i):
            nonlocal errors
            async with sem:
                t = time.perf_counter()
                r = await c.post(f"{BACKEND}/webhook/alertmanager", json=_bench_payload(i, tag))
                lat.append((time.perf_counter() - t) * 1000)
                if r.status_code != 200:
                    errors += 1
        t0 = time.perf_counter()
        await asyncio.gather(*(one(i) for i in range(total)))
        wall = time.perf_counter() - t0
    return {"requests": total, "concurrency": concurrency, "errors": errors,
            "throughput_rps": round(total / wall, 1),
            "mean_ms": round(statistics.mean(lat), 2), "p50_ms": round(percentile(lat, 50), 2),
            "p95_ms": round(percentile(lat, 95), 2), "p99_ms": round(percentile(lat, 99), 2),
            "max_ms": round(max(lat), 2)}


def phase_bench(total: int) -> None:
    res = {"sequential": asyncio.run(_bench(total, 1, "seq")),
           "concurrent_10": asyncio.run(_bench(total, 10, "c10")),
           "concurrent_50": asyncio.run(_bench(total, 50, "c50")),
           "note": "each request creates a new incident in PostgreSQL; notifications disabled during the benchmark"}
    log(json.dumps(res, indent=1))
    res["client_location"] = os.getenv("BENCH_LOCATION", "host (Windows -> Docker Desktop port forwarding)")
    save(os.getenv("BENCH_NAME", "webhook_benchmark"), res)


# ----------------------------------------------------------- overhead phase
def phase_overhead(window: str) -> None:
    with httpx.Client(timeout=30) as c:
        def per_instance(q):
            return {r["metric"].get("instance", "?"): round(float(r["value"][1]), 4) for r in prom_query(c, q)}
        res = {
            "window": window,
            "node_exporter_cpu_percent_avg": per_instance(f'avg_over_time((rate(process_cpu_seconds_total{{job="node-exporter"}}[1m]) * 100)[{window}:15s])'),
            "node_exporter_cpu_percent_max": per_instance(f'max_over_time((rate(process_cpu_seconds_total{{job="node-exporter"}}[1m]) * 100)[{window}:15s])'),
            "node_exporter_rss_mb_avg": per_instance(f'avg_over_time(process_resident_memory_bytes{{job="node-exporter"}}[{window}]) / 1048576'),
            "node_exporter_rss_mb_max": per_instance(f'max_over_time(process_resident_memory_bytes{{job="node-exporter"}}[{window}]) / 1048576'),
            "scrape_success_percent": per_instance(f'avg_over_time(up[{window}]) * 100'),
            "scrapes_counted": per_instance(f'count_over_time(up[{window}])'),
            "scrape_duration_ms_avg": per_instance(f'avg_over_time(scrape_duration_seconds[{window}]) * 1000'),
            "scrape_duration_ms_max": per_instance(f'max_over_time(scrape_duration_seconds[{window}]) * 1000'),
            "rule_eval_duration_ms_avg": round(float(prom_query(c, f'avg(avg_over_time(prometheus_rule_group_last_duration_seconds[{window}])) * 1000')[0]["value"][1]), 3),
            "tsdb_head_series": int(float(prom_query(c, "prometheus_tsdb_head_series")[0]["value"][1])),
            "samples_appended_per_s": round(float(prom_query(c, "rate(prometheus_tsdb_head_samples_appended_total[5m])")[0]["value"][1]), 2),
        }
    stats = sh("docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}")
    res["docker_stats_snapshot"] = [line.split("\t") for line in stats.strip().splitlines()]
    log(json.dumps(res, indent=1))
    save("overhead_and_scrape", res)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("phase", choices=["service", "flap", "cpu", "memory", "cleanup", "bench", "overhead"])
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--cooldown", type=float, default=120)
    ap.add_argument("--duration", type=int, default=120)
    ap.add_argument("--target-pct", type=float, default=70)
    ap.add_argument("--requests", type=int, default=500)
    ap.add_argument("--window", default="1h")
    a = ap.parse_args()
    {"service": lambda: phase_service(a.runs, a.cooldown),
     "flap": phase_flap,
     "cpu": lambda: phase_cpu(a.runs, a.duration),
     "memory": lambda: phase_memory(a.runs, a.duration, a.target_pct),
     "cleanup": phase_cleanup,
     "bench": lambda: phase_bench(a.requests),
     "overhead": lambda: phase_overhead(a.window)}[a.phase]()


if __name__ == "__main__":
    sys.exit(main())
