"""Recovery playbooks for automated remediation."""

from __future__ import annotations

from app.recovery.ssh_client import SSHClient
from app.utils.logging import get_logger

logger = get_logger(__name__)


class RecoveryPlaybooks:
    """Pre-defined recovery actions executed over SSH."""

    @staticmethod
    def restart_service(
        ssh_client: SSHClient,
        instance: str,
        service_name: str,
        dry_run: bool = True,
    ) -> dict:
        """Restart a systemd service and verify it is active.

        Returns a dict with keys: success, action, output, error.
        """
        hostname = instance.split(":")[0]
        action = f"restart_service:{service_name}"

        if dry_run:
            logger.info(
                "[DRY RUN] Would restart service '%s' on %s", service_name, hostname
            )
            return {
                "success": True,
                "action": action,
                "output": f"[DRY RUN] Would restart {service_name} on {hostname}",
                "error": None,
            }

        try:
            # Restart
            stdout, stderr, exit_code = ssh_client.execute_command(
                hostname, f"systemctl restart {service_name}", sudo=True
            )
            if exit_code != 0:
                return {
                    "success": False,
                    "action": action,
                    "output": stdout,
                    "error": stderr or f"systemctl restart exited with code {exit_code}",
                }

            # Verify
            stdout, stderr, exit_code = ssh_client.execute_command(
                hostname, f"systemctl is-active {service_name}", sudo=True
            )
            is_active = stdout.strip() == "active"

            return {
                "success": is_active,
                "action": action,
                "output": f"Service {service_name} status: {stdout.strip()}",
                "error": None if is_active else f"Service not active after restart: {stdout.strip()}",
            }
        except Exception as exc:
            logger.error("Error restarting service %s on %s: %s", service_name, hostname, exc)
            return {
                "success": False,
                "action": action,
                "output": "",
                "error": str(exc),
            }

    @staticmethod
    def cleanup_disk_space(
        ssh_client: SSHClient,
        instance: str,
        dry_run: bool = True,
    ) -> dict:
        """Clean temporary files and old journal logs to free disk space.

        Only cleans /tmp, /var/tmp, and old journal logs — NEVER deletes
        arbitrary files.

        Returns a dict with keys: success, action, output, error.
        """
        hostname = instance.split(":")[0]
        action = "cleanup_disk_space"

        commands = [
            "find /tmp -type f -atime +7 -delete",
            "find /var/tmp -type f -atime +7 -delete",
            "journalctl --vacuum-time=3d",
        ]

        if dry_run:
            logger.info("[DRY RUN] Would clean disk space on %s", hostname)
            return {
                "success": True,
                "action": action,
                "output": f"[DRY RUN] Would execute cleanup commands on {hostname}: {'; '.join(commands)}",
                "error": None,
            }

        outputs: list[str] = []
        try:
            for cmd in commands:
                stdout, stderr, exit_code = ssh_client.execute_command(
                    hostname, cmd, sudo=True
                )
                outputs.append(f"$ {cmd}\n{stdout}")
                if exit_code != 0:
                    logger.warning(
                        "Cleanup command '%s' on %s exited %d: %s",
                        cmd,
                        hostname,
                        exit_code,
                        stderr,
                    )

            combined_output = "\n".join(outputs)
            return {
                "success": True,
                "action": action,
                "output": combined_output,
                "error": None,
            }
        except Exception as exc:
            logger.error("Error cleaning disk on %s: %s", hostname, exc)
            return {
                "success": False,
                "action": action,
                "output": "\n".join(outputs),
                "error": str(exc),
            }
