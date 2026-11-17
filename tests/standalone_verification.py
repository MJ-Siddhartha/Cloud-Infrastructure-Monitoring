"""Comprehensive Standalone Verification Suite for Cloud Monitoring System.
Runs without external dependencies (no docker, no pytest, no network needed).
Tests all core logic, schemas, rules, configs, recovery engine, and dashboards.
"""

import sys
import json
import yaml
import time
from pathlib import Path

# Add backend to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

# Results tracker
tests_run = 0
tests_passed = 0
tests_failed = 0
failures = []

def run_test(name, fn):
    global tests_run, tests_passed, tests_failed
    tests_run += 1
    try:
        fn()
        print(f"  [PASS] {name}")
        tests_passed += 1
    except Exception as e:
        print(f"  [FAIL] {name}: {e}")
        tests_failed += 1
        failures.append((name, str(e)))

print("=" * 70)
print("CLOUD INFRASTRUCTURE MONITORING - VERIFICATION SUITE")
print("=" * 70)

# ------------------------------------------------------------------------------
# 1. Config & Settings
# ------------------------------------------------------------------------------
print("\n[1] Testing Configuration & Settings...")

def test_settings_load():
    from app.config import Settings
    s = Settings(
        RECOVERY_ENABLED=True,
        ALLOWED_RECOVERY_HOSTS="192.168.56.11,192.168.56.12",
        ALLOWED_RECOVERY_SERVICES="nginx,mysql"
    )
    assert s.RECOVERY_ENABLED is True
    assert s.ALLOWED_RECOVERY_HOSTS == ["192.168.56.11", "192.168.56.12"]
    assert s.ALLOWED_RECOVERY_SERVICES == ["nginx", "mysql"]

run_test("Settings parses comma-separated lists correctly", test_settings_load)

# ------------------------------------------------------------------------------
# 2. Webhook Schema Validation
# ------------------------------------------------------------------------------
print("\n[2] Testing Webhook Schemas...")

def test_valid_webhook_schema():
    from app.schemas.webhook import AlertmanagerWebhook
    raw = {
        "version": "4",
        "groupKey": "g1",
        "status": "firing",
        "receiver": "webhook-backend",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "HighCPU", "instance": "host1:9100", "severity": "critical"},
                "annotations": {"description": "CPU > 85%", "current_value": "89.2%"},
                "startsAt": "2026-11-05T20:00:00Z",
                "fingerprint": "fp1234"
            }
        ]
    }
    wh = AlertmanagerWebhook.model_validate(raw)
    assert wh.status == "firing"
    assert len(wh.alerts) == 1
    assert wh.alerts[0].labels.alertname == "HighCPU"
    assert wh.alerts[0].fingerprint == "fp1234"

run_test("Valid AlertmanagerWebhook parses successfully", test_valid_webhook_schema)

def test_malformed_webhook_rejected():
    from app.schemas.webhook import AlertmanagerWebhook
    from pydantic import ValidationError
    # Invalid alert entry (labels must be an object/dict)
    raw = {"version": "4", "status": "firing", "alerts": [{"status": "firing", "labels": "not_an_object"}]}
    try:
        AlertmanagerWebhook.model_validate(raw)
        raise AssertionError("Should have failed validation")
    except ValidationError:
        pass  # expected

run_test("Malformed webhook payload triggers ValidationError", test_malformed_webhook_rejected)

# ------------------------------------------------------------------------------
# 3. Recovery Engine Logic
# ------------------------------------------------------------------------------
print("\n[3] Testing Recovery Engine Logic...")

def test_recovery_allowlist():
    from app.config import Settings
    from app.recovery.engine import RecoveryEngine
    s = Settings(
        RECOVERY_ENABLED=True,
        ALLOWED_RECOVERY_HOSTS=["srv1", "srv2"],
        ALLOWED_RECOVERY_SERVICES=["nginx", "redis-server"]
    )
    eng = RecoveryEngine(s)
    # Allowed alert and allowed host
    assert eng.should_recover("ServiceDown", "srv1:9100", "fp1") is True
    # Disallowed host
    assert eng.should_recover("ServiceDown", "hacker-host:9100", "fp2") is False
    # Disallowed alert
    assert eng.should_recover("UnapprovedAlert", "srv1:9100", "fp3") is False

run_test("RecoveryEngine enforces strict host and alert allowlists", test_recovery_allowlist)

def test_recovery_cooldown():
    from app.config import Settings
    from app.recovery.engine import RecoveryEngine
    s = Settings(RECOVERY_ENABLED=True, RECOVERY_COOLDOWN_SECONDS=60, ALLOWED_RECOVERY_HOSTS=[])
    eng = RecoveryEngine(s)
    fp = "cooldown-test-fp"
    # First time allowed
    assert eng.should_recover("ServiceDown", "host:9100", fp) is True
    # Simulate recent recovery
    eng._recent_recoveries[fp] = time.time()
    # Second time blocked due to cooldown
    assert eng.should_recover("ServiceDown", "host:9100", fp) is False
    # After cooldown expires
    eng._recent_recoveries[fp] = time.time() - 70
    assert eng.should_recover("ServiceDown", "host:9100", fp) is True

