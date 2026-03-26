from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class ServiceState:
    installed: bool
    active: bool


class ZeroTierServiceManager:
    def __init__(self) -> None:
        pass

    @staticmethod
    def _unit_exists() -> bool:
        return (
            Path("/lib/systemd/system/zerotier-one.service").exists()
            or Path("/etc/systemd/system/zerotier-one.service").exists()
        )

    @staticmethod
    def _binary_exists() -> bool:
        return (
            shutil.which("zerotier-one") is not None
            or shutil.which("zerotier-cli") is not None
            or Path("/usr/sbin/zerotier-one").exists()
        )

    @staticmethod
    def _run(cmd: list[str], timeout_s: float = 180.0) -> subprocess.CompletedProcess[str]:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)

    def get_state(self) -> ServiceState:
        installed = self._unit_exists() or self._binary_exists()

        active = False
        if shutil.which("systemctl") is not None and self._unit_exists():
            try:
                p = self._run(["systemctl", "is-active", "--quiet", "zerotier-one"], timeout_s=10.0)
                active = p.returncode == 0
            except Exception:
                active = False
        return ServiceState(installed=installed, active=active)

    def _sudo_prefix(self) -> list[str]:
        if shutil.which("pkexec"):
            return ["pkexec"]
        if shutil.which("sudo"):
            return ["sudo", "-n"]
        return []

    def start_service(self) -> tuple[bool, str]:
        prefix = self._sudo_prefix()
        if not prefix:
            return (False, "Neither pkexec nor sudo is available for privilege escalation.")

        if prefix[0] == "pkexec":
            cmd = prefix + ["systemctl", "start", "zerotier-one"]
        else:
            cmd = prefix + ["systemctl", "start", "zerotier-one"]

        try:
            p = self._run(cmd, timeout_s=120.0)
        except subprocess.TimeoutExpired:
            return (False, "Timed out while starting the service.")

        if p.returncode != 0:
            return (False, p.stderr.strip() or p.stdout.strip() or "Failed to start service.")
        return (True, "ZeroTier service started.")

    def install_service(self) -> tuple[bool, str]:
        prefix = self._sudo_prefix()
        if not prefix:
            return (False, "Neither pkexec nor sudo is available for privilege escalation.")

        # Debian/Ubuntu package name.
        # This is the common one; distros may require a different name later.
        install_pkg = "zerotier-one"

        cmd = prefix + ["apt-get", "update"]
        try:
            p1 = self._run(cmd, timeout_s=180.0)
            if p1.returncode != 0:
                # Best-effort error message.
                return (False, p1.stderr.strip() or p1.stdout.strip() or "apt-get update failed.")

            cmd2 = prefix + ["apt-get", "install", "-y", install_pkg]
            p2 = self._run(cmd2, timeout_s=600.0)
        except subprocess.TimeoutExpired:
            return (False, "Timed out while installing the service.")

        if p2.returncode != 0:
            return (False, p2.stderr.strip() or p2.stdout.strip() or "Failed to install service.")

        # Try starting after install.
        ok, msg = self.start_service()
        if ok:
            return (True, "Installed and started ZeroTier service.")
        return (True, "Installed ZeroTier service. Start it from the menu.")

