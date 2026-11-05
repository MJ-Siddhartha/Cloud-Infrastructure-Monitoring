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
