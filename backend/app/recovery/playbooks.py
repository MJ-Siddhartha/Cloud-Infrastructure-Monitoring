"""Recovery playbooks for automated remediation."""

from __future__ import annotations

import time

from app.recovery.ssh_client import SSHClient
from app.utils.logging import get_logger

logger = get_logger(__name__)


class RecoveryPlaybooks:
    """Pre-defined recovery actions executed over SSH.

    Every command run here is fixed in code; the only value taken from an
    alert is a service name, which the engine has already validated against
    a strict pattern and the service allowlist.
    """

    @staticmethod
    def restart_service(
        ssh_client: SSHClient,
        instance: str,
        service_name: str,
        dry_run: bool = True,
    ) -> dict:
        """Restart a service and verify it is running.

        Uses ``systemctl`` on hosts managed by systemd and falls back to the
        SysV ``service`` wrapper on hosts where systemd is not PID 1 (for
        example the container-based lab nodes). Success is reported only if
        the post-restart check confirms the service is running.

        Returns a dict with keys: success, action, output, error, duration_s.
        """
        hostname = instance.split(":")[0]
        action = f"restart_service:{service_name}"

        if dry_run:
            logger.info("[DRY RUN] Would restart service '%s' on %s", service_name, hostname)
            return {
                "success": True,
                "action": action,
                "output": f"[DRY RUN] Would restart {service_name} on {hostname}",
                "error": None,
            }

        started = time.monotonic()
        log: list[str] = []
        try:
            stdout, stderr, code = ssh_client.execute_command(
                hostname, f"systemctl restart {service_name}", sudo=True
            )
            log.append(f"$ systemctl restart {service_name} -> exit {code} {stderr.strip()}")
            manager = "systemctl"
            if code != 0:
                stdout, stderr, code = ssh_client.execute_command(
                    hostname, f"service {service_name} restart", sudo=True
                )
                log.append(f"$ service {service_name} restart -> exit {code} {stdout.strip()} {stderr.strip()}")
                manager = "service"
            if code != 0:
                return {
                    "success": False,
                    "action": action,
                    "output": "\n".join(log),
                    "error": stderr.strip() or f"restart exited with code {code}",
                    "duration_s": round(time.monotonic() - started, 3),
                }

            # Verify
            if manager == "systemctl":
                stdout, _, code = ssh_client.execute_command(
                    hostname, f"systemctl is-active {service_name}", sudo=True
                )
                is_active = stdout.strip() == "active"
                log.append(f"$ systemctl is-active {service_name} -> {stdout.strip()}")
            else:
                stdout, _, code = ssh_client.execute_command(
                    hostname, f"service {service_name} status", sudo=True
                )
                is_active = code == 0
                log.append(f"$ service {service_name} status -> exit {code} {stdout.strip()}")

            return {
                "success": is_active,
                "action": action,
                "output": "\n".join(log),
                "error": None if is_active else f"Service {service_name} not running after restart",
                "duration_s": round(time.monotonic() - started, 3),
            }
        except Exception as exc:
            logger.error("Error restarting service %s on %s: %s", service_name, hostname, exc)
            return {
                "success": False,
                "action": action,
                "output": "\n".join(log),
                "error": str(exc),
            }

    @staticmethod
    def cleanup_disk_space(
        ssh_client: SSHClient,
        instance: str,
        dry_run: bool = True,
    ) -> dict:
        """Clean old temporary files and old journal logs to free disk space.

        Only deletes regular files older than 7 days in /tmp and /var/tmp and
        vacuums journal logs older than 3 days - it NEVER deletes arbitrary
        paths. Missing journald (e.g. in containers) is not treated as failure.

        Returns a dict with keys: success, action, output, error.
        """
        hostname = instance.split(":")[0]
        action = "cleanup_disk_space"

        commands = [
            "find /tmp -xdev -type f -mtime +7 -print -delete",
            "find /var/tmp -xdev -type f -mtime +7 -print -delete",
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
        errors: list[str] = []
        try:
            for cmd in commands:
                stdout, stderr, exit_code = ssh_client.execute_command(hostname, cmd, sudo=True)
                outputs.append(f"$ {cmd} (exit {exit_code})\n{stdout}")
                if exit_code != 0:
                    if cmd.startswith("journalctl"):
                        outputs.append("journald not available on this host; skipped")
                    else:
                        errors.append(f"{cmd}: {stderr.strip()}")
            return {
                "success": not errors,
                "action": action,
                "output": "\n".join(outputs),
                "error": "; ".join(errors) or None,
            }
        except Exception as exc:
            logger.error("Error cleaning disk on %s: %s", hostname, exc)
            return {
                "success": False,
                "action": action,
                "output": "\n".join(outputs),
                "error": str(exc),
            }
