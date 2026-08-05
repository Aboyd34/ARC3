from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import tempfile

from app.services.android_wrappers import AdbWrapper
from app.services.device_models import DeviceState, OperationResult


class AndroidDiagnosticsService:
    """Allowlisted, read-only ADB diagnostics and bounded log capture."""

    BUILD_KEYS = (
        "ro.product.manufacturer", "ro.product.model", "ro.product.device",
        "ro.build.version.release", "ro.build.version.sdk", "ro.build.id",
        "ro.build.fingerprint", "ro.build.version.security_patch",
    )
    SECURITY_KEYS = (
        "ro.boot.verifiedbootstate", "ro.boot.flash.locked", "ro.boot.vbmeta.device_state",
        "ro.crypto.state", "ro.secure", "ro.debuggable",
    )

    def __init__(self, adb: AdbWrapper | None = None) -> None:
        self.adb = adb or AdbWrapper()

    def collect(self, device: DeviceState) -> OperationResult:
        properties = self.adb.read_properties(device.serial)
        data = {
            "battery": self.adb.read_battery(device.serial),
            "storage": self.adb.read_storage(device.serial),
            "build": self._select(properties, self.BUILD_KEYS),
            "security": self._select(properties, self.SECURITY_KEYS),
        }
        return OperationResult(True, "ADB diagnostics collected.", data=data)

    def capture_logcat(
        self, device: DeviceState, max_lines: int, export_path: Path,
    ) -> OperationResult:
        destination = export_path.expanduser().resolve()
        if destination.exists() and destination.is_dir():
            raise ValueError("Choose a file path for the logcat export, not a directory.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        output = self.adb.capture_logcat(device.serial, max_lines)
        safe_serial = re.sub(r"[\r\n\t]", "_", device.serial)
        header = (
            f"ARC3 bounded logcat capture\n"
            f"Captured UTC: {datetime.now(timezone.utc).isoformat()}\n"
            f"Device serial: {safe_serial}\n\n"
        )
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", newline="\n", delete=False,
                dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp",
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(header)
                handle.write(output)
                handle.flush()
                os.fsync(handle.fileno())
            temporary_path.replace(destination)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return OperationResult(
            True, "Bounded logcat capture exported.",
            data={"export_path": str(destination), "characters": len(output),
                  "requested_lines": max_lines},
        )

    @staticmethod
    def _select(values: dict[str, str], keys: tuple[str, ...]) -> dict[str, str]:
        return {key: values.get(key, "Unknown") for key in keys}
