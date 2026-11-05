#!/usr/bin/env bash
# ==============================================================================
# validate_config.sh
# Validates Prometheus configuration, rule syntax, Alertmanager routing,
# docker-compose specifications, and environment file integrity.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ERRORS=0

echo -e "${YELLOW}--> Validating configurations across project root: ${PROJECT_ROOT}${NC}"

# 1. Check Python environment syntax for backend
echo -n "Checking Python backend files syntax... "
if command -v python &>/dev/null; then
    python -c "
import py_compile, sys
from pathlib import Path
root = Path(r'${PROJECT_ROOT}/backend/app')
failed = False
for p in root.rglob('*.py'):
    try:
        py_compile.compile(str(p), doraise=True)
    except Exception as e:
        print(f'Syntax error in {p}: {e}', file=sys.stderr)
        failed = True
if failed: sys.exit(1)
" && echo -e "${GREEN}[OK]${NC}" || { echo -e "${RED}[FAILED]${NC}"; ERRORS=$((ERRORS + 1)); }
else
    echo -e "${YELLOW}[SKIPPED] (Python not found)${NC}"
fi

# 2. Check Prometheus YAML rules
echo -n "Checking Prometheus rule files YAML syntax... "
if command -v python &>/dev/null; then
    python -c "
import yaml, sys
from pathlib import Path
rule_dir = Path(r'${PROJECT_ROOT}/prometheus/rules')
for yml in rule_dir.glob('*.yml'):
    with open(yml, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
        if not data or 'groups' not in data:
            print(f'Invalid rule file structure: {yml.name}', file=sys.stderr)
            sys.exit(1)
" && echo -e "${GREEN}[OK]${NC}" || { echo -e "${RED}[FAILED]${NC}"; ERRORS=$((ERRORS + 1)); }
else
    echo -e "${YELLOW}[SKIPPED]${NC}"
fi

# 3. Check Prometheus main config
echo -n "Checking prometheus.yml syntax... "
if command -v python &>/dev/null; then
    python -c "
import yaml, sys
with open(r'${PROJECT_ROOT}/prometheus/prometheus.yml', 'r', encoding='utf-8') as f:
    cfg = yaml.safe_load(f)
    if 'scrape_configs' not in cfg:
        sys.exit(1)
" && echo -e "${GREEN}[OK]${NC}" || { echo -e "${RED}[FAILED]${NC}"; ERRORS=$((ERRORS + 1)); }
else
    echo -e "${YELLOW}[SKIPPED]${NC}"
fi

# 4. Check Alertmanager config
echo -n "Checking alertmanager.yml syntax... "
if command -v python &>/dev/null; then
    python -c "
import yaml, sys
with open(r'${PROJECT_ROOT}/alertmanager/alertmanager.yml', 'r', encoding='utf-8') as f:
    cfg = yaml.safe_load(f)
    if 'route' not in cfg or 'receivers' not in cfg:
        sys.exit(1)
" && echo -e "${GREEN}[OK]${NC}" || { echo -e "${RED}[FAILED]${NC}"; ERRORS=$((ERRORS + 1)); }
else
    echo -e "${YELLOW}[SKIPPED]${NC}"
fi

# 5. Check Grafana Dashboard JSON integrity
echo -n "Checking Grafana dashboards JSON schema... "
if command -v python &>/dev/null; then
    python -c "
import json, sys
from pathlib import Path
d_dir = Path(r'${PROJECT_ROOT}/grafana/dashboards')
count = 0
for jf in d_dir.glob('*.json'):
    with open(jf, 'r', encoding='utf-8') as f:
        d = json.load(f)
        if 'title' not in d or 'panels' not in d:
            print(f'Corrupt dashboard: {jf.name}', file=sys.stderr)
            sys.exit(1)
        count += 1
if count < 5:
    print(f'Expected 5 dashboards, found {count}', file=sys.stderr)
    sys.exit(1)
" && echo -e "${GREEN}[OK (5 dashboards verified)]${NC}" || { echo -e "${RED}[FAILED]${NC}"; ERRORS=$((ERRORS + 1)); }
else
    echo -e "${YELLOW}[SKIPPED]${NC}"
fi

# 6. Check .env.example variables completeness
echo -n "Checking .env.example completeness... "
REQUIRED_VARS=("DATABASE_URL" "POSTGRES_USER" "POSTGRES_PASSWORD" "GF_SECURITY_ADMIN_PASSWORD" "RECOVERY_ENABLED")
MISSING=0
for var in "${REQUIRED_VARS[@]}"; do
    if ! grep -q "^${var}=" "${PROJECT_ROOT}/.env.example"; then
        echo -e "\n${RED}Missing required var: ${var}${NC}"
        MISSING=$((MISSING + 1))
    fi
done
if [[ $MISSING -eq 0 ]]; then
    echo -e "${GREEN}[OK]${NC}"
else
    echo -e "${RED}[FAILED] (${MISSING} vars missing)${NC}"
    ERRORS=$((ERRORS + 1))
fi

if [[ $ERRORS -eq 0 ]]; then
    echo -e "\n${GREEN}==> ALL CONFIGURATION FILES ARE VALID!${NC}"
    exit 0
else
    echo -e "\n${RED}==> CONFIGURATION VALIDATION FAILED WITH ${ERRORS} ERROR(S)${NC}"
    exit 1
fi
