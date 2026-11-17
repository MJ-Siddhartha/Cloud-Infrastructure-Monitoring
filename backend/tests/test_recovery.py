"""Tests for the recovery engine."""

from __future__ import annotations

import time

try:
    import pytest
except ImportError:
    pytest = None

from app.config import Settings
from app.recovery.engine import RecoveryEngine


def _make_settings(**overrides) -> Settings:
    """Create a Settings instance with test defaults."""
    defaults = {
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "RECOVERY_ENABLED": True,
        "RECOVERY_DRY_RUN": True,
        "RECOVERY_COOLDOWN_SECONDS": 60,
        "ALLOWED_RECOVERY_HOSTS": ["server-1", "server-2"],
        "ALLOWED_RECOVERY_SERVICES": ["nginx", "redis-server"],
    }
    defaults.update(overrides)
    return Settings(**defaults)


class TestShouldRecover:
    """Tests for RecoveryEngine.should_recover."""

    def test_known_alert_and_allowed_host(self):
        engine = RecoveryEngine(_make_settings())
        assert engine.should_recover("ServiceDown", "server-1:9090", "fp-1") is True

    def test_unknown_alert_is_rejected(self):
        engine = RecoveryEngine(_make_settings())
        assert engine.should_recover("RandomAlert", "server-1:9090", "fp-1") is False

    def test_disallowed_host_is_rejected(self):
        engine = RecoveryEngine(_make_settings())
        assert engine.should_recover("ServiceDown", "unknown-host:9090", "fp-1") is False

    def test_empty_allowlist_accepts_any_host(self):
        engine = RecoveryEngine(_make_settings(ALLOWED_RECOVERY_HOSTS=[]))
        assert engine.should_recover("ServiceDown", "any-host:9090", "fp-1") is True


class TestCooldown:
    """Tests for cooldown enforcement."""

    def test_cooldown_prevents_rapid_recovery(self):
        engine = RecoveryEngine(_make_settings(RECOVERY_COOLDOWN_SECONDS=300))
        fingerprint = "ServiceDown:server-1:9090"
        # Simulate a recent recovery
        engine._recent_recoveries[fingerprint] = time.time()
        assert engine.should_recover("ServiceDown", "server-1:9090", fingerprint) is False

    def test_expired_cooldown_allows_recovery(self):
        engine = RecoveryEngine(_make_settings(RECOVERY_COOLDOWN_SECONDS=1))
        fingerprint = "ServiceDown:server-1:9090"
        engine._recent_recoveries[fingerprint] = time.time() - 10
        assert engine.should_recover("ServiceDown", "server-1:9090", fingerprint) is True


class TestDryRun:
    """Tests for dry-run mode in playbooks."""

    def test_dry_run_restart_service(self):
        from app.recovery.playbooks import RecoveryPlaybooks
        from unittest.mock import MagicMock

        ssh_mock = MagicMock()
        result = RecoveryPlaybooks.restart_service(
            ssh_mock, "server-1:9090", "nginx", dry_run=True
        )
        assert result["success"] is True
        assert "[DRY RUN]" in result["output"]
        ssh_mock.execute_command.assert_not_called()

    def test_dry_run_cleanup_disk(self):
        from app.recovery.playbooks import RecoveryPlaybooks
        from unittest.mock import MagicMock

        ssh_mock = MagicMock()
        result = RecoveryPlaybooks.cleanup_disk_space(
            ssh_mock, "server-1:9090", dry_run=True
        )
        assert result["success"] is True
        assert "[DRY RUN]" in result["output"]
        ssh_mock.execute_command.assert_not_called()


