"""Recovery engine that decides whether to recover and dispatches playbooks."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.recovery.playbooks import RecoveryPlaybooks
from app.recovery.ssh_client import SSHClient
from app.services.incident_service import update_recovery_status
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Alert-name patterns mapped to recovery playbook methods
ALERT_PLAYBOOK_MAP: dict[str, str] = {
    "ServiceDown": "restart_service",
    "HighCPU": "restart_service",
    "ProcessCrash": "restart_service",
    "DiskSpaceLow": "cleanup_disk_space",
    "DiskSpaceCritical": "cleanup_disk_space",
}


class RecoveryEngine:
    """Coordinates automated recovery actions for incidents."""

    def __init__(self, config: Settings) -> None:
        self.config = config
        self.allowed_hosts: set[str] = set(config.ALLOWED_RECOVERY_HOSTS)
        self.allowed_services: set[str] = set(config.ALLOWED_RECOVERY_SERVICES)
        self.cooldown_seconds: int = config.RECOVERY_COOLDOWN_SECONDS
        self.dry_run: bool = config.RECOVERY_DRY_RUN
        self._recent_recoveries: dict[str, float] = {}
        self.ssh_client = SSHClient(
            key_path=config.SSH_KEY_PATH,
            username=config.SSH_USERNAME,
            timeout=config.SSH_TIMEOUT,
        )
        self.playbooks = RecoveryPlaybooks()
        logger.info(
            "RecoveryEngine initialised (dry_run=%s, cooldown=%ds, allowed_hosts=%s)",
            self.dry_run,
            self.cooldown_seconds,
            self.allowed_hosts or "any",
        )

    def should_recover(
        self, alert_name: str, instance: str, fingerprint: str
    ) -> bool:
        """Check whether recovery should proceed based on allow-lists and cooldown."""
        # Check if there is a playbook for this alert
        if alert_name not in ALERT_PLAYBOOK_MAP:
            logger.debug("No playbook mapped for alert_name=%s", alert_name)
            return False

        # Check host allow-list
        hostname = instance.split(":")[0] if instance else ""
        if self.allowed_hosts and hostname not in self.allowed_hosts:
            logger.info(
                "Host %s not in allowed_hosts, skipping recovery", hostname
            )
            return False

        # Cooldown check
        last_recovery = self._recent_recoveries.get(fingerprint)
        if last_recovery is not None:
            elapsed = time.time() - last_recovery
            if elapsed < self.cooldown_seconds:
                logger.info(
                    "Cooldown active for fingerprint=%s (%.0fs remaining)",
                    fingerprint,
                    self.cooldown_seconds - elapsed,
                )
                return False

        return True

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

        # Mark as running
        await update_recovery_status(db, incident_id, "running")
        self._recent_recoveries[f"{alert_name}:{instance}"] = time.time()

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
            )
            logger.info(
                "Recovery %s for incident id=%s: %s",
                status,
                incident_id,
                result.get("action"),
            )
            return result
        except Exception as exc:
            logger.error("Recovery failed for incident id=%s: %s", incident_id, exc)
            await update_recovery_status(
                db, incident_id, "failed", error=str(exc)
            )
            return {"success": False, "error": str(exc)}

    def _run_playbook(
        self, playbook_name: str, instance: str, labels: dict[str, Any]
    ) -> dict:
        """Synchronous dispatcher for playbook execution."""
        if playbook_name == "restart_service":
            service_name = labels.get("service", labels.get("job", ""))
            if service_name not in self.allowed_services:
                return {
                    "success": False,
                    "action": f"restart_service:{service_name}",
                    "output": "",
                    "error": f"Service '{service_name}' not in allowed list",
                }
            return self.playbooks.restart_service(
                self.ssh_client, instance, service_name, dry_run=self.dry_run
            )
        elif playbook_name == "cleanup_disk_space":
            return self.playbooks.cleanup_disk_space(
                self.ssh_client, instance, dry_run=self.dry_run
            )
        else:
            return {
                "success": False,
                "action": playbook_name,
                "output": "",
                "error": f"Unknown playbook: {playbook_name}",
            }

    def close(self) -> None:
        """Shut down all SSH connections."""
        self.ssh_client.close_all()
