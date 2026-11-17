#!/usr/bin/env bash
# ==============================================================================
# setup_monitoring.sh
# Initializes and deploys the centralized monitoring infrastructure stack
# (Prometheus, Alertmanager, Grafana, PostgreSQL, FastAPI Backend)
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=====================================================================${NC}"
echo -e "${BLUE}     Cloud Infrastructure Monitoring System - Stack Initializer     ${NC}"
echo -e "${BLUE}=====================================================================${NC}"

cd "${PROJECT_ROOT}"

# Step 1: Check prerequisites
echo -e "\n${YELLOW}--> Checking prerequisites...${NC}"

if ! command -v docker &>/dev/null; then
    echo -e "${RED}[ERROR] Docker is not installed or not in PATH.${NC}"
    exit 1
fi

DOCKER_COMPOSE_CMD=""
if docker compose version &>/dev/null; then
    DOCKER_COMPOSE_CMD="docker compose"
elif command -v docker-compose &>/dev/null; then
    DOCKER_COMPOSE_CMD="docker-compose"
else
    echo -e "${RED}[ERROR] Neither 'docker compose' nor 'docker-compose' found.${NC}"
    exit 1
fi
echo -e "${GREEN}--> Using Docker Compose command: ${DOCKER_COMPOSE_CMD}${NC}"

# Step 2: Ensure environment file exists
if [[ ! -f ".env" ]]; then
    if [[ -f ".env.example" ]]; then
        echo -e "${YELLOW}--> .env file not found. Creating from .env.example...${NC}"
        cp .env.example .env
        echo -e "${YELLOW}[NOTE] Please review and customize passwords in .env for production.${NC}"
    else
        echo -e "${RED}[ERROR] Neither .env nor .env.example found!${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}--> Found existing .env configuration.${NC}"
fi

# Step 2b: SSH key pair used by the recovery engine (key-only login on targets)
if [[ ! -f "keys/recovery_id_rsa" ]]; then
    echo -e "${YELLOW}--> Generating recovery SSH key pair in keys/ ...${NC}"
    mkdir -p keys
    ssh-keygen -q -t rsa -b 3072 -m PEM -N "" -C "cloud-monitoring-recovery" -f keys/recovery_id_rsa
else
    echo -e "${GREEN}--> Found existing recovery SSH key (keys/recovery_id_rsa).${NC}"
fi

# Step 3: Validate configuration syntax
echo -e "\n${YELLOW}--> Validating configuration files...${NC}"
if [[ -f "${SCRIPT_DIR}/validate_config.sh" ]]; then
    bash "${SCRIPT_DIR}/validate_config.sh"
else
    echo -e "${YELLOW}--> validate_config.sh not found, skipping pre-flight check.${NC}"
fi

# Step 4: Build and launch containers
echo -e "\n${YELLOW}--> Starting container services...${NC}"
${DOCKER_COMPOSE_CMD} up -d --build

# Step 5: Wait for services to become healthy
echo -e "\n${YELLOW}--> Waiting for services to become ready...${NC}"
MAX_WAIT=60
COUNTER=0

check_endpoint() {
    local url=$1
    local name=$2
    if curl -s -o /dev/null -w "%{http_code}" "$url" | grep -q "200\|302"; then
        echo -e "${GREEN}[OK] ${name} is responding at ${url}${NC}"
        return 0
    else
        return 1
    fi
}

echo "Waiting for services..."
until check_endpoint "http://localhost:9090/-/healthy" "Prometheus" && \
      check_endpoint "http://localhost:9093/-/healthy" "Alertmanager" && \
      check_endpoint "http://localhost:3000/api/health" "Grafana" && \
      check_endpoint "http://localhost:8000/health" "FastAPI Backend"; do
    sleep 3
    COUNTER=$((COUNTER + 3))
    if [[ $COUNTER -ge $MAX_WAIT ]]; then
        echo -e "${RED}[WARNING] Some services took longer than ${MAX_WAIT}s to respond.${NC}"
        echo -e "Check container logs with: ${DOCKER_COMPOSE_CMD} logs"
        break
    fi
done

# Step 6: Print access summary
echo -e "\n${BLUE}=====================================================================${NC}"
echo -e "${GREEN} Monitoring Infrastructure Stack is Online!${NC}"
echo -e "${BLUE}=====================================================================${NC}"
echo -e "• Prometheus Engine:      http://localhost:9090"
echo -e "• Grafana Dashboards:     http://localhost:3000 (admin / changeme_grafana_password)"
echo -e "• Alertmanager UI:        http://localhost:9093"
echo -e "• FastAPI Webhook API:    http://localhost:8000/docs"
echo -e "• Backend Health Check:   http://localhost:8000/health"
echo -e "• Incident Statistics:    http://localhost:8000/api/statistics"
echo -e "${BLUE}=====================================================================${NC}"
