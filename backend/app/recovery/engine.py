"""Recovery engine that decides whether to recover and dispatches playbooks."""

from __future__ import annotations

import asyncio
import re
import threading
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.recovery.playbooks import RecoveryPlaybooks
from app.recovery.ssh_client import SSHClient
from app.services.incident_service import update_recovery_status
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Alert names mapped to recovery playbooks.
# Only faults with a well-defined, safe remediation are mapped. Resource
# saturation alerts (CPU / memory) are deliberately NOT mapped: restarting an
# arbitrary service is not a correct response to high load, so those alerts
# are notified to an operator instead.
ALERT_PLAYBOOK_MAP: dict[str, str] = {
    "SystemdServiceFailed": "restart_service",
    "SystemdServiceNotActive": "restart_service",
    "ServiceDown": "restart_service",
    "ProcessCrash": "restart_service",
    "DiskSpaceLow": "cleanup_disk_space",
    "DiskSpaceCritical": "cleanup_disk_space",
    "LowDiskSpace": "cleanup_disk_space",
    "CriticalDiskSpace": "cleanup_disk_space",
}

_SERVICE_NAME_RE = re.compile(r"^[A-Za-z0-9_.@-]+$")


def service_name_from_labels(labels: dict[str, Any]) -> str:
    """Extract the systemd service name (without '.service') from alert labels."""
    raw = labels.get("name") or labels.get("service") or ""
    return str(raw).replace(".service", "").strip()


