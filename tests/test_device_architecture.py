import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from app.services.android_audit import AndroidAuditLogger
from app.services.android_wrappers import SamsungDownloadWrapper
from app.services.device_discovery import DeviceDiscoveryAgent
from app.services.device_models import (
    DeviceMode, DeviceState, OperationType, ProfessionalOperationRequest,
)
from app.services.device_validation import ValidationAgent
from app.services.servicing_orchestrator import ServicingOrchestrator


class DeviceArchitectureTests(unittest.TestCase):
    def test_discovery_unifies_and_deduplicates_wrappers(self):
        device = DeviceState("ABC", DeviceMode.ADB, "device", authorized=True)
        adb = Mock(executable="adb.exe")
        adb.list_devices.return_value = [device, device]
        fastboot = Mock(executable="fastboot.exe")
        fastboot.list_devices.return_value = []
        samsung = Mock(executable="powershell.exe")
        samsung.list_devices.return_value = []
        result = DeviceDiscoveryAgent(adb, fastboot, samsung).discover()
        self.assertEqual(result.devices, (device,))
        self.assertEqual(result.errors, ())

    def test_validation_blocks_unauthorized_adb_reboot(self):
        request = ProfessionalOperationRequest(
            "CASE-1", "TECH-1", OperationType.REBOOT_RECOVERY,
            "ABC", ownership_confirmed=True,
        )
        device = DeviceState("ABC", DeviceMode.ADB, "unauthorized")
        result = ValidationAgent().validate(request, device)
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "adb_unauthorized")

    def test_orchestrator_routes_authorized_adb_reboot(self):
        request = ProfessionalOperationRequest(
            "CASE-1", "TECH-1", OperationType.REBOOT_RECOVERY,
            "ABC", ownership_confirmed=True,
        )
        device = DeviceState("ABC", DeviceMode.ADB, "device", authorized=True)
        adb = Mock()
        audit = Mock()
        result = ServicingOrchestrator(adb=adb, audit=audit).handle(request, device)
        self.assertTrue(result.success)
        adb.reboot.assert_called_once_with("ABC", "recovery")
        audit.record.assert_called_once()

    def test_audit_redacts_sensitive_keys(self):
        request = ProfessionalOperationRequest(
            "CASE-1", "TECH-1", OperationType.READ_INFO, "ABC",
            authorization_reference="private-reference",
        )
        device = DeviceState("ABC", DeviceMode.ADB, "device", authorized=True)
        with tempfile.TemporaryDirectory() as directory:
            logger = AndroidAuditLogger(Path(directory))
            result = ServicingOrchestrator(audit=logger).handle(request, device)
            content = next(Path(directory).glob("*.log")).read_text(encoding="utf-8")
            entry = json.loads(content)
            self.assertTrue(result.success)
            self.assertNotIn("private-reference", content)
            self.assertEqual(entry["operation"], "read_info")

    def test_samsung_download_mode_requires_known_usb_id(self):
        output = json.dumps({
            "InstanceId": "USB\\VID_04E8&PID_685D\\SERIAL1",
            "FriendlyName": "Samsung Mobile USB CDC Composite Device",
            "Status": "OK",
        })
        devices = SamsungDownloadWrapper.parse_devices(output)
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].mode, DeviceMode.DOWNLOAD)
        self.assertEqual(devices[0].oem, "Samsung")


if __name__ == "__main__":
    unittest.main()
