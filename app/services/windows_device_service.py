from __future__ import annotations

import json
import subprocess
from typing import Any
import xml.etree.ElementTree as ET


class WindowsDeviceService:
    """Enumerate and reversibly control Windows Plug and Play devices."""

    ENUMERATION_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$devices = Get-PnpDevice | ForEach-Object {
    $device = $_
    $properties = @{}
    Get-PnpDeviceProperty -InstanceId $device.InstanceId -ErrorAction SilentlyContinue |
        ForEach-Object { $properties[$_.KeyName] = $_.Data }
    [PSCustomObject]@{
        name = if ($device.FriendlyName) { $device.FriendlyName } else { $device.InstanceId }
        class = $device.Class
        status = $device.Status
        problem_code = $device.Problem
        instance_id = $device.InstanceId
        manufacturer = $properties['DEVPKEY_Device_Manufacturer']
        driver_provider = $properties['DEVPKEY_Device_DriverProvider']
        driver_version = $properties['DEVPKEY_Device_DriverVersion']
        driver_date = $properties['DEVPKEY_Device_DriverDate']
        enabled = ($device.Status -ne 'Disabled')
    }
}
@($devices) | ConvertTo-Json -Compress -Depth 4
"""

    DETAILS_SCRIPT = r"""
param([string]$InstanceId)
$ErrorActionPreference = 'Stop'
$device = Get-PnpDevice -InstanceId $InstanceId -ErrorAction Stop
$properties = @{}
Get-PnpDeviceProperty -InstanceId $InstanceId -ErrorAction SilentlyContinue |
    ForEach-Object { $properties[$_.KeyName] = $_.Data }