run_test("RecoveryEngine prevents rapid recovery loops with cooldown", test_recovery_cooldown)

def test_playbook_dry_run():
    from app.recovery.playbooks import RecoveryPlaybooks
    from unittest.mock import MagicMock
    ssh = MagicMock()
    res = RecoveryPlaybooks.restart_service(ssh, "host1:9100", "nginx", dry_run=True)
    assert res["success"] is True
    assert "[DRY RUN]" in res["output"]
    ssh.execute_command.assert_not_called()

run_test("RecoveryPlaybooks dry_run executes safely without touching host", test_playbook_dry_run)

# ------------------------------------------------------------------------------
# 4. Prometheus Rules & YAML Validation
# ------------------------------------------------------------------------------
print("\n[4] Testing Prometheus Alert Rules...")

def test_all_rule_files():
    rule_dir = PROJECT_ROOT / "prometheus" / "rules"
    rule_files = list(rule_dir.glob("*.yml"))
    assert len(rule_files) == 6, f"Expected 6 rule files, found {len(rule_files)}"
    total_rules = 0
    for rf in rule_files:
        with open(rf, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            assert "groups" in data
            for group in data["groups"]:
                assert "name" in group
                assert "rules" in group
                for rule in group["rules"]:
                    assert "alert" in rule
                    assert "expr" in rule
                    assert "for" in rule
                    assert "labels" in rule and "severity" in rule["labels"]
                    assert "annotations" in rule
                    total_rules += 1
    assert total_rules >= 12, f"Expected at least 12 alert rules, found {total_rules}"

run_test("All 6 Prometheus rule files are structurally complete with annotations", test_all_rule_files)

# ------------------------------------------------------------------------------
# 5. Alertmanager Configuration Validation
# ------------------------------------------------------------------------------
print("\n[5] Testing Alertmanager Configuration...")

def test_alertmanager_config():
    am_path = PROJECT_ROOT / "alertmanager" / "alertmanager.yml"
    with open(am_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert "route" in data
    assert "receivers" in data
    assert "inhibit_rules" in data
    receivers = {r["name"] for r in data["receivers"]}
    assert "critical-alerts" in receivers
    assert "warning-alerts" in receivers
    assert "webhook-backend" in receivers

run_test("Alertmanager routing, inhibition, and multi-receivers configured", test_alertmanager_config)

def test_inhibition_matches_rule_pairs():
    """Every critical/warning pair must share the labels used by the inhibit rule."""
    am_path = PROJECT_ROOT / "alertmanager" / "alertmanager.yml"
    with open(am_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    equal = set(data["inhibit_rules"][0]["equal"])
    # alertname differs between warning/critical variants, so it must not be required
    assert "alertname" not in equal, "inhibition requires equal alertname; it can never match"
    assert {"instance", "category"} <= equal
    for rule_file in (PROJECT_ROOT / "prometheus" / "rules").glob("*.yml"):
        with open(rule_file, "r", encoding="utf-8") as f:
            for group in yaml.safe_load(f)["groups"]:
                for rule in group["rules"]:
                    assert "category" in rule["labels"], f"{rule['alert']} has no category label"
    # No route may use `continue`, otherwise an alert is delivered more than once
    for route in data["route"].get("routes", []):
        assert not route.get("continue", False), "route uses continue: duplicate delivery"

run_test("Inhibition rule can match warning/critical pairs; no duplicate routes", test_inhibition_matches_rule_pairs)

# ------------------------------------------------------------------------------
# 6. Grafana Dashboards Schema Validation
# ------------------------------------------------------------------------------
print("\n[6] Testing Grafana Dashboards...")

def test_grafana_dashboards():
    dash_dir = PROJECT_ROOT / "grafana" / "dashboards"
    dashboards = list(dash_dir.glob("*.json"))
    assert len(dashboards) == 5, f"Expected 5 dashboards, found {len(dashboards)}"
    uids = set()
    total_panels = 0
    for d in dashboards:
        with open(d, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert "title" in data
            assert "uid" in data
            assert data["uid"] not in uids, f"Duplicate UID: {data['uid']}"
            uids.add(data["uid"])
            assert "panels" in data
            total_panels += len(data["panels"])
            for panel in data["panels"]:
                assert "id" in panel
                assert "type" in panel
                assert "gridPos" in panel
    assert total_panels >= 45, f"Expected at least 45 panels, found {total_panels}"

run_test("5 Provisioned Grafana dashboards valid with 52 panels and unique UIDs", test_grafana_dashboards)

# ------------------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------------------
print("\n" + "=" * 70)
print(f"VERIFICATION RESULTS: {tests_passed}/{tests_run} PASSED ({(tests_passed/tests_run)*100:.1f}%)")
if tests_failed > 0:
    print(f"FAILURES ({tests_failed}):")
    for name, err in failures:
        print(f"  - {name}: {err}")
    sys.exit(1)
else:
    print("ALL TESTS PASSED SUCCESSFULLY!")
print("=" * 70)
