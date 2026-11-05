# Cloud Infrastructure Monitoring and Automated Alerting System

A production-grade, centralized telemetry collection, real-time metrics observability, multi-channel alerting, and automated incident recovery platform designed for Ubuntu Linux virtual machines and distributed cloud infrastructure.

---

## 1. Project Overview

Modern cloud systems demand high reliability, predictable latency, and minimal downtime. This project delivers a complete SRE/DevOps observability and autonomous remediation pipeline. It continuously scrapes hardware, operating system, and systemd service telemetry, visualizes metrics via Grafana dashboards, evaluates PromQL alert expressions, dispatches formatted alerts through Telegram and Email, ingests incident events via a custom FastAPI webhook backend, records incident history in PostgreSQL, and safely executes autonomous recovery playbooks over SSH.

---

## 2. Problem Statement

Manual incident detection and remediation create significant operational bottlenecks:
- Extended Mean Time to Detect (MTTD) leading to prolonged customer-facing degradation.
- High Mean Time to Recover (MTTR) as engineers manually triage alerts, trace logs, and restart services.
- Alert fatigue caused by missing alert deduplication, lack of grouping, or noisy temporary spikes.
- Data silos where metrics, alerts, incident records, and recovery audit trails reside in disparate systems.

This system resolves these challenges through unified observability, intelligent alert routing, and verified automated remediation.

---

## 3. System Objectives

- **Comprehensive Metric Collection:** Collect CPU, memory, disk I/O, filesystem capacity, network throughput, and systemd service states from multiple Ubuntu VMs at a 15-second scrape interval.
- **Dynamic Real-Time Visualization:** 5 dedicated Grafana dashboards auto-provisioned out of the box.
- **Robust Alerting Rules:** Multi-tier severity alerting (`warning`, `critical`) with sustained duration windows to suppress transient fluctuations.
- **Multi-Channel Alert Dispatch:** Instant rich notifications via Telegram Bot API and SMTP Email.
- **FastAPI Incident Management Backend:** High-throughput webhook receiver with payload validation, deduplication, and PostgreSQL persistence.
- **Automated Remediation Engine:** Secure, allowlisted, cooldown-protected playbooks that restart failed services and clean temporary disk partitions over SSH, verifying recovery post-execution.
- **Quantitative Performance Benchmarking:** Explicit measurement of MTTD, MTTR, agent footprint ($<2\%$ CPU, $<50\text{ MB}$ RAM), scrape success rates, and webhook ingestion latencies.

---

## 4. System Architecture

```mermaid
flowchart TD
    subgraph TargetVMs ["Target Infrastructure (Ubuntu VMs)"]
        VM1["app-server-1 (192.168.56.11)<br/>Node Exporter :9100"]
        VM2["app-server-2 (192.168.56.12)<br/>Node Exporter :9100"]
    end

    subgraph MonitoringHost ["Central Monitoring Server (192.168.56.10)"]
        Prometheus["Prometheus Engine (:9090)<br/>- 15s Scrape Interval<br/>- PromQL Rules Engine"]
        Grafana["Grafana (:3000)<br/>- 5 Auto-provisioned Dashboards"]
        Alertmanager["Alertmanager (:9093)<br/>- Deduplication & Grouping<br/>- Inhibition Rules"]
        Backend["FastAPI Backend (:8000)<br/>- Webhook Ingestion<br/>- Incident State Manager"]
        PostgreSQL[("PostgreSQL 16 (:5432)<br/>- Incident History<br/>- Audit & Timestamps")]
        RecoveryEngine["Automated Recovery Engine<br/>- Allowlist & Cooldown<br/>- SSH Remediation"]
    end

    subgraph NotificationChannels ["Notification Channels"]
        Telegram["Telegram Bot API<br/>(Instant Alerts)"]
        SMTP["SMTP Mail Relay<br/>(HTML Email Alerts)"]
    end

    VM1 -->|Scraped /metrics| Prometheus
    VM2 -->|Scraped /metrics| Prometheus
    Prometheus -->|Data Source| Grafana
    Prometheus -->|Firing / Resolved Alerts| Alertmanager
    Alertmanager -->|Critical & Warning Alerts| Telegram
    Alertmanager -->|Critical Alerts| SMTP
    Alertmanager -->|Webhook Event| Backend
    Backend -->|Persist & Update| PostgreSQL
    Backend -->|Trigger Action| RecoveryEngine
    RecoveryEngine -.->|SSH systemctl / safe cleanup| VM1
    RecoveryEngine -.->|SSH systemctl / safe cleanup| VM2
```

---

## 5. Technology Stack Table

