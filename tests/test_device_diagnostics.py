import json
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication, QMessageBox, QStackedWidget, QTableWidgetItem, QWidget,
)

from app.pages.android_workspace import AndroidWorkspace
from app.services.android_device_service import AndroidDeviceService
from app.services.android_diagnostics import AndroidDiagnosticsService
from app.services.android_wrappers import AdbWrapper
from app.services.android_wrappers import SamsungDownloadWrapper
from app.services.device_models import DeviceMode, DeviceState
from app.ui.phase4_enhancements import refresh_visible_page


class DeviceDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_battery_parser_normalizes_keys(self):
        values = AdbWrapper.parse_colon_values("level: 82\nUSB powered: true\n")
        self.assertEqual(values, {"level": "82", "USB_powered": "true"})

    def test_logcat_command_is_allowlisted_and_bounded(self):
        runner = Mock()
        runner.run.return_value = "log output"
        adb = AdbWrapper(runner)
        adb.executable = "adb.exe"
        self.assertEqual(adb.capture_logcat("SERIAL", 99999), "log output")
        runner.run.assert_called_once_with([
            "adb.exe", "-s", "SERIAL", "logcat", "-d", "-t", "5000",
            "-v", "threadtime",
        ])

    def test_diagnostics_collects_four_read_only_sections(self):
        adb = Mock()
        adb.read_properties.return_value = {
            "ro.product.model": "Pixel", "ro.secure": "1",
        }
        adb.read_battery.return_value = {"level": "90"}
        adb.read_storage.return_value = {"used_percent": "25%"}
        device = DeviceState("ABC", DeviceMode.ADB, "device", authorized=True)
        result = AndroidDiagnosticsService(adb).collect(device)
        self.assertTrue(result.success)
        self.assertEqual(set(result.data), {"battery", "storage", "build", "security"})

    def test_hardware_verification_is_audited(self):
        device = DeviceState("ABC", DeviceMode.ADB, "device", authorized=True)
        discovery = Mock()
        verifier = Mock()
        verifier.verify.return_value.success = True
        audit = Mock()
        service = AndroidDeviceService(
            discovery=discovery, hardware_verifier=verifier, audit=audit,
        )
        service.devices_by_key[("ABC", "ADB")] = device
        service.verify_hardware("ABC", "ADB", "CASE-1", "TECH-1")
        verifier.verify.assert_called_once_with(device)
        audit.record.assert_called_once()
        self.assertEqual(audit.record.call_args.args[0].operation.value, "verify_hardware")

    def test_bounded_logcat_export_writes_header_and_output(self):
        adb = Mock()
        adb.capture_logcat.return_value = "01-01 log line\n"
        device = DeviceState("ABC", DeviceMode.ADB, "device", authorized=True)
        path = Path.cwd() / f"test_logcat_{uuid4().hex}.txt"
        try:
            result = AndroidDiagnosticsService(adb).capture_logcat(device, 100, path)
            content = path.read_text(encoding="utf-8")
        finally:
            path.unlink(missing_ok=True)
        self.assertTrue(result.success)
        self.assertIn("Device serial: ABC", content)
        self.assertIn("01-01 log line", content)

    def test_logcat_export_sanitizes_header_and_leaves_no_temporary_file(self):
        adb = Mock()
        adb.capture_logcat.return_value = "log line\n"
        device = DeviceState("ABC\nInjected: value", DeviceMode.ADB, "device", authorized=True)
        path = Path.cwd() / f"test_logcat_{uuid4().hex}.txt"
        try:
            AndroidDiagnosticsService(adb).capture_logcat(device, 100, path)
            content = path.read_text(encoding="utf-8")
            leftovers = list(path.parent.glob(f".{path.name}.*.tmp"))
        finally:
            path.unlink(missing_ok=True)
        self.assertIn("Device serial: ABC_Injected: value", content)
        self.assertNotIn("\nInjected: value\n", content)
        self.assertEqual(leftovers, [])

    def test_logcat_export_rejects_a_directory_destination(self):
        adb = Mock()
        adb.capture_logcat.return_value = "log line\n"
        device = DeviceState("ABC", DeviceMode.ADB, "device", authorized=True)
        with self.assertRaisesRegex(ValueError, "file path"):
            AndroidDiagnosticsService(adb).capture_logcat(device, 100, Path.cwd())

    @patch("app.pages.android_workspace.QFileDialog.getSaveFileName")
    @patch("app.pages.android_workspace.QMessageBox.warning")
    def test_logcat_export_requires_default_no_privacy_confirmation(
        self, warning, get_save_file_name,
    ):
        with patch("app.pages.android_workspace.QTimer.singleShot"):
            workspace = AndroidWorkspace()
        workspace.table.setRowCount(1)
        for column, value in enumerate(("ABC", "ADB", "device", "Pixel", "p", "d")):
            workspace.table.setItem(0, column, QTableWidgetItem(value))
        workspace.table.selectRow(0)
        workspace.case_id.setText("CASE-1")
        workspace.technician_id.setText("TECH-1")
        get_save_file_name.return_value = (str(Path.cwd() / "capture.txt"), "Text files (*.txt)")
        warning.return_value = QMessageBox.No
        workspace._start_operation = Mock()
        workspace.export_logcat()
        warning.assert_called_once()
        self.assertEqual(warning.call_args.args[-1], QMessageBox.No)
        workspace._start_operation.assert_not_called()
        workspace.close()

    def test_connection_guidance_covers_supported_states(self):
        self.assertIn("accept", AndroidDeviceService.guidance("ADB", "unauthorized"))
        self.assertIn("reconnect", AndroidDeviceService.guidance("ADB", "offline"))
        self.assertIn("identity", AndroidDeviceService.guidance("Fastboot", "fastboot"))
        self.assertIn("Samsung-authorized", AndroidDeviceService.guidance("Download", "OK"))

    def test_samsung_interfaces_for_one_phone_are_grouped(self):
        parent = "USB\\VID_04E8&PID_685D\\PHYSICAL-A"
        output = json.dumps([
            {
                "InstanceId": "USB\\VID_04E8&PID_685D&MI_02\\6&ABC&0&0002",
                "ParentInstanceId": parent,
                "FriendlyName": "SAMSUNG Mobile USB Modem #3",
                "Status": "OK",
            },
            {
                "InstanceId": "USB\\VID_04E8&PID_685D&MI_00\\6&ABC&0&0000",
                "ParentInstanceId": parent,
                "FriendlyName": "SAMSUNG Mobile USB CDC Composite Device",
                "Status": "OK",
            },
        ])
        devices = SamsungDownloadWrapper.parse_devices(output)
        reversed_devices = SamsungDownloadWrapper.parse_devices(
            json.dumps(list(reversed(json.loads(output))))
        )
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].model, "SAMSUNG Mobile USB CDC Composite Device")
        self.assertEqual(devices[0].serial, reversed_devices[0].serial)

    def test_separate_samsung_phones_remain_separate(self):
        records = []
        for suffix in ("PHYSICAL-A", "PHYSICAL-B"):
            records.extend([
                {
                    "InstanceId": f"USB\\VID_04E8&PID_685D&MI_00\\{suffix}&0000",
                    "ParentInstanceId": f"USB\\VID_04E8&PID_685D\\{suffix}",
                    "FriendlyName": "SAMSUNG Mobile USB CDC Composite Device",
                    "Status": "OK",
                },
                {
                    "InstanceId": f"USB\\VID_04E8&PID_685D&MI_02\\{suffix}&0002",
                    "ParentInstanceId": f"USB\\VID_04E8&PID_685D\\{suffix}",
                    "FriendlyName": "SAMSUNG Mobile USB Modem",
                    "Status": "OK",
                },
            ])
        devices = SamsungDownloadWrapper.parse_devices(json.dumps(records))
        self.assertEqual(len(devices), 2)
        self.assertEqual(len({device.serial for device in devices}), 2)

    def test_missing_tool_guidance_uses_process_local_directory(self):
        message = AndroidDeviceService.tool_status_message({
            "adb": None, "fastboot": None, "samsung_download": "powershell.exe",
        })
        self.assertIn("ARC3_ANDROID_PLATFORM_TOOLS", message)
        self.assertIn("$env:ARC3_ANDROID_PLATFORM_TOOLS", message)
        self.assertIn("without changing global PATH", message)
        self.assertIn("does not download or install", message)

    def test_offscreen_workspace_builds_and_f5_refreshes_once(self):
        with patch("app.pages.android_workspace.QTimer.singleShot"):
            workspace = AndroidWorkspace()
        calls = []
        workspace.refresh_devices = lambda: calls.append("refresh")
        window = QWidget()
        window.pages = QStackedWidget(window)
        window.pages.addWidget(workspace)
        self.assertTrue(refresh_visible_page(window))
        self.assertEqual(calls, ["refresh"])
        workspace.close()
        window.close()


if __name__ == "__main__":
    unittest.main()
