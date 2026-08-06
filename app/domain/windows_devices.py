from __future__ import annotations

from enum import Enum
from typing import Any


class DeviceHealth(str, Enum):
    HEALTHY = "Healthy"
    NEEDS_ATTENTION = "Needs attention"
    DISABLED = "Disabled"


def problem_number(problem: Any) -> int | None:
    try:
        return int(str(problem).strip().casefold(), 0)
    except ValueError:
        return None


def is_disabled(problem: Any, status: str) -> bool:
    value = str(problem).strip().casefold()
    return (
        value == "cm_prob_disabled"
        or problem_number(problem) == 22
        or status.casefold() == "disabled"
    )


def normalize_device(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize Windows data into the existing Device Manager UI contract."""
    status = str(record.get("status") or "Unknown")
    problem = record.get("problem_code")
    disabled = is_disabled(problem, status)
    enabled = bool(record.get(
        "enabled", status.casefold() != "disabled" and not disabled,
    )) and not disabled
    no_problem = problem in (None, "") or problem_number(problem) == 0
    healthy_status = status.casefold() in {"ok", "started", "stopped"}
    if not enabled:
        health = DeviceHealth.DISABLED
    elif healthy_status and no_problem:
        health = DeviceHealth.HEALTHY
    else:
        health = DeviceHealth.NEEDS_ATTENTION
    return {
        "name": str(record.get("name") or "Unknown device"),
        "class": str(record.get("class") or "Unknown"),
        "status": status,
        "health": health.value,
        "problem_code": "" if problem is None else str(problem),
        "manufacturer": str(record.get("manufacturer") or "Unknown"),
        "driver_provider": str(record.get("driver_provider") or "Unknown"),
        "driver_version": str(record.get("driver_version") or "Unknown"),
        "driver_date": str(record.get("driver_date") or "Unknown"),
        "instance_id": str(record.get("instance_id") or ""),
        "enabled": enabled,
    }
