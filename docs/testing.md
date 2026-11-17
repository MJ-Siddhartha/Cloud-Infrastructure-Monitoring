# Testing and Quality Assurance Guide

This document outlines the testing strategies, validation scripts, synthetic fault injection runs, and benchmark evaluations.

---

## 1. Test Categories and Execution

| Test Suite | Purpose | Command |
|---|---|---|
| **Configuration Check** | Validates YAML, JSON, Python syntax, and environment completeness | `./scripts/validate_config.sh` |
| **Backend Unit Tests** | Validates FastAPI endpoints, incident lifecycle, deduplication, schemas | `pytest backend/tests/ -v` |
| **Integration Tests** | Validates full pipeline (Prometheus, Alertmanager, Backend APIs) | `pytest tests/integration/ -v` |
| **Performance Tests** | Benchmarks ingestion throughput and percentile latencies | `pytest tests/performance/ -v` |
| **Fault Injection** | Controlled synthetic resource pressure and service failures | `./scripts/run_fault_injection.sh [type]` |
| **Recovery Test** | Tests automated remediation workflow and MTTR | `./scripts/test_recovery.sh` |
| **Performance Metrics** | Extracts SRE benchmark KPIs (MTTD, MTTR, Footprint) | `./scripts/collect_metrics.sh` |
| **Live Experiments** | Real fault injection with timings measured from the live stack; raw JSON in `results/` | `python scripts/run_experiments.py <service\|flap\|cpu\|memory\|cleanup\|bench\|overhead>` |
| **Result Figures** | Exports Prometheus time series to `results/timeseries/` and draws the report figures | `python scripts/plot_results.py` |

---

## 2. Running Controlled Synthetic Fault Injections (Phase 9)

Fault injection scripts are located in `scripts/run_fault_injection.sh`.

### Test 1: CPU Saturation
```bash
./scripts/run_fault_injection.sh cpu
```
- **Target:** CPU load sustained at $>85\%$ for 150 seconds.
- **Verification:** Observe `HighCPUUsage` alert firing in Prometheus after 2 minutes. Check Telegram/Email notification and incident recorded in PostgreSQL.

### Test 2: Memory Pressure
```bash
./scripts/run_fault_injection.sh memory
```
- **Target:** RAM consumption pushed above $85\%$ for 150 seconds.
- **Verification:** Observe `HighMemoryUsage` alert transition from pending to firing.

### Test 3: Disk Space Exhaustion (Bounded & Safe)
```bash
./scripts/run_fault_injection.sh disk
```
- **Target:** Allocates bounded temporary file in `/tmp` consuming up to $85\%$ of available partition capacity.
- **Safety Guarantee:** Automatically trapped and cleaned upon completion or script interruption. Never touches system or boot partitions.

### Test 4: Critical Service Termination
```bash
SERVICE_NAME=nginx ./scripts/run_fault_injection.sh service
```
- **Target:** Simulates unexpected service failure (`systemctl stop nginx`).
- **Verification:** Prometheus evaluates `node_systemd_unit_state{state="failed"} == 1`. Alertmanager routes event to FastAPI backend $\to$ triggers recovery engine.

---

## 3. Automated Remediation Verification (Phase 8)

Run the end-to-end recovery test:
```bash
./scripts/test_recovery.sh
```

**Evaluation criteria:**
- Incident payload received with fingerprint.
- Check allowlist validation (`ALLOWED_RECOVERY_SERVICES`).
- Check cooldown enforcement (`RECOVERY_COOLDOWN_SECONDS`).
- Execution of `systemctl restart <service>` over SSH.
- Query verification `systemctl is-active <service>` returning `"active"`.
- PostgreSQL database stores `recovery_status: "success"`, stdout log, and completion timestamp.

---

## 4. Benchmark Performance Metrics (Phase 10)

```bash
./scripts/collect_metrics.sh
```

Measures:
1. **Mean Time to Detect (MTTD):** Elapsed time from threshold crossing to notification receipt.
2. **Mean Time to Recover (MTTR):** Elapsed duration from incident receipt to verified active service state.
3. **Agent Overhead:** Node Exporter CPU percentage ($<2\%$) and RAM consumption ($<50\text{ MB}$).
4. **Scrape Reliability:** Percentage of successful scrape cycles over 24-hour evaluation window.
5. **Webhook Ingestion Latency:** P50, P95, and P99 latency percentiles.

---

## 5. Reproducible Live Experiments (`scripts/run_experiments.py`)

All published results come from this harness, run against the Docker Compose stack. It never
simulates a value: every timestamp is read from the live system (container clock, Prometheus,
Alertmanager, PostgreSQL rows and backend log timestamps) and a host-to-VM clock offset is applied
to times observed by the script itself.

| Phase | What it does | Output |
|---|---|---|
| `service --runs 10` | Stops nginx on `app-server-01`, measures pending/firing, webhook, Telegram delivery, live SSH restart + verification and resolution; waits out the recovery cooldown between runs | `results/service_failure_runs.json` |
| `flap` | Stops nginx again right after a recovery (cooldown set to 300 s) — the second recovery must be `skipped` | `results/flap_cooldown_test.json` |
| `cpu --runs 2` | `stress-ng --cpu 0 --cpu-load 90` for 120 s; records HighCPU/CriticalCPU timing and whether Alertmanager inhibited the warning | `results/cpu_fault_runs.json` |
| `memory --runs 2` | Allocates memory up to ~70 % used for 120 s; records HighMemoryUsage timing | `results/memory_fault_runs.json` |
| `cleanup` | Creates files dated 10 days ago in `/tmp`, sends a `LowDiskSpace` webhook, checks the live cleanup playbook deleted only the old files | `results/cleanup_playbook_test.json` |
| `bench --requests 500` | Webhook latency at concurrency 1, 10 and 50 (run with notifications disabled) | `results/webhook_benchmark.json` |
| `overhead --window 2h` | Node Exporter CPU/RSS, scrape success, scrape duration, rule-evaluation time, container footprint | `results/overhead_and_scrape.json` |

Disk-space alerts are not triggered by filling the disk in the lab, because the containers share the
Docker VM's large virtual disk; the `disk` fault in `run_fault_injection.sh` is intended for VMs.
