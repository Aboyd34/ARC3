import json
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread, QTimer, Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QStackedWidget, QWidget

from app.main_window import MainWindow
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

    def test_pnputil_fallback_resolves_masked_published_inf(self):
        device_xml = """<PnpUtil><Device InstanceId="USB\\BOOT">
            <DeviceDescription>Android Bootloader Interface</DeviceDescription>
            <ClassName>AndroidUsbDeviceClass</ClassName>
            <ClassGuid>{android-guid}</ClassGuid><ManufacturerName>Google, Inc.</ManufacturerName>
            <Status>Disconnected</Status><DriverName>oem36.---</DriverName>
            <MatchingDrivers><DriverName>
              <OriginalName>android_general.inf</OriginalName>
              <ProviderName>Google, Inc.</ProviderName>
              <ClassGuid>{android-guid}</ClassGuid>
              <DriverVersion>08/27/2012 7.0.0.4</DriverVersion>
              <SignerName>Trusted Driver Publisher</SignerName>
              <Status>BestRanked</Status>
            </DriverName></MatchingDrivers>
        </Device></PnpUtil>"""
        drivers_xml = """<PnpUtil>
          <Driver DriverName="oem65.inf">
            <OriginalName>android_general.inf</OriginalName>
            <ProviderName>Google, Inc.</ProviderName>
            <ClassGuid>{android-guid}</ClassGuid>
            <DriverVersion>08/27/2012 7.0.0.4</DriverVersion>
            <SignerName>Trusted Driver Publisher</SignerName>
          </Driver>
          <Driver DriverName="oem37.inf">
            <OriginalName>android_winusb.inf</OriginalName>
            <ProviderName>MediaTek</ProviderName>
            <ClassGuid>{android-guid}</ClassGuid>
            <DriverVersion>08/28/2014 11.0.0.0</DriverVersion>
          </Driver>
        </PnpUtil>"""
        runner = Mock(side_effect=[
            PermissionError("denied"),
            Mock(returncode=0, stderr="", stdout=device_xml),
            Mock(returncode=0, stderr="", stdout=drivers_xml),
        ])

        details = WindowsDeviceService(runner).collect_details("USB\\BOOT")

        self.assertEqual(details["driver_inf_path"], "oem65.inf")
        self.assertEqual(runner.call_args.args[0][:2], ["pnputil.exe", "/enum-drivers"])

    def test_pnputil_fallback_reports_signed_when_signer_exists(self):
        xml = """<PnpUtil><Device InstanceId="USB\\SIGNED">
            <DeviceDescription>Signed Device</DeviceDescription><Status>Started</Status>
            <DriverName>oem42.inf</DriverName>
            <MatchingDrivers><DriverName>
              <SignerName>Microsoft Windows Hardware Compatibility Publisher</SignerName>
              <Status>BestRanked/Installed</Status>
            </DriverName></MatchingDrivers>
        </Device></PnpUtil>"""
        runner = Mock(side_effect=[
            PermissionError("denied"), Mock(returncode=0, stderr="", stdout=xml),
        ])

        details = WindowsDeviceService(runner).collect_details("USB\\SIGNED")

        self.assertTrue(details["driver_is_signed"])
        self.assertEqual(
            details["driver_signer"],
            "Microsoft Windows Hardware Compatibility Publisher",
        )

    def test_masked_inf_resolution_failure_keeps_safe_details(self):
        device_xml = """<PnpUtil><Device InstanceId="USB\\BOOT">
            <DeviceDescription>Bootloader</DeviceDescription><Status>Disconnected</Status>
            <DriverName>oem36.---</DriverName>
            <MatchingDrivers><DriverName>
              <OriginalName>android_general.inf</OriginalName>
              <ProviderName>Google, Inc.</ProviderName>
            </DriverName></MatchingDrivers>
        </Device></PnpUtil>"""
        runner = Mock(side_effect=[
            PermissionError("denied"),
            Mock(returncode=0, stderr="", stdout=device_xml),
            Mock(returncode=1, stderr="access denied", stdout=""),
        ])

        details = WindowsDeviceService(runner).collect_details("USB\\BOOT")

        self.assertEqual(details["name"], "Bootloader")
        self.assertEqual(details["driver_inf_path"], "oem36.---")

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

    @staticmethod
    def two_devices():
        return [
            {"name": "Device A", "class": "USB", "health": "Healthy", "status": "OK",
             "manufacturer": "V", "driver_provider": "V", "driver_version": "1",
             "driver_date": "2026", "problem_code": "", "instance_id": "USB\\A", "enabled": True},
            {"name": "Device B", "class": "USB", "health": "Healthy", "status": "OK",
             "manufacturer": "V", "driver_provider": "V", "driver_version": "1",
             "driver_date": "2026", "problem_code": "", "instance_id": "USB\\B", "enabled": True},
        ]

    @staticmethod
    def select_instance(tab, instance_id):
        row = next(
            row for row in range(tab.table.rowCount())
            if tab.table.item(row, 0).data(Qt.UserRole) == instance_id
        )
        tab.table.selectRow(row)

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

    def test_refresh_preserves_selected_device(self):
        tab = self.build_tab()
        devices = [
            {"name": "Camera", "class": "Camera", "health": "Healthy", "status": "OK",
             "manufacturer": "V", "driver_provider": "V", "driver_version": "1",
             "driver_date": "2026", "problem_code": "", "instance_id": "USB\\CAM", "enabled": True},
            {"name": "Adapter", "class": "Net", "health": "Healthy", "status": "OK",
             "manufacturer": "V", "driver_provider": "V", "driver_version": "2",
             "driver_date": "2026", "problem_code": "", "instance_id": "PCI\\NET", "enabled": True},
        ]
        tab._loaded(devices)
        camera_row = next(
            row for row in range(tab.table.rowCount())
            if tab.table.item(row, 0).data(Qt.UserRole) == "USB\\CAM"
        )
        tab.table.selectRow(camera_row)

        tab._loaded(list(reversed(devices)))

        self.assertEqual(tab.selected_device()["instance_id"], "USB\\CAM")
        tab.close()

    def test_details_populate_panel_and_copy_hardware_ids(self):
        tab = self.build_tab()
        details = {
            "instance_id": "USB\\CAM", "hardware_ids": ["USB\\VID_1234"],
            "driver_is_signed": True, "driver_signer": "Trusted Vendor",
        }
        with patch("app.pages.windows.devices_tab.QMessageBox.information"):
            tab._copy_loaded_hardware_ids(details)
        self.assertIn("Driver Is Signed: True", tab.details_panel.toPlainText())
        self.assertEqual(QApplication.clipboard().text(), "USB\\VID_1234")
        tab.close()

    def test_stale_details_callback_does_not_update_panel(self):
        tab = self.build_tab()
        tab._loaded(self.two_devices())
        self.select_instance(tab, "USB\\A")
        with patch.object(tab, "_start_action") as start_action:
            tab.show_selected_details()
        callback = start_action.call_args.args[1]
        self.select_instance(tab, "USB\\B")

        callback({"instance_id": "USB\\A", "hardware_ids": ["A-ID"]})

        self.assertEqual(tab.details_panel.toPlainText(), "")
        self.assertIsNone(tab.selected_details)
        tab.close()

    def test_stale_copy_callback_does_not_copy_hardware_ids(self):
        tab = self.build_tab()
        tab._loaded(self.two_devices())
        self.select_instance(tab, "USB\\A")
        QApplication.clipboard().setText("unchanged")
        with patch.object(tab, "_start_action") as start_action:
            tab.copy_hardware_ids()
        callback = start_action.call_args.args[1]
        self.select_instance(tab, "USB\\B")

        with patch("app.pages.windows.devices_tab.QMessageBox.information") as information:
            callback({"instance_id": "USB\\A", "hardware_ids": ["A-ID"]})

        self.assertEqual(QApplication.clipboard().text(), "unchanged")
        information.assert_not_called()
        tab.close()

    def test_stale_verification_callback_does_not_open_dialog(self):
        tab = self.build_tab()
        tab._loaded(self.two_devices())
        self.select_instance(tab, "USB\\A")
        with patch.object(tab, "_start_action") as start_action:
            tab.verify_selected_hardware()
        callback = start_action.call_args.args[1]
        self.select_instance(tab, "USB\\B")

        with patch("app.pages.windows.devices_tab.QMessageBox.information") as information:
            callback({"verification": "Verified", "message": "A", "checks": {}, "details": {}})

        information.assert_not_called()
        tab.close()

    def test_stale_export_details_callback_does_not_prompt_or_export(self):
        tab = self.build_tab()
        tab._loaded(self.two_devices())
        self.select_instance(tab, "USB\\A")
        tab.service.export_driver = Mock()
        with patch.object(tab, "_start_action") as start_action:
            tab.export_selected_driver()
        callback = start_action.call_args.args[1]
        self.select_instance(tab, "USB\\B")

        with patch(
            "app.pages.windows.devices_tab.QFileDialog.getExistingDirectory",
            return_value="C:\\Driver Export",
        ) as export_dialog:
            callback({"instance_id": "USB\\A", "driver_inf_path": "oem42.inf"})

        export_dialog.assert_not_called()
        tab.service.export_driver.assert_not_called()
        self.assertIsNone(tab.pending_action)
        tab.close()

    def test_driver_export_waits_for_details_thread_to_finish(self):
        tab = self.build_tab()
        tab._loaded([self.two_devices()[0]])
        self.select_instance(tab, "USB\\A")
        tab.action_thread = Mock()
        tab.service.export_driver = Mock()
        with patch(
            "app.pages.windows.devices_tab.QFileDialog.getExistingDirectory",
            return_value="C:\\Driver Export",
        ), patch.object(tab, "_start_action") as start_action:
            tab._choose_driver_export({
                "instance_id": "USB\\A", "driver_inf_path": "oem42.inf",
            })

            start_action.assert_not_called()
            self.assertIsNotNone(tab.pending_action)
            tab.action_thread = None
            tab._start_pending_action()

        start_action.assert_called_once()
        tab.close()

    def test_queued_driver_export_is_discarded_after_selection_changes(self):
        tab = self.build_tab()
        tab._loaded(self.two_devices())
        self.select_instance(tab, "USB\\A")
        tab.action_thread = Mock()
        with patch(
            "app.pages.windows.devices_tab.QFileDialog.getExistingDirectory",
            return_value="C:\\Driver Export",
        ):
            tab._choose_driver_export({
                "instance_id": "USB\\A", "driver_inf_path": "oem42.inf",
            })
        self.select_instance(tab, "USB\\B")
        tab.action_thread = None

        with patch.object(tab, "_start_action") as start_action:
            tab._start_pending_action()

        start_action.assert_not_called()
        self.assertIsNone(tab.pending_action)
        tab.close()

class MainWindowLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def build_window():
        with patch.object(MainWindow, "build_interface"), patch.object(
            MainWindow, "restore_window_geometry",
        ):
            return MainWindow()

    def test_close_waits_for_running_child_thread(self):
        window = self.build_window()
        window.show()
        self.app.processEvents()
        thread = QThread(window)
        thread.start()
        self.assertTrue(thread.isRunning())

        self.assertFalse(window.close())
        self.assertTrue(window.isVisible())
        self.assertIn("Waiting for background", window.statusBar().currentMessage())

        thread.quit()
        self.assertTrue(thread.wait(2000))
        with patch.object(QTimer, "singleShot", side_effect=lambda _, callback: callback()):
            window._close_when_workers_finish()
        self.app.processEvents()
        self.assertFalse(window.isVisible())

    def test_close_tracks_thread_started_during_shutdown(self):
        window = self.build_window()
        window.show()
        self.app.processEvents()
        first_thread = QThread(window)
        second_thread = QThread(window)
        first_thread.start()

        self.assertFalse(window.close())
        second_thread.start()
        first_thread.quit()
        self.assertTrue(first_thread.wait(2000))
        window._close_when_workers_finish()

        second_thread.quit()
        self.assertTrue(second_thread.wait(2000))
        with patch.object(QTimer, "singleShot", side_effect=lambda _, callback: callback()):
            window._close_when_workers_finish()
        self.app.processEvents()
        self.assertFalse(window.isVisible())


if __name__ == "__main__":
    unittest.main()
