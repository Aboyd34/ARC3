from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Sequence

from app.services.device_models import DeviceMode, DeviceState


class CommandRunner:
    def __init__(self, timeout_seconds: int = 10) -> None:
        self.timeout_seconds = timeout_seconds

    def run(self, arguments: Sequence[str]) -> str:
        try:
            result = subprocess.run(
                list(arguments), capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=self.timeout_seconds, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                f"{arguments[0]} timed out after {self.timeout_seconds} seconds."
            ) from error
        except PermissionError as error:
            raise RuntimeError(f"Access denied while running {arguments[0]}.") from error
        except OSError as error:
            raise RuntimeError(f"Unable to run {arguments[0]}: {error}") from error
        if result.returncode != 0:
            message = result.stderr.strip() or "Unknown command error"
            raise RuntimeError(f"{arguments[0]} failed: {message}")
        return result.stdout

    def run_combined(self, arguments: Sequence[str]) -> str:
        """Run a command whose informational output may use stderr."""
        try:
            result = subprocess.run(
                list(arguments), capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=self.timeout_seconds, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                f"{arguments[0]} timed out after {self.timeout_seconds} seconds."
            ) from error
        except PermissionError as error:
            raise RuntimeError(f"Access denied while running {arguments[0]}.") from error
        except OSError as error:
            raise RuntimeError(f"Unable to run {arguments[0]}: {error}") from error
        output = "\n".join(
            part.strip() for part in (result.stdout, result.stderr) if part.strip()
        )
        if result.returncode != 0:
            raise RuntimeError(f"{arguments[0]} failed: {output or 'Unknown command error'}")
        return output


class AdbWrapper:
    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or CommandRunner()
        self.executable = shutil.which("adb")

    def list_devices(self) -> list[DeviceState]:
        if not self.executable:
            raise RuntimeError("ADB was not found in PATH.")
        return self.parse_devices(self.runner.run([self.executable, "devices", "-l"]))

    def reboot(self, serial: str, target: str) -> None:
        if target not in {"recovery", "bootloader"}:
            raise ValueError("Unsupported ADB reboot target.")
        if not self.executable:
            raise RuntimeError("ADB was not found in PATH.")
        self.runner.run([self.executable, "-s", serial, "reboot", target])

    def read_properties(self, serial: str) -> dict[str, str]:
        if not self.executable:
            raise RuntimeError("ADB was not found in PATH.")
        output = self.runner.run([self.executable, "-s", serial, "shell", "getprop"])
        return self.parse_properties(output)

    @staticmethod
    def parse_properties(output: str) -> dict[str, str]:
        properties = {}
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line.startswith("[") or "]: [" not in line or not line.endswith("]"):
                continue
            key, value = line[1:-1].split("]: [", 1)
            properties[key] = value
        return properties

    @staticmethod
    def parse_devices(output: str) -> list[DeviceState]:
        devices = []
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("List of devices") or line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            metadata = {}
            for value in parts[2:]:
                if ":" in value:
                    key, item_value = value.split(":", 1)
                    metadata[key] = item_value
            model = metadata.get("model")
            devices.append(DeviceState(
                serial=parts[0], mode=DeviceMode.ADB, state=parts[1],
                model=model.replace("_", " ") if model else None,
                product=metadata.get("product"), device=metadata.get("device"),
                oem=AdbWrapper.infer_oem(model), authorized=parts[1] == "device",
            ))
        return devices

    @staticmethod
    def infer_oem(model: str | None) -> str | None:
        if not model:
            return None
        normalized = model.upper().replace("_", "-")
        if normalized.startswith("SM-"):
            return "Samsung"
        if normalized.startswith(("MOTO", "XT")):
            return "Motorola"
        return None


class FastbootWrapper:
    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or CommandRunner()
        self.executable = shutil.which("fastboot")

    def list_devices(self) -> list[DeviceState]:
        if not self.executable:
            raise RuntimeError("Fastboot was not found in PATH.")
        return self.parse_devices(self.runner.run([self.executable, "devices"]))

    def reboot(self, serial: str, target: str | None = None) -> None:
        if target not in {None, "recovery", "bootloader"}:
            raise ValueError("Unsupported Fastboot reboot target.")
        if not self.executable:
            raise RuntimeError("Fastboot was not found in PATH.")
        arguments = [self.executable, "-s", serial, "reboot"]
        if target:
            arguments.append(target)
        self.runner.run(arguments)

    def read_variables(self, serial: str) -> dict[str, str]:
        if not self.executable:
            raise RuntimeError("Fastboot was not found in PATH.")
        output = self.runner.run_combined([
            self.executable, "-s", serial, "getvar", "all",
        ])
        return self.parse_variables(output)

    @staticmethod
    def parse_variables(output: str) -> dict[str, str]:
        variables = {}
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if line.startswith("(bootloader) "):
                line = line[len("(bootloader) "):]
            if ":" not in line or line.lower().startswith("finished."):
                continue
            key, value = line.split(":", 1)
            variables[key.strip()] = value.strip()
        return variables

    @staticmethod
    def parse_devices(output: str) -> list[DeviceState]:
        devices = []
        for raw_line in output.splitlines():
            parts = raw_line.split()
            if parts:
                devices.append(DeviceState(
                    serial=parts[0], mode=DeviceMode.FASTBOOT,
                    state=parts[1] if len(parts) > 1 else "fastboot",
                ))
        return devices


class SamsungDownloadWrapper:
    """Read-only Windows PnP detection for Samsung Download Mode USB devices."""

    DOWNLOAD_USB_IDS = ("VID_04E8&PID_685D",)

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or CommandRunner()
        self.executable = shutil.which("powershell") or shutil.which("powershell.exe")

    def list_devices(self) -> list[DeviceState]:
        if not self.executable:
            raise RuntimeError("Windows PowerShell was not found.")
        script = (
            "Get-PnpDevice -PresentOnly | "
            "Where-Object {$_.InstanceId -like 'USB*VID_04E8*'} | "
            "Select-Object InstanceId,FriendlyName,Status | ConvertTo-Json -Compress"
        )
        return self.parse_devices(self.runner.run([
            self.executable, "-NoProfile", "-NonInteractive", "-Command", script,
        ]))

    @classmethod
    def parse_devices(cls, output: str) -> list[DeviceState]:
        if not output.strip():
            return []
        payload = json.loads(output)
        records = payload if isinstance(payload, list) else [payload]
        devices = []
        for record in records:
            instance_id = str(record.get("InstanceId") or "")
            if not any(identifier in instance_id.upper() for identifier in cls.DOWNLOAD_USB_IDS):
                continue
            serial = instance_id.rsplit("\\", 1)[-1] or instance_id
            devices.append(DeviceState(
                serial=serial, mode=DeviceMode.DOWNLOAD,
                state=str(record.get("Status") or "Unknown"),
                model=str(record.get("FriendlyName") or "Samsung Download Mode"),
                oem="Samsung", authorized=True,
            ))
        return devices
