from __future__ import annotations

from app.services.android_wrappers import AdbWrapper, FastbootWrapper
from app.services.device_discovery import DeviceDiscoveryAgent
from app.services.device_models import OperationType, ProfessionalOperationRequest
from app.services.servicing_orchestrator import ServicingOrchestrator


class AndroidDeviceService:
    """UI-facing compatibility facade over the device discovery architecture."""

    def __init__(
        self,
        discovery: DeviceDiscoveryAgent | None = None,
        orchestrator: ServicingOrchestrator | None = None,
    ) -> None:
        self.discovery = discovery or DeviceDiscoveryAgent()
        self.orchestrator = orchestrator or ServicingOrchestrator()
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
