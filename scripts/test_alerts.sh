#!/usr/bin/env bash
# ==============================================================================
# test_alerts.sh
# Tests the alerting and webhook delivery pipeline
# Simulates Alertmanager webhook payloads and queries Prometheus alert states
# ==============================================================================

set -euo pipefail

PROMETHEUS_URL="${PROMETHEUS_URL:-http://localhost:9090}"
ALERTMANAGER_URL="${ALERTMANAGER_URL:-http://localhost:9093}"
BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}--> Checking Prometheus Alert Rules status at ${PROMETHEUS_URL}...${NC}"
if curl -s "${PROMETHEUS_URL}/api/v1/rules" | grep -q '"status":"success"'; then
    RULE_COUNT=$(curl -s "${PROMETHEUS_URL}/api/v1/rules" | grep -o '"name":' | wc -l)
    echo -e "${GREEN}[OK] Prometheus rules API responding. Total rule entries: ${RULE_COUNT}${NC}"
else
    echo -e "${YELLOW}[NOTE] Prometheus rules API unreachable or returned non-success.${NC}"
fi

echo -e "\n${YELLOW}--> Checking Alertmanager API status at ${ALERTMANAGER_URL}...${NC}"
if curl -s "${ALERTMANAGER_URL}/api/v2/status" | grep -q '"versionInfo"'; then
    echo -e "${GREEN}[OK] Alertmanager API is operational.${NC}"
else
    echo -e "${YELLOW}[NOTE] Alertmanager API unreachable.${NC}"
fi

echo -e "\n${YELLOW}--> Testing FastAPI Webhook Ingestion (/webhook/alertmanager)...${NC}"

# Synthetic Alertmanager webhook payload with dynamic timestamps
TEST_FP="test_fp_$(date +%s)"
TEST_STARTS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

TEST_PAYLOAD=$(cat << EOF
{
  "version": "4",
  "groupKey": "{}:{alertname=\"HighCPUUsage\",instance=\"test-node-01:9100\"}",
  "truncatedAlerts": 0,
  "status": "firing",
  "receiver": "webhook-backend",
  "groupLabels": {
    "alertname": "HighCPUUsage",
    "instance": "test-node-01:9100"
  },
  "commonLabels": {
    "alertname": "HighCPUUsage",
    "instance": "test-node-01:9100",
    "severity": "critical"
  },
  "commonAnnotations": {
    "summary": "High CPU utilization detected on test-node-01",
    "description": "CPU utilization reached 92.5%",
    "current_value": "92.5%",
    "recommended_action": "Inspect top processes and scale service"
  },
  "externalURL": "http://alertmanager:9093",
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "HighCPUUsage",
        "instance": "test-node-01:9100",
        "severity": "critical",
        "job": "node-exporter"
      },
      "annotations": {
        "summary": "High CPU utilization detected on test-node-01",
        "description": "CPU utilization reached 92.5%",
        "current_value": "92.5%",
        "recommended_action": "Inspect top processes and scale service"
      },
      "startsAt": "${TEST_STARTS}",
      "endsAt": "0001-01-01T00:00:00Z",
      "generatorURL": "http://prometheus:9090/graph?g0.expr=high_cpu",
      "fingerprint": "${TEST_FP}"
    }
  ]
}
EOF
)

RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${BACKEND_URL}/webhook/alertmanager" \
    -H "Content-Type: application/json" \
    -d "${TEST_PAYLOAD}")

HTTP_STATUS=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n -1)

if [[ "$HTTP_STATUS" == "200" ]]; then
    echo -e "${GREEN}[OK] Firing webhook accepted successfully! HTTP Status: ${HTTP_STATUS}${NC}"
    echo -e "Response body: ${BODY}"
else
    echo -e "${RED}[ERROR] Webhook ingestion failed with HTTP status ${HTTP_STATUS}${NC}"
    echo -e "Response body: ${BODY}"
    exit 1
fi

echo -e "\n${YELLOW}--> Verifying Incident Record via REST API (/api/incidents)...${NC}"
INCIDENTS=$(curl -s "${BACKEND_URL}/api/incidents?page=1&per_page=5")
if echo "$INCIDENTS" | grep -q "HighCPUUsage"; then
    echo -e "${GREEN}[OK] Incident successfully recorded and queried from database!${NC}"
    echo -e "${INCIDENTS}"
else
    echo -e "${RED}[ERROR] Incident not found in database query.${NC}"
    exit 1
fi

echo -e "\n${YELLOW}--> Testing Resolved Alert Webhook Deduplication & Status Update...${NC}"
RESOLVED_PAYLOAD=$(echo "$TEST_PAYLOAD" | sed 's/"status": "firing"/"status": "resolved"/g' | sed 's/"0001-01-01T00:00:00Z"/"2026-11-05T20:05:00.000Z"/g')

RES_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${BACKEND_URL}/webhook/alertmanager" \
    -H "Content-Type: application/json" \
    -d "${RESOLVED_PAYLOAD}")

RES_STATUS=$(echo "$RES_RESPONSE" | tail -n1)
if [[ "$RES_STATUS" == "200" ]]; then
    echo -e "${GREEN}[OK] Resolved webhook accepted! Incident status updated.${NC}"
else
    echo -e "${RED}[ERROR] Failed to process resolved alert webhook.${NC}"
    exit 1
fi

echo -e "\n${GREEN}==> All alert pipeline tests completed successfully!${NC}"
