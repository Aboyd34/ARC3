import json
import unittest
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

from app.services.android_audit import AndroidAuditLogger
from app.services.android_wrappers import AdbWrapper, FastbootWrapper, SamsungDownloadWrapper
from app.services.device_discovery import DeviceDiscoveryAgent
from app.services.device_hardware import DeviceHardwareVerifier
from app.services.device_models import (
    DeviceMode, DeviceState, OperationType, ProfessionalOperationRequest,
)
from app.services.device_validation import ValidationAgent
from app.services.servicing_orchestrator import ServicingOrchestrator


class DeviceArchitectureTests(unittest.TestCase):
    def test_adb_property_parser(self):
        values = AdbWrapper.parse_properties(
            "[ro.product.model]: [Pixel 8]\n[ro.serialno]: [ABC123]\ninvalid"
        )
        self.assertEqual(values["ro.product.model"], "Pixel 8")
        self.assertEqual(values["ro.serialno"], "ABC123")

    def test_fastboot_variable_parser(self):
        values = FastbootWrapper.parse_variables(
            "(bootloader) product:panther\n(bootloader) serialno:ABC123\nFinished. Total time: 0.1s"
        )
        self.assertEqual(values, {"product": "panther", "serialno": "ABC123"})

    def test_hardware_verification_matches_adb_serial(self):
        adb = Mock()
        adb.read_properties.return_value = {
            "ro.serialno": "ABC123",
            "ro.product.model": "Pixel 8",
            "ro.hardware": "tensor",
        }
        device = DeviceState("ABC123", DeviceMode.ADB, "device", authorized=True)
        result = DeviceHardwareVerifier(adb=adb).verify(device)
        self.assertTrue(result.success)
        self.assertEqual(result.data["verification"], "Verified")

    def test_hardware_verification_flags_serial_mismatch(self):
        fastboot = Mock()
        fastboot.read_variables.return_value = {
            "serialno": "OTHER", "product": "panther",
        }
        device = DeviceState("ABC123", DeviceMode.FASTBOOT, "fastboot")
        result = DeviceHardwareVerifier(fastboot=fastboot).verify(device)
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "verification_incomplete")

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

    def test_orchestrator_does_not_route_diagnostics_as_a_reboot(self):
        request = ProfessionalOperationRequest(
            "CASE-1", "TECH-1", OperationType.RUN_DIAGNOSTICS, "ABC",
        )
        device = DeviceState("ABC", DeviceMode.ADB, "device", authorized=True)
        adb = Mock()
        audit = Mock()
        result = ServicingOrchestrator(adb=adb, audit=audit).handle(request, device)
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "unsupported_operation")
        adb.reboot.assert_not_called()
        audit.record.assert_called_once()

    def test_audit_redacts_sensitive_keys(self):
        serial = f"TEST-{uuid4().hex}"
        request = ProfessionalOperationRequest(
            "CASE-1", "TECH-1", OperationType.READ_INFO, serial,
            authorization_reference="private-reference",
        )
        device = DeviceState(serial, DeviceMode.ADB, "device", authorized=True)
        logger = AndroidAuditLogger(Path.cwd())
        path = None
        try:
            result = ServicingOrchestrator(audit=logger).handle(request, device)
            path = next(Path.cwd().glob(f"*_{serial}.log"))
            content = path.read_text(encoding="utf-8")
            entry = json.loads(content)
            self.assertTrue(result.success)
            self.assertNotIn("private-reference", content)
            self.assertEqual(entry["operation"], "read_info")
        finally:
            if path is not None:
                path.unlink(missing_ok=True)

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
