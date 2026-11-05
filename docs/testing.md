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
