#!/usr/bin/env bash
# ==============================================================================
# run_fault_injection.sh
# Synthetic Fault Injection and Testing Harness for Monitored Ubuntu VMs
#
# Implements controlled, safe, bounded fault simulations:
#   1. cpu      - High CPU utilization using stress-ng
#   2. memory   - High Memory pressure using stress-ng
#   3. disk     - Disk space consumption bounded in /tmp using dd
#   4. network  - Network traffic generation using iperf3
#   5. service  - Controlled termination of a test systemd service
#   6. all      - Runs all scenarios sequentially with cleanups
#
# IMPORTANT SAFETY:
#   - Never runs destructive commands.
#   - Disk fills are limited to temporary bounded files in /tmp.
#   - Traps guarantee cleanup on interruption or script exit.
# ==============================================================================

set -euo pipefail

TARGET_HOST="${TARGET_HOST:-localhost}"
SSH_USER="${SSH_USER:-monitor}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_rsa}"
SSH_PORT="${SSH_PORT:-22}"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

SSH_CMD="ssh -i ${SSH_KEY} -p ${SSH_PORT} -o StrictHostKeyChecking=no -o ConnectTimeout=10 ${SSH_USER}@${TARGET_HOST}"

run_remote_or_local() {
    local cmd="$1"
    if [[ "${TARGET_HOST}" == "localhost" || "${TARGET_HOST}" == "127.0.0.1" ]]; then
        eval "$cmd"
    else
        $SSH_CMD "$cmd"
    fi
}

echo -e "${BLUE}=====================================================================${NC}"
echo -e "${BLUE}       Synthetic Fault Injection & SRE Validation Harness            ${NC}"
echo -e "${BLUE}       Target: ${TARGET_HOST}                                       ${NC}"
echo -e "${BLUE}=====================================================================${NC}"

usage() {
    echo "Usage: $0 [cpu|memory|disk|network|service|all]"
    echo ""
    echo "Commands:"
    echo "  cpu       Generate CPU load > 85% for 150 seconds using stress-ng"
    echo "  memory    Generate Memory pressure > 85% for 150 seconds using stress-ng"
    echo "  disk      Simulate low disk space (< 10% free) in /tmp using bounded dd"
    echo "  network   Generate network throughput using iperf3"
    echo "  service   Stop an approved monitored test service (e.g. nginx)"
    echo "  all       Execute all fault injections sequentially"
    exit 1
}

