"""SSH client wrapper around paramiko with connection pooling."""

from __future__ import annotations

import os

try:
    import paramiko
except ImportError:
    paramiko = None

from app.utils.logging import get_logger

logger = get_logger(__name__)


class SSHClient:
    """Manages SSH connections to remote hosts using paramiko."""

    def __init__(
        self,
        key_path: str = "~/.ssh/id_rsa",
        username: str = "monitor",
        timeout: int = 30,
    ) -> None:
        self.key_path = os.path.expanduser(key_path)
        self.username = username
        self.timeout = timeout
        self._connections: dict = {}

    def connect(self, hostname: str):
        """Open (or return a cached) SSH connection to *hostname*."""
        if paramiko is None:
            raise RuntimeError("paramiko is not installed; SSH connections disabled.")
        if hostname in self._connections:
            transport = self._connections[hostname].get_transport()
            if transport and transport.is_active():
                return self._connections[hostname]
            # Stale – drop it
            self._connections.pop(hostname, None)

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            pkey = paramiko.RSAKey.from_private_key_file(self.key_path)
            client.connect(
                hostname=hostname,
                username=self.username,
                pkey=pkey,
                timeout=self.timeout,
                look_for_keys=False,
                allow_agent=False,
            )
        except FileNotFoundError:
            logger.error("SSH key file not found: %s", self.key_path)
            raise
        except paramiko.AuthenticationException:
            logger.error("SSH authentication failed for %s@%s", self.username, hostname)
            raise
        except paramiko.SSHException as exc:
            logger.error("SSH connection error to %s: %s", hostname, exc)
            raise
        except Exception as exc:
            logger.error("Unexpected SSH error connecting to %s: %s", hostname, exc)
            raise

        self._connections[hostname] = client
        logger.info("SSH connection established to %s", hostname)
        return client

    def execute_command(
        self, hostname: str, command: str, sudo: bool = False
    ) -> tuple[str, str, int]:
        """Execute *command* on *hostname* and return (stdout, stderr, exit_code)."""
        client = self.connect(hostname)
        if sudo:
            command = f"sudo {command}"

        logger.info("Executing on %s: %s", hostname, command)
        try:
            stdin, stdout, stderr = client.exec_command(command, timeout=self.timeout)
            exit_code = stdout.channel.recv_exit_status()
            stdout_str = stdout.read().decode("utf-8", errors="replace")
            stderr_str = stderr.read().decode("utf-8", errors="replace")
            logger.info(
                "Command on %s exited with code %d", hostname, exit_code
            )
            return stdout_str, stderr_str, exit_code
        except Exception as exc:
            logger.error("Error executing command on %s: %s", hostname, exc)
            return "", str(exc), 1

    def close(self, hostname: str) -> None:
        """Close the connection to a specific host."""
        client = self._connections.pop(hostname, None)
        if client:
            client.close()
            logger.info("SSH connection to %s closed", hostname)

    def close_all(self) -> None:
        """Close every cached SSH connection."""
        for hostname in list(self._connections):
            self.close(hostname)
        logger.info("All SSH connections closed")
