from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class DeviceMode(str, Enum):
    ADB = "adb"
    FASTBOOT = "fastboot"
    DOWNLOAD = "download"


class OperationType(str, Enum):
    READ_INFO = "read_info"
    VERIFY_HARDWARE = "verify_hardware"
    RUN_DIAGNOSTICS = "run_diagnostics"
    CAPTURE_LOGCAT = "capture_logcat"
    REBOOT_RECOVERY = "reboot_recovery"
    REBOOT_BOOTLOADER = "reboot_bootloader"


@dataclass(frozen=True)
class DeviceState:
    serial: str
    mode: DeviceMode
    state: str
    model: str | None = None
    product: str | None = None
    device: str | None = None
    oem: str | None = None
    authorized: bool = False
    frp_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        values = asdict(self)
        values["mode"] = self.mode.value
        return values


@dataclass(frozen=True)
class ProfessionalOperationRequest:
    case_id: str
    technician_id: str
    operation: OperationType
    target_serial: str
    ownership_confirmed: bool = False
    data_loss_confirmed: bool = False
    authorization_reference: str | None = None


@dataclass(frozen=True)
class OperationResult:
    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None


@dataclass(frozen=True)
class DiscoveryResult:
    devices: tuple[DeviceState, ...]
    tools: dict[str, str | None]
    errors: tuple[str, ...] = ()
