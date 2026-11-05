# Installation and Setup Guide

This guide describes how to deploy the entire Cloud Infrastructure Monitoring and Automated Alerting System from scratch.

---

## 1. Prerequisites

### Host Environment
- **Operating System:** Linux (Ubuntu 22.04 LTS recommended) or Windows 10/11 with Docker Desktop.
- **Docker & Docker Compose:** Docker v24+ and Docker Compose v2.20+.
- **Python:** Python 3.11+.
- **VirtualBox (Optional for VM testing):** VirtualBox 7.0+ if running dedicated guest VMs.

---

## 2. Quickstart with Docker Compose

Deploy the complete centralized monitoring stack on your local host or monitoring server:

```bash
# 1. Clone or navigate to the project directory
cd "Cloud Monitoring"

# 2. Copy the environment template
cp .env.example .env

# 3. Edit .env with your specific credentials (passwords, Telegram bot token, SMTP)
nano .env

# 4. Run the automated startup script
chmod +x scripts/*.sh
./scripts/setup_monitoring.sh
```

The script will:
- Check system prerequisites.
- Validate configuration files.
- Build and spin up the Docker Compose stack.
- Poll service endpoints until all components report healthy.

---

## 3. Ubuntu Virtual Machine Setup (Target Nodes)

To monitor external Ubuntu virtual machines:

### Step 3.1: Network Setup in VirtualBox
1. Open VirtualBox $\to$ **Tools** $\to$ **Network Manager**.
2. Create a Host-Only network adapter `vboxnet0` with IPv4 `192.168.56.1/24` (DHCP disabled).
3. On each Ubuntu VM:
   - Adapter 1: NAT (for internet access).
   - Adapter 2: Host-Only (`vboxnet0`).
   - Assign static IP:
     - `app-server-1`: `192.168.56.11`
     - `app-server-2`: `192.168.56.12`

### Step 3.2: Install Node Exporter on Monitored VMs
Copy `scripts/setup_node_exporter.sh` to each target VM and execute:

```bash
# On target Ubuntu VM
sudo bash setup_node_exporter.sh
```

Verify that metrics are accessible:
```bash
curl -s http://localhost:9100/metrics | grep node_cpu_seconds_total
```

### Step 3.3: Register Targets in Prometheus
Edit `prometheus/prometheus.yml` to uncomment or add the target VM IP addresses:

```yaml
  - job_name: "node-exporter"
    static_configs:
      - targets: ["192.168.56.11:9100"]
        labels:
          hostname: "app-server-1"
          environment: "production"
      - targets: ["192.168.56.12:9100"]
        labels:
          hostname: "app-server-2"
          environment: "production"
```

Reload Prometheus without downtime:
```bash
curl -X POST http://localhost:9090/-/reload
```

---

## 4. Telegram Bot and SMTP Configuration

### Setting Up Telegram Notifications
1. Message `@BotFather` on Telegram to create a new bot: `/newbot`.
2. Copy the HTTP API token generated.
3. Message `@userinfobot` or your new bot to find your Chat ID.
4. Update `.env`:
   ```env
   TELEGRAM_BOT_TOKEN=123456789:ABCDefGhIJKlmNoPQRsTUVwxyZ
   TELEGRAM_CHAT_ID=987654321
   ```

### Setting Up SMTP Email Alerts
1. For Gmail, generate an **App Password** under Google Account $\to$ Security $\to$ 2-Step Verification.
2. Update `.env`:
   ```env
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USERNAME=your_email@gmail.com
   SMTP_PASSWORD=your_16_char_app_password
   SMTP_FROM_EMAIL=alerts@monitoring.local
   SMTP_TO_EMAIL=oncall_engineer@example.com
   ```

---

## 5. Automated Recovery Engine Configuration

1. Generate dedicated SSH key pair on monitoring server:
   ```bash
   ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_monitor_rsa -N ""
   ```
2. Distribute public key to monitored VMs:
   ```bash
   ssh-copy-id -i ~/.ssh/id_monitor_rsa.pub monitor@192.168.56.11
   ```
3. Grant limited passwordless sudo permissions on target VM (`/etc/sudoers.d/monitor-recovery`):
   ```sudoers
   monitor ALL=(ALL) NOPASSWD: /bin/systemctl restart nginx, /bin/systemctl is-active *
   ```
4. Enable recovery in `.env`:
   ```env
   RECOVERY_ENABLED=true
   RECOVERY_DRY_RUN=false
   ALLOWED_RECOVERY_HOSTS=192.168.56.11,192.168.56.12
   ALLOWED_RECOVERY_SERVICES=nginx,apache2,postgresql,mysql,redis-server
   ```