[PSCustomObject]@{
    name = if ($device.FriendlyName) { $device.FriendlyName } else { $device.InstanceId }
    class = $device.Class
    status = $device.Status
    problem_code = $device.Problem
    instance_id = $device.InstanceId
    present = $device.Present
    manufacturer = $properties['DEVPKEY_Device_Manufacturer']
    description = $properties['DEVPKEY_Device_DeviceDesc']
    hardware_ids = $properties['DEVPKEY_Device_HardwareIds']
    compatible_ids = $properties['DEVPKEY_Device_CompatibleIds']
    class_guid = $properties['DEVPKEY_Device_ClassGuid']
    driver_provider = $properties['DEVPKEY_Device_DriverProvider']
    driver_version = $properties['DEVPKEY_Device_DriverVersion']
    driver_date = $properties['DEVPKEY_Device_DriverDate']
    driver_inf_path = $properties['DEVPKEY_Device_DriverInfPath']
    service = $properties['DEVPKEY_Device_Service']
    enumerator = $properties['DEVPKEY_Device_EnumeratorName']
    location = $properties['DEVPKEY_Device_LocationInfo']
    parent = $properties['DEVPKEY_Device_Parent']
    container_id = $properties['DEVPKEY_Device_ContainerId']
} | ConvertTo-Json -Compress -Depth 4
"""

    def __init__(self, runner=None) -> None:
        self.runner = runner or subprocess.run

    def collect_devices(self) -> list[dict[str, Any]]:
        try:
            completed = self.runner(
                [
                    "powershell.exe", "-NoProfile", "-NonInteractive",
                    "-ExecutionPolicy", "Bypass", "-Command", self.ENUMERATION_SCRIPT,
                ],
                capture_output=True, text=True, timeout=45, check=False,
            )
        except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired, OSError):
            return self._collect_devices_with_pnputil()
        if completed.returncode:
            return self._collect_devices_with_pnputil()
        output = completed.stdout.strip()
        if not output:
            return []
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            return self._collect_devices_with_pnputil()
        if not isinstance(parsed, (dict, list)):
            return self._collect_devices_with_pnputil()
        records = parsed if isinstance(parsed, list) else [parsed]
        if not all(isinstance(record, dict) for record in records):
            return self._collect_devices_with_pnputil()
        return sorted(
            (self._normalize(record) for record in records),
            key=lambda item: (item["class"].casefold(), item["name"].casefold()),
        )

    def collect_details(self, instance_id: str) -> dict[str, Any]:
        """Collect read-only identity, topology, and driver evidence."""
        if not self._valid_instance_id(instance_id):
            raise ValueError("The selected device identifier is invalid.")
        try:
            completed = self.runner(
                [
                    "powershell.exe", "-NoProfile", "-NonInteractive",
                    "-ExecutionPolicy", "Bypass", "-Command",
                    self.DETAILS_SCRIPT, instance_id,
                ],
                capture_output=True, text=True, timeout=30, check=False,
            )
        except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired, OSError):
            return self._collect_details_with_pnputil(instance_id)
        if completed.returncode:
            return self._collect_details_with_pnputil(instance_id)
        try:
            record = json.loads(completed.stdout.strip())
        except json.JSONDecodeError:
            return self._collect_details_with_pnputil(instance_id)
        if not isinstance(record, dict):
            return self._collect_details_with_pnputil(instance_id)
        return {key: self._display_value(value) for key, value in record.items()}

    def _collect_devices_with_pnputil(self) -> list[dict[str, Any]]:
        root = self._pnputil_xml(["/enum-devices", "/drivers"])
        records = [self._pnputil_record(element) for element in root.findall("Device")]
        return sorted(
            (self._normalize(record) for record in records),
            key=lambda item: (item["class"].casefold(), item["name"].casefold()),
        )

    def _collect_details_with_pnputil(self, instance_id: str) -> dict[str, Any]:
        root = self._pnputil_xml([
            "/enum-devices", "/instanceid", instance_id,
            "/deviceids", "/drivers", "/properties",
        ])
        element = root.find("Device")
        if element is None:
            raise RuntimeError("Windows did not return the selected device details.")
        record = self._pnputil_record(element)
        properties = self._pnputil_properties(element)
        details = {
            **record,
            "present": str(properties.get("DEVPKEY_Device_IsPresent", "")).casefold() == "true",
            "description": properties.get("DEVPKEY_Device_DeviceDesc", record["name"]),
            "hardware_ids": properties.get("DEVPKEY_Device_HardwareIds", []),
            "compatible_ids": properties.get("DEVPKEY_Device_CompatibleIds", []),
            "class_guid": element.findtext("ClassGuid", ""),
            "driver_inf_path": element.findtext("DriverName", ""),
            "service": properties.get("DEVPKEY_Device_Service", ""),
            "enumerator": properties.get("DEVPKEY_Device_EnumeratorName", ""),
            "location": properties.get("DEVPKEY_Device_LocationInfo", ""),
            "parent": properties.get("DEVPKEY_Device_Parent", ""),
            "container_id": properties.get("DEVPKEY_Device_ContainerId", ""),
        }
        return {key: self._display_value(value) for key, value in details.items()}

    def _pnputil_xml(self, arguments: list[str]) -> ET.Element:
        try:
            completed = self.runner(
                ["pnputil.exe", *arguments, "/format", "xml"],
                capture_output=True, text=True, timeout=60, check=False,
            )
        except FileNotFoundError as error:
            raise RuntimeError("Windows device inspection is not supported.") from error
        except PermissionError as error:
            raise RuntimeError("Access was denied while inspecting Windows devices.") from error
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("Windows did not enumerate devices in time.") from error
        except OSError as error:
            raise RuntimeError(f"Windows device inspection failed: {error}") from error
        if completed.returncode:
            message = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(message or "Windows device inspection failed.")
        try:
            return ET.fromstring(completed.stdout.lstrip("\ufeff").strip())
        except ET.ParseError as error:
            raise RuntimeError("Windows returned invalid device information.") from error

    @classmethod
    def _pnputil_record(cls, element: ET.Element) -> dict[str, Any]:
        properties = cls._pnputil_properties(element)
        drivers = element.findall("./MatchingDrivers/DriverName")
        installed_driver = next(
            (driver for driver in drivers
             if "installed" in driver.findtext("Status", "").casefold()),
            drivers[0] if drivers else None,
        )
        provider = properties.get("DEVPKEY_Device_DriverProvider", "Unknown")
        version = properties.get("DEVPKEY_Device_DriverVersion", "Unknown")
        if installed_driver is not None:
            provider = installed_driver.findtext("ProviderName", str(provider))
            version = installed_driver.findtext("DriverVersion", str(version))
        problem = element.findtext(
            "ProblemCode", str(properties.get("DEVPKEY_Device_ProblemCode", "")),
        )
        status = element.findtext("Status", "Unknown")
        return {
            "name": element.findtext("DeviceDescription", "Unknown device"),
            "class": element.findtext("ClassName", "Unknown"),
            "status": status,
            "problem_code": problem,
            "instance_id": element.get("InstanceId", ""),
            "manufacturer": element.findtext("ManufacturerName", "Unknown"),
            "driver_provider": provider,
            "driver_version": version,
            "driver_date": properties.get("DEVPKEY_Device_DriverDate", "Unknown"),
            "enabled": not cls._is_disabled(problem, status),
        }

    @staticmethod
    def _pnputil_properties(element: ET.Element) -> dict[str, Any]:
        properties = {}
        for item in element.findall("./Properties/Property"):
            values = [value.text or "" for value in item.findall("Value")]
            if values:
                properties[item.get("Key", "")] = values if len(values) > 1 else values[0]
        return properties

    def verify_hardware(self, instance_id: str) -> dict[str, Any]:
        """Check Windows-reported identity evidence for internal consistency."""
        details = self.collect_details(instance_id)
        reported_id = str(details.get("instance_id") or "")
        checks = {
            "device_present": details.get("present") is True,
            "instance_id_matches": reported_id.casefold() == instance_id.casefold(),
            "hardware_identity_reported": bool(details.get("hardware_ids")),
            "device_class_reported": bool(details.get("class")),
        }
        verified = all(checks.values())
        return {
            "verification": "Verified" if verified else "Needs review",
            "checks": checks,
            "details": details,
            "message": (
                "Windows hardware identity evidence is internally consistent."
                if verified else
                "Windows hardware identity evidence is incomplete or inconsistent."
            ),
        }

    @staticmethod
    def _normalize(record: dict[str, Any]) -> dict[str, Any]:
        status = str(record.get("status") or "Unknown")
        problem = record.get("problem_code")
        disabled_by_problem = WindowsDeviceService._is_disabled(problem, status)
        enabled = bool(record.get(
            "enabled",
            status.casefold() != "disabled" and not disabled_by_problem,
        ))
        if disabled_by_problem:
            enabled = False
        problem_number = WindowsDeviceService._problem_number(problem)
        no_problem = problem in (None, "") or problem_number == 0
        healthy_status = status.casefold() in {"ok", "started", "stopped"}
        if not enabled:
            health = "Disabled"
        elif healthy_status and no_problem:
            health = "Healthy"
        else:
            health = "Needs attention"
        return {
            "name": str(record.get("name") or "Unknown device"),
            "class": str(record.get("class") or "Unknown"),
            "status": status,
            "health": health,
            "problem_code": "" if problem is None else str(problem),
            "manufacturer": str(record.get("manufacturer") or "Unknown"),
            "driver_provider": str(record.get("driver_provider") or "Unknown"),
            "driver_version": str(record.get("driver_version") or "Unknown"),
            "driver_date": str(record.get("driver_date") or "Unknown"),
            "instance_id": str(record.get("instance_id") or ""),
            "enabled": enabled,
        }

    @staticmethod
    def _is_disabled(problem: Any, status: str) -> bool:
        value = str(problem).strip().casefold()
        if value == "cm_prob_disabled":
            return True
        return (
            WindowsDeviceService._problem_number(problem) == 22
            or status.casefold() == "disabled"
        )

    @staticmethod
    def _problem_number(problem: Any) -> int | None:
        value = str(problem).strip().casefold()
        try:
            return int(value, 0)
        except ValueError:
            return None

    def set_enabled(self, instance_id: str, enabled: bool) -> tuple[bool, str]:
        if not self._valid_instance_id(instance_id):
            return False, "The selected device identifier is invalid."
        action = "/enable-device" if enabled else "/disable-device"
        try:
            completed = self.runner(
                ["pnputil.exe", action, instance_id],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except FileNotFoundError:
            return False, "Device control is not supported on this Windows version."
        except PermissionError:
            return False, "Access was denied. Run ARC3 with the required administrator access."
        except subprocess.TimeoutExpired:
            return False, "Windows did not finish the device operation in time."
        except OSError as error:
            return False, f"Windows could not change the device state: {error}"
        output = (completed.stdout or completed.stderr).strip()
        if completed.returncode:
            return False, output or "Windows rejected the device operation."
        state = "enabled" if enabled else "disabled"
        return True, output or f"The device was {state}."

    @staticmethod
    def _valid_instance_id(instance_id: str) -> bool:
        return bool(
            instance_id and instance_id.strip() == instance_id
            and "\n" not in instance_id and "\r" not in instance_id
            and len(instance_id) <= 4096
        )

    @staticmethod
    def _display_value(value: Any) -> Any:
        if isinstance(value, list):
            return [str(item) for item in value if item is not None]
        return "" if value is None else value