class RecoveryEngine:
    """Coordinates automated recovery actions for incidents.

    Cooldown state is tracked under two keys so that it holds across webhook
    requests (the engine is a process-wide singleton, see
    :func:`get_recovery_engine`):

    * the alert fingerprint - stops the same alert re-firing (flapping) from
      triggering a new recovery inside the cooldown window;
    * the recovery target (playbook + host + service) - stops two different
      alerts about the same fault (e.g. SystemdServiceFailed and
      SystemdServiceNotActive) from starting two concurrent recoveries.
    """

    def __init__(self, config: Settings) -> None:
        self.config = config
        self.allowed_hosts: set[str] = set(config.ALLOWED_RECOVERY_HOSTS)
        self.allowed_services: set[str] = set(config.ALLOWED_RECOVERY_SERVICES)
        self.cooldown_seconds: int = config.RECOVERY_COOLDOWN_SECONDS
        self.dry_run: bool = config.RECOVERY_DRY_RUN
        self._recent_recoveries: dict[str, float] = {}
        self._lock = threading.RLock()  # re-entrant: reserve() calls should_recover()
        self.ssh_client = SSHClient(
            key_path=config.SSH_KEY_PATH,
            username=config.SSH_USERNAME,
            timeout=config.SSH_TIMEOUT,
            known_hosts_path=config.SSH_KNOWN_HOSTS_PATH,
        )
        self.playbooks = RecoveryPlaybooks()
        logger.info(
            "RecoveryEngine initialised (dry_run=%s, cooldown=%ds, allowed_hosts=%s)",
            self.dry_run,
            self.cooldown_seconds,
            self.allowed_hosts or "any",
        )

    # ------------------------------------------------------------------ guards
    @staticmethod
    def target_key(alert_name: str, instance: str, labels: dict[str, Any] | None) -> str:
        playbook = ALERT_PLAYBOOK_MAP.get(alert_name, "none")
        hostname = instance.split(":")[0] if instance else ""
        service = service_name_from_labels(labels or {}) if playbook == "restart_service" else ""
        return f"target:{playbook}:{hostname}:{service}"

    def _in_cooldown(self, key: str) -> float | None:
        last = self._recent_recoveries.get(key)
        if last is None:
            return None
        remaining = self.cooldown_seconds - (time.time() - last)
        return remaining if remaining > 0 else None

    def should_recover(
        self,
        alert_name: str,
        instance: str,
        fingerprint: str,
        labels: dict[str, Any] | None = None,
    ) -> bool:
        """Check whether recovery should proceed based on allow-lists and cooldown."""
        if alert_name not in ALERT_PLAYBOOK_MAP:
            logger.debug("No playbook mapped for alert_name=%s", alert_name)
            return False

        hostname = instance.split(":")[0] if instance else ""
        if self.allowed_hosts and hostname not in self.allowed_hosts:
            logger.info("Host %s not in allowed_hosts, skipping recovery", hostname)
            return False

        with self._lock:
            for key in (fingerprint, self.target_key(alert_name, instance, labels)):
                remaining = self._in_cooldown(key)
                if remaining is not None:
                    logger.info("Cooldown active for %s (%.0fs remaining)", key, remaining)
                    return False
        return True

    def reserve(
        self,
        alert_name: str,
        instance: str,
        fingerprint: str,
        labels: dict[str, Any] | None = None,
    ) -> bool:
        """Atomically check the guards and start the cooldown window.

        Returns True if the caller may run the recovery. Calling this before
        spawning the background task closes the race in which two webhook
        deliveries both pass ``should_recover`` before either has recorded
        its attempt.
        """
        with self._lock:
            if not self.should_recover(alert_name, instance, fingerprint, labels):
                return False
            now = time.time()
            self._recent_recoveries[fingerprint] = now
            self._recent_recoveries[self.target_key(alert_name, instance, labels)] = now
            return True

    async def reserve_shared(
        self,
        db: AsyncSession,
        alert_name: str,
        instance: str,
        fingerprint: str,
        labels: dict[str, Any] | None = None,
    ) -> bool:
        """Like :meth:`reserve`, but with the cooldown stored in PostgreSQL.

        With several backend worker processes, in-memory state is not shared,
        so the reservation is made in the ``recovery_cooldowns`` table under a
        transaction-scoped advisory lock. On other databases (unit tests with
        SQLite) it falls back to the in-memory reservation.
        """
        if db.bind.dialect.name != "postgresql":
            return self.reserve(alert_name, instance, fingerprint, labels)
        if not self.should_recover(alert_name, instance, fingerprint, labels):
            return False

        keys = [fingerprint, self.target_key(alert_name, instance, labels)]
        await db.execute(text("SELECT pg_advisory_xact_lock(724001)"))
        busy = (
            await db.execute(
                text(
                    "SELECT key FROM recovery_cooldowns WHERE key = ANY(:keys) "
                    "AND reserved_at > now() - make_interval(secs => :cd)"
                ),
                {"keys": keys, "cd": float(self.cooldown_seconds)},
            )
        ).scalars().all()
        if busy:
            await db.commit()
            logger.info("Cooldown active for %s (shared)", ", ".join(busy))
            return False
        for key in keys:
            await db.execute(
                text(
                    "INSERT INTO recovery_cooldowns (key, reserved_at) VALUES (:k, now()) "
                    "ON CONFLICT (key) DO UPDATE SET reserved_at = EXCLUDED.reserved_at"
                ),
                {"k": key},
            )
        await db.commit()  # also releases the advisory lock
        with self._lock:
            now = time.time()
            for key in keys:
                self._recent_recoveries[key] = now
        return True

    # --------------------------------------------------------------- execution
    async def execute_recovery(
        self,
        incident_id: int,
        alert_name: str,
        instance: str,
        labels: dict[str, Any],
        db: AsyncSession,
    ) -> dict:
        """Run the appropriate playbook for the given alert.

        Updates the incident's recovery fields throughout the process.
        """
        playbook_name = ALERT_PLAYBOOK_MAP.get(alert_name)
        if not playbook_name:
            return {"success": False, "error": "No playbook for alert"}

        await update_recovery_status(db, incident_id, "running", action=playbook_name)
        await db.commit()

        try:
            result = await asyncio.to_thread(
                self._run_playbook, playbook_name, instance, labels
            )
            status = "success" if result["success"] else "failed"
            await update_recovery_status(
                db,
                incident_id,
                status,
                output=result.get("output"),
                error=result.get("error"),
                action=result.get("action"),
            )
            logger.info(
                "Recovery %s for incident id=%s: %s", status, incident_id, result.get("action")
            )
            return result
        except Exception as exc:
            logger.error("Recovery failed for incident id=%s: %s", incident_id, exc)
            await update_recovery_status(db, incident_id, "failed", error=str(exc))
            return {"success": False, "error": str(exc)}

    def _run_playbook(
        self, playbook_name: str, instance: str, labels: dict[str, Any]
    ) -> dict:
        """Synchronous dispatcher for playbook execution."""
        if playbook_name == "restart_service":
            service_name = service_name_from_labels(labels)
            action = f"restart_service:{service_name or '?'}"
            if not service_name or not _SERVICE_NAME_RE.match(service_name):
                return {
                    "success": False,
                    "action": action,
                    "output": "",
                    "error": f"Invalid or missing service name: {service_name!r}",
                }
            if self.allowed_services and service_name not in self.allowed_services:
                return {
                    "success": False,
                    "action": action,
                    "output": "",
                    "error": f"Service '{service_name}' not in allowed list",
                }
            return self.playbooks.restart_service(
                self.ssh_client, instance, service_name, dry_run=self.dry_run
            )
        if playbook_name == "cleanup_disk_space":
            return self.playbooks.cleanup_disk_space(
                self.ssh_client, instance, dry_run=self.dry_run
            )
        return {
            "success": False,
            "action": playbook_name,
            "output": "",
            "error": f"Unknown playbook: {playbook_name}",
        }

    def close(self) -> None:
        """Shut down all SSH connections."""
        self.ssh_client.close_all()


_engine: RecoveryEngine | None = None
_engine_lock = threading.Lock()


def get_recovery_engine(settings: Settings) -> RecoveryEngine:
    """Return the process-wide recovery engine (created on first use)."""
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = RecoveryEngine(settings)
        return _engine


def reset_recovery_engine() -> None:
    """Close and drop the singleton (used on shutdown and in tests)."""
    global _engine
    with _engine_lock:
        if _engine is not None:
            _engine.close()
        _engine = None