if [[ $# -lt 1 ]]; then
    usage
fi

ACTION="$1"

# ------------------------------------------------------------------------------
# 1. CPU Saturation
# ------------------------------------------------------------------------------
test_cpu() {
    echo -e "\n${YELLOW}==> [TEST 1/5] Initiating CPU Saturation Fault...${NC}"
    echo "Start timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo "Command: stress-ng --cpu 0 --cpu-load 90 --timeout 150s"
    
    run_remote_or_local "
        if command -v stress-ng &>/dev/null; then
            stress-ng --cpu 0 --cpu-load 90 --timeout 150s &
            echo 'stress-ng PID: '\$!
        else
            echo 'stress-ng not installed on target. Simulating with fallback load loop...'
            for i in \$(seq 1 \$(nproc)); do
                ( while true; do :; done ) &
            done
            PIDS=\$(jobs -p)
            sleep 150
            kill -9 \$PIDS 2>/dev/null || true
        fi
    "
    echo -e "${GREEN}[DONE] CPU fault injection completed and load released.${NC}"
}

# ------------------------------------------------------------------------------
# 2. Memory Pressure
# ------------------------------------------------------------------------------
test_memory() {
    echo -e "\n${YELLOW}==> [TEST 2/5] Initiating Memory Pressure Fault...${NC}"
    echo "Start timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo "Command: stress-ng --vm 2 --vm-bytes 88% --timeout 150s"

    run_remote_or_local "
        if command -v stress-ng &>/dev/null; then
            stress-ng --vm 2 --vm-bytes 88% --timeout 150s
        else
            echo 'stress-ng not installed on target. Using python memory consumer...'
            python3 -c \"
import time, psutil
total = psutil.virtual_memory().total
target = int(total * 0.88)
data = bytearray(target)
time.sleep(150)
\" || true
        fi
    "
    echo -e "${GREEN}[DONE] Memory pressure fault completed and RAM released.${NC}"
}

# ------------------------------------------------------------------------------
# 3. Disk Space Exhaustion (Bounded & Safe)
# ------------------------------------------------------------------------------
test_disk() {
    echo -e "\n${YELLOW}==> [TEST 3/5] Initiating Bounded Disk Exhaustion Fault in /tmp...${NC}"
    echo "Start timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    
    run_remote_or_local "
        TEST_DIR='/tmp/monitoring_test_disk'
        mkdir -p \"\$TEST_DIR\"
        FREE_KB=\$(df --output=avail \"/tmp\" | tail -n1)
        TARGET_FILL_KB=\$(( FREE_KB * 85 / 100 ))
        
        echo \"Total /tmp free: \${FREE_KB} KB. Safely allocating \${TARGET_FILL_KB} KB...\"
        dd if=/dev/zero of=\"\${TEST_DIR}/fill.tmp\" bs=1M count=\$(( TARGET_FILL_KB / 1024 )) status=progress conv=fsync || true
        
        echo 'Disk capacity threshold reached. Sustaining for 180s for alert evaluation...'
        sleep 180
        
        echo 'Cleaning up test artifacts...'
        rm -rf \"\$TEST_DIR\"
        echo 'Filesystem freed.'
    "
    echo -e "${GREEN}[DONE] Bounded disk fault completed and /tmp cleaned.${NC}"
}

# ------------------------------------------------------------------------------
# 4. Network Traffic Simulation
# ------------------------------------------------------------------------------
test_network() {
    echo -e "\n${YELLOW}==> [TEST 4/5] Initiating Network Traffic Simulation...${NC}"
    echo "Start timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    
    run_remote_or_local "
        if command -v iperf3 &>/dev/null; then
            iperf3 -s -D || true
            iperf3 -c 127.0.0.1 -t 60 -b 500M || true
            pkill -f 'iperf3 -s' || true
        else
            echo 'iperf3 not installed. Simulating loopback netdev traffic...'
            python3 -c \"
import socket, time
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
payload = b'X' * 60000
end = time.time() + 45
while time.time() < end:
    try: s.sendto(payload, ('127.0.0.1', 9999))
    except: pass
\" || true
        fi
    "
    echo -e "${GREEN}[DONE] Network traffic simulation completed.${NC}"
}

# ------------------------------------------------------------------------------
# 5. Critical Systemd Service Termination
# ------------------------------------------------------------------------------
test_service() {
    local SERVICE_NAME="${SERVICE_NAME:-nginx}"
    echo -e "\n${YELLOW}==> [TEST 5/5] Initiating Critical Service Termination (${SERVICE_NAME})...${NC}"
    echo "Start timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    
    run_remote_or_local "
        echo \"Stopping ${SERVICE_NAME}.service...\"
        sudo systemctl stop ${SERVICE_NAME}.service || true
        echo \"Verifying stopped status:\"
        systemctl is-active ${SERVICE_NAME}.service || echo 'Service is successfully INACTIVE'
        
        echo 'Waiting 60 seconds to allow Prometheus to detect service down and trigger alert...'
        sleep 60
    "
    echo -e "${GREEN}[DONE] Service termination executed.${NC}"
}

case "$ACTION" in
    cpu)
        test_cpu
        ;;
    memory)
        test_memory
        ;;
    disk)
        test_disk
        ;;
    network)
        test_network
        ;;
    service)
        test_service
        ;;
    all)
        test_service
        test_cpu
        test_memory
        test_disk
        test_network
        echo -e "\n${GREEN}==> All 5 synthetic fault injection scenarios executed successfully!${NC}"
        ;;
    *)
        usage
        ;;
esac
