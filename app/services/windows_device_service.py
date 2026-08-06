from __future__ import annotations

import json
import re
import subprocess
from typing import Any
import xml.etree.ElementTree as ET

from app.adapters.windows.device_commands import WindowsDeviceCommandAdapter
from app.core.results import OperationResult
from app.domain.windows_devices import is_disabled, normalize_device, problem_number
from app.safety.device_operations import DeviceOperationPolicy


class WindowsDeviceService:
    """Enumerate and reversibly control Windows Plug and Play devices."""

    _MASKED_DRIVER_INF = re.compile(r"oem\d+\.---", re.IGNORECASE)

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
$signedDriver = Get-CimInstance Win32_PnPSignedDriver -Filter "DeviceID='$($InstanceId.Replace("'", "''"))'" -ErrorAction SilentlyContinue |
    Select-Object -First 1
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
    driver_is_signed = $signedDriver.IsSigned
    driver_signer = $signedDriver.Signer
    service = $properties['DEVPKEY_Device_Service']
    enumerator = $properties['DEVPKEY_Device_EnumeratorName']
    location = $properties['DEVPKEY_Device_LocationInfo']
    parent = $properties['DEVPKEY_Device_Parent']
    container_id = $properties['DEVPKEY_Device_ContainerId']
} | ConvertTo-Json -Compress -Depth 4
"""

    def __init__(self, runner=None) -> None:
        self.commands = WindowsDeviceCommandAdapter(runner)
        self.runner = self.commands.runner

    def collect_devices(self) -> list[dict[str, Any]]:
        try:
            completed = self.commands.powershell(self.ENUMERATION_SCRIPT, timeout=45)
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
            completed = self.commands.powershell(
                self.DETAILS_SCRIPT, instance_id, timeout=30,
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
        installed_driver = self._installed_driver(element)
        driver_inf = element.findtext("DriverName", "")
        if self._is_masked_driver_inf(driver_inf):
            try:
                driver_inf = self._resolve_published_driver(installed_driver) or driver_inf
            except RuntimeError:
                # Details remain useful and the masked value stays non-exportable.
                pass
        driver_signer = self._driver_signer(installed_driver)
        details = {
            **record,
            "present": str(properties.get("DEVPKEY_Device_IsPresent", "")).casefold() == "true",
            "description": properties.get("DEVPKEY_Device_DeviceDesc", record["name"]),
            "hardware_ids": properties.get("DEVPKEY_Device_HardwareIds", []),
            "compatible_ids": properties.get("DEVPKEY_Device_CompatibleIds", []),
            "class_guid": element.findtext("ClassGuid", ""),
            "driver_inf_path": driver_inf,
            "driver_is_signed": self._signed_driver_value(element, driver_signer),
            "driver_signer": driver_signer,
            "service": properties.get("DEVPKEY_Device_Service", ""),
            "enumerator": properties.get("DEVPKEY_Device_EnumeratorName", ""),
            "location": properties.get("DEVPKEY_Device_LocationInfo", ""),
            "parent": properties.get("DEVPKEY_Device_Parent", ""),
            "container_id": properties.get("DEVPKEY_Device_ContainerId", ""),
        }
        return {key: self._display_value(value) for key, value in details.items()}

    @staticmethod
    def _signed_driver_value(element: ET.Element, signer: str = "") -> bool | str:
        value = element.findtext("IsSigned", "")
        if not value:
            value = str(WindowsDeviceService._pnputil_properties(element).get(
                "DEVPKEY_Device_DriverIsSigned", "",
            ))
        if not value:
            return True if signer.strip() else "Not reported"
        return value.casefold() == "true"

    @staticmethod
    def _driver_signer(installed_driver: ET.Element | None) -> str:
        return (
            installed_driver.findtext("SignerName", "")
            if installed_driver is not None else ""
        )

    @staticmethod
    def _installed_driver(element: ET.Element) -> ET.Element | None:
        drivers = element.findall("./MatchingDrivers/DriverName")
        return next(
            (driver for driver in drivers
             if "installed" in driver.findtext("Status", "").casefold()),
            drivers[0] if drivers else None,
        )

    @classmethod
    def _is_masked_driver_inf(cls, value: str) -> bool:
        return bool(cls._MASKED_DRIVER_INF.fullmatch((value or "").strip()))

    def _resolve_published_driver(self, installed_driver: ET.Element | None) -> str:
        if installed_driver is None:
            return ""
        identity_fields = ("OriginalName", "ProviderName", "ClassGuid", "DriverVersion")
        identity = {
            field: installed_driver.findtext(field, "").strip().casefold()
            for field in identity_fields
        }
        if not identity["OriginalName"]:
            return ""
        root = self._pnputil_xml(["/enum-drivers"])
        matches = []
        for candidate in root.findall("Driver"):
            if all(
                not expected
                or candidate.findtext(field, "").strip().casefold() == expected
                for field, expected in identity.items()
            ):
                published_name = candidate.get("DriverName", "").strip()
                if DeviceOperationPolicy.valid_driver_inf(published_name):
                    matches.append(published_name)
        unique_matches = list(dict.fromkeys(matches))
        return unique_matches[0] if len(unique_matches) == 1 else ""

    def _pnputil_xml(self, arguments: list[str]) -> ET.Element:
        try:
            completed = self.commands.pnputil(
                [*arguments, "/format", "xml"], timeout=60,
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
        installed_driver = cls._installed_driver(element)
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
        return normalize_device(record)

    @staticmethod
    def _is_disabled(problem: Any, status: str) -> bool:
        return is_disabled(problem, status)

    @staticmethod
    def _problem_number(problem: Any) -> int | None:
        return problem_number(problem)

    def set_enabled(self, instance_id: str, enabled: bool) -> OperationResult:
        if not self._valid_instance_id(instance_id):
            return OperationResult(False, "The selected device identifier is invalid.")
        action = "/enable-device" if enabled else "/disable-device"
        try:
            completed = self.commands.pnputil([action, instance_id], timeout=30)
        except FileNotFoundError:
            return OperationResult(False, "Device control is not supported on this Windows version.")
        except PermissionError:
            return OperationResult(False, "Access was denied. Run ARC3 with the required administrator access.")
        except subprocess.TimeoutExpired:
            return OperationResult(False, "Windows did not finish the device operation in time.")
        except OSError as error:
            return OperationResult(False, f"Windows could not change the device state: {error}")
        output = (completed.stdout or completed.stderr).strip()
        if completed.returncode:
            return OperationResult(False, output or "Windows rejected the device operation.")
        state = "enabled" if enabled else "disabled"
        return OperationResult(True, output or f"The device was {state}.")

    def export_driver(self, driver_inf: str, destination: str) -> OperationResult:
        if not DeviceOperationPolicy.valid_driver_inf(driver_inf):
            return OperationResult(False, "Windows did not report a valid driver INF name.")
        if not destination or "\n" in destination or "\r" in destination:
            return OperationResult(False, "Select a valid driver export folder.")
        try:
            completed = self.commands.pnputil(
                ["/export-driver", driver_inf, destination], timeout=120,
            )
        except FileNotFoundError:
            return OperationResult(False, "Driver export is not supported on this Windows version.")
        except PermissionError:
            return OperationResult(False, "Access was denied while exporting the driver.")
        except subprocess.TimeoutExpired:
            return OperationResult(False, "Windows did not finish exporting the driver in time.")
        except OSError as error:
            return OperationResult(False, f"Windows could not export the driver: {error}")
        output = (completed.stdout or completed.stderr).strip()
        if completed.returncode:
            return OperationResult(False, output or "Windows rejected the driver export.")
        return OperationResult(True, output or "The driver package was exported.")

    def open_device_manager(self) -> OperationResult:
        try:
            self.commands.open_device_manager()
        except (FileNotFoundError, PermissionError, OSError) as error:
            return OperationResult(False, f"Windows Device Manager could not be opened: {error}")
        return OperationResult(True, "Windows Device Manager was opened.")

    @staticmethod
    def _valid_instance_id(instance_id: str) -> bool:
        return DeviceOperationPolicy.valid_instance_id(instance_id)

    @staticmethod
    def _display_value(value: Any) -> Any:
        if isinstance(value, list):
            return [str(item) for item in value if item is not None]
        return "" if value is None else value