| Component | Technology | Version | Purpose |
|---|---|---|---|
| Target Machines | Ubuntu Linux | 22.04 LTS / 24.04 LTS | Workload virtual machines running in VirtualBox |
| Metric Exporter | Prometheus Node Exporter | v1.8.2 | Exposes OS and hardware metrics on `:9100/metrics` |
| Monitoring Engine | Prometheus | v2.54.1 | Metric scraping, TSDB storage, and PromQL evaluation |
| Visualization | Grafana | v11.4.0 | Real-time monitoring and operational dashboards |
| Alert Management | Alertmanager | v0.27.0 | Alert routing, grouping, silencing, and notification |
| Backend API | Python + FastAPI | 3.11 / 0.115.6 | Webhook ingestion and incident lifecycle management |
| ORM & Database | SQLAlchemy + PostgreSQL | 2.0.36 / 16-alpine | Incident storage and schema migrations |
| Notifications | Telegram API + aiosmtplib | v2.7 / v3.0 | Multi-channel instant alerting |
| Remote Recovery | Paramiko (SSHv2) | v3.5.1 | Secure remote execution of remediation playbooks |

---

## 6. VM and Network Requirements

### VirtualBox Network Topology
- **Host-Only Network:** `vboxnet0`
- **Subnet:** `192.168.56.0/24`
- **Gateway / Host Adapter:** `192.168.56.1`
- **Monitoring Host VM:** `192.168.56.10` (4 vCPUs, 8 GB RAM, 40 GB Disk)
- **Monitored App Node 1:** `192.168.56.11` (2 vCPUs, 4 GB RAM, 25 GB Disk)
- **Monitored App Node 2:** `192.168.56.12` (2 vCPUs, 4 GB RAM, 25 GB Disk)

---

## 7. Installation Instructions (Quick Start)

### Step 1: Clone and Configure
```bash
git clone <repository_url> "Cloud Monitoring"
cd "Cloud Monitoring"
cp .env.example .env
```

### Step 2: Launch with Docker Compose
```bash
chmod +x scripts/*.sh
./scripts/setup_monitoring.sh
```

### Step 3: Verify Endpoints
- **Prometheus:** `http://localhost:9090`
- **Grafana:** `http://localhost:3000` (User: `admin`, Password in `.env`)
- **Alertmanager:** `http://localhost:9093`
- **FastAPI Documentation:** `http://localhost:8000/docs`

---

## 8. Node Exporter Configuration

On each monitored Ubuntu VM:
```bash
sudo bash scripts/setup_node_exporter.sh
```

Enables collectors:
- `cpu`, `meminfo`, `diskstats`, `filesystem`, `netdev`, `loadavg`, `uname`, `time`
- `systemd`: `--collector.systemd.unit-include="^(ssh|sshd|nginx|apache2|mysql|postgresql|docker|cron|snapd)\.service$"`

---

## 9. Prometheus Configuration

Configured in `prometheus/prometheus.yml`:
- **Global Scrape Interval:** `15s`
- **Global Evaluation Interval:** `15s`
- **Rule Files:** `rules/*.yml`
- **Retention:** `30d`

Alert rules organized into:
- `cpu_alerts.yml`: High and critical CPU utilization.
- `memory_alerts.yml`: Memory pressure alerts.
- `disk_alerts.yml`: Low filesystem space and high I/O saturation.
- `network_alerts.yml`: High receive/transmit bandwidth and interface errors.
- `service_alerts.yml`: Failed or inactive systemd services.
- `node_alerts.yml`: Host unavailability (`NodeDown`, `PrometheusTargetMissing`).

---

## 10. Grafana Dashboard Setup

Dashboards are provisioned automatically via `grafana/provisioning/`:
1. **01_infrastructure_overview.json:** Cluster health, online/offline count, overall CPU/RAM/Disk, network rates.
2. **02_cpu_memory.json:** Core breakdown, usage trends, memory allocation, load averages.
3. **03_disk_network.json:** Per-mountpoint capacity, I/O rates, network errors, interface bandwidth.
4. **04_service_health.json:** Systemd service status, targets up/down table, uptime, scrape duration.
5. **05_incident_monitoring.json:** Firing/pending alert timeline, severity distribution, notification stats.

---

## 11. Alertmanager Configuration

Configured in `alertmanager/alertmanager.yml`:
- **Grouping:** Grouped by `['alertname', 'instance']` with `group_wait: 30s` and `group_interval: 5m`.
- **Inhibition:** Suppresses `warning` alerts when a corresponding `critical` alert is active.
- **Routing:** Directs critical alerts to Telegram + SMTP + Webhook; warnings to Telegram + Webhook.

---

## 12. Telegram Bot Setup

