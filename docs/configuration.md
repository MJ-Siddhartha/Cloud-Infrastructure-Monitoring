# Configuration Reference Guide

Detailed parameter reference for all configurable components of the system.

---

## 1. Environment Variables (`.env`)

| Variable | Type | Default | Description |
|---|---|---|---|
| `POSTGRES_USER` | String | `monitor` | PostgreSQL database username |
| `POSTGRES_PASSWORD` | String | *(required)* | PostgreSQL user password |
| `POSTGRES_DB` | String | `monitoring` | Database name |
| `DATABASE_URL` | String | `postgresql+asyncpg://...` | SQLAlchemy async connection string |
| `GF_SECURITY_ADMIN_PASSWORD` | String | *(required)* | Grafana admin account password |
| `TELEGRAM_BOT_TOKEN` | String | `""` | Telegram Bot API token from @BotFather |
| `TELEGRAM_CHAT_ID` | String | `""` | Target recipient chat/group ID |
| `SMTP_HOST` | String | `localhost` | Outgoing SMTP mail relay host |
| `SMTP_PORT` | Integer | `587` | Outgoing SMTP port (587 for TLS, 465 for SSL) |
| `SMTP_USERNAME` | String | `""` | SMTP authentication username |
| `SMTP_PASSWORD` | String | `""` | SMTP password or app-specific token |
| `SMTP_FROM_EMAIL` | String | `alerts@monitoring.local`| Email From address header |
| `SMTP_TO_EMAIL` | String | `""` | On-call notification destination email |
| `RECOVERY_ENABLED` | Boolean | `false` | Enables autonomous remediation execution |
| `RECOVERY_DRY_RUN` | Boolean | `true` | When true, audits actions without modifying target |
| `RECOVERY_COOLDOWN_SECONDS` | Integer | `300` | Minimum interval before repeating recovery on host |
| `ALLOWED_RECOVERY_HOSTS` | CSV | `""` | Strict allowlist of hosts permitted for remediation |
| `ALLOWED_RECOVERY_SERVICES`| CSV | `nginx,apache2...` | Strict allowlist of systemd services |
| `SSH_KEY_PATH` | Path | `~/.ssh/id_rsa` | Private SSH key path for remote execution |
| `SSH_USERNAME` | String | `monitor` | User account utilized for SSH remote commands |
| `SSH_TIMEOUT` | Integer | `30` | Network socket timeout for SSH operations |
| `LOG_LEVEL` | String | `INFO` | Logging verbosity (DEBUG, INFO, WARNING, ERROR) |

---

## 2. Prometheus Alert Rule Specifications

All rule files are located in `prometheus/rules/`.

### 2.1 CPU Rules (`cpu_alerts.yml`)
- **HighCPUUsage (Warning):**
  - Expression: `100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 85`
  - Sustained Duration: `2m`
- **CriticalCPUUsage (Critical):**
  - Expression: `100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 95`
  - Sustained Duration: `1m`

### 2.2 Memory Rules (`memory_alerts.yml`)
- **HighMemoryUsage (Warning):**
  - Expression: `(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100 > 85`
  - Sustained Duration: `2m`
- **CriticalMemoryUsage (Critical):**
  - Expression: `(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100 > 95`
  - Sustained Duration: `1m`

### 2.3 Disk Rules (`disk_alerts.yml`)
- **LowDiskSpace (Warning):**
  - Expression: `(node_filesystem_avail_bytes{mountpoint="/",fstype!="tmpfs"} / node_filesystem_size_bytes{mountpoint="/",fstype!="tmpfs"}) * 100 < 15`
  - Sustained Duration: `5m`
- **CriticalDiskSpace (Critical):**
  - Expression: `... < 5`
  - Sustained Duration: `2m`
- **HighDiskIO (Warning):**
  - Expression: `rate(node_disk_io_time_seconds_total[5m]) * 100 > 90`
  - Sustained Duration: `5m`

### 2.4 Service Rules (`service_alerts.yml`)
- **SystemdServiceFailed (Critical):**
  - Expression: `node_systemd_unit_state{state="failed"} == 1`
  - Sustained Duration: `30s`
- **SystemdServiceNotActive (Warning):**
  - Expression: `node_systemd_unit_state{state="active"} == 0`
  - Sustained Duration: `1m`

### 2.5 Node Availability Rules (`node_alerts.yml`)
- **NodeDown (Critical):**
  - Expression: `up{job="node-exporter"} == 0`
  - Sustained Duration: `1m`
- **PrometheusTargetMissing (Critical):**
  - Expression: `up == 0`
  - Sustained Duration: `2m`

---

## 3. Alertmanager Routing & Inhibition (`alertmanager.yml`)

- **Root Routing Tree:**
  - Group By: `['alertname', 'instance']`
  - Group Wait: `30s`
  - Group Interval: `5m`
  - Repeat Interval: `4h`
- **Inhibition Rules:**
  - Suppresses `warning` alerts when a corresponding `critical` alert is already firing for the identical `alertname` and `instance`.
- **Receivers:**
  - `critical-alerts`: Dispatches to Telegram Bot + SMTP Email + FastAPI Webhook.
  - `warning-alerts`: Dispatches to Telegram Bot + FastAPI Webhook.
  - `webhook-backend`: Direct webhook pipeline for incident database recording.
