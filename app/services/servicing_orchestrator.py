from __future__ import annotations

from app.services.android_audit import AndroidAuditLogger
from app.services.android_wrappers import AdbWrapper, FastbootWrapper
from app.services.device_models import (
    DeviceMode, DeviceState, OperationResult, OperationType, ProfessionalOperationRequest,
)
from app.services.device_validation import ValidationAgent


class ServicingOrchestrator:
    def __init__(self, validation=None, adb=None, fastboot=None, audit=None) -> None:
        self.validation = validation or ValidationAgent()
        self.adb = adb or AdbWrapper()
        self.fastboot = fastboot or FastbootWrapper()
        self.audit = audit or AndroidAuditLogger()

    def handle(self, request: ProfessionalOperationRequest, device: DeviceState) -> OperationResult:
        validation = self.validation.validate(request, device)
        if not validation.success:
            self.audit.record(request, device, validation)
            return validation
        try:
            result = self._route(request, device)
        except (RuntimeError, ValueError) as error:
            result = OperationResult(False, str(error), error_code="command_failed")
        self.audit.record(request, device, result)
        return result

    def _route(self, request: ProfessionalOperationRequest, device: DeviceState) -> OperationResult:
        if request.operation is OperationType.READ_INFO:
            return OperationResult(True, "Device information collected.", data=device.to_dict())
        if request.operation not in {
            OperationType.REBOOT_RECOVERY,
            OperationType.REBOOT_BOOTLOADER,
        }:
            return OperationResult(
                False,
                "This operation is not handled by the reboot orchestrator.",
                error_code="unsupported_operation",
            )
        target = "recovery" if request.operation is OperationType.REBOOT_RECOVERY else "bootloader"
        if device.mode is DeviceMode.ADB:
            self.adb.reboot(device.serial, target)
        elif device.mode is DeviceMode.FASTBOOT:
            self.fastboot.reboot(device.serial, target)
        else:
            return OperationResult(False, "Unsupported device mode.", error_code="unsupported_mode")
        return OperationResult(True, f"Reboot to {target} requested.")
