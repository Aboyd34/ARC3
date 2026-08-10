"""Read-only, privacy-minimized remote health service."""

from __future__ import annotations

from datetime import datetime, timezone
import os
import platform
from typing import Any, Callable, Mapping

import psutil

from app.services.windows_info import WindowsInfoService

from .models import TrustedDevice
from .permissions import PermissionPolicy
from .protocol import ReplayGuard, SignedRequest


class ReadOnlyHealthCollector:
    """Collect operational health without identities, addresses, or process data."""

    def collect(self) -> dict[str, Any]:
        memory = psutil.virtual_memory()
        root = os.environ.get("SystemDrive", "C:") + "\\" if os.name == "nt" else "/"
        try:
            disk = psutil.disk_usage(root)
            disk_health: Mapping[str, Any] = {
                "total": WindowsInfoService.format_bytes(disk.total),
                "free": WindowsInfoService.format_bytes(disk.free),
                "percent_used": round(disk.percent, 1),
            }
        except OSError:
            disk_health = {"available": False}
        try:
            battery = psutil.sensors_battery()
        except (AttributeError, OSError, NotImplementedError):
            battery = None
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": "ok",
            "os": {
                "name": platform.system() or "Unknown",
                "release": platform.release() or "Unknown",
                "architecture": platform.machine() or "Unknown",
            },
            "uptime_seconds": max(0, int(datetime.now().timestamp() - psutil.boot_time())),
            "cpu": {
                "logical_cores": psutil.cpu_count(logical=True) or 0,
                "percent_used": round(psutil.cpu_percent(interval=None), 1),
            },
            "memory": {
                "total": WindowsInfoService.format_bytes(memory.total),
                "available": WindowsInfoService.format_bytes(memory.available),
                "percent_used": round(memory.percent, 1),
            },
            "disk": dict(disk_health),
            "battery": {
                "available": battery is not None,
                "percent": round(battery.percent, 1) if battery is not None else None,
                "plugged_in": bool(battery.power_plugged) if battery is not None else None,
            },
        }


class RemoteHealthEndpoint:
    """Authenticated application endpoint; transport adapters call ``handle``."""

    ACTION = "health.read"

    def __init__(
        self,
        collector: ReadOnlyHealthCollector | None = None,
        permission_policy: PermissionPolicy | None = None,
    ) -> None:
        self._collector = collector or ReadOnlyHealthCollector()
        self._permission_policy = permission_policy or PermissionPolicy()

    def handle(
        self,
        request: SignedRequest,
        trusted_device: TrustedDevice,
        replay_guard: ReplayGuard,
        *,
        now_ms: int | None = None,
    ) -> dict[str, Any]:
        if request.action != self.ACTION:
            raise ValueError("remote health endpoint accepts only health.read")
        self._permission_policy.verify_and_authorize(
            request, trusted_device, replay_guard, now_ms=now_ms
        )
        return self._collector.collect()