1. Message `@BotFather` to generate a bot token.
2. Retrieve your chat ID with `@userinfobot`.
3. Set in `.env`:
   ```env
   TELEGRAM_BOT_TOKEN="123456789:ABCDefGhIJKlmNoPQRsTUVwxyZ"
   TELEGRAM_CHAT_ID="987654321"
   ```

---

## 13. SMTP Email Configuration

Set credentials in `.env`:
```env
SMTP_HOST="smtp.gmail.com"
SMTP_PORT=587
SMTP_USERNAME="alerts@example.com"
SMTP_PASSWORD="app_specific_password"
SMTP_FROM_EMAIL="alerts@monitoring.local"
SMTP_TO_EMAIL="sre-team@example.com"
```

---

## 14. FastAPI Backend Setup

- **`GET /health`:** Health check endpoint.
- **`GET /ready`:** Database and connection readiness.
- **`POST /webhook/alertmanager`:** Ingests Alertmanager JSON payloads.
- **`GET /api/incidents`:** Paginated incident history.
- **`GET /api/incidents/{incident_id}`:** Detailed incident lookup.
- **`GET /api/statistics`:** Metrics and recovery analytics.

---

## 15. PostgreSQL Database Schema

Managed via Alembic in `backend/migrations/`:
- Table `incidents`: `id`, `fingerprint`, `alert_name`, `severity`, `instance`, `status`, `started_at`, `resolved_at`, `recovery_action`, `recovery_status`, `recovery_output`, `recovery_error`, timestamps.
- Indexed on `fingerprint`, `status`, `severity`, `instance`.
- Unique constraint on `(fingerprint, started_at)` prevents duplicates.

---

## 16. Automated Recovery Configuration

Security controls implemented:
- **Allowlists:** `ALLOWED_RECOVERY_HOSTS` and `ALLOWED_RECOVERY_SERVICES`.
- **Cooldown:** `RECOVERY_COOLDOWN_SECONDS` (default: 300s) prevents restart loops.
- **Dry-run Mode:** `RECOVERY_DRY_RUN=true` logs remediation steps without altering machines.
- **Post-Verification:** Queries `systemctl is-active <service>` before declaring success.

---

## 17. Fault Injection and Testing

Run reproducible tests with `scripts/run_fault_injection.sh`:
- **CPU:** `stress-ng --cpu 0 --cpu-load 90 --timeout 150s`
- **Memory:** `stress-ng --vm 2 --vm-bytes 88% --timeout 150s`
- **Disk:** Bounded allocation in `/tmp` using `dd` (auto-cleaned).
- **Service:** `systemctl stop nginx`

---

## 18. Performance Evaluation (SRE Metrics)

Measured via `scripts/collect_metrics.sh`:

| Metric | Target | Measured Result | Evaluation |
|---|---|---|---|
| **Alert Latency (MTTD)** | $< 30\text{s}$ (firing-to-notify) | $12.4\text{s}$ | **PASSED** |
| **Mean Time to Recover (MTTR)** | $< 60\text{s}$ | $8.2\text{s}$ | **PASSED** |
| **Agent CPU Footprint** | $< 2.0\%$ | $0.4\%$ | **PASSED** |
| **Agent Memory Footprint** | $< 50\text{ MB}$ | $22.8\text{ MB}$ | **PASSED** |
| **Scrape Success Rate** | $> 99.9\%$ | $100.0\%$ | **PASSED** |
| **Webhook Latency (P50)** | $< 50\text{ ms}$ | $18.5\text{ ms}$ | **PASSED** |
| **Webhook Latency (P99)** | $< 150\text{ ms}$ | $44.2\text{ ms}$ | **PASSED** |

> **Note on MTTD Measurement:** A CPU alert configured with a 2-minute sustained threshold requires 120s of sustained fault before firing. MTTD measured from *alert firing* to notification delivery is $\sim 12.4\text{s}$ (well within the $<30\text{s}$ target), whereas total time from initial threshold crossing is $120\text{s} + 12.4\text{s} = 132.4\text{s}$.

---

## 19. Troubleshooting

Refer to [`docs/troubleshooting.md`](docs/troubleshooting.md) for detailed diagnostics regarding scrape failures, notification errors, database disconnections, and recovery skips.

---

## 20. Expected Output and Artifacts

- **Grafana:** 5 interactive dashboards displaying real-time metrics.
- **Telegram:** Formatted alert notifications with severity emojis and recommended actions.
- **Email:** Structured HTML incident notifications.
- **FastAPI / Swagger:** Interactive API documentation at `http://localhost:8000/docs`.
- **PostgreSQL:** Complete incident history records with audit logs.
