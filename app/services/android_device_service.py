from __future__ import annotations

from pathlib import Path

from app.services.android_wrappers import AdbWrapper, FastbootWrapper
from app.services.device_discovery import DeviceDiscoveryAgent
from app.services.device_hardware import DeviceHardwareVerifier
from app.services.android_audit import AndroidAuditLogger
from app.services.android_diagnostics import AndroidDiagnosticsService
from app.services.device_models import OperationResult, OperationType, ProfessionalOperationRequest
from app.services.device_validation import ValidationAgent
from app.services.servicing_orchestrator import ServicingOrchestrator


class AndroidDeviceService:
    """UI-facing compatibility facade over the device discovery architecture."""

    def __init__(
        self,
        discovery: DeviceDiscoveryAgent | None = None,
        orchestrator: ServicingOrchestrator | None = None,
        hardware_verifier: DeviceHardwareVerifier | None = None,
        diagnostics: AndroidDiagnosticsService | None = None,
        audit: AndroidAuditLogger | None = None,
        validation: ValidationAgent | None = None,
    ) -> None:
        self.discovery = discovery or DeviceDiscoveryAgent()
        self.orchestrator = orchestrator or ServicingOrchestrator()
        self.hardware_verifier = hardware_verifier or DeviceHardwareVerifier()
        self.diagnostics = diagnostics or AndroidDiagnosticsService()
        self.audit = audit or AndroidAuditLogger()
        self.validation = validation or ValidationAgent()
        self.devices_by_key = {}

    def collect_devices(self) -> dict[str, object]:
        result = self.discovery.discover()
        tools = {
            "adb": result.tools.get("adb"),
            "fastboot": result.tools.get("fastboot"),
            "samsung_download": result.tools.get("samsung_download"),
        }
        devices = []
        self.devices_by_key = {
            (device.serial, self._display_mode(device.mode.value)): device
            for device in result.devices
        }
        for device in result.devices:
            devices.append({
                "serial": device.serial, "mode": self._display_mode(device.mode.value),
                "state": device.state, "model": device.model or "Unknown",
                "product": device.product or "Unknown", "device": device.device or "Unknown",
            })
        return {"tools": tools, "devices": devices, "errors": list(result.errors)}

    def run_operation(
        self,
        serial: str,
        mode: str,
        operation: OperationType,
        case_id: str,
        technician_id: str,
        ownership_confirmed: bool,
    ):
        device = self.devices_by_key.get((serial, mode))
        if device is None:
            raise RuntimeError("Refresh devices and select an available device first.")
        request = ProfessionalOperationRequest(
            case_id=case_id,
            technician_id=technician_id,
            operation=operation,
            target_serial=serial,
            ownership_confirmed=ownership_confirmed,
        )
        return self.orchestrator.handle(request, device)

    def verify_hardware(self, serial: str, mode: str, case_id: str, technician_id: str):
        return self._run_audited_read(
            serial, mode, OperationType.VERIFY_HARDWARE, case_id, technician_id,
            lambda device: self.hardware_verifier.verify(device),
        )

    def collect_diagnostics(self, serial: str, mode: str, case_id: str, technician_id: str):
        return self._run_audited_read(
            serial, mode, OperationType.RUN_DIAGNOSTICS, case_id, technician_id,
            lambda device: self.diagnostics.collect(device),
        )

    def capture_logcat(
        self, serial: str, mode: str, case_id: str, technician_id: str,
        max_lines: int, export_path: str,
    ):
        return self._run_audited_read(
            serial, mode, OperationType.CAPTURE_LOGCAT, case_id, technician_id,
            lambda device: self.diagnostics.capture_logcat(
                device, max_lines, Path(export_path),
            ),
        )

    def _run_audited_read(self, serial, mode, operation, case_id, technician_id, action):
        device = self.devices_by_key.get((serial, mode))
        if device is None:
            raise RuntimeError("Refresh devices and select an available device first.")
        request = ProfessionalOperationRequest(
            case_id=case_id, technician_id=technician_id, operation=operation,
            target_serial=serial,
        )
        validation = self.validation.validate(request, device)
        if not validation.success:
            self.audit.record(request, device, validation)
            return validation
        try:
            result = action(device)
        except (RuntimeError, ValueError, OSError) as error:
            result = OperationResult(False, str(error), error_code="diagnostic_failed")
        self.audit.record(request, device, result)
        return result

    @staticmethod
    def guidance(mode: str, state: str) -> str:
        normalized = state.casefold()
        if mode == "ADB" and normalized == "device":
            return "Authorized ADB: read-only diagnostics and bounded log capture are available."
        if mode == "ADB" and normalized == "unauthorized":
            return "Unauthorized: unlock the device, accept the USB debugging prompt, then refresh."
        if mode == "ADB" and normalized == "offline":
            return "Offline: reconnect USB, select File Transfer if offered, restart ADB, then refresh."
        if mode == "Fastboot":
            return "Fastboot: hardware identity checks are available; Android/ADB diagnostics require a normal authorized boot."
        if mode == "Download":
            return "Samsung Download Mode: detection is read-only. Use Samsung-authorized service tooling and procedures."
        return "Review the device connection state and vendor-authorized service procedure."

    @staticmethod
    def tool_status_message(tools: dict[str, str | None]) -> str:
        adb = "available" if tools.get("adb") else "not found"
        fastboot = "available" if tools.get("fastboot") else "not found"
        message = f"ADB: {adb}  |  Fastboot: {fastboot}"
        if not tools.get("adb") or not tools.get("fastboot"):
            message += (
                " — Configure without changing global PATH: set the process-local "
                "ARC3_ANDROID_PLATFORM_TOOLS environment variable to your existing "
                "Android platform-tools directory before starting ARC3 (PowerShell: "
                "$env:ARC3_ANDROID_PLATFORM_TOOLS='C:\\Android\\platform-tools'). "
                "ARC3 does not download or install platform-tools."
            )
        return message

    parse_adb_devices = staticmethod(
        lambda output: [AndroidDeviceService._legacy(item) for item in AdbWrapper.parse_devices(output)]
    )
    parse_fastboot_devices = staticmethod(
        lambda output: [AndroidDeviceService._legacy(item) for item in FastbootWrapper.parse_devices(output)]
    )

    @staticmethod
    def _legacy(device):
        return {
            "serial": device.serial, "mode": AndroidDeviceService._display_mode(device.mode.value), "state": device.state,
            "model": device.model or "Unknown", "product": device.product or "Unknown",
            "device": device.device or "Unknown",
        }

    @staticmethod
    def _display_mode(mode: str) -> str:
        return "ADB" if mode == "adb" else mode.capitalize()