class TestCooldownAcrossAlerts:
    """Cooldown must hold across alerts about the same fault and across requests."""

    def test_reserve_blocks_second_alert_for_same_service(self):
        engine = RecoveryEngine(_make_settings(RECOVERY_COOLDOWN_SECONDS=300))
        labels = {"name": "nginx.service"}
        assert engine.reserve("SystemdServiceFailed", "server-1:9100", "fp-a", labels) is True
        # Different alert (different fingerprint) about the same service on the same host
        assert engine.reserve("SystemdServiceNotActive", "server-1:9100", "fp-b", labels) is False
        # Same alert re-firing (flapping) within the cooldown window
        assert engine.reserve("SystemdServiceFailed", "server-1:9100", "fp-a", labels) is False

    def test_other_service_not_blocked(self):
        engine = RecoveryEngine(_make_settings(RECOVERY_COOLDOWN_SECONDS=300))
        assert engine.reserve("SystemdServiceFailed", "server-1:9100", "fp-a", {"name": "nginx.service"})
        assert engine.reserve("SystemdServiceFailed", "server-1:9100", "fp-c", {"name": "redis-server.service"})

    def test_singleton_shares_state(self):
        from app.recovery.engine import get_recovery_engine, reset_recovery_engine

        reset_recovery_engine()
        settings = _make_settings(RECOVERY_COOLDOWN_SECONDS=300)
        first = get_recovery_engine(settings)
        assert first.reserve("ServiceDown", "server-1:9100", "fp-s", {"name": "nginx"})
        second = get_recovery_engine(settings)
        assert second is first
        assert second.should_recover("ServiceDown", "server-1:9100", "fp-s", {"name": "nginx"}) is False
        reset_recovery_engine()

    def test_reserve_shared_falls_back_to_memory_without_postgres(self):
        import asyncio
        from types import SimpleNamespace

        engine = RecoveryEngine(_make_settings(RECOVERY_COOLDOWN_SECONDS=300))
        fake_db = SimpleNamespace(bind=SimpleNamespace(dialect=SimpleNamespace(name="sqlite")))
        labels = {"name": "nginx.service"}
        first = asyncio.run(engine.reserve_shared(fake_db, "ServiceDown", "server-1:9100", "fp-x", labels))
        again = asyncio.run(engine.reserve_shared(fake_db, "ServiceDown", "server-1:9100", "fp-x", labels))
        assert first is True and again is False

    def test_cpu_alerts_have_no_playbook(self):
        engine = RecoveryEngine(_make_settings())
        assert engine.should_recover("HighCPUUsage", "server-1:9100", "fp-cpu") is False
        assert engine.should_recover("CriticalCPUUsage", "server-1:9100", "fp-cpu") is False


class TestLivePlaybooks:
    """Live (non dry-run) playbook logic with a mocked SSH client."""

    def test_restart_falls_back_to_service_command(self):
        from unittest.mock import MagicMock
        from app.recovery.playbooks import RecoveryPlaybooks

        ssh = MagicMock()
        ssh.execute_command.side_effect = [
            ("", "System has not been booted with systemd", 1),  # systemctl restart
            (" * Restarting nginx nginx   [ OK ]", "", 0),        # service restart
            (" * nginx is running", "", 0),                         # service status
        ]
        result = RecoveryPlaybooks.restart_service(ssh, "server-1:9100", "nginx", dry_run=False)
        assert result["success"] is True
        assert ssh.execute_command.call_args_list[1].args[1] == "service nginx restart"

    def test_restart_reports_failure_if_not_running(self):
        from unittest.mock import MagicMock
        from app.recovery.playbooks import RecoveryPlaybooks

        ssh = MagicMock()
        ssh.execute_command.side_effect = [("", "", 0), ("failed", "", 3)]
        result = RecoveryPlaybooks.restart_service(ssh, "server-1:9100", "nginx", dry_run=False)
        assert result["success"] is False

    def test_invalid_service_name_rejected(self):
        engine = RecoveryEngine(_make_settings(RECOVERY_DRY_RUN=False, ALLOWED_RECOVERY_SERVICES=[]))
        result = engine._run_playbook("restart_service", "server-1:9100", {"name": "nginx; rm -rf /"})
        assert result["success"] is False
        assert "Invalid" in result["error"]
