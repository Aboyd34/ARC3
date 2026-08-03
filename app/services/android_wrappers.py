from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from app.services.device_models import DeviceMode, DeviceState


def find_platform_tool(name: str) -> str | None:
    """Resolve a tool from ARC3's process-local directory before PATH."""
    configured = os.environ.get("ARC3_ANDROID_PLATFORM_TOOLS", "").strip()
    if configured:
        candidate = Path(configured) / f"{name}.exe"
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


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
    LOGCAT_MIN_LINES = 50
    LOGCAT_MAX_LINES = 5000
    LOGCAT_MAX_CHARACTERS = 2_000_000

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or CommandRunner()
        self.executable = find_platform_tool("adb")

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

    def read_battery(self, serial: str) -> dict[str, str]:
        return self.parse_colon_values(self._shell(serial, ["dumpsys", "battery"]))

    def read_storage(self, serial: str) -> dict[str, str]:
        output = self._shell(serial, ["df", "-k", "/data"])
        lines = [line.split() for line in output.splitlines() if line.strip()]
        if len(lines) < 2 or len(lines[-1]) < 5:
            return {"raw": output.strip() or "Unavailable"}
        row = lines[-1]
        return {
            "filesystem": row[0], "total_kb": row[1], "used_kb": row[2],
            "available_kb": row[3], "used_percent": row[4],
        }

    def capture_logcat(self, serial: str, max_lines: int = 1000) -> str:
        bounded_lines = max(self.LOGCAT_MIN_LINES, min(int(max_lines), self.LOGCAT_MAX_LINES))
        output = self._command([
            "-s", serial, "logcat", "-d", "-t", str(bounded_lines), "-v", "threadtime",
        ])
        return output[:self.LOGCAT_MAX_CHARACTERS]

    def _shell(self, serial: str, arguments: list[str]) -> str:
        return self._command(["-s", serial, "shell", *arguments])

    def _command(self, arguments: list[str]) -> str:
        if not self.executable:
            raise RuntimeError("ADB was not found in PATH.")
        return self.runner.run([self.executable, *arguments])

    @staticmethod
    def parse_colon_values(output: str) -> dict[str, str]:
        values = {}
        for raw_line in output.splitlines():
            if ":" not in raw_line:
                continue
            key, value = raw_line.strip().split(":", 1)
            values[key.strip().replace(" ", "_")] = value.strip()
        return values

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
        self.executable = find_platform_tool("fastboot")

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
            "Where-Object {$_.InstanceId -like 'USB*VID_04E8*'} | ForEach-Object { "
            "$parent=(Get-PnpDeviceProperty -InstanceId $_.InstanceId "
            "-KeyName 'DEVPKEY_Device_Parent' -ErrorAction SilentlyContinue).Data; "
            "[PSCustomObject]@{InstanceId=$_.InstanceId;FriendlyName=$_.FriendlyName;"
            "Status=$_.Status;ParentInstanceId=$parent} } | ConvertTo-Json -Compress"
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
        grouped = {}
        for record in records:
            instance_id = str(record.get("InstanceId") or "")
            if not any(identifier in instance_id.upper() for identifier in cls.DOWNLOAD_USB_IDS):
                continue
            physical_key = cls._physical_key(record)
            current = grouped.get(physical_key)
            if current is None or cls._interface_rank(record) < cls._interface_rank(current):
                grouped[physical_key] = record
        devices = []
        for physical_key in sorted(grouped):
            record = grouped[physical_key]
            digest = hashlib.sha256(physical_key.encode("utf-8")).hexdigest()[:16].upper()
            devices.append(DeviceState(
                serial=f"SAMSUNG-DL-{digest}", mode=DeviceMode.DOWNLOAD,
                state=str(record.get("Status") or "Unknown"),
                model=str(record.get("FriendlyName") or "Samsung Download Mode"),
                oem="Samsung", authorized=True,
            ))
        return devices

    @staticmethod
    def _physical_key(record: dict) -> str:
        parent = str(record.get("ParentInstanceId") or "").strip()
        if parent:
            return parent.upper()
        instance_id = str(record.get("InstanceId") or "").strip().upper()
        parts = instance_id.split("\\", 1)
        hardware_id = re.sub(r"&MI_[0-9A-F]{2}", "", parts[0])
        if len(parts) == 1:
            return hardware_id
        interface_suffix = re.sub(r"&[0-9]{4}$", "", parts[1])
        return f"{hardware_id}\\{interface_suffix}"

    @staticmethod
    def _interface_rank(record: dict) -> tuple[int, str]:
        name = str(record.get("FriendlyName") or "").casefold()
        if "composite" in name:
            rank = 0
        elif "download" in name:
            rank = 1
        elif "modem" in name:
            rank = 9
        else:
            rank = 5
        return rank, name
