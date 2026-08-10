from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path

import psutil


class HealthState(IntEnum):
    HEALTHY = 0
    WARNING = 1
    CRITICAL = 2


@dataclass(frozen=True)
class HealthMetric:
    name: str
    state: HealthState
    value: float | int | str
    detail: str


@dataclass(frozen=True)
class HealthSnapshot:
    collected_at: datetime
    overall_state: HealthState
    cpu: HealthMetric
    memory: HealthMetric
    storage: HealthMetric
    uptime: HealthMetric
    application: HealthMetric
    warnings: tuple[str, ...]


class HealthEngine:
    """Collect a read-only, normalized health snapshot for ARC3 and Windows."""

    WARNING_PERCENT = 80
    CRITICAL_PERCENT = 95

    def __init__(self, storage_path: str | Path | None = None) -> None:
        system_drive = os.environ.get("SystemDrive", "C:")
        self.storage_path = Path(storage_path or f"{system_drive}\\")

    def collect(self, active_workers: int = 0) -> HealthSnapshot:
        cpu_percent = float(psutil.cpu_percent(interval=None))
        memory = psutil.virtual_memory()
        storage = psutil.disk_usage(str(self.storage_path))
        uptime_seconds = max(0, int(datetime.now().timestamp() - psutil.boot_time()))

        cpu = self._usage_metric(
            "CPU", cpu_percent, f"{psutil.cpu_count(logical=True) or 0} logical processors"
        )
        memory_metric = self._usage_metric(
            "Memory",
            float(memory.percent),
            f"{self.format_bytes(memory.used)} used of {self.format_bytes(memory.total)}",
        )
        storage_metric = self._usage_metric(
            "Primary storage",
            float(storage.percent),
            f"{self.format_bytes(storage.used)} used of {self.format_bytes(storage.total)}",
        )
        uptime = HealthMetric(
            "Windows uptime", HealthState.HEALTHY, uptime_seconds, self.format_uptime(uptime_seconds)
        )
        application = self._application_metric(active_workers)
        metrics = (cpu, memory_metric, storage_metric, uptime, application)
        warnings = tuple(
            f"{metric.name}: {metric.state.name} - {metric.detail}"
            for metric in metrics
            if metric.state is not HealthState.HEALTHY
        )
        return HealthSnapshot(
            collected_at=datetime.now(timezone.utc),
            overall_state=max(metric.state for metric in metrics),
            cpu=cpu,
            memory=memory_metric,
            storage=storage_metric,
            uptime=uptime,
            application=application,
            warnings=warnings,
        )

    def _application_metric(self, active_workers: int) -> HealthMetric:
        process = psutil.Process()
        status = process.status()
        unhealthy_statuses = {psutil.STATUS_DEAD, psutil.STATUS_ZOMBIE}
        state = HealthState.CRITICAL if status in unhealthy_statuses else HealthState.HEALTHY
        worker_count = max(0, int(active_workers))
        detail = (
            f"Process {status}; {worker_count} active background "
            f"worker{'s' if worker_count != 1 else ''}; {threading.active_count()} Python threads"
        )
        return HealthMetric("ARC3 application", state, worker_count, detail)

    @classmethod
    def _usage_metric(cls, name: str, percentage: float, detail: str) -> HealthMetric:
        if percentage >= cls.CRITICAL_PERCENT:
            state = HealthState.CRITICAL
        elif percentage >= cls.WARNING_PERCENT:
            state = HealthState.WARNING
        else:
            state = HealthState.HEALTHY
        return HealthMetric(name, state, round(percentage, 1), detail)

    @staticmethod
    def format_bytes(value: int) -> str:
        size = float(value)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

    @staticmethod
    def format_uptime(seconds: int) -> str:
        days, remainder = divmod(max(0, seconds), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)
        return f"{days}d {hours}h {minutes}m" if days else f"{hours}h {minutes}m"
