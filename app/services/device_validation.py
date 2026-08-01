from __future__ import annotations

from app.services.device_models import (
    DeviceMode, DeviceState, OperationResult, OperationType,
    ProfessionalOperationRequest,
)


class ValidationAgent:
    def validate(
        self, request: ProfessionalOperationRequest, device: DeviceState,
    ) -> OperationResult:
        if not request.case_id.strip() or not request.technician_id.strip():
            return OperationResult(False, "Case and technician IDs are required.", error_code="case_required")
        if request.target_serial != device.serial:
            return OperationResult(False, "The selected device serial does not match the request.", error_code="serial_mismatch")
        if request.operation is OperationType.READ_INFO:
            return OperationResult(True, "Read-only operation validated.")
        if not request.ownership_confirmed:
            return OperationResult(False, "Ownership confirmation is required.", error_code="ownership_required")
        if device.mode is DeviceMode.ADB and not device.authorized:
            return OperationResult(False, "ADB authorization is required on the device.", error_code="adb_unauthorized")
        if request.operation in {OperationType.REBOOT_RECOVERY, OperationType.REBOOT_BOOTLOADER}:
            if device.mode not in {DeviceMode.ADB, DeviceMode.FASTBOOT}:
                return OperationResult(False, "This reboot is unsupported in the current mode.", error_code="unsupported_mode")
            return OperationResult(True, "Operation validated.")
        return OperationResult(False, "Unsupported operation.", error_code="unsupported_operation")
