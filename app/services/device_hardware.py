from __future__ import annotations

from app.services.android_wrappers import AdbWrapper, FastbootWrapper
from app.services.device_models import DeviceMode, DeviceState, OperationResult


class DeviceHardwareVerifier:
    """Collect read-only hardware evidence and verify the selected identity."""

    def __init__(self, adb=None, fastboot=None) -> None:
        self.adb = adb or AdbWrapper()
        self.fastboot = fastboot or FastbootWrapper()

    def verify(self, device: DeviceState) -> OperationResult:
        if device.mode is DeviceMode.ADB:
            if not device.authorized:
                return OperationResult(
                    False,
                    "Authorize this computer on the device before hardware verification.",
                    error_code="adb_unauthorized",
                )
            return self._verify_adb(device, self.adb.read_properties(device.serial))
        if device.mode is DeviceMode.FASTBOOT:
            return self._verify_fastboot(device, self.fastboot.read_variables(device.serial))
        return OperationResult(
            False,
            "Hardware verification is not supported in Download mode.",
            error_code="unsupported_mode",
        )

    @staticmethod
    def _verify_adb(device: DeviceState, values: dict[str, str]) -> OperationResult:
        details = {
            "manufacturer": values.get("ro.product.manufacturer") or device.oem or "Unknown",
            "model": values.get("ro.product.model") or device.model or "Unknown",
            "product": values.get("ro.product.name") or device.product or "Unknown",
            "device": values.get("ro.product.device") or device.device or "Unknown",
            "hardware": values.get("ro.hardware") or "Unknown",
            "android_version": values.get("ro.build.version.release") or "Unknown",
            "security_patch": values.get("ro.build.version.security_patch") or "Unknown",
            "build_fingerprint": values.get("ro.build.fingerprint") or "Unknown",
            "bootloader": values.get("ro.bootloader") or "Unknown",
        }
        reported_serial = values.get("ro.serialno") or values.get("ro.boot.serialno")
        return DeviceHardwareVerifier._result(device, details, reported_serial)

    @staticmethod
    def _verify_fastboot(device: DeviceState, values: dict[str, str]) -> OperationResult:
        details = {
            "manufacturer": device.oem or "Unknown",
            "model": values.get("product") or device.model or "Unknown",
            "product": values.get("product") or device.product or "Unknown",
            "hardware": values.get("variant") or values.get("hw-revision") or "Unknown",
            "bootloader": values.get("version-bootloader") or "Unknown",
            "baseband": values.get("version-baseband") or "Unknown",
            "unlocked": values.get("unlocked") or "Unknown",
            "secure": values.get("secure") or "Unknown",
        }
        reported_serial = values.get("serialno")
        return DeviceHardwareVerifier._result(device, details, reported_serial)

    @staticmethod
    def _result(
        device: DeviceState, details: dict[str, str], reported_serial: str | None,
    ) -> OperationResult:
        serial_matches = bool(reported_serial) and reported_serial.casefold() == device.serial.casefold()
        checks = {
            "transport_detected": True,
            "serial_reported": bool(reported_serial),
            "serial_matches_transport": serial_matches,
            "identity_fields_present": any(
                details.get(key) not in {None, "", "Unknown"}
                for key in ("manufacturer", "model", "product", "hardware")
            ),
        }
        verified = all(checks.values())
        data = {
            "serial": device.serial,
            "reported_serial": reported_serial or "Not reported",
            "mode": device.mode.value,
            **details,
            "verification": "Verified" if verified else "Needs review",
            "checks": checks,
        }
        message = (
            "Hardware identity verified."
            if verified else
            "Hardware details collected, but the identity checks need review."
        )
        return OperationResult(verified, message, data=data,
                               error_code=None if verified else "verification_incomplete")
