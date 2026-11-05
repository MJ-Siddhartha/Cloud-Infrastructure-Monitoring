#!/usr/bin/env bash
# ==============================================================================
# setup_node_exporter.sh
# Installs and configures Prometheus Node Exporter as a systemd service on Ubuntu
# Enables hardware, OS, disk, filesystem, network, and systemd service collectors
# ==============================================================================

set -euo pipefail

# Configuration
NODE_EXPORTER_VERSION="1.8.2"
ARCH="linux-amd64"
INSTALL_DIR="/usr/local/bin"
SERVICE_USER="node_exporter"
SERVICE_GROUP="node_exporter"
TARBALL="node_exporter-${NODE_EXPORTER_VERSION}.${ARCH}.tar.gz"
DOWNLOAD_URL="https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/${TARBALL}"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}==> Starting Node Exporter v${NODE_EXPORTER_VERSION} setup for Ubuntu...${NC}"

# Check for root privilege
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}[ERROR] This script must be run as root or with sudo.${NC}" 
   exit 1
fi

# Step 1: Create system user if not exists
if ! id "${SERVICE_USER}" &>/dev/null; then
    echo -e "${YELLOW}--> Creating system user ${SERVICE_USER}...${NC}"
    useradd --no-create-home --system --shell /bin/false "${SERVICE_USER}"
else
    echo -e "${GREEN}--> User ${SERVICE_USER} already exists.${NC}"
fi

# Step 2: Download and install binary
TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

echo -e "${YELLOW}--> Downloading Node Exporter from ${DOWNLOAD_URL}...${NC}"
if command -v curl &>/dev/null; then
    curl -fsSL "${DOWNLOAD_URL}" -o "${TMP_DIR}/${TARBALL}"
elif command -v wget &>/dev/null; then
    wget -qO "${TMP_DIR}/${TARBALL}" "${DOWNLOAD_URL}"
else
    echo -e "${RED}[ERROR] Neither curl nor wget is installed.${NC}"
    exit 1
fi

echo -e "${YELLOW}--> Extracting and installing binary...${NC}"
tar -xzf "${TMP_DIR}/${TARBALL}" -C "${TMP_DIR}"
cp "${TMP_DIR}/node_exporter-${NODE_EXPORTER_VERSION}.${ARCH}/node_exporter" "${INSTALL_DIR}/"
chown "${SERVICE_USER}:${SERVICE_GROUP}" "${INSTALL_DIR}/node_exporter"
chmod 755 "${INSTALL_DIR}/node_exporter"

# Step 3: Create systemd service with required collectors
echo -e "${YELLOW}--> Creating systemd service file...${NC}"
cat << 'EOF' > /etc/systemd/system/node_exporter.service
[Unit]
Description=Prometheus Node Exporter
Documentation=https://github.com/prometheus/node_exporter
After=network-online.target
Wants=network-online.target

[Service]
User=node_exporter
Group=node_exporter
Type=simple
ExecStart=/usr/local/bin/node_exporter \
    --collector.cpu \
    --collector.meminfo \
    --collector.diskstats \
    --collector.filesystem \
    --collector.filesystem.mount-points-exclude="^/(sys|proc|dev|run)($|/)" \
    --collector.netdev \
    --collector.netstat \
    --collector.loadavg \
    --collector.uname \
    --collector.time \
    --collector.systemd \
    --collector.systemd.unit-include="^(ssh|sshd|nginx|apache2|mysql|postgresql|docker|cron|snapd)\\.service$" \
    --web.listen-address=0.0.0.0:9100

Restart=always
RestartSec=5s
LimitNOFILE=65536

# Security hardening
ProtectSystem=full
ProtectHome=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

# Step 4: Reload systemd and start service
echo -e "${YELLOW}--> Reloading systemd and enabling service...${NC}"
systemctl daemon-reload
systemctl enable node_exporter.service
systemctl restart node_exporter.service

# Step 5: Configure firewall if ufw is active
if command -v ufw &>/dev/null && ufw status | grep -q "Status: active"; then
    echo -e "${YELLOW}--> Configuring ufw firewall to allow port 9100...${NC}"
    ufw allow 9100/tcp comment "Prometheus Node Exporter"
fi

# Step 6: Verify service health and metrics exposure
echo -e "${YELLOW}--> Verifying metrics endpoint...${NC}"
sleep 2

if curl -s http://127.0.0.1:9100/metrics | grep -q "node_cpu_seconds_total"; then
    echo -e "${GREEN}==> SUCCESS: Node Exporter v${NODE_EXPORTER_VERSION} is active and exposing metrics!${NC}"
    echo -e "Metrics endpoint: http://$(hostname -I | awk '{print $1}'):9100/metrics"
else
    echo -e "${RED}[ERROR] Node Exporter failed to respond on port 9100.${NC}"
    systemctl status node_exporter.service --no-pager
    exit 1
fi
