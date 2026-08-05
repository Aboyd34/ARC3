import json
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox, QStackedWidget, QWidget

from app.pages.windows.devices_tab import DevicesTab
from app.services.windows_device_service import WindowsDeviceService
from app.ui.phase4_enhancements import refresh_visible_page


class WindowsDeviceServiceTests(unittest.TestCase):
    def test_enumeration_normalizes_health_and_driver_metadata(self):
        runner = Mock()
        runner.return_value = Mock(
            returncode=0, stderr="", stdout=json.dumps([
                {"name": "Camera", "class": "Camera", "status": "OK",
                 "problem_code": 0, "instance_id": "USB\\CAM", "enabled": True,
                 "driver_provider": "Vendor", "driver_version": "1.2.3"},
                {"name": "Adapter", "class": "Net", "status": "Error",
                 "problem_code": 10, "instance_id": "PCI\\NET", "enabled": True},
            ]),
        )
        devices = WindowsDeviceService(runner).collect_devices()
        self.assertEqual({item["health"] for item in devices}, {"Healthy", "Needs attention"})
        self.assertEqual(next(item for item in devices if item["name"] == "Camera")["driver_version"], "1.2.3")
        command = runner.call_args.args[0]
        self.assertEqual(command[:4], ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy"])

    def test_problem_code_22_is_normalized_as_disabled(self):
        normalized = WindowsDeviceService._normalize({
            "name": "Adapter", "class": "Net", "status": "Error",
            "problem_code": 22, "instance_id": "PCI\\NET",
        })
        self.assertFalse(normalized["enabled"])
        self.assertEqual(normalized["health"], "Disabled")

    def test_hex_problem_code_22_is_normalized_as_disabled(self):
        normalized = WindowsDeviceService._normalize({
            "name": "Adapter", "class": "Net", "status": "Stopped",
            "problem_code": "0x00000016", "instance_id": "PCI\\NET",
        })
        self.assertFalse(normalized["enabled"])

    def test_invalid_primary_enumeration_uses_pnputil_xml_fallback(self):
        xml = """<PnpUtil><Device InstanceId="USB\\CAM">
            <DeviceDescription>Camera</DeviceDescription><ClassName>Camera</ClassName>
            <ManufacturerName>Vendor</ManufacturerName><Status>Started</Status>
            <ProblemCode>0</ProblemCode>
        </Device></PnpUtil>"""
        runner = Mock(side_effect=[
            Mock(returncode=0, stderr="", stdout="not-json"),
            Mock(returncode=0, stderr="", stdout=xml),
        ])
        devices = WindowsDeviceService(runner).collect_devices()
        self.assertEqual(devices[0]["instance_id"], "USB\\CAM")
        self.assertEqual(devices[0]["health"], "Healthy")
        self.assertEqual(runner.call_args.args[0][:3], [
            "pnputil.exe", "/enum-devices", "/drivers",
        ])

    def test_pnputil_details_fallback_parses_identity_and_driver(self):
        xml = """<PnpUtil><Device InstanceId="USB\\CAM">
            <DeviceDescription>Camera</DeviceDescription><ClassName>Camera</ClassName>
            <ClassGuid>{guid}</ClassGuid><ManufacturerName>Vendor</ManufacturerName>
            <Status>Started</Status><DriverName>camera.inf</DriverName>
            <MatchingDrivers><DriverName><ProviderName>Vendor</ProviderName>
            <DriverVersion>01/01/2026 1.2.3</DriverVersion>
            <Status>BestRanked/Installed</Status></DriverName></MatchingDrivers>
            <Properties>
              <Property Key="DEVPKEY_Device_IsPresent"><Value>true</Value></Property>
              <Property Key="DEVPKEY_Device_HardwareIds"><Value>USB\\VID_1234</Value></Property>
            </Properties>
        </Device></PnpUtil>"""
        runner = Mock(side_effect=[
            PermissionError("denied"), Mock(returncode=0, stderr="", stdout=xml),
        ])
        details = WindowsDeviceService(runner).collect_details("USB\\CAM")
        self.assertTrue(details["present"])
        self.assertEqual(details["hardware_ids"], "USB\\VID_1234")
        self.assertEqual(details["driver_provider"], "Vendor")
        self.assertEqual(runner.call_args.args[0][:4], [
            "pnputil.exe", "/enum-devices", "/instanceid", "USB\\CAM",
        ])

    def test_enable_disable_uses_argument_list(self):
        runner = Mock(return_value=Mock(returncode=0, stdout="done", stderr=""))
        service = WindowsDeviceService(runner)
        self.assertTrue(service.set_enabled("USB\\DEVICE", False)[0])
        self.assertEqual(runner.call_args.args[0], ["pnputil.exe", "/disable-device", "USB\\DEVICE"])

    def test_invalid_instance_id_is_rejected_without_running_command(self):
        runner = Mock()
        self.assertFalse(WindowsDeviceService(runner).set_enabled("USB\nBAD", True)[0])
        runner.assert_not_called()

    def test_details_pass_instance_id_as_separate_argument(self):
        runner = Mock(return_value=Mock(
            returncode=0, stderr="", stdout=json.dumps({
                "instance_id": "USB\\DEVICE", "present": True,
                "hardware_ids": ["USB\\VID_1234"], "class": "USB",
            }),
        ))
        details = WindowsDeviceService(runner).collect_details("USB\\DEVICE")
        command = runner.call_args.args[0]
        self.assertEqual(command[-1], "USB\\DEVICE")
        self.assertEqual(details["hardware_ids"], ["USB\\VID_1234"])

    def test_hardware_verification_requires_consistent_identity_evidence(self):
        service = WindowsDeviceService()
        service.collect_details = Mock(return_value={
            "instance_id": "USB\\DEVICE", "present": True,
            "hardware_ids": ["USB\\VID_1234"], "class": "USB",
        })
        result = service.verify_hardware("USB\\DEVICE")
        self.assertEqual(result["verification"], "Verified")
        self.assertTrue(all(result["checks"].values()))

    def test_missing_hardware_ids_requires_review(self):
        service = WindowsDeviceService()
        service.collect_details = Mock(return_value={
            "instance_id": "USB\\DEVICE", "present": True,
            "hardware_ids": [], "class": "USB",
        })
        result = service.verify_hardware("USB\\DEVICE")
        self.assertEqual(result["verification"], "Needs review")


class WindowsDeviceTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def build_tab(self):
        with patch("app.pages.windows.devices_tab.QTimer.singleShot"):
            return DevicesTab()

    def test_search_health_filter_and_sortable_table(self):
        tab = self.build_tab()
        tab._loaded([
            {"name": "Camera", "class": "Camera", "health": "Healthy", "status": "OK",
             "manufacturer": "Vendor", "driver_provider": "Vendor", "driver_version": "1",
             "driver_date": "2026", "problem_code": "", "instance_id": "USB\\CAM", "enabled": True},
            {"name": "Adapter", "class": "Net", "health": "Disabled", "status": "Disabled",
             "manufacturer": "Vendor", "driver_provider": "Vendor", "driver_version": "2",
             "driver_date": "2025", "problem_code": "", "instance_id": "PCI\\NET", "enabled": False},
        ])
        tab.search_box.setText("camera")
        self.assertEqual(tab.count_label.text(), "1 of 2 devices")
        tab.search_box.clear()
        tab.health_filter.setCurrentText("Disabled")
        self.assertEqual(tab.count_label.text(), "1 of 2 devices")
        self.assertTrue(tab.table.isSortingEnabled())
        tab.close()

    def test_state_change_confirmation_defaults_to_no(self):
        tab = self.build_tab()
        tab._loaded([{"name": "Camera", "class": "Camera", "health": "Healthy", "status": "OK",
                      "manufacturer": "V", "driver_provider": "V", "driver_version": "1",
                      "driver_date": "2026", "problem_code": "", "instance_id": "USB\\CAM", "enabled": True}])
        tab.table.selectRow(0)
        tab.service.set_enabled = Mock()
        with patch("app.pages.windows.devices_tab.QMessageBox.question", return_value=QMessageBox.No) as question:
            tab.change_selected_state(False)
        self.assertEqual(question.call_args.args[-1], QMessageBox.No)
        tab.service.set_enabled.assert_not_called()
        tab.close()

    def test_f5_refreshes_devices_once(self):
        tab = self.build_tab()
        calls = []
        tab.refresh = lambda: calls.append("refresh")
        workspace = QWidget()
        workspace.tabs = QStackedWidget(workspace)
        workspace.tabs.addWidget(tab)
        window = QWidget()
        window.pages = QStackedWidget(window)
        window.pages.addWidget(workspace)
        self.assertTrue(refresh_visible_page(window))
        self.assertEqual(calls, ["refresh"])
        window.close()

    def test_failed_refresh_clears_stale_devices(self):
        tab = self.build_tab()
        tab._loaded([{
            "name": "Camera", "class": "Camera", "health": "Healthy",
            "status": "OK", "manufacturer": "V", "driver_provider": "V",
            "driver_version": "1", "driver_date": "2026", "problem_code": "",
            "instance_id": "USB\\CAM", "enabled": True,
        }])
        with patch("app.pages.windows.devices_tab.QMessageBox.critical"):
            tab._failed("enumeration failed")
        self.assertEqual(tab.devices, [])
        self.assertEqual(tab.table.rowCount(), 0)
        self.assertEqual(tab.count_label.text(), "Device refresh failed")
        tab.close()


if __name__ == "__main__":
    unittest.main()
